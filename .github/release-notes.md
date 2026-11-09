Download **LootLedger.exe** and run it. No install needed. If you have 0.8.1 or later, LootLedger updates itself: it installs this version the next time you close it.

## What's new in 0.8.4

- **Faster first launch.** Replays are read on several cores at once: half your cores, at most 6, so a running game keeps room. The first import of a full replay folder is the part that used to take a minute or more.
- **Snappier page switching.** Overview and Statistics used to rebuild every card on every visit. Now they rebuild only when your statistics, the date or the theme changed. Every import and setting still updates them right away.

## About counting chests during a match

This was checked again on a real match in progress. While Fortnite records, the replay is encrypted and its key is only written when the match ends. Epic does this so replay files can't be used as a wallhack. The file holds no chest events, and the game's log doesn't record chest openings. So LootLedger keeps counting from the finished replay, a few seconds after the match ends. It never reads the game's memory.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`. The update check and download are LootLedger's only internet traffic; none of your data is sent.

## Not yet verified

The speed-ups were measured while a match was running, so the numbers are noisy. They still need timing with Fortnite closed. Also not yet verified: the match pop-up and the pop-out counter over Fortnite, global shortcuts, dragging dashboard cards, Windows Snap on several monitors and display scaling above 100%. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
