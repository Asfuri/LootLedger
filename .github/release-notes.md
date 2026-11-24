Download **LootLedger.exe** and run it. No install needed. If you have 0.8.1 or later, LootLedger updates itself: it installs this version the next time you close it.

## What's new in 0.8.9

- **Rewards.** During the Treasure Hunt event, opening a chest can roll a prize. LootLedger now reads the prizes your replays recorded and counts them by type: Gold outfit, Pickaxe, Back bling, Jam track, Loading screen, Gold car decal, Gizmo and Pirate shop. Requested in #1.
  - **Overview:** a new **Rewards** card (added to your dashboard once; remove it if you don't want it) with your total, your top three types and how many your teammates got.
  - **Statistics:** a new **Rewards by type** card with your count and your teammates' count for every type.
  - **Details:** a match lists each prize with who got it, when, and which kind of chest it came from. A session lists the prizes from all its matches, and the Session overview card shows a "rewards" number once you have one.
  - **Export:** **Settings → Ledger and settings → Export rewards** saves every recorded prize as CSV or JSON. The full ledger export also carries them.
- **First start after updating:** LootLedger reads your saved replays once more to look for prizes, so the first launch takes a minute or two. Matches whose replay Fortnite has already deleted stay without reward data.

### What the rewards numbers mean

These are **minimums**. A prize shows up only when the game recorded its animation in your replay. Prizes won by players far from you usually aren't recorded, and Gizmos may not be saved at all. A prize this version has no name for is counted apart as "not recognized", never guessed into a type.

## About counting chests during a match

While Fortnite records, the replay is encrypted and its key is only written when the match ends. Epic does this so replay files can't be used as a wallhack. The file holds no chest events, and the game's log doesn't record chest openings. So LootLedger counts from the finished replay, a few seconds after the match ends, and the session total grows then. It never reads the game's memory.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`. The update check and download are LootLedger's only internet traffic; none of your data is sent.

## Not yet verified

The Sessions page was checked in screenshots from a made-up ledger, in the dark and light theme. The Session overview card has not yet been seen during a live match. Also not yet verified: the match pop-up and the pop-out counter over Fortnite, global shortcuts, dragging dashboard cards, Windows Snap on several monitors and display scaling above 100%. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
