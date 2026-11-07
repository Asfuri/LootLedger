# LootLedger validation

# 0.7 live match, motion, UI fixes and new features (not yet released)

Date: 7 November 2026. Windows 11, with Fortnite running in the lobby. No match was played during development.

What the replay files allow during a match, checked on the 100 finished replays on this PC (read-only):

- Every finished replay is encrypted and stores its 32-byte key in the header. Fortnite writes match data in chunks about every 20 s (median gap 20.0 s, about 90 KB each). The game's own log agrees (`httpReplay.ChunkUploadDelayInSeconds:20`).
- The vendored parser, following Unreal's own reader, rejects a replay that is still marked live and encrypted, because the key is written only when the replay is finalized. So the chests of a match can't be read until it ends. LootLedger does not try to get around this: doing so would mean touching the game.
- **Not observed:** a real in-progress replay. A sampler watched the Demos folder for about three hours, but no match was played. If Fortnite does leave the key in a live replay, LootLedger reads it and shows the count during the match; that path is tested only with fixture data.

Verified, and how:

- **Live hand-over:** `scripts/simulate_live.py` writes a real replay the way Fortnite records it (header marked live, no key, chunks appended over time) into a temporary folder, then finalizes it. The tracker goes live → saving → ended, the scan never decodes or records the locked file, and the count equals a direct import (36 = 36 = 36). A second full re-read adds nothing. The finished replay was read 2.9–3.3 s after it was finalized. Unit tests cover the header reader, the state machine and the scan.
- **Paint crash fixed:** the goals ring and the live timeline used `QPen(..., cap=...)`, which PySide6 rejects. A full repaint of the Statistics page crashed the process. A test now paints every page completely and fails on any paint error.
- **Small and large windows:** every page was rendered with real Windows fonts (nothing shown on screen) at 900×600, 1240×860 and 2560×1080, in light and dark, plus XL text at 900×600 and compact density with S text. Fixed: tables that scrolled sideways (columns now fit the width), filter bars wider than the window, the match detail squeezing the table (now a splitter, and the detail scrolls), clipped labels, ghost text from cleared cards, cards too short for wrapped text, the Teammates table and export buttons, and the squad share bars. A test checks the tables fit at 860×580.
- **Dashboard editing:** the drop handler is tested with a synthetic drop event, and the new keyboard buttons (move earlier and later) are tested.
- **Global shortcuts:** a shortcut another app already owns is now reported and skipped, and the others keep working (tested by making registration fail). The shortcut list (press ? or F1) shows each one's state.
- **Window and counter:** size, position and maximized state are restored after a restart (tested). Quitting no longer switches the pop-out counter off.
- **Settings and ledger:** old settings files load, and the old Animations switch becomes the Off level. Ledgers move to schema 3 (a new `match_notes` table) after an automatic backup in `backups/`. Tested on a v2 ledger. Older versions still open a v3 ledger and ignore the new table.
- **Tests:** 173 pass with `pytest`. The packaged-style smoke test passes with 6 pages.

Not yet verified:

- **Live match:** counting during a real live match and the live states with a real match.
- **On a real display:** the pop-out counter over Fortnite, and click-through.
- **Real input:** mouse drag-and-drop on a real display, and global shortcuts pressed while Fortnite has focus.
- **Motion:** that animations keep a steady frame rate on your hardware. Qt Widgets paint on the CPU, so "GPU-friendly" can't be promised; animations only move and fade, and the large tables are not animated.
- **Not built:** staggered table rows, cards gliding to new positions after a reflow, container-transform dialogs, loading skeletons and animated empty states.

# 0.6 teammates

Date: 7 November 2026.

What was wrong:

- The helper already read teammates' searched and broken-open chests. The app threw the split away: the snapshot kept one total per type, and the Broken card showed only your numbers. Teammates' broken-open count could not appear.
- Teammates were keyed by display name, so a renamed teammate became two people.
- Teammate ammo boxes were dropped. The By-type table listed only chest types you had opened, so a type only teammates opened was missing from its rows while the Total row still counted it.
- The "(seen)" label was not explained. Teammate counts are only what the replay recorded.

What changed:

- The helper writes the searching player's Epic id on each chest (`playerId`). Each match stores every player with searched and broken counts per type, and the id is hashed, so the ledger and exports never hold the raw teammate id. The data lives in the match metadata, so the SQLite schema is unchanged.
- Matches saved before this change have no per-player detail. The scanner reads their replay files again on the next scan, if Fortnite still has them. Totals and corrections do not change, because imports are idempotent.
- New Teammates page (leaderboard, records, filters, profile, CSV/JSON export), a squad table in match details with searched, broken, share and types, and teammate figures on the Broken and By-type cards.
- Fixed: "Last 7 days" on the Matches page covered 8 days. It now covers 7, today included.

Checks:

- **Regression on real replays:** 97 replays were read by both the old and the new helper. The 3 others had been removed from the Fortnite folder during the session. The chest events are identical apart from the new id field. The old and new summaries agree on every existing field. Every invariant holds: your total equals your chest events, teammate totals equal their per-type parts, the unattributed count is right, and no player is listed twice.
- **Migration on a copy of the real ledger:** 113 matches, 107 without per-player detail. The scan re-read 98 replay files in 189 s. Afterwards 9 older matches remain without detail because their replay files are gone. Totals are unchanged for all 113 matches, no event was lost or changed, undone and review corrections are kept, and 58 people appear on the Teammates board.
- **Known match:** `python scripts/verify_replays.py` checks the bundled 17:23 squad match (your 27 opened and 9 broken are the hand-counted values). It also reads any replay files you pass in and checks each one. Two more real replays passed.
- **Tests:** 153 pass with `pytest`, 12 of them new (`tests/test_teammates.py`).
- **Smoke test:** the packaged-style smoke test passes with 6 pages.
- **Visual review:** Teammates, Matches detail and Statistics were rendered offscreen in light and dark. Layout fixes: the leaderboard fits without sideways scroll, and the squad table and footnotes wrap.

Limits (what replay files do not show):

- About 20 chests per match (1,911 across the 97 replays) were already open when your game first showed them. The replay has no searching player for them, so nobody is credited. Teammate and "other" counts are therefore lower bounds.
- A teammate far from you may open chests your game never received.
- Two bot records in the replays have no id and no name, so they are not listed. Bots and unnamed players are listed where they appear but never ranked or recorded.
- Only you have a known answer. Teammate counts are checked for consistency and against the previous build, not against a count made by hand.

Not yet verified: teammate counts during a live match, and the Teammates page on a real display at other scales. The release build runs on GitHub Actions: it runs the tests and the packaged smoke test, and the run log holds the result.

# 0.5 interface overhaul

Date: 7 November 2026. Development on Windows 11 x64. The release exe is built and smoke-tested on GitHub's Windows runner.

- **Tests:** 141 pass with `pytest`. They cover the statistics (period deltas, trends, streaks, sessions, heatmap, team share), theme contrast (WCAG AA for text and outlines in light and dark, standard and higher contrast), preference migration and formats, dashboard customization, filters, the match detail and timeline, filtered export, settings export and import, and clearing data with a backup.
- **Visual review:** every page was rendered offscreen from a copy of the 0.4 ledger (about 2,300 openings in 108 matches), in light and dark, at 1000×680 and 1600×1000. Problems found in review and fixed: the navigation rail, horizontal overflow, clipped labels, donut labels and table columns.
- **Speed on that ledger:** window build about 1.3 s. The statistics snapshot takes 0.1–0.2 s and is reused until the data changes. A theme change takes about 2 s, because Qt re-lays out the window.
- **Release build:** GitHub Actions builds the exe, runs the tests, and runs the packaged smoke test (bundled replay reader, icon font, every page). The run log holds the result.

Not yet verified: counting during a live match (Fortnite was not running), drag-and-drop reordering and global shortcuts on a real display, and the look at other display scales.

Earlier screen-detector records: [VALIDATION-0.3.md](VALIDATION-0.3.md), [VALIDATION-0.2.md](VALIDATION-0.2.md), [VALIDATION-0.1.md](VALIDATION-0.1.md).

# 0.4 replay reader

Date: 6 November 2026. Windows 11 x64, Fortnite build `++Fortnite+Release-43.00`.

## Method change

The screen detector found 0/4 openings in the first supplied clip (v0.1) and remained unreliable after redesign. Version 0.4 reads Fortnite's own replay files instead. Each chest replicates `SearchingPawn` when an interaction starts and `bAlreadySearched` when it completes. A pawn maps to its player state, and the replay names the recording player's state (`RecorderPlayerState`). An opening is counted once per container per search episode, so repeated replication and reloading the same replay cannot add duplicates. Cancelled interactions never set `bAlreadySearched` and are not counted.

## Results on real replays

Record: [validation/v0.4-replays.json](validation/v0.4-replays.json).

- **100 / 100** local replays parsed without errors (Build/Zero Build, Solo/Duo/Trio/Squad, Ranked, one non-loot playlist). The run took 39 s for all 100.
- Every searching pawn recorded in those replays resolved to a player. 2,560 searches are "unknown" because the container was first recorded already searched, with no searcher reference left; they are never counted as yours.

### Against independently labelled clips

The two clips you supplied were labelled frame by frame for the screen detector *before* replay reading existed. Each clip was matched to its replay by upload time. The players-left count reconstructed from the replay's elimination events matched each clip title: clip 1 ≈ 42→39 left (title "40 Left") and clip 2 ≈ 38→37 left ("38 Left").

| Clip | Labelled openings (s) | Replay openings in clip window (s) | Matched | Missed | Extra / duplicate |
|---|---|---|---:|---:|---:|
| 40 Left (20.3 s), incl. rapid pair 1.2 s apart | 1.6, 10.6, 11.8, 17.4 | 1.60, 10.73, 11.80, 17.39 | 4 | 0 | 0 |
| 38 Left (10.1 s) | 2.05, 8.25 | 2.05, 8.29 | 2 | 0 | 0 |

The clip start was aligned with the first labelled opening. The other openings and the absence of any extra event in each window are the independent checks. Searching the four-opening pattern across all 100 replays finds exactly one match: the expected replay. These checks run as `tests/test_replay_helper.py` on this PC.

## Automated checks

`pytest`: replay classification, owner/team/other attribution summary, and idempotent imports, including renamed copies and preserved user corrections. Also: the broken-chest toggle, skipping non-loot/ownerless replays, holding back an in-progress replay and importing an abandoned one, v1→v2 ledger migration and backup restore, UI counters, live-match display, and corrections. It also runs the real helper on the labelled clips' replays and on garbage input. The smoke test reads the newest real replay into a temporary ledger and renders every page.

A truncated copy of a finished replay (25%, 50% and 90% of the file) still returned every opening up to the cut-off, including one copy where the parser stopped with an error. This simulates, but does not prove, reading a replay that Fortnite is still writing.

## Not yet verified

- **In-progress reading during a live match.** Fortnite was not running during development. The current-match card depends on how often Fortnite flushes the replay file.
- **Broken-open attribution.** "Broken open" events (container destroyed before a search, with your pawn as `SearchingPawn` and a completed loot animation) were not compared with footage. Many rare chests break open in bursts with ammo boxes, consistent with vault containers releasing their loot together. They are listed separately and can be excluded in Settings.
- **Chest type names** are derived from Fortnite class names, not from footage of each type. Classes not seen yet fall into "Other chest" or "Other container".
- **Teammate counts** include only chests your replay recorded.
- **Future Fortnite updates** may change the replay format. A parse error is reported in the app, and the replay is listed as read with partial data. Use "Read all replays again" after updating LootLedger.
