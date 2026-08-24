from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "bitforensics.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    txid = Column(String(64), index=True, nullable=False)
    timestamp = Column(DateTime, index=True, nullable=False)
    src_ip = Column(String(45), index=True)
    src_port = Column(Integer)
    dst_ip = Column(String(45), index=True)
    dst_port = Column(Integer)
    input_addresses = Column(Text)
    output_addresses = Column(Text)
    input_amounts = Column(Text)
    output_amounts = Column(Text)
    amount_btc = Column(Float, default=0.0)
    fee_btc = Column(Float, default=0.0)
    input_count = Column(Integer, default=0)
    output_count = Column(Integer, default=0)
    script_type = Column(String(20), default="UNKNOWN")
    geo_country = Column(String(10))
    asn = Column(String(20))
    source_file = Column(String(255))


class Correlation(Base):
    __tablename__ = "correlations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    txid = Column(String(64), index=True, nullable=False)
    timestamp = Column(DateTime)
    src_ip = Column(String(45))
    dst_ip = Column(String(45))
    wallet_addresses = Column(Text)
    amount_btc = Column(Float)
    fee_btc = Column(Float)
    script_type = Column(String(20))
    correlation_score = Column(Float)
    network_observations = Column(Integer, default=1)


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    txid = Column(String(64), index=True, nullable=False)
    anomaly_score = Column(Float)
    confidence = Column(Float)
    is_anomaly = Column(Integer, default=0)
    reasons = Column(Text)
    severity = Column(String(20))
    amount_btc = Column(Float)
    timestamp = Column(DateTime)


class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(100), index=True)
    cluster_id = Column(Integer, index=True)
    entity_type = Column(String(50))
    total_volume_btc = Column(Float)
    transaction_count = Column(Integer)
    linked_ips = Column(Text)


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(20), unique=True, index=True)
    priority = Column(String(20))
    score = Column(Float)
    confidence = Column(Float)
    title = Column(String(255))
    summary = Column(Text)
    evidence = Column(Text)
    related_txids = Column(Text)
    related_addresses = Column(Text)
    related_ips = Column(Text)
    lead_type = Column(String(50))


NEW_COLS = [
    ("transactions", "input_amounts", "TEXT"),
    ("transactions", "output_amounts", "TEXT"),
    ("transactions", "geo_country", "VARCHAR(10)"),
    ("transactions", "asn", "VARCHAR(20)"),
    ("transactions", "input_count", "INTEGER"),
    ("transactions", "output_count", "INTEGER"),
    ("anomalies", "confidence", "FLOAT"),
    ("leads", "confidence", "FLOAT"),
]


def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        for table, col, typ in NEW_COLS:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
                conn.commit()
            except Exception:
                pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def serialize_addresses(addrs: list[str]) -> str:
    return json.dumps(addrs)


def deserialize_addresses(raw: str | None) -> list[str]:
    return json.loads(raw) if raw else []


def serialize_floats(vals: list[float]) -> str:
    return json.dumps(vals)


def deserialize_floats(raw: str | None) -> list[float]:
    return json.loads(raw) if raw else []
