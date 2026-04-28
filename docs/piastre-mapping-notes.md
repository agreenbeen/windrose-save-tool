# Player Piastre Mapping: Why It Is Hard

## Summary

Piastre editing is currently less reliable than other inventory edits, especially for player-side values.

Ship Piastre frequently resolves to a stable, high-confidence offset.
Player Piastre frequently resolves to fallback candidates that drift between runs and between known values.

Current operational strategy: do routine Piastre edits on ship inventory only. Avoid routine player Piastre edits until deterministic player mapping is proven.

This document explains why that happens, what is already understood, and what must be done to make player Piastre writes deterministic.

## Current Behavior

Observed in repeated live tests:

- Ship Piastre can map with high confidence and stable offsets.
- Player Piastre often maps with low or medium confidence.
- Player Piastre candidate offsets can change when known value changes by one (for example 49, 50, 51).
- A write can succeed at the byte level but still not change the in-game player Piastre total.

## Why This Happens

### 1. Fallback Heuristic Ambiguity

Current mapping can fall back to "nearest int32 with known value" relative to a coin object offset.
For player Piastre, many int32 fields near coin data can contain similar small values.
Nearest-value heuristics can select a real field that is not the authoritative gameplay counter.

### 2. Entry-Count Model in Inspection

In many player Piastre snapshots, inspection reports:

- `quantity_model = entry_count`
- `linked_counter = null`
- `inferred_amount_offset = null`

This means the parser is not finding a direct writable counter field for player Piastre in that state.

### 3. Dual Live Save Roots

There are two live roots in practice:

- `AppData/Local/R5/Saved/SaveProfiles/.../Players/<id>`
- `AppData/Local/Windrose/Saved/Players/<id>`

If they diverge, edits can appear to work in one root while the game reads the other, or later overwrite one from the other.

### 4. Root-Sync Timing Errors

A sync in the wrong direction can overwrite a freshly changed state and invalidate a probe run.
This is especially damaging during before/after delta capture.

## What We Do Understand

- Backup-first writes and restore flow are working.
- Compression compatibility is handled correctly (`NoCompression`).
- Ship Piastre path is usually high-confidence and practical.
- Player Piastre requires stronger field identification than fallback proximity.

## Required Safety Policy

Use this policy until player Piastre becomes deterministic:

- Ship Piastre edits are acceptable in routine operation when dry-run calibration passes.
- Player Piastre edits are experimental only and should be avoided for normal workflows.
- Always dry-run first.
- Always verify path divergence with `doctor` before and after write.

## Deterministic Resolution Plan

### 1. No-Clobber Capture Protocol

Before any sync:

1. Determine authoritative root by `CURRENT` timestamp and manifest recency.
2. Capture snapshots from that root only.
3. Only then sync in the same direction (authoritative -> mirror).

### 2. Controlled Delta Probes

For player Piastre:

1. Capture `before` snapshots.
2. Change player Piastre by exactly +1 or -1 in game.
3. Capture `after` snapshots immediately.
4. Diff candidate offsets and keep only fields that move exactly with delta repeatedly.

A candidate should be accepted only after multiple consecutive deltas show stable behavior.

### 3. Prefer Structural Links Over Proximity

Candidate ranking should prefer:

1. explicit attribute/counter linkage
2. stable repeated delta behavior
3. proximity fallback only as last resort

### 4. Add Runtime Hints (Recommended)

If backend/runtime context can provide object ids or authoritative value fields, use that to bypass heuristic matching for player Piastre.

## Practical Next Steps

1. Use ship inventory as the authoritative Piastre edit path for day-to-day operations.
2. Avoid routine player Piastre edits because writes can hit non-authoritative fields.
3. Run no-clobber +1/-1 delta probes only when explicitly working on player Piastre mapping.
4. Promote player Piastre to routine use only after repeated deterministic field confirmation.

## Related Docs

- `docs/architecture.md`
- `docs/SAFETY.md`
- `docs/MAPPINGS.md`
- `docs/examples.md`