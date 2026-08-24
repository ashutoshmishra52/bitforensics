# BIT-Forensics

**AI-Powered Monitoring & Analysis of Bitcoin Transaction Traffic**

> Smart India Hackathon 2026 · Problem Statement **26146** · National Technical Research Organisation (NTRO)

A complete **offline** forensic analysis system that ingests bulk Bitcoin transaction and network metadata, correlates network-layer observations with blockchain-layer data, and applies AI/ML to detect anomalies, cluster entities, and generate explainable investigative leads.

---

## Features

| Capability | Implementation |
|---|---|
| **Bulk Data Ingestion** | CSV, JSON, XML parsers with flexible field aliasing |
| **Network-Blockchain Correlation** | Links IP/port/timing to TXIDs, wallet addresses, amounts |
| **Anomaly Detection** | Isolation Forest with explainable feature attribution |
| **Entity Clustering** | DBSCAN grouping of related wallets and network nodes |
| **Investigative Leads** | Prioritized, explainable forensic leads with evidence chains |
| **Offline Operation** | SQLite storage, no external API dependencies |

## Quick Start

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the server
python run.py
```

Open **http://localhost:8000** in your browser.

Sample datasets in `data/samples/` are auto-loaded on first startup.

## Data Format

Supported fields (flexible naming):

| Field | Aliases |
|---|---|
| `txid` | transaction_id, tx_id, hash |
| `timestamp` | time, datetime, date, block_time |
| `src_ip` / `dst_ip` | source_ip, dest_ip, destination_ip |
| `src_port` / `dst_port` | source_port, dest_port |
| `input_addresses` | inputs, from_addresses |
| `output_addresses` | outputs, to_addresses |
| `amount_btc` | amount, value_btc, value |
| `fee_btc` | fee, transaction_fee |
| `script_type` | script, type (P2PKH, P2SH, P2WPKH, etc.) |

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | System health check |
| GET | `/api/stats` | Dashboard statistics |
| GET | `/api/transactions` | List ingested transactions |
| POST | `/api/ingest` | Upload CSV/JSON/XML file |
| POST | `/api/analyze` | Run full ML analysis pipeline |
| GET | `/api/correlations` | Network-blockchain correlations |
| GET | `/api/anomalies` | Detected anomalies with explanations |
| GET | `/api/clusters` | Entity cluster memberships |
| GET | `/api/leads` | Prioritized investigative leads |

## Architecture

```
bitcoin/
├── backend/
│   ├── main.py              # FastAPI server
│   ├── ingest/parser.py     # CSV/JSON/XML ingestion
│   ├── correlation/engine.py # Network ↔ blockchain linking
│   ├── ml/analyzer.py       # Isolation Forest + DBSCAN + leads
│   ├── database/db.py       # SQLite ORM
│   └── models/schemas.py    # Pydantic models
├── frontend/dist/           # Dashboard UI
├── data/samples/            # Sample datasets
└── run.py                   # Entry point
```

## Demo Flow (for judges)

1. **Dashboard** — View pre-loaded stats from sample data
2. **Transactions** — Browse ingested network + blockchain records
3. **Run Analysis** — Click to execute correlation + ML pipeline
4. **Anomalies** — Review flagged transactions with explainable reasons
5. **Clusters** — See grouped wallet entities (mixers, high-volume actors)
6. **Investigative Leads** — Prioritized forensic leads with evidence
7. **Data Ingestion** — Upload additional CSV/JSON/XML files

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy, scikit-learn
- **ML:** Isolation Forest (anomaly detection), DBSCAN (clustering)
- **Storage:** SQLite (fully offline)
- **Frontend:** Vanilla JS dashboard with dark forensic theme

## Team Notes

- System runs entirely offline — suitable for air-gapped forensic environments
- All ML models train on ingested data at analysis time (no pre-trained external models)
- Explainability is built into every anomaly flag and investigative lead
