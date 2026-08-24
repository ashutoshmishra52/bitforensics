from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from backend.database.db import Correlation, Transaction, deserialize_addresses, serialize_addresses, serialize_floats
from backend.models.schemas import CorrelatedEvent, TransactionRecord


def store_transactions(db: Session, records: list[TransactionRecord], source_file: str = "") -> dict:
    """Insert new TXIDs only. No row cap — duplicates are skipped by txid."""
    if not records:
        return {"added": 0, "skipped_duplicates": 0, "updated": 0, "parsed": 0, "total_in_db": 0}

    added = updated = skipped = 0
    batch: list[Transaction] = []
    chunk: list[TransactionRecord] = []

    for r in records:
        chunk.append(r)
        if len(chunk) < 500:
            continue
        added, updated, skipped, batch = _ingest_chunk(
            db, chunk, source_file, batch, added, updated, skipped,
        )
        chunk = []

    if chunk:
        added, updated, skipped, batch = _ingest_chunk(
            db, chunk, source_file, batch, added, updated, skipped,
        )

    if batch:
        db.bulk_save_objects(batch)
        db.commit()
        added += len(batch)

    total = db.query(Transaction).count()
    return {
        "added": added,
        "updated": updated,
        "skipped_duplicates": skipped,
        "parsed": len(records),
        "total_in_db": total,
    }


def _merge_tx(row: Transaction, rec: TransactionRecord, source_file: str) -> bool:
    """Fill missing fields on an existing row. Returns True if anything changed."""
    changed = False
    if source_file and not row.source_file:
        row.source_file = source_file
        changed = True
    if (row.amount_btc or 0) <= 0 and (rec.amount_btc or 0) > 0:
        row.amount_btc = rec.amount_btc
        changed = True
    if (row.fee_btc or 0) <= 0 and (rec.fee_btc or 0) > 0:
        row.fee_btc = rec.fee_btc
        changed = True
    if not row.input_addresses and rec.input_addresses:
        row.input_addresses = serialize_addresses(rec.input_addresses)
        changed = True
    if not row.output_addresses and rec.output_addresses:
        row.output_addresses = serialize_addresses(rec.output_addresses)
        changed = True
    if not row.src_ip and rec.src_ip:
        row.src_ip = rec.src_ip
        row.src_port = rec.src_port
        changed = True
    if not row.dst_ip and rec.dst_ip:
        row.dst_ip = rec.dst_ip
        row.dst_port = rec.dst_port
        changed = True
    if (row.input_count or 0) <= 0 and (rec.input_count or 0) > 0:
        row.input_count = rec.input_count
        changed = True
    if (row.output_count or 0) <= 0 and (rec.output_count or 0) > 0:
        row.output_count = rec.output_count
        changed = True
    return changed


def _ingest_chunk(db, chunk, source_file, batch, added, updated, skipped):
    known = {r.txid: r for r in db.query(Transaction).filter(
        Transaction.txid.in_([c.txid for c in chunk])
    ).all()}
    merged = False
    for r in chunk:
        existing = known.get(r.txid)
        if existing:
            if _merge_tx(existing, r, source_file):
                updated += 1
                merged = True
            else:
                skipped += 1
            continue
        batch.append(Transaction(
            txid=r.txid, timestamp=r.timestamp,
            src_ip=r.src_ip, src_port=r.src_port,
            dst_ip=r.dst_ip, dst_port=r.dst_port,
            input_addresses=serialize_addresses(r.input_addresses),
            output_addresses=serialize_addresses(r.output_addresses),
            input_amounts=serialize_floats(r.input_amounts),
            output_amounts=serialize_floats(r.output_amounts),
            amount_btc=r.amount_btc, fee_btc=r.fee_btc,
            input_count=r.input_count or len(r.input_addresses),
            output_count=r.output_count or len(r.output_addresses),
            script_type=r.script_type.value,
            geo_country=r.geo_country, asn=r.asn,
            source_file=source_file,
        ))
        known[r.txid] = batch[-1]
        if len(batch) >= 2000:
            db.bulk_save_objects(batch)
            db.commit()
            added += len(batch)
            batch = []
    if merged:
        db.commit()
    return added, updated, skipped, batch


def correlate_network_blockchain(db: Session, window_sec: int = 300) -> list[CorrelatedEvent]:
    """Correlate only rows with IP metadata. Skip entirely if none (avoids 100k empty inserts)."""
    db.query(Correlation).delete()
    db.commit()

    if db.query(Transaction).count() == 0:
        return []

    with_ip = db.query(Transaction).filter(
        (Transaction.src_ip.isnot(None)) | (Transaction.dst_ip.isnot(None))
    ).count()
    if with_ip == 0:
        return []

    txs = db.query(Transaction).filter(
        (Transaction.src_ip.isnot(None)) | (Transaction.dst_ip.isnot(None))
    ).order_by(Transaction.timestamp).limit(20000).all()

    by_ip = defaultdict(list)
    by_txid = defaultdict(list)
    for tx in txs:
        by_txid[tx.txid].append(tx)
        if tx.src_ip:
            by_ip[tx.src_ip].append(tx)
        if tx.dst_ip:
            by_ip[tx.dst_ip].append(tx)

    results = []
    batch = []
    for txid, group in by_txid.items():
        main = group[0]
        wallets, ips, hits = set(), set(), len(group)
        for tx in group:
            wallets |= set(deserialize_addresses(tx.input_addresses))
            wallets |= set(deserialize_addresses(tx.output_addresses))
            if tx.src_ip:
                ips.add(tx.src_ip)
            if tx.dst_ip:
                ips.add(tx.dst_ip)

        for ip in ips:
            for other in by_ip.get(ip, []):
                if other.txid == txid:
                    continue
                if abs((other.timestamp - main.timestamp).total_seconds()) <= window_sec:
                    hits += 1

        score = _score(main, hits, len(wallets), len(ips))
        event = CorrelatedEvent(
            txid=txid, timestamp=main.timestamp,
            src_ip=main.src_ip, dst_ip=main.dst_ip,
            wallet_addresses=sorted(wallets)[:20],
            amount_btc=main.amount_btc, fee_btc=main.fee_btc,
            script_type=main.script_type or "UNKNOWN",
            correlation_score=round(score, 4), network_observations=hits,
        )
        results.append(event)
        batch.append(Correlation(
            txid=event.txid, timestamp=event.timestamp,
            src_ip=event.src_ip, dst_ip=event.dst_ip,
            wallet_addresses=serialize_addresses(event.wallet_addresses),
            amount_btc=event.amount_btc, fee_btc=event.fee_btc,
            script_type=event.script_type,
            correlation_score=event.correlation_score,
            network_observations=event.network_observations,
        ))
        if len(batch) >= 1000:
            db.bulk_save_objects(batch)
            db.commit()
            batch = []

    if batch:
        db.bulk_save_objects(batch)
        db.commit()

    results.sort(key=lambda e: e.correlation_score, reverse=True)
    return results


def _score(tx, hits, wallets, ips) -> float:
    s = 0.15 if tx.src_ip or tx.dst_ip else 0
    if tx.src_ip and tx.dst_ip:
        s += 0.1
    s += min(hits / 10, 0.35) + min(wallets / 8, 0.25) + min(ips / 4, 0.15)
    if (tx.amount_btc or 0) > 1:
        s += 0.05
    return min(s, 1.0)
