# Technical Approach — BitForensics (SIH 2026, PS 26146)

## Problem

Bitcoin's pseudonymous design lets bad actors move illicit funds while hiding behind wallet addresses and P2P network hops. NTRO needs an **offline** tool that joins network-layer data (IP, port, timing) with blockchain data (TXID, wallets, amounts) and surfaces suspicious activity with clear reasons.

## Our Approach

### 1. Data Ingestion

Bulk metadata comes in as **CSV, JSON, or XML**. The parser normalises field names (e.g. `source_ip` → `src_ip`) and extracts:

`timestamp`, `src/dst IP & port`, `txid`, `input/output addresses`, `input/output amounts`, `fee`, `script type`, `geo_country`, `asn`.

If geo fields are missing, we look up country/ASN from a bundled offline CSV (`data/geoip.csv`). No live internet needed.

### 2. Network ↔ Blockchain Correlation

For each TXID we collect linked wallet addresses and IP observations within a 5-minute window. A correlation score (0–1) is computed from:

- IP coverage (source + destination present)
- Number of network observations sharing the same IP
- Wallet fan-out
- Transaction amount

This links *who sent on the network* to *what moved on-chain*.

### 3. Entity Graph

We build a graph with three node types:

| Node | Links to |
|------|----------|
| IP | transaction (src/dst) |
| Wallet | transaction (input/output) |
| Transaction | wallets and IPs |

Flagged nodes (from ML alerts) get a red border in the link-analysis view.

### 4. AI/ML Models (not rule-only)

**Anomaly detection — Isolation Forest (scikit-learn)**

- Trains on ingested data at analysis time (unsupervised)
- Features: amount, fee ratio, input/output count, hour, script type, geo flag, IP presence
- Outputs anomaly score + confidence (0–100%)
- Explainability: after the model flags a row, we attach human-readable reasons (high amount, mixing pattern, foreign IP, etc.)

**Entity clustering — DBSCAN (scikit-learn)**

- Groups wallets by volume, tx count, linked IPs, and counterparties
- Labels clusters as "possible mixer", "high volume", "multi-node", etc.

Rules are used only for **explanation text**, not for the primary detection decision.

### 5. Ranked Alerts

Alerts merge three sources, sorted by score:

1. Isolation Forest anomalies (with confidence)
2. DBSCAN wallet clusters
3. High-scoring network-blockchain correlations

Each alert includes: priority, confidence %, summary, and a bullet list of *why* it was flagged.

### 6. Dashboard

Simple offline web UI (no npm build needed):

- Overview stats
- **Link graph** — canvas force-layout of IP / wallet / tx nodes
- **Alerts** — ranked list with confidence and reasons
- Transactions table with geo/ASN
- File upload

## Stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.9+, FastAPI |
| ML | scikit-learn (Isolation Forest, DBSCAN) |
| Storage | SQLite |
| Geo | Offline CSV lookup |
| Frontend | Plain HTML/CSS/JS |
| Platform | Linux (also runs on macOS for dev) |

## Explainability Method

1. **Model score** — Isolation Forest decision function → confidence %
2. **Feature attribution** — check which features deviate (amount, fan-out, fee, geo, time)
3. **Evidence list** — plain-language bullets shown in the alert panel
4. **Graph context** — flagged nodes highlighted in link-analysis view

## Limitations

- Synthetic/demo dataset only (no real seized data)
- Geo lookup uses a small bundled prefix table; production would use MaxMind GeoLite2 offline DB
- Graph layout is basic force-directed; large datasets may need sampling

## How to Run (Linux)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
# open http://localhost:8000
```
