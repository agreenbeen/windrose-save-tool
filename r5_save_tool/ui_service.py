from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .backup import backup_details, list_backups, restore_backup
from .coin import apply_coin_values, inspect_coins, map_coin_offsets_by_known_values
from .inventory import build_inventory_stage_plan, inspect_inventory
from .inventory_targets import _MAPPED_ASSET_PATHS, asset_name_from_path, resolve_inventory_asset_target
from .inventory_write import apply_ship_chest_additions, apply_ship_chest_count_update
from .manifest import (
    load_manifest_inventory_asset_paths,
    locate_windrose_manifest,
    search_manifest_inventory_assets,
)
from .paths import get_writable_base
from .report import generate_html_report
from .save_context import doctor_status, find_save_root, list_captains, resolve_db_dir


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_PATH = PROJECT_ROOT / "tmp" / "ui" / "report" / "latest-report.html"


_LEADING_NOISE_TOKENS = {
    "da",
    "did",
    "aid",
    "bl",
    "misc",
    "default",
    "inventory",
    "items",
}

_DISPLAY_LABEL_OVERRIDES = {
    "DA_DID_Resource_Leather_T01": "Rough Hide",
}


def _friendly_item_label(asset_name: str) -> str:
    override = _DISPLAY_LABEL_OVERRIDES.get(asset_name)
    if override:
        return override

    text = asset_name
    text = re.sub(r"^DA_[A-Z]+_", "", text)
    text = re.sub(r"_T\d+$", "", text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = text.replace("_", " ")
    tokens = [tok for tok in text.split() if tok]
    while tokens and tokens[0].lower() in _LEADING_NOISE_TOKENS:
        tokens.pop(0)
    if not tokens:
        return asset_name
    return " ".join(tok.capitalize() for tok in tokens)


@dataclass
class UIConfigState:
    save_root: str | None = os.environ.get("R5_SAVE_ROOT")
    manifest_path: str | None = os.environ.get("WINDROSE_MANIFEST_PATH") or os.environ.get("STEAM_MANIFEST_PATH")
    captain_uuid: str | None = None


class UIService:
    def __init__(self) -> None:
        self._config = UIConfigState()
        self._sync_manifest_env()

    def _sync_manifest_env(self) -> None:
        manifest_path = (self._config.manifest_path or "").strip() or None
        if manifest_path is None:
            os.environ.pop("WINDROSE_MANIFEST_PATH", None)
            os.environ.pop("STEAM_MANIFEST_PATH", None)
        else:
            os.environ["WINDROSE_MANIFEST_PATH"] = manifest_path
            os.environ["STEAM_MANIFEST_PATH"] = manifest_path
        load_manifest_inventory_asset_paths.cache_clear()

    def _resolve_save_root(self) -> Path:
        return find_save_root(self._config.save_root)

    def _captain_uuid(self) -> str | None:
        return self._config.captain_uuid

    def _config_snapshot(self) -> dict[str, object]:
        manifest = locate_windrose_manifest()
        resolved_save_root = None
        save_root_error = None
        doctor = None
        try:
            root = self._resolve_save_root()
            resolved_save_root = str(root)
            doctor = doctor_status(root)
        except FileNotFoundError as exc:
            save_root_error = str(exc)

        captains: list[dict[str, object]] = []
        try:
            if resolved_save_root:
                from .save_context import list_captains as _list_captains
                captains = _list_captains(Path(resolved_save_root))
        except Exception:
            pass

        return {
            **asdict(self._config),
            "resolved_save_root": resolved_save_root,
            "save_root_error": save_root_error,
            "resolved_manifest_path": str(manifest) if manifest else None,
            "manifest_found": manifest is not None,
            "doctor": doctor,
            "captains": captains,
        }

    def get_status(self) -> dict[str, object]:
        return self._config_snapshot()

    def update_config(self, *, save_root: str | None, manifest_path: str | None, captain_uuid: str | None = None) -> dict[str, object]:
        self._config.save_root = (save_root or "").strip() or None
        self._config.manifest_path = (manifest_path or "").strip() or None
        self._config.captain_uuid = (captain_uuid or "").strip() or None
        if self._config.save_root is None:
            os.environ.pop("R5_SAVE_ROOT", None)
        else:
            os.environ["R5_SAVE_ROOT"] = self._config.save_root
        self._sync_manifest_env()
        return self._config_snapshot()

    def list_captains(self) -> dict[str, object]:
        save_root = self._resolve_save_root()
        return {"captains": list_captains(save_root)}

    def generate_report(self, *, out_path: str | None = None) -> dict[str, object]:
        save_root = self._resolve_save_root()
        final_path = Path(out_path) if out_path else DEFAULT_REPORT_PATH
        final_path.parent.mkdir(parents=True, exist_ok=True)
        generate_html_report(save_root, final_path, captain_uuid=self._captain_uuid())
        return {
            "report_path": str(final_path),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "resolved_save_root": str(save_root),
        }

    def latest_report_path(self) -> Path:
        return DEFAULT_REPORT_PATH

    def search_inventory_catalog(self, *, query: str | None, limit: int) -> dict[str, object]:
        manifest_path = locate_windrose_manifest()
        lowered_query = (query or "").lower()
        normalized_query = re.sub(r"[^a-z0-9]+", "", lowered_query)

        results: list[dict[str, object]] = []
        for alias, mapping in sorted(_MAPPED_ASSET_PATHS.items()):
            asset_path = str(mapping["asset_path"])
            asset_name = asset_name_from_path(asset_path)
            in_game_label = _friendly_item_label(asset_name)
            haystack = f"{alias} {asset_name} {in_game_label} {asset_path}".lower()
            if lowered_query:
                if lowered_query in haystack:
                    pass
                elif normalized_query and normalized_query in re.sub(r"[^a-z0-9]+", "", haystack):
                    pass
                else:
                    continue
            resolved = resolve_inventory_asset_target(alias)
            results.append(
                {
                    "kind": "alias",
                    "requested_value": alias,
                    "display_label": f"{in_game_label} ({alias})",
                    "in_game_label": in_game_label,
                    "alias": alias,
                    "asset_name": resolved["asset_name"],
                    "asset_path": resolved["asset_path"],
                    "mapping_confidence": resolved["mapping_confidence"],
                    "mapping_source": resolved["mapping_source"],
                    "manifest_path": resolved["manifest_path"],
                }
            )

        for entry in search_manifest_inventory_assets(None, limit=None):
            in_game_label = _friendly_item_label(entry["asset_name"])
            haystack = f"{entry['asset_name']} {in_game_label} {entry['asset_path']}".lower()
            if lowered_query:
                if lowered_query in haystack:
                    pass
                elif normalized_query and normalized_query in re.sub(r"[^a-z0-9]+", "", haystack):
                    pass
                else:
                    continue
            results.append(
                {
                    "kind": "manifest",
                    "requested_value": entry["asset_name"],
                    "display_label": in_game_label,
                    "in_game_label": in_game_label,
                    "alias": None,
                    "asset_name": entry["asset_name"],
                    "asset_path": entry["asset_path"],
                    "mapping_confidence": "manifest",
                    "mapping_source": "steam_manifest",
                    "manifest_path": str(manifest_path) if manifest_path else None,
                }
            )

        deduped: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for result in results:
            key = (str(result["kind"]), str(result["requested_value"]))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)
            if len(deduped) >= limit:
                break

        return {
            "query": query,
            "limit": limit,
            "manifest_found": manifest_path is not None,
            "manifest_path": str(manifest_path) if manifest_path else None,
            "results": deduped,
        }

    def resolve_inventory_target(self, *, target: str, strict_manifest: bool = False) -> dict[str, object]:
        return resolve_inventory_asset_target(target, strict_manifest=strict_manifest)

    def inspect_inventory(self, *, ship_capacity: int = 28) -> dict[str, object]:
        save_root = self._resolve_save_root()
        return inspect_inventory(save_root, ship_capacity=ship_capacity, captain_uuid=self._captain_uuid())

    def inventory_plan(
        self,
        *,
        targets: dict[str, int],
        player_open_slots_per_stage: int = 20,
        ship_capacity: int = 28,
        strict_manifest: bool = False,
    ) -> dict[str, object]:
        save_root = self._resolve_save_root()
        return build_inventory_stage_plan(
            save_root,
            targets=targets,
            player_open_slots_per_stage=player_open_slots_per_stage,
            ship_capacity=ship_capacity,
            strict_manifest=strict_manifest,
            captain_uuid=self._captain_uuid(),
        )

    def apply_ship_add(
        self,
        *,
        targets: dict[str, int],
        dry_run: bool,
        allow_assumed_assets: bool,
        strict_manifest: bool,
        preferred_ship_key_prefix: str | None,
    ) -> dict[str, object]:
        save_root = self._resolve_save_root()
        return apply_ship_chest_additions(
            save_root,
            targets=targets,
            dry_run=dry_run,
            allow_assumed_assets=allow_assumed_assets,
            strict_manifest=strict_manifest,
            preferred_ship_key_prefix=preferred_ship_key_prefix,
            captain_uuid=self._captain_uuid(),
        )

    def apply_ship_count(
        self,
        *,
        target: str,
        new_count: int,
        expected_current_count: int | None,
        update_all_matches: bool,
        dry_run: bool,
        strict_manifest: bool,
        preferred_ship_key_prefix: str | None,
    ) -> dict[str, object]:
        save_root = self._resolve_save_root()
        return apply_ship_chest_count_update(
            save_root,
            target=target,
            new_count=new_count,
            expected_current_count=expected_current_count,
            update_all_matches=update_all_matches,
            dry_run=dry_run,
            strict_manifest=strict_manifest,
            preferred_ship_key_prefix=preferred_ship_key_prefix,
            captain_uuid=self._captain_uuid(),
        )

    def inspect_coins(self) -> dict[str, object]:
        save_root = self._resolve_save_root()
        return inspect_coins(save_root, captain_uuid=self._captain_uuid())

    def map_coins(
        self,
        *,
        person_piastre: int,
        person_guinea: int,
        ship_piastre: int,
        ship_guinea: int,
    ) -> dict[str, object]:
        save_root = self._resolve_save_root()
        return map_coin_offsets_by_known_values(
            save_root,
            person_piastre=person_piastre,
            person_guinea=person_guinea,
            ship_piastre=ship_piastre,
            ship_guinea=ship_guinea,
            captain_uuid=self._captain_uuid(),
        )

    def apply_coins(
        self,
        *,
        known_person_piastre: int,
        known_person_guinea: int,
        known_ship_piastre: int,
        known_ship_guinea: int,
        new_person_piastre: int | None,
        new_person_guinea: int | None,
        new_ship_piastre: int | None,
        new_ship_guinea: int | None,
        dry_run: bool,
    ) -> dict[str, object]:
        save_root = self._resolve_save_root()
        return apply_coin_values(
            save_root,
            known_person_piastre=known_person_piastre,
            known_person_guinea=known_person_guinea,
            known_ship_piastre=known_ship_piastre,
            known_ship_guinea=known_ship_guinea,
            new_person_piastre=new_person_piastre,
            new_person_guinea=new_person_guinea,
            new_ship_piastre=new_ship_piastre,
            new_ship_guinea=new_ship_guinea,
            dry_run=dry_run,
            captain_uuid=self._captain_uuid(),
        )

    def list_backups(self, *, db: Literal["players", "accounts"]) -> dict[str, object]:
        save_root = self._resolve_save_root()
        db_dir = resolve_db_dir(save_root, db, captain_uuid=self._captain_uuid() if db == "players" else None)
        backups: list[dict[str, object]] = []
        for backup_path in list_backups(db_dir):
            info = backup_details(backup_path)
            size_bytes = sum(path.stat().st_size for path in backup_path.rglob("*") if path.is_file())
            backups.append(
                {
                    "backup_name": backup_path.name,
                    "backup_path": str(backup_path),
                    "size_bytes": size_bytes,
                    "details": info,
                }
            )
        return {
            "db": db,
            "resolved_db_path": str(db_dir),
            "backups": backups,
        }

    def restore_backup(self, *, db: Literal["players", "accounts"], backup_name: str) -> dict[str, object]:
        save_root = self._resolve_save_root()
        db_dir = resolve_db_dir(save_root, db, captain_uuid=self._captain_uuid() if db == "players" else None)
        backup_root = get_writable_base() / "_backups" / db_dir.parent.name
        backup_path = backup_root / backup_name
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")
        return restore_backup(backup_path, db_dir)


service = UIService()