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
]


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
    Write alerts_<datetime>.csv — identical columns to bitcoin_transactions_*.csv.
    Exports transactions linked to top alerts only (fast path).
    """
    stamp = _stamp()
    filename = f"alerts_{stamp}.csv"
    dataset_name = f"alerts_{stamp}"
    path = EXPORT_DIR / filename
    created_at = datetime.now(timezone.utc).isoformat()

    # Cap export work — top-scored leads only
    ranked = sorted(leads or [], key=lambda l: float(getattr(l, "score", 0) or 0), reverse=True)[:80]

    items: list[dict] = []
    seen_txids: set[str] = set()
    if db is not None:
        all_txids = []
        for l in ranked:
            all_txids.extend(_parse_json_field(getattr(l, "related_txids", None)))
        # One batched resolve instead of per-lead table scans
        for t in _resolve_alert_txs(db, all_txids, []):
            if t.txid in seen_txids:
                continue
            seen_txids.add(t.txid)
            items.extend(_tx_to_exploded_csv_rows(t))
        pg_items = [_lead_payload(l) for l in ranked]
    else:
        pg_items = [_lead_payload(l) for l in ranked]

    items.sort(key=lambda r: r.get("timestamp") or "")

    path.write_text(_rows_to_csv(items, dataset_name), encoding="utf-8")
    logger.info("Alert export written: %s (%s rows, %s alerts)", path, len(items), len(ranked))

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
        "dataset_name": dataset_name,
        "path": str(path.relative_to(ROOT)),
        "alert_count": len(ranked),
        "row_count": len(items),
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
    if path.suffix.lower() == ".csv":
        text = path.read_text(encoding="utf-8")
        title, rows = _read_export_csv(text)
        return {
            "filename": path.name,
            "dataset_name": title or path.stem,
            "path": str(path.relative_to(ROOT)),
            "format": "csv",
            "row_count": len(rows),
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
    """List local export files (newest first)."""
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
