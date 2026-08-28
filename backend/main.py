from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.correlation.engine import correlate_network_blockchain, store_transactions
from backend.database.db import (
    Anomaly, Cluster, Correlation, Lead, Transaction,
    deserialize_addresses, deserialize_floats, get_db, init_db,
)
from backend.graph.builder import build_graph
from backend.ingest.parser import parse_csv, parse_json, parse_xml, parse_file
from backend.geo.lookup import status as geo_status
from backend.geo.download import download_geoip
from backend.ml.analyzer import run_full_analysis
from backend.ml.typology import classify_group, classify_tx, unique_title
from backend.ml.red_flags import dataset_stats, explain_alert
from backend.database.postgres_alerts import (
    EXPORT_DIR,
    list_alert_exports,
    postgres_status,
    write_alerts_export,
)
from backend.models.schemas import AnomalyResult, ClusterMember, CorrelatedEvent, DashboardStats, InvestigativeLead

app = FastAPI(title="BitForensics", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "dist"
SAMPLES = ROOT / "data" / "samples"


@app.on_event("startup")
def startup():
    init_db()
    # Optional dev seed — off by default (upload your own data in production use)
    if os.environ.get("BITFORENSICS_SEED_SAMPLES", "").strip().lower() not in ("1", "true", "yes"):
        return
    from backend.database.db import SessionLocal

    db = SessionLocal()
    try:
        if db.query(Transaction).count() > 0:
            return
        if not SAMPLES.exists():
            return
        for f in sorted(SAMPLES.iterdir()):
            if f.suffix.lower() in (".csv", ".json", ".xml"):
                store_transactions(db, parse_file(f), f.name)
        correlate_network_blockchain(db)
        run_full_analysis(db)
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "offline", "geo": geo_status()}


@app.get("/api/stats", response_model=DashboardStats)
def stats(db: Session = Depends(get_db)):
    from sqlalchemy import func

    total = db.query(func.count(Transaction.id)).scalar() or 0
    network = db.query(func.count(Transaction.id)).filter(
        (Transaction.src_ip.isnot(None)) | (Transaction.dst_ip.isnot(None))
    ).scalar() or 0
    volume = db.query(func.coalesce(func.sum(Transaction.amount_btc), 0.0)).scalar() or 0.0
    anomalies = db.query(func.count(Anomaly.id)).scalar() or 0
    leads = db.query(func.count(Lead.id)).scalar() or 0
    corr = db.query(func.count(Correlation.id)).scalar() or 0
    cluster_ids = {c[0] for c in db.query(Cluster.cluster_id).all() if c[0] is not None and c[0] >= 0}
    sources = db.query(Transaction.source_file, func.count(Transaction.id)).group_by(
        Transaction.source_file
    ).all()

    return DashboardStats(
        total_transactions=total,
        total_network_events=network,
        correlated_events=corr,
        anomalies_detected=anomalies,
        clusters_found=len(cluster_ids),
        leads_generated=leads,
        total_volume_btc=round(float(volume), 4),
        graph_nodes=0,
        graph_edges=0,
        sources={name or "unknown": count for name, count in sources},
    )


@app.get("/api/transactions")
def transactions(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    rows = db.query(Transaction).order_by(Transaction.timestamp.desc()).offset(offset).limit(limit).all()
    return [{
        "txid": t.txid,
        "timestamp": t.timestamp.isoformat() if t.timestamp else None,
        "src_ip": t.src_ip, "dst_ip": t.dst_ip,
        "src_port": t.src_port, "dst_port": t.dst_port,
        "amount_btc": t.amount_btc, "fee_btc": t.fee_btc,
        "script_type": t.script_type,
        "geo_country": t.geo_country, "asn": t.asn,
        "input_addresses": deserialize_addresses(t.input_addresses),
        "output_addresses": deserialize_addresses(t.output_addresses),
        "input_amounts": deserialize_floats(t.input_amounts),
        "output_amounts": deserialize_floats(t.output_amounts),
    } for t in rows]


@app.get("/api/graph")
def graph(db: Session = Depends(get_db)):
    """Focused IP / TX / wallet neighborhood from real DB rows (not invented nodes)."""
    return build_graph(db)


def _clear_all(db: Session) -> dict:
    counts = {
        "leads": db.query(Lead).count(),
        "anomalies": db.query(Anomaly).count(),
        "clusters": db.query(Cluster).count(),
        "correlations": db.query(Correlation).count(),
        "transactions": db.query(Transaction).count(),
    }
    for model in (Lead, Anomaly, Cluster, Correlation, Transaction):
        db.query(model).delete()
    db.commit()
    return counts


def _load_demo_dataset(db) -> dict:
    """Replace DB contents with bundled demo CSV + network JSON, then analyze."""
    sample = SAMPLES / "transactions.csv"
    network = SAMPLES / "network_events.json"
    if not sample.exists():
        raise HTTPException(404, "Demo data not found (data/samples/transactions.csv)")

    cleared = _clear_all(db)
    csv_result = store_transactions(db, parse_file(sample), sample.name)
    net_result = {"parsed": 0, "added": 0}
    if network.exists():
        net_result = store_transactions(db, parse_file(network), network.name)
    correlate_network_blockchain(db)
    analysis = run_full_analysis(db)
    return {
        "message": "Demo dataset loaded and analyzed",
        "cleared": cleared,
        "ingest": csv_result,
        "network_ingest": net_result,
        "analysis": analysis,
    }


@app.post("/api/samples/load")
@app.post("/api/demo/network-sample")
def load_network_sample(db: Session = Depends(get_db)):
    return _load_demo_dataset(db)


def _alert_item(db, r, rank, stats):
    txids = json.loads(r.related_txids or "[]")
    wallets = json.loads(r.related_addresses or "[]")
    txs = []
    for txid in txids:
        t = db.query(Transaction).filter(Transaction.txid == txid).first()
        detail = {
            "txid": txid,
            "explorer_url": f"https://www.blockchain.com/explorer/transactions/btc/{txid}",
            "blockchain_url": f"https://www.blockchain.com/explorer/transactions/btc/{txid}",
        }
        if t:
            if (t.amount_btc or 0) <= 1e-8:
                continue
            detail.update({
                "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                "amount_btc": t.amount_btc,
                "fee_btc": t.fee_btc,
                "script_type": t.script_type,
                "src_ip": t.src_ip,
                "dst_ip": t.dst_ip,
                "src_port": t.src_port,
                "dst_port": t.dst_port,
                "geo_country": t.geo_country,
                "asn": t.asn,
                "input_addresses": deserialize_addresses(t.input_addresses),
                "output_addresses": deserialize_addresses(t.output_addresses),
                "input_count": t.input_count or 0,
                "output_count": t.output_count or 0,
            })
        txs.append(detail)

    if txids and not txs and not wallets:
        return None

    payload = [
        {
            "amount_btc": t.get("amount_btc") or 0,
            "fee_btc": t.get("fee_btc") or 0,
            "input_count": t.get("input_count") or len(t.get("input_addresses") or []),
            "output_count": t.get("output_count") or len(t.get("output_addresses") or []),
        }
        for t in txs
    ]
    if len(payload) >= 2:
        typ = classify_group(payload)
    elif payload:
        t0 = txs[0]
        typ = classify_tx(
            t0.get("amount_btc"), t0.get("fee_btc"),
            t0.get("input_count") or len(t0.get("input_addresses") or []),
            t0.get("output_count") or len(t0.get("output_addresses") or []),
        )
    else:
        typ = classify_group([])
        typ["label"] = (r.title or "Alert")[:48]

    peak = max((t.get("amount_btc") or 0) for t in txs) if txs else 0
    why_line = typ.get("why") or ""
    stored_why = json.loads(r.evidence or "[]")
    title = unique_title(typ, txs[0]["txid"] if len(txs) == 1 else None)
    if len(txs) <= 1 and r.lead_type and "Anomaly" in (r.lead_type or ""):
        title = unique_title(typ, txs[0]["txid"] if txs else None)

    return {
        "id": r.lead_id,
        "rank": rank,
        "priority": r.priority,
        "score": r.score,
        "confidence": r.confidence or r.score,
        "title": title,
        "why": stored_why,
        "summary": (
            f"{typ['label']}. {why_line} "
            + (f"Peak {peak:.2f} BTC across {len(txs)} linked txs. " if len(txs) > 1 else "")
            + (r.summary or "")
        ).strip(),
        "type": r.lead_type,
        "typology": typ.get("code"),
        "typology_label": typ.get("label"),
        "peak_btc": round(peak, 6),
        "txids": [t["txid"] for t in txs] if txs else txids,
        "wallets": wallets,
        "ips": json.loads(r.related_ips or "[]"),
        "transactions": txs,
        "wallet_details": [{
            "address": w,
            "explorer_url": f"https://www.blockchain.com/explorer/addresses/btc/{w}",
        } for w in wallets[:12]],
        "red_flags": explain_alert(
            db,
            [t["txid"] for t in txs] if txs else txids,
            wallets,
            r.lead_type or "",
            stats=stats,
        ),
    }


def _compact_alert(r, rank):
    txids = [t for t in json.loads(r.related_txids or "[]") if t]
    wallets = [w for w in json.loads(r.related_addresses or "[]") if w]
    # Cluster members sometimes store TXIDs in address field when entity is a tx
    txid = txids[0] if txids else ""
    if not txid and wallets and len(wallets[0]) >= 32 and all(c in "0123456789abcdef" for c in wallets[0][:32].lower()):
        txid = wallets[0]
        wallets = wallets[1:]
    why = json.loads(r.evidence or "[]")
    if not isinstance(why, list):
        why = [str(why)] if why else []
    why = [str(x).strip() for x in why if str(x).strip()][:5]
    summary = (r.summary or "").strip()
    # Short preview: first reason or first sentence of summary
    preview = why[0] if why else (summary.split(".")[0] + "." if summary else "Pattern flagged by analysis.")
    if len(preview) > 160:
        preview = preview[:157] + "…"
    return {
        "id": r.lead_id,
        "rank": rank,
        "priority": r.priority or "LOW",
        "score": r.score,
        "confidence": r.confidence or r.score,
        "title": r.title,
        "type": r.lead_type,
        "txid": txid,
        "tx_count": len(txids) or (1 if txid else 0),
        "wallet": wallets[0] if wallets else "",
        "why": why,
        "summary": summary,
        "reason_preview": preview,
    }


@app.get("/api/alerts")
def alerts(limit: int = 80, offset: int = 0, compact: bool = False, db: Session = Depends(get_db)):
    """Ranked alerts. compact=1 returns the full list (no pagination) for the dashboard."""
    total = db.query(Lead).count()
    if compact:
        rows = db.query(Lead).order_by(Lead.score.desc()).all()
        return {
            "total": total,
            "items": [_compact_alert(r, i + 1) for i, r in enumerate(rows)],
        }
    stats = dataset_stats(db) if total else None
    rows = db.query(Lead).order_by(Lead.score.desc()).offset(max(offset, 0)).limit(min(max(limit, 1), 200)).all()
    items = []
    for i, r in enumerate(rows):
        item = _alert_item(db, r, offset + i + 1, stats)
        if item:
            items.append(item)
    return {"total": total, "offset": offset, "limit": limit, "items": items}


def _resolve_alert_detail(db: Session, lead_id: str):
    r = db.query(Lead).filter(Lead.lead_id == lead_id).first()
    if not r:
        raise HTTPException(404, "Alert not found")
    rank = db.query(Lead).filter(Lead.score > (r.score or 0)).count() + 1
    item = _alert_item(db, r, rank, dataset_stats(db))
    if not item:
        # Still return a usable card for cluster/wallet leads with no TX rows left
        return {
            "id": r.lead_id,
            "rank": rank,
            "priority": r.priority or "LOW",
            "score": r.score,
            "confidence": r.confidence or r.score,
            "title": r.title,
            "why": json.loads(r.evidence or "[]"),
            "summary": r.summary or "",
            "type": r.lead_type,
            "typology": "cluster",
            "typology_label": r.lead_type or "Cluster",
            "peak_btc": 0,
            "txids": json.loads(r.related_txids or "[]"),
            "wallets": json.loads(r.related_addresses or "[]"),
            "ips": json.loads(r.related_ips or "[]"),
            "transactions": [],
            "wallet_details": [{
                "address": w,
                "explorer_url": f"https://www.blockchain.com/explorer/addresses/btc/{w}",
            } for w in json.loads(r.related_addresses or "[]")[:12]],
            "red_flags": None,
        }
    return item


@app.get("/api/alert-detail")
def alert_detail(id: str, db: Session = Depends(get_db)):
    """Evidence for one alert. Query param avoids SPA catch-all stealing path routes."""
    if not id:
        raise HTTPException(400, "Missing id")
    return _resolve_alert_detail(db, id)


@app.post("/api/ingest")
async def ingest(file: UploadFile = File(...), db: Session = Depends(get_db)):
    raw = await file.read()
    ext = Path(file.filename or "").suffix.lower()
    parsers = {".csv": parse_csv, ".json": parse_json, ".xml": parse_xml}
    if ext not in parsers:
        raise HTTPException(400, "Use CSV, JSON, or XML")
    try:
        records = parsers[ext](raw)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    if not records:
        raise HTTPException(400, "No valid records found")
    result = store_transactions(db, records, file.filename or "upload")
    parsed = result["parsed"]
    added = result["added"]
    skipped = result["skipped_duplicates"]
    updated = result["updated"]
    total = result["total_in_db"]
    parts = [f"Parsed {parsed:,}", f"added {added:,}"]
    if updated:
        parts.append(f"updated {updated:,}")
    if skipped:
        parts.append(f"skipped {skipped:,} duplicate TXIDs")
    parts.append(f"total in database {total:,}")
    message = ". ".join(parts) + "."
    if skipped and added == 0:
        message += " Those TXIDs were already loaded from another file — there is no 1 lakh row limit."
    return {
        "message": message,
        "parsed": parsed,
        "added": added,
        "updated": updated,
        "skipped_duplicates": skipped,
        "total_in_db": total,
    }


@app.post("/api/analyze")
def analyze(db: Session = Depends(get_db)):
    if not db.query(Transaction).count():
        raise HTTPException(400, "Upload data first")
    correlate_network_blockchain(db)
    return {"message": "Done", **run_full_analysis(db)}


@app.get("/api/alerts/exports")
def alerts_exports(limit: int = 20):
    """List saved alert snapshot files (newest first). Default last 20 datasheets."""
    return {"items": list_alert_exports(min(max(limit, 1), 50)), "postgres": postgres_status()}


def _alert_export_file(name: str) -> FileResponse:
    """Resolve a saved alerts_* datasheet under data/exports/ for download."""
    safe = Path(name).name
    ok = safe.startswith("alerts_") and (
        safe.endswith(".csv") or safe.endswith(".json") or safe.endswith(".pdf")
    )
    if not ok:
        raise HTTPException(400, "Invalid export filename")
    path = EXPORT_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Export file not found")
    if safe.endswith(".csv"):
        media = "text/csv"
    elif safe.endswith(".pdf"):
        media = "application/pdf"
    else:
        media = "application/json"
    return FileResponse(
        path,
        media_type=media,
        filename=safe,
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@app.get("/api/alerts/exports/download/{filename}")
def download_alert_export(filename: str):
    """Download one saved alerts_*.csv / alerts_*.json datasheet."""
    return _alert_export_file(filename)


@app.get("/api/alerts/exports/file")
def download_alert_export_query(name: str):
    """Same as path download; query form avoids SPA / encoding edge cases."""
    return _alert_export_file(name)


@app.get("/api/alerts/export.csv")
def export_alerts_csv_now(db: Session = Depends(get_db)):
    """
    Build a CSV of current SQLite alerts for immediate browser download
    (also archives a dated copy under data/exports/).
    """
    rows = db.query(Lead).order_by(Lead.score.desc()).all()
    if not rows:
        raise HTTPException(400, "No alerts yet — run analysis first")
    info = write_alerts_export(rows, meta={"source": "frontend_export", "leads": len(rows)}, db=db)
    path = EXPORT_DIR / info["filename"]
    if not path.exists():
        raise HTTPException(500, "Export failed to write file")
    name = info["filename"]
    return FileResponse(
        path,
        media_type="text/csv",
        filename=name,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/api/alerts/export.pdf")
def export_alerts_pdf_now(db: Session = Depends(get_db)):
    """Simple plain-language PDF of current alerts (also writes matching CSV)."""
    rows = db.query(Lead).order_by(Lead.score.desc()).all()
    if not rows:
        raise HTTPException(400, "No alerts yet — run analysis first")
    info = write_alerts_export(rows, meta={"source": "frontend_export_pdf", "leads": len(rows)}, db=db)
    pdf_name = info.get("pdf_filename") or ""
    path = EXPORT_DIR / pdf_name if pdf_name else None
    if not path or not path.exists():
        raise HTTPException(500, "PDF export failed to write file")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=pdf_name,
        headers={"Content-Disposition": f'attachment; filename="{pdf_name}"'},
    )


@app.post("/api/alerts/archive")
def alerts_archive_now(db: Session = Depends(get_db)):
    """Re-save current SQLite leads to a new datetime-named file (+ Postgres if configured)."""
    rows = db.query(Lead).order_by(Lead.score.desc()).all()
    if not rows:
        raise HTTPException(400, "No alerts yet — run analysis first")
    info = write_alerts_export(rows, meta={"source": "manual_archive", "leads": len(rows)}, db=db)
    return {"message": "Alerts archived", **info}


@app.get("/api/postgres/status")
def pg_status():
    return postgres_status()


@app.post("/api/reset")
def reset(db: Session = Depends(get_db)):
    """Delete all transactions, alerts, clusters, anomalies, correlations."""
    counts = _clear_all(db)
    return {"message": "All data cleared", "deleted": counts}


@app.get("/api/correlations", response_model=list[CorrelatedEvent])
def correlations(db: Session = Depends(get_db)):
    rows = db.query(Correlation).order_by(Correlation.correlation_score.desc()).limit(50).all()
    return [CorrelatedEvent(
        txid=r.txid, timestamp=r.timestamp, src_ip=r.src_ip, dst_ip=r.dst_ip,
        wallet_addresses=deserialize_addresses(r.wallet_addresses),
        amount_btc=r.amount_btc or 0, fee_btc=r.fee_btc or 0,
        script_type=r.script_type or "UNKNOWN",
        correlation_score=r.correlation_score or 0,
        network_observations=r.network_observations or 0,
    ) for r in rows]


@app.get("/api/anomalies", response_model=list[AnomalyResult])
def anomalies(limit: int = 10000, db: Session = Depends(get_db)):
    rows = db.query(Anomaly).order_by(Anomaly.anomaly_score.desc()).limit(min(max(limit, 1), 20000)).all()
    return [AnomalyResult(
        txid=r.txid, anomaly_score=r.anomaly_score,
        confidence=r.confidence or _to_conf(r.anomaly_score),
        is_anomaly=bool(r.is_anomaly),
        reasons=json.loads(r.reasons or "[]"), severity=r.severity,
        amount_btc=r.amount_btc or 0, timestamp=r.timestamp,
    ) for r in rows]


def _to_conf(score):
    return round(min(max((score or 0) * 100, 5), 99), 1)


@app.get("/api/clusters", response_model=list[ClusterMember])
def clusters(db: Session = Depends(get_db)):
    return [ClusterMember(
        address=r.address, cluster_id=r.cluster_id, entity_type=r.entity_type,
        total_volume_btc=r.total_volume_btc or 0,
        transaction_count=r.transaction_count or 0,
        linked_ips=deserialize_addresses(r.linked_ips),
    ) for r in db.query(Cluster).order_by(Cluster.cluster_id, Cluster.total_volume_btc.desc())]


@app.get("/api/geo/status")
def geoip_status():
    """Offline GeoIP engine: DB-IP Lite MMDB if present, else bundled prefix CSV."""
    return geo_status()


@app.post("/api/geo/download")
def geoip_download():
    """One-time fetch of DB-IP Lite (CC BY 4.0). After this, lookups stay offline."""
    try:
        return download_geoip()
    except Exception as e:
        raise HTTPException(502, f"GeoIP download failed: {e}") from e


@app.get("/api/leads", response_model=list[InvestigativeLead])
def leads(db: Session = Depends(get_db)):
    return [InvestigativeLead(
        lead_id=r.lead_id, priority=r.priority, score=r.score,
        confidence=r.confidence or r.score,
        title=r.title, summary=r.summary,
        evidence=json.loads(r.evidence or "[]"),
        related_txids=json.loads(r.related_txids or "[]"),
        related_addresses=json.loads(r.related_addresses or "[]"),
        related_ips=json.loads(r.related_ips or "[]"),
        lead_type=r.lead_type,
    ) for r in db.query(Lead).order_by(Lead.score.desc())]


if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/favicon.ico")
    def favicon():
        icon = FRONTEND / "assets" / "icon.png"
        if icon.exists():
            return FileResponse(icon, media_type="image/png")
        raise HTTPException(404, "favicon not found")

    @app.get("/{path:path}")
    def ui(path: str):
        # Never serve the SPA HTML for /api/* — that breaks fetch().json()
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, f"API route not found: /{path}")
        return FileResponse(FRONTEND / "index.html")
