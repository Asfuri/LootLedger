# Performance baseline and measurement limits

The production reference is the published v0.7.1 `LootLedger.exe`, 82,459,084 bytes
(82.46 MB / 78.64 MiB). Python 3.14, Qt Widgets/PySide6, PyInstaller one-file,
with a self-contained .NET 10 replay helper. The release pipeline remains unchanged.

## Reference measurements, 7 November 2026

Windows x64 on the development PC. `scripts/bench_release.py` starts the actual
release executable with an isolated `LOCALAPPDATA`, no replays, no hotkeys, no live
tracking or overlay, and no What's New dialog. It captures the complete process
tree after 60 seconds, then samples CPU for 30 seconds. The populated case uses
SQLite's backup API to snapshot the real ledger, including its WAL, read-only.
No settings or data in the real profile are changed.

| Metric | Empty ledger | Populated ledger |
|---|---:|---:|
| Matches / events | 0 / 0 | 124 / 2,723 |
| Process count | 2 | 2 |
| Working set after 60 s | 265.27 MiB | 244.66 MiB |
| Private bytes after 60 s | 196.25 MiB | 195.04 MiB |
| Idle CPU, percent of one core | 0.104% | 0.052% |
| Launch to first visible window (proxy) | 10,658 ms | 22,727 ms |
| Cold start to first paint | **Not measured** | **Not measured** |

Raw reports: [empty](perf-python-empty.json), [populated](perf-python-ledger.json).
These are single observations, not medians. OS disk cache was uncontrolled;
Fortnite was running, and compilation overlapped the populated measurement.
The startup values in particular must not be used as a fair speedup claim.
Window visibility does not establish that a composed frame reached the display.
The lower populated working set is measurement variation, not a claim that more
data reduces memory. Repeat matched measurements with compilation stopped before
making a production comparison. A 124-match ledger is representative of this PC;
a substantially larger stress ledger is still needed.

## Replay parsing baseline

The existing standalone self-contained helper decoded one 18,108,139-byte replay
three times, each yielding 165 container episodes. Wall times were 26.594 s,
21.059 s and 12.724 s. Sampled peak working sets were 157.13, 165.35 and 163.98 MiB;
CPU times were at least 4.5625, 3.1875 and 3.015625 core-seconds respectively.
CPU utilization was at least 17.16%, 15.14% and 23.70% of one core over those runs.
These runs overlapped compilation, so they are provisional. The monitor samples
every 20 ms and can miss the last CPU interval before process exit.
Raw report: [parser](perf-python-parser.json).

## Rust comparison

No production comparison is valid yet: the Rust UI is an explicitly labelled,
read-only migration preview, and replicated-actor decoding is not implemented.
A smaller executable showing fewer features cannot establish the requested
full-parity performance improvement. The observations below cover the window
and rendering spike.

### Software-renderer spike observations

The instrumented preview is 11,770,368 bytes (11.77 MB / 11.23 MiB), one process.
After 60 seconds on an empty ledger: 24.22 MiB working set, 7.42 MiB private
bytes, and no measurable CPU increment during the following 30 seconds. Time
to its first visible app window was 2,833 ms. On a snapshot with 127 matches and
2,827 events: 26.68 MiB working set, 8.96 MiB private bytes, 0.0% sampled idle CPU,
and a 2,111 ms first-window proxy.

The Python release was repeated on the same row-count snapshot: 269.79 MiB
working set, 206.17 MiB private bytes, 0.0% sampled idle CPU, 33,137 ms to the
first visible app window. The two populated observations overlapped and OS
cache/game/background load remained uncontrolled. They are observations, not
a controlled benchmark, and the Rust preview implements substantially less UI.
Both prototypes had replay watching disabled in this idle workload.

The motion workload repeatedly grows 12 example bars and reorders two model
cards every 400 ms, with capture enabled explicitly by CLI. In one software run,
405 redraw intervals in the measured 600–4,800 ms window had median 8.45 ms and
p95 19.50 ms. Sampled peak process working set was 33.94 MiB, private bytes
7.61 MiB, and CPU time at least 0.625 core-seconds including startup. This records
winit redraw-event cadence, **not actual presented frames or physical dragging**;
multiple redraws can occur within a display refresh. It does not establish
steady 60 fps. The capture recorder is inactive during normal app operation.

Raw reports: [Rust empty](perf-rust-software-empty.json),
[Rust populated](perf-rust-software-ledger.json),
[Python repeat](perf-python-ledger-repeat.json),
[scripted motion](perf-rust-software-motion.json).
FemtoVG has not been measured yet, so renderer selection remains provisional.

Build options: static CRT on `x86_64-pc-windows-msvc`, LTO, one codegen unit,
stripped release symbols. Slint defaults are disabled; software rendering and
accessibility are enabled. `--no-default-features --features femtovg` builds the OpenGL comparison.
There is no Python, Qt, .NET, Node or WebView runtime in the Rust binary.
Repeat runtime PE import verification on the completed application before release.

The software spike's direct/delay PE imports were checked and contain only
Windows system libraries, including DWM, DirectWrite and UI Automation.
No dynamic CRT, Qt, Python, .NET, Node or WebView import was present. The check
does not trace every runtime LoadLibrary call. Production verification must be
repeated once the complete parser and UI are linked.

## Reproduce

```powershell
.\scripts\perf.ps1 -Exe PATH\LootLedger.exe -Out docs\perf-empty.json
.\scripts\perf.ps1 -Exe PATH\LootLedger.exe -Ledger "$env:LOCALAPPDATA\LootLedger\ledger.sqlite" -Out docs\perf-ledger.json
.\.venv\Scripts\python.exe scripts\bench_parser.py replay-reader\publish\LootLedger.ReplayReader.exe PATH\match.replay --output docs\perf-parser.json
cargo build --release -p lootledger
cargo build --release -p lootledger --no-default-features --features femtovg
```

Use the same ledger, window size, display scaling, overlay/live settings and
settling period for both implementations. Report first-window timing separately
from first-paint timing and cold-cache timing. Measure animation frame cadence
and drag responsiveness on a real display; do not infer 60 fps from a 16 ms timer.
