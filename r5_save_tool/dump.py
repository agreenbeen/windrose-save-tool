"""
Dump and inspect operations — scan one or all column families and print findings.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO

from .db import R5Database
from .schema import decode_key, decode_value, format_decoded


def dump_db(
    db: R5Database,
    output: TextIO = sys.stdout,
    cf_filter: list[str] | None = None,
    max_per_cf: int | None = None,
) -> dict[str, list[dict]]:
    """
    Scan all (or filtered) column families in *db* and print a human-readable
    report.  Returns a structured summary dict for further processing.

    Returns:
        {cf_name: [{"key": str, "value_bytes": int, "strings": [...], "numerics": [...], "text": str|None}, ...]}
    """
    summary: dict[str, list[dict]] = {}

    cfs = cf_filter if cf_filter else db.column_families

    for cf_name in cfs:
        print(f"\n{'='*70}", file=output)
        print(f"  COLUMN FAMILY: {cf_name}", file=output)
        print(f"{'='*70}", file=output)

        entries: list[dict] = []
        count = 0
        try:
            for key_bytes, val_bytes in db.iter_cf(cf_name):
                if max_per_cf and count >= max_per_cf:
                    print(f"  ... (truncated at {max_per_cf} entries)", file=output)
                    break

                decoded = decode_value(val_bytes)
                entry = {
                    "key": decode_key(key_bytes),
                    "key_raw": key_bytes.hex(),
                    "value_bytes": len(val_bytes),
                    "text": decoded.text,
                    "strings": decoded.strings,
                    "numerics": [str(n) for n in decoded.numerics],
                }
                entries.append(entry)
                print(format_decoded(key_bytes, val_bytes, cf_name), file=output)
                count += 1
        except Exception as exc:
            print(f"  ERROR reading {cf_name}: {exc}", file=output)

        print(f"\n  → {count} entries", file=output)
        summary[cf_name] = entries

    return summary


def dump_to_json(db: R5Database, out_path: Path, **kwargs) -> None:
    """Run dump_db and write the structured summary to a JSON file."""
    with open(out_path, "w", encoding="utf-8") as fh:
        summary = dump_db(db, output=sys.stdout, **kwargs)
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    print(f"\nJSON summary written to: {out_path}")


def search_key(db: R5Database, pattern: str) -> list[tuple[str, str, int]]:
    """
    Search all column families for keys matching *pattern* (case-insensitive substring).
    Returns list of (cf_name, key_str, value_len).
    """
    results = []
    pattern_lower = pattern.lower()
    for cf_name in db.column_families:
        try:
            for key_bytes, val_bytes in db.iter_cf(cf_name):
                key_str = decode_key(key_bytes)
                if pattern_lower in key_str.lower():
                    results.append((cf_name, key_str, len(val_bytes)))
        except Exception:
            pass
    return results


def search_value_strings(db: R5Database, pattern: str) -> list[tuple[str, str, list[str]]]:
    """
    Search all column families for values that contain *pattern* as an embedded string.
    Returns list of (cf_name, key_str, [matching_strings]).
    """
    results = []
    pattern_lower = pattern.lower()
    for cf_name in db.column_families:
        try:
            for key_bytes, val_bytes in db.iter_cf(cf_name):
                decoded = decode_value(val_bytes)
                # Check text values and embedded string fragments
                all_strings = decoded.strings if decoded.strings else []
                if decoded.text:
                    all_strings = [decoded.text] + all_strings
                matches = [s for s in all_strings if pattern_lower in s.lower()]
                if matches:
                    results.append((cf_name, decode_key(key_bytes), matches))
        except Exception:
            pass
    return results
