# LootLedger validation

What has been checked, and what has not. Earlier history (the Python app and the screen detector) is in git history and under the `v0.7.1` tag.

## Verified

- **Replay decoder parity (0.8.0):** 100 local replays (99 finished, 1 still live; 8,971 openings) were decoded by the Rust decoder and by the original C# reader. Everything matched:
  - every opening: time, class, searched or broken, who, player, pawn, actor and episode;
  - owner, teammates and display names;
  - placement, total players, eliminations, playlist, session, team size, branch and timestamp.

  Two things were compared loosely: openings with equal times were compared in a fixed order (the old sort is unstable), and only whether a file failed was compared, not the error text. Parity was rechecked after the toolchain change in 0.8.0 and after adding match stats in 0.8.1.
- **Data compatibility (0.8.0):** importing 100 replay results produced the same matches, events, metadata and replay-file rows as the Python 0.7.1 app. Python 0.7.1 opened and edited the Rust-created ledger, and a Rust re-import kept those corrections and undone events.
- **Statistics (0.8.0):** on a copy of the real ledger (131 matches, 3,181 chests), the Rust statistics matched the Python app on all 36 compared fields.
- **Match stats (0.8.1):** re-importing 97 replays into a copy of the real ledger changed no total and added stats to 96 matches.
- **Unit tests:**
  - core: bit reads, headers, partial chunks, live-file detection, imports, corrections, notes, undo, backup and restore, upgrades, exports and statistics;
  - app: settings files, number and duration formats, theme colours (equal to 0.7.1, and WCAG contrast for every preset), hotkey parsing, dashboard packing, chart paths, window hit testing at 100–200% scaling, and the updater (version order, checksum refusal, exe swap);
  - a style guard keeping colours, radii and spacing in the design tokens.
- **Screens:** every page, in dark and light, was rendered off-screen with real data and reviewed. So were the What's new dialog, the Match stats card and the summary and weekly-recap images.
- **Updates:** a live test fetched the latest release from GitHub, downloaded it and verified it against the published SHA-256.
- **Live files:** while Fortnite records, the replay header has a 32-byte all-zero key placeholder, and the key appears when the match ends. LootLedger treats such a file as locked and never tries to decode it.
- **Runtime:** the release exe imports only Windows system DLLs (no dynamic CRT, Python, Qt, .NET or WebView).
- **Taskbar icon (0.8.2):** an off-screen window reported both a large and a small icon through WM_GETICON.
- **Match pop-up (0.8.3):**
  - It was rendered off-screen from demo data, with a unit test of its comparison line (above or below average, on average, best match, first match).
  - Without screenshot mode, the pop-up is created inactive and off-screen, then moved into its corner with a no-activate style.
- **Size build (0.8.3):** `opt-level = "s"`, with the software renderer, path rasteriser, core decoder, Oodle and AES at `opt-level = 3`. This took the exe from 16.4 to 12.9 MB, and every page still renders. The rest is mostly Slint itself:
  - its ICU word-break data, including about 3 MB of Chinese and Japanese dictionaries;
  - its image and SVG decoders, which Slint's winit backend always switches on.

  Going below 10 MB would need a patched Slint or exe compression, which antivirus tools often flag.

## Not yet verified

- A live match from start to finish, the match pop-up and the pop-out counter over Fortnite (on screen, and that the game keeps focus), the chime, and global shortcuts.
- Dragging dashboard cards, tooltips and the clipboard copy with a real mouse.
- Aero Snap, the snap layout popup, an auto-hiding taskbar, display scaling above 100%, mixed-DPI monitors and screen readers.
- A real update from one release to the next (0.8.1 was the first release with the updater; 0.8.2 is the first update it can install), and updating behind a proxy or from a protected folder such as Program Files.
- Performance of the full app after the size build: cold start, memory, idle CPU and frame rate. These need Fortnite closed, because measuring opens a window.
