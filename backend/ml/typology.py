"""Map on-chain shape to SIH-friendly scam / laundering typologies."""
from __future__ import annotations


TYPES = {
    "mixer": ("Mixer / tumbler pattern", "Funds split across many outputs — classic mixing / obfuscation."),
    "peel": ("Peel-chain", "Large input, many small leftover-style outputs — layering."),
    "consolidation": ("Consolidation", "Many inputs into one wallet — cash-out or pooling."),
    "whale": ("High-value transfer", "Amount far above typical traffic in this dump."),
    "dusting": ("Dusting / probe", "Tiny amounts to many addresses — tracking or spam."),
    "structuring": ("Structuring", "Amount sits near a round threshold or is split evenly."),
    "pass_through": ("Pass-through hop", "High in and high out together — rapid movement."),
    "overnight": ("Off-hours burst", "Activity in an unusual time window."),
    "cluster": ("Coordinated cluster", "Several transactions share the same behavioural fingerprint."),
}


def classify_tx(amount=0.0, fee=0.0, inn=0, out=0, hour=12) -> dict:
    amt = float(amount or 0)
    fee = float(fee or 0)
    inn = int(inn or 0)
    out = int(out or 0)
    fr = (fee / amt) if amt > 0 else 0.0
    code = "whale"
    if amt > 0 and amt < 0.0005 and (inn >= 4 or out >= 6):
        code = "dusting"
    elif inn >= 8 and out <= 3:
        code = "consolidation"
    elif out >= 12:
        code = "mixer"
    elif inn >= 6 and out >= 6:
        code = "pass_through"
    elif out >= 6 and amt >= 0.05:
        code = "peel"
    elif amt >= 50:
        code = "whale"
    elif 0.85 <= amt < 10 and abs(amt - round(amt)) < 0.02:
        code = "structuring"
    elif hour is not None and int(hour) < 5 and amt >= 1:
        code = "overnight"
    elif amt >= 5:
        code = "whale"
    label, why = TYPES[code]
    return {
        "code": code,
        "label": label,
        "why": why,
        "amount_btc": amt,
        "inputs": inn,
        "outputs": out,
        "fee_ratio": round(fr, 4),
    }


def classify_group(txs: list[dict]) -> dict:
    if not txs:
        return {
            "code": "cluster",
            "label": TYPES["cluster"][0],
            "why": TYPES["cluster"][1],
            "n": 0,
            "volume": 0.0,
            "max_amount": 0.0,
            "avg_outputs": 0.0,
            "avg_inputs": 0.0,
        }
    n = len(txs)
    amts = [float(t.get("amount_btc") or 0) for t in txs]
    inns = [int(t.get("input_count") or t.get("inputs") or 0) for t in txs]
    outs = [int(t.get("output_count") or t.get("outputs") or 0) for t in txs]
    vol = sum(amts)
    max_amt = max(amts) if amts else 0
    avg_out = sum(outs) / n if n else 0
    avg_in = sum(inns) / n if n else 0
    votes = []
    for t in txs:
        c = classify_tx(
            t.get("amount_btc"), t.get("fee_btc"),
            t.get("input_count") or t.get("inputs") or len(t.get("input_addresses") or []),
            t.get("output_count") or t.get("outputs") or len(t.get("output_addresses") or []),
        )
        votes.append(c["code"])
    code = max(set(votes), key=votes.count) if votes else "cluster"
    if avg_out >= 10:
        code = "mixer"
    elif avg_in >= 8 and avg_out <= 3:
        code = "consolidation"
    elif max_amt >= 100:
        code = "whale"
    label, why = TYPES.get(code, TYPES["cluster"])
    return {
        "code": code,
        "label": label,
        "why": why,
        "n": n,
        "volume": round(vol, 4),
        "max_amount": round(max_amt, 4),
        "avg_outputs": round(avg_out, 1),
        "avg_inputs": round(avg_in, 1),
    }


def unique_title(typ: dict, txid: str | None = None, cluster_id=None) -> str:
    short = (txid[:10] + "…") if txid and len(txid) > 10 else (txid or "")
    if typ.get("n", 0) > 1:
        return (
            f"{typ['label']}: {typ['n']} linked txs · "
            f"{typ['max_amount']:.2f} BTC peak"
        )
    if typ["code"] == "whale":
        return f"High-value move {typ['amount_btc']:.2f} BTC" + (f" · {short}" if short else "")
    if typ["code"] == "mixer":
        return f"Fan-out mixing · {typ.get('outputs', 0)} outputs" + (f" · {short}" if short else "")
    if typ["code"] == "consolidation":
        return f"Many-to-one pool · {typ.get('inputs', 0)} inputs" + (f" · {short}" if short else "")
    if typ["code"] == "dusting":
        return f"Dust / probe pattern" + (f" · {short}" if short else "")
    if typ["code"] == "peel":
        return f"Peel-chain split" + (f" · {short}" if short else "")
    return f"{typ['label']}" + (f" · {short}" if short else "")
