Download **LootLedger.exe** and run it. No install needed.

## What's new in 0.6

- **Teammates page** (Ctrl+3): everyone who played with you, merged across matches. For each person: matches together, chests, chests per match, searched and broken-open chests, rare, relic and buried chests, and their best match. You are in the list too.
- **Records:** most chests, best single match by a teammate, and who you have played with most.
- **Filters and profiles:** filter by mode, date range and minimum matches. Select a person for their chests per match, chest types and the matches you shared. Export the table as CSV or JSON.
- **Match details:** a squad table with each player's chests, searched and broken-open counts, share of the squad, chest types, and the MVP.
- **Searched vs broken open:** teammates' broken-open chests now show next to yours. Ammo boxes are shown for you and your teammates. They are still not counted as chests.
- **Teammates stay one person** when they change their display name. They are matched by their Epic account id, which is stored hashed.
- **Fixed:** "Last 7 days" on the Matches page covered 8 days.

Everything from 0.5 is still here, and your existing ledger opens unchanged.

## Upgrading

The first time LootLedger reads your replays after this update, it reads older matches again to add their teammate details. This is automatic. It only works while Fortnite still keeps those replay files (about 100). Your totals and corrections do not change.

Some chests can't be credited to anyone. The replay doesn't say who opened them, because they were already open when your game first showed them. They count in your match totals, so teammate counts are a lower bound.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`.

## Not yet verified

Teammate counts during a live match, drag-and-drop reordering, the global shortcuts, and the Teammates page at other window sizes on a real display. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
