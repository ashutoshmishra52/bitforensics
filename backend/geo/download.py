"""Download DB-IP Lite Country + ASN MaxMind DBs (open, CC BY 4.0). Offline after that."""
from __future__ import annotations

import gzip
import shutil
import urllib.request
from datetime import datetime
from pathlib import Path

from backend.geo.lookup import ASN_DB, COUNTRY_DB, GEO_DIR, reload_databases

UA = "BitForensics/1.0 (SIH 2026 offline GeoIP fetch)"


def _months():
    now = datetime.utcnow()
    y, m = now.year, now.month
    out = []
    for i in range(0, 4):
        mm = m - i
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def _fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as f:
        shutil.copyfileobj(resp, f)
    tmp.replace(dest)


def _gunzip(src: Path, dest: Path) -> None:
    with gzip.open(src, "rb") as g, open(dest, "wb") as o:
        shutil.copyfileobj(g, o)


def download_geoip() -> dict:
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    errors = []
    saved = []
    for kind, dest in (("country", COUNTRY_DB), ("asn", ASN_DB)):
        ok = False
        for month in _months():
            gz = GEO_DIR / f"dbip-{kind}-lite-{month}.mmdb.gz"
            url = f"https://download.db-ip.com/free/dbip-{kind}-lite-{month}.mmdb.gz"
            try:
                _fetch(url, gz)
                _gunzip(gz, dest)
                gz.unlink(missing_ok=True)
                saved.append(str(dest.name))
                ok = True
                break
            except Exception as e:
                errors.append(f"{kind} {month}: {e}")
                gz.unlink(missing_ok=True)
        if not ok and not dest.exists():
            raise RuntimeError(f"Could not download DB-IP {kind} lite. Last errors: {errors[-3:]}")
    reload_databases()
    return {
        "message": "GeoIP databases ready (offline MMDB)",
        "files": saved,
        "country_db": COUNTRY_DB.exists(),
        "asn_db": ASN_DB.exists(),
        "license": "DB-IP Lite — CC BY 4.0 — https://db-ip.com",
    }
