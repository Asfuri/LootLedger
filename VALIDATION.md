# LootLedger 0.4 validation

Date: 6 November 2026. Windows 11 x64, Fortnite build `++Fortnite+Release-43.00`. Earlier screen-detector records: [VALIDATION-0.3.md](VALIDATION-0.3.md), [VALIDATION-0.2.md](VALIDATION-0.2.md), [VALIDATION-0.1.md](VALIDATION-0.1.md).

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
