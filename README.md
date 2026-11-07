# LootLedger 0.7

A Windows desktop chest tracker for Fortnite. It reads the **replay files Fortnite already saves on your PC** and counts every chest *you* opened: per match, per day, per type, all time. Your teammates' chests are shown separately.

No account, no uploads, no game-memory reading, no injection, no network interception, no gameplay automation. The app only reads `.replay` files after Fortnite writes them.

## Why replays instead of screen capture

Versions 0.1–0.3 tried to recognize chests on screen. That failed in real play: chests appear from every angle and distance, and the detector found 0 of 4 openings in the first clip. Fortnite replays record each chest's state directly. When someone searches a chest, the replay stores *who* searched it (`SearchingPawn`) and *when* the search completed (`bAlreadySearched`). The replay also identifies the recording player, so each opening can be attributed exactly. See [VALIDATION.md](VALIDATION.md).

## Use it

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Download **LootLedger.exe** from [Releases](https://github.com/femboypuppy/LootLedger/releases/latest) and run it (single file, no install; SmartScreen may warn because it is unsigned).
3. Play. Each finished match is read automatically, usually within 20 seconds of returning to the lobby. The first launch reads the replays already on your PC (about 0.4 s each).

The **current match** card shows Idle, Waiting for a match, Live (with the match clock), Saving and Match counted. Fortnite encrypts the replay while it records and writes the key only when the match ends, so the chests appear a few seconds after the match, with a count-up, your split, your teammates and a timeline. During the match LootLedger only reads the replay file's header and the game's log time. It never touches the Fortnite process. The **pop-out counter** is an ordinary always-on-top LootLedger window: drag it, resize it, set its opacity, size and corner, make it click-through, and toggle it with Ctrl+Alt+F10.

Fortnite only keeps your most recent replays (100 here) and deletes older ones. LootLedger keeps every count once it has read a replay, so open it at least once every few dozen matches.

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

**Broken open** means the chest was destroyed by your damage before anyone searched it, and its loot spilled. Several containers in a vault can break open at once. Broken-open chests count by default (shown as a separate line). You can turn that off in **Settings**.

**Teammates** only includes chests your replay recorded. A teammate far from you may open chests your game never received. Some chests were already open when your game first showed them, so the replay cannot say who opened them. They are counted in the match totals but not credited to anyone; the Teammates page shows how many. Teammates are matched by their Epic account id, so a renamed teammate stays one person (the id is stored hashed).

### Corrections

The **Openings** page lists every counted chest. **Remove entry**, **Restore entry**, **Correct entry…** (type/count), **Manual +1** (adds to the latest match) and **Undo last** are recorded in an audit trail. Reading replays again never duplicates entries or undoes your edits. Optional hotkeys can be set in Settings (default Ctrl+Alt+F8 = +1, Ctrl+Alt+F9 = undo).

### Data

The ledger is `%LOCALAPPDATA%\LootLedger\ledger.sqlite` (SQLite, saved immediately). Settings include Export JSON/CSV, Create backup, and Restore backup. Restore validates the file and saves a safety copy first; backups from v0.3 also restore. Your earlier v0.3 data stays in the same ledger.

## Pages and settings

- **Overview:** the current match, all time, today, this week and this month, each compared with the same days in the previous period. Also chests over time (7 days, 30 days, 90 days or all; by day, week or month; bar, line or area), chest types, records and streaks, and your team. Click **Customize** to add, remove, resize and drag cards. **Reset layout** restores the default.
- **Matches:** every match, searchable and filterable by date range, mode, chest type and minimum chests. Select a match to see its chests by type, the squad (you and each teammate, with the MVP and each player's share) and when each opening happened. Column headers sort.
- **Teammates:** everyone who played with you, merged across matches, with searched and broken-open counts, rare chests, each player's best match and records (most chests, best single match, most matches together). Filter by mode, date range and minimum matches, select a player for their profile (chests per match, chest types, matches together), and export the table as CSV or JSON. Bots and unnamed players are listed but never ranked.
- **Openings:** every chest, filtered by match, type, status and text. The timeline above shows the chosen match. **Export** writes exactly the rows you can see, as CSV or JSON.
- **Statistics:** the same cards with a weekday-by-hour heatmap, the game-mode breakdown and the full set of tiles. Also a setup and replay-health checklist, sessions (matches less than 30 minutes apart), daily and weekly goals with rings, trophies, and a card that compares any two date ranges.
- **Matches** also take notes, tags and a favourite star, and the search covers them.
- **Settings:** theme (light, dark or system), accent colour (presets or your own `#rrggbb`), higher contrast, corner shape, density, text size, chart style, background, animations, overview tiles, date, time and number formats, replay folder, auto-watch, counting broken-open chests and shortcuts. Data tools: export, backups, settings export and import, and **Clear all data**, which saves a backup first.

Every setting applies immediately and is saved to `%LOCALAPPDATA%\LootLedger\ui-settings.json`. **Ctrl+1** to **Ctrl+6** switch pages, **Ctrl+K** opens the command palette (pages, matches, teammates, settings), and **?** lists every shortcut. The share button on Overview saves or copies a summary image; nothing is uploaded. **Check for updates** in Settings only opens the releases page in your browser. LootLedger makes no network calls.

## Build from source

Requirements: Windows 10/11 x64, Python 3.11–3.14 x64. The build script installs a private .NET 10 SDK into `.dotnet\` when none is found.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

The script installs locked Python dependencies and publishes the replay reader as a self-contained single file (no .NET install needed to *run* it). It then runs the tests and packages a single `dist\LootLedger.exe` with PyInstaller.

Releases are built by GitHub Actions (`.github/workflows/release.yml`): pushing a `v*` tag runs `build.ps1` on `windows-latest`, smoke-tests the exe and attaches it to a GitHub release. Running the workflow manually uploads the exe as a build artifact instead.

Development:

```powershell
.\.venv\Scripts\python.exe -m pytest -q                       # Includes real-replay checks when the replays exist
.\.venv\Scripts\python.exe run.py                             # Run from source
.\.venv\Scripts\python.exe run.py --smoke-test local-data\smoke
.\dist\LootLedger.exe --smoke-test local-data\smoke-exe
.\replay-reader\publish\LootLedger.ReplayReader.exe [--trace] <file.replay>   # Raw JSON for one replay
```

### Layout

- `replay-reader/`: C# helper. `ChestReplayReader.cs` tracks each container's search/break episodes and resolves the searching pawn to you, a teammate or someone else. `vendor/FortniteReplayDecompressor` is the MIT replay parser, with a small documented patch (`VENDORED.md`).
- `lootledger/replay_reader.py`: runs the helper, classifies chest types, and imports new replays.
- `lootledger/store.py`: SQLite ledger with idempotent replay imports, corrections, stats, and backups.
- `lootledger/app.py`: the window, pages, dashboard customization and actions.
- `lootledger/widgets.py`: cards, buttons, switches, segmented controls, the snackbar, charts and the drag-and-drop grid.
- `lootledger/panels.py`: the dashboard cards and what each one shows.
- `lootledger/theme.py`: Material 3 colour roles built from the accent colour, type, spacing and corner tokens, and the stylesheet generated from them. The icon font is `assets/fonts/MaterialSymbolsRounded.ttf`.
- `lootledger/stats.py`: statistics as plain Python (deltas, trends, streaks, sessions, heatmap).
- `lootledger/prefs.py`: UI preferences and the number, date and duration formats.
- The retired screen detector (`screenvision.py`, `vision.py`, `detector.py`, `worker.py`, `analyze.py`, `replay.py`) remains for reference and its tests. The desktop app no longer uses it.
