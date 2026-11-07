"""Visual QA: screenshots of every page, size, theme and shape setting, plus tooltips, menus and dialogs.

    python scripts/visual_qa.py OUT [--quick]

Uses example data in a temporary folder (your ledger and replays are never touched) and real Windows fonts,
without showing anything on screen. Writes PNGs to OUT and a checklist.md next to them: open the images
and tick each item. --quick renders one size per theme.
"""
import copy
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QScrollArea  # noqa: E402

from lootledger.app import MainWindow  # noqa: E402
from lootledger.config import Config  # noqa: E402
from lootledger.controls import Tip  # noqa: E402
from lootledger.prefs import Prefs  # noqa: E402
from test_teammates import sample, with_ids  # noqa: E402

PAGES = ("overview", "matches", "teammates", "openings", "statistics", "settings")
CHECKLIST = """# Visual QA checklist

For every image: no clipped or overlapping text, no horizontal scrollbars, no square corners poking out of
rounded cards/tables/charts, controls on one row share a height, nothing light left over in dark mode.

- [ ] pages-*: all six pages at each size and theme
- [ ] shapes-*: sharp / default / round corners, compact and XL text
- [ ] tip-*: tooltips show text, follow the theme, sit beside the hovered thing and stay inside the window
- [ ] full-*: whole pages incl. below the fold (cards, charts, heatmap legend, steppers, sliders)
- [ ] menu-* and dialog-*: rounded menus and dialogs, highlighted choice, readable
"""


def window(app, theme_name, size, density="comfortable", font="M", corners="default"):
    folder = Path(tempfile.mkdtemp(prefix="lootledger-qa-"))
    Config(hotkey_add="", hotkey_undo="", replay_folder=str(folder / "replays")).save(folder / "config.json")
    Prefs(motion="off", theme=theme_name, density=density, font_scale=font, corners=corners, hotkey_overlay="",
          goal_daily=50, goal_weekly=200).save(folder / "ui-settings.json")
    win = MainWindow(folder, scan_on_start=False)
    win.resize(*size)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    Tip.instance().setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    win.show()
    base = with_ids(sample())
    for index in range(6):  # matches spread over two weeks, so charts and the heatmap have content
        result = copy.deepcopy(base)
        result["sessionId"] = f"s{index}"
        result["timestamp"] = (datetime.now() - timedelta(days=index * 2, hours=index * 3)).isoformat()
        result["events"] = result["events"][: 141 - index * 18]
        win.store.import_replay(result, f"m{index}.replay", 10, 1.0 + index)
    win.refresh()
    app.processEvents()
    return win


def shot(app, win, path, with_tip=False):
    app.processEvents()
    image = win.grab().toImage()
    tip = Tip.instance()
    if with_tip and tip.isVisible():  # the tooltip is its own window: draw it where it would appear
        painter = QPainter(image)
        painter.drawImage(tip.geometry().topLeft() - win.mapToGlobal(QPoint(0, 0)), tip.grab().toImage())
        painter.end()
    image.save(str(path))


def hover(widget, point):
    event = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(point), QPointF(widget.mapToGlobal(point)),
                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def card(win, key):
    return next(c for c in win.stats_grid.cards if c.key == key)


def main(argv):
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    quick = "--quick" in argv
    app = QApplication.instance() or QApplication([])
    sizes = [(1240, 860)] if quick else [(900, 600), (1240, 860), (2560, 1080)]
    for theme_name in ("dark", "light"):
        for size in sizes:
            win = window(app, theme_name, size)
            for index, name in enumerate(PAGES):
                win.navigate(index)
                if name == "matches":
                    win.select_match(win.store.snapshot()["match_rows"][0]["id"])
                shot(app, win, out / f"pages-{theme_name}-{size[0]}x{size[1]}-{name}.png")
            win.close()
        win = window(app, theme_name, (1240, 860))
        win.navigate(4)
        area = win.pages.currentWidget().findChild(QScrollArea)
        for key, points in (("heat", ("middle", "edge")), ("trend", ("last",)), ("types", ("donut",))):
            target = card(win, key)
            area.verticalScrollBar().setValue(target.mapTo(area.widget(), QPoint(0, 0)).y() - 40)
            app.processEvents()
            for where in points:
                if key == "heat":
                    w = target.heat
                    point = QPoint(w.width() // 2, w.height() // 3) if where == "middle" else QPoint(w.width() - 6, 28)
                elif key == "trend":
                    w = target.chart
                    point = QPoint(w.width() - 14, w.height() // 2)
                else:
                    w = target.donut
                    point = QPoint(w.width() // 2, 10)
                hover(w, point)
                shot(app, win, out / f"tip-{theme_name}-{key}-{where}.png", with_tip=True)
                Tip.instance().hide()
        for index, name in ((0, "overview"), (4, "statistics"), (5, "settings")):
            win.navigate(index)
            app.processEvents()
            win.pages.currentWidget().findChild(QScrollArea).widget().grab().save(str(out / f"full-{theme_name}-{name}.png"))
        win.navigate(1)
        combo = win.match_range
        combo.view().window().setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        combo.showPopup()
        app.processEvents()
        combo.view().window().grab().save(str(out / f"menu-{theme_name}-select.png"))
        combo.hidePopup()
        menu = QMenu(win)
        menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        for text in ("No goal", "10", "25", "50", "Custom…"):
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(text == "25")
        menu.popup(QPoint(0, 0))
        app.processEvents()
        menu.grab().save(str(out / f"menu-{theme_name}-presets.png"))
        menu.close()
        for name, dialog in (("palette", win.open_palette()), ("shortcuts", win.show_shortcuts())):
            app.processEvents()
            dialog.grab().save(str(out / f"dialog-{theme_name}-{name}.png"))
            dialog.close()
        win.close()
        for corners, density, font in (("sharp", "compact", "S"), ("round", "comfortable", "XL")):
            win = window(app, theme_name, (1240, 860), density, font, corners)
            win.navigate(4)
            shot(app, win, out / f"shapes-{theme_name}-{corners}-{density}-{font}.png")
            win.close()
    (out / "checklist.md").write_text(CHECKLIST, encoding="utf-8")
    print(f"wrote {len(list(out.glob('*.png')))} screenshots and checklist.md to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
