from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ui_service import service


class ConfigUpdate(BaseModel):
    save_root: str | None = None
    manifest_path: str | None = None
    captain_uuid: str | None = None


class ReportGenerateRequest(BaseModel):
    out_path: str | None = None


class InventoryTargetCount(BaseModel):
    target: str
    count: int = Field(gt=0)


class InventoryResolveRequest(BaseModel):
    target: str
    strict_manifest: bool = False


class InventoryPlanRequest(BaseModel):
    targets: list[InventoryTargetCount]
    player_open_slots_per_stage: int = Field(default=20, ge=1)
    ship_capacity: int = Field(default=28, ge=1)
    strict_manifest: bool = False


class ShipAddRequest(BaseModel):
    targets: list[InventoryTargetCount]
    dry_run: bool = True
    allow_assumed_assets: bool = False
    strict_manifest: bool = False
    preferred_ship_key_prefix: str | None = None


class ShipCountRequest(BaseModel):
    target: str
    new_count: int = Field(ge=0)
    expected_current_count: int | None = Field(default=None, ge=0)
    update_all_matches: bool = False
    dry_run: bool = True
    strict_manifest: bool = False
    preferred_ship_key_prefix: str | None = None


class CoinMapRequest(BaseModel):
    person_piastre: int = Field(ge=0)
    person_guinea: int = Field(ge=0)
    ship_piastre: int = Field(ge=0)
    ship_guinea: int = Field(ge=0)


class CoinSetRequest(BaseModel):
    known_person_piastre: int = Field(ge=0)
    known_person_guinea: int = Field(ge=0)
    known_ship_piastre: int = Field(ge=0)
    known_ship_guinea: int = Field(ge=0)
    new_person_piastre: int | None = Field(default=None, ge=0)
    new_person_guinea: int | None = Field(default=None, ge=0)
    new_ship_piastre: int | None = Field(default=None, ge=0)
    new_ship_guinea: int | None = Field(default=None, ge=0)
    dry_run: bool = True


class RestoreBackupRequest(BaseModel):
    backup_name: str


app = FastAPI(title="Windrose Save Tool UI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:1420", "http://127.0.0.1:1420"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _raise_api_error(exc: Exception) -> None:
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _targets_to_dict(items: list[InventoryTargetCount]) -> dict[str, int]:
    return {item.target: int(item.count) for item in items}


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"ok": True, "status": service.get_status()}


@app.get("/api/config")
def get_config() -> dict[str, object]:
    return service.get_status()


@app.put("/api/config")
def put_config(request: ConfigUpdate) -> dict[str, object]:
    return service.update_config(save_root=request.save_root, manifest_path=request.manifest_path, captain_uuid=request.captain_uuid)


@app.get("/api/captains")
def list_captains() -> dict[str, object]:
    try:
        return service.list_captains()
    except Exception as exc:
        _raise_api_error(exc)


@app.post("/api/report/generate")
def generate_report(request: ReportGenerateRequest) -> dict[str, object]:
    try:
        return service.generate_report(out_path=request.out_path)
    except Exception as exc:
        _raise_api_error(exc)


@app.get("/api/report/latest")
def latest_report() -> FileResponse:
    report_path = service.latest_report_path()
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report has not been generated yet.")
    return FileResponse(report_path, media_type="text/html")


@app.get("/api/inventory/catalog")
def inventory_catalog(
    query: str | None = None,
    limit: int = Query(default=25, ge=1, le=200),
) -> dict[str, object]:
    try:
        return service.search_inventory_catalog(query=query, limit=limit)
    except Exception as exc:
        _raise_api_error(exc)


@app.post("/api/inventory/resolve")
def inventory_resolve(request: InventoryResolveRequest) -> dict[str, object]:
    try:
        return service.resolve_inventory_target(target=request.target, strict_manifest=request.strict_manifest)
    except Exception as exc:
        _raise_api_error(exc)


@app.get("/api/inventory/inspect")
def inventory_inspect(ship_capacity: int = Query(default=28, ge=1, le=200)) -> dict[str, object]:
    try:
        return service.inspect_inventory(ship_capacity=ship_capacity)
    except Exception as exc:
        _raise_api_error(exc)


@app.post("/api/inventory/plan")
def inventory_plan(request: InventoryPlanRequest) -> dict[str, object]:
    try:
        return service.inventory_plan(
            targets=_targets_to_dict(request.targets),
            player_open_slots_per_stage=request.player_open_slots_per_stage,
            ship_capacity=request.ship_capacity,
            strict_manifest=request.strict_manifest,
        )
    except Exception as exc:
        _raise_api_error(exc)


@app.post("/api/inventory/ship-add")
def inventory_ship_add(request: ShipAddRequest) -> dict[str, object]:
    try:
        return service.apply_ship_add(
            targets=_targets_to_dict(request.targets),
            dry_run=request.dry_run,
            allow_assumed_assets=request.allow_assumed_assets,
            strict_manifest=request.strict_manifest,
            preferred_ship_key_prefix=request.preferred_ship_key_prefix,
        )
    except Exception as exc:
        _raise_api_error(exc)


@app.post("/api/inventory/ship-count")
def inventory_ship_count(request: ShipCountRequest) -> dict[str, object]:
    try:
        return service.apply_ship_count(
            target=request.target,
            new_count=request.new_count,
            expected_current_count=request.expected_current_count,
            update_all_matches=request.update_all_matches,
            dry_run=request.dry_run,
            strict_manifest=request.strict_manifest,
            preferred_ship_key_prefix=request.preferred_ship_key_prefix,
        )
    except Exception as exc:
        _raise_api_error(exc)


@app.get("/api/coins/inspect")
def coins_inspect() -> dict[str, object]:
    try:
        return service.inspect_coins()
    except Exception as exc:
        _raise_api_error(exc)


@app.post("/api/coins/map")
def coins_map(request: CoinMapRequest) -> dict[str, object]:
    try:
        return service.map_coins(
            person_piastre=request.person_piastre,
            person_guinea=request.person_guinea,
            ship_piastre=request.ship_piastre,
            ship_guinea=request.ship_guinea,
        )
    except Exception as exc:
        _raise_api_error(exc)


@app.post("/api/coins/set")
def coins_set(request: CoinSetRequest) -> dict[str, object]:
    try:
        return service.apply_coins(
            known_person_piastre=request.known_person_piastre,
            known_person_guinea=request.known_person_guinea,
            known_ship_piastre=request.known_ship_piastre,
            known_ship_guinea=request.known_ship_guinea,
            new_person_piastre=request.new_person_piastre,
            new_person_guinea=request.new_person_guinea,
            new_ship_piastre=request.new_ship_piastre,
            new_ship_guinea=request.new_ship_guinea,
            dry_run=request.dry_run,
        )
    except Exception as exc:
        _raise_api_error(exc)


@app.get("/api/backups/{db}")
def backups(db: Literal["players", "accounts"]) -> dict[str, object]:
    try:
        return service.list_backups(db=db)
    except Exception as exc:
        _raise_api_error(exc)


@app.post("/api/backups/{db}/restore")
def restore_backup_route(
    db: Literal["players", "accounts"],
    request: RestoreBackupRequest,
) -> dict[str, object]:
    try:
        return service.restore_backup(db=db, backup_name=request.backup_name)
    except Exception as exc:
        _raise_api_error(exc)


def main() -> None:
    host = os.environ.get("R5_SAVE_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("R5_SAVE_UI_PORT", "8765"))
    uvicorn.run("r5_save_tool.ui_api:app", host=host, port=port, reload=False)


def _static_dir() -> Path:
    """Return the ui_static directory, handling both dev and PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "r5_save_tool" / "ui_static"
    return Path(__file__).parent / "ui_static"


_ui_static = _static_dir()
if _ui_static.exists():
    app.mount("/ui", StaticFiles(directory=str(_ui_static), html=True), name="ui_static")


if __name__ == "__main__":
    main()