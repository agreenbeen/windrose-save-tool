#!/usr/bin/env python3
"""
Measure PyInstaller artifact sizes and optionally time-to-health for CI/local checks.

Writes JSON to stdout or `--out`. Intended for repeatable comparisons after
changing build_exe.spec or dependencies.

Usage (repository root):

  python scripts/measure_exe_size.py --out tmp/exe-size/latest-measure.json

  python scripts/measure_exe_size.py --dist-glob "dist/**/*.exe" --out tmp/exe-size/all-exes.json

  python scripts/measure_exe_size.py --path dist/windrose-save-tool.exe --health-url http://127.0.0.1:8765/api/health

Artifacts go under tmp/exe-size/ when following project hygiene (directory is gitignored).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KiB", "MiB", "GiB"):
        n /= 1024.0
        if n < 1024.0:
            return f"{n:.2f} {unit}"
    return f"{n:.2f} TiB"


def _dir_size(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for p in root.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def _probe_health(url: str, *, timeout_s: float) -> tuple[bool, float | None]:
    """Return (ok, seconds_to_first_success)."""
    deadline = time.monotonic() + max(timeout_s, 0.1)
    started = time.monotonic()
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:  # noqa: S310
                if getattr(resp, "status", None) == 200:
                    return True, time.monotonic() - started
        except KeyboardInterrupt:
            raise
        except OSError:
            pass
        time.sleep(0.05)
    return False, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure EXE/dist folder payload sizes.")
    parser.add_argument("--path", type=Path, help="Single file or directory to measure.")
    parser.add_argument(
        "--dist-glob",
        default="dist/windrose-save-tool.exe",
        help='Glob relative to cwd (default: packaged onefile exe name).',
    )
    parser.add_argument(
        "--health-url",
        help="Optional; poll until HTTP 200 (e.g. http://127.0.0.1:8765/api/health).",
    )
    parser.add_argument(
        "--health-timeout",
        type=float,
        default=30.0,
        help="Max seconds for health polling (default: 30).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write JSON payload to this file (parent dirs created).",
    )
    args = parser.parse_args()

    cwd = Path.cwd()
    scanned: list[dict[str, object]] = []

    if args.path:
        p = args.path.resolve()
        if p.is_dir():
            size = _dir_size(p)
            scanned.append({"path": str(p), "kind": "dir", "bytes": size, "human": _human_bytes(size)})
        elif p.is_file():
            size = p.stat().st_size
            scanned.append({"path": str(p), "kind": "file", "bytes": size, "human": _human_bytes(size)})
        else:
            scanned.append({"path": str(p), "kind": "missing", "bytes": None, "error": "not found"})
    else:
        matches = sorted(cwd.glob(args.dist_glob))
        if not matches:
            scanned.append({"path": args.dist_glob, "kind": "glob", "bytes": None, "error": "no matches"})
        else:
            dir_parents_done: set[Path] = set()
            for p in matches:
                size = p.stat().st_size
                scanned.append({"path": str(p.resolve()), "kind": "file", "bytes": size, "human": _human_bytes(size)})
                parent = p.parent.resolve()
                if parent not in dir_parents_done:
                    dir_parents_done.add(parent)
                    dir_size = _dir_size(parent)
                    scanned.append(
                        {
                            "path": str(parent),
                            "kind": "dir_of_exe",
                            "bytes": dir_size,
                            "human": _human_bytes(dir_size),
                            "note": "directory containing measured exe(s)",
                        }
                    )

    health_ok = None
    health_latency_s = None
    if args.health_url:
        ok, latency = _probe_health(args.health_url, timeout_s=args.health_timeout)
        health_ok = ok
        health_latency_s = round(latency, 3) if latency is not None else None

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cwd": str(cwd.resolve()),
        "entries": scanned,
        "health": {"url": args.health_url, "ok": health_ok, "seconds_to_ready": health_latency_s},
        "environment": {"python": sys.version.split()[0]},
    }

    text = json.dumps(payload, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    print(text)

    missing = any(e.get("kind") == "missing" or e.get("error") for e in scanned)
    health_failed = bool(args.health_url and health_ok is False)
    return 1 if missing or health_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
