"""Map a transaction to the 120 AML/KYT red-flag conditions (indicators, not proof)."""
from __future__ import annotations

from collections import defaultdict

import numpy as np
from sqlalchemy.orm import Session

from backend.database.db import Transaction, deserialize_addresses

CONDITIONS: dict[int, tuple[str, str]] = {
    1: ("Amount & Value", "Unusually large vs typical amounts in this dataset."),
    2: ("Amount & Value", "Sudden high-value BTC inflow (many inputs / large amount)."),
    3: ("Amount & Value", "Sudden high-value BTC outflow (many outputs / large amount)."),
    4: ("Amount & Value", "Amount is much larger than the dataset median."),
    5: ("Amount & Value", "Repeated large transfers in a short window (same wallets)."),
    6: ("Amount & Value", "Amount sits just below a round threshold (possible structuring)."),
    7: ("Amount & Value", "Large amount split across many outputs."),
    8: ("Amount & Value", "Many small inputs combined into one large transfer."),
    9: ("Amount & Value", "Round-number amount (typical of structured payments)."),
    10: ("Amount & Value", "Same/similar amount repeated for this wallet."),
    11: ("Amount & Value", "Large send with almost no leftover outputs (possible cash-out)."),
    12: ("Amount & Value", "High-value first appearance of a wallet in this dataset."),
    13: ("Frequency & Velocity", "High transaction frequency for linked wallets."),
    14: ("Frequency & Velocity", "Several incoming txs in a short time for the same wallet."),
    15: ("Frequency & Velocity", "Several outgoing txs in a short time for the same wallet."),
    16: ("Frequency & Velocity", "Activity burst vs quiet history for the same wallet."),
    17: ("Frequency & Velocity", "Irregular stop-start velocity pattern."),
    18: ("Frequency & Velocity", "Funds appear to move on quickly after receipt."),
    19: ("Frequency & Velocity", "Multiple txs within minutes for the same address."),
    20: ("Frequency & Velocity", "24/7-looking activity (overnight + daytime hits)."),
    21: ("Frequency & Velocity", "High velocity: many txs relative to time span."),
    22: ("Frequency & Velocity", "Large amount moved in rapid successive transfers."),
    23: ("Wallet Behaviour", "Newly seen wallet involved in a large transaction."),
    24: ("Wallet Behaviour", "Long-quiet wallet becomes active again."),
    25: ("Wallet Behaviour", "Unusually many counterparties."),
    26: ("Wallet Behaviour", "Interaction with a very large set of addresses."),
    27: ("Wallet Behaviour", "Fan-in/fan-out mix that does not match a simple payment."),
    28: ("Wallet Behaviour", "Peel-chain style: large in, many tiny leftover-like outputs."),
    29: ("Wallet Behaviour", "Repeated small leftover pattern (peeling)."),
    30: ("Wallet Behaviour", "Unusual incoming vs outgoing count ratio."),
    31: ("Wallet Behaviour", "Behaviour differs from typical txs in this dump."),
    32: ("Wallet Behaviour", "Linked to a mixing / high-fan-out behaviour cluster."),
    33: ("Fan-In / Fan-Out", "One source spreading funds to many wallets."),
    34: ("Fan-In / Fan-Out", "Many wallets consolidating into one."),
    35: ("Fan-In / Fan-Out", "One-to-many transfer pattern."),
    36: ("Fan-In / Fan-Out", "Many-to-one consolidation pattern."),
    37: ("Fan-In / Fan-Out", "Complex many-to-many shape (high in and high out)."),
    38: ("Fan-In / Fan-Out", "Funds split across multiple addresses."),
    39: ("Fan-In / Fan-Out", "Funds consolidated from multiple addresses."),
    40: ("Fan-In / Fan-Out", "Same destination funded by many unrelated inputs."),
    41: ("Fan-In / Fan-Out", "Same source funding many unrelated outputs."),
    42: ("Fan-In / Fan-Out", "Coordinated split/consolidate counts."),
    43: ("Rapid Movement", "Receive-and-forward style (high in and high out together)."),
    44: ("Rapid Movement", "Looks like a hop in a chain (pass-through fan-out)."),
    45: ("Rapid Movement", "Multiple hops suggested by dense counterparties + timing."),
    46: ("Rapid Movement", "Large movement consistent with deposit-then-withdraw."),
    47: ("Rapid Movement", "Pass-through with high fee pressure (urgent move)."),
    48: ("Rapid Movement", "Wallet-to-wallet relay pattern (many counterparties)."),
    49: ("Rapid Movement", "Large transfer followed by many smaller outputs."),
    50: ("Rapid Movement", "Short gap between related wallet transactions."),
    51: ("Structuring", "Large payment split into many smaller outputs."),
    52: ("Structuring", "Similar-value repeated outputs."),
    53: ("Structuring", "Amount just under a round reporting-style threshold."),
    54: ("Structuring", "Many outputs of similar size (layering)."),
    55: ("Structuring", "Many similar forwards from one source."),
    56: ("Structuring", "Sequential-looking split of a large amount."),
    57: ("Structuring", "Many small inputs then one large send."),
    58: ("Structuring", "One large amount then many small withdrawals."),
    59: ("Structuring", "Same split/consolidate pattern seen on other days for this wallet."),
    60: ("Structuring", "Coordinated splitting (high output count + round-ish sizes)."),
    61: ("Mixer / Obfuscation", "Mixer-like high fan-out without a simple 2-output payment."),
    62: ("Mixer / Obfuscation", "Send-side mixing pattern (many outputs)."),
    63: ("Mixer / Obfuscation", "Receive-side mixing pattern (many inputs)."),
    64: ("Mixer / Obfuscation", "Close to a mixing-style cluster (high fan-out group)."),
    65: ("Mixer / Obfuscation", "Multi-hop obfuscation suggested by complexity."),
    66: ("Mixer / Obfuscation", "Intentionally complex trail (high in AND high out)."),
    67: ("Mixer / Obfuscation", "Repeated address hopping (many unique counterparties)."),
    68: ("Mixer / Obfuscation", "History-obscuring construction (P2SH + high fan-out)."),
    69: ("Mixer / Obfuscation", "Many intermediate outputs with no simple 1-to-1 payment."),
    70: ("Mixer / Obfuscation", "Rapid obfuscation: large amount + high fan-out."),
    71: ("Cross-Chain", "Not enough chain-bridge fields in this metadata to confirm."),
    72: ("Cross-Chain", "Not enough stablecoin/bridge fields in this metadata to confirm."),
    73: ("Cross-Chain", "Not enough wrap/unwrap fields in this metadata to confirm."),
    74: ("Cross-Chain", "Not enough bridge identifiers in this metadata to confirm."),
    75: ("Cross-Chain", "Not enough multi-chain fields in this metadata to confirm."),
    76: ("Cross-Chain", "Not enough bridge+split fields in this metadata to confirm."),
    77: ("Cross-Chain", "Not enough routing fields in this metadata to confirm."),
    78: ("Cross-Chain", "Not enough business-purpose fields in this metadata to confirm."),
    79: ("Cross-Chain", "Not enough multi-chain repeat fields in this metadata to confirm."),
    80: ("Cross-Chain", "Not enough high-risk chain tags in this metadata to confirm."),
    81: ("Exchange Behaviour", "Not enough exchange labels in this metadata to confirm."),
    82: ("Exchange Behaviour", "Not enough exchange-hop labels in this metadata to confirm."),
    83: ("Exchange Behaviour", "New wallet + large amount can resemble a fresh exchange deposit."),
    84: ("Exchange Behaviour", "Large in then large out can resemble deposit-then-withdraw."),
    85: ("Exchange Behaviour", "Many unrelated inputs can resemble multi-exchange funding."),
    86: ("Exchange Behaviour", "Many outputs can resemble payouts to several venues."),
    87: ("Exchange Behaviour", "Profile mismatch vs typical simple payments in this dump."),
    88: ("Exchange Behaviour", "Foreign IP/ASN with large move can raise venue-risk questions."),
    89: ("Exchange Behaviour", "Shared funding source pattern (many inputs)."),
    90: ("Exchange Behaviour", "Shared withdrawal destination pattern (many outputs)."),
    91: ("Risky Address", "No scam-label feed in this offline dataset — cannot confirm."),
    92: ("Risky Address", "No ransomware-label feed in this offline dataset — cannot confirm."),
    93: ("Risky Address", "No theft-label feed in this offline dataset — cannot confirm."),
    94: ("Risky Address", "No fraud-label feed in this offline dataset — cannot confirm."),
    95: ("Risky Address", "No sanctions list in this offline dataset — cannot confirm."),
    96: ("Risky Address", "No darknet-label feed in this offline dataset — cannot confirm."),
    97: ("Risky Address", "No high-risk service tags in this offline dataset — cannot confirm."),
    98: ("Risky Address", "Previously flagged only if this TXID was already an ML anomaly."),
    99: ("Risky Address", "Indirect cluster link: similar mixing/high-volume behaviour group."),
    100: ("Risky Address", "No illicit-cluster intelligence feed in this offline dataset."),
    101: ("Dust & Micro", "Many tiny incoming amounts."),
    102: ("Dust & Micro", "Repeated dust-sized values."),
    103: ("Dust & Micro", "Tiny inputs consolidated into a larger send."),
    104: ("Dust & Micro", "Tiny amounts from many unrelated inputs."),
    105: ("Dust & Micro", "Dust-like activity on a rarely seen wallet."),
    106: ("Dust & Micro", "Repeated tiny outputs to many addresses."),
    107: ("Dust & Micro", "Micro outputs alongside a large movement."),
    108: ("Dust & Micro", "Dust pattern with other risk flags."),
    109: ("Dust & Micro", "Same tiny amount style repeated."),
    110: ("Dust & Micro", "Dust combined with mixing/fan-out indicators."),
    111: ("Fee & Technical", "Unusually high fee vs dataset."),
    112: ("Fee & Technical", "Repeated very low fee (batch/automated look)."),
    113: ("Fee & Technical", "Abnormal fee compared with transaction size."),
    114: ("Fee & Technical", "Fee behaviour unlike typical txs in this dump."),
    115: ("Fee & Technical", "Unusual construction (extreme in/out counts)."),
    116: ("Fee & Technical", "Extremely large number of inputs."),
    117: ("Fee & Technical", "Extremely large number of outputs."),
    118: ("Fee & Technical", "Unusual input/output ratio."),
    119: ("Fee & Technical", "Structure unlike a simple payment (not 1-in 2-out)."),
    120: ("Fee & Technical", "Several technical anomalies together."),
}

# Conditions that need external intel we do not have — never auto-match
INTEL_ONLY = set(range(71, 83)) | set(range(91, 98)) | {100}

WEIGHT = {
    **{i: 2 for i in range(1, 13)},
    **{i: 3 for i in range(13, 23)},
    **{i: 2 for i in range(23, 33)},
    **{i: 4 for i in range(33, 43)},
    **{i: 4 for i in range(43, 51)},
    **{i: 4 for i in range(51, 61)},
    **{i: 5 for i in range(61, 71)},
    **{i: 2 for i in range(83, 91)},
    **{i: 3 for i in range(98, 100)},
    **{i: 3 for i in range(101, 111)},
    **{i: 2 for i in range(111, 121)},
}


def _roundish(x: float) -> bool:
    if x <= 0:
        return False
    if abs(x - round(x)) < 1e-8:
        return True
    for step in (0.1, 0.01, 0.001, 0.5):
        if abs(x / step - round(x / step)) < 1e-6:
            return True
    return False


def _just_below_threshold(x: float) -> bool:
    if x <= 0:
        return False
    for t in (0.1, 0.5, 1, 2, 5, 10, 25, 50, 100):
        if 0.85 * t <= x < t:
            return True
    return False


def dataset_stats(db: Session) -> dict:
    rows = db.query(
        Transaction.amount_btc, Transaction.fee_btc,
        Transaction.input_count, Transaction.output_count,
    ).limit(40000).all()
    amts = np.array([r.amount_btc or 0 for r in rows], dtype=float)
    fees = np.array([r.fee_btc or 0 for r in rows], dtype=float)
    ins = np.array([r.input_count or 0 for r in rows], dtype=float)
    outs = np.array([r.output_count or 0 for r in rows], dtype=float)
    pos = amts[amts > 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        fr = np.where(amts > 0, fees / amts, 0.0)

    def p(arr, q, default=0.0):
        if len(arr) == 0:
            return default
        return float(np.percentile(arr, q))

    return {
        "med_amt": p(pos, 50),
        "p90_amt": p(pos, 90),
        "p95_amt": p(pos, 95),
        "p99_amt": p(pos, 99),
        "med_fee": p(fees, 50),
        "p90_fee": p(fees, 90),
        "p90_fr": p(fr, 90),
        "med_in": p(ins, 50, 1),
        "med_out": p(outs, 50, 2),
        "p90_in": p(ins, 90, 5),
        "p90_out": p(outs, 90, 5),
    }


def _wallet_context(db: Session, addrs: list[str], limit=80) -> list:
    if not addrs:
        return []
    sample = db.query(Transaction).limit(8000).all()
    want = set(addrs[:8])
    hits = []
    for t in sample:
        ins = set(deserialize_addresses(t.input_addresses))
        outs = set(deserialize_addresses(t.output_addresses))
        if want & (ins | outs):
            hits.append(t)
            if len(hits) >= limit:
                break
    return hits


def evaluate_tx(tx: Transaction, stats: dict, related: list | None = None, mixer_cluster: bool = False) -> list[dict]:
    amt = float(tx.amount_btc or 0)
    fee = float(tx.fee_btc or 0)
    inn = int(tx.input_count or 0)
    out = int(tx.output_count or 0)
    fr = (fee / amt) if amt > 0 else 0.0
    io = (out / inn) if inn else float(out)
    dust = amt > 0 and amt < 1e-4
    large = amt >= max(stats["p90_amt"], stats["med_amt"] * 5, 0.05)
    huge = amt >= max(stats["p95_amt"], 1.0)
    hi_out = out >= max(10, int(stats["p90_out"]))
    hi_in = inn >= max(8, int(stats["p90_in"]))
    many_ctpty = (inn + out) >= 12
    pass_through = hi_in and hi_out
    peel = out >= 8 and amt > 0.01
    high_fee = fee > stats["p90_fee"] * 1.5 or (fr > max(0.05, stats["p90_fr"]))
    low_fee = 0 < fee < max(stats["med_fee"] * 0.05, 1e-7)
    p2sh = (tx.script_type or "") in ("P2SH", "P2WSH")
    foreign = bool(tx.geo_country and tx.geo_country not in ("LOCAL", "UNK", ""))
    related = related or []
    times = sorted([t.timestamp for t in related if t.timestamp])
    burst = False
    overnight_and_day = False
    long_quiet = False
    first_seen = len(related) <= 1
    same_amt = False
    if times:
        span = (times[-1] - times[0]).total_seconds() or 1
        burst = len(times) >= 4 and span < 3600
        hours = {t.hour for t in times}
        overnight_and_day = any(h < 5 for h in hours) and any(h >= 8 for h in hours)
        gaps = [(times[i] - times[i - 1]).total_seconds() for i in range(1, len(times))]
        if gaps and max(gaps) > 30 * 86400 and min(gaps) < 86400:
            long_quiet = True
        if len(times) >= 5 and span < 6 * 3600:
            burst = True
    if related:
        amts = [t.amount_btc or 0 for t in related if (t.amount_btc or 0) > 0]
        if len(amts) >= 3:
            med = float(np.median(amts))
            same_amt = sum(1 for a in amts if med and abs(a - med) / med < 0.05) >= 3

    hit: set[int] = set()

    if huge or (large and amt > stats["med_amt"] * 8):
        hit.update({1, 4})
    if large and hi_in:
        hit.add(2)
    if large and hi_out:
        hit.add(3)
    if burst and large:
        hit.add(5)
    if _just_below_threshold(amt):
        hit.update({6, 53})
    if large and hi_out:
        hit.update({7, 51, 56, 58})
    if large and hi_in:
        hit.update({8, 57})
    if _roundish(amt):
        hit.add(9)
    if same_amt:
        hit.add(10)
    if large and out <= 2:
        hit.add(11)
    if first_seen and large:
        hit.update({12, 23, 83})
    if len(related) >= 8:
        hit.add(13)
    if burst and hi_in:
        hit.add(14)
    if burst and hi_out:
        hit.add(15)
    if burst:
        hit.update({16, 19, 21})
    if burst and long_quiet:
        hit.add(17)
    if pass_through or (hi_out and large):
        hit.update({18, 43, 46, 84})
    if overnight_and_day and len(related) >= 4:
        hit.add(20)
    if burst and large:
        hit.add(22)
    if long_quiet:
        hit.add(24)
    if many_ctpty:
        hit.update({25, 48})
    if out >= 20 or inn >= 20:
        hit.add(26)
    if pass_through:
        hit.add(27)
    if peel:
        hit.update({28, 29, 49})
    if inn and out and (io >= 5 or io <= 0.2):
        hit.add(30)
    if large or hi_out or hi_in:
        hit.add(31)
    if mixer_cluster or hi_out:
        hit.update({32, 64, 99})
    if hi_out:
        hit.update({33, 35, 38, 41, 55, 62, 86, 90})
    if hi_in:
        hit.update({34, 36, 39, 40, 63, 85, 89})
    if pass_through:
        hit.update({37, 42, 44, 66})
    if burst and many_ctpty:
        hit.update({45, 50, 65})
    if high_fee and pass_through:
        hit.add(47)
    if hi_out and _roundish(amt):
        hit.update({52, 54, 60})
    if same_amt and len({(t.timestamp.date() if t.timestamp else None) for t in related}) >= 2:
        hit.add(59)
    if hi_out and not (inn <= 2 and out <= 2):
        hit.update({61, 69})
    if many_ctpty:
        hit.add(67)
    if p2sh and hi_out:
        hit.add(68)
    if large and hi_out:
        hit.add(70)
    if large or hi_out or hi_in:
        hit.add(87)
    if foreign and large:
        hit.add(88)
    if dust or (amt > 0 and amt < 0.0005 and inn >= 5):
        hit.update({101, 102, 109})
    if dust and hi_in:
        hit.update({103, 104})
    if dust and first_seen:
        hit.add(105)
    if amt < 0.001 and hi_out:
        hit.update({106, 107})
    if (dust or amt < 0.001) and (hi_out or hi_in):
        hit.update({108, 110})
    if high_fee:
        hit.update({111, 113, 114})
    if low_fee and (hi_in or hi_out):
        hit.add(112)
    if hi_in or hi_out or pass_through:
        hit.add(115)
    if inn >= 15:
        hit.add(116)
    if out >= 15:
        hit.add(117)
    if inn and out and (io >= 4 or (inn >= 8 and out >= 8)):
        hit.add(118)
    if not (inn <= 2 and 1 <= out <= 3):
        hit.add(119)

    hit -= INTEL_ONLY
    tech = {111, 112, 113, 115, 116, 117, 118, 119} & hit
    if len(tech) >= 3:
        hit.add(120)

    # Keep explanations focused
    ranked = sorted(hit, key=lambda i: (-WEIGHT.get(i, 1), i))[:18]
    out_list = []
    for i in ranked:
        cat, text = CONDITIONS[i]
        why = _why(i, amt, fee, fr, inn, out)
        out_list.append({
            "id": i,
            "category": cat,
            "condition": text,
            "why": why,
            "weight": WEIGHT.get(i, 1),
        })
    return out_list


def _why(i: int, amt, fee, fr, inn, out) -> str:
    if i in (1, 2, 3, 4, 12, 23):
        return f"Amount {amt:.6f} BTC is large relative to this dataset."
    if i in (7, 33, 35, 38, 51, 58, 62, 117):
        return f"{out} outputs — split / fan-out pattern."
    if i in (8, 34, 36, 39, 57, 63, 116):
        return f"{inn} inputs — consolidation pattern."
    if i in (6, 9, 53):
        return f"Amount {amt:.6f} BTC looks structured (round or just-under threshold)."
    if i in (111, 113):
        return f"Fee {fee:.8f} BTC ({fr:.2%} of amount)."
    if i in (61, 66, 70):
        return f"Complex construction: {inn} in / {out} out with material value."
    return f"Observed on this record: {amt:.6f} BTC, {inn} in, {out} out."


def score_flags(flags: list[dict]) -> tuple[int, str]:
    pts = min(100, sum(f["weight"] for f in flags))
    if pts >= 81:
        level = "Critical"
    elif pts >= 61:
        level = "Very High"
    elif pts >= 41:
        level = "High"
    elif pts >= 21:
        level = "Medium"
    else:
        level = "Low"
    return pts, level


def explain_alert(db: Session, txids: list[str], wallets: list[str], lead_type: str = "", stats: dict | None = None) -> dict:
    stats = stats or dataset_stats(db)
    mixer = "mix" in (lead_type or "").lower()
    seen = {}
    txs_used = []
    lookup_ids = list(txids[:12])
    if not lookup_ids and wallets:
        sample = db.query(Transaction).limit(8000).all()
        want = set(wallets[:8])
        for t in sample:
            addrs = set(deserialize_addresses(t.input_addresses)) | set(deserialize_addresses(t.output_addresses))
            if want & addrs and (t.amount_btc or 0) > 1e-8:
                lookup_ids.append(t.txid)
            if len(lookup_ids) >= 8:
                break
    for txid in lookup_ids:
        tx = db.query(Transaction).filter(Transaction.txid == txid).first()
        if not tx or (tx.amount_btc or 0) <= 1e-8:
            continue
        addrs = deserialize_addresses(tx.input_addresses) + deserialize_addresses(tx.output_addresses)
        related = _wallet_context(db, addrs or wallets)
        for f in evaluate_tx(tx, stats, related, mixer_cluster=mixer):
            seen[f["id"]] = f
        txs_used.append(txid)
        if len(seen) >= 18:
            break
    flags = sorted(seen.values(), key=lambda f: (-f["weight"], f["id"]))[:18]
    pts, level = score_flags(flags)
    cats = defaultdict(list)
    for f in flags:
        cats[f["category"]].append(f)
    return {
        "matched": len(flags),
        "checked": 120,
        "risk_points": pts,
        "risk_level": level,
        "disclaimer": (
            "These 120 items are AML/KYT red-flag indicators, not proof of a crime. "
            "Match only what this metadata can support. Mixer, sanctions, darknet, "
            "and cross-chain labels need extra intelligence feeds."
        ),
        "categories": [
            {"name": name, "flags": items}
            for name, items in cats.items()
        ],
        "flags": flags,
    }
