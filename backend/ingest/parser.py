from __future__ import annotations

import csv
import json
from datetime import datetime
from io import StringIO
from pathlib import Path
from xml.etree import ElementTree

from backend.geo.lookup import lookup as geo_lookup
from backend.models.schemas import ScriptType, TransactionRecord

ALIASES = {
    "txid": ["txid", "transaction_id", "tx_id", "hash", "txhash", "tx_hash"],
    "timestamp": ["timestamp", "time", "datetime", "date", "block_time"],
    "src_ip": ["src_ip", "source_ip", "srcip"],
    "src_port": ["src_port", "source_port"],
    "dst_ip": ["dst_ip", "dest_ip", "destination_ip", "dstip"],
    "dst_port": ["dst_port", "dest_port", "destination_port"],
    "input_addresses": ["input_addresses", "inputs", "from_addresses", "input_address"],
    "output_addresses": ["output_addresses", "outputs", "to_addresses", "output_address"],
    "input_amounts": ["input_amounts", "input_amount", "inputs_amount"],
    "output_amounts": ["output_amounts", "output_amount", "outputs_amount"],
    "input_count": ["input_count", "inputcount", "vin_count"],
    "output_count": ["output_count", "outputcount", "vout_count"],
    "amount_btc": [
        "amount_btc", "amount", "value_btc", "input_value_btc", "output_value_btc",
        "inputvalue", "input_value", "outputvalue", "output_value", "total_btc", "btc",
        # keep generic "value" last — many datasets use it for unrelated fields
        "value",
    ],
    "fee_btc": ["fee_btc", "fee", "transaction_fee", "feevalue", "fee_value", "fee_btc_value"],
    "script_type": ["script_type", "script", "type"],
    "geo_country": ["geo_country", "country", "geo"],
    "asn": ["asn", "as_number"],
}


def _flatten(obj, prefix="") -> dict:
    """Flatten nested dicts so block.timestamp.time becomes accessible."""
    out = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}_{k}"
        key = key.lower().replace(" ", "_").replace("-", "_")
        if isinstance(v, dict):
            # keep nested time/hash fields one level up too
            if "time" in v and not isinstance(v["time"], (dict, list)):
                out[key] = v["time"]
                out["timestamp"] = out.get("timestamp") or v["time"]
                out["time"] = out.get("time") or v["time"]
            if "hash" in v and isinstance(v["hash"], str):
                out["hash"] = out.get("hash") or v["hash"]
            out.update(_flatten(v, key))
            out[key] = v  # keep original for address extraction
        else:
            out[key] = v
    return out


def _get(row: dict, field: str):
    if not isinstance(row, dict):
        return None
    norm = {}
    for k, v in row.items():
        nk = str(k).strip().lower().replace(" ", "_").replace("-", "_")
        norm[nk] = v
    for name in ALIASES[field]:
        if name in norm and norm[name] not in (None, ""):
            return norm[name]
    return None


def _time(val) -> datetime:
    if isinstance(val, datetime):
        return val
    if isinstance(val, dict):
        val = val.get("time") or val.get("timestamp") or val.get("date")
    if isinstance(val, (int, float)):
        # ms vs seconds
        if val > 1e12:
            val = val / 1000
        return datetime.fromtimestamp(val)
    if not val:
        return datetime.utcnow()
    text = str(val).strip().replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if "T" in text or " " in text else text[:10], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.split("+")[0])
    except ValueError:
        return datetime.utcnow()


def _extract_addrs(val) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        text = val.strip()
        if text.startswith("["):
            try:
                val = json.loads(text.replace("'", '"'))
            except json.JSONDecodeError:
                return [text]
        else:
            sep = ";" if ";" in text else "|" if "|" in text else None
            return [a.strip() for a in text.split(sep)] if sep else [text]
    if isinstance(val, list):
        addrs = []
        for item in val:
            if isinstance(item, str) and item:
                addrs.append(item.strip())
            elif isinstance(item, dict):
                for k in ("address", "addr", "scriptPubKey", "scriptpubkey"):
                    a = item.get(k)
                    if isinstance(a, dict):
                        a = a.get("address") or a.get("addresses")
                    if isinstance(a, list):
                        addrs.extend(str(x) for x in a if x)
                    elif a:
                        addrs.append(str(a))
        return addrs
    return []


def _to_float(val) -> float:
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        return _to_float(val.get("value") or val.get("amount") or val.get("value_btc") or 0)
    try:
        return float(str(val).strip().replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _floats(val) -> list[float]:
    if not val:
        return []
    if isinstance(val, (int, float)):
        return [float(val)]
    if isinstance(val, list):
        out = []
        for v in val:
            try:
                if isinstance(v, dict):
                    v = (
                        v.get("value") or v.get("amount") or v.get("value_btc")
                        or v.get("input_value_btc") or 0
                    )
                out.append(float(v))
            except (TypeError, ValueError):
                pass
        return out
    text = str(val).strip()
    if text.startswith("["):
        try:
            return [float(x) for x in json.loads(text.replace("'", '"'))]
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
    sep = ";" if ";" in text else "," if "," in text else None
    try:
        return [float(x.strip()) for x in text.split(sep)] if sep else [float(text)]
    except ValueError:
        return []


def _record(row) -> TransactionRecord | None:
    if not isinstance(row, dict):
        return None

    flat = _flatten(row)
    # merge flat over original so aliases work on both
    merged = {**flat, **{str(k).lower(): v for k, v in row.items()}}

    txid = _get(merged, "txid")
    if not txid:
        return None

    script_raw = str(_get(merged, "script_type") or "UNKNOWN").upper()
    try:
        script = ScriptType(script_raw)
    except ValueError:
        script = ScriptType.UNKNOWN

    src_ip = _get(merged, "src_ip")
    country = _get(merged, "geo_country")
    asn = _get(merged, "asn")
    if src_ip and not country:
        country, asn_val, _ = geo_lookup(src_ip)
        asn = asn or asn_val

    amount = _to_float(_get(merged, "amount_btc"))
    fee = _to_float(_get(merged, "fee_btc"))

    # nested timestamp: block.timestamp.time already flattened
    ts = _get(merged, "timestamp")
    if not ts and isinstance(row.get("block"), dict):
        blk = row["block"]
        ts = (blk.get("timestamp") or {}).get("time") if isinstance(blk.get("timestamp"), dict) else blk.get("timestamp")

    def port(k):
        try:
            return int(_get(merged, k) or 0) or None
        except (TypeError, ValueError):
            return None

    inputs = _extract_addrs(_get(merged, "input_addresses") or row.get("inputs") or row.get("vin"))
    outputs = _extract_addrs(_get(merged, "output_addresses") or row.get("outputs") or row.get("vout"))
    in_amts = _floats(_get(merged, "input_amounts") or row.get("inputs") or row.get("vin"))
    out_amts = _floats(_get(merged, "output_amounts") or row.get("outputs") or row.get("vout"))

    def as_int(field, fallback=0):
        raw = _get(merged, field)
        try:
            return int(raw) if raw is not None else fallback
        except (TypeError, ValueError):
            return fallback

    in_count = as_int("input_count", len(inputs))
    out_count = as_int("output_count", len(outputs))
    if not in_count and inputs:
        in_count = len(inputs)
    if not out_count and outputs:
        out_count = len(outputs)

    # recover amount from nested IO lists or USD fields when BTC amount missing
    if amount <= 0 and in_amts:
        amount = float(sum(in_amts))
    if amount <= 0 and out_amts:
        amount = float(sum(out_amts))
    if amount <= 0:
        usd = _to_float(merged.get("input_value_usd") or merged.get("inputvalueusd") or merged.get("amount_usd"))
        fee_usd = _to_float(merged.get("fee_value_usd") or merged.get("feevalueusd") or merged.get("fee_usd"))
        if usd > 0 and fee > 0 and fee_usd > 0:
            amount = usd * (fee / fee_usd)
        elif usd > 0:
            amount = usd / 45000.0  # offline approx when no fee/USD pair

    return TransactionRecord(
        txid=str(txid).strip(),
        timestamp=_time(ts),
        src_ip=src_ip, src_port=port("src_port"),
        dst_ip=_get(merged, "dst_ip"), dst_port=port("dst_port"),
        input_addresses=inputs,
        output_addresses=outputs,
        input_amounts=in_amts,
        output_amounts=out_amts,
        input_count=in_count,
        output_count=out_count,
        amount_btc=float(amount or 0),
        fee_btc=float(fee or 0),
        script_type=script,
        geo_country=country, asn=str(asn) if asn else None,
    )


def _find_tx_lists(obj, found=None) -> list:
    """Walk nested JSON and collect lists that look like transaction arrays."""
    if found is None:
        found = []
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            sample = obj[0]
            keys = {str(k).lower() for k in sample.keys()}
            if keys & {"txid", "hash", "tx_id", "transaction_id", "txhash"}:
                found.append(obj)
            else:
                for item in obj:
                    _find_tx_lists(item, found)
        return found
    if isinstance(obj, dict):
        for key in ("transactions", "records", "txs", "data", "bitcoin", "items", "results"):
            if key in obj:
                _find_tx_lists(obj[key], found)
        if not found:
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    _find_tx_lists(v, found)
    return found


def _parse_rows(rows) -> list[TransactionRecord]:
    if not isinstance(rows, list):
        rows = [rows] if isinstance(rows, dict) else []
    out = []
    for row in rows:
        rec = _record(row)
        if rec and rec.txid:
            out.append(rec)
    return out


def parse_csv(content: str | bytes) -> list[TransactionRecord]:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    return _parse_rows(list(csv.DictReader(StringIO(text))))


def parse_json(content: str | bytes) -> list[TransactionRecord]:
    text = content.decode("utf-8") if isinstance(content, bytes) else content
    data = json.loads(text)

    if isinstance(data, list):
        return _parse_rows(data)

    if not isinstance(data, dict):
        raise ValueError("JSON must be an object or array")

    # direct known keys first
    for key in ("transactions", "records", "txs", "items", "results"):
        if isinstance(data.get(key), list):
            return _parse_rows(data[key])

    # nested e.g. {data: {bitcoin: {transactions: [...]}}}
    lists = _find_tx_lists(data)
    if lists:
        # merge all found lists (usually one)
        rows = []
        for lst in lists:
            rows.extend(lst)
        return _parse_rows(rows)

    # single transaction object
    rec = _record(data)
    return [rec] if rec else []


def parse_xml(content: str | bytes) -> list[TransactionRecord]:
    text = content.decode("utf-8") if isinstance(content, bytes) else content
    root = ElementTree.fromstring(text)
    rows = []
    for elem in root.findall(".//transaction") + root.findall(".//record") + root.findall(".//tx"):
        row = {child.tag: child.text for child in elem}
        row.update(elem.attrib)
        rows.append(row)
    return _parse_rows(rows)


def parse_file(path: Path) -> list[TransactionRecord]:
    parsers = {".csv": parse_csv, ".json": parse_json, ".xml": parse_xml}
    fn = parsers.get(path.suffix.lower())
    if not fn:
        raise ValueError(f"Unsupported file: {path.suffix}")
    return fn(path.read_bytes())
