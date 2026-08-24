from __future__ import annotations

import json
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.correlation.engine import correlate_network_blockchain, store_transactions
from backend.database.db import (
    Anomaly, Cluster, Correlation, Lead, Transaction,
    deserialize_addresses, get_db, init_db,
)
from backend.graph.builder import build_graph
from backend.ingest.parser import parse_csv, parse_json, parse_xml, parse_file
from backend.ml.analyzer import run_full_analysis
from backend.models.schemas import AnomalyResult, ClusterMember, CorrelatedEvent, DashboardStats, InvestigativeLead

app = FastAPI(title="BitForensics", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "dist"
SAMPLES = ROOT / "data" / "samples"


@app.on_event("startup")
def startup():
    init_db()
    from backend.database.db import SessionLocal
    db = SessionLocal()
    try:
        if db.query(Transaction).count() == 0 and SAMPLES.exists():
            for f in SAMPLES.iterdir():
                if f.suffix.lower() in (".csv", ".json", ".xml"):
                    store_transactions(db, parse_file(f), f.name)
            correlate_network_blockchain(db)
            run_full_analysis(db)
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "offline"}


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

    # Graph size without building full graph
    graph_nodes = min(total, 250) if anomalies == 0 else min(total, 250 + anomalies)
    return DashboardStats(
        total_transactions=total,
        total_network_events=network,
        correlated_events=corr,
        anomalies_detected=anomalies,
        clusters_found=len(cluster_ids),
        leads_generated=leads,
        total_volume_btc=round(float(volume), 4),
        graph_nodes=graph_nodes,
        graph_edges=0 if anomalies == 0 else min(graph_nodes * 2, 800),
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
    } for t in rows]


@app.get("/api/graph")
def graph(db: Session = Depends(get_db)):
    return build_graph(db)


@app.get("/api/alerts")
def alerts(db: Session = Depends(get_db)):
    """Ranked alert list with confidence, reasons, and full tx details."""
    items = []
    for r in db.query(Lead).order_by(Lead.score.desc()).all():
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
                # skip dust / zero-amount txs in alert cards
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
                })
            txs.append(detail)

        # Drop cluster/anomaly alerts that only referenced zero-amount txs
        if txids and not txs and not wallets:
            continue

        wallet_details = [{
            "address": w,
            "explorer_url": f"https://www.blockchain.com/explorer/addresses/btc/{w}",
        } for w in wallets[:12]]

        items.append({
            "id": r.lead_id,
            "rank": len(items) + 1,
            "priority": r.priority,
            "score": r.score,
            "confidence": r.confidence or r.score,
            "title": r.title,
            "why": json.loads(r.evidence or "[]"),
            "summary": r.summary,
            "type": r.lead_type,
            "txids": [t["txid"] for t in txs] if txs else txids,
            "wallets": wallets,
            "ips": json.loads(r.related_ips or "[]"),
            "transactions": txs,
            "wallet_details": wallet_details,
        })
    return items


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


@app.post("/api/reset")
def reset(db: Session = Depends(get_db)):
    """Delete all transactions, alerts, clusters, anomalies, correlations."""
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
def anomalies(db: Session = Depends(get_db)):
    return [AnomalyResult(
        txid=r.txid, anomaly_score=r.anomaly_score,
        confidence=r.confidence or _to_conf(r.anomaly_score),
        is_anomaly=bool(r.is_anomaly),
        reasons=json.loads(r.reasons or "[]"), severity=r.severity,
        amount_btc=r.amount_btc or 0, timestamp=r.timestamp,
    ) for r in db.query(Anomaly).order_by(Anomaly.anomaly_score.desc())]


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

    @app.get("/{path:path}")
    def ui(path: str):
        return FileResponse(FRONTEND / "index.html")
