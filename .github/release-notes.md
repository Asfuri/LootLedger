Download **LootLedger.exe** and run it. No install needed. If you have 0.8.0, download this one once: from now on LootLedger updates itself.

## What's new in 0.8.1

- **Match stats.** For each match: damage to players, damage taken, eliminations, assists, accuracy, revives, damage to structures, materials gathered and used, and distance travelled. They are in a match's details on Matches, and in the new **Match stats** card (on Statistics; add it to Overview with Customize). Matches you already have get their stats when LootLedger reads their replay again, which happens once by itself; matches whose replay Fortnite has already deleted have none.
- **Weekly recap image.** Your week in one shareable picture: chests, matches, best match, change from last week and top teammate. On Overview, use the share button, or Ctrl+K → "weekly recap". Saved or copied, never uploaded.
- **Automatic updates.** LootLedger checks this project's GitHub releases, downloads a newer version, verifies it against GitHub's published SHA-256 checksum and installs it when you close the app (or right away with Restart now). It never restarts during a game. Turn it off in Settings → About.
- **Fixed:** the navigation rail and other controls needed two clicks; the What's new text could run outside its box.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`. The update check and download are LootLedger's only internet traffic; none of your data is sent.

## Not yet verified

A real update from one release to the next (this is the first release with the updater), a live match from start to finish, the pop-out counter over Fortnite, global shortcuts, dragging dashboard cards, Windows Snap on several monitors and display scaling above 100%. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
