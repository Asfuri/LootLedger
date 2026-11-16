Download **LootLedger.exe** and run it. No install needed. If you have 0.8.1 or later, LootLedger updates itself: it installs this version the next time you close it.

## What's new in 0.8.6

- **Session overview.** The "Current match" card on the Overview page is now a live view of the session you are playing. It shows:
  - the chests you have opened this session, with a pop-up of the new match's chests after each match
  - how long the session has lasted, how much of it was in matches, chests per match and per hour
  - your best match so far, the chest types, your best placement, wins and eliminations
  - your top teammates by chests, and a small chart of chests per match
- **What counts as a session.** A run of matches less than 30 minutes apart, the same rule as the Sessions card. When you are not playing, the card shows your last session and when it ended. The dot and text at the top still say what the game is doing right now (waiting, live, reading the replay, match counted).
- The match timeline that the old card drew is gone. The match detail on the Matches page still has it.

## About counting chests during a match

While Fortnite records, the replay is encrypted and its key is only written when the match ends. Epic does this so replay files can't be used as a wallhack. The file holds no chest events, and the game's log doesn't record chest openings. So LootLedger counts from the finished replay, a few seconds after the match ends, and the session total grows then. It never reads the game's memory.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`. The update check and download are LootLedger's only internet traffic; none of your data is sent.

## Not yet verified

The session card was checked on your real ledger in a screenshot, in the dark and light theme, but not yet during a live match. Also not yet verified: the match pop-up and the pop-out counter over Fortnite, global shortcuts, dragging dashboard cards, Windows Snap on several monitors and display scaling above 100%. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
