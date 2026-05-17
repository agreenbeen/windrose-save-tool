# Windrose Save Tool — v1.2 Release Notes

**Multi-captain support.** Saves with more than one captain now work correctly across every screen. The tool auto-selects the right captain from your account's default, or you can switch captains explicitly from the Config screen or the `--captain` flag.

---

## What changed

**Multi-captain save support**
Saves that contain more than one `Players/` directory are now handled end-to-end. The tool reads the `DefaultPlayerId` from your account to auto-select the active captain. No extra configuration needed for single-captain saves — nothing changes there.

**Captain selector in the Config tab**
When more than one captain is detected, a dropdown appears in the Config tab. Each entry shows the captain's name, a short UUID prefix, and which one is marked as last used. Switching the dropdown re-routes all inventory, coin, and report operations to that captain immediately.

**Active captain shown in the sidebar**
The selected captain's name is pinned to the bottom of the nav sidebar, visible from any screen.

**CLI `--captain` flag and `R5_CAPTAIN` env var**
```
r5-save --captain <UUID> inventory-inspect
r5-save list-captains
```
`list-captains` prints every captain with their UUID and which is the default. `--captain` overrides auto-selection on any command.

---

## Fixes and behaviour

- All inventory, coin, and report operations correctly target the selected captain's Players DB
- Auto-selection falls back gracefully when the account DB is unreadable and instructs you to pass `--captain` explicitly
- No change in behaviour for single-captain saves

---

# Windrose Save Tool — v1.1 Release Notes

**Patch to restore compatibility with the v0.10.0 game update.** The upstream game moved its save format in three ways that broke inventory editing. All three are fixed here — if edits were silently doing nothing after the update, this is the release to grab.

---

## What changed in the game

**Save directory renamed.**
The game switched its live save location from `RocksDB/0.10.0/` to `RocksDB_v2/0.10.0/`. The tool was reading from — and writing to — the old path, which the game ignores entirely.

**Inventory slot structure wrapped.**
Item slots are now nested inside an outer container object in the save blob. The slot scanner was picking up both the wrapper and the real slots, then patching the wrapper. Counts appeared to change but the actual slots were untouched.

**Checkpoint ZIP is the authoritative save on load.**
The game restores its live database from a backup ZIP (`RocksDB_v2_Backups/…/_Latest.zip`) every time a save is loaded. Writing directly to the live DB worked until the game launched — then it wiped the changes clean. The tool now rebuilds this ZIP after every write so the changes survive the load.

---

## Fixes in this release

- Resolve save path to `RocksDB_v2/0.10.0/` first, falling back to `RocksDB/0.10.0/` for older installs
- Filter outer container objects from the slot list so only real item slots are patched
- Rebuild the game's checkpoint ZIP after every write so changes persist through game load
- Added `wood` to the confirmed item mapping (was missing from the lookup table despite being in the docs)

---

# Windrose Save Tool — v1.0 Release Notes

**Ahoy, captain.** The first release of the Windrose Save Tool has weighed anchor. She's seaworthy, but she's fresh off the shipyard — expect some rough planks and the occasional unexpected squall. Sail with a backup and you'll make port fine.

---

## What's aboard

**Desktop app — no command line required**
A small dark-themed window gives you a proper helm. Point, click, plunder.

**Inventory → Add Items**
Search by name and drop items straight into your ship's hold. Quantities you choose. Guinea and rope confirmed in live testing.

**Inventory → Edit Counts**
Already have the goods? Adjust how much sits in storage.

**Coins**
Tune your Guinea and Piastre coin amounts. Field mapping is functional but imperfect — treat this as experimental waters.

**Backups**
The tool backs up your save *before every single change*, no exceptions. The Backups screen lets you browse and restore previous saves with one click. If the tool scuttles something, you swim back to safety from here.

**Auto save detection**
Finds your Windrose save automatically on Steam. If it can't, the Config screen will tell you why.

---

## Known rough waters — YAR

- **Coin mapping is best-effort.** The Guinea and Piastre field resolution works in common cases but hasn't been hardened against every save shape. Don't bet the whole treasure chest on it.
- **Item ID mappings are incomplete.** Not every item in the game has a confirmed mapping. Unrecognized items won't appear in search.
- **Windows only.** No Mac, no Linux — this ship doesn't sail those seas yet.
- **Single-player saves only.** Messing with anything else is uncharted territory.
- **The UI is functional, not fancy.** She works. She ain't pretty.
- **This is v1.** There are almost certainly edge cases the crew hasn't encountered yet. Back up early, back up often.

---

## Safety reminder

The backup model is the one thing this tool takes seriously. Every write is preceded by a backup. Use the Backups screen. Trust the backups.

---

*Sail careful, keep your save backed up, and report any leaks you find. — agreenbeen*
