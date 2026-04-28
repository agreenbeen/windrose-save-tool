"""
HTML report generator — produces a self-contained HTML file for viewing save data.

Groups keys into logical sections, colour-codes values by type, and adds
client-side search/filter.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .coin import _parse_fields_with_offsets, extract_type3_objects
from .db import R5Database, open_accounts_db, open_players_db
from .inventory import _classify_inventory_scope, _dedupe_visible_items, _extract_inventory_items
from .schema import decode_key
from .ue_parser import extract_blackboard, parse_r5_value


# ---------------------------------------------------------------------------
# Namespace grouping
# ---------------------------------------------------------------------------

_SECTION_ORDER = [
    ("Inventory At a Glance", ["InventorySummary."]),
    ("Character", ["Customization.", "Morph.", "Hairs", "Torso", "Legs", "Feets",
                   "Hands", "Headgear", "Face", "Head", "Chest", "Back",
                   "Shoulder", "Forearm", "Leg", "Eyeliner", "Lips",
                   "Cheecks", "Cursemark", "Waist"]),
    ("Quest", ["Quest."]),
    ("Scenario", ["Scenario."]),
    ("Inventory", ["Inventory.", "DropInventory"]),
    ("Progression", ["StatTree.", "Talent.", "/R5BusinessRules/EntityProgression"]),
    ("Recipes", ["Quest.RecipeLootUnlock.", "Quest.RecipePaperUnlock.",
                 "Quest.ItemItemUnlock.", "/R5BusinessRules/Recipes"]),
    ("Ship", ["ShipOwner", "DefaultShipId", "FlagshipId", "PossessedShipId",
              "R5BLShip", "/R5BusinessRules/Ship"]),
    ("UI / Blacklist", ["UI.", "User."]),
    ("Account Settings", ["AccountGameSettings", "CloudSettings", "ColorBlind",
                          "InputSettings", "GamepadSettings", "KeyboardSettings",
                          "MouseSettings", "AudioOutput", "Language"]),
    ("Account Inventory", ["AccountInventory", "IsPersonalInventory", "Modules",
                           "Slots", "ItemsStack"]),
]

_SECTION_LABELS = {
    "Quest.RecipeLootUnlock.": "Recipes",
    "Quest.RecipePaperUnlock.": "Recipes",
    "Quest.ItemItemUnlock.": "Recipes",
}


def _classify(key: str) -> str:
    for section_name, prefixes in _SECTION_ORDER:
        for prefix in prefixes:
            if key.startswith(prefix) or key == prefix.rstrip("."):
                return section_name
    return "Other"


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Windrose Save Tool — {title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e2e8f0; display: flex; height: 100vh; overflow: hidden; }}
  #sidebar {{ width: 220px; min-width: 180px; background: #1a1d27; border-right: 1px solid #2d3148; overflow-y: auto; padding: 12px 0; flex-shrink: 0; }}
  #sidebar h1 {{ font-size: 13px; font-weight: 600; color: #7c85b0; padding: 8px 16px; text-transform: uppercase; letter-spacing: .06em; }}
    #sidebar .controls {{ padding: 8px 16px 10px; border-bottom: 1px solid #2d3148; margin-bottom: 8px; }}
    #sidebar .controls label {{ display: flex; gap: 8px; align-items: center; font-size: 12px; color: #cbd5e1; user-select: none; }}
    #sidebar .controls input {{ accent-color: #6366f1; }}
  #sidebar a {{ display: block; padding: 6px 16px; font-size: 13px; color: #a0aec0; text-decoration: none; border-left: 2px solid transparent; }}
  #sidebar a:hover, #sidebar a.active {{ background: #252840; color: #e2e8f0; border-left-color: #6366f1; }}
  #sidebar .count {{ float: right; background: #2d3148; border-radius: 10px; padding: 1px 7px; font-size: 11px; }}
  #main {{ flex: 1; overflow-y: auto; padding: 20px 28px; }}
  #search-bar {{ position: sticky; top: 0; background: #0f1117; padding-bottom: 12px; z-index: 10; }}
  #search {{ width: 100%; padding: 8px 14px; background: #1a1d27; border: 1px solid #2d3148; border-radius: 6px; color: #e2e8f0; font-size: 14px; outline: none; }}
  #search:focus {{ border-color: #6366f1; }}
  #stats {{ font-size: 12px; color: #4a5568; margin-top: 6px; }}
        .help {{ margin: 12px 0 22px; border: 1px solid #2d3148; border-radius: 8px; background: #111522; padding: 12px; }}
        .help h2 {{ font-size: 14px; color: #c7d2fe; margin: 0 0 10px; }}
        .help p {{ font-size: 12px; color: #cbd5e1; margin: 0 0 8px; }}
        .help ul {{ margin: 0 0 0 18px; color: #94a3b8; font-size: 12px; }}
        .help li {{ margin: 3px 0; }}
    .snapshot {{ margin: 12px 0 22px; border: 1px solid #2d3148; border-radius: 8px; background: #111522; padding: 12px; }}
    .snapshot h2 {{ font-size: 14px; color: #c7d2fe; margin: 0 0 10px; }}
    .snapshot-grid {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
    .snapshot-grid.two-col {{ grid-template-columns: repeat(2, 1fr); }}
    @media (max-width: 900px) {{ .snapshot-grid.two-col {{ grid-template-columns: 1fr; }} }}
    .snapshot-panel {{ border: 1px solid #2d3148; border-radius: 6px; overflow: hidden; background: #0f1421; }}
    .snapshot-panel h3 {{ font-size: 13px; font-weight: 600; color: #e2e8f0; padding: 10px 12px; border-bottom: 1px solid #2d3148; margin: 0; display: flex; align-items: center; gap: 8px; }}
    .snapshot-panel h3 .active-badge {{ font-size: 11px; padding: 2px 6px; background: #059669; color: #fff; border-radius: 3px; font-weight: 600; }}
    .snapshot-panel table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    .snapshot-panel th {{ text-align: left; padding: 8px 10px; color: #94a3b8; border-bottom: 1px solid #2d3148; font-weight: 600; background: #0a0f1b; }}
    .snapshot-panel td {{ padding: 8px 10px; border-bottom: 1px solid #1a1d27; word-break: break-word; }}
    .snapshot-empty {{ padding: 12px 10px; color: #64748b; font-style: italic; text-align: center; }}
  .section {{ margin-bottom: 28px; }}
  .section-header {{ font-size: 15px; font-weight: 600; color: #818cf8; border-bottom: 1px solid #1e2130; padding-bottom: 6px; margin-bottom: 10px; cursor: pointer; user-select: none; display: flex; justify-content: space-between; align-items: center; }}
  .section-header::after {{ content: '▾'; font-size: 11px; color: #4a5568; }}
  .section-header.collapsed::after {{ content: '▸'; }}
  .section-body.collapsed {{ display: none; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }}
  tr {{ border-bottom: 1px solid #1a1d27; }}
  tr:hover {{ background: #141725; }}
  tr.hidden {{ display: none; }}
    td {{ padding: 5px 8px; vertical-align: top; white-space: normal; overflow-wrap: anywhere; }}
    td.key {{ color: #94a3b8; font-family: monospace; width: 42%; word-break: break-word; }}
    td.key .prefix {{ color: #4a5568; }}
    td.val {{ font-family: monospace; width: 58%; word-break: break-word; }}
  .val-true  {{ color: #4ade80; }}
  .val-false {{ color: #f87171; }}
  .val-int   {{ color: #60a5fa; }}
  .val-str   {{ color: #e2e8f0; }}
  .val-blob  {{ color: #6b7280; font-style: italic; }}
  .val-null  {{ color: #4a5568; font-style: italic; }}
    .val-empty {{ color: #64748b; font-style: italic; }}
</style>
</head>
<body>
<nav id="sidebar">
  <h1>Windrose Save Tool</h1>
    <div class="controls">
        <label><input type="checkbox" id="hide-empty" checked onchange="onToggleHideEmpty(this)"> Hide null/empty</label>
    </div>
        <a href="#" onclick="showHelp()" id="nav-help">Helpful</a>
    <a href="#" onclick="showSnapshot()" id="nav-snapshot">Inventory Snapshot</a>
  <a href="#" onclick="showAll()" id="nav-all">All <span class="count" id="total-count">0</span></a>
  {nav_links}
</nav>
<div id="main">
  <div id="search-bar">
    <input id="search" type="text" placeholder="Search keys…" oninput="onSearch(this.value)">
    <div id="stats"></div>
  </div>
        <div id="help-view">
                {help_html}
        </div>
    <div id="snapshot-view">
        {inventory_snapshot_html}
    </div>
    <div id="sections-view">
        {sections_html}
    </div>
</div>
<script>
const sections = {sections_json};
let activeSection = null;
let activeView = 'help';
let hideEmpty = true;
let currentQuery = '';

function _setActiveNav(id) {{
    document.querySelectorAll('#sidebar a').forEach(a => a.classList.remove('active'));
    document.getElementById(id)?.classList.add('active');
}}

function _setViewVisibility(help, snapshot, sections) {{
    document.getElementById('help-view').style.display = help ? '' : 'none';
    document.getElementById('snapshot-view').style.display = snapshot ? '' : 'none';
    document.getElementById('sections-view').style.display = sections ? '' : 'none';
}}

function showHelp() {{
    activeView = 'help';
    activeSection = null;
    _setViewVisibility(true, false, false);
    _setActiveNav('nav-help');
    updateStats();
}}

function applyFilters() {{
    document.querySelectorAll('tr[data-key]').forEach(tr => {{
        const key = tr.dataset.key.toLowerCase();
        const val = tr.dataset.val.toLowerCase();
        const queryMiss = currentQuery.length > 0 && !key.includes(currentQuery) && !val.includes(currentQuery);
        const emptyMiss = hideEmpty && tr.dataset.empty === '1';
        tr.classList.toggle('hidden', queryMiss || emptyMiss);
    }});
}}

function showAll() {{
    activeView = 'all';
  activeSection = null;
        _setViewVisibility(false, false, true);
  document.querySelectorAll('.section').forEach(s => s.style.display = '');
    _setActiveNav('nav-all');
  updateStats();
}}

function showSnapshot() {{
    activeView = 'snapshot';
    activeSection = null;
        _setViewVisibility(false, true, false);
        _setActiveNav('nav-snapshot');
    updateStats();
}}

function showSection(id) {{
    activeView = 'section';
  activeSection = id;
        _setViewVisibility(false, false, true);
  document.querySelectorAll('.section').forEach(s => {{
    s.style.display = s.dataset.section === id ? '' : 'none';
  }});
    _setActiveNav('nav-' + id);
  updateStats();
}}

function onSearch(q) {{
    currentQuery = q.toLowerCase();
    applyFilters();
  updateStats();
}}

function onToggleHideEmpty(el) {{
    hideEmpty = !!el.checked;
    applyFilters();
    updateStats();
}}

function toggleSection(header) {{
  header.classList.toggle('collapsed');
  header.nextElementSibling.classList.toggle('collapsed');
}}

function updateStats() {{
    if (activeView === 'help') {{
        document.getElementById('stats').textContent = 'Helpful overview';
        return;
    }}
    if (activeView === 'snapshot') {{
        document.getElementById('stats').textContent = 'Inventory snapshot view';
        return;
    }}
  const visible = document.querySelectorAll('tr[data-key]:not(.hidden)').length;
  const total = document.querySelectorAll('tr[data-key]').length;
  document.getElementById('stats').textContent = visible === total
    ? `${{total}} entries`
    : `${{visible}} / ${{total}} entries`;
  document.getElementById('total-count').textContent = total;
}}

document.addEventListener('DOMContentLoaded', () => {{
    const cb = document.getElementById('hide-empty');
    hideEmpty = cb ? cb.checked : true;
    showHelp();
    applyFilters();
    updateStats();
}});
</script>
</body>
</html>
"""

_NAV_LINK = '<a href="#" onclick="showSection(\'{id}\')" id="nav-{id}">{label} <span class="count">{count}</span></a>'

_SECTION_HTML = """\
<div class="section" data-section="{id}">
  <div class="section-header" onclick="toggleSection(this)">{label} <span style="color:#4a5568;font-size:12px;font-weight:400">{count} entries</span></div>
  <div class="section-body">
    <table>{rows}</table>
  </div>
</div>"""

_ROW_HTML = '<tr data-key="{key}" data-val="{val}" data-empty="{is_empty}"><td class="key">{key_html}</td><td class="val {val_class}">{val_html}</td></tr>'


def _help_html() -> str:
    """Render stable guidance content for the dedicated Helpful tab."""
    return (
        '<section class="help">'
        "<h2>Helpful</h2>"
        "<p>Core tabs are template-defined and remain stable across fresh report runs.</p>"
        "<ul>"
        "<li><strong>Helpful</strong>: orientation and quick usage notes.</li>"
        "<li><strong>Inventory Snapshot</strong>: player and ship totals at a glance.</li>"
        "<li><strong>All</strong> and section tabs: full key/value explorer.</li>"
        "</ul>"
        "<p>Use <strong>Hide null/empty</strong> for concise browsing, then disable it when auditing raw detail.</p>"
        "</section>"
    )


def _fmt_key(key: str) -> str:
    """Colour the namespace prefix of a dotted key differently."""
    parts = key.rsplit(".", 1)
    if len(parts) == 2:
        return f'<span class="prefix">{html.escape(parts[0])}.</span>{html.escape(parts[1])}'
    return html.escape(key)


def _fmt_val(value: Any) -> tuple[str, str]:
    """Return (css_class, html_repr)."""
    if value is True:
        return "val-true", "true"
    if value is False:
        return "val-false", "false"
    if value is None:
        return "val-null", "null"
    if isinstance(value, int):
        return "val-int", html.escape(str(value))
    if isinstance(value, str):
        if value == "":
            return "val-empty", "(empty)"
        if value.startswith("<blob"):
            return "val-blob", html.escape(value)
        return "val-str", html.escape(value)
    if isinstance(value, dict):
        return "val-blob", html.escape(json.dumps(value, ensure_ascii=False, default=str))
    if isinstance(value, list):
        return "val-blob", html.escape(json.dumps(value, ensure_ascii=False, default=str))
    return "val-str", html.escape(str(value))


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _collect_named_values(obj: Any, name: str) -> list[str]:
    values: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == name and isinstance(v, str) and v.strip():
                values.append(v.strip())
            values.extend(_collect_named_values(v, name))
    elif isinstance(obj, list):
        for item in obj:
            values.extend(_collect_named_values(item, name))
    return values


def _find_first_string_key_like(obj: Any, key_fragment: str) -> str | None:
    fragment = key_fragment.lower()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if fragment in str(k).lower() and isinstance(v, str) and v.strip():
                return v.strip()
            found = _find_first_string_key_like(v, key_fragment)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first_string_key_like(item, key_fragment)
            if found:
                return found
    return None


def _extract_ship_name_from_blob(blob: bytes) -> str | None:
    """
    Extract the ship name from raw R5BLShip blob bytes.

    Ship names are stored with the pattern:
    - "ShipName\0" tag (9 bytes)
    - 4-byte little-endian length
    - Null-terminated string
    """
    import struct

    # Search for "ShipName\0" in the blob
    tag = b"ShipName\x00"
    try:
        idx = blob.find(tag)
        if idx < 0:
            return None

        # Read the 4-byte length (little-endian) after the tag
        length_offset = idx + len(tag)
        if length_offset + 4 > len(blob):
            return None

        length = struct.unpack("<I", blob[length_offset:length_offset+4])[0]

        # Extract the string (should be null-terminated but we use length anyway)
        string_offset = length_offset + 4
        if string_offset + length > len(blob):
            return None

        name_bytes = blob[string_offset:string_offset+length]
        # Decode and strip null terminator
        name = name_bytes.rstrip(b"\x00").decode("utf-8", errors="ignore")

        return name if name else None
    except (struct.error, UnicodeDecodeError, ValueError):
        return None


def _extract_ship_type_from_refs(obj: Any, depth: int = 0) -> str | None:
    """Extract ship type (e.g., 'Ketch') from asset references like 'DA_Ship_Ketch'."""
    import re
    if depth > 8:
        return None

    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and "DA_Ship_" in v:
                match = re.search(r"DA_Ship_(\w+)", v)
                if match:
                    return match.group(1)
            if isinstance(v, (dict, list)):
                result = _extract_ship_type_from_refs(v, depth + 1)
                if result:
                    return result
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                result = _extract_ship_type_from_refs(item, depth + 1)
                if result:
                    return result
    return None


def _marker_matches_key_hex(marker: str, key_hex: str) -> bool:
    m = marker.strip().lower()
    kh = key_hex.strip().lower()
    if not m:
        return False
    if m == kh:
        return True
    try:
        return m.encode("ascii", errors="ignore").hex().lower() == kh
    except Exception:
        return False


def _safe_json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _inventory_entries_for_report(container_label: str, blob: bytes) -> list[tuple[str, Any]]:
    entries: list[tuple[str, Any]] = []
    for item in _extract_inventory_items(blob):
        base = f"Inventory.Items.{container_label}.obj{item['object_id']}.{item['item_name']}"
        entries.append((f"{base}.Count", item["count"]))
        entries.append((f"{base}.MaxValue", item["max_value"]))
        entries.append((f"{base}.ItemId", item["item_id"] if item["item_id"] else None))
        entries.append((f"{base}.AttributesRef", item["attributes_ref"]))
        entries.append((f"{base}.ItemParams", item["item_params"]))
        entries.append((f"{base}.RawItemParams", item.get("raw_item_params")))
        entries.append((f"{base}.SlotName", item.get("slot_name")))
        entries.append((f"{base}.SlotIndex", item.get("slot_index")))
        entries.append((f"{base}.SlotParams", item.get("slot_params")))
        entries.append((f"{base}.IsSlotRecord", item.get("is_slot_record")))
    return entries


def _inventory_projection_entries(container_label: str, blob: bytes) -> list[tuple[str, Any]]:
    """Build concise, item-centric projections for quick at-a-glance inventory review."""
    items = _extract_inventory_items(blob)
    scoped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        scope = "detached"
        if item.get("is_slot_record"):
            slot_name = item.get("slot_name") or ""
            if slot_name == "DA_BL_Slot_Chest":
                scope = "storage"
            elif slot_name.startswith("DA_BL_Slot_Equipment_") or slot_name.startswith("DA_BL_Slot_ShipEquipment_"):
                scope = "equipped"
            else:
                scope = "quick"
        scoped[scope].append(item)

    entries: list[tuple[str, Any]] = []
    base_root = f"InventorySummary.{container_label}"
    for scope in sorted(scoped):
        scope_items = scoped[scope]
        known_counts = [i.get("count") for i in scope_items if isinstance(i.get("count"), int)]
        entries.append((f"{base_root}.{scope}.Stacks", len(scope_items)))
        entries.append((f"{base_root}.{scope}.KnownCountTotal", sum(int(v) for v in known_counts)))
        entries.append((f"{base_root}.{scope}.UnknownCountStacks", len(scope_items) - len(known_counts)))

        by_item: dict[str, dict[str, Any]] = {}
        for item in scope_items:
            name = str(item.get("item_name") or "unknown")
            rec = by_item.setdefault(name, {"stacks": 0, "count_total": 0, "known": 0})
            rec["stacks"] += 1
            if isinstance(item.get("count"), int):
                rec["count_total"] += int(item["count"])
                rec["known"] += 1

        for item_name in sorted(by_item):
            rec = by_item[item_name]
            item_base = f"{base_root}.{scope}.Item.{item_name}"
            entries.append((f"{item_base}.Stacks", rec["stacks"]))
            entries.append((f"{item_base}.CountTotal", rec["count_total"]))
            entries.append((f"{item_base}.KnownCountStacks", rec["known"]))

    return entries


def _inventory_snapshot_html(
    inventory_records: list[dict[str, Any]],
    ship_labels: dict[str, str],
    active_ship_markers: list[str],
) -> str:
    """Render concise player/ship inventory tables for the most common lookup."""
    visible = [rec for rec in _dedupe_visible_items(inventory_records) if rec.get("is_slot_record")]

    def _bucket_for_scope(scope: str) -> str | None:
        if scope in {"player_quick", "player_storage"}:
            return "player"
        if scope in {"ship_storage", "ship_equipped"}:
            return "ship"
        return None

    buckets: dict[str, dict[str, dict[str, Any]]] = {"player": {}}
    ship_buckets: dict[str, dict[str, dict[str, Any]]] = {}
    for rec in visible:
        bucket = _bucket_for_scope(str(rec.get("inventory_scope") or ""))
        if bucket is None:
            continue
        ship_key = str(rec.get("key_hex") or "")
        if bucket == "ship" and not ship_key:
            continue
        name = str(rec.get("item_name") or "unknown")
        if bucket == "ship":
            root = ship_buckets.setdefault(ship_key, {})
        else:
            root = buckets[bucket]

        item = root.setdefault(
            name,
            {
                "item_name": name,
                "item_params": rec.get("item_params"),
                "stacks": 0,
                "known_count_total": 0,
                "known_count_stacks": 0,
            },
        )
        item["stacks"] += 1
        if isinstance(rec.get("count"), int):
            item["known_count_total"] += int(rec["count"])
            item["known_count_stacks"] += 1

    player_rows = sorted(
        buckets["player"].values(),
        key=lambda r: (-int(r["known_count_total"]), str(r["item_name"]).lower()),
    )
    ship_rows_by_key: dict[str, list[dict[str, Any]]] = {}
    for key_hex, rows in ship_buckets.items():
        ship_rows_by_key[key_hex] = sorted(
            rows.values(),
            key=lambda r: (-int(r["known_count_total"]), str(r["item_name"]).lower()),
        )

    player_total = sum(int(r["known_count_total"]) for r in player_rows)
    ship_total = sum(
        int(row["known_count_total"])
        for rows in ship_rows_by_key.values()
        for row in rows
    )

    # Build player inventory HTML
    player_tbody = ""
    for row in player_rows:
        unknown = int(row["stacks"]) - int(row["known_count_stacks"])
        player_tbody += (
            "<tr>"
            f"<td>{html.escape(str(row['item_name']))}</td>"
            f"<td>{row['known_count_total']}</td>"
            f"<td>{row['stacks']}</td>"
            f"<td>{unknown}</td>"
            "</tr>"
        )

    if not player_tbody:
        player_tbody = '<tr><td colspan="4" class="snapshot-empty">No visible player inventory found.</td></tr>'

    ship_entries: list[dict[str, Any]] = []
    ship_index = 1
    for key_hex, rows in sorted(ship_rows_by_key.items(), key=lambda item: item[0]):
        known_total = sum(int(r["known_count_total"]) for r in rows)
        stack_total = sum(int(r["stacks"]) for r in rows)
        top_resources = [
            {
                "item_name": str(r["item_name"]),
                "count": int(r["known_count_total"]),
            }
            for r in rows[:5]
            if int(r["known_count_total"]) > 0
        ]
        ship_name = ship_labels.get(key_hex) or f"Ship #{ship_index}"
        is_active = any(_marker_matches_key_hex(marker, key_hex) for marker in active_ship_markers)
        ship_entries.append(
            {
                "key_hex": key_hex,
                "ship_name": ship_name,
                "is_active": is_active,
                "known_total": known_total,
                "stack_total": stack_total,
                "rows": [
                    {
                        "item_name": str(r["item_name"]),
                        "known_count_total": int(r["known_count_total"]),
                        "stacks": int(r["stacks"]),
                        "unknown": int(r["stacks"]) - int(r["known_count_stacks"]),
                    }
                    for r in rows
                ],
                "top_resources": top_resources,
            }
        )
        ship_index += 1

    if not ship_entries:
        ship_entries = [
            {
                "key_hex": "",
                "ship_name": "No ship inventory found",
                "is_active": False,
                "known_total": 0,
                "stack_total": 0,
                "rows": [],
                "top_resources": [],
            }
        ]

    # Active ship first, then by known total.
    ship_entries.sort(key=lambda e: (0 if e.get("is_active") else 1, -int(e["known_total"]), e["ship_name"].lower()))

    ship_options = "".join(
        f'<option value="{html.escape(e["key_hex"])}">{html.escape(e["ship_name"])}</option>'
        for e in ship_entries
    )

    ship_data_json = _safe_json_for_script(ship_entries)

    # Build the complete snapshot HTML
    html_parts = [
        '<section class="snapshot">',
        "<h2>Inventory Snapshot</h2>",
        f'<div style="font-size:12px;color:#94a3b8;margin-bottom:12px;">',
        f"Player known count total: {player_total} | Fleet known count total: {ship_total}</div>",

        # Player inventory - full width
        '<div class="snapshot-panel" style="margin-bottom:16px;">',
        '<h3>Player Inventory</h3>',
        '<table><thead><tr><th>Item</th><th>Total Count</th><th>Stacks</th><th>Unknown</th></tr></thead>',
        f"<tbody>{player_tbody}</tbody>",
        "</table></div>",

        # Ship selector
        '<div style="display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap;">',
        '<label style="font-size:12px;color:#94a3b8;font-weight:600;">Ship:</label>',
        f'<select id="snapshot-ship-select" style="background:#0f1421;border:1px solid #2d3148;color:#e2e8f0;padding:6px 10px;border-radius:6px;min-width:280px;font-size:12px;cursor:pointer;">{ship_options}</select>',
        '</div>',

        # Ship inventory and top resources - 2 column layout
        '<div class="snapshot-grid two-col">',
        '<div class="snapshot-panel"><h3 id="snapshot-ship-title">Ship Inventory</h3>',
        '<table><thead><tr><th>Item</th><th>Total Count</th><th>Stacks</th><th>Unknown</th></tr></thead>',
        '<tbody id="snapshot-ship-body"></tbody></table></div>',
        '<div class="snapshot-panel"><h3>Top Resources <span id="snapshot-ship-meta" style="font-size:11px;color:#94a3b8;font-weight:400;"></span></h3>',
        '<table><thead><tr><th>Item</th><th>Count</th></tr></thead><tbody id="snapshot-ship-top"></tbody></table></div>',
        "</div></section>",
        f'<script id="snapshot-ship-data" type="application/json">{ship_data_json}</script>',
    ]

    return "".join(html_parts) + (
        '<script>'
        '(function(){'
        'const el=document.getElementById("snapshot-ship-data");'
        'const select=document.getElementById("snapshot-ship-select");'
        'const body=document.getElementById("snapshot-ship-body");'
        'const top=document.getElementById("snapshot-ship-top");'
        'const meta=document.getElementById("snapshot-ship-meta");'
        'const title=document.getElementById("snapshot-ship-title");'
        'if(!el||!select||!body||!top||!title||!meta){console.error("Missing element",{el,select,body,top,title,meta});return;}'
        'let data=[];'
        'try{data=JSON.parse(el.textContent||"[]");}catch(e){console.error("JSON parse error",e);return;}'
        'if(!data.length){console.error("No ship data");return;}'
        'function esc(s){const m={"&":"&amp;","<":"&lt;",">":"&gt;","\\u0022":"&quot;","\\u0027":"&#39;"};return String(s).replace(/[&<>"\']/g,c=>m[c]||c);}'
        'function render(key){'
        'console.log("render called with key",key,"data length",data.length);'
        'let ship=data.find(x=>x.key_hex===key);'
        'if(!ship){'
        'console.warn("Ship not found for key",key,"using first ship");'
        'ship=data[0];'
        '}'
        'if(!ship){console.error("No ship data at all");return;}'
        'const badge=ship.is_active?` <span class="active-badge">ACTIVE</span>`:"";'
        'title.innerHTML=`Ship Inventory — ${esc(ship.ship_name)}${badge}`;'
        'meta.textContent=`(${ship.known_total} items | ${ship.stack_total} stacks)`;'
        'console.log("Rendering",ship.ship_name,"with",ship.rows.length,"rows");'
        'if(!ship.rows||ship.rows.length===0){'
        'body.innerHTML=`<tr><td colspan="4" class="snapshot-empty">No visible inventory found.</td></tr>`;'
        '}else{'
        'body.innerHTML=ship.rows.map(r=>`<tr><td>${esc(r.item_name)}</td><td>${r.known_count_total}</td><td>${r.stacks}</td><td>${r.unknown}</td></tr>`).join("");'
        '}'
        'if(!ship.top_resources||ship.top_resources.length===0){'
        'top.innerHTML=`<tr><td colspan="2" class="snapshot-empty">No resources.</td></tr>`;'
        '}else{'
        'top.innerHTML=ship.top_resources.map(r=>`<tr><td>${esc(r.item_name)}</td><td>${r.count}</td></tr>`).join("");'
        '}'
        '}'
        'select.addEventListener("change",()=>{console.log("Select changed to",select.value);render(select.value);});'
        'if(data.length>0){'
        'console.log("Initial data loaded, first ship key",data[0].key_hex);'
        'render(data[0].key_hex);'
        '}else{'
        'console.error("No ship data to render");'
        '}'
        '})();'
        '</script>'
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_html_report(
    save_root: Path,
    out_path: Path,
) -> None:
    """
    Generate a self-contained HTML report covering both databases.
    """
    all_entries: list[tuple[str, str, Any]] = []  # (db_label, key, value)

    # --- Accounts DB ---
    with open_accounts_db(save_root) as db:
        for cf in db.column_families:
            for key_bytes, val_bytes in db.iter_cf(cf):
                key = decode_key(key_bytes)
                # For account CF, use full parsed data
                if cf == "R5BLAccount":
                    parsed = parse_r5_value(val_bytes)
                    for k, v in parsed.items():
                        if not k.startswith("__"):
                            all_entries.append(("Account", k, v))
                else:
                    all_entries.append(("Account", f"[{cf}] {key}", None))

    inventory_records: list[dict[str, Any]] = []
    ship_labels: dict[str, str] = {}
    active_ship_markers: list[str] = []

    # --- Players DB ---
    with open_players_db(save_root) as db:
        for cf in db.column_families:
            for key_bytes, val_bytes in db.iter_cf(cf):
                key = decode_key(key_bytes)
                if cf == "R5BLPlayer":
                    # Extract blackboard (quest/scenario state)
                    bb = extract_blackboard(val_bytes)
                    for k, v in bb.items():
                        all_entries.append(("Player", k, v))
                    # Top-level fields from structural parse
                    top = parse_r5_value(val_bytes)
                    for marker_name in ("PossessedShipId", "FlagshipId", "DefaultShipId"):
                        for marker_value in _collect_named_values(top, marker_name):
                            if marker_value not in active_ship_markers:
                                active_ship_markers.append(marker_value)
                    for k, v in top.items():
                        if not k.startswith("__") and "." not in k and k not in bb:
                            all_entries.append(("Player", f"[top] {k}", v))

                    # Add normalized inventory item rows with current counts.
                    extracted = _extract_inventory_items(val_bytes)
                    for item in extracted:
                        rec = {
                            "cf": cf,
                            "key_hex": key_bytes.hex(),
                            **item,
                        }
                        rec["inventory_scope"] = _classify_inventory_scope(
                            cf,
                            rec.get("slot_name"),
                            bool(rec.get("is_slot_record")),
                        )
                        inventory_records.append(rec)

                    for inv_key, inv_val in _inventory_entries_for_report("Player", val_bytes):
                        all_entries.append(("Player", inv_key, inv_val))
                    for proj_key, proj_val in _inventory_projection_entries("Player", val_bytes):
                        all_entries.append(("Player", proj_key, proj_val))
                elif cf == "R5BLShip":
                    parsed = parse_r5_value(val_bytes)
                    # Try to extract ship name (in order of preference)
                    ship_name = _extract_ship_name_from_blob(val_bytes)
                    if not ship_name:
                        ship_name = _find_first_string_key_like(parsed, "ShipName")
                    if not ship_name:
                        ship_name = _extract_ship_type_from_refs(parsed)
                    key_hex = key_bytes.hex()
                    if ship_name:
                        ship_labels[key_hex] = ship_name
                    for k, v in parsed.items():
                        if not k.startswith("__"):
                            all_entries.append(("Ship", k, v))

                    extracted = _extract_inventory_items(val_bytes)
                    for item in extracted:
                        rec = {
                            "cf": cf,
                            "key_hex": key_bytes.hex(),
                            **item,
                        }
                        rec["inventory_scope"] = _classify_inventory_scope(
                            cf,
                            rec.get("slot_name"),
                            bool(rec.get("is_slot_record")),
                        )
                        inventory_records.append(rec)

                    for inv_key, inv_val in _inventory_entries_for_report("Ship", val_bytes):
                        all_entries.append(("Ship", inv_key, inv_val))
                    for proj_key, proj_val in _inventory_projection_entries("Ship", val_bytes):
                        all_entries.append(("Ship", proj_key, proj_val))
                else:
                    all_entries.append(("Other", f"[{cf}] {key}", None))

    # --- Group by section ---
    sections: dict[str, list[tuple[str, Any]]] = defaultdict(list)
    for db_label, key, value in all_entries:
        section = _classify(key)
        sections[section].append((key, value))

    # Sort sections by predefined order
    ordered_sections = [name for name, _ in _SECTION_ORDER] + ["Other"]
    ordered_sections = [s for s in ordered_sections if s in sections]

    # --- Build HTML ---
    nav_links = ""
    sections_html_parts = []
    sections_json: list[str] = []

    for section_name in ordered_sections:
        entries = sections[section_name]
        section_id = section_name.replace(" ", "_").replace("/", "_")
        sections_json.append(section_id)

        rows = ""
        for key, value in sorted(entries, key=lambda x: x[0]):
            val_class, val_html = _fmt_val(value)
            rows += _ROW_HTML.format(
                key=html.escape(key, quote=True),
                val=html.escape(str(value), quote=True),
                is_empty="1" if _is_empty_value(value) else "0",
                key_html=_fmt_key(key),
                val_class=val_class,
                val_html=val_html,
            )

        nav_links += _NAV_LINK.format(
            id=section_id,
            label=section_name,
            count=len(entries),
        )
        sections_html_parts.append(
            _SECTION_HTML.format(
                id=section_id,
                label=section_name,
                count=len(entries),
                rows=rows,
            )
        )

    report = _HTML_TEMPLATE.format(
        title="Player Save",
        nav_links=nav_links,
        help_html=_help_html(),
        inventory_snapshot_html=_inventory_snapshot_html(
            inventory_records,
            ship_labels=ship_labels,
            active_ship_markers=active_ship_markers,
        ),
        sections_html="\n".join(sections_html_parts),
        sections_json=json.dumps(sections_json),
    )

    out_path.write_text(report, encoding="utf-8")
    total = len(all_entries)
    print(f"Report written to: {out_path}  ({total} entries, {len(ordered_sections)} sections)")
