Download **LootLedger.exe** and run it. No install needed. If you have 0.8.1 or later, LootLedger updates itself: it installs this version the next time you close it.

## What's new in 0.8.5

- **Fixed replays getting stuck.** Some replays contain a malformed piece of network data. After it, the reader jumped back to the start of the same section and read it again forever. It used up a CPU core for hours and counted no new matches, because every later replay waited behind it. The reader now notices when it stops moving forward and carries on with the rest of the file. The replay that triggered this now reads in under a second, and the other 99 replays it was checked against give exactly the same results as before.
- **A safety net.** If a replay ever hangs in some other way, it is given up on after 90 seconds and recorded as unreadable, so it can't block the rest.

If LootLedger shows "Reading replays…" for a long time, close it and open this version. The new matches are then read within a few seconds.

## About counting chests during a match

While Fortnite records, the replay is encrypted and its key is only written when the match ends. Epic does this so replay files can't be used as a wallhack. The file holds no chest events, and the game's log doesn't record chest openings. So LootLedger counts from the finished replay, a few seconds after the match ends. It never reads the game's memory.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`. The update check and download are LootLedger's only internet traffic; none of your data is sent.

## Not yet verified

The speed-ups from 0.8.4 were measured while a match was running, so the numbers are noisy. They still need timing with Fortnite closed. Also not yet verified: the match pop-up and the pop-out counter over Fortnite, global shortcuts, dragging dashboard cards, Windows Snap on several monitors and display scaling above 100%. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
