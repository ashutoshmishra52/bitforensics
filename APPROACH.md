# Technical approach

Architecture and ML design notes for BitForensics. See [README.md](README.md) for install and usage.

## Problem (as stated)

Bitcoin’s pseudonymous P2P design lets illicit funds move, layer, and cash out (ransomware, darknet, extortion, laundering) outside traditional financial surveillance. NTRO needs an **offline** system that:

1. Ingests bulk Bitcoin **transaction + network** metadata (CSV / JSON / XML).
2. Correlates **network-layer** (IP, port, timing) with **blockchain-layer** (wallets, TXID, amounts).
3. Applies **AI/ML** (a working model, not rules-only) to detect anomalies, cluster entities, and emit **ranked, explainable** investigative leads.
4. Shows findings on a dashboard / link-analysis view.

## Mapping to expected solution

| Expected deliverable | What we built |
|---|---|
| Workable complete offline Linux solution | FastAPI + SQLite + vanilla UI; `python run.py` → `http://localhost:8000` |
| Ingestion, correlation, AI/ML in a code repo | `backend/ingest`, `backend/correlation`, `backend/ml` |
| Short technical write-up | This file |
| Dashboard with flagged entities and evidence | Overview, Alerts (why + confidence), Link Graph (red = flagged) |

## 1. Ingest & parse bulk metadata

Parser: `backend/ingest/parser.py`. Formats: **CSV, JSON, XML**. Field aliases absorb messy synthetic dumps.

| PS field | Stored / used |
|---|---|
| `timestamp` | `transactions.timestamp` |
| `src_ip`, `dst_ip`, `src_port`, `dst_port` | columns + graph IP nodes |
| `txid` | unique key (same TXID in two files counts once) |
| `input_addresses[]`, `output_addresses[]` | JSON lists |
| `input_amounts[]`, `output_amounts[]` | JSON lists; sum used if total amount missing |
| `amount` / fee / `script_type` | Isolation Forest features |
| `geo_country` / `asn` | file fields **or** offline GeoIP lookup |

Missing geo is filled from IP via `backend/geo/lookup.py`.

## 2. Network ↔ blockchain correlation

`backend/correlation/engine.py` joins observations around the same TXID in a timing window. Score (0–1) uses IP coverage, repeated IPs, wallet fan-out, and amount. Output: `correlations` table and IP/wallet/tx **entity graph** (`backend/graph/builder.py`).

## 3. AI/ML (working models, not rule-only)

Trained **on the ingested dump at “Run Analysis”** (unsupervised). No cloud APIs.

**Anomaly detection — Isolation Forest (scikit-learn)**  
Features: log amount, log fee, fee ratio, input/output counts, I/O ratio, IP present, hour, P2SH, foreign geo, amount z-score.  
Outputs: anomaly score → **confidence %** and severity.

**Entity clustering — MiniBatchKMeans** (same sklearn family as the suggested clustering focus; chosen so 100k rows finish on a laptop). Groups wallets/txs by volume, counts, and linked IPs. Cluster labels feed typology (mixer / peel / consolidation / whale / dusting / etc.).

Rules and the 120 AML/KYT checklist are used **after** the model flags a row: they write the *why*, they do not replace Isolation Forest.

## 4. Ranked, explainable alerts

Leads merge Isolation Forest hits + cluster groups + high correlations, sorted by score.

Each alert includes:

- **Priority** and **confidence**
- **Typology** (human label)
- **Evidence bullets** (feature deviations)
- **Red-flag panel** (matched conditions from the 120-list, intel-only flags not auto-claimed)
- Linked **TXIDs, wallets, IPs**, geo/ASN, ports

## 5. Dashboard / link analysis

Offline HTML/CSS/JS (`frontend/dist/`): Overview stats, priority leads, highest-risk txs, **link graph** (IP / wallet / tx; red border = flagged), full Alerts, Transactions, Clusters, Upload.

## 6. GeoIP (open-source, downloadable, then offline)

PS: *integrate open source downloadable Geo IP database*.

| Mode | When |
|---|---|
| Bundled prefix CSV `data/geoip.csv` | Default; **no internet** |
| **DB-IP Lite** Country + ASN MaxMind `.mmdb` (CC BY 4.0) | Upload page → **Download DB-IP Lite** once |

After download, files live in `data/geoip/` and lookups stay air-gapped. APIs: `GET /api/geo/status`, `POST /api/geo/download`.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.9+, FastAPI |
| ML | scikit-learn Isolation Forest + MiniBatchKMeans |
| Storage | SQLite |
| Geo | DB-IP Lite MMDB (`maxminddb`) or bundled CSV |
| Frontend | Plain HTML/CSS/JS |
| Platform | Linux (macOS for dev) |

## Explainability method

1. **Model score** — Isolation Forest decision function → confidence 0–100%.
2. **Feature attribution** — which features deviate (amount, fan-out, fee, geo, time).
3. **Evidence list** — plain-language bullets on the alert card.
4. **Typology + 120-condition flags** — investigative language, not a court finding.
5. **Graph context** — flagged nodes highlighted in link analysis.

## Limitations

- Synthetic/demo data only (no seized or live intercept).
- Graph is sampled force-layout for large dumps.
- DB-IP download needs internet **once**; daily use is offline.

## How to run (Linux)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
# http://localhost:8000
# Upload CSV/JSON/XML → Run Analysis
```
