from __future__ import annotations

import csv
from pathlib import Path

GEO_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "geoip.csv"
_cache: list[tuple[str, str, str, str]] = []


def _load():
    global _cache
    if _cache or not GEO_FILE.exists():
        return
    with open(GEO_FILE) as f:
        for row in csv.DictReader(f):
            _cache.append((row["ip_prefix"], row["country"], row["asn"], row.get("org", "")))
    _cache.sort(key=lambda x: len(x[0]), reverse=True)


def lookup(ip: str | None) -> tuple[str, str, str]:
    """Return (country, asn, org) for an IP. Uses bundled offline CSV."""
    if not ip:
        return "", "", ""
    _load()
    for prefix, country, asn, org in _cache:
        if ip.startswith(prefix):
            return country, asn, org
    if ip.startswith("192.168") or ip.startswith("10."):
        return "LOCAL", "0", "Private"
    return "UNK", "0", "Unknown"
