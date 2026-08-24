# BIT-Forensics

**AI-Powered Monitoring & Analysis of Bitcoin Transaction Traffic**

> Smart India Hackathon 2026 · Problem Statement **26146** · National Technical Research Organisation (NTRO)

A complete **offline** forensic system: ingest bulk Bitcoin transaction/network metadata (CSV/JSON/XML), correlate IPs/ports/timing with wallets/TXIDs/amounts, run Isolation Forest + clustering, and show **ranked, explainable** leads on a dashboard.

Technical write-up: **[APPROACH.md](APPROACH.md)**.

---

## PS coverage

| Challenge objective | Status |
|---|---|
| Ingest timestamp, src/dst IP & port, TXID, input/output wallets, amounts, fee, script type | Parser + SQLite |
| Entity/transaction graph (IP ↔ wallet ↔ tx) | Link Graph tab |
| Working AI/ML model (not rules-only) | Isolation Forest + MiniBatchKMeans |
| Ranked explainable alerts + confidence | Alerts + Overview |
| Dashboard / link-analysis | Vanilla UI; `npm run dev` on Win/macOS/Linux |
| Open-source downloadable GeoIP (country/ASN) | Bundled CSV + optional DB-IP Lite MMDB |
| Offline Linux prototype | `python run.py` |

---

## Install & run

Needs **Python 3.9+** and **Node.js 16+** (for `npm run dev`). Browser: **http://localhost:8000**.

### Windows (Command Prompt or PowerShell)

1. Install [Git for Windows](https://git-scm.com/download/win).
2. Install [Python 3.11+](https://www.python.org/downloads/windows/). On the installer:
   - tick **Add python.exe to PATH**
   - then **Install Now**
3. Install [Node.js LTS](https://nodejs.org/). Leave **Add to PATH** checked. Close and reopen the terminal after install.
4. Confirm tools work (new window):

```bat
python --version
node --version
npm --version
```

If `python` is missing, try `py --version`. If Node is missing, reinstall Node and reopen the terminal.

5. Clone and start:

```bat
git clone https://github.com/ashutoshmishra52/bitforensics.git
cd bitforensics
npm install
npm run dev
```

First run creates `venv` and installs Python packages (can take a few minutes). Then open **http://localhost:8000**. Stop with `Ctrl+C`.

**If `npm run dev` fails on Windows**

| Problem | Fix |
|---|---|
| `python` / `py` not found | Reinstall Python and tick **Add python.exe to PATH** |
| `npm` is not recognized | Reinstall Node.js LTS, then open a **new** Command Prompt |
| `Microsoft Store` Python stub | Disable the app execution alias: Settings → Apps → Advanced app settings → App execution aliases → turn off `python.exe` |
| `Activate.ps1` execution policy | You do not need to activate venv yourself; `npm run dev` uses `venv\Scripts\python.exe` |
| Port 8000 already in use | Close the other app, or set `set PORT=8001` then `npm run dev` |

**Windows without npm** (Python only):

```bat
cd bitforensics
py -3 -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python run.py
```

### macOS / Linux

```bash
git clone https://github.com/ashutoshmishra52/bitforensics.git
cd bitforensics
npm install
npm run dev
```

Python-only:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

Optional (needs internet once): Upload page → **Download DB-IP Lite**. After that, GeoIP stays offline.

## Data format (minimum PS fields)

| Field | Aliases / notes |
|---|---|
| `txid` | transaction_id, tx_id, hash |
| `timestamp` | time, datetime, block_time |
| `src_ip` / `dst_ip` | source_ip, dest_ip |
| `src_port` / `dst_port` | source_port, dest_port |
| `input_addresses[]` | inputs, from_addresses |
| `output_addresses[]` | outputs, to_addresses |
| `input_amounts[]` / `output_amounts[]` | summed if total amount missing |
| `amount_btc` | amount, value_btc, input_value_btc |
| `fee_btc` | fee, transaction_fee |
| `script_type` | P2PKH, P2SH, P2WPKH, … |
| `geo_country` / `asn` | or filled from GeoIP |

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Offline health + GeoIP engine |
| GET | `/api/stats` | Dashboard statistics |
| GET | `/api/transactions` | Ingested rows (incl. amounts lists, geo) |
| POST | `/api/ingest` | Upload CSV/JSON/XML |
| POST | `/api/analyze` | Correlation + ML |
| GET | `/api/graph` | Link-analysis nodes/edges |
| GET | `/api/alerts` | Ranked leads (paginated) |
| GET | `/api/anomalies` | Isolation Forest hits |
| GET | `/api/clusters` | Entity clusters |
| GET | `/api/correlations` | Network–chain joins |
| GET | `/api/geo/status` | CSV vs DB-IP MMDB |
| POST | `/api/geo/download` | Fetch DB-IP Lite once |

## Architecture

```
bitcoin/
├── backend/
│   ├── main.py                 # FastAPI
│   ├── ingest/parser.py        # CSV/JSON/XML
│   ├── correlation/engine.py   # Network ↔ chain
│   ├── ml/analyzer.py          # Isolation Forest + MiniBatchKMeans
│   ├── ml/typology.py          # Mixer / peel / dusting labels
│   ├── ml/red_flags.py         # Explainability (120 conditions)
│   ├── geo/lookup.py           # Offline GeoIP
│   ├── geo/download.py         # DB-IP Lite fetch
│   ├── graph/builder.py        # IP / wallet / tx graph
│   ├── database/db.py          # SQLite
│   └── models/schemas.py
├── frontend/dist/              # Dashboard
├── data/samples/               # Demo files
├── data/geoip.csv              # Bundled prefix table
├── APPROACH.md
└── run.py
```

## Demo flow (judges)

1. Upload bulk CSV/JSON/XML (e.g. `bitcoin_transactions_100k.csv`).
2. Stay on Overview → **Run Analysis**.
3. Read **Priority leads** and **Highest-risk transactions** (confidence + why).
4. Open **Alerts** for TXID, wallets, IPs, geo/ASN, red flags.
5. Open **Link Graph** for flagged entities.
6. Optional: download GeoIP DB, then work fully offline.

## Tech stack

- **Backend:** Python 3.9+, FastAPI, SQLAlchemy, scikit-learn, maxminddb
- **ML:** Isolation Forest (anomalies), MiniBatchKMeans (entities)
- **Storage:** SQLite
- **Geo:** DB-IP Lite (CC BY 4.0) or bundled CSV
- **Frontend:** Vanilla JS (no npm build)

## Notes

- Fully offline after install (and after optional GeoIP download).
- Models train on the uploaded dump at analysis time.
- Alerts are investigative leads, not proof of a crime.
