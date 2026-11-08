Download **LootLedger.exe** and run it. No install needed. If you have 0.8.1 or later, LootLedger updates itself: it installs this version the next time you close it.

## What's new in 0.8.3

- **Pop-up after each match.** When a match is counted, a small card shows in the bottom-right corner for 8 seconds: your chests, mode, placement, how the match compares with your average (or "Your best match yet") and today's total. It never takes focus from the game, and a click closes it. If your pop-out counter sits bottom-right, the pop-up uses the top-right corner. Turn it off in **Settings → Live match and counter**.
- **Smaller app: 12.9 MB instead of 16.5 MB.** The app is now built for size. Drawing, replay reading and decompression still get full-speed optimisation.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`. The update check and download are LootLedger's only internet traffic; none of your data is sent.

## Not yet verified

The pop-up over a running game. It was checked off-screen, but not yet seen after a real match. Also not yet verified: a live match from start to finish, the pop-out counter over Fortnite, global shortcuts, dragging dashboard cards, Windows Snap on several monitors and display scaling above 100%. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
