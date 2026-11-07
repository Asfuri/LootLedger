# LootLedger 0.7.1: what exists today (the parity checklist for the Rust port)

Taken from the code (`lootledger/*.py`, `replay-reader/*.cs`), README, VALIDATION.md and the release notes.
Each line is a feature the Rust version must have, or must list as missing with the reason.

Current Rust implementation status and remaining parity gates: [MIGRATION.md](MIGRATION.md).
The production Python app remains the reference until those gates pass. Retired
screen-recognition modules and their video-analysis/calibration tools are retained
for historical reference; the current desktop app does not use them (see README).

## Current stack

| Part | Today |
|---|---|
| Language and UI | Python 3.14, PySide6 6.x (Qt Widgets), stylesheets generated from Material 3 tokens (`theme.py`), painted widgets for charts (`widgets.py`), shared controls (`controls.py`) |
| Window | Native Windows frame and title bar ("LootLedger"), `QMainWindow`; navigation rail starts with an "inventory_2" icon and a "LootLedger" label |
| Replay parser | Vendored C# FortniteReplayDecompressor (MIT, ~14,500 lines incl. OozSharp Oodle decoder) plus `ChestReplayReader.cs`, built as a .NET 10 self-contained helper `LootLedger.ReplayReader.exe` (~36 MB) and called per batch of 12 files over JSON lines |
| Storage | `%LOCALAPPDATA%\LootLedger\ledger.sqlite` (SQLite, WAL, schema v3), `config.json`, `ui-settings.json`, `backups\` |
| Packaging | PyInstaller one-file exe (~82 MB) that bundles Python, Qt and the .NET helper |
| CI | GitHub Actions `release.yml` on `v*` tags: Python 3.14 + .NET 10, `build.ps1` (pytest, dotnet publish, PyInstaller), packaged smoke test, `gh release create` |

## Data (must stay readable and writable unchanged)

- **ledger.sqlite**, `PRAGMA user_version` 3:
  - `matches(id, started, ended, seconds)`
  - `events(id, match_id, created, video_time, status ∈ confirmed/review/undone/rejected, chest_type, amount, source, confidence, reason, evidence)`
  - `audit(id, created, event_id, action, detail)`
  - `match_meta(match_id, key UNIQUE, meta JSON)`; meta holds: file, playlist, mode, placement, total_players, eliminations, length, owner, owner_id, teammates, containers, team, team_players, players[key, name, me, bot, team, counts{type:{opened,broken}}, containers], unattributed, complete, error, branch, key
  - `replay_files(file, size, mtime, status ∈ imported/skipped, match_id, scanned)`
  - `match_notes(match_id, note, tags, favorite)`
- **Event IDs** are `uuid5(NAMESPACE 2f9c6a4e-8d1b-4e57-9b0a-6c3e1d7f5a21, "{match key}:{actor}:{episode}")`; match IDs are `uuid5(NAMESPACE, match key)`, where the match key is `"{sessionId}:{owner epic id}"` or `"file:{name}"`. These make re-imports idempotent.
- **Player keys** are `"epic-" + sha256(epic id)[:16]`, `"name-{name}"`, or `"anon-{pawn}"`.
- **config.json**: replay_folder, count_broken, scan_seconds (5–600), auto_watch, hotkey_add, hotkey_undo, plus legacy detector fields that must be kept when the file is rewritten.
- **ui-settings.json**: every field in `Prefs` (theme, seed, contrast, corners, density, font_scale, chart_style, motion, background, time_24h, date_format, separators, playtime, default_range, layout, live_tracking, live_seconds, the overlay fields, hotkey_overlay, sound, volume, window_geometry, window_maximized, goal_daily, goal_weekly, celebrate, celebrated, trophies, colorblind, seen_version), plus `animations` written for older versions. Unknown keys and invalid values are ignored.

## Replay reading

- Finds `*.replay` files in the replay folder (default `%LOCALAPPDATA%\FortniteGame\Saved\Demos`), oldest first. It reads a file again when its size or mtime changes, or when its match has no per-player data yet.
- **Attribution:** containers matched by class (chest, ammo, …). The `SearchingPawn` is mapped to a PlayerState and then to me, team, other or unknown. Search episodes come from `bAlreadySearched`, with resets when a container is respawned. A chest counts as broken open when `bDestroyed` is set without a search, a searching pawn is known, and `SearchAnimationCount > 0`.
- **Chest types** come from class name patterns: Rare, Buried, Sprite poster, Relic, Loot cannon, Chest, and Other chest. Ammo boxes, food boxes, fishing barrels and other containers are not chests.
- **Match metadata:** owner (recorder), teammates by team index, playlist and mode name, placement, total players, eliminations, length, session id, branch, and the partial-read flag.
- **Live handling:** an in-progress replay (header says live, encrypted, no key) is never decoded. The header is peeked instead (live, locked, recorded seconds, chunks). An abandoned live replay is imported after 15 minutes.
- **Import is idempotent:** deterministic IDs and `ON CONFLICT DO NOTHING`, so corrections survive re-reads. Replays without an owner or without events are recorded as skipped.
- **Statistics:** per day, week and month; types; heat (weekday × hour) and heat matches; streaks; sessions (30-minute gap); peak hour; best day; records; modes; team totals (opened, broken, types, containers); unattributed count; your share; board (merged per player); records; profiles; MVP per match.

## Pages and features

- **Window:** native frame; size, position and maximized state restored; minimum 860×580; Ctrl+1–6 page shortcuts; Ctrl+K command palette; ? / F1 shortcut list; snackbar messages; scrim behind dialogs; themed tooltips everywhere.
- **Overview:**
  - Cards: live match card, 11 stat tiles (all time, today, week, month, last match, average, best, per hour, playtime, matches, session) with count-up, deltas and sparklines with tooltips, trend chart (7d/30d/90d/All; day/week/month; bar/line/smooth/area), types (donut + table incl. teammates), modes, heatmap with legend, records, team, searched vs broken, setup and replay health, sessions, goals (rings), trophies, compare periods.
  - Customizing: add, remove, resize, drag reorder with a drop marker, keyboard move buttons, and reset layout.
  - Header actions: check now, share summary image (copy or save), pop-out counter.
- **Matches:** search (mode, date, tag, note), date range, mode, chest type, minimum stepper, favourites filter, sortable table (date, mode, place, chests, broken, teammates, ammo, length). The detail pane (in a splitter) shows title, place, length, teammates, a favourite star, tags, note, type bars, a timeline of openings, and a squad table (chests, searched, broken, share bar, types, MVP).
- **Teammates:** mode, range and minimum-matches filters; records (most chests, best match, most played); sortable leaderboard (matches, chests, per match, searched, broken, rare+, best); profile (stats, chests-per-match chart, types, matches together); CSV/JSON export; bots and unnamed players listed but never ranked.
- **Openings:** match timeline; filters (match, type, status, text); table (when, type in its rarity colour, how, count, status, details); remove, restore, correct entry (type and count); manual +1 FAB; undo; export of the visible rows as CSV/JSON (formula-safe CSV); audit trail.
- **Statistics:** every card above at once.
- **Settings:**
  - Appearance: theme, accent presets and custom #rrggbb, higher contrast, corners, density, text size, colourblind chest colours, chart style, background, animations Full/Reduced/Off (follows Windows "Show animations").
  - Overview tiles chips.
  - Formats: 24-hour clock, date format, number separator, playtime style, default range.
  - Replays: folder (edit, browse, open), auto watch, check interval, count broken-open, read all again.
  - Live match and counter: tracking, check interval, counter on/off, opacity, size, position, click-through, teammates, sound and volume.
  - Goals: daily and weekly steppers with presets, celebrate.
  - Shortcuts: global add, undo and counter-toggle hotkeys, with conflict reporting.
  - Data: export ledger (JSON/CSV), create backup, restore backup (integrity, schema and foreign-key checks, safety copy first), open data folder, export and import settings, check for updates (opens the browser only), clear all data (backup first).
- **Live match:** states idle, waiting (Fortnite log active), live (clock, saved-so-far timeline), saving and ended. When a match is counted: count-up, a "+N" pop tinted by the rarest chest, breakdown, teammates, timeline and an optional chime. The status line follows the state.
- **Pop-out counter:** an always-on-top tool window with opacity, size, corner or free position, click-through, saved geometry, a global hotkey, and an optional teammates line.
- **Global hotkeys:** RegisterHotKey for add, undo and overlay. A shortcut taken by another app is skipped and reported.
- **Onboarding and updates:** first-run checklist (folder, replays found, recent matches recorded, with a fix for each); "What's new" once per version.
- **Goals and trophies:** goal rings, streak, trophies (milestones, best match, first relic/buried/sprite, week streak, 100 matches); each announced once in-app.
- **Notes, tags, favourites per match** (schema v3 with an automatic backup before upgrading).
- **Summary image:** 1200×630 PNG, saved or copied to the clipboard.
- **Tools:**
  - `run.py --smoke-test` and `scripts/verify_replays.py` (known match plus consistency).
  - `scripts/simulate_live.py` (live hand-over on a real replay) and `scripts/visual_qa.py` (screenshots and checklist).
  - Tests: 182, including the style guard.
