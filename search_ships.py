import argparse
from pathlib import Path

from r5_save_tool.db import open_players_db
from r5_save_tool.ue_parser import parse_r5_value


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def search_ship_strings(save_root: Path, patterns: list[str], cf_name: str = "R5BLShip") -> int:
    try:
        db = open_players_db(save_root)
    except Exception as exc:
        print(f"Error opening DB at {save_root}: {exc}")
        return 1

    normalized_patterns = [p.strip().upper() for p in patterns if p.strip()]
    if not normalized_patterns:
        print("No patterns provided.")
        return 1

    with db:
        print(f"Searching {cf_name} in {save_root}...")
        count = 0
        matches = {p: [] for p in normalized_patterns}

        for key, value in db.iter_cf(cf_name):
            count += 1
            key_hex = key.hex()

            raw_upper = value.decode("ascii", errors="ignore").upper()
            for pattern in normalized_patterns:
                if pattern in raw_upper:
                    idx = raw_upper.find(pattern)
                    snippet = raw_upper[max(0, idx - 40):idx + len(pattern) + 40]
                    matches[pattern].append((key_hex, f"RAW: ...{snippet}..."))

            try:
                parsed = parse_r5_value(value)
                for text in _walk_strings(parsed):
                    text_upper = text.upper()
                    for pattern in normalized_patterns:
                        if pattern in text_upper:
                            matches[pattern].append((key_hex, f"PARSED: {text}"))
            except Exception:
                continue

    print(f"Scanned {count} entries.")
    for pattern in normalized_patterns:
        grouped = {}
        for key_hex, hit in matches[pattern]:
            grouped.setdefault(key_hex, set()).add(hit)

        if not grouped:
            print(f"\n{pattern} -> not found")
            continue

        print(f"\nResults for {pattern}:")
        for key_hex in sorted(grouped):
            print(f"  Key Hex: {key_hex}")
            for hit in sorted(grouped[key_hex]):
                print(f"    {hit}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Search ship records for custom string patterns.")
    parser.add_argument(
        "--save-root",
        default="test_saves",
        help="Path to the save root that contains Players DB data (default: test_saves).",
    )
    parser.add_argument(
        "--pattern",
        action="append",
        required=True,
        help="Pattern to search for. Provide multiple --pattern values as needed.",
    )
    parser.add_argument(
        "--cf",
        default="R5BLShip",
        help="Column family to scan (default: R5BLShip).",
    )
    args = parser.parse_args()
    return search_ship_strings(Path(args.save_root), args.pattern, cf_name=args.cf)


if __name__ == "__main__":
    raise SystemExit(main())
