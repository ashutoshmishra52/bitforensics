from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ScriptType(str, Enum):
    P2PKH = "P2PKH"
    P2SH = "P2SH"
    P2WPKH = "P2WPKH"
    P2WSH = "P2WSH"
    P2TR = "P2TR"
    UNKNOWN = "UNKNOWN"


class TransactionRecord(BaseModel):
    txid: str
    timestamp: datetime
    src_ip: Optional[str] = None
    src_port: Optional[int] = None
    dst_ip: Optional[str] = None
    dst_port: Optional[int] = None
    input_addresses: list[str] = Field(default_factory=list)
    output_addresses: list[str] = Field(default_factory=list)
    input_amounts: list[float] = Field(default_factory=list)
    output_amounts: list[float] = Field(default_factory=list)
    input_count: int = 0
    output_count: int = 0
    amount_btc: float = 0.0
    fee_btc: float = 0.0
    script_type: ScriptType = ScriptType.UNKNOWN
    geo_country: Optional[str] = None
    asn: Optional[str] = None


class CorrelatedEvent(BaseModel):
    txid: str
    timestamp: datetime
    src_ip: Optional[str]
    dst_ip: Optional[str]
    wallet_addresses: list[str]
    amount_btc: float
    fee_btc: float
    script_type: str
    correlation_score: float
    network_observations: int


class AnomalyResult(BaseModel):
    txid: str
    anomaly_score: float
    confidence: float = 0.0
    is_anomaly: bool
    reasons: list[str]
    severity: str
    amount_btc: float
    timestamp: datetime


class ClusterMember(BaseModel):
    address: str
    cluster_id: int
    entity_type: str
    total_volume_btc: float
    transaction_count: int
    linked_ips: list[str]


class InvestigativeLead(BaseModel):
    lead_id: str
    priority: str
    score: float
    confidence: float = 0.0
    title: str
    summary: str
    evidence: list[str]
    related_txids: list[str]
    related_addresses: list[str]
    related_ips: list[str]
    lead_type: str


class DashboardStats(BaseModel):
    total_transactions: int
    total_network_events: int
    correlated_events: int
    anomalies_detected: int
    clusters_found: int
    leads_generated: int
    total_volume_btc: float
    graph_nodes: int = 0
    graph_edges: int = 0
    sources: dict[str, int] = Field(default_factory=dict)
