# Rust migration status

The working branch is `rust-port`. The Python v0.7.1 app, its build script and its
release workflow remain the production path until the Rust app is released.
The Rust app now reads and writes the same ledger and settings files as 0.7.1, with
no format change; both versions can be used on the same data. The first time it
opens the ledger it saves a backup in `backupsefore-lootledger-0.8.0.sqlite`.

## Inspection and baseline

- [FEATURES.md](FEATURES.md) inventories the current implementation, SQLite v3,
  stable IDs, settings, pages, data tools and replay limitations.
- [PERF.md](PERF.md) records the release executable's baseline and the limitations
  of the measurements. True cold-cache first paint is not measured yet.
- [Before screenshots](screenshots/before-native) include each of the six pages
  in light/dark, the actual Windows title bar, and the old branded navigation rail.
  `scripts/capture_before.py` reproduces them with synthetic data.

## Stack and spike

The candidate remains pure Rust + Slint 1.18.1/winit 0.30.13, with static CRT on
Windows MSVC. There is no existing web UI in this repository to reuse with Tauri;
the current UI is Qt Widgets. No Slint feature blocker has been established, so
there is no basis for switching to Tauri.

Software rendering is the default candidate. `--no-default-features --features femtovg` enables the
OpenGL comparison. A decision requires measurements of the same spike workload
on both, then measurements again with the complete UI. The preview's bar chart
is explicitly a synthetic rendering workload, not imported match data.

The preview has a frameless, unbranded top bar. The optional page context defaults
off. The app's own HWND is subclassed to provide native caption/edge/maximize
hit testing, system-menu access, DWM corners/shadow and maximized work-area
handling. Windows handles caption dragging and double-clicking. The Win32
subclass is removed at window destruction. No Fortnite window is subclassed.

API evidence:

- [Slint Window/winit access](https://docs.slint.dev/latest/docs/rust/slint/struct.Window)
- [Slint 1.18 no-frame WindowMoveArea](https://www.slint.dev/blog/slint-1.18-released)
- [WM_NCHITTEST](https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-nchittest)
- [Custom title bars and Snap Layouts](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-snap-layout-menu)
- [DWM window attributes](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)

The installed winit source requests per-monitor DPI-awareness v2, with fallbacks
for older Windows. Hit-test unit cases cover 100%, 125%, 150% and 200%; those are
geometry tests, not evidence of mixed-monitor display behavior. Snap Layouts,
Aero Snap, native animations, taskbar auto-hide and physical DPI changes still
need real-display testing. Window-state persistence is not ported yet.

## Data and replay checks

Rust has SQLite v3 support without a schema change: stable UUIDv5 match/event
IDs, the existing SHA-256 player keys, classification, owner/team/unknown split,
notes/tags/favourites, correction validation/auditing, undo, transactional imports,
backups, backup-before-clear, strict backup restore checks and backup-before-old-
schema upgrade. Large-table queries accept page offsets and limits.

The attribution and persisted-row golden checks passed on **100 saved C# parser results**, comparing
the complete summaries, type splits, player identities and deterministic event
IDs. The Python app edited the Rust-created ledger; Rust re-import preserved
its corrections and undone events. The existing ledger was opened read-only and its totals matched. This does
**not** test decoding a replay in Rust.

The Rust replay decoder (`crates/core/src/replay.rs`) is a port of the vendored C# reader limited to
what chest attribution needs. It keeps the old reader's quirks on purpose: export-group path matching,
"incompatible" fields, and the exception points that drop a packet, a bunch or a file. The full gate
(`scripts/golden_rust.py --old-jsonl target/golden/old.jsonl --rust target/release/lootledger-cli.exe`)
passed on 100 local replays (8,971 openings): `parser_parity`, `storage_parity` and the read-only
check of the existing ledger were all true. Two things are normalized: openings with equal times are
compared in (time, actor, episode) order, because the old reader's sort is unstable, and only the
presence of an error is compared, not the .NET exception text. In one process, the 100 replays took
148 s with Fortnite running, against 250 s for the C# helper.

Before the decoder, the Rust replay reader handled file headers, complete chunks,
AES-256-ECB decryption and Oodle decompression. The bit-reader port has its own
tests and a generated FName table. Unreal replicated-actor decoding, external
player names and match event decoding remain to be ported and compared.

`lootledger-cli decode` intentionally exits unsuccessfully until that decoder is
implemented. `scripts/golden_rust.py` defaults to testing actual decoding and
fails at this gate. `--summary-only` is a separately labelled data-layer check;
it cannot mark `parser_parity` true. Corpus/results stay under ignored `target/`
because they can include private account IDs and display names.

The incremental tail indexes only new complete chunks, reads a fixed header
probe to detect finalization and skips encrypted payloads. If the header/key
layout changes, it resets the index. The notify worker debounces file-change
bursts and blocks on a channel while idle. It does not poll the replay folder.
It currently reports file state only; finished imports still belong to Python.
There is no claim of live chest counts while Fortnite withholds the replay key.
A real growing-to-finalized replay was observed in this session: its live key
field contained 32 zero bytes, then became nonzero when `live` cleared. A zero
placeholder is treated as locked, even though the key field has length 32.

## Parity gates still open

| Area | Current state | Required before replacement |
|---|---|---|
| Replay decoder | **Parity passed** on 100 real replays (99 finished, 1 live): every opening, owner, teammate, name, placement, playlist and timestamp equal to the C# reader | Wire into the app's import path (Python still imports); re-run the gate after each Fortnite update |
| Ledger | Read and write the shared SQLite v3 ledger; first Rust launch backs it up (`backups/before-lootledger-0.8.0.sqlite`); statistics match Python on all 36 compared fields of the real ledger | Broader crash/restore tests |
| Live | Tracker port (idle, waiting, live, saving, ended), background import with the Rust decoder, match hand-over, chime, live chip in the title bar | A real match observed end to end |
| Window | Frameless window: caption/resize hit testing, snap layouts, system menu, DWM corners, work-area maximize with auto-hide taskbar edge, logical geometry restore kept on screen, controls dim when inactive | Real-display checks: Snap, mixed DPI, auto-hide taskbar |
| Overview/statistics | All 24 widgets with the 0.7.1 wording; add, remove, resize, drag with drop marker, move buttons, reset; count-up and draw-in animation (Full/Reduced/Off); themed tooltips | Physical drag and 60 fps on a real display |
| Matches/openings/teammates | Filters, sortable virtualized tables, match detail (notes, tags, favourite, timeline, squad, MVP), corrections dialog, remove/restore, +1, undo, exports, teammates records, leaderboard and profile | Screen reader pass |
| Settings | Every 0.7.1 option, plus "Show page title in title bar"; settings export/import in the 0.7.1 format | — |
| Other UI | Command palette (Ctrl+K), shortcut list (? or F1), first-run checklist, What's new, trophy and goal messages, summary image (save or copy), pop-out counter (opacity, size, corner, click-through, teammates), global hotkeys | Hotkey conflicts on other PCs |
| Performance | See PERF.md | Cold-cache first paint |
| Distribution | Python release path retained | Rust release workflow and user approval |

## Developer checks

```powershell
cargo test --workspace
cargo build -p lootledger-cli
.\.venv\Scripts\python.exe scripts\golden_rust.py --old-jsonl target\golden\old.jsonl --summary-only --ledger "$env:LOCALAPPDATA\LootLedger\ledger.sqlite"
# Full gate: decodes every replay in Rust and compares it with the old C# reader.
.\.venv\Scripts\python.exe scripts\golden_rust.py --folder "$env:LOCALAPPDATA\FortniteGame\Saved\Demos"
cargo build --release -p lootledger
.\.venv\Scripts\python.exe scripts\qa_rust.py target\release\lootledger.exe
```

Screenshot capture does not mean every control is implemented or validated.
Keep real input, accessibility and hardware checks explicitly unverified until
they are exercised. Release only after the inventory and these gates are complete.
