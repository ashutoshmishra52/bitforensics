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
from backend.models.schemas import AnomalyResult, ClusterMember, InvestigativeLead

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / "isolation_forest.joblib"
SCALER_PATH = MODEL_DIR / "feature_scaler.joblib"

FEATURE_COLS = [
    "log_amount", "log_fee", "fee_ratio", "input_count", "output_count",
    "io_ratio", "has_ip", "hour", "is_p2sh", "foreign_geo", "amount_z",
]

# Cap stored anomalies — enough to not miss strong cases, still fast in UI
MAX_ANOMALIES_STORE = 400
MAX_CLUSTER_MEMBERS = 100
MAX_ALERTS_FROM_ANOMALIES = 40
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


def _to_confidence(score: float, scores: np.ndarray) -> float:
    if len(scores) == 0:
        return 50.0
    pct = float((scores <= score).mean() * 100)
    return round(min(max(pct, 8), 99), 1)


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

    # Catch more outliers on large dumps without making analysis slow
    if n >= 50000:
        contamination = 0.06
        n_estimators = 100
        max_samples = min(12000, n)
    elif n >= 10000:
        contamination = 0.07
        n_estimators = 120
        max_samples = min(10000, n)
    else:
        contamination = 0.10
        n_estimators = 150
        max_samples = n

    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        max_samples=max_samples,
        random_state=42,
        n_jobs=-1,
    )
    flags = model.fit_predict(Xs)
    scores = -model.decision_function(Xs)

    amounts = extras["amount_btc"]
    positive = amounts > MIN_AMOUNT_BTC

    # Extreme cases — only when there is a real BTC amount
    extra_mask = positive & (
        (extras["amount_z"] > 2.8)
        | ((extras["fee_ratio"] > 0.06) & (amounts > MIN_AMOUNT_BTC))
        | ((extras["output_count"] >= 12) & (amounts > 0.001))
        | ((extras["input_count"] >= 10) & (amounts > 0.5))
    )
    flags = np.where(extra_mask, -1, flags)
    # Never alert on zero / empty amount transactions
    flags = np.where(~positive, 1, flags)

    joblib.dump(model, MODEL_PATH)
    joblib.dump({
        "features": FEATURE_COLS,
        "contamination": contamination,
        "n": n,
        "n_estimators": n_estimators,
    }, SCALER_PATH)

    anom_idx = np.where(flags == -1)[0]
    if len(anom_idx) == 0:
        return []
    order = anom_idx[np.argsort(-scores[anom_idx])][:MAX_ANOMALIES_STORE]
    anomaly_scores = scores[order]

    found = []
    batch = []
    for i in order:
        if float(extras["amount_btc"][i]) <= MIN_AMOUNT_BTC:
            continue
        tx = lookup[txids[i]]
        row = {k: float(extras[k][i]) for k in extras}
        reasons = _reasons(row, tx, float(scores[i]), anomaly_scores)
        severity = _severity(float(scores[i]), row["amount_btc"], anomaly_scores)
        conf = _to_confidence(float(scores[i]), anomaly_scores)
        result = AnomalyResult(
            txid=txids[i],
            anomaly_score=round(float(scores[i]), 4),
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
    out = []
    amt = row["amount_btc"]
    fee = row["fee_btc"]
    if amt <= MIN_AMOUNT_BTC:
        return ["Skipped — no transferable amount on record"]
    med = float(np.median(anomaly_scores)) if len(anomaly_scores) else score

    if row["amount_z"] > 2.5:
        out.append(f"Amount {amt:.6f} BTC is much higher than typical transactions in this dataset")
    elif amt > 1:
        out.append(f"Large transfer: {amt:.6f} BTC")
    if row["fee_ratio"] > 0.05:
        out.append(f"Unusually high fee ratio ({row['fee_ratio']:.2%} of amount)")
    elif fee > 0.001 and 0 < amt < 0.01:
        out.append(f"Fee ({fee:.6f} BTC) is high relative to a small transfer")
    if row["output_count"] >= 10 and amt > 0:
        out.append(f"High fan-out: {int(row['output_count'])} outputs — mixing / peeling pattern")
    if row["input_count"] >= 8 and amt > 0:
        out.append(f"Many inputs ({int(row['input_count'])}) — consolidation pattern")
    if row["io_ratio"] >= 5 and row["output_count"] >= 5 and amt > 0:
        out.append("Outputs greatly exceed inputs — distribution pattern")
    if row["is_p2sh"]:
        out.append("Uses P2SH script type")
    if getattr(tx, "timestamp", None) and tx.timestamp.hour < 5:
        out.append(f"Occurred at {tx.timestamp.strftime('%H:%M')} UTC (overnight window)")
    if row["has_ip"] == 0:
        out.append("No network IP metadata on this record")
    if row["foreign_geo"]:
        out.append(f"Foreign network origin ({tx.geo_country}, ASN {tx.asn})")
    if score >= med:
        out.append(f"Isolation Forest ranked this among top outliers (score {score:.3f})")
    return out or ["Statistically unusual compared to the rest of the dataset"]


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

    # Prefer wallet clustering when addresses exist (sample for speed)
    sample = db.query(Transaction).limit(15000).all()
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
        kind = "Possible mixing pattern" if any((t.output_count or 0) >= 10 for t in group) else (
            "High-volume pattern" if vol / len(group) > 1 else "Similar behavior group"
        )
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

    for a in anomalies[:MAX_ALERTS_FROM_ANOMALIES]:
        if (a.amount_btc or 0) <= MIN_AMOUNT_BTC:
            continue
        tx = db.query(Transaction).filter(Transaction.txid == a.txid).first()
        addrs, ips = [], []
        if tx:
            addrs = deserialize_addresses(tx.input_addresses) + deserialize_addresses(tx.output_addresses)
            ips = [ip for ip in [tx.src_ip, tx.dst_ip] if ip]
        boost = 20 if a.severity == "CRITICAL" else 10 if a.severity == "HIGH" else 0
        score = min(a.anomaly_score * 100 + boost, 100)
        leads.append(InvestigativeLead(
            lead_id=f"L-{uuid.uuid4().hex[:6].upper()}",
            priority=a.severity, score=round(score, 1), confidence=a.confidence,
            title=f"Suspicious transaction {a.txid[:16]}...",
            summary=(
                f"Isolation Forest flagged {a.amount_btc:.6f} BTC "
                f"(confidence {a.confidence}%). "
                + (a.reasons[0] if a.reasons else "Unusual pattern detected.")
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
        title = (
            f"Behavior cluster #{cid}: {len(group)} similar transactions"
            if looks_like_txid else
            f"Wallet cluster #{cid}: {len(group)} linked addresses"
        )
        leads.append(InvestigativeLead(
            lead_id=f"L-{uuid.uuid4().hex[:6].upper()}",
            priority="HIGH" if vol > 5 or len(group) > 10 else "MEDIUM",
            score=round(min(50 + vol * 2 + len(group) * 3, 95), 1), confidence=conf,
            title=title,
            summary=f"{group[0].entity_type}. Combined volume {vol:.4f} BTC across {len(group)} entities.",
            evidence=[
                f"Cluster size: {len(group)}",
                f"Combined volume: {vol:.4f} BTC",
                f"Shared IPs: {len(ips)}",
                f"Type: {group[0].entity_type}",
            ],
            related_txids=[m.address for m in group[:10]] if looks_like_txid else [],
            related_addresses=[] if looks_like_txid else [m.address for m in group[:10]],
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
    return {
        "anomalies": len(anomalies),
        "clusters": len({c.cluster_id for c in clusters if c.cluster_id >= 0}),
        "leads": len(leads),
        "model": "IsolationForest+MiniBatchKMeans",
        "model_saved": str(MODEL_PATH),
    }
