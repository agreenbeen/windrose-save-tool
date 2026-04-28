# Asset Mapping Reference

This guide explains how item asset paths are discovered, mapped, and verified. Understanding mappings is critical because writes are gated by confidence levels.

## Quick Reference: Confirmed Mappings

These mappings are verified and safe to use:

| Item Name | Confirmed Path | Max Stack | Status |
|-----------|---|---|---|
| Nails | `DA_DID_Resource_Nails_T01` | 500 | ✅ Confirmed |
| Iron Ingot | `DA_DID_Metal_Ingot_Iron_T02` | 200 | ✅ Confirmed |
| Wood | `DA_DID_Resource_Wood_T01` | 400 | ✅ Confirmed |
| Rope | `DA_DID_Resource_Rope_T01` | 300 | ✅ Confirmed |
| Linen Fabric | `DA_DID_Resource_LinenFabric_T02` | 400 | ✅ Confirmed |
| Shipright Tools | `DA_DID_TradeCraft_FineTools_01` | 200 | ✅ Confirmed |
| Plank | `DA_DID_Resource_PlanksWood_T01` | 200 | ✅ Confirmed |
| Tarred Planks | `DA_DID_Resource_TarredPlanks_T03` | 100 | ✅ Confirmed |
| Tarred Fabric | `DA_DID_Resource_TarredFabric_T03` | 100 | ✅ Confirmed |
| Coin Guinea | `DA_DID_Misc_CoinGuinea_T03` | validated as ship inventory insertion | ✅ Confirmed For Ship Insertion |

## Low-Confidence / Broken Mappings

These mappings are problematic and should not be used:

| Item Type | Issue | Status |
|-----------|-------|--------|
| Player Piastre Coins | Player-side writable field is not yet deterministic; fallback offset calibration can target non-authoritative values | ❌ Avoid Routine Use |
| Ship Piastre Coins | Calibrated ship-side edits are observed to work in-game | ✅ Supported (Ship Only) |
| Unknown Items | Not yet mapped to confirmed asset paths | ❌ Blocked |

## Mapping Confidence Levels

Every asset mapping has a confidence level that controls write behavior:

### Confirmed ✅

- Cross-referenced with Steam client manifest (`Manifest_UFSFiles_Win64.txt`)
- Found in multiple saves
- Verified by in-game use
- **Write behavior**: Always allowed

Example:
```json
{
  "item": "nails",
  "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_Nails_T01.DA_DID_Resource_Nails_T01",
  "confidence": "confirmed",
  "verification": "steam_manifest + in_game_verified"
}
```

### Assumed ⚠️

- Inferred from partial evidence or naming patterns
- Not yet verified in-game
- May be incorrect
- **Write behavior**: Blocked by default, allowed with `--confirm-assumed`

Example:
```json
{
  "item": "example_item",
  "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/...",
  "confidence": "assumed",
  "reason": "Pattern-matched from similar items; not yet verified in inventory"
}
```

### Unknown ❌

- No mapping found in current knowledge
- Must be researched before use
- **Write behavior**: Always blocked

## How Mappings Are Discovered

### 1. Manifest Verification (Highest Confidence)

The tool cross-references item asset paths with the Steam client manifest:

```
F:\SteamLibrary\steamapps\common\Windrose\Manifest_UFSFiles_Win64.txt
```

If an asset path appears in this manifest, it is almost certainly correct.

Current tool behavior for `inventory-add-ship` now treats manifest-backed matches as a first-class safe source.
Dry-run output will show `mapping=manifest source=steam_manifest` when a target was validated this way.
If a built-in alias resolves to a manifest-confirmed asset path, dry-run output will show `mapping=manifest source=built_in_alias+steam_manifest`.

**Workflow:**
1. Open the manifest file
2. Search for the item name (e.g., "Nails", "Planks")
3. Find the exact asset path
4. Verify it matches the save data

### 2. In-Game Verification

Add a single item to your inventory and inspect it:

```powershell
# Before: take a snapshot of current inventory
r5-save inventory-inspect --out tmp/before.json

# In game: Pick up one item (e.g., one nail)

# After: take a new snapshot
r5-save inventory-inspect --out tmp/after.json

# Diff the two files to see the new item's asset path
```

The exact asset path should appear in the "after" snapshot.

### 3. Rescue From Failed Writes

If a write was applied with an assumed mapping and it worked:

1. Verify in-game that the item exists and is correct
2. Update the mapping to "confirmed" in `inventory_targets.py`
3. Add a note about how it was verified

## Adding New Mappings

To add a new confirmed mapping:

### Step 1: Discover the Asset Path

Use one of the discovery methods above (manifest, in-game, or from a working write).

### Step 2: Add to inventory_write.py

Edit `r5_save_tool/inventory_targets.py` and add the mapping to `_MAPPED_ASSET_PATHS`:

```python
"example_item_name": {
    "asset_path": "/R5BusinessRules/InventoryItems/DefaultItems/Path/DA_DID_Example_T01.DA_DID_Example_T01",
    "confirmed": True,  # Set to False if you're not certain yet
},
```

Use the full path including the duplicate asset name suffix (e.g., `DA_DID_Example_T01.DA_DID_Example_T01`).

### Step 3: Test with Dry-Run

```powershell
r5-save inventory-add-ship --target example_item_name=1 --dry-run \
  --out tmp/test_new_mapping.json
```

Review the output for:
- No warnings about assumed mappings
- Correct asset path resolved
- Correct max stack capacity detected

### Step 4: Test with Write

If dry-run looks good:

```powershell
# Write one item to test
r5-save inventory-add-ship --target example_item_name=1 --write \
  --out tmp/test_new_mapping_write.json
```

Load the game and verify:
- Item appears in inventory
- Count is correct
- Item is the right type

### Step 5: Mark as Confirmed

Update the mapping to `"confirmed": True` once verified.

## Mapping Lookup Algorithm

When you specify an item name like `nails`, the tool:

1. Normalizes the name (lowercase, remove non-alphanumeric)
2. Looks up in `_MAPPED_ASSET_PATHS` in `inventory_targets.py`
3. Checks the `confirmed` flag
4. If `confirmed=False` and `--confirm-assumed` is not set, blocks the write

Example normalization:
- `"Nails"` → `"nails"`
- `"Linen Fabric"` → `"linenfabric"`
- `"Iron Ingot (Foothills)"` → `"ironingotfoothills"`

## Manifest Verification Process

### Accessing the Manifest

The manifest file location depends on your Steam installation:

```
[STEAM_ROOT]\steamapps\common\Windrose\Manifest_UFSFiles_Win64.txt
```

Common Steam roots:
- `C:\Program Files\Steam\`
- `C:\Program Files (x86)\Steam\`
- `F:\SteamLibrary\` (secondary drive)
- Wherever you installed Steam

### Manifest Format

The file is line-delimited, with entries like:

```
../../../Windrose/Content/Windrose/Business/InventoryItems/DefaultItems/Resource/Nails/DA_DID_Resource_Nails_T01.uasset
../../../Windrose/Content/Windrose/Business/InventoryItems/DefaultItems/Resource/Wood/DA_DID_Resource_Wood_T01.uasset
../../../Windrose/Content/Windrose/Business/InventoryItems/DefaultItems/Resource/LinenFabric/DA_DID_Resource_LinenFabric_T02.uasset
```

### Mapping from Manifest to Save Path

Manifest path:
```
../../../Windrose/Content/Windrose/Business/InventoryItems/DefaultItems/Resource/Nails/DA_DID_Resource_Nails_T01.uasset
```

Becomes save path:
```
/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_Nails_T01.DA_DID_Resource_Nails_T01
```

The pattern is: `/R5BusinessRules/InventoryItems/[...]/[ASSETNAME].[ASSETNAME]`

## Coin Mapping (Special Case)

Coins are treated differently because they don't have item stack structures.

There are now two distinct coin workflows and they should not be conflated:

1. coin counter mutation via `coin-map` and `coin-set`
2. coin item stack insertion via `inventory-add-ship`

The second workflow is now materially stronger because it can use manifest-backed item resolution and has a confirmed live validation for ship-side Guinea insertion.

### Guinea Coins ✅ Confirmed

- High-confidence offset mapping
- Linked counter object in the payload
- Safe to use
- Separately, `DA_DID_Misc_CoinGuinea_T03` is now validated as a ship inventory item insertion target via `inventory-add-ship`

### Piastre Coins ❌ Low Confidence

- Offset calibration is fragile (proximity-based heuristic)
- No linked counter structure to anchor the offset
- Easily broken by small save changes
- **Use with extreme caution or avoid**

Coin mapping workflow:
1. Inspect coins with current amounts visible in-game
2. Use `coin-map` to calibrate offsets
3. Verify offsets in the dry-run
4. Only proceed if confidence is "high"

## Troubleshooting Mappings

### "Mapping has low confidence"

The tool found an asset path but isn't sure it's right.

**Solution:**
1. Verify with `--confirm-assumed` flag and test on a low-value item
2. Use manifest verification before confirming
3. Check in-game after applying to verify correctness

### "Unknown item"

The tool can't find a mapping for the item name.

**Solution:**
1. Check the spelling (e.g., `linenfabric` not `linenfab`)
2. Use manifest search to find the correct asset path
3. Add the mapping to `inventory_targets.py`
4. Test with a dry-run first

### "Mapping mismatch in save"

The tool found a mapping but detected a different asset path in the actual save.

**Solution:**
1. The save may have custom mods or modifications
2. Use `r5-save inventory-inspect --out tmp/inspect.json` to see actual paths
3. Update the mapping to match what's in the save
4. Re-run the command

## Reference: Full Asset Path Format

All item asset paths follow this format:

```
/R5BusinessRules/InventoryItems/[CATEGORY]/[SUBCATEGORY]/[ASSETNAME].[ASSETNAME]
```

Examples:
- `/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_Nails_T01.DA_DID_Resource_Nails_T01`
- `/R5BusinessRules/InventoryItems/DefaultItems/Resource/DA_DID_Resource_Wood_T01.DA_DID_Resource_Wood_T01`
- `/R5BusinessRules/InventoryItems/DefaultItems/TradeCraft/DA_DID_TradeCraft_FineTools_01.DA_DID_TradeCraft_FineTools_01`

The asset name is always repeated twice (before and after the dot).
