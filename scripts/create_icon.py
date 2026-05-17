#!/usr/bin/env python3
"""
Build assets/icon.ico from the master PNG (all sizes from one source image).

Usage (repository root):

  python scripts/create_icon.py

  python scripts/create_icon.py --source assets/windrose-save-tool-icon.png --out assets/icon.ico
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Standard Windows shell / Explorer sizes (single artwork, Lanczos downscale).
ICO_SIZES: tuple[tuple[int, int], ...] = (
    (16, 16),
    (20, 20),
    (24, 24),
    (32, 32),
    (40, 40),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT / "assets" / "windrose-save-tool-icon.png"
DEFAULT_OUT = REPO_ROOT / "assets" / "icon.ico"


def build_icon(source: Path, dest: Path, sizes: tuple[tuple[int, int], ...] = ICO_SIZES) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required. Install build extras: uv sync --extra build"
        ) from exc

    if not source.is_file():
        raise FileNotFoundError(f"Source image not found: {source}")

    with Image.open(source) as img:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="ICO", sizes=list(sizes))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate assets/icon.ico from the master PNG.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Master PNG (square, with alpha).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output .ico path.")
    args = parser.parse_args(argv)

    try:
        build_icon(args.source.resolve(), args.out.resolve())
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Wrote {args.out} ({len(ICO_SIZES)} sizes from {args.source.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
