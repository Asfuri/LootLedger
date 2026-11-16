Download **LootLedger.exe** and run it. No install needed. If you have 0.8.1 or later, LootLedger updates itself: it installs this version the next time you close it.

## What's new in 0.8.7

- **A simpler Session overview card.** The card added in 0.8.6 had too many lines. It now shows:
  - the chests you opened this session, with the "+N" pop-up after each match;
  - four numbers in one row: matches, time in the session, chests per match and chests per hour;
  - your best match of the session, and a small chart of chests per match.
- Chest types, placements, eliminations and teammates are no longer on the card. They are on the Statistics, Matches and Teammates pages.
- A session is still a run of matches less than 30 minutes apart. When you are not playing, the card shows your last session and when it ended.
- The README is updated with new pictures of the card.

## About counting chests during a match

While Fortnite records, the replay is encrypted and its key is only written when the match ends. Epic does this so replay files can't be used as a wallhack. The file holds no chest events, and the game's log doesn't record chest openings. So LootLedger counts from the finished replay, a few seconds after the match ends, and the session total grows then. It never reads the game's memory.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`. The update check and download are LootLedger's only internet traffic; none of your data is sent.

## Not yet verified

The session card was checked in screenshots with a real and a made-up ledger, in the dark and light theme, but not yet during a live match. Also not yet verified: the match pop-up and the pop-out counter over Fortnite, global shortcuts, dragging dashboard cards, Windows Snap on several monitors and display scaling above 100%. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
