from __future__ import annotations

import csv
import ipaddress
from pathlib import Path

GEO_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "geoip"
CSV_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "geoip.csv"
COUNTRY_DB = GEO_DIR / "dbip-country-lite.mmdb"
ASN_DB = GEO_DIR / "dbip-asn-lite.mmdb"

_csv_cache: list[tuple[str, str, str, str]] = []
_country_reader = None
_asn_reader = None
_mmdb_tried = False


def _private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.strip())
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        return False


def _load_csv():
    global _csv_cache
    if _csv_cache or not CSV_FILE.exists():
        return
    with open(CSV_FILE) as f:
        for row in csv.DictReader(f):
            _csv_cache.append((row["ip_prefix"], row["country"], row["asn"], row.get("org", "")))
    _csv_cache.sort(key=lambda x: len(x[0]), reverse=True)


def _open_mmdb():
    global _country_reader, _asn_reader, _mmdb_tried
    if _mmdb_tried:
        return
    _mmdb_tried = True
    try:
        import maxminddb
    except ImportError:
        return
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    if COUNTRY_DB.exists():
        _country_reader = maxminddb.open_database(str(COUNTRY_DB))
    if ASN_DB.exists():
        _asn_reader = maxminddb.open_database(str(ASN_DB))


def reload_databases():
    """Re-open MMDB files after a download."""
    global _country_reader, _asn_reader, _mmdb_tried
    for r in (_country_reader, _asn_reader):
        try:
            if r:
                r.close()
        except Exception:
            pass
    _country_reader = None
    _asn_reader = None
    _mmdb_tried = False
    _open_mmdb()


def status() -> dict:
    _open_mmdb()
    return {
        "engine": "db-ip-mmdb" if _country_reader else "prefix-csv",
        "country_db": COUNTRY_DB.exists(),
        "asn_db": ASN_DB.exists(),
        "country_path": str(COUNTRY_DB) if COUNTRY_DB.exists() else None,
        "asn_path": str(ASN_DB) if ASN_DB.exists() else None,
        "offline": True,
        "source": "DB-IP Lite (CC BY 4.0)" if _country_reader else "bundled prefix CSV",
    }


def _from_mmdb(ip: str) -> tuple[str, str, str]:
    _open_mmdb()
    country = asn = org = ""
    if _country_reader:
        rec = _country_reader.get(ip) or {}
        if isinstance(rec, dict):
            c = rec.get("country") or rec.get("registered_country") or {}
            if isinstance(c, dict):
                country = c.get("iso_code") or (c.get("names") or {}).get("en") or ""
            elif isinstance(c, str):
                country = c
            continent = rec.get("continent") or {}
            if not country and isinstance(continent, dict):
                country = continent.get("code") or ""
    if _asn_reader:
        rec = _asn_reader.get(ip) or {}
        if isinstance(rec, dict):
            num = rec.get("autonomous_system_number") or rec.get("asn")
            org = rec.get("autonomous_system_organization") or rec.get("org") or rec.get("name") or ""
            if num:
                asn = f"AS{num}"
            elif rec.get("autonomous_system"):
                asn = str(rec["autonomous_system"])
    return str(country or ""), str(asn or ""), str(org or "")


def _from_csv(ip: str) -> tuple[str, str, str]:
    _load_csv()
    for prefix, country, asn, org in _csv_cache:
        if ip.startswith(prefix):
            return country, asn, org
    return "", "", ""


def lookup(ip: str | None) -> tuple[str, str, str]:
    """Return (country, asn, org). Prefers offline DB-IP MMDB, then prefix CSV."""
    if not ip:
        return "", "", ""
    ip = str(ip).strip()
    if _private(ip) or ip.startswith("192.168") or ip.startswith("10.") or ip.startswith("127."):
        return "LOCAL", "0", "Private network"

    country, asn, org = _from_mmdb(ip)
    if not country and not asn:
        country, asn, org = _from_csv(ip)
    if not country:
        return "UNK", asn or "0", org or "Unknown"
    return country, asn or "0", org or ""


def lookup_route(ip: str | None) -> tuple[str, str]:
    """Country + ASN for export rows; prefix CSV fills gaps when MMDB returns LOCAL/UNK."""
    if not ip:
        return "", ""
    country, asn, _ = lookup(ip)
    if country in ("LOCAL", "UNK", ""):
        c2, a2, _ = _from_csv(ip)
        if c2:
            country = c2
            if not asn or asn == "0":
                asn = a2
    return country or "", asn or ""
