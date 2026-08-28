"""
Archive analysis alerts to:
  1) CSV file under data/exports/alerts_YYYYMMDD_HHMMSS.csv (always)
     Row 1 = dataset name, row 2 = headers, row 3+ = data. One address and one
     amount per cell; multi-output txs get multiple rows (no semicolon lists).
  2) PostgreSQL tables (when POSTGRES_URL / DATABASE_URL is set)
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.database.db import deserialize_floats

logger = logging.getLogger("bitforensics.postgres_alerts")

ROOT = Path(__file__).resolve().parent.parent.parent
EXPORT_DIR = ROOT / "data" / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Example: postgresql+psycopg://bitforensics:bitforensics@localhost:5432/bitforensics
def _pg_url() -> str | None:
    url = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        return None
    # Allow plain postgresql:// — SQLAlchemy 2 + psycopg3 prefers postgresql+psycopg://
    if url.startswith("postgresql://") and "+psycopg" not in url and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _parse_json_field(val, default=None):
    if default is None:
        default = []
    if val is None:
        return default
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val or ("[]" if default == [] else "{}"))
        except Exception:
            return default
    return default


def _format_ts(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, str):
        text = dt.replace("+00:00", "Z")
        return text if text.endswith("Z") else text
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_amount(v) -> str:
    """Match bitcoin_transactions_*.csv amount style (up to 8 decimal places)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    text = f"{f:.8f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"



def _align_addrs_amounts(addrs: list, amounts: list) -> tuple[list, list]:
    """Same-side address/amount counts; never pad fake amounts."""
    addrs = [a for a in (addrs or []) if a]
    cleaned = []
    for a in amounts or []:
        try:
            cleaned.append(float(a))
        except (TypeError, ValueError):
            continue
    if len(cleaned) > len(addrs) and addrs:
        cleaned = cleaned[: len(addrs)]
    return addrs, cleaned


def _fmt_asn(val) -> str:
    if val is None or str(val).strip() in ("", "0"):
        return ""
    s = str(val).strip()
    return s.upper() if s.upper().startswith("AS") else f"AS{s}"


def _route_country(src_ip, dst_ip, stored: str | None) -> str:
    stored = (stored or "").strip()
    if "->" in stored:
        return stored.replace(" -> ", "->").strip()
    from backend.geo.lookup import lookup_route
    sc, _ = lookup_route(src_ip)
    dc, _ = lookup_route(dst_ip)
    if sc in ("LOCAL", "UNK", "") and stored and "->" not in stored:
        sc = stored
    if sc and dc:
        return f"{sc}->{dc}"
    return stored or sc or dc or ""


def _route_asn(src_ip, dst_ip, stored: str | None) -> str:
    stored = (stored or "").strip()
    if "->" in stored:
        parts = stored.split("->", 1)
        if len(parts) == 2:
            return f"{_fmt_asn(parts[0])}->{_fmt_asn(parts[1])}"
        return stored
    from backend.geo.lookup import lookup_route
    sc, sa = lookup_route(src_ip)
    dc, da = lookup_route(dst_ip)
    if sc in ("LOCAL", "UNK", "") and stored and "->" not in stored:
        sa = stored
    if not _fmt_asn(sa) and stored:
        sa = stored
    if not _fmt_asn(da) and stored and not _fmt_asn(sa):
        da = stored
    sa_f, da_f = _fmt_asn(sa), _fmt_asn(da)
    if sa_f and not da_f and dc == "LOCAL":
        da_f = "AS0"
    if sa_f and da_f:
        return f"{sa_f}->{da_f}"
    return _fmt_asn(stored) if stored else (sa_f or da_f or "")


def _pick_one(items: list, index: int):
    if not items:
        return ""
    if index < len(items):
        return items[index]
    return items[0]


def _tx_to_exploded_csv_rows(t) -> list[dict[str, Any]]:
    """One row per address/amount pair — each cell holds a single value (no ; lists)."""
    from backend.database.db import deserialize_addresses

    in_addrs = deserialize_addresses(t.input_addresses)
    out_addrs = deserialize_addresses(t.output_addresses)
    in_amts = deserialize_floats(t.input_amounts)
    out_amts = deserialize_floats(t.output_amounts)
    if not in_amts and (t.amount_btc or 0) > 0 and len(in_addrs) <= 1:
        in_amts = [float(t.amount_btc)]
    if not out_amts and (t.amount_btc or 0) > 0 and len(out_addrs) <= 1:
        out_amts = [float(t.amount_btc)]

    in_addrs, in_amts = _align_addrs_amounts(in_addrs, in_amts)
    out_addrs, out_amts = _align_addrs_amounts(out_addrs, out_amts)

    base = {
        "timestamp": _format_ts(t.timestamp),
        "src_ip": t.src_ip or "",
        "dst_ip": t.dst_ip or "",
        "src_port": int(t.src_port) if t.src_port is not None else "",
        "dst_port": int(t.dst_port) if t.dst_port is not None else "",
        "txid": t.txid or "",
        "geo_country": _route_country(t.src_ip, t.dst_ip, t.geo_country),
        "asn": _route_asn(t.src_ip, t.dst_ip, t.asn),
    }

    n = max(len(in_addrs), len(out_addrs), 1)
    rows = []
    for i in range(n):
        in_amt = _pick_one(in_amts, i) if in_amts else ""
        out_amt = _pick_one(out_amts, i) if out_amts else ""
        rows.append({
            **base,
            "input_addresses[]": _pick_one(in_addrs, i),
            "input_amounts[]": _fmt_amount(in_amt) if in_amt != "" else "",
            "output_addresses[]": _pick_one(out_addrs, i),
            "output_amounts[]": _fmt_amount(out_amt) if out_amt != "" else "",
        })
    return rows


def _resolve_alert_txs(db, txids: list[str], wallets: list[str], limit: int = 200):
    """Resolve by TXID only — no full-table address scans (keeps analysis fast)."""
    from backend.database.db import Transaction

    seen: set[str] = set()
    txs = []
    ids = [t for t in (txids or []) if t]
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        for t in db.query(Transaction).filter(Transaction.txid.in_(chunk)).all():
            if t.txid not in seen:
                seen.add(t.txid)
                txs.append(t)
            if len(txs) >= limit:
                return txs
    return txs


def _lead_payload(lead) -> dict[str, Any]:
    """Serialize InvestigativeLead or ORM Lead-like object."""
    evidence = getattr(lead, "evidence", None)
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except Exception:
            evidence = [evidence] if evidence else []
    related_txids = getattr(lead, "related_txids", None)
    if isinstance(related_txids, str):
        related_txids = json.loads(related_txids or "[]")
    related_addresses = getattr(lead, "related_addresses", None)
    if isinstance(related_addresses, str):
        related_addresses = json.loads(related_addresses or "[]")
    related_ips = getattr(lead, "related_ips", None)
    if isinstance(related_ips, str):
        related_ips = json.loads(related_ips or "[]")

    return {
        "lead_id": getattr(lead, "lead_id", None),
        "priority": getattr(lead, "priority", None),
        "score": float(getattr(lead, "score", 0) or 0),
        "confidence": float(getattr(lead, "confidence", 0) or 0),
        "title": getattr(lead, "title", None),
        "summary": getattr(lead, "summary", None),
        "evidence": evidence or [],
        "related_txids": related_txids or [],
        "related_addresses": related_addresses or [],
        "related_ips": related_ips or [],
        "lead_type": getattr(lead, "lead_type", None),
    }


CSV_COLUMNS = [
    "timestamp",
    "src_ip",
    "dst_ip",
    "src_port",
    "dst_port",
    "txid",
    "input_addresses[]",
    "output_addresses[]",
    "input_amounts[]",
    "output_amounts[]",
    "geo_country",
    "asn",
    "reason",
]


def _clean_one_line(text: str, max_len: int = 220) -> str:
    """Single CSV-safe line: collapse whitespace, strip bullets, hard-cap length."""
    s = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    s = s.replace("•", "").replace("—", "-").strip(" -|;")
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip(" ,.;:") + "…"
    return s


def _one_line_scam_reason(lead) -> str:
    """
    One clear line: why this looks suspicious / scam-like (investigative lead, not proof).
    Prefer the strongest evidence paragraph (pattern language over bare correlation scores).
    """
    payload = _lead_payload(lead) if not isinstance(lead, dict) else lead
    title = (payload.get("title") or "").strip()
    summary = (payload.get("summary") or "").strip()
    evidence = payload.get("evidence") or []
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except Exception:
            evidence = [evidence]
    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    evidence = [str(x).strip() for x in evidence if str(x).strip()]

    conf = payload.get("confidence")
    if conf is None:
        conf = payload.get("score")
    try:
        conf_s = f"{float(conf):.0f}%" if conf is not None else ""
    except (TypeError, ValueError):
        conf_s = ""

    def _rank_line(text: str) -> int:
        s = text.lower()
        score = min(len(text), 200)
        for kw, boost in (
            ("mixer", 100), ("tumbler", 100), ("peel", 90), ("launder", 90),
            ("scam", 80), ("ransomware", 80), ("whale", 70), ("dust", 70),
            ("fan-out", 70), ("fan out", 70), ("consolidat", 70), ("obfus", 70),
            ("cash-out", 60), ("layering", 60), ("pass-through", 50),
            ("isolation forest", 40), ("outlier", 30),
            ("correlation score", -40),  # prefer pattern narrative over bare corr score
        ):
            if kw in s:
                score += boost
        return score

    core = ""
    if evidence:
        core = max(evidence, key=_rank_line)
    if not core and summary:
        # First 1–2 sentences of summary
        parts = [p.strip() for p in summary.replace("!", ".").split(".") if p.strip()]
        core = ". ".join(parts[:2]).strip()
        if core and not core.endswith("."):
            core += "."
    if not core:
        core = title or "Flagged as unusual versus this dataset - review wallets, fan-out, and counterparties."
        if core and not core.endswith("."):
            core += "."

    # Keep title prefix when it adds pattern name not already in the line
    if title and title.lower() not in core.lower()[:100]:
        line = f"{title}: {core}"
    else:
        line = core

    if conf_s and f"confidence {conf_s}" not in line.lower() and conf_s not in line:
        line = f"{line} | confidence {conf_s}"

    if not line.lower().startswith("why suspicious"):
        line = f"Why suspicious: {line}"

    return _clean_one_line(line, 240)


def _reason_by_txid(ranked_leads: list) -> dict[str, str]:
    """Best one-line reason per related TXID (prefer pattern / scam narrative)."""
    best: dict[str, tuple[int, str]] = {}
    for lead in ranked_leads:
        reason = _one_line_scam_reason(lead)
        quality = 0
        # Re-score the final line
        s = reason.lower()
        quality = min(len(reason), 200)
        for kw, boost in (
            ("mixer", 100), ("tumbler", 100), ("peel", 90), ("launder", 90),
            ("scam", 80), ("ransomware", 80), ("whale", 70), ("dust", 70),
            ("fan-out", 70), ("consolidat", 70), ("obfus", 70), ("layering", 60),
            ("isolation forest", 50), ("outlier", 40),
            ("network link", -30), ("correlation score", -50), ("destination ip", -20),
        ):
            if kw in s:
                quality += boost
        # Slight boost for higher lead score
        quality += int(float(getattr(lead, "score", 0) or 0) / 5)

        txids = _parse_json_field(getattr(lead, "related_txids", None))
        if not txids:
            addrs = _parse_json_field(getattr(lead, "related_addresses", None))
            for a in addrs:
                if a and len(a) >= 32 and all(c in "0123456789abcdef" for c in a[:32].lower()):
                    txids.append(a)
        for tid in txids:
            if not tid:
                continue
            prev = best.get(tid)
            if prev is None or quality > prev[0]:
                best[tid] = (quality, reason)
    return {tid: pair[1] for tid, pair in best.items()}


def _anomaly_reason_map(db, txids: list[str]) -> dict[str, str]:
    """Pull Isolation Forest / pattern reasons stored on Anomaly rows."""
    if db is None or not txids:
        return {}
    from backend.database.db import Anomaly

    out: dict[str, str] = {}
    ids = list({t for t in txids if t})
    for i in range(0, len(ids), 200):
        chunk = ids[i : i + 200]
        for a in db.query(Anomaly).filter(Anomaly.txid.in_(chunk)).all():
            try:
                reasons = json.loads(a.reasons or "[]")
            except Exception:
                reasons = []
            if not isinstance(reasons, list):
                reasons = [str(reasons)]
            reasons = [str(x).strip() for x in reasons if str(x).strip()]
            if not reasons:
                continue
            # Pick strongest pattern paragraph
            core = max(
                reasons,
                key=lambda t: (
                    sum(
                        b for k, b in (
                            ("mixer", 100), ("peel", 90), ("launder", 90), ("scam", 80),
                            ("whale", 70), ("dust", 70), ("consolidat", 70), ("layering", 60),
                        ) if k in t.lower()
                    ) + min(len(t), 180)
                ),
            )
            conf = a.confidence
            conf_s = f"{float(conf):.0f}%" if conf is not None else ""
            line = f"Why suspicious: {core}"
            if conf_s:
                line = f"{line} | confidence {conf_s}"
            out[a.txid] = _clean_one_line(line, 240)
    return out


def _pdf_safe(text: str) -> str:
    """Helvetica-safe text for simple PDF (no fancy unicode)."""
    s = str(text or "")
    for a, b in (
        ("…", "..."), ("—", "-"), ("–", "-"), ("→", "->"), ("←", "<-"),
        ("•", "-"), ("\u00a0", " "), ("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"),
    ):
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _human_when(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "—"
    # 2026-01-01T00:39:48Z → 1 Jan 2026, 00:39 UTC
    try:
        ts = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return ts.strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        return s.replace("T", " ").replace("Z", " UTC")


def _stories_for_pdf(items: list[dict], max_stories: int = 40) -> list[dict[str, Any]]:
    """One simple card per unique TXID (for normal-person PDF)."""
    by_tx: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in items:
        tid = (row.get("txid") or "").strip()
        if not tid:
            continue
        in_addr = (row.get("input_addresses[]") or "").strip()
        out_addr = (row.get("output_addresses[]") or "").strip()
        in_amt = row.get("input_amounts[]") or ""
        out_amt = row.get("output_amounts[]") or ""
        if tid not in by_tx:
            reason = (row.get("reason") or "").strip()
            if reason.lower().startswith("why suspicious:"):
                reason = reason[len("Why suspicious:") :].strip()
            by_tx[tid] = {
                "txid": tid,
                "when": _human_when(row.get("timestamp") or ""),
                "src_ip": row.get("src_ip") or "—",
                "dst_ip": row.get("dst_ip") or "—",
                "amount": out_amt or in_amt or "—",
                "geo": row.get("geo_country") or "—",
                "reason": reason or "Flagged as unusual in this dataset.",
                "wallets_in": [],
                "wallets_out": [],
            }
            order.append(tid)
        st = by_tx[tid]
        if in_addr and in_addr not in st["wallets_in"]:
            st["wallets_in"].append(in_addr)
        if out_addr and out_addr not in st["wallets_out"]:
            st["wallets_out"].append(out_addr)
        if (not st["amount"] or st["amount"] == "—") and (out_amt or in_amt):
            st["amount"] = out_amt or in_amt
        if len(order) >= max_stories and tid not in order[:max_stories]:
            continue
    return [by_tx[tid] for tid in order[:max_stories]]


def _write_simple_alerts_pdf(
    path: Path,
    stories: list[dict[str, Any]],
    *,
    stamp: str,
    created_at: str,
    alert_count: int,
    row_count: int,
) -> None:
    """
    Plain-language PDF a non-technical reader can skim:
    title, short intro, then numbered cards (what / when / how much / why).
    """
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    pdf.set_margins(16, 16, 16)

    pdf.set_x(16)
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(178, 10, _pdf_safe("BitForensics - Simple Alert Report"))
    pdf.set_font("Helvetica", "", 11)
    pdf.set_x(16)
    pdf.multi_cell(178, 6, _pdf_safe(f"Report id: alerts_{stamp}"))
    pdf.set_x(16)
    pdf.multi_cell(178, 6, _pdf_safe(f"Created (UTC): {created_at}"))
    pdf.ln(2)

    pdf.set_x(16)
    pdf.set_font("Helvetica", "B", 12)
    pdf.multi_cell(178, 7, "What is this?")
    pdf.set_font("Helvetica", "", 10)
    intro = (
        "This report lists Bitcoin transactions that look unusual or scam-like "
        "in plain language. Each card shows what moved, when, and WHY it looks "
        "suspicious. This is for investigation only - not legal proof. "
        f"Alerts linked: {alert_count}. Detail rows in CSV: {row_count}. "
        "For full technical columns, open the matching CSV file."
    )
    pdf.set_x(16)
    pdf.multi_cell(178, 5, _pdf_safe(intro))
    pdf.ln(3)

    if not stories:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_x(16)
        pdf.multi_cell(178, 6, "No alert transactions to show. Run analysis first.")
        pdf.output(str(path))
        return

    pdf.set_font("Helvetica", "B", 12)
    pdf.set_x(16)
    pdf.multi_cell(178, 7, _pdf_safe(f"Suspicious transactions (showing {len(stories)})"))
    pdf.ln(1)

    usable_w = 178  # A4 width minus 16+16 margins

    def block(text: str, *, bold: bool = False, size: int = 10, h: float = 5):
        pdf.set_x(16)
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.multi_cell(usable_w, h, _pdf_safe(text))

    for i, s in enumerate(stories, 1):
        if pdf.get_y() > 245:
            pdf.add_page()
        pdf.set_fill_color(240, 244, 248)
        pdf.set_x(16)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(usable_w, 8, _pdf_safe(f"  Alert {i} of {len(stories)}"), new_x="LMARGIN", new_y="NEXT", fill=True)
        pdf.ln(1)

        amt = s.get("amount") or "—"
        amt_line = amt if amt in ("—", "") else f"{amt} BTC"
        wallets_in = s.get("wallets_in") or []
        wallets_out = s.get("wallets_out") or []
        from_w = wallets_in[0] if wallets_in else ""
        to_w = wallets_out[0] if wallets_out else ""
        if from_w and to_w:
            wallet_line = f"{from_w}  ->  {to_w}"
        else:
            wallet_line = from_w or to_w or "—"

        block(f"When: {s.get('when') or '—'}")
        block(f"Wallet ID: {wallet_line}")
        block(f"How much: {amt_line}")
        block(f"From IP: {s.get('src_ip') or '—'}")
        block(f"To IP: {s.get('dst_ip') or '—'}")
        block("Why it looks suspicious:", bold=True)
        block(s.get("reason") or "Unusual pattern in this dataset.")
        pdf.ln(3)
        y = pdf.get_y()
        pdf.set_draw_color(200, 200, 200)
        pdf.line(16, y, 194, y)
        pdf.ln(4)

    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(
        0,
        4,
        _pdf_safe(
            "Note: Confidence and pattern labels are machine-assisted leads. "
            "Always verify wallets, timing, and counterparties before escalating."
        ),
    )
    pdf.output(str(path))


def _rows_to_csv(items: list[dict], dataset_name: str) -> str:
    buf = io.StringIO()
    buf.write(f"{dataset_name}\r\n")
    writer = csv.DictWriter(
        buf,
        fieldnames=CSV_COLUMNS,
        extrasaction="ignore",
        lineterminator="\r\n",
    )
    writer.writeheader()
    for row in items:
        writer.writerow({k: row.get(k, "") for k in CSV_COLUMNS})
    return "\ufeff" + buf.getvalue()


def _read_export_csv(text: str) -> tuple[str | None, list[dict]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None, []
    title = None
    start = 0
    if "timestamp" not in lines[0]:
        title = lines[0].strip()
        start = 1
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))
    return title, rows


def write_alerts_export(leads: list, meta: dict | None = None, db=None) -> dict[str, Any]:
    """
    Write alerts_<datetime>.csv (full detail + reason) AND matching
    alerts_<datetime>.pdf (simple plain-language cards for non-technical readers).
    """
    stamp = _stamp()
    filename = f"alerts_{stamp}.csv"
    pdf_filename = f"alerts_{stamp}.pdf"
    dataset_name = f"alerts_{stamp}"
    path = EXPORT_DIR / filename
    pdf_path = EXPORT_DIR / pdf_filename
    created_at = datetime.now(timezone.utc).isoformat()

    # Cap export work — top-scored leads only
    ranked = sorted(leads or [], key=lambda l: float(getattr(l, "score", 0) or 0), reverse=True)[:80]
    reason_map = _reason_by_txid(ranked)

    items: list[dict] = []
    seen_txids: set[str] = set()
    if db is not None:
        all_txids = []
        for l in ranked:
            all_txids.extend(_parse_json_field(getattr(l, "related_txids", None)))
        # Prefer model anomaly reasons when available (clearer "why scam" than bare network corr)
        anom_map = _anomaly_reason_map(db, all_txids)
        for tid, reason in anom_map.items():
            prev = reason_map.get(tid, "")
            # Anomaly narrative wins unless lead already has strong pattern language
            prev_l = prev.lower()
            strong = any(k in prev_l for k in ("mixer", "peel", "launder", "scam", "whale", "dust", "layering"))
            if not prev or not strong:
                reason_map[tid] = reason

        for t in _resolve_alert_txs(db, all_txids, []):
            if t.txid in seen_txids:
                continue
            seen_txids.add(t.txid)
            reason = reason_map.get(t.txid) or ""
            weak = (not reason) or any(
                k in reason.lower()
                for k in ("network link on", "correlation score", "destination ip:")
            ) and not any(
                k in reason.lower()
                for k in ("mixer", "peel", "launder", "scam", "whale", "dust", "layering", "outlier")
            )
            if weak:
                from backend.ml.typology import classify_tx

                typ = classify_tx(
                    t.amount_btc,
                    t.fee_btc,
                    t.input_count or 0,
                    t.output_count or 0,
                    t.timestamp.hour if t.timestamp else 12,
                )
                hop = ""
                if t.src_ip or t.dst_ip:
                    hop = f" Network hop {t.src_ip or '—'} -> {t.dst_ip or '—'}."
                reason = _clean_one_line(
                    f"Why suspicious: {typ.get('label')}: {typ.get('why')} "
                    f"Amount {float(t.amount_btc or 0):.4f} BTC"
                    f" ({int(t.input_count or 0)} in / {int(t.output_count or 0)} out).{hop}",
                    240,
                )
            # Prefer true TX amount on first exploded row for PDF friendliness
            tx_rows = _tx_to_exploded_csv_rows(t)
            for idx, row in enumerate(tx_rows):
                row["reason"] = reason
                if idx == 0 and (t.amount_btc or 0) > 0:
                    # Keep amount visible even when exploded amounts are split
                    if not row.get("output_amounts[]") and not row.get("input_amounts[]"):
                        row["output_amounts[]"] = _fmt_amount(t.amount_btc)
                items.append(row)
        pg_items = [_lead_payload(l) for l in ranked]
    else:
        pg_items = [_lead_payload(l) for l in ranked]

    items.sort(key=lambda r: r.get("timestamp") or "")

    path.write_text(_rows_to_csv(items, dataset_name), encoding="utf-8")
    logger.info("Alert export written: %s (%s rows, %s alerts)", path, len(items), len(ranked))

    stories = _stories_for_pdf(items, max_stories=40)
    # Enrich story amounts with full TX amount when available via reason line / first row
    try:
        _write_simple_alerts_pdf(
            pdf_path,
            stories,
            stamp=stamp,
            created_at=created_at,
            alert_count=len(ranked),
            row_count=len(items),
        )
        logger.info("Alert PDF written: %s (%s stories)", pdf_path, len(stories))
    except Exception as e:
        logger.warning("Alert PDF failed: %s", e)
        pdf_filename = ""
        if pdf_path.exists():
            try:
                pdf_path.unlink()
            except Exception:
                pass

    pg = {"enabled": False, "saved": False, "error": None}
    url = _pg_url()
    if url:
        pg["enabled"] = True
        try:
            _save_to_postgres(url, filename, created_at, pg_items, meta or {})
            pg["saved"] = True
        except Exception as e:
            pg["error"] = str(e)
            logger.warning("Postgres alert save failed: %s", e)

    return {
        "filename": filename,
        "pdf_filename": pdf_filename,
        "dataset_name": dataset_name,
        "path": str(path.relative_to(ROOT)),
        "pdf_path": str(pdf_path.relative_to(ROOT)) if pdf_filename else None,
        "alert_count": len(ranked),
        "row_count": len(items),
        "pdf_stories": len(stories),
        "created_at": created_at,
        "postgres": pg,
    }


def _save_to_postgres(url: str, filename: str, created_at: str, items: list[dict], meta: dict) -> None:
    from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, text
    from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

    class PgBase(DeclarativeBase):
        pass

    class AlertRun(PgBase):
        __tablename__ = "alert_runs"
        id = Column(Integer, primary_key=True, autoincrement=True)
        filename = Column(String(128), unique=True, nullable=False, index=True)
        created_at = Column(DateTime(timezone=True), nullable=False)
        alert_count = Column(Integer, default=0)
        model = Column(String(120))
        meta_json = Column(Text)

    class AlertRow(PgBase):
        __tablename__ = "alerts"
        id = Column(Integer, primary_key=True, autoincrement=True)
        run_filename = Column(String(128), index=True, nullable=False)
        lead_id = Column(String(32), index=True)
        priority = Column(String(20))
        score = Column(Float)
        confidence = Column(Float)
        title = Column(String(255))
        summary = Column(Text)
        evidence = Column(Text)
        related_txids = Column(Text)
        related_addresses = Column(Text)
        related_ips = Column(Text)
        lead_type = Column(String(80))
        created_at = Column(DateTime(timezone=True))

    engine = create_engine(url, pool_pre_ping=True)
    PgBase.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    # Parse ISO created_at
    try:
        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception:
        ts = datetime.now(timezone.utc)

    with SessionLocal() as session:
        # Replace same filename if re-run (unique)
        session.execute(text("DELETE FROM alerts WHERE run_filename = :f"), {"f": filename})
        session.execute(text("DELETE FROM alert_runs WHERE filename = :f"), {"f": filename})
        session.add(
            AlertRun(
                filename=filename,
                created_at=ts,
                alert_count=len(items),
                model=(meta or {}).get("model"),
                meta_json=json.dumps(meta or {}),
            )
        )
        for a in items:
            session.add(
                AlertRow(
                    run_filename=filename,
                    lead_id=a.get("lead_id"),
                    priority=a.get("priority"),
                    score=a.get("score"),
                    confidence=a.get("confidence"),
                    title=a.get("title"),
                    summary=a.get("summary"),
                    evidence=json.dumps(a.get("evidence") or []),
                    related_txids=json.dumps(a.get("related_txids") or []),
                    related_addresses=json.dumps(a.get("related_addresses") or []),
                    related_ips=json.dumps(a.get("related_ips") or []),
                    lead_type=a.get("lead_type"),
                    created_at=ts,
                )
            )
        session.commit()
    engine.dispose()


def _export_summary(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        text = path.read_text(encoding="utf-8")
        title, rows = _read_export_csv(text)
        pdf_name = path.with_suffix(".pdf").name
        return {
            "filename": path.name,
            "pdf_filename": pdf_name if (path.with_suffix(".pdf")).exists() else None,
            "dataset_name": title or path.stem,
            "path": str(path.relative_to(ROOT)),
            "format": "csv",
            "row_count": len(rows),
            "created_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "bytes": path.stat().st_size,
        }
    if suffix == ".pdf":
        return {
            "filename": path.name,
            "path": str(path.relative_to(ROOT)),
            "format": "pdf",
            "created_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "bytes": path.stat().st_size,
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "filename": path.name,
        "path": str(path.relative_to(ROOT)),
        "format": "json",
        "alert_count": data.get("alert_count", 0),
        "created_at": data.get("created_at"),
        "bytes": path.stat().st_size,
    }


def list_alert_exports(limit: int = 50) -> list[dict[str, Any]]:
    """List CSV datasheets (newest first). Matching PDF is attached as pdf_filename."""
    files = sorted(
        list(EXPORT_DIR.glob("alerts_*.csv")) + list(EXPORT_DIR.glob("alerts_*.json")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out = []
    for p in files[: max(1, min(limit, 200))]:
        try:
            out.append(_export_summary(p))
        except Exception:
            out.append({"filename": p.name, "path": str(p.relative_to(ROOT)), "error": "unreadable"})
    return out


def postgres_status() -> dict[str, Any]:
    url = _pg_url()
    if not url:
        return {
            "configured": False,
            "message": "Set POSTGRES_URL or DATABASE_URL to archive alerts in PostgreSQL",
        }
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            try:
                runs = conn.execute(text("SELECT COUNT(*) FROM alert_runs")).scalar()
                alerts = conn.execute(text("SELECT COUNT(*) FROM alerts")).scalar()
            except Exception:
                runs, alerts = 0, 0
        engine.dispose()
        return {
            "configured": True,
            "reachable": True,
            "alert_runs": int(runs or 0),
            "alerts": int(alerts or 0),
        }
    except Exception as e:
        return {"configured": True, "reachable": False, "error": str(e)}
