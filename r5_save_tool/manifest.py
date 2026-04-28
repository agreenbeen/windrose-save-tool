from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path


_MANIFEST_NAME = "Manifest_UFSFiles_Win64.txt"
_INVENTORY_MARKER = "/InventoryItems/"
_COMMON_STEAM_ROOTS = [
    Path("C:/Program Files/Steam"),
    Path("C:/Program Files (x86)/Steam"),
    Path("D:/SteamLibrary"),
    Path("E:/SteamLibrary"),
    Path("F:/SteamLibrary"),
    Path("G:/SteamLibrary"),
]


def _candidate_manifest_paths() -> list[Path]:
    env_paths: list[Path] = []
    for env_name in ("WINDROSE_MANIFEST_PATH", "STEAM_MANIFEST_PATH"):
        raw = os.environ.get(env_name)
        if raw:
            env_paths.append(Path(raw))

    paths = env_paths[:]
    for root in _COMMON_STEAM_ROOTS:
        paths.append(root / "steamapps" / "common" / "Windrose" / _MANIFEST_NAME)
    return paths


def locate_windrose_manifest() -> Path | None:
    for candidate in _candidate_manifest_paths():
        if candidate.exists():
            return candidate
    return None


def _manifest_line_to_asset_path(line: str) -> str | None:
    normalized = line.strip().replace("\\", "/")
    if _INVENTORY_MARKER not in normalized:
        return None

    marker_index = normalized.find(_INVENTORY_MARKER)
    suffix = normalized[marker_index + len(_INVENTORY_MARKER) :]
    suffix = suffix.lstrip("/")
    if not suffix:
        return None

    stem = suffix.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.split(".", 1)[0]
    if not stem:
        return None

    parts = suffix.split("/")
    if len(parts) < 2:
        return None

    category_parts = parts[:-1]
    return "/R5BusinessRules/InventoryItems/" + "/".join(category_parts) + f"/{stem}.{stem}"


@lru_cache(maxsize=1)
def load_manifest_inventory_asset_paths() -> dict[str, str]:
    manifest_path = locate_windrose_manifest()
    if manifest_path is None:
        return {}

    asset_paths: dict[str, str] = {}
    with manifest_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            asset_path = _manifest_line_to_asset_path(line)
            if asset_path is None:
                continue
            asset_name = asset_path.rsplit("/", 1)[-1].split(".", 1)[0]
            asset_paths.setdefault(asset_name.lower(), asset_path)
    return asset_paths


def resolve_manifest_inventory_asset(name_or_path: str) -> dict[str, str] | None:
    manifest_path = locate_windrose_manifest()
    if manifest_path is None:
        return None

    inventory_assets = load_manifest_inventory_asset_paths()
    if name_or_path.startswith("/R5BusinessRules/InventoryItems/"):
        asset_name = name_or_path.rsplit("/", 1)[-1].split(".", 1)[0].lower()
        manifest_asset = inventory_assets.get(asset_name)
        if manifest_asset == name_or_path:
            return {"asset_path": manifest_asset, "manifest_path": str(manifest_path)}
        return None

    normalized = "".join(ch.lower() for ch in name_or_path if ch.isalnum())
    for asset_name, asset_path in inventory_assets.items():
        if normalized == "".join(ch.lower() for ch in asset_name if ch.isalnum()):
            return {"asset_path": asset_path, "manifest_path": str(manifest_path)}
    return None


def search_manifest_inventory_assets(query: str | None = None, *, limit: int | None = None) -> list[dict[str, str]]:
    assets = load_manifest_inventory_asset_paths()
    lowered_query = query.lower() if query else None
    normalized_query = re.sub(r"[^a-z0-9]+", "", lowered_query) if lowered_query else None

    results: list[dict[str, str]] = []
    for _, asset_path in sorted(assets.items(), key=lambda pair: pair[0]):
        asset_name = asset_path.rsplit("/", 1)[-1].split(".", 1)[0]
        haystack = f"{asset_name} {asset_path}".lower()
        if lowered_query:
            if lowered_query in haystack:
                pass
            elif normalized_query and normalized_query in re.sub(r"[^a-z0-9]+", "", haystack):
                pass
            else:
                continue
        results.append({"asset_name": asset_name, "asset_path": asset_path})
        if limit is not None and len(results) >= limit:
            break
    return results
