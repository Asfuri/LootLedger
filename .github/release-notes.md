Download **LootLedger.exe** and run it. No install needed. If you have 0.8.1 or later, LootLedger updates itself: it installs this version the next time you close it.

## What's new in 0.8.8

- **A new Sessions tab**, between Matches and Openings. It lists every play session, newest first. A session is a run of matches less than 30 minutes apart, the same rule as the Session overview card.
  - **Summary:** your average session, your longest session and the session with the most chests.
  - **The list:** start time, length, matches, chests, chests per match and per hour, best match and best placement. Click a column to sort it, and pick a date range (7 days, 30 days, 90 days or all time).
  - **Details:** select a session to see its chest types, a chart of chests per match, its best placement, wins and eliminations, your top teammates, and every match in it. Double-click a match to open it on the Matches page.
- **Shortcuts:** the pages after Matches moved down by one, so Ctrl+1 to Ctrl+7 now go to Overview, Matches, Sessions, Openings, Statistics, Teammates and Settings.
- The README has a new picture of the Sessions page.

## About counting chests during a match

While Fortnite records, the replay is encrypted and its key is only written when the match ends. Epic does this so replay files can't be used as a wallhack. The file holds no chest events, and the game's log doesn't record chest openings. So LootLedger counts from the finished replay, a few seconds after the match ends, and the session total grows then. It never reads the game's memory.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`. The update check and download are LootLedger's only internet traffic; none of your data is sent.

## Not yet verified

The Sessions page was checked in screenshots from a made-up ledger, in the dark and light theme. The Session overview card has not yet been seen during a live match. Also not yet verified: the match pop-up and the pop-out counter over Fortnite, global shortcuts, dragging dashboard cards, Windows Snap on several monitors and display scaling above 100%. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
