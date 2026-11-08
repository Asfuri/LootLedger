Download **LootLedger.exe** and run it. No install needed.

## What's new in 0.8.0

- **Rebuilt as a native Windows app.** The exe is about 16 MB instead of 82 MB and uses around 30–40 MB of memory instead of about 250 MB. There is no Python, Qt or .NET inside any more.
- **Your data carries over unchanged.** It uses the same ledger and settings in `%LOCALAPPDATA%\LootLedger`: matches, corrections, notes, tags, goals and your dashboard layout. The first time it starts, it saves a backup to `backups\before-lootledger-0.8.0.sqlite`. You can still open your data with 0.7.1.
- **New replay reader.** It is built into the app and gave exactly the same results as the old one on every chest of 100 real replays.
- **New look.** A slim title bar without the app name: drag it, double-click it to maximize, and hover the maximize button for Windows snap layouts. The navigation rail has no logo, and Settings sits at the bottom.
- **Everything from 0.7.1:**
  - the live match card and the pop-out counter
  - the customizable dashboard with all its cards
  - Matches, Openings, Teammates and Statistics
  - accent colours, themes, corners, density and text size
  - goals, trophies, sessions and compare
  - notes, tags and favourites, corrections and exports
  - Ctrl+K, global shortcuts and the summary image
- **New setting:** show the page title in the title bar (off by default).

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`.

## Not yet verified

A real live match from start to finish, the pop-out counter over Fortnite, global shortcuts, dragging dashboard cards, Windows Snap on several monitors and display scaling above 100%. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
