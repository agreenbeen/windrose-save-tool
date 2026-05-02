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
