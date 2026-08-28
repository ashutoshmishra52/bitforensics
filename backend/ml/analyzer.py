from __future__ import annotations

import json
import math
import uuid
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

from backend.database.db import (
    Anomaly, Cluster, Correlation, Lead, Transaction,
    deserialize_addresses, serialize_addresses,
)
from backend.ml.typology import classify_group, classify_tx, unique_title
from backend.models.schemas import AnomalyResult, ClusterMember, InvestigativeLead

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / "isolation_forest.joblib"
SCALER_PATH = MODEL_DIR / "feature_scaler.joblib"

FEATURE_COLS = [
    "log_amount", "log_fee", "fee_ratio", "input_count", "output_count",
    "io_ratio", "has_ip", "hour", "is_p2sh", "foreign_geo", "amount_z",
]

# Store Isolation Forest hits (UI paginates). Cap keeps analysis fast on 100k.
MAX_ANOMALIES_STORE = 2500
MAX_ANOMALY_LEADS = 120
MAX_CLUSTER_MEMBERS = 120
MIN_AMOUNT_BTC = 1e-8  # ignore dust / zero-value rows in alerts


def _load_feature_matrix(db: Session):
    """Build features from DB columns only (no JSON address parsing) — fast for 100k+."""
    rows = db.query(
        Transaction.txid,
        Transaction.amount_btc,
        Transaction.fee_btc,
        Transaction.input_count,
        Transaction.output_count,
        Transaction.src_ip,
        Transaction.dst_ip,
        Transaction.timestamp,
        Transaction.script_type,
        Transaction.geo_country,
        Transaction.asn,
    ).all()
    if not rows:
        return None, [], {}

    n = len(rows)
    amounts = np.array([r.amount_btc or 0.0 for r in rows], dtype=np.float64)
    fees = np.array([r.fee_btc or 0.0 for r in rows], dtype=np.float64)
    in_c = np.array([r.input_count or 0 for r in rows], dtype=np.float64)
    out_c = np.array([r.output_count or 0 for r in rows], dtype=np.float64)
    mean_amt = float(amounts.mean())
    std_amt = float(amounts.std()) or 1.0

    hours = np.array([r.timestamp.hour if r.timestamp else 12 for r in rows], dtype=np.float64)
    has_ip = np.array([1.0 if (r.src_ip or r.dst_ip) else 0.0 for r in rows])
    is_p2sh = np.array([1.0 if (r.script_type or "") == "P2SH" else 0.0 for r in rows])
    foreign = np.array([
        1.0 if r.geo_country and r.geo_country not in ("LOCAL", "UNK", "") else 0.0
        for r in rows
    ])

    with np.errstate(divide="ignore", invalid="ignore"):
        fee_ratio = np.where(amounts > 0, fees / amounts, 0.0)
        io_ratio = np.where(in_c > 0, out_c / in_c, out_c)

    X = np.column_stack([
        np.log1p(np.maximum(amounts, 0)),
        np.log1p(np.maximum(fees, 0)),
        fee_ratio,
        in_c,
        out_c,
        io_ratio,
        has_ip,
        hours,
        is_p2sh,
        foreign,
        (amounts - mean_amt) / std_amt,
    ])

    txids = [r.txid for r in rows]
    lookup = {r.txid: r for r in rows}
    extras = {
        "amount_btc": amounts,
        "fee_btc": fees,
        "fee_ratio": fee_ratio,
        "input_count": in_c,
        "output_count": out_c,
        "io_ratio": io_ratio,
        "has_ip": has_ip,
        "is_p2sh": is_p2sh,
        "foreign_geo": foreign,
        "amount_z": (amounts - mean_amt) / std_amt,
    }
    return X, txids, lookup, extras


def _to_confidence(score: float, ranks: dict | None = None, scores: np.ndarray | None = None) -> float:
    if ranks is not None:
        # Precomputed: higher anomaly score → higher confidence
        return ranks.get(score, 50.0)
    if scores is None or len(scores) == 0:
        return 50.0
    pct = float((scores <= score).mean() * 100)
    return round(min(max(pct, 8), 99), 1)


def _confidence_map(scores: np.ndarray) -> dict:
    """O(n log n) once instead of O(n²) per-anomaly percentile."""
    if len(scores) == 0:
        return {}
    order = np.argsort(scores)
    n = len(scores)
    out = {}
    for rank, idx in enumerate(order):
        pct = round(min(max((rank + 1) / n * 100, 8), 99), 1)
        out[float(scores[idx])] = pct
    return out


def detect_anomalies(db: Session) -> list[AnomalyResult]:
    db.query(Anomaly).delete()
    db.commit()

    loaded = _load_feature_matrix(db)
    if loaded[0] is None:
        return []
    X, txids, lookup, extras = loaded
    n = len(txids)
    if n < 10:
        return []

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    # Cap training size on large dumps for responsive analysis
    if n >= 50000:
        contamination = 0.05
        n_estimators = 60
        max_samples = min(6000, n)
    elif n >= 10000:
        contamination = 0.07
        n_estimators = 80
        max_samples = min(5000, n)
    else:
        contamination = 0.10
        n_estimators = 100
        max_samples = n

    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        max_samples=max_samples,
        random_state=42,
        n_jobs=-1,
        bootstrap=False,
    )
    flags = model.fit_predict(Xs)
    scores = -model.decision_function(Xs)

    amounts = extras["amount_btc"]
    positive = amounts > MIN_AMOUNT_BTC
    flags = np.where(~positive, 1, flags)

    try:
        joblib.dump(model, MODEL_PATH, compress=0)
        joblib.dump({
            "features": FEATURE_COLS,
            "contamination": contamination,
            "n": n,
            "n_estimators": n_estimators,
        }, SCALER_PATH, compress=0)
    except Exception:
        pass

    anom_idx = np.where(flags == -1)[0]
    if len(anom_idx) == 0:
        return []
    store_n = min(MAX_ANOMALIES_STORE, len(anom_idx))
    order = anom_idx[np.argsort(-scores[anom_idx])][:store_n]
    anomaly_scores = scores[order]
    conf_map = _confidence_map(anomaly_scores)

    found = []
    batch = []
    for i in order:
        if float(extras["amount_btc"][i]) <= MIN_AMOUNT_BTC:
            continue
        tx = lookup[txids[i]]
        row = {k: float(extras[k][i]) for k in extras}
        sc = float(scores[i])
        reasons = _reasons(row, tx, sc, anomaly_scores)
        severity = _severity(sc, row["amount_btc"], anomaly_scores)
        conf = _to_confidence(sc, ranks=conf_map)
        result = AnomalyResult(
            txid=txids[i],
            anomaly_score=round(sc, 4),
            confidence=conf,
            is_anomaly=True,
            reasons=reasons,
            severity=severity,
            amount_btc=row["amount_btc"],
            timestamp=tx.timestamp,
        )
        found.append(result)
        batch.append(Anomaly(
            txid=result.txid, anomaly_score=result.anomaly_score, confidence=conf,
            is_anomaly=1, reasons=json.dumps(reasons), severity=severity,
            amount_btc=result.amount_btc, timestamp=result.timestamp,
        ))

    if batch:
        db.bulk_save_objects(batch)
        db.commit()
    return found


def _reasons(row, tx, score, anomaly_scores) -> list[str]:
    """Real investigative reason paragraphs (pattern / scam-risk language, not proof)."""
    out = []
    amt = row["amount_btc"]
    fee = row["fee_btc"]
    if amt <= MIN_AMOUNT_BTC:
        return ["Skipped — no transferable amount on record."]
    med = float(np.median(anomaly_scores)) if len(anomaly_scores) else score
    inn = int(row["input_count"] or 0)
    outn = int(row["output_count"] or 0)

    # Pattern-first narrative
    if outn >= 10 and amt > 0:
        out.append(
            f"Mixer / tumbler-style pattern: this transaction fans out to {outn} outputs "
            f"({amt:.4f} BTC total). Scammers and launderers often split funds across many "
            f"wallets to break the trail and cash out through separate hops."
        )
    elif outn >= 5 and amt >= 0.05:
        out.append(
            f"Peel-chain style layering: {outn} outputs from a {amt:.4f} BTC flow. "
            f"Typical peel behaviour leaves successive leftovers while the main value moves "
            f"forward — a common obfuscation pattern in ransomware and darknet cash-outs."
        )
    elif inn >= 8 and outn <= 3:
        out.append(
            f"Consolidation pattern: {inn} inputs collapse into {outn} output(s) "
            f"({amt:.4f} BTC). This often marks pooling before an exchange deposit or "
            f"a final cash-out step after earlier mixing."
        )
    elif inn >= 6 and outn >= 6:
        out.append(
            f"Pass-through hop: high fan-in ({inn}) and high fan-out ({outn}) together. "
            f"Funds appear to enter and leave quickly — consistent with intermediary "
            f"wallets used in multi-hop scam pipelines."
        )
    elif amt >= 50:
        out.append(
            f"Whale / high-value move: {amt:.4f} BTC is far above typical traffic in this dump. "
            f"Large single transfers deserve review for ransomware payouts, OTC deals, "
            f"or staged cash-outs."
        )
    elif amt > 0 and amt < 0.0005 and (inn >= 4 or outn >= 6):
        out.append(
            f"Dusting / probe pattern: tiny amount ({amt:.8f} BTC) with {inn} inputs / {outn} outputs. "
            f"Dusting is used to tag wallets for tracking or to spam address clusters."
        )

    if row["amount_z"] > 2.5 and not any("Whale" in x or "high-value" in x for x in out):
        out.append(
            f"Amount {amt:.4f} BTC is statistically extreme versus this dataset "
            f"(z-score {row['amount_z']:.1f}). Unusual size alone is a priority triage signal."
        )
    elif amt > 1 and not out:
        out.append(f"Elevated transfer size: {amt:.4f} BTC relative to normal traffic in this dump.")

    if row["fee_ratio"] > 0.05:
        out.append(
            f"Urgent-fee behaviour: fee is {row['fee_ratio']:.2%} of the amount "
            f"({fee:.6f} BTC). High fee pressure often means the actor wants confirmation "
            f"fast — common in exit hops after a scam."
        )
    elif fee > 0.001 and 0 < amt < 0.01:
        out.append(
            f"Fee ({fee:.6f} BTC) is high relative to a small transfer ({amt:.6f} BTC), "
            f"which can indicate priority routing of residual / probe funds."
        )

    if row["is_p2sh"]:
        out.append(
            "Uses P2SH scripting. Not criminal by itself, but often appears in multi-sig / "
            "complex spend paths that investigators track alongside fan-out patterns."
        )
    if getattr(tx, "timestamp", None) and tx.timestamp.hour < 5 and amt >= 0.5:
        out.append(
            f"Off-hours burst at {tx.timestamp.strftime('%H:%M')} UTC with meaningful value. "
            f"Overnight timing plus size is a classic layering / cash-out window."
        )
    if row["foreign_geo"]:
        out.append(
            f"Cross-border network context: geo {tx.geo_country}, ASN {tx.asn}. "
            f"When combined with mixing or peel shapes, foreign hops support a laundering narrative."
        )
    if row["has_ip"] == 0:
        out.append(
            "No src/dst IP on this record — blockchain-only view. Pattern still stands from "
            "amount and input/output shape; network correlation cannot confirm the hop."
        )
    elif row["has_ip"] and (tx.src_ip or tx.dst_ip):
        out.append(
            f"Network link present ({tx.src_ip or '—'} → {tx.dst_ip or '—'}). "
            f"IP ↔ TX correlation strengthens the case that this chain activity matches observed traffic."
        )

    if score >= med:
        out.append(
            f"Isolation Forest ranks this among the strongest outliers in the dump "
            f"(model score {score:.3f}). The model reacts to the combined feature shape — "
            f"not a single rule — which is why it is treated as a ranked investigative lead."
        )

    # Always return up to 5 crisp paragraphs
    cleaned = [x.strip() for x in out if x and x.strip()]
    if not cleaned:
        cleaned = [
            "Statistically unusual versus the rest of this dataset. "
            "Treat as a triage lead and verify wallets, timing, and counterparties before escalating."
        ]
    return cleaned[:5]


def _severity(score, amount, anomaly_scores) -> str:
    if len(anomaly_scores):
        p90 = float(np.percentile(anomaly_scores, 90))
        p70 = float(np.percentile(anomaly_scores, 70))
        med = float(np.median(anomaly_scores))
    else:
        p90, p70, med = 0.7, 0.5, 0.4
    if score >= p90 or amount > 10:
        return "CRITICAL"
    if score >= p70 or amount > 2:
        return "HIGH"
    if score >= med:
        return "MEDIUM"
    return "LOW"


def cluster_entities(db: Session) -> list[ClusterMember]:
    db.query(Cluster).delete()
    db.commit()

    # Prefer wallet clustering when addresses exist (capped sample for speed)
    sample = (
        db.query(Transaction)
        .order_by(Transaction.amount_btc.desc())
        .limit(6000)
        .all()
    )
    address_stats = defaultdict(lambda: {"volume": 0.0, "tx_count": 0, "ips": set(), "peers": set()})
    for tx in sample:
        addrs = set(deserialize_addresses(tx.input_addresses)) | set(deserialize_addresses(tx.output_addresses))
        if not addrs:
            continue
        for addr in addrs:
            address_stats[addr]["volume"] += tx.amount_btc or 0
            address_stats[addr]["tx_count"] += 1
            if tx.src_ip:
                address_stats[addr]["ips"].add(tx.src_ip)
            if tx.dst_ip:
                address_stats[addr]["ips"].add(tx.dst_ip)
            address_stats[addr]["peers"].update(addrs - {addr})

    if len(address_stats) >= 2:
        return _wallet_kmeans(db, address_stats)

    return _tx_behavior_clusters(db)


def _wallet_kmeans(db, address_stats) -> list[ClusterMember]:
    addresses = list(address_stats.keys())
    X = StandardScaler().fit_transform([
        [s["volume"], s["tx_count"], len(s["ips"]), len(s["peers"])]
        for s in address_stats.values()
    ])
    k = min(8, max(2, len(addresses) // 20))
    labels = MiniBatchKMeans(n_clusters=k, random_state=42, batch_size=1024, n_init=3).fit_predict(X)
    return _persist_members(db, addresses, labels, address_stats)


def _tx_behavior_clusters(db: Session) -> list[ClusterMember]:
    """Cluster a sample of transactions by amount/fee/counts — O(n) with MiniBatchKMeans."""
    rows = db.query(
        Transaction.txid, Transaction.amount_btc, Transaction.fee_btc,
        Transaction.input_count, Transaction.output_count, Transaction.timestamp,
        Transaction.src_ip, Transaction.dst_ip,
    ).limit(30000).all()
    if len(rows) < 50:
        return []

    # Prefer high-value / high-fanout for clustering — skip zero-amount rows
    scored = [
        r for r in rows
        if (r.amount_btc or 0) > MIN_AMOUNT_BTC
    ]
    scored = sorted(
        scored,
        key=lambda r: (r.amount_btc or 0) + 0.01 * (r.output_count or 0),
        reverse=True,
    )[:8000]
    if len(scored) < 50:
        return []

    feats = []
    for r in scored:
        amt = r.amount_btc or 0
        fee = r.fee_btc or 0
        feats.append([
            math.log1p(amt), math.log1p(fee),
            (fee / amt) if amt else 0,
            r.input_count or 0, r.output_count or 0,
            r.timestamp.hour if r.timestamp else 12,
        ])
    X = StandardScaler().fit_transform(feats)
    k = 6
    labels = MiniBatchKMeans(n_clusters=k, random_state=42, batch_size=2048, n_init=3).fit_predict(X)

    by_label = defaultdict(list)
    for r, lab in zip(scored, labels):
        by_label[int(lab)].append(r)

    members = []
    batch = []
    for lab, group in by_label.items():
        group = [t for t in group if (t.amount_btc or 0) > MIN_AMOUNT_BTC]
        if len(group) < 8:
            continue
        vol = sum(t.amount_btc or 0 for t in group)
        typ = classify_group([
            {
                "amount_btc": t.amount_btc, "fee_btc": t.fee_btc,
                "input_count": t.input_count, "output_count": t.output_count,
            }
            for t in group
        ])
        kind = typ["label"]
        top = sorted(group, key=lambda t: t.amount_btc or 0, reverse=True)[:12]
        for t in top:
            if (t.amount_btc or 0) <= MIN_AMOUNT_BTC:
                continue
            m = ClusterMember(
                address=t.txid, cluster_id=lab, entity_type=kind,
                total_volume_btc=round(t.amount_btc or 0, 6),
                transaction_count=1,
                linked_ips=[ip for ip in [t.src_ip, t.dst_ip] if ip],
            )
            members.append(m)
            batch.append(Cluster(
                address=m.address, cluster_id=m.cluster_id, entity_type=m.entity_type,
                total_volume_btc=m.total_volume_btc, transaction_count=m.transaction_count,
                linked_ips=serialize_addresses(m.linked_ips),
            ))
            if len(members) >= MAX_CLUSTER_MEMBERS:
                break
        if len(members) >= MAX_CLUSTER_MEMBERS:
            break

    if batch:
        db.bulk_save_objects(batch)
        db.commit()
    return members


def _persist_members(db, addresses, labels, stats) -> list[ClusterMember]:
    members, batch = [], []
    for addr, label in zip(addresses, labels):
        s = stats[addr]
        kind = _wallet_type(int(label), s)
        m = ClusterMember(
            address=addr, cluster_id=int(label), entity_type=kind,
            total_volume_btc=round(s["volume"], 6),
            transaction_count=s["tx_count"], linked_ips=sorted(s["ips"]),
        )
        members.append(m)
        batch.append(Cluster(
            address=addr, cluster_id=int(label), entity_type=kind,
            total_volume_btc=m.total_volume_btc, transaction_count=m.transaction_count,
            linked_ips=serialize_addresses(m.linked_ips),
        ))
    db.bulk_save_objects(batch)
    db.commit()
    return sorted(members, key=lambda m: (m.cluster_id, -m.total_volume_btc))[:MAX_CLUSTER_MEMBERS]


def _wallet_type(label, s) -> str:
    if s["tx_count"] > 5 and len(s["peers"]) > 8:
        return "Possible mixer"
    if s["volume"] > 10:
        return "High volume"
    if len(s["ips"]) > 2:
        return "Multi-node"
    return "Wallet group"


def generate_leads(db: Session, anomalies, clusters) -> list[InvestigativeLead]:
    db.query(Lead).delete()
    db.commit()
    leads = []

    usable = [a for a in anomalies if (a.amount_btc or 0) > MIN_AMOUNT_BTC]
    usable = sorted(usable, key=lambda a: a.anomaly_score or 0, reverse=True)[:MAX_ANOMALY_LEADS]
    by_txid = {}
    ids = [a.txid for a in usable]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for t in db.query(Transaction).filter(Transaction.txid.in_(chunk)).all():
            by_txid[t.txid] = t

    for a in usable:
        tx = by_txid.get(a.txid)
        addrs, ips = [], []
        if tx:
            addrs = deserialize_addresses(tx.input_addresses) + deserialize_addresses(tx.output_addresses)
            ips = [ip for ip in [tx.src_ip, tx.dst_ip] if ip]
        boost = 20 if a.severity == "CRITICAL" else 10 if a.severity == "HIGH" else 0
        score = min(a.anomaly_score * 100 + boost, 100)
        inn = tx.input_count if tx else 0
        outn = tx.output_count if tx else 0
        hour = tx.timestamp.hour if tx and tx.timestamp else 12
        typ = classify_tx(a.amount_btc, tx.fee_btc if tx else 0, inn, outn, hour)
        leads.append(InvestigativeLead(
            lead_id=f"L-{uuid.uuid4().hex[:8].upper()}",
            priority=a.severity, score=round(score, 1), confidence=a.confidence,
            title=unique_title(typ, a.txid),
            summary=(
                f"{typ['label']}: Isolation Forest scored {a.amount_btc:.4f} BTC "
                f"(confidence {a.confidence}%). {typ['why']} "
                + (a.reasons[0] if a.reasons else "")
            ),
            evidence=a.reasons, related_txids=[a.txid],
            related_addresses=addrs[:10], related_ips=ips, lead_type="Anomaly Detection",
        ))

    groups = defaultdict(list)
    for c in clusters:
        if c.cluster_id >= 0:
            groups[c.cluster_id].append(c)

    for cid, group in groups.items():
        group = [m for m in group if (m.total_volume_btc or 0) > MIN_AMOUNT_BTC]
        if len(group) < 2:
            continue
        vol = sum(m.total_volume_btc for m in group)
        if vol <= MIN_AMOUNT_BTC:
            continue
        ips = {ip for m in group for ip in m.linked_ips}
        conf = round(min(40 + len(group) * 4 + min(vol, 20), 92), 1)
        looks_like_txid = all(len(m.address) >= 32 for m in group[:3])
        typ = classify_group([
            {"amount_btc": m.total_volume_btc, "outputs": 8 if "mix" in (m.entity_type or "").lower() else 2}
            for m in group
        ])
        typ["n"] = len(group)
        typ["label"] = group[0].entity_type or typ["label"]
        title = unique_title(typ) if looks_like_txid else (
            f"{group[0].entity_type}: {len(group)} linked wallets"
        )
        peak = max((m.total_volume_btc or 0) for m in group)
        related_tx = [m.address for m in group[:10]] if looks_like_txid else []
        related_wallets = [] if looks_like_txid else [m.address for m in group[:10]]
        # Skip full-table wallet→txid scan (too slow on 100k); TX cluster already has ids
        leads.append(InvestigativeLead(
            lead_id=f"L-{uuid.uuid4().hex[:6].upper()}",
            priority="HIGH" if vol > 5 or len(group) > 10 else "MEDIUM",
            score=round(min(48 + min(peak, 40) + len(group) * 1.2 + (8 if "mix" in title.lower() else 0), 96), 1),
            confidence=conf,
            title=title,
            summary=(
                f"{group[0].entity_type}. {len(group)} linked records, "
                f"peak {peak:.2f} BTC, combined {vol:.2f} BTC. {typ['why']}"
            ),
            evidence=[
                (
                    f"{group[0].entity_type} pattern across {len(group)} linked records. "
                    f"{typ.get('why') or 'Entities share similar volume and connectivity features.'}"
                ),
                f"Peak amount in the group is {peak:.4f} BTC; combined volume {vol:.4f} BTC.",
                f"Shared network context: {len(ips)} distinct IP(s) across the cluster.",
                (
                    "MiniBatchKMeans placed these entities in the same behavioural bucket — "
                    "review as a coordinated set, not isolated one-off payments."
                ),
                (
                    "This is an investigative cluster lead (possible scam/laundering pipeline), "
                    "not automatic proof of crime."
                ),
            ],
            related_txids=related_tx,
            related_addresses=related_wallets,
            related_ips=sorted(ips)[:10],
            lead_type="Entity Clustering",
        ))

    for c in db.query(Correlation).order_by(Correlation.correlation_score.desc()).limit(5):
        if (c.correlation_score or 0) < 0.5 or (not c.src_ip and not c.dst_ip):
            continue
        addrs = deserialize_addresses(c.wallet_addresses)
        conf = round((c.correlation_score or 0) * 85, 1)
        leads.append(InvestigativeLead(
            lead_id=f"L-{uuid.uuid4().hex[:6].upper()}",
            priority="MEDIUM", score=round(c.correlation_score * 80, 1), confidence=conf,
            title=f"Network link on {c.txid[:16]}...",
            summary=f"Correlated network observations with blockchain data (score {c.correlation_score:.2f}).",
            evidence=[
                f"Correlation score: {c.correlation_score}",
                f"Source IP: {c.src_ip or 'n/a'}",
                f"Destination IP: {c.dst_ip or 'n/a'}",
            ],
            related_txids=[c.txid], related_addresses=addrs[:10],
            related_ips=[ip for ip in [c.src_ip, c.dst_ip] if ip],
            lead_type="Network Correlation",
        ))

    leads.sort(key=lambda l: l.score, reverse=True)
    batch = [
        Lead(
            lead_id=l.lead_id, priority=l.priority, score=l.score, confidence=l.confidence,
            title=l.title, summary=l.summary, evidence=json.dumps(l.evidence),
            related_txids=json.dumps(l.related_txids),
            related_addresses=json.dumps(l.related_addresses),
            related_ips=json.dumps(l.related_ips), lead_type=l.lead_type,
        )
        for l in leads
    ]
    db.bulk_save_objects(batch)
    db.commit()
    return leads


def run_full_analysis(db: Session) -> dict:
    anomalies = detect_anomalies(db)
    clusters = cluster_entities(db)
    leads = generate_leads(db, anomalies, clusters)
    result = {
        "anomalies": len(anomalies),
        "clusters": len({c.cluster_id for c in clusters if c.cluster_id >= 0}),
        "leads": len(leads),
        "model": "IsolationForest+MiniBatchKMeans",
        "model_saved": str(MODEL_PATH),
    }
    # Archive alerts only: JSON file with datetime + optional PostgreSQL
    try:
        from backend.database.postgres_alerts import write_alerts_export
        result["alert_export"] = write_alerts_export(leads, meta={
            "model": result["model"],
            "anomalies": result["anomalies"],
            "clusters": result["clusters"],
            "leads": result["leads"],
        }, db=db)
    except Exception as e:
        result["alert_export"] = {"error": str(e)}
    return result
