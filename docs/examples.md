# Examples

## 1. Inspect The Save Root

Use the default save location:

```powershell
r5-save dump players --cf R5BLPlayer --max 5
```

Point at a specific save root:

```powershell
r5-save --save-root "C:\Users\you\AppData\Local\R5\Saved\SaveProfiles\7656119..." dump players --cf R5BLPlayer
```

## 2. Search For Interesting Data

Search keys:

```powershell
r5-save search-key Inventory
r5-save search-key Quest
```

Search embedded strings in values:

```powershell
r5-save search-value CoinPiastre
r5-save search-value CoinGuinea
```

## 3. Decode A Full Column Family

```powershell
r5-save decode players R5BLPlayer --out tmp/decode/player_decoded.json
r5-save decode accounts R5BLAccount --out tmp/decode/account_decoded.json
```

This is useful when you want structured JSON to inspect offline.

## 4. Generate An HTML Report

```powershell
r5-save report --out tmp/report/r5_save_report.html
```

The report groups keys into sections like inventory, quests, ship, recipes, and account settings.

Recent report UX additions:

- `Inventory Snapshot` is a dedicated default tab
- `Hide null/empty` toggle is enabled by default
- `Inventory At a Glance` projections summarize item counts by scope

## 5. Inspect Coins

```powershell
r5-save coin-inspect --out tmp/coins/coin_inspect.json
```

Typical output includes:

- container sizes
- discovered coin objects
- inferred amounts
- inferred max values, when available
- candidate writable offsets

## 6. Calibrate Coin Offsets

Calibration uses values you already know from the in-game UI.

```powershell
r5-save coin-map --person-piastre 3 --person-guinea 2 --ship-piastre 909 --ship-guinea 7 --out tmp/coins/coin_mapping.json
```

Typical output:

```text
person_piastre: [R5BLPlayer] obj=12 value=3 off=5041 dist=48 conf=high
person_guinea: [R5BLPlayer] obj=16 value=2 off=6102 dist=48 conf=high
ship_piastre: [R5BLShip] obj=14 value=909 off=6204 dist=48 conf=high
ship_guinea: [R5BLShip] obj=13 value=7 off=5842 dist=48 conf=high
```

## 7. Dry-Run A Coin Edit

Always do this first.

```powershell
r5-save coin-set --known-person-piastre 51 --known-person-guinea 1 --known-ship-piastre 103 --known-ship-guinea 0 --set-ship-piastre 133 --dry-run --out tmp/coins/coin_set_dryrun.json
```

That will verify:

- the offsets still map correctly
- the current stored values match your calibration inputs
- the write can be applied safely after calibration

Recommended strategy: perform routine Piastre edits on ship inventory only. Treat player Piastre edits as experimental until player mapping is deterministic.

## 8. Apply The Coin Edit

```powershell
r5-save coin-set --known-person-piastre 51 --known-person-guinea 1 --known-ship-piastre 103 --known-ship-guinea 0 --set-ship-piastre 133 --write --out tmp/coins/coin_set_write.json
```

The tool will:

1. back up the live `Players` DB
2. patch the calibrated int32 offsets
3. write the updated blobs back through RocksDB

## 9. List Available Backups

```powershell
r5-save backups players
r5-save backups accounts
```

Example output:

```
  0A4AA38532484CFE4D874A73ABC43A82_20260418_202701  (1.4 MB, files=21, current=MANIFEST-035884)
  0A4AA38532484CFE4D874A73ABC43A82_20260418_155218  (1.4 MB, files=21, current=MANIFEST-035883)
```

## 10. Check Save State (Doctor Command)

Verify the save paths are correct and detect divergence between R5 and Windrose locations:

```powershell
r5-save doctor
```

Output shows:

```text
Resolved save root: C:\Users\[YOU]\AppData\Local\R5\Saved\SaveProfiles\<steam_id>\RocksDB\0.10.0
Players DB path: C:\Users\[YOU]\AppData\Local\R5\Saved\SaveProfiles\<steam_id>\RocksDB\0.10.0\Players\<dbdir>
Players CURRENT: MANIFEST-035884
Players files: 21
Windrose mirror path: C:\Users\[YOU]\AppData\Local\Windrose\Saved\Players\<dbdir>
Windrose CURRENT: MANIFEST-035884
Windrose files: 21
Divergence: R5-only=0 Windrose-only=0
```

If divergence is detected (R5-only > 0 or Windrose-only > 0), restore from a known-good backup to sync both paths.

## 11. Restore From Backup (Automated)

Use the new CLI command for safe, clean restoration:

```powershell
# List backups to find the one you want
r5-save backups players

# Restore a specific backup (clean replace, not overlay)
r5-save restore-backup players <dbdir>_YYYYMMDD_HHMMSS
```

Output:

```text
Restored from: r5_save_tool\_backups\Players\<dbdir>_YYYYMMDD_HHMMSS
Destination: C:\Users\[YOU]\AppData\Local\R5\Saved\SaveProfiles\<steam_id>\RocksDB\0.10.0\Players\<dbdir>
File count: 21 / expected 21
CURRENT: MANIFEST-035884
Exact match: True
```

The restore operation:

1. Clears the live DB directory completely
2. Copies all files from the backup
3. Verifies file count and CURRENT marker
4. Confirms the restore matches the backup

**If automated restore fails**, see the [Safety & Recovery guide](SAFETY.md) for manual restore procedures.

## 12. Manual Restore (If CLI Fails)

Basic flow with PowerShell:

```powershell
$live = "C:\Users\you\AppData\Local\R5\Saved\SaveProfiles\<id>\RocksDB\0.10.0\Players\<dbdir>"
$backup = "C:\path\to\r5_save_tool\_backups\Players\<dbdir_timestamp>"

# Safety: take a current snapshot first
Copy-Item "$live\*" -Destination "C:\temp\snapshot" -Recurse -Force

# Clear the live DB
Remove-Item "$live\*" -Recurse -Force

# Restore the backup
Copy-Item "$backup\*" -Destination $live -Recurse -Force

# Verify
r5-save doctor
```

## 13. Source-Only Invocation Example

If you are not using the installed `r5-save` entrypoint:

```powershell
.venv\Scripts\python.exe -c "from r5_save_tool.cli import cli; cli()" coin-inspect --out tmp/coins/coin_inspect.json
```

## 14. Inventory Inspection

```powershell
r5-save inventory-inspect --out tmp/inventory/inventory_inspect.json
```

Current inspection output separates:

- `raw_items` for all discovered inventory-like records
- `items` for visible slot-backed inventory
- `detached_items` for unresolved or non-visible candidates

## 15. Complete Workflow Example

A realistic edit workflow:

```powershell
# 1. Check current state
r5-save doctor

# 2. Plan what you want to add
r5-save inventory-inspect --out tmp/current_inventory.json

# 3. Dry-run the changes
r5-save inventory-add-ship --target nails=300 --target planks=50 --strict-manifest --dry-run \
  --out tmp/ship_plan.json

# 4. Review dry-run output for:
#    - Correct mapping confidence (ideally "manifest")
#    - Correct item counts and slot assignments

# 5. Apply the changes
r5-save inventory-add-ship --target nails=300 --target planks=50 --strict-manifest --write \
  --out tmp/ship_write.json

# 6. Test in-game
#    Load a save and verify items are present and counts are correct

# 7. If problems: restore immediately
r5-save backups players  # Find the backup
r5-save restore-backup players [BACKUP_NAME]
r5-save doctor  # Verify sync
```

## 16. Update Existing Ship Stack Count Safely

Use this when the stack already exists in ship storage and you only want to change its count.

```powershell
# Plan only (safe default)
r5-save inventory-set-ship-count \
  --target DA_DID_Reputation_BlackbeardSign_02 \
  --count 420 \
  --current-count 33 \
  --dry-run \
  --out tmp/inventory/ship_set_count_dryrun.json

# Apply write (backup created automatically)
r5-save inventory-set-ship-count \
  --target DA_DID_Reputation_BlackbeardSign_02 \
  --count 420 \
  --current-count 33 \
  --write \
  --out tmp/inventory/ship_set_count_write.json

# Verify
r5-save inventory-inspect --out tmp/inventory/ship_set_count_verify.json
```

Notes:

- `--current-count` prevents accidental writes if the save changed since planning.
- If more than one logical stack matches, the command fails unless you pass `--all-matches`.

## Troubleshooting

If a write succeeds but the game no longer boots:

1. Restore from the last backup immediately (see step 11)
2. Confirm the tool is writing with `NoCompression` (it should be by default)
3. Verify the updated values with a dry-run against the expected post-write values

See the [Safety & Recovery guide](SAFETY.md) for detailed troubleshooting steps.

The compression requirement is not optional. A logically correct write can still produce SST files the game will not load if compression is enabled.

## 18. Validated First Ship Inventory Test

This is the first fully validated inventory insertion workflow that succeeded both offline and in game:

```powershell
r5-save inventory-add-ship \
  --target /R5BusinessRules/InventoryItems/DefaultItems/Misc/DA_DID_Misc_CoinGuinea_T03.DA_DID_Misc_CoinGuinea_T03=222 \
  --target rope=10 \
  --strict-manifest \
  --dry-run \
  --out tmp/first-inventory-test/dryrun.json

r5-save inventory-add-ship \
  --target /R5BusinessRules/InventoryItems/DefaultItems/Misc/DA_DID_Misc_CoinGuinea_T03.DA_DID_Misc_CoinGuinea_T03=222 \
  --target rope=10 \
  --strict-manifest \
  --write \
  --out tmp/first-inventory-test/write.json

r5-save inventory-inspect --out tmp/first-inventory-test/inventory_after.json
```

Observed result:

- the write succeeded
- backup was created automatically
- ship storage contained the expected Guinea and rope stacks after the write
- in-game validation confirmed both items appeared correctly

## 16. Inspect Manifest-Backed Item Resolution

Use the Steam manifest directly to preview resolvable inventory items:

```powershell
r5-save manifest-check rope shiprighttools --query Coin --limit 10
```

This prints:

- the located Steam manifest path
- how provided targets resolve
- whether the target is manifest-backed or only explicit/alias-backed
- matching inventory assets from the manifest

## 17. Fail Closed On Unverified Explicit Paths

When you want to reject explicit inventory paths that are not present in the Steam manifest:

```powershell
r5-save inventory-add-ship \
  --target /R5BusinessRules/InventoryItems/DefaultItems/Misc/DA_DID_Misc_CoinGuinea_T03.DA_DID_Misc_CoinGuinea_T03=222 \
  --strict-manifest \
  --dry-run \
  --out tmp/coins/coin_guinea_plan.json
```

You can use the same `--strict-manifest` flag with `inventory-plan`.
