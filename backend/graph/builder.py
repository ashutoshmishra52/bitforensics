from __future__ import annotations

import json

from sqlalchemy.orm import Session

from backend.database.db import Anomaly, Lead, Transaction, deserialize_addresses


def build_graph(db: Session, max_txs: int = 250) -> dict:
    """Build a focused link graph from flagged / high-value txs only (not full 100k)."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid, ntype, label, flagged=False, extra=None):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype, "label": label, "flagged": flagged, **(extra or {})}
        elif flagged:
            nodes[nid]["flagged"] = True

    def edge(src, dst, rel):
        edges.append({"from": src, "to": dst, "rel": rel})

    flagged_tx = {a.txid for a in db.query(Anomaly.txid).all()}
    lead_txids = set()
    for l in db.query(Lead).limit(50).all():
        lead_txids.update(json.loads(l.related_txids or "[]"))

    focus = list(flagged_tx | lead_txids)[:max_txs]
    if not focus:
        # fallback: top amount txs
        top = db.query(Transaction).order_by(Transaction.amount_btc.desc()).limit(80).all()
    else:
        top = db.query(Transaction).filter(Transaction.txid.in_(focus)).limit(max_txs).all()
        if len(top) < 40:
            extra = db.query(Transaction).order_by(Transaction.amount_btc.desc()).limit(40).all()
            seen = {t.txid for t in top}
            top.extend(t for t in extra if t.txid not in seen)

    for tx in top:
        txid_short = tx.txid[:12]
        tx_node = f"tx:{txid_short}"
        bad = tx.txid in flagged_tx
        node(tx_node, "tx", tx.txid[:14] + "...", bad, {"amount": tx.amount_btc})

        for addr in deserialize_addresses(tx.input_addresses)[:4]:
            w = f"w:{addr[:12]}"
            node(w, "wallet", addr[:14] + "...", bad)
            edge(w, tx_node, "input")

        for addr in deserialize_addresses(tx.output_addresses)[:4]:
            w = f"w:{addr[:12]}"
            node(w, "wallet", addr[:14] + "...", bad)
            edge(tx_node, w, "output")

        for ip_field in ("src_ip", "dst_ip"):
            ip = getattr(tx, ip_field)
            if not ip:
                continue
            ip_node = f"ip:{ip}"
            node(ip_node, "ip", ip, bad, {"country": tx.geo_country or "", "asn": tx.asn or ""})
            if ip_field == "src_ip":
                edge(ip_node, tx_node, "src")
            else:
                edge(tx_node, ip_node, "dst")

    return {"nodes": list(nodes.values()), "edges": edges}
