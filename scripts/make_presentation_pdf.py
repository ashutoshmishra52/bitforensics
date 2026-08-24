#!/usr/bin/env python3
"""Build a simple presentation PDF for BitForensics (SIH 2026 PS 26146)."""
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "BitForensics_Project_Presentation.pdf"

NAVY = HexColor("#162033")
BLUE = HexColor("#1d4ed8")
INK = HexColor("#1a1a1a")
MUTED = HexColor("#475467")
LINE = HexColor("#dde3ea")
PILL = HexColor("#eef2ff")


def styles():
    base = getSampleStyleSheet()
    s = {
        "cover_kicker": ParagraphStyle(
            "cover_kicker", parent=base["Normal"], fontName="Helvetica",
            fontSize=10, textColor=HexColor("#8b97a8"), alignment=TA_CENTER,
            spaceAfter=8, tracking=1,
        ),
        "cover_title": ParagraphStyle(
            "cover_title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=26, textColor=white, alignment=TA_CENTER, spaceAfter=8, leading=32,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub", parent=base["Normal"], fontName="Helvetica",
            fontSize=12, textColor=HexColor("#c5d0de"), alignment=TA_CENTER, leading=18,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=16, textColor=NAVY, spaceBefore=14, spaceAfter=8, leading=20,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12.5, textColor=BLUE, spaceBefore=10, spaceAfter=5, leading=16,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName="Helvetica",
            fontSize=10.5, textColor=INK, leading=15, alignment=TA_JUSTIFY, spaceAfter=7,
        ),
        "left": ParagraphStyle(
            "left", parent=base["Normal"], fontName="Helvetica",
            fontSize=10.5, textColor=INK, leading=15, alignment=TA_LEFT, spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["Normal"], fontName="Helvetica",
            fontSize=10.5, textColor=INK, leading=14.5, leftIndent=4,
        ),
        "speak": ParagraphStyle(
            "speak", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=10, textColor=MUTED, leading=14, spaceBefore=4, spaceAfter=8,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontName="Helvetica",
            fontSize=8, textColor=MUTED, alignment=TA_CENTER,
        ),
        "th": ParagraphStyle(
            "th", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9, textColor=NAVY, leading=12,
        ),
        "td": ParagraphStyle(
            "td", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, textColor=INK, leading=12,
        ),
    }
    return s


def bullets(items, st):
    return ListFlowable(
        [ListItem(Paragraph(i, st["bullet"]), leftIndent=12, bulletColor=BLUE) for i in items],
        bulletType="bullet",
        start="•",
        leftIndent=16,
        spaceAfter=8,
    )


def kv_table(rows, st, col1=42, col2=138):
    data = [[Paragraph(a, st["th"]), Paragraph(b, st["td"])] for a, b in rows]
    t = Table(data, colWidths=[col1 * mm, col2 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PILL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
    ]))
    return t


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, A4[1] - 12 * mm, A4[0], 12 * mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(18 * mm, A4[1] - 7.5 * mm, "BitForensics  ·  SIH 2026  ·  PS 26146  ·  NTRO")
    canvas.setFillColor(HexColor("#eef1f4"))
    canvas.rect(0, 0, A4[0], 12 * mm, fill=1, stroke=0)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(18 * mm, 5 * mm, "Offline Bitcoin forensic analysis  ·  http://localhost:8000")
    canvas.drawRightString(A4[0] - 18 * mm, 5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def cover(c, doc):
    c.saveState()
    c.setFillColor(NAVY)
    c.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    c.setFillColor(HexColor("#1d4ed8"))
    c.rect(0, 42 * mm, A4[0], 3 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica", 11)
    c.drawCentredString(A4[0] / 2, A4[1] - 48 * mm, "SMART INDIA HACKATHON 2026")
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(A4[0] / 2, A4[1] - 72 * mm, "BitForensics")
    c.setFont("Helvetica", 13)
    c.drawCentredString(A4[0] / 2, A4[1] - 88 * mm, "AI-Powered Monitoring of Bitcoin Transaction Traffic")
    c.setFont("Helvetica", 11)
    c.drawCentredString(A4[0] / 2, A4[1] - 108 * mm, "Problem Statement 26146")
    c.drawCentredString(A4[0] / 2, A4[1] - 122 * mm, "National Technical Research Organisation (NTRO)")
    c.setStrokeColor(HexColor("#3d4f6f"))
    c.line(50 * mm, A4[1] - 136 * mm, A4[0] - 50 * mm, A4[1] - 136 * mm)
    c.setFont("Helvetica", 11)
    c.drawCentredString(A4[0] / 2, A4[1] - 155 * mm, "How the project works  ·  Models  ·  Tech flow")
    c.drawCentredString(A4[0] / 2, A4[1] - 170 * mm, "Simple notes for a live presentation")
    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#8b97a8"))
    c.drawCentredString(A4[0] / 2, 28 * mm, "Offline  ·  Linux / Windows / macOS  ·  No live Bitcoin node required")
    c.restoreState()


def build():
    st = styles()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title="BitForensics — Project Presentation",
        author="BitForensics team",
    )
    story = []

    story.append(Paragraph("1. One-minute story (say this first)", st["h1"]))
    story.append(Paragraph(
        "Bitcoin wallets have no name. Criminals can move ransomware money, darknet proceeds, "
        "or extortion payments by splitting funds across many addresses. Banks cannot see this "
        "the usual way. NTRO asked for an <b>offline</b> tool that reads a bulk dump of Bitcoin "
        "metadata, joins <b>network clues</b> (IP, port, time) with <b>on-chain clues</b> "
        "(TXID, wallets, amount), and uses a <b>real ML model</b> — not only if-else rules — "
        "to rank suspicious activity with a reason and a confidence score.",
        st["body"],
    ))
    story.append(Paragraph(
        "Speaker line: “Yeh software seized / synthetic dump ko locally padhta hai, graph banata hai, "
        "Isolation Forest se outliers nikalta hai, aur investigator ko ranked leads deta hai.”",
        st["speak"],
    ))

    story.append(Paragraph("2. What the user actually does", st["h1"]))
    story.append(bullets([
        "<b>Start:</b> <font face='Courier'>npm run dev</font> or <font face='Courier'>python run.py</font> → open <b>http://localhost:8000</b>.",
        "<b>Upload</b> a CSV / JSON / XML file (demo: a 100k-row transaction CSV).",
        "Stay on Overview. Click <b>Run Analysis</b> (analysis is manual — upload does not auto-train).",
        "Read stats, the full alert list, then click a row for evidence (TXID, IP, geo, AML flags).",
        "Open <b>Link Graph</b>: blue = IP, green = wallet, orange = transaction, red border = flagged.",
        "Optional: download open-source GeoIP once; after that the app stays air-gapped.",
    ], st))

    story.append(Paragraph("3. Tech stack (simple)", st["h1"]))
    story.append(kv_table([
        ["Layer", "What we used and why"],
        ["Language", "Python 3.9+ — one stack for ingest, ML, and API."],
        ["API / UI server", "FastAPI + Uvicorn. Serves JSON APIs and the dashboard files."],
        ["Database", "SQLite file on disk. No Postgres, no cloud. Fully offline."],
        ["ML library", "scikit-learn (no GPU, no paid API, trains on the uploaded dump)."],
        ["Anomaly model", "<b>Isolation Forest</b> — unsupervised outlier detector."],
        ["Clustering model", "<b>MiniBatchKMeans</b> — groups similar wallets / txs on large files."],
        ["Scaling", "StandardScaler so amount and hour sit on a comparable scale."],
        ["GeoIP", "Bundled prefix CSV, or downloadable DB-IP Lite MMDB (CC BY 4.0)."],
        ["Frontend", "Plain HTML / CSS / JS (no React build). Judges open a browser."],
        ["OS", "Linux (PS requirement), also Windows and macOS via npm run dev."],
    ], st))

    story.append(Paragraph("4. End-to-end tech flow", st["h1"]))
    story.append(Paragraph(
        "Think of a pipeline. Data only moves forward. The ML step does not talk to the internet.",
        st["body"],
    ))
    flow = [
        ["Step", "Module", "What happens"],
        ["1. Ingest", "backend/ingest/parser.py",
         "CSV / JSON / XML → one common record: time, IPs, ports, TXID, wallets, amounts, fee, script, country, ASN."],
        ["2. Store", "backend/correlation + SQLite",
         "Save unique TXIDs. Same TXID in two files counts once. Fill missing amount/IP if a second file has them."],
        ["3. Geo", "backend/geo/lookup.py",
         "If country/ASN missing, look up from IP using offline DB (MMDB or CSV)."],
        ["4. Correlate", "backend/correlation/engine.py",
         "Join rows that share a TXID and have IPs. Score 0–1 from IP coverage, repeats, wallets, amount. 5-minute window."],
        ["5. Graph", "backend/graph/builder.py",
         "Build nodes: IP ↔ transaction ↔ wallet. Flagged nodes get a red border in the UI."],
        ["6. Features", "backend/ml/analyzer.py",
         "Turn each tx into 11 numbers (log amount, fee ratio, in/out counts, hour, geo, …)."],
        ["7. ML", "Isolation Forest + KMeans",
         "Train on THIS dump. Flag outliers. Cluster similar behaviour."],
        ["8. Explain", "typology.py + red_flags.py",
         "After the model flags a row, attach a human label (mixer, peel, …) and matching AML/KYT conditions."],
        ["9. Rank", "Leads table + /api/alerts",
         "Merge anomalies + clusters + strong correlations. Sort by score. Show confidence %."],
        ["10. Show", "frontend/dist",
         "Overview, Alerts table, graph, transactions, clusters, upload."],
    ]
    data = [[Paragraph(c, st["th"] if i == 0 else st["td"]) for c in row] for i, row in enumerate(flow)]
    t = Table(data, colWidths=[22 * mm, 48 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("BACKGROUND", (0, 1), (-1, -1), white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#f8fafc")]),
    ]))
    # header cells were Paragraph with navy text on navy - fix header style
    thw = ParagraphStyle("thw", parent=st["th"], textColor=white)
    data[0] = [Paragraph(c, thw) for c in flow[0]]
    t = Table(data, colWidths=[22 * mm, 48 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#f8fafc")]),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Speaker line: “Pehle parse, phir SQLite, phir IP-chain join, phir 11 features, phir Isolation Forest, "
        "phir cluster, last mein explainable alert list.”",
        st["speak"],
    ))

    story.append(PageBreak())
    story.append(Paragraph("5. How we built the ML models", st["h1"]))
    story.append(Paragraph("5.1 Isolation Forest — the main detector", st["h2"]))
    story.append(Paragraph(
        "This is an <b>unsupervised</b> model. We do not label “crime” vs “clean” (NTRO will not give seized "
        "live data). Isolation Forest randomly splits the feature space. Points that need few splits to isolate "
        "are <b>outliers</b>. That matches “unusual mixing / whale / odd fan-out” better than a fixed rule like "
        "“amount &gt; 10 BTC”.",
        st["body"],
    ))
    story.append(Paragraph("<b>When it trains:</b> only when the user clicks Run Analysis. It fits on the rows currently in SQLite, then we save <font face='Courier'>data/models/isolation_forest.joblib</font>.", st["left"]))
    story.append(Paragraph("<b>11 features we feed it</b>", st["h2"]))
    story.append(bullets([
        "<b>log_amount, log_fee</b> — log so a 0.01 BTC tx and a 1,000 BTC tx can sit in one model.",
        "<b>fee_ratio</b> — fee ÷ amount (odd fees can mean rush or obfuscation).",
        "<b>input_count, output_count, io_ratio</b> — fan-in / fan-out (mixers peel to many outputs).",
        "<b>has_ip</b> — 1 if we saw a network IP (PS asks for network + chain together).",
        "<b>hour</b> — clock hour (off-hours bursts).",
        "<b>is_p2sh</b> — script type P2SH often used in more complex scripts.",
        "<b>foreign_geo</b> — country not local/unknown.",
        "<b>amount_z</b> — how far the amount is from the mean of <i>this</i> dump (z-score).",
    ], st))
    story.append(Paragraph("<b>Hyperparameters (how we “made” it)</b>", st["h2"]))
    story.append(kv_table([
        ["Piece", "Choice"],
        ["Library", "sklearn.ensemble.IsolationForest"],
        ["Scaler", "StandardScaler.fit_transform on the 11 columns"],
        ["random_state", "42 — same dump → same flags (demo is repeatable)"],
        ["contamination", "About 6% of rows if n ≥ 50k; 7% if n ≥ 10k; 10% on small dumps. This is “expected outlier share”, not a fake cap of 46 alerts."],
        ["n_estimators", "100–150 trees (fewer trees on huge files so a laptop finishes)"],
        ["max_samples", "Up to 12,000 — subsample so 100k rows stay fast"],
        ["n_jobs", "-1 — use all CPU cores"],
        ["Score", "anomaly_score = −decision_function (higher = more isolated)"],
        ["Confidence", "Percentile of that score among stored outliers, clipped to 8–99%"],
        ["Severity", "CRITICAL / HIGH / MEDIUM from score + amount"],
        ["Filter", "Ignore ~0 BTC rows so empty amounts do not become fake mixer alerts"],
    ], st))
    story.append(Paragraph(
        "Speaker line: “Model labelled nahi hai. Dump ke andar jo shape rare hai, forest use isolate karta hai. "
        "Rules baad mein sirf ‘kyun’ likhne ke liye hain.”",
        st["speak"],
    ))

    story.append(Paragraph("5.2 MiniBatchKMeans — entity / behaviour clusters", st["h2"]))
    story.append(Paragraph(
        "PS also wants <b>clustering</b>. Classic DBSCAN on 100k points can be slow on a jury laptop, so we used "
        "<b>MiniBatchKMeans</b> (same scikit-learn family, mini-batches). It groups wallets (when addresses exist) "
        "or a sample of transactions by volume, counts, and linked IPs. Each group becomes a cluster card and can "
        "become a HIGH lead (for example “12 linked txs, mixer-like fan-out”).",
        st["body"],
    ))
    story.append(kv_table([
        ["Piece", "Choice"],
        ["Library", "sklearn.cluster.MiniBatchKMeans"],
        ["n_init", "3"],
        ["batch_size", "1024 (wallets) or 2048 (tx sample)"],
        ["random_state", "42"],
        ["Why not only rules", "The cluster assignment is learned from distances in feature space, not a hand list of TXIDs."],
    ], st))

    story.append(Paragraph("5.3 What is NOT the model", st["h2"]))
    story.append(Paragraph(
        "Two extra layers run <b>after</b> ML. They do not replace Isolation Forest.",
        st["body"],
    ))
    story.append(bullets([
        "<b>Typology</b> (<font face='Courier'>typology.py</font>): looks at in/out counts and amount shape → mixer, peel-chain, consolidation, whale, dusting, structuring, pass-through, overnight. This is the sentence on the alert title.",
        "<b>120 AML/KYT conditions</b> (<font face='Courier'>red_flags.py</font>): match what this metadata can support (fan-out, geo, timing). Mixer lists, sanctions, darknet labels are <b>not auto-claimed</b> without intel feeds. UI shows a disclaimer: indicators, not proof of a crime.",
    ], st))

    story.append(PageBreak())
    story.append(Paragraph("6. Correlation and graph (network ↔ chain)", st["h1"]))
    story.append(Paragraph(
        "If a row has src/dst IP, we treat it as a network observation of a TXID. We group by TXID, collect wallets "
        "and IPs, and compute a correlation score from: both IPs present, how often that IP appears, how many wallets, "
        "and amount. Timing window is <b>300 seconds</b>. If the dump has no IPs at all, we skip empty correlation rows "
        "so a 100k CSV still analyses quickly.",
        st["body"],
    ))
    story.append(Paragraph(
        "The link graph is the picture of the same join: an IP node connected to a transaction node connected to wallet "
        "nodes. Investigators see “this IP touched these wallets.”",
        st["body"],
    ))

    story.append(Paragraph("7. How alerts are ranked", st["h1"]))
    story.append(bullets([
        "Every Isolation Forest hit with a real amount becomes a lead (priority = severity, score from anomaly score).",
        "Each behaviour cluster with enough volume becomes a lead.",
        "A few high-scoring IP–TX correlations become medium leads.",
        "The Alerts page lists <b>all</b> of them (example: ~6,000 on a 100k dump), not a fake 40-row sample. Click a row to load evidence.",
    ], st))

    story.append(Paragraph("8. Dashboard map (what to click in the demo)", st["h1"]))
    story.append(kv_table([
        ["Screen", "Show the jury"],
        ["Overview", "Unique tx count, anomalies, alerts, BTC volume, full ranked table."],
        ["Link Graph", "IP / wallet / tx; red = model-flagged."],
        ["Alerts", "Click one HIGH row → TXID, blockchain.com link, IPs, country/ASN, why-list, 120-condition panel."],
        ["Transactions", "Raw ingested fields (time, amount, IP, geo)."],
        ["Clusters", "Grouped entities from MiniBatchKMeans."],
        ["Upload", "CSV/JSON/XML + optional GeoIP download + Clear Data."],
    ], st))

    story.append(Paragraph("9. Live demo script (about 3 minutes)", st["h1"]))
    story.append(bullets([
        "“PS 26146: offline Bitcoin forensic system for NTRO.”",
        "Open localhost:8000. “No internet APIs. SQLite on disk.”",
        "Upload sample or 100k CSV. “Parser accepts CSV, JSON, XML with messy column names.”",
        "Run Analysis. “Isolation Forest trains now on this dump; MiniBatchKMeans clusters entities.”",
        "Point to alert count. “This is the model’s outlier rate, not a hard-coded 46.”",
        "Click one alert. “Confidence is from the forest score. Typology is the shape. Red flags are the 120-list — not a court verdict.”",
        "Link Graph. “Network IP tied to wallets through the TXID.”",
        "If asked ‘is this ML or rules?’: “Forest decides who is flagged. Rules only write the explanation.”",
        "If asked ‘Linux?’: “Yes. Also Windows: Git + Python PATH + Node, then npm run dev.”",
    ], st))

    story.append(Paragraph("10. How to run (reminder)", st["h1"]))
    story.append(Paragraph(
        "<b>Windows / macOS / Linux:</b> install Python 3.9+ and Node.js, then "
        "<font face='Courier'>git clone https://github.com/ashutoshmishra52/bitforensics.git</font>, "
        "<font face='Courier'>cd bitforensics</font>, <font face='Courier'>npm install</font>, "
        "<font face='Courier'>npm run dev</font> → <b>http://localhost:8000</b>.",
        st["left"],
    ))
    story.append(Paragraph(
        "<b>Python only:</b> <font face='Courier'>python -m venv venv</font>, activate, "
        "<font face='Courier'>pip install -r requirements.txt</font>, <font face='Courier'>python run.py</font>.",
        st["left"],
    ))

    story.append(Paragraph("11. Honest limits (say this if asked)", st["h1"]))
    story.append(bullets([
        "Synthetic / demo metadata only — no real intercept or seized chain.",
        "Unsupervised: unusual ≠ guilty. We label investigative leads.",
        "Graph is sampled on huge dumps so the canvas stays usable.",
        "Sanctions / mixer blacklists need extra intel; we do not pretend the CSV contains them.",
    ], st))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Repo: https://github.com/ashutoshmishra52/bitforensics &nbsp;·&nbsp; Write-up: APPROACH.md",
        st["left"],
    ))

    def first_page(canvas, doc_):
        cover(canvas, doc_)

    def later(canvas, doc_):
        header_footer(canvas, doc_)

    # Cover is drawn on page 1 only; story starts page 2
    doc.build(story, onFirstPage=later, onLaterPages=later)
    # Rebuild with a dedicated cover page
    from reportlab.platypus import KeepTogether  # noqa: F401 — placeholder

    # Simpler: prepend a spacer page that cover paints over — actually first page currently has content+header.
    # Rebuild properly: empty first flow + cover-only first page.
    return OUT


def build_with_cover():
    """Page 1 = cover art only; rest = notes with header."""
    st = styles()
    OUT.parent.mkdir(parents=True, exist_ok=True)

    # Rebuild story by calling build's story construction via two-pass
    # Easier: SimpleDocTemplate with onFirstPage=cover and a tiny invisible first element
    # then PageBreak then content — cover paints full page hiding the blank para.

    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title="BitForensics — Project Presentation",
        author="BitForensics team",
    )
    st = styles()
    story = [Spacer(1, 1), PageBreak()]

    # Duplicate content assembly
    inner = SimpleDocTemplate.__new__(SimpleDocTemplate)
    # Just inline: import build content by executing the middle of build()
    # I'll call a helper get_story()
    story.extend(get_story(st))

    def on_first(c, d):
        cover(c, d)

    def on_later(c, d):
        header_footer(c, d)

    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return OUT


def get_story(st):
    story = []
    story.append(Paragraph("1. One-minute story (say this first)", st["h1"]))
    story.append(Paragraph(
        "Bitcoin wallets have no name. Criminals can move ransomware money, darknet proceeds, "
        "or extortion payments by splitting funds across many addresses. Banks cannot see this "
        "the usual way. NTRO asked for an <b>offline</b> tool that reads a bulk dump of Bitcoin "
        "metadata, joins <b>network clues</b> (IP, port, time) with <b>on-chain clues</b> "
        "(TXID, wallets, amount), and uses a <b>real ML model</b> — not only if-else rules — "
        "to rank suspicious activity with a reason and a confidence score.",
        st["body"],
    ))
    story.append(Paragraph(
        "Bolne ke liye: “Yeh software dump ko locally padhta hai, graph banata hai, "
        "Isolation Forest se outliers nikalta hai, aur investigator ko ranked leads deta hai.”",
        st["speak"],
    ))

    story.append(Paragraph("2. User kya karta hai (product flow)", st["h1"]))
    story.append(bullets([
        "<b>Start:</b> <font face='Courier'>npm run dev</font> ya <font face='Courier'>python run.py</font> → <b>http://localhost:8000</b>.",
        "<b>Upload</b> CSV / JSON / XML (demo: ~1 lakh rows wali CSV).",
        "Overview par raho. <b>Run Analysis</b> dabao (upload se model khud train nahi hota).",
        "Stats + poori alert list dekho. Row click → TXID, IP, geo, AML flags.",
        "<b>Link Graph:</b> neela = IP, hara = wallet, narangi = transaction, laal border = flagged.",
        "Optional: GeoIP ek baar download; uske baad fully offline.",
    ], st))

    story.append(Paragraph("3. Tech stack", st["h1"]))
    story.append(kv_table([
        ["Layer", "Kya use kiya, kyun"],
        ["Language", "Python 3.9+ — ingest, ML, API ek hi language."],
        ["Server", "FastAPI + Uvicorn — JSON API + dashboard files."],
        ["Database", "SQLite file. Cloud nahi. Offline."],
        ["ML", "scikit-learn. GPU / paid API nahi. Train isi dump par."],
        ["Anomaly", "<b>Isolation Forest</b> — unsupervised outliers."],
        ["Cluster", "<b>MiniBatchKMeans</b> — 1 lakh rows laptop par."],
        ["Scale", "StandardScaler — amount aur hour ek scale par."],
        ["GeoIP", "CSV fallback, ya DB-IP Lite MMDB (CC BY 4.0)."],
        ["UI", "HTML / CSS / JS — npm se frontend build nahi."],
        ["OS", "Linux (PS), Windows, macOS."],
    ], st))

    story.append(Paragraph("4. End-to-end tech flow", st["h1"]))
    flow = [
        ["Step", "Code", "Kaam"],
        ["1. Ingest", "ingest/parser.py",
         "CSV/JSON/XML → ek format: time, IP, port, TXID, wallets, amounts, fee, script, country, ASN."],
        ["2. Store", "SQLite",
         "Unique TXID. Do files mein same TXID = ek row. Missing amount/IP doosri file se fill."],
        ["3. Geo", "geo/lookup.py",
         "Country/ASN na ho to IP se offline lookup (MMDB ya CSV)."],
        ["4. Correlate", "correlation/engine.py",
         "Same TXID + IP. Score 0–1: IP coverage, repeat IP, wallets, amount. Window 5 min."],
        ["5. Graph", "graph/builder.py",
         "IP ↔ transaction ↔ wallet. Flagged = red border."],
        ["6. Features", "ml/analyzer.py",
         "Har tx → 11 numbers (log amount, fee ratio, in/out, hour, geo, …)."],
        ["7. ML", "Forest + KMeans",
         "Isi dump par train. Outliers + similar groups."],
        ["8. Explain", "typology + red_flags",
         "Flag ke baad label (mixer/peel/…) aur 120 AML conditions."],
        ["9. Rank", "/api/alerts",
         "Anomaly + cluster + strong correlation. Score se sort. Confidence %."],
        ["10. UI", "frontend/dist",
         "Overview, Alerts, Graph, Transactions, Clusters, Upload."],
    ]
    thw = ParagraphStyle("thw2", parent=st["th"], textColor=white)
    data = []
    for i, row in enumerate(flow):
        sty = thw if i == 0 else st["td"]
        data.append([Paragraph(c, sty) for c in row])
    t = Table(data, colWidths=[22 * mm, 42 * mm, 116 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#f8fafc")]),
    ]))
    story.append(t)
    story.append(Paragraph(
        "Bolne ke liye: “Parse → SQLite → IP–chain join → 11 features → Isolation Forest → cluster → explainable list.”",
        st["speak"],
    ))

    story.append(PageBreak())
    story.append(Paragraph("5. Models kaise banaye", st["h1"]))
    story.append(Paragraph("5.1 Isolation Forest (mukhya model)", st["h2"]))
    story.append(Paragraph(
        "Yeh <b>unsupervised</b> hai. Hum “criminal / clean” label nahi dete (seized live data nahi milta). "
        "Forest feature space ko random splits se kaatta hai. Jo point jaldi alag ho jata hai, woh <b>outlier</b> hai. "
        "Yeh “ajeeb mixer / whale / zyada outputs” ke liye ek hi threshold rule se better hai.",
        st["body"],
    ))
    story.append(Paragraph(
        "<b>Train kab:</b> sirf <b>Run Analysis</b> par. Current SQLite rows par fit, phir "
        "<font face='Courier'>data/models/isolation_forest.joblib</font> save.",
        st["left"],
    ))
    story.append(Paragraph("Gyarah features", st["h2"]))
    story.append(bullets([
        "<b>log_amount, log_fee</b> — chhoti aur badi BTC values ek model mein.",
        "<b>fee_ratio</b> — fee ÷ amount.",
        "<b>input_count, output_count, io_ratio</b> — kitne wallets se aaya / kitne ko gaya (mixer peel).",
        "<b>has_ip</b> — network observation mili ya nahi.",
        "<b>hour</b> — raat ko burst.",
        "<b>is_p2sh</b> — complex script type.",
        "<b>foreign_geo</b> — desh local/unknown nahi.",
        "<b>amount_z</b> — is dump ke average se kitna door (z-score).",
    ], st))
    story.append(Paragraph("Settings (hyperparameters)", st["h2"]))
    story.append(kv_table([
        ["Cheez", "Value / matlab"],
        ["Library", "sklearn IsolationForest"],
        ["Scaler", "StandardScaler pehle, phir forest"],
        ["random_state", "42 — same file, same demo"],
        ["contamination", "≈6% (n≥50k), 7% (n≥10k), 10% (chhoti file). Ye outlier share hai, 46 alerts ki cap nahi."],
        ["n_estimators", "100–150 trees"],
        ["max_samples", "max 12,000 subsample — 1 lakh rows tez"],
        ["n_jobs", "-1 (saare CPU cores)"],
        ["Score", "−decision_function (zyada = zyada isolated)"],
        ["Confidence", "us score ka percentile, 8–99%"],
        ["Severity", "CRITICAL / HIGH / MEDIUM"],
        ["Filter", "≈0 BTC rows skip — khali amount ko mixer mat banao"],
    ], st))
    story.append(Paragraph(
        "Sawal “ML hai ya rules?”: “Forest decide karta hai kaun flagged hai. Rules sirf explanation likhte hain.”",
        st["speak"],
    ))

    story.append(Paragraph("5.2 MiniBatchKMeans (clustering)", st["h2"]))
    story.append(Paragraph(
        "PS clustering maangta hai. 1 lakh points par DBSCAN laptop par slow ho sakta hai, isliye "
        "<b>MiniBatchKMeans</b>. Wallets (agar address hon) ya txs ko volume, counts, linked IPs se group karta hai. "
        "Har group ek cluster + kabhi HIGH lead (jaise 12 linked mixer-like txs).",
        st["body"],
    ))
    story.append(kv_table([
        ["Cheez", "Value"],
        ["Library", "sklearn MiniBatchKMeans"],
        ["n_init", "3"],
        ["batch_size", "1024 (wallets) / 2048 (tx sample)"],
        ["random_state", "42"],
    ], st))

    story.append(Paragraph("5.3 Model ke baad (explainability)", st["h2"]))
    story.append(bullets([
        "<b>Typology:</b> mixer, peel-chain, consolidation, whale, dusting, structuring, pass-through, overnight — alert ka title.",
        "<b>120 AML/KYT:</b> jo metadata allow kare (fan-out, geo, time). Mixer-list / sanctions / darknet <b>apne aap claim nahi</b>. Disclaimer: indicator, crime ka proof nahi.",
    ], st))

    story.append(PageBreak())
    story.append(Paragraph("6. Network ↔ blockchain correlation", st["h1"]))
    story.append(Paragraph(
        "Agar row mein src/dst IP hai, woh TXID ki network observation hai. TXID se group, wallets + IPs collect, "
        "score: dono IP, IP kitni baar, wallet count, amount. Window <b>300 second</b>. Bina IP ke dump par khali "
        "correlation skip — 1 lakh CSV tez rehti hai. Graph wahi join ka picture hai.",
        st["body"],
    ))

    story.append(Paragraph("7. Alerts kaise rank hoti hain", st["h1"]))
    story.append(bullets([
        "Har Isolation Forest hit (asli amount) = ek lead.",
        "Har mota cluster = ek lead.",
        "Kuch strong IP–TX correlations = medium leads.",
        "Alerts page <b>saari</b> list (100k par ~6,000), fake 40 nahi. Row click = evidence.",
    ], st))

    story.append(Paragraph("8. Demo mein kya dikhana hai", st["h1"]))
    story.append(kv_table([
        ["Page", "Jury ko dikhao"],
        ["Overview", "Unique txs, anomalies, alerts, BTC volume, poori table."],
        ["Link Graph", "IP / wallet / tx; laal = flagged."],
        ["Alerts", "HIGH row → TXID, explorer, IP, country/ASN, why, 120 flags."],
        ["Transactions", "Raw fields."],
        ["Clusters", "KMeans groups."],
        ["Upload", "CSV/JSON/XML, GeoIP, Clear Data."],
    ], st))

    story.append(Paragraph("9. 3-minute bolna (script)", st["h1"]))
    story.append(bullets([
        "“PS 26146: NTRO ke liye offline Bitcoin forensic system.”",
        "localhost:8000. “Koi cloud API nahi. SQLite disk par.”",
        "CSV upload. “Parser CSV, JSON, XML — column names flexible.”",
        "Run Analysis. “Ab Isolation Forest is dump par train hota hai; KMeans cluster karta hai.”",
        "Alert count. “Yeh model ka outlier rate hai, hard-coded 46 nahi.”",
        "Ek alert kholo. “Confidence forest se. Typology shape se. 120-list explanation hai, court verdict nahi.”",
        "Graph. “IP TXID ke through wallets se juda.”",
        "Linux: “Haan. Windows: Git + Python PATH + Node, phir npm run dev.”",
    ], st))

    story.append(Paragraph("10. Run kaise karein", st["h1"]))
    story.append(Paragraph(
        "Python 3.9+ aur Node.js. "
        "<font face='Courier'>git clone https://github.com/ashutoshmishra52/bitforensics.git</font> → "
        "<font face='Courier'>cd bitforensics</font> → <font face='Courier'>npm install</font> → "
        "<font face='Courier'>npm run dev</font> → <b>http://localhost:8000</b>.",
        st["left"],
    ))
    story.append(Paragraph(
        "Sirf Python: venv banao, <font face='Courier'>pip install -r requirements.txt</font>, "
        "<font face='Courier'>python run.py</font>.",
        st["left"],
    ))

    story.append(Paragraph("11. Limits (agar poochhein)", st["h1"]))
    story.append(bullets([
        "Synthetic/demo data — real intercept nahi.",
        "Unsupervised: unusual ≠ guilty. Leads hain, conviction nahi.",
        "Bade dump par graph sample hota hai.",
        "Sanctions/mixer blacklist alag intel se aati hai; CSV mein pretend nahi.",
    ], st))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "GitHub: https://github.com/ashutoshmishra52/bitforensics &nbsp;·&nbsp; Short write-up: APPROACH.md",
        st["left"],
    ))
    return story


if __name__ == "__main__":
    path = build_with_cover()
    print(path)
