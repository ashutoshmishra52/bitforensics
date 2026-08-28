from __future__ import annotations

import json

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database.db import (
    Anomaly,
    Lead,
    Transaction,
    deserialize_addresses,
    deserialize_floats,
)
from backend.geo.lookup import lookup as geo_lookup
from backend.ml.typology import classify_tx

WALLET_SOFT_IN = 6
WALLET_SOFT_OUT = 8
WALLET_HARD_MAX = 20


def build_graph(db: Session, max_txs: int = 12, focus_nodes: int = 48) -> dict:
    """
    Build IP ↔ TX ↔ wallet graph from SQLite.

    One neighborhood around the highest-risk TX:
    - Pattern / high risk only on TX nodes (never copied to IP/wallet)
    - Each IP gets its own GeoIP lookup
    - Wallet amounts use that address's values when present
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_keys: set[tuple[str, str, str]] = set()

    def node(nid: str, ntype: str, label: str, flagged: bool = False, extra: dict | None = None):
        if nid not in nodes:
            payload = {"id": nid, "type": ntype, "label": label, "flagged": bool(flagged)}
            if extra:
                payload.update(extra)
            nodes[nid] = payload
            return
        if flagged:
            nodes[nid]["flagged"] = True
        if not extra:
            return
        for k, v in extra.items():
            if v is None or v == "":
                continue
            if k == "role" and nodes[nid].get("role") and nodes[nid]["role"] != v:
                nodes[nid]["role"] = "both"
                continue
            if k not in nodes[nid] or nodes[nid].get(k) in (None, "", []):
                nodes[nid][k] = v

    def edge(src: str, dst: str, rel: str):
        key = (src, dst, rel)
        if key in edge_keys or src == dst:
            return
        if src not in nodes or dst not in nodes:
            return
        edge_keys.add(key)
        edges.append({"from": src, "to": dst, "rel": rel})

    def ip_geo(ip: str) -> tuple[str, str]:
        country, asn, _ = geo_lookup(ip)
        return country or "", asn or ""

    def addr_amount(amounts: list[float], index: int, fallback: float, n_addrs: int) -> float:
        if index < len(amounts) and amounts[index] is not None:
            try:
                return float(amounts[index])
            except (TypeError, ValueError):
                pass
        if n_addrs <= 0:
            return 0.0
        return float(fallback or 0) / n_addrs

    flagged_tx = {a.txid for a in db.query(Anomaly.txid).all()}
    anomaly_map = {
        a.txid: {
            "confidence": a.confidence or 0,
            "severity": a.severity or "LOW",
            "reasons": json.loads(a.reasons or "[]"),
            "score": a.anomaly_score or 0,
        }
        for a in db.query(Anomaly).all()
    }
    lead_txids: set[str] = set()
    lead_wallets: set[str] = set()
    lead_ips: set[str] = set()
    for lead in db.query(Lead).order_by(Lead.score.desc()).limit(80).all():
        lead_txids.update(json.loads(lead.related_txids or "[]"))
        lead_wallets.update(json.loads(lead.related_addresses or "[]"))
        lead_ips.update(json.loads(lead.related_ips or "[]"))

    def has_links(t: Transaction) -> bool:
        if t.src_ip or t.dst_ip:
            return True
        return bool(
            deserialize_addresses(t.input_addresses) or deserialize_addresses(t.output_addresses)
        )

    focus_ids = list(flagged_tx | lead_txids)
    linked_focus: list[Transaction] = []
    if focus_ids:
        for i in range(0, len(focus_ids), 400):
            chunk = focus_ids[i : i + 400]
            for t in db.query(Transaction).filter(Transaction.txid.in_(chunk)).all():
                if has_links(t):
                    linked_focus.append(t)

    if len(linked_focus) < max_txs:
        seen = {t.txid for t in linked_focus}
        q = (
            db.query(Transaction)
            .filter(
                or_(
                    Transaction.src_ip.isnot(None),
                    Transaction.dst_ip.isnot(None),
                    Transaction.input_addresses.isnot(None),
                    Transaction.output_addresses.isnot(None),
                )
            )
            .order_by(Transaction.amount_btc.desc())
            .limit(max_txs * 4)
        )
        for t in q:
            if t.txid in seen or not has_links(t):
                continue
            linked_focus.append(t)
            seen.add(t.txid)
            if len(linked_focus) >= max_txs:
                break

    if not linked_focus:
        if focus_ids:
            linked_focus = (
                db.query(Transaction)
                .filter(Transaction.txid.in_(focus_ids[:max_txs]))
                .limit(max_txs)
                .all()
            )
        if len(linked_focus) < max_txs:
            seen = {t.txid for t in linked_focus}
            for t in db.query(Transaction).order_by(Transaction.amount_btc.desc()).limit(80).all():
                if t.txid not in seen:
                    linked_focus.append(t)
                    seen.add(t.txid)
                    if len(linked_focus) >= max_txs:
                        break

    def tx_rank(t: Transaction) -> tuple:
        conf = float((anomaly_map.get(t.txid) or {}).get("confidence") or 0)
        return (
            1 if t.txid in flagged_tx else 0,
            conf,
            1 if t.txid in lead_txids else 0,
            float(t.amount_btc or 0),
        )

    linked_focus.sort(key=tx_rank, reverse=True)
    linked_focus = linked_focus[:max_txs]
    seed_txid = linked_focus[0].txid if linked_focus else None

    def add_tx_links(tx: Transaction, *, max_in: int, max_out: int) -> None:
        tx_id = f"tx:{tx.txid}"
        bad = tx.txid in flagged_tx
        short_tx = (tx.txid[:12] + "…") if len(tx.txid) > 12 else tx.txid
        node(
            tx_id,
            "tx",
            short_tx,
            bad,
            {
                "txid": tx.txid,
                "amount_btc": tx.amount_btc,
                "fee_btc": tx.fee_btc,
                "script_type": tx.script_type,
                "timestamp": tx.timestamp.isoformat() if tx.timestamp else None,
                "src_ip": tx.src_ip,
                "dst_ip": tx.dst_ip,
                "geo_country": tx.geo_country,
                "asn": tx.asn,
                "input_count": tx.input_count or 0,
                "output_count": tx.output_count or 0,
            },
        )

        ts_iso = tx.timestamp.isoformat() if tx.timestamp else None
        inputs = deserialize_addresses(tx.input_addresses)
        outputs = deserialize_addresses(tx.output_addresses)
        in_amts = deserialize_floats(tx.input_amounts)
        out_amts = deserialize_floats(tx.output_amounts)
        amt = float(tx.amount_btc or 0)

        show_in = inputs[:max_in]
        show_out = outputs[:max_out]
        if len(inputs) > max_in:
            nodes[tx_id]["inputs_shown"] = len(show_in)
            nodes[tx_id]["inputs_total"] = len(inputs)
        if len(outputs) > max_out:
            nodes[tx_id]["outputs_shown"] = len(show_out)
            nodes[tx_id]["outputs_total"] = len(outputs)

        for i, addr in enumerate(show_in):
            # Use original index in full list for amount alignment
            full_i = i
            w_id = f"w:{addr}"
            piece = addr_amount(in_amts, full_i, amt, len(inputs))
            node(
                w_id,
                "wallet",
                (addr[:14] + "…") if len(addr) > 14 else addr,
                addr in lead_wallets,
                {"address": addr, "total_received": 0.0, "total_sent": 0.0, "top_countries": []},
            )
            nodes[w_id]["total_sent"] = float(nodes[w_id].get("total_sent") or 0) + piece
            if ts_iso:
                if not nodes[w_id].get("first_seen") or ts_iso < nodes[w_id]["first_seen"]:
                    nodes[w_id]["first_seen"] = ts_iso
                if not nodes[w_id].get("last_seen") or ts_iso > nodes[w_id]["last_seen"]:
                    nodes[w_id]["last_seen"] = ts_iso
            edge(w_id, tx_id, "input")

        for i, addr in enumerate(show_out):
            w_id = f"w:{addr}"
            piece = addr_amount(out_amts, i, amt, len(outputs))
            node(
                w_id,
                "wallet",
                (addr[:14] + "…") if len(addr) > 14 else addr,
                addr in lead_wallets,
                {"address": addr, "total_received": 0.0, "total_sent": 0.0, "top_countries": []},
            )
            nodes[w_id]["total_received"] = float(nodes[w_id].get("total_received") or 0) + piece
            if ts_iso:
                if not nodes[w_id].get("first_seen") or ts_iso < nodes[w_id]["first_seen"]:
                    nodes[w_id]["first_seen"] = ts_iso
                if not nodes[w_id].get("last_seen") or ts_iso > nodes[w_id]["last_seen"]:
                    nodes[w_id]["last_seen"] = ts_iso
            edge(tx_id, w_id, "output")

        if tx.src_ip:
            country, asn = ip_geo(tx.src_ip)
            ip_id = f"ip:{tx.src_ip}"
            node(
                ip_id,
                "ip",
                tx.src_ip,
                tx.src_ip in lead_ips,
                {"ip": tx.src_ip, "country": country, "asn": asn, "role": "src"},
            )
            edge(ip_id, tx_id, "src")

        if tx.dst_ip:
            country, asn = ip_geo(tx.dst_ip)
            ip_id = f"ip:{tx.dst_ip}"
            node(
                ip_id,
                "ip",
                tx.dst_ip,
                tx.dst_ip in lead_ips,
                {"ip": tx.dst_ip, "country": country, "asn": asn, "role": "dst"},
            )
            edge(tx_id, ip_id, "dst")

    for tx in linked_focus:
        hard = tx.txid == seed_txid
        add_tx_links(
            tx,
            max_in=WALLET_HARD_MAX if hard else WALLET_SOFT_IN,
            max_out=WALLET_HARD_MAX if hard else WALLET_SOFT_OUT,
        )

    # Degree + scores
    degree = {nid: {"in": 0, "out": 0, "ips": 0, "wallets": 0, "txs": 0} for nid in nodes}
    neigh: dict[str, list[dict]] = {nid: [] for nid in nodes}
    for e in edges:
        frm, to, rel = e["from"], e["to"], e["rel"]
        if frm in degree:
            degree[frm]["out"] += 1
        if to in degree:
            degree[to]["in"] += 1
        for end, other, direction in ((frm, to, "out"), (to, frm, "in")):
            if end not in degree or other not in nodes:
                continue
            ot = nodes[other]["type"]
            if ot == "ip":
                degree[end]["ips"] += 1
            elif ot == "wallet":
                degree[end]["wallets"] += 1
            elif ot == "tx":
                degree[end]["txs"] += 1
            if len(neigh[end]) < 20:
                on = nodes[other]
                neigh[end].append({
                    "id": other,
                    "type": ot,
                    "label": on.get("label") or other,
                    "rel": rel,
                    "direction": direction,
                    "flagged": bool(on.get("flagged")),
                    "risk_score": 0.0,
                })

    for nid, n in nodes.items():
        d = degree.get(nid, {})
        n["connected_ips"] = d.get("ips", 0)
        n["connected_wallets"] = d.get("wallets", 0)
        n["connected_txs"] = d.get("txs", 0)
        n["degree"] = d.get("in", 0) + d.get("out", 0)
        n["neighbors"] = neigh.get(nid, [])
        if n["type"] == "ip":
            n["layer"] = "network"
            n["layer_label"] = "Network layer (IP / geo / ASN)"
        elif n["type"] == "wallet":
            n["layer"] = "blockchain"
            n["layer_label"] = "Blockchain layer (wallet address)"
        else:
            n["layer"] = "bridge"
            n["layer_label"] = "Bridge entity (TX links network ↔ wallets)"

        why: list[str] = []
        if n["type"] == "tx":
            typ = classify_tx(
                n.get("amount_btc"),
                n.get("fee_btc"),
                n.get("input_count"),
                n.get("output_count"),
                None,
            )
            n["pattern"] = typ.get("code")
            n["pattern_label"] = typ.get("label")
            n["pattern_why"] = typ.get("why")
            if typ.get("why"):
                why.append(typ["why"])
            if n.get("inputs_total") is not None:
                why.append(
                    f"Showing {n.get('inputs_shown')} of {n['inputs_total']} input wallets on graph"
                )
            if n.get("outputs_total") is not None:
                why.append(
                    f"Showing {n.get('outputs_shown')} of {n['outputs_total']} output wallets on graph"
                )
        else:
            n.pop("pattern", None)
            n.pop("pattern_label", None)
            n.pop("pattern_why", None)

        if n["type"] == "tx" and n.get("txid") in anomaly_map:
            info = anomaly_map[n["txid"]]
            n["risk_score"] = round(float(info["confidence"] or 0), 1)
            n["severity"] = info["severity"]
            n["flagged"] = True
            why = list(info["reasons"] or [])[:4] + why[:2]
        elif n.get("flagged"):
            n["risk_score"] = float(n.get("risk_score") or 35.0)
            n["severity"] = n.get("severity") or "MEDIUM"
            why.append("Linked to a model-flagged transaction or investigative lead")
        else:
            n["risk_score"] = float(n.get("risk_score") or 0)
            n["severity"] = n.get("severity") or "LOW"

        if n["type"] == "tx" and n.get("connected_ips", 0) >= 1:
            why.append(f"Network correlation: {n['connected_ips']} linked IP(s)")
        if n["type"] == "tx" and n.get("connected_wallets", 0) >= 3:
            why.append(f"Connected to {n['connected_wallets']} wallets")
        if n["type"] == "tx" and n.get("amount_btc") and float(n["amount_btc"] or 0) >= 5:
            why.append(f"High amount: {float(n['amount_btc']):.4f} BTC")
        if n["type"] == "ip" and n.get("country") and n["country"] not in ("LOCAL", "UNK", ""):
            why.append(f"GeoIP country: {n['country']}")
        if n["type"] == "wallet" and (n.get("total_received") or n.get("total_sent")):
            why.append(
                f"On-graph volume: sent {float(n.get('total_sent') or 0):.4f} BTC · "
                f"received {float(n.get('total_received') or 0):.4f} BTC"
            )
        n["why"] = why[:6]

    for n in nodes.values():
        for nb in n.get("neighbors") or []:
            other = nodes.get(nb["id"])
            if other:
                nb["flagged"] = bool(other.get("flagged"))
                nb["risk_score"] = float(other.get("risk_score") or 0)
                nb["label"] = other.get("label") or nb["id"]

    def risk_bucket(n: dict) -> str:
        sev = (n.get("severity") or "LOW").upper()
        if not n.get("flagged"):
            return "normal"
        if sev in ("CRITICAL", "HIGH"):
            return "high"
        if sev == "MEDIUM":
            return "medium"
        return "low"

    seed = f"tx:{seed_txid}" if seed_txid and f"tx:{seed_txid}" in nodes else None
    adj: dict[str, set[str]] = {nid: set() for nid in nodes}
    for e in edges:
        adj[e["from"]].add(e["to"])
        adj[e["to"]].add(e["from"])

    keep: set[str] = set()
    if seed:
        keep.add(seed)

        def rank_nb(nid: str) -> tuple:
            n = nodes[nid]
            type_ord = 0 if n["type"] == "ip" else 1 if n["type"] == "wallet" else 2
            return (0 if n.get("flagged") else 1, type_ord, -float(n.get("risk_score") or 0))

        direct = sorted(
            (nid for nid in adj.get(seed, ()) if nodes[nid]["type"] != "tx"),
            key=rank_nb,
        )
        for nb in direct:
            keep.add(nb)
            if len(keep) >= focus_nodes:
                break

        related_txs: list[str] = []
        for w in list(keep):
            if nodes[w]["type"] != "wallet":
                continue
            for tid in adj.get(w, ()):
                if nodes[tid]["type"] == "tx" and tid != seed and tid not in related_txs:
                    related_txs.append(tid)
        related_txs.sort(
            key=lambda nid: (
                -(1 if nodes[nid].get("flagged") else 0),
                -float(nodes[nid].get("risk_score") or 0),
                -float(nodes[nid].get("amount_btc") or 0),
            )
        )
        for tid in related_txs[:1]:
            if len(keep) >= focus_nodes:
                break
            keep.add(tid)
            extras = sorted(
                (nid for nid in adj.get(tid, ()) if nodes[nid]["type"] != "tx" and nid not in keep),
                key=rank_nb,
            )
            for nb in extras[:6]:
                if len(keep) >= focus_nodes:
                    break
                keep.add(nb)

    if keep:
        node_list = [nodes[nid] for nid in keep if nid in nodes]
        keep_ids = {n["id"] for n in node_list}
        edge_list = [e for e in edges if e["from"] in keep_ids and e["to"] in keep_ids]

        neigh2: dict[str, list[dict]] = {nid: [] for nid in keep_ids}
        deg2 = {nid: {"ips": 0, "wallets": 0, "txs": 0, "in": 0, "out": 0} for nid in keep_ids}
        for e in edge_list:
            frm, to, rel = e["from"], e["to"], e["rel"]
            deg2[frm]["out"] += 1
            deg2[to]["in"] += 1
            for end, other, direction in ((frm, to, "out"), (to, frm, "in")):
                ot = nodes[other]["type"]
                if ot == "ip":
                    deg2[end]["ips"] += 1
                elif ot == "wallet":
                    deg2[end]["wallets"] += 1
                elif ot == "tx":
                    deg2[end]["txs"] += 1
                if len(neigh2[end]) < 20:
                    on = nodes[other]
                    neigh2[end].append({
                        "id": other,
                        "type": ot,
                        "label": on.get("label") or other,
                        "rel": rel,
                        "direction": direction,
                        "flagged": bool(on.get("flagged")),
                        "risk_score": float(on.get("risk_score") or 0),
                    })
        for n in node_list:
            d = deg2[n["id"]]
            n["connected_ips"] = d["ips"]
            n["connected_wallets"] = d["wallets"]
            n["connected_txs"] = d["txs"]
            n["degree"] = d["in"] + d["out"]
            n["neighbors"] = neigh2[n["id"]]
            if n["type"] != "tx":
                n.pop("pattern", None)
                n.pop("pattern_label", None)
                n.pop("pattern_why", None)
    else:
        node_list = list(nodes.values())
        edge_list = edges

    risk_counts = {"high": 0, "medium": 0, "low": 0, "normal": 0}
    counts = {"ip": 0, "wallet": 0, "tx": 0, "flagged": 0}
    for n in node_list:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
        if n.get("flagged"):
            counts["flagged"] += 1
        risk_counts[risk_bucket(n)] += 1

    return {
        "nodes": node_list,
        "edges": edge_list,
        "meta": {
            "transactions_used": len(linked_focus),
            "counts": counts,
            "risk_counts": risk_counts,
            "has_links": len(edge_list) > 0,
            "focused": True,
            "seed": seed,
            "nodes_drawn": len(node_list),
            "edges_drawn": len(edge_list),
        },
    }
