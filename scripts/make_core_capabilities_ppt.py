#!/usr/bin/env python3
"""BitForensics Core Capabilities — flow diagram in the numbered 1→2→3 style (PPT 16:9)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_PNG = ROOT / "docs" / "BitForensics_Core_Capabilities_PPT.png"
OUT_JPG = ROOT / "docs" / "BitForensics_Core_Capabilities_PPT.jpg"

W, H = 1920, 1080
WHITE = (255, 255, 255)
INK = (30, 30, 30)
MUTED = (80, 80, 80)
NAVY = (30, 41, 59)

# palette matching reference vibe
PINK = (236, 72, 153)
PINK_BG = (252, 231, 243)
TAN = (217, 160, 102)
TAN_BG = (254, 243, 226)
PURPLE = (126, 58, 242)
PURPLE_LT = (237, 233, 254)
ORANGE = (249, 115, 22)
ORANGE_BG = (255, 237, 213)
GREEN = (34, 197, 94)
GREEN_BG = (220, 252, 231)
BLUE = (59, 130, 246)
BLUE_BG = (219, 234, 254)
TEAL = (20, 184, 166)
RED = (239, 68, 68)
GRAY = (100, 116, 139)
LINE_P = (109, 40, 217)
BROWN = (180, 83, 9)


def font(size: int, bold: bool = False):
    for p in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def rr(d, xy, r=10, fill=None, outline=None, width=2):
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def badge(d, x, y, n, fill, fnt):
    d.ellipse((x, y, x + 36, y + 36), fill=fill, outline=WHITE, width=2)
    tw = d.textlength(str(n), font=fnt)
    d.text((x + 18 - tw / 2, y + 7), str(n), font=fnt, fill=WHITE)


def lock(d, cx, cy, r=12, fill=LINE_P):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
    d.rectangle((cx - 5, cy - 1, cx + 5, cy + 7), fill=WHITE)
    d.arc((cx - 4, cy - 8, cx + 4, cy + 2), 0, 180, fill=WHITE, width=2)


def arrow_h(d, x1, y, x2, color=LINE_P, w=4):
    d.line([(x1, y), (x2, y)], fill=color, width=w)
    d.polygon([(x2, y), (x2 - 12, y - 7), (x2 - 12, y + 7)], fill=color)


def arrow_v(d, x, y1, y2, color=LINE_P, w=4):
    d.line([(x, y1), (x, y2)], fill=color, width=w)
    if y2 > y1:
        d.polygon([(x, y2), (x - 7, y2 - 12), (x + 7, y2 - 12)], fill=color)
    else:
        d.polygon([(x, y2), (x - 7, y2 + 12), (x + 7, y2 + 12)], fill=color)


def mini_box(d, x, y, w, h, title, sub, fill, f_t, f_s):
    rr(d, (x, y, x + w, y + h), 8, fill=fill, outline=(200, 200, 200), width=1)
    d.text((x + 10, y + 10), title, font=f_t, fill=INK)
    if sub:
        d.text((x + 10, y + 32), sub, font=f_s, fill=MUTED)


def stage_bar(d, x, y, w, text, fnt, fill=ORANGE):
    rr(d, (x, y, x + w, y + 36), 6, fill=fill)
    tw = d.textlength(text, font=fnt)
    d.text((x + (w - tw) / 2, y + 8), text, font=fnt, fill=WHITE)


def draw() -> Image.Image:
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    f_title = font(28, True)
    f_h = font(14, True)
    f_b = font(12, False)
    f_s = font(11, False)
    f_tiny = font(10, False)
    f_num = font(16, True)
    f_bar = font(13, True)
    f_big = font(15, True)

    # Title
    d.text((40, 24), "BITFORENSICS — Core Capabilities", font=f_title, fill=NAVY)
    d.text(
        (40, 62),
        "Offline Bitcoin forensic pipeline  ·  SIH 2026 · PS 26146 · NTRO",
        font=f_s,
        fill=MUTED,
    )

    # ========== COLUMN 1: Data entry + DB ==========
    badge(d, 40, 100, 1, PINK, f_num)

    # Upload box
    rr(d, (90, 100, 420, 200), 12, fill=PINK_BG, outline=PINK, width=3)
    d.text((110, 118), "Upload Dataset", font=f_h, fill=INK)
    d.text((110, 142), "CSV  ·  JSON  ·  XML", font=f_b, fill=MUTED)
    d.text((110, 166), "TX + network metadata", font=f_tiny, fill=MUTED)

    # Arrow down with lock
    arrow_v(d, 250, 205, 250, PINK, 4)
    lock(d, 250, 228, 11, PINK)

    # Database box
    rr(d, (90, 255, 420, 480), 12, fill=TAN_BG, outline=TAN, width=3)
    d.text((110, 270), "SQLite Database", font=f_h, fill=INK)
    fields = [
        "txid, timestamp",
        "src_ip / dst_ip, ports",
        "input / output wallets",
        "amount_btc, fee_btc",
        "script_type, geo, ASN",
    ]
    yy = 305
    for f in fields:
        d.ellipse((115, yy + 4, 125, yy + 14), fill=TAN)
        d.text((135, yy), f, font=f_b, fill=INK)
        yy += 26

    # FACE DATA equivalent → NETWORK + CHAIN LAYERS
    rr(d, (110, 430, 400, 465), 8, fill=PINK, outline=PINK)
    d.text((130, 438), "NETWORK + BLOCKCHAIN LAYERS", font=f_tiny, fill=WHITE)

    # ========== COLUMN 2: Processing ==========
    badge(d, 480, 100, 2, PURPLE, f_num)

    # Outer processing frame
    rr(d, (530, 100, 1280, 700), 14, fill=PURPLE_LT, outline=PURPLE, width=3)

    # Feed placeholder
    rr(d, (560, 120, 1250, 175), 8, fill=(226, 232, 240), outline=GRAY, width=1)
    d.text((580, 138), "Ingested dump  →  feature matrix + entity graph inputs", font=f_b, fill=MUTED)

    # Stage A — Correlation
    stage_bar(d, 560, 195, 690, "Correlation (Network ↔ Blockchain) Stage", f_bar, BLUE)
    boxes_a = [
        (560, 245, "IP / Port Join", "timing window"),
        (800, 245, "Wallet Linkage", "fan-in / fan-out"),
        (1040, 245, "Score 0–1", "correlation_score"),
    ]
    for x, y, t, s in boxes_a:
        mini_box(d, x, y, 220, 70, t, s, BLUE_BG, f_h, f_tiny)
    arrow_h(d, 785, 280, 795, BLUE, 3)
    arrow_h(d, 1025, 280, 1035, BLUE, 3)

    # Stage B — Isolation Forest
    stage_bar(d, 560, 340, 690, "Anomaly Detection (Isolation Forest) Stage", f_bar, ORANGE)
    boxes_b = [
        (560, 390, "Feature Extract", "log amt, fee, I/O…"),
        (800, 390, "Forest Fit", "unsupervised"),
        (1040, 390, "Confidence %", "severity band"),
    ]
    for x, y, t, s in boxes_b:
        mini_box(d, x, y, 220, 70, t, s, ORANGE_BG, f_h, f_tiny)
    arrow_h(d, 785, 425, 795, ORANGE, 3)
    arrow_h(d, 1025, 425, 1035, ORANGE, 3)

    # Stage C — Cluster + Typology
    stage_bar(d, 560, 485, 690, "Clustering + Typology (KMeans / Patterns) Stage", f_bar, TEAL)
    boxes_c = [
        (560, 535, "MiniBatchKMeans", "entity groups"),
        (800, 535, "Typology Label", "mixer / peel / whale"),
        (1040, 535, "120 Red Flags", "AML / KYT why"),
    ]
    for x, y, t, s in boxes_c:
        mini_box(d, x, y, 220, 70, t, s, (204, 251, 241), f_h, f_tiny)
    arrow_h(d, 785, 570, 795, TEAL, 3)
    arrow_h(d, 1025, 570, 1035, TEAL, 3)

    # Auth / Decision bar
    stage_bar(d, 560, 630, 690, "Lead Ranking  ·  Evidence Assembly  ·  Graph Build", f_bar, BROWN)

    # Arrow from DB face-data into processing
    d.line([(420, 448), (530, 448)], fill=BROWN, width=4)
    d.polygon([(530, 448), (518, 441), (518, 455)], fill=BROWN)
    lock(d, 475, 448, 12, BROWN)

    # Vertical flow locks inside col2
    lock(d, 905, 325, 10, PURPLE)
    lock(d, 905, 470, 10, PURPLE)
    lock(d, 905, 615, 10, PURPLE)

    # ========== COLUMN 3: Outcomes ==========
    badge(d, 1340, 100, 3, GREEN, f_num)

    # Arrow from stage 2 to 3
    arrow_h(d, 1285, 648, 1380, LINE_P, 5)
    lock(d, 1335, 648, 12, LINE_P)

    # Success
    rr(d, (1380, 200, 1860, 400), 14, fill=GREEN_BG, outline=GREEN, width=3)
    d.text((1410, 220), "FLAGGED / HIGH RISK", font=f_big, fill=(21, 128, 61))
    for i, t in enumerate([
        "Ranked alert created",
        "Confidence + severity set",
        "Evidence + red flags",
        "Shown on Link Graph (red)",
    ]):
        d.ellipse((1415, 265 + i * 30, 1425, 275 + i * 30), fill=GREEN)
        d.text((1435, 260 + i * 30), t, font=f_b, fill=INK)

    # Failure / normal
    rr(d, (1380, 440, 1860, 640), 14, fill=ORANGE_BG, outline=ORANGE, width=3)
    d.text((1410, 460), "NORMAL / LOW RISK", font=f_big, fill=(194, 65, 12))
    for i, t in enumerate([
        "Stays in transaction list",
        "No priority lead",
        "Still searchable in UI",
        "Available for re-analysis",
    ]):
        d.ellipse((1415, 505 + i * 30, 1425, 515 + i * 30), fill=ORANGE)
        d.text((1435, 500 + i * 30), t, font=f_b, fill=INK)

    # Split arrows into outcomes
    d.line([(1380, 648), (1480, 648), (1480, 400)], fill=GREEN, width=3)
    d.polygon([(1480, 400), (1473, 412), (1487, 412)], fill=GREEN)
    d.line([(1380, 648), (1480, 648), (1480, 440)], fill=ORANGE, width=3)

    # ========== FOOTER: Offline execution ==========
    rr(d, (40, 740, W - 40, 1040), 16, fill=PURPLE, outline=PURPLE)
    d.text((70, 760), "OFFLINE EXECUTION STACK", font=f_big, fill=WHITE)

    foot = [
        (70, "FastAPI + Uvicorn", "REST APIs for ingest,\nanalyze, graph, alerts"),
        (520, "SQLite Working DB", "Local file store\ndata/bitforensics.db"),
        (970, "scikit-learn ML", "IsolationForest +\nMiniBatchKMeans"),
        (1420, "Vanilla Dashboard", "HTML/CSS/JS UI\nLink Graph canvas"),
    ]
    for x, title, sub in foot:
        rr(d, (x, 800, x + 400, 980), 12, fill=WHITE, outline=WHITE)
        d.text((x + 20, 820), title, font=f_h, fill=PURPLE)
        yy = 860
        for ln in sub.split("\n"):
            d.text((x + 20, yy), ln, font=f_b, fill=MUTED)
            yy += 22

    d.text(
        (70, 1005),
        "Air-gapped after setup  ·  Optional GeoIP MMDB download once  ·  Alerts = investigative leads, not legal proof",
        font=f_tiny,
        fill=(221, 214, 254),
    )

    return img


def main():
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    img = draw()
    img.save(OUT_PNG, "PNG", optimize=True)
    img.convert("RGB").save(OUT_JPG, "JPEG", quality=95, optimize=True)
    # also overwrite code capability names if user looks there
    alt = ROOT / "docs" / "BitForensics_Code_Capability_Diagram.jpg"
    img.convert("RGB").save(alt, "JPEG", quality=95, optimize=True)
    print(OUT_PNG)
    print(OUT_JPG)


if __name__ == "__main__":
    main()
