Download **LootLedger.exe** and run it. No install needed.

## What's new in 0.7.1

- **Tooltips fixed everywhere.** They used to be empty grey boxes. Now hover (or Tab and use the arrow keys) on the chest chart, the weekday × hour heatmap and the chest-type donut to read each point, for example "Tuesday, 21:00 · 14 chests · 3 matches", or the date with its chests, matches and the change from the period before. They follow the theme and stay inside the window.
- **Rounded Material 3 controls.** Segmented buttons are pills with a sliding selection and a check mark. Goals use a stepper (− value +) with presets. Selects, date fields, sliders, menus, tables and scrollbars all follow the theme and your corner setting (sharp, default or round).
- **Charts.** Bars have rounded tops, there is a new Smooth line style, the area fill fades out, the donut has rounded segments, the heatmap has a legend and visible low values, and axis labels never overlap or get cut off.
- **Small windows.** Filter bars wrap instead of squeezing the search box.

Everything from 0.7 is still here: the live match card, the pop-out counter, sessions, goals, trophies, notes and tags, Ctrl+K and the summary image.

## First launch

1. In Fortnite: **Settings → Game → Replays → Record Replays: On**.
2. Open LootLedger and play. Finished matches are added automatically.

The exe is unsigned, so Windows SmartScreen may warn the first time (More info → Run anyway). It is built from this repository's source by GitHub Actions. Data is saved in `%LOCALAPPDATA%\LootLedger`.

## Not yet verified

Tooltips and hover with a real mouse, rounded select popups on screen, a real live match, the pop-out counter over Fortnite, and global shortcuts on a real display. See [VALIDATION.md](https://github.com/femboypuppy/LootLedger/blob/main/VALIDATION.md).
