# BitForensics

Offline tool to ingest Bitcoin transaction dumps (CSV / JSON / XML), correlate network metadata with on-chain data, run anomaly detection, and review alerts in a browser UI.

Works on **Windows**, **macOS**, and **Linux**. No cloud required after setup.

---

## What you need

| Tool | Version |
|------|---------|
| Python | 3.9 or newer |
| Node.js | 16 or newer (for the easy launcher) |

Check:

```bash
python3 --version   # macOS / Linux
node --version
npm --version
```

Windows (Command Prompt or PowerShell):

```bat
python --version
node --version
```

If `python` fails on Windows, try `py --version`.

---

## Quick start

Clone the repo, install once, run:

```bash
git clone https://github.com/ashutoshmishra52/bitforensics.git
cd bitforensics
npm install
npm run dev
```

Open **http://localhost:8000**

First run creates a Python virtualenv and installs dependencies (may take a few minutes). Stop the server with `Ctrl+C`.

---

## macOS (including MacBook)

Same as above. If you prefer Python only:

```bash
cd bitforensics
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Then open http://localhost:8000

**Try it without your own file:** Link Graph → **Demo data**, or Upload → pick something from `data/samples/`.

**Optional:** set `BITFORENSICS_SEED_SAMPLES=1` before `npm run dev` to auto-load sample files on first start (dev only).

---

## Linux

```bash
git clone https://github.com/ashutoshmishra52/bitforensics.git
cd bitforensics
npm install
npm run dev
```

Python-only:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Different port:

```bash
PORT=8001 npm run dev
```

Packaged install (tar.gz): see [packaging/README.md](packaging/README.md).

---

## Windows

1. Install [Python 3.11+](https://www.python.org/downloads/windows/) — tick **Add python.exe to PATH**
2. Install [Node.js LTS](https://nodejs.org/)
3. Open a **new** terminal:

```bat
git clone https://github.com/ashutoshmishra52/bitforensics.git
cd bitforensics
npm install
npm run dev
```

Browser: http://localhost:8000

**Without npm** (Python only):

```bat
cd bitforensics
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

### Windows issues

| Problem | What to do |
|---------|------------|
| `python` not found | Reinstall Python with PATH, or use `py -3` |
| `npm` not found | Reinstall Node, open a new terminal |
| Microsoft Store Python stub | Settings → App execution aliases → turn off `python.exe` |
| Port 8000 in use | `set PORT=8001` then `npm run dev` |

---

## Normal workflow

1. **Upload** — CSV, JSON, or XML (see columns below)
2. **Run Analysis** — builds models and alerts
3. **Alerts / Link Graph** — review flagged transactions
4. **Export** — CSV (full detail + `reason` column) and PDF (simple summary)

Exports are saved under `data/exports/` as matching `alerts_*.csv` and `alerts_*.pdf`.

---

## Input file columns

Parser accepts common aliases. Minimum useful fields:

| Field | Also accepted as |
|-------|------------------|
| `txid` | transaction_id, hash |
| `timestamp` | time, datetime |
| `src_ip`, `dst_ip` | source_ip, dest_ip |
| `src_port`, `dst_port` | source_port, dest_port |
| `input_addresses[]`, `output_addresses[]` | inputs, outputs |
| `input_amounts[]`, `output_amounts[]` | per-address amounts |
| `amount_btc`, `fee_btc` | amount, fee |
| `script_type` | P2PKH, P2SH, … |
| `geo_country`, `asn` | filled from GeoIP if missing |

Sample files live in `data/samples/`.

---

## GeoIP (optional)

Bundled prefix CSV works offline. For better country/ASN lookup, use Upload → **Download DB-IP Lite** once (needs internet that one time). After that, lookups stay offline.

---

## PostgreSQL (optional)

SQLite is the main database. To also archive alerts in Postgres:

```bash
docker compose up -d
cp .env.example .env
# edit POSTGRES_URL in .env
pip install -r requirements.txt
python run.py
```

---

## Project layout

```
backend/          FastAPI, ingest, ML, graph
frontend/dist/    Dashboard (static)
data/samples/     Example input files
data/exports/     Generated CSV + PDF (gitignored)
run.py            Start server
scripts/dev.js    npm run dev helper
```

Technical notes: [APPROACH.md](APPROACH.md)

---

## API (short list)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Health check |
| GET | `/api/stats` | Dashboard counts |
| POST | `/api/ingest` | Upload file |
| POST | `/api/analyze` | Run ML pipeline |
| GET | `/api/alerts` | Ranked alerts |
| GET | `/api/graph` | Link graph data |
| GET | `/api/alerts/export.csv` | Download current CSV |
| GET | `/api/alerts/export.pdf` | Download current PDF |
| GET | `/api/alerts/exports` | List past exports |

---

## Stack

Python · FastAPI · SQLAlchemy · scikit-learn · vanilla JS frontend

Alerts are investigative leads, not legal proof.
