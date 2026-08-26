from __future__ import annotations

import json

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database.db import Anomaly, Lead, Transaction, deserialize_addresses
from backend.ml.typology import classify_tx


def build_graph(db: Session, max_txs: int = 5, focus_nodes: int = 14) -> dict:
    """
    Build a real IP ↔ transaction ↔ wallet relationship network from SQLite.
    Compact investigation view centered on one high-risk neighborhood (readable, not crowded).
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
        else:
            if flagged:
                nodes[nid]["flagged"] = True
            if extra:
                for k, v in extra.items():
                    if v is not None and v != "" and (k not in nodes[nid] or nodes[nid].get(k) in (None, "", [])):
                        nodes[nid][k] = v

    def edge(src: str, dst: str, rel: str):
        key = (src, dst, rel)
        if key in edge_keys or src == dst:
            return
        if src not in nodes or dst not in nodes:
            return
        edge_keys.add(key)
        edges.append({"from": src, "to": dst, "rel": rel})

    flagged_tx = {a.txid for a in db.query(Anomaly.txid).all()}
    lead_txids: set[str] = set()
    lead_wallets: set[str] = set()
    lead_ips: set[str] = set()
    for lead in db.query(Lead).order_by(Lead.score.desc()).limit(80).all():
        lead_txids.update(json.loads(lead.related_txids or "[]"))
        lead_wallets.update(json.loads(lead.related_addresses or "[]"))
        lead_ips.update(json.loads(lead.related_ips or "[]"))

    def _has_links(t: Transaction) -> bool:
        if t.src_ip or t.dst_ip:
            return True
        ins = deserialize_addresses(t.input_addresses)
        outs = deserialize_addresses(t.output_addresses)
        return bool(ins or outs)

    # 1) Prefer flagged / lead txs that actually have IP or wallet edges
    focus_ids = list(flagged_tx | lead_txids)
    linked_focus: list[Transaction] = []
    if focus_ids:
        for i in range(0, len(focus_ids), 400):
            chunk = focus_ids[i:i + 400]
            for t in db.query(Transaction).filter(Transaction.txid.in_(chunk)).all():
                if _has_links(t):
                    linked_focus.append(t)

    # 2) Fill with any linked txs (IP or wallets), high amount first
    if len(linked_focus) < max_txs:
        seen = {t.txid for t in linked_focus}
        q = db.query(Transaction).filter(
            or_(
                Transaction.src_ip.isnot(None),
                Transaction.dst_ip.isnot(None),
                Transaction.input_addresses.isnot(None),
                Transaction.output_addresses.isnot(None),
            )
        ).order_by(Transaction.amount_btc.desc()).limit(max_txs * 3)
        for t in q:
            if t.txid in seen:
                continue
            if not _has_links(t):
                continue
            linked_focus.append(t)
            seen.add(t.txid)
            if len(linked_focus) >= max_txs:
                break

    # 3) Fallback: flagged/high-value txs even without links (still real API data)
    if not linked_focus:
        if focus_ids:
            linked_focus = (
                db.query(Transaction)
                .filter(Transaction.txid.in_(focus_ids[:max_txs]))
                .limit(max_txs)
                .all()
            )
        if len(linked_focus) < 40:
            seen = {t.txid for t in linked_focus}
            for t in db.query(Transaction).order_by(Transaction.amount_btc.desc()).limit(80).all():
                if t.txid not in seen:
                    linked_focus.append(t)
                    seen.add(t.txid)

    linked_focus = linked_focus[:max_txs]

    for tx in linked_focus:
        tx_id = f"tx:{tx.txid}"
        bad = tx.txid in flagged_tx
        node(
            tx_id,
            "tx",
            (tx.txid[:14] + "…") if len(tx.txid) > 14 else tx.txid,
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
        amt = float(tx.amount_btc or 0)
        geo = (tx.geo_country or "").strip()

        def _touch_wallet(w_id: str, *, received: bool) -> None:
            wn = nodes[w_id]
            wn["total_received"] = float(wn.get("total_received") or 0) + (amt if received else 0)
            wn["total_sent"] = float(wn.get("total_sent") or 0) + (0 if received else amt)
            if ts_iso:
                if not wn.get("first_seen") or ts_iso < wn["first_seen"]:
                    wn["first_seen"] = ts_iso
                if not wn.get("last_seen") or ts_iso > wn["last_seen"]:
                    wn["last_seen"] = ts_iso
            if geo and geo not in ("LOCAL", "UNK"):
                countries = wn.setdefault("top_countries", [])
                if geo not in countries:
                    countries.append(geo)

        # Cap fan-out hard — clean star, still enough outs to hint mixer
        for addr in deserialize_addresses(tx.input_addresses)[:3]:
            w_id = f"w:{addr}"
            node(
                w_id,
                "wallet",
                (addr[:14] + "…") if len(addr) > 14 else addr,
                bad and addr in lead_wallets,
                {"address": addr, "total_received": 0.0, "total_sent": 0.0, "top_countries": []},
            )
            if addr in lead_wallets:
                nodes[w_id]["flagged"] = True
            _touch_wallet(w_id, received=False)
            edge(w_id, tx_id, "input")

        for addr in deserialize_addresses(tx.output_addresses)[:4]:
            w_id = f"w:{addr}"
            node(
                w_id,
                "wallet",
                (addr[:14] + "…") if len(addr) > 14 else addr,
                bad and addr in lead_wallets,
                {"address": addr, "total_received": 0.0, "total_sent": 0.0, "top_countries": []},
            )
            if addr in lead_wallets:
                nodes[w_id]["flagged"] = True
            _touch_wallet(w_id, received=True)
            edge(tx_id, w_id, "output")

        if tx.src_ip:
            ip_id = f"ip:{tx.src_ip}"
            node(
                ip_id,
                "ip",
                tx.src_ip,
                tx.src_ip in lead_ips,
                {
                    "ip": tx.src_ip,
                    "country": tx.geo_country or "",
                    "asn": tx.asn or "",
                    "role": "src",
                },
            )
            if tx.src_ip in lead_ips:
                nodes[ip_id]["flagged"] = True
            edge(ip_id, tx_id, "src")

        if tx.dst_ip:
            ip_id = f"ip:{tx.dst_ip}"
            node(
                ip_id,
                "ip",
                tx.dst_ip,
                tx.dst_ip in lead_ips,
                {
                    "ip": tx.dst_ip,
                    "country": tx.geo_country or "",
                    "asn": tx.asn or "",
                    "role": "dst",
                },
            )
            if tx.dst_ip in lead_ips:
                nodes[ip_id]["flagged"] = True
            edge(tx_id, ip_id, "dst")

    # Do not attach orphan leads — floating unconnected nodes clutter the view

    # Anomaly scores for risk display
    anomaly_map = {
        a.txid: {
            "confidence": a.confidence or 0,
            "severity": a.severity or "LOW",
            "reasons": json.loads(a.reasons or "[]"),
            "score": a.anomaly_score or 0,
        }
        for a in db.query(Anomaly).all()
    }

    # Neighbor / degree counts from edges
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
            if len(neigh[end]) < 12:
                on = nodes[other]
                neigh[end].append({
                    "id": other,
                    "type": ot,
                    "label": on.get("label") or other,
                    "rel": rel,
                    "direction": direction,
                    "flagged": bool(on.get("flagged")),
                    "risk_score": float(on.get("risk_score") or 0),
                })

    for nid, n in nodes.items():
        d = degree.get(nid, {})
        n["connected_ips"] = d.get("ips", 0)
        n["connected_wallets"] = d.get("wallets", 0)
        n["connected_txs"] = d.get("txs", 0)
        n["degree"] = d.get("in", 0) + d.get("out", 0)
        n["neighbors"] = neigh.get(nid, [])
        # Layer tag for PS explainability
        if n["type"] == "ip":
            n["layer"] = "network"
            n["layer_label"] = "Network layer (IP / geo / ASN)"
        elif n["type"] == "wallet":
            n["layer"] = "blockchain"
            n["layer_label"] = "Blockchain layer (wallet address)"
        else:
            n["layer"] = "bridge"
            n["layer_label"] = "Bridge entity (TX links network ↔ wallets)"
        why = []
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
            if typ.get("label"):
                why.append(typ["why"])
        if n["type"] == "tx" and n.get("txid") in anomaly_map:
            info = anomaly_map[n["txid"]]
            n["risk_score"] = round(float(info["confidence"] or 0), 1)
            n["severity"] = info["severity"]
            n["flagged"] = True
            why = list(info["reasons"] or [])[:4] + why[:2]
        elif n.get("flagged"):
            n["risk_score"] = n.get("risk_score") or 75.0
            n["severity"] = n.get("severity") or "HIGH"
            why.append("Linked to a model-flagged transaction or lead")
        else:
            n["risk_score"] = float(n.get("risk_score") or 0)
            n["severity"] = n.get("severity") or "LOW"
        if n.get("connected_ips", 0) >= 1 and n["type"] == "tx":
            why.append(f"Network correlation: {n['connected_ips']} linked IP(s)")
        if n.get("connected_wallets", 0) >= 3:
            why.append(f"Connected to {n['connected_wallets']} wallets")
        if n.get("amount_btc") and float(n["amount_btc"] or 0) >= 5:
            why.append(f"High amount: {float(n['amount_btc']):.4f} BTC")
        if n.get("geo_country") or n.get("country"):
            c = n.get("geo_country") or n.get("country")
            if c and c not in ("LOCAL", "UNK", ""):
                why.append(f"Network geo: {c}")
        n["why"] = why[:6]

    # Copy SIH pattern from linked TX onto wallets / IPs for the detail panel
    for n in nodes.values():
        if n["type"] == "tx" or n.get("pattern"):
            continue
        for nb in n.get("neighbors") or []:
            other = nodes.get(nb["id"])
            if other and other.get("pattern"):
                n["pattern"] = other["pattern"]
                n["pattern_label"] = other.get("pattern_label")
                n["pattern_why"] = other.get("pattern_why")
                break

    # Refresh neighbor risk after scores are assigned
    for n in nodes.values():
        for nb in n.get("neighbors") or []:
            other = nodes.get(nb["id"])
            if other:
                nb["flagged"] = bool(other.get("flagged"))
                nb["risk_score"] = float(other.get("risk_score") or 0)
                nb["label"] = other.get("label") or nb["id"]

    risk_counts = {"high": 0, "medium": 0, "low": 0, "normal": 0}
    for n in nodes.values():
        sev = (n.get("severity") or "LOW").upper()
        if n.get("flagged") and sev == "CRITICAL":
            risk_counts["high"] += 1
        elif n.get("flagged") and sev == "HIGH":
            risk_counts["high"] += 1
        elif n.get("flagged") and sev == "MEDIUM":
            risk_counts["medium"] += 1
        elif n.get("flagged"):
            risk_counts["low"] += 1
        else:
            risk_counts["normal"] += 1

    counts = {"ip": 0, "wallet": 0, "tx": 0, "flagged": 0}
    for n in nodes.values():
        counts[n["type"]] = counts.get(n["type"], 0) + 1
        if n.get("flagged"):
            counts["flagged"] += 1

    # Compact investigation view: one connected neighborhood around top flagged TX
    node_list = list(nodes.values())
    edge_list = edges
    adj: dict[str, set[str]] = {nid: set() for nid in nodes}
    for e in edges:
        adj[e["from"]].add(e["to"])
        adj[e["to"]].add(e["from"])

    def _pick_seed() -> str | None:
        ranked = sorted(
            node_list,
            key=lambda x: (
                1 if x.get("flagged") else 0,
                2 if x.get("type") == "tx" else (1 if x.get("type") == "wallet" else 0),
                int(x.get("output_count") or 0),  # mixer / peel first for SIH demo
                float(x.get("risk_score") or 0),
                float(x.get("amount_btc") or 0),
                x.get("degree") or 0,
            ),
            reverse=True,
        )
        for n in ranked:
            if adj.get(n["id"]):
                return n["id"]
        return ranked[0]["id"] if ranked else None

    seed = _pick_seed()
    keep: set[str] = set()
    if seed:
        keep.add(seed)
        seed_type = nodes[seed]["type"]

        def _rank_nb(nid: str) -> tuple:
            n = nodes[nid]
            return (
                0 if n.get("flagged") else 1,
                0 if n["type"] == "ip" else 1 if n["type"] == "wallet" else 2,
                -float(n.get("risk_score") or 0),
            )

        # Pass 1: direct non-TX neighbors (IPs + wallets), capped
        direct = sorted(
            (nid for nid in adj.get(seed, ()) if nodes[nid]["type"] != "tx"),
            key=_rank_nb,
        )
        for nb in direct[:8]:
            keep.add(nb)
            if len(keep) >= focus_nodes:
                break

        # Pass 2: at most 2 related TXs, each with 2 wallets/IPs max
        if seed_type == "tx":
            # sibling TXs via shared wallets
            related_txs = []
            for w in list(keep):
                if nodes[w]["type"] != "wallet":
                    continue
                for tid in adj.get(w, ()):
                    if nodes[tid]["type"] == "tx" and tid != seed and tid not in related_txs:
                        related_txs.append(tid)
            related_txs.sort(key=lambda nid: (
                -(1 if nodes[nid].get("flagged") else 0),
                -float(nodes[nid].get("risk_score") or 0),
                -float(nodes[nid].get("amount_btc") or 0),
            ))
        else:
            related_txs = [
                nid for nid in adj.get(seed, ())
                if nodes[nid]["type"] == "tx" and nid not in keep
            ]
            related_txs.sort(key=lambda nid: (
                -(1 if nodes[nid].get("flagged") else 0),
                -float(nodes[nid].get("risk_score") or 0),
                -float(nodes[nid].get("amount_btc") or 0),
            ))

        for tid in related_txs[:2]:
            if len(keep) >= focus_nodes:
                break
            keep.add(tid)
            extras = sorted(
                (nid for nid in adj.get(tid, ()) if nodes[nid]["type"] != "tx" and nid not in keep),
                key=_rank_nb,
            )
            for nb in extras[:2]:
                if len(keep) >= focus_nodes:
                    break
                keep.add(nb)

    # Drop isolates / other disconnected components — one story at a time
    if keep:
        node_list = [n for n in node_list if n["id"] in keep]
        keep_ids = {n["id"] for n in node_list}
        edge_list = [e for e in edges if e["from"] in keep_ids and e["to"] in keep_ids]
        for n in node_list:
            n["neighbors"] = [nb for nb in (n.get("neighbors") or []) if nb["id"] in keep_ids][:12]

        # Re-attach SIH pattern from the seed TX after focus trim
        seed_node = next((n for n in node_list if n["id"] == seed), None)
        if seed_node and seed_node.get("pattern"):
            for n in node_list:
                if n["id"] == seed:
                    continue
                n["pattern"] = seed_node["pattern"]
                n["pattern_label"] = seed_node.get("pattern_label")
                n["pattern_why"] = seed_node.get("pattern_why")

        risk_counts = {"high": 0, "medium": 0, "low": 0, "normal": 0}
        counts = {"ip": 0, "wallet": 0, "tx": 0, "flagged": 0}
        for n in node_list:
            counts[n["type"]] = counts.get(n["type"], 0) + 1
            if n.get("flagged"):
                counts["flagged"] += 1
            sev = (n.get("severity") or "LOW").upper()
            if n.get("flagged") and sev in ("CRITICAL", "HIGH"):
                risk_counts["high"] += 1
            elif n.get("flagged") and sev == "MEDIUM":
                risk_counts["medium"] += 1
            elif n.get("flagged"):
                risk_counts["low"] += 1
            else:
                risk_counts["normal"] += 1

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
        },
    }
