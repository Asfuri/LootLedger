# LootLedger

A Windows chest tracker for Fortnite. It reads the **replay files Fortnite already saves on your PC** and counts every chest *you* opened: per match, per day, per type, all time. Your teammates' chests are shown separately.

No account, no game-memory reading, no injection, no network interception, no gameplay automation. LootLedger only reads `.replay` files after Fortnite writes them. Its only internet traffic is the update check (see below); none of your data is sent.

## Use it

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Download **LootLedger.exe** from [Releases](https://github.com/femboypuppy/LootLedger/releases/latest) and run it. It is a single file with no install. SmartScreen may warn because it is unsigned.
3. Play. Each finished match is read automatically a few seconds after it ends.

Fortnite keeps only your most recent replays (about 100) and deletes older ones. LootLedger keeps every count once it has read a replay.

**Updates** install themselves. LootLedger asks this project's GitHub releases for a newer version and downloads it. It checks the download against GitHub's published SHA-256 and installs it when you close the app, or right away with **Restart now**. Turn this off in **Settings → About**.

### What counts

| Shown as | Fortnite classes (from the replay) | In chest total |
|---|---|---|
| Chest | `Tiered_Chest_Athena_C`, `AlwaysSpawn_NormalChest_C` | yes |
| Rare chest | `AlwaysSpawn_RareChest_C` | yes |
| Relic chest | `B_TieredChest_Relics_C`, `…_Relics_Variant1_C` | yes |
| Buried chest | `B_Athena_BuriedChest_Chest_C`, `…_RelicFinder_C` | yes |
| Sprite poster chest | `B_SpritePosters_Booty_Chest_C` | yes |
| Other chest | any other class with "Chest" in its name | yes |
| Ammo box / Food box / Fishing barrel | `Tiered_Ammo_Athena_C`, … | no, listed separately |

**Broken open** means your damage destroyed the chest before anyone searched it, and its loot spilled. These count by default; you can turn that off in Settings.

**Teammates** only includes chests your replay recorded. Fortnite records what happens near you, so a teammate looting far away is not in your replay. Chests that were already open when your game first saw them are counted in match totals but credited to no one.

### Your data

Everything stays in `%LOCALAPPDATA%\LootLedger`: the ledger (`ledger.sqlite`), `config.json` and `ui-settings.json`. The **Openings** page lets you remove, restore or correct entries, add a manual +1, and undo. Every change is kept in an audit trail, and reading replays again never undoes your edits. Settings → Data has export (JSON or CSV), backups and restore. **Clear all data** saves a backup first.

## Pages

- **Overview:** a customizable dashboard showing the live match, chest totals, trends, chest types, goals, sessions and more. Use the tune button to add, remove, resize and drag cards. The share button saves or copies a summary or weekly-recap image, and the counter button pops out an always-on-top counter.
- **Matches:** search and filters, plus match details: chests by type, a timeline, the squad (with MVP), match stats (damage, accuracy, materials, distance and more), notes, tags and favourites.
- **Openings:** every chest, with filters, corrections and export.
- **Statistics:** every card, including the weekday-by-hour heatmap, match stats, records, trophies and a comparison of any two periods.
- **Teammates:** everyone you played with: records, a sortable leaderboard, a profile for each player, and CSV/JSON export.
- **Settings:** theme, accent colour, contrast, corners, density, text size, animations, formats, the replay folder, the live match and counter, goals, global shortcuts, data tools and updates.

**Ctrl+1** to **Ctrl+6** switch pages. **Ctrl+K** opens the command palette. **?** or **F1** lists every shortcut.

## Build from source

Requirements: Windows 10/11 x64 and Rust (the version is pinned in `rust-toolchain.toml`, so `rustup` installs it).

```powershell
cargo build --release -p lootledger   # target\release\lootledger.exe
cargo test --workspace
```

Pushing a `v*` tag runs `.github/workflows/release.yml`. It checks formatting, lints and tests, builds the exe, confirms it imports only Windows system DLLs, and publishes it to a GitHub release with `.github/release-notes.md`.

### Layout

- `crates/core`: no UI.
  - `container.rs`: the replay file format: header, chunks, decryption and Oodle decompression.
  - `replay.rs` and `bits.rs`: the Unreal replay decoder and chest attribution.
  - `store.rs`: the SQLite ledger.
  - `stats.rs`: statistics.
- `crates/app`: the Slint app.
  - `ui/*.slint`: the interface, with every colour and size in `tokens.slint`.
  - `main.rs`: wiring.
  - `cards.rs`: dashboard cards.
  - `pages.rs`: Matches, Openings and Teammates.
  - `live.rs`: live match and replay import.
  - `update.rs`: updates.
  - `native.rs`: Win32 window, hotkeys and clipboard.
- `scripts/`:
  - `subset_icons.py`: rebuilds the icon font subset.
  - `check_pe_runtime.py`: the runtime-import check used in CI.

[Made with Slint](https://slint.dev). Third-party licences are in [THIRD_PARTY.md](THIRD_PARTY.md); test notes are in [VALIDATION.md](VALIDATION.md).
