# Safety & Recovery Guide

This guide covers backup workflows, recovery procedures, and troubleshooting for the Windrose Save Tool.

## Core Safety Model

The tool implements three layers of safety:

1. **Automatic backups** before any write operation
2. **Dry-run verification** available for all write commands
3. **Clean restore capability** to rollback problematic writes

Always follow this workflow:

1. Run a dry-run first to verify the changes
2. Review the output carefully
3. Apply the write if everything looks correct
4. Test in-game to verify the changes worked

## Backup System

### How Backups Work

Every write operation (coin-set, inventory-add-ship) automatically:

1. Creates a snapshot of the live Players DB
2. Stores it under `r5_save_tool/_backups/Players/[PLAYERID]_[TIMESTAMP]/`
3. Writes a `_backup_manifest.json` with metadata
4. Then applies the write to the live database

### Listing Backups

```powershell
r5-save backups players
```

Output:
```
  0A4AA38532484CFE4D874A73ABC43A82_20260418_202701  (1.4 MB, files=21, current=MANIFEST-035884)
```

The timestamp encodes: YYYYMMDD_HHMMSS

### Backup Integrity

Backups include:

- All RocksDB SST files (sorted string table blocks)
- CURRENT manifest marker
- LOG files and metadata
- `_backup_manifest.json` metadata file

A good backup should have:
- 20+ files (exact count depends on DB activity)
- A valid CURRENT marker
- All column family data intact

## Recovery Procedures

### Restore a Backup

If a write caused problems (game won't boot, corrupted inventory, etc.), restore immediately:

```powershell
# Find the checkpoint you want to restore
r5-save backups players

# Restore a specific backup (uses exact replace, not overlay)
r5-save restore-backup players 0A4AA38532484CFE4D874A73ABC43A82_20260418_202701
```

The restore operation:

1. Clears the live Players DB directory completely
2. Copies all files from the backup directory
3. Verifies the file count matches the backup
4. Checks the CURRENT marker is restored

### Manual Restore (if CLI fails)

If the `restore-backup` command fails, you can manually restore:

```powershell
$live = "C:\Users\[YOU]\AppData\Local\R5\Saved\SaveProfiles\<steam_id>\RocksDB\0.10.0\Players\<dbdir>"
$backup = "C:\path\to\r5-save-tool\r5_save_tool\_backups\Players\<dbdir>_YYYYMMDD_HHMMSS"

# Safety: take a current snapshot first
Copy-Item "$live\*" -Destination "C:\temp\snapshot_$(Get-Date -Format 'yyyyMMdd_HHmmss')" -Recurse -Force

# Clear the live DB
Remove-Item "$live\*" -Recurse -Force

# Restore the backup
Copy-Item "$backup\*" -Destination $live -Recurse -Force
```

### Verify After Restore

After restoring, verify with:

```powershell
# Check the save state
r5-save doctor

# Load a game save in Windrose and verify
# - Inventory is correct
# - Coins match expectations
# - No corruption or missing items
```

## Common Failure Modes

### Boot Failure After Write

**Symptoms:**
- Game starts but hangs during load
- Game crashes to desktop on save load
- "Invalid database" errors in logs

**Cause:**
- RocksDB compression mismatch (written with compression, game expects NoCompression)
- Stale files left in save directory from incomplete restore

**Recovery:**
1. Restore immediately from the last good backup
2. Verify the tool is using NoCompression (it should be by default)
3. If it happens again, check for leftover/stale files in the live DB directory

### Divergent Save Paths

**Symptoms:**
- `r5-save doctor` reports divergence (R5-only or Windrose-only files)
- Different file counts or CURRENT markers

**Cause:**
- Changes made to one path without syncing to the other
- Incomplete overlay restores leaving stale files

**Recovery:**
```powershell
# See which path is diverged
r5-save doctor

# Restore a known-good backup to both paths
r5-save restore-backup players 0A4AA38532484CFE4D874A73ABC43A82_20260418_202701

# Verify paths are now synchronized
r5-save doctor
```

### Missing Inventory Items

**Symptoms:**
- Inventory items disappeared after a write
- Different item counts than expected

**Cause:**
- Slot mapping error (assumed mapping that was incorrect)
- Incomplete item structure write

**Recovery:**
1. Restore from backup before the write
2. Review the mapping confidence in the output JSON
3. Re-run with correct mappings or `--confirm-assumed` if the mapping was assumed

### Coin Values Unchanged

**Symptoms:**
- Coin write completed but in-game values didn't change
- Dry-run and write both reported success

**Cause:**
- Calibration offset was wrong (known values didn't match actual)
- Piastre coins (low-confidence, structural issues)
- Game cached the old value

**Recovery:**
```powershell
# Re-calibrate with current in-game values
r5-save coin-inspect --out tmp/coins_check.json
r5-save coin-map --person-piastre [ACTUAL] --person-guinea [ACTUAL] ...

# Try the write again with updated offsets
r5-save coin-set --known-person-piastre [ACTUAL] ... --set-person-guinea 333 --write
```

## The RocksDB Compression Requirement

This is the single most critical safety rule: **All writes must use NoCompression**.

### Why It Matters

The game's RocksDB configuration uses `NoCompression`. If the tool writes SST files with compression enabled, the game's RocksDB build will either:

1. Refuse to read the compressed blocks (immediate boot failure)
2. Silently skip the blocks (silent data corruption)

### Verification

Check that the tool enforces NoCompression:

1. In `db.py`, look for:
   ```python
   opts.set_compression_type(DBCompressionType.none())
   opts.set_bottommost_compression_type(DBCompressionType.none())
   ```

2. This is applied to both the top-level DB options AND every column family options object

3. If you see any compression settings, the tool is broken and must not be used for writes

### If You Break This Rule

If a write was applied with compression enabled:

1. Restore from backup immediately
2. Verify the tool's `db.py` has the NoCompression settings
3. Never use that backup for anything else (it's corrupted)

## Pre-Flight Checklist

Before any write operation, verify:

- [ ] Live save is bootable (start the game, load a save)
- [ ] Last backup is recent and valid (`r5-save backups players`)
- [ ] Mapping confidence is high (review dry-run output)
- [ ] Dry-run shows expected changes (`--dry-run` flag)
- [ ] No path divergence (`r5-save doctor` shows 0 divergence)

## Path Configuration

The tool looks for saves in this order:

1. **Primary (default)**: `AppData\Local\R5\Saved\SaveProfiles\[STEAMID]\RocksDB\0.10.0\Players\[DBID]`
2. **Mirror (Windrose)**: `AppData\Local\Windrose\Saved\Players\[DBID]`

The tool reads from the primary path and should keep both synchronized.

Use `doctor` to check for divergence:

```powershell
r5-save doctor
```

If paths diverge, restore to both:

```powershell
# Restore the same backup to both paths
r5-save restore-backup players [BACKUP_NAME]

# Manually sync the Windrose mirror if needed
Copy-Item "$r5_path\*" -Destination "$windrose_path\" -Recurse -Force
```

## Testing Safety Procedures

To verify your recovery workflow:

1. Create a known-good checkpoint backup
2. Make a test write (e.g., add 1 coin)
3. Verify in-game that the change worked
4. Restore from the checkpoint
5. Verify in-game that the restore worked
6. Repeat with other write types

This builds confidence in the tool before making critical changes.

## Backup Retention

Keep these backups:

- **Last known-good checkpoint**: Before any experimental writes
- **Pre-write snapshots**: Before each major change
- **Recent backups**: Last 3-5 backups for safety net

Delete:
- Backups older than 2 weeks (unless they're checkpoints)
- Backups from failed experiments (after confirming restore worked)
- Any backup from a write that caused problems (to avoid confusion)

Example cleanup:

```powershell
# List all backups
r5-save backups players

# Delete old ones manually
Remove-Item "r5_save_tool\_backups\Players\0A4AA38_OLD_DATE" -Recurse -Force
```

## Getting Help

If something goes wrong:

1. **Restore from backup** (always the first step)
2. **Check the JSON output** of the failed operation for error details
3. **Review the HTML report** to inspect save state
4. **Use `doctor`** to check for path issues
5. **Consult this guide** for known failure modes

Critical files:
- Backup manifest: `_backup_manifest.json` in backup directory
- CLI output: Always saved to `--out` file for review
- Game logs: `%APPDATA%\Local\Windrose\Saved\Logs\` (if accessible)
