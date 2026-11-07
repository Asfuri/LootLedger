Download **LootLedger.exe** and run it. No install needed.

## What's new in 0.7

- **Live match card:** Idle, Waiting for a match, Live (with the match clock and how much of the replay Fortnite has saved), Saving and Match counted. Fortnite encrypts the replay until the match ends, so the chests arrive a few seconds after the match, with a count-up and a "+N" in the colour of your rarest chest. LootLedger only reads files on disk and never touches the Fortnite process.
- **Pop-out counter:** an always-on-top LootLedger window you can drag, resize, fade and make click-through, with its own shortcut (Ctrl+Alt+F10). Optional sound when a match is counted.
- **New cards:** setup and replay health, sessions, daily and weekly goals, trophies, and compare any two periods.
- **Matches:** notes, tags and favourites. **Ctrl+K** jumps anywhere; **?** lists every shortcut and shows if one is taken by another app.
- **Share** a summary image (saved or copied, never uploaded). Chest types keep one colour everywhere, with a colourblind-safe option.
- **Motion:** shared-axis page transitions, charts that draw in, sliding snackbars and a theme cross-fade, with Full, Reduced and Off levels.
- **Fixes:** a crash when painting the goals card, tables and filter bars in small windows, the match detail squeezing the table, clipped and ghost text, shortcut conflicts, and the window and counter remembering where they were.

Your ledger is backed up automatically to `backups\` before it is upgraded.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`.

## Not yet verified

A real live match, the pop-out counter over Fortnite, mouse drag-and-drop and global shortcuts on a real display. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
