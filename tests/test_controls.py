import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from lootledger import theme
from lootledger.controls import Segmented, Stepper, Tip, install, show_tip
from lootledger.prefs import Prefs
from lootledger.widgets import Heatmap, SeriesChart

app = QApplication.instance() or QApplication([])
install(app)
theme.build(Prefs(), dark=True, motion=False)


def host(widget, size=(600, 300)):
    window = QMainWindow()
    window.setCentralWidget(widget)
    window.resize(*size)
    window.show()
    app.processEvents()
    return window


def key(widget, code):
    QApplication.sendEvent(widget, QKeyEvent(QKeyEvent.Type.KeyPress, code, Qt.KeyboardModifier.NoModifier))


def test_the_tooltip_always_has_text_and_stays_inside_the_window():
    window = host(QWidget(), (500, 300))
    owner = window.centralWidget()
    show_tip(owner, QRect(490, 2, 8, 8), [])  # top-right corner, no text given
    tip = Tip.instance()
    assert tip.isVisible() and tip.lines == ["No data"]
    frame = QRect(window.mapToGlobal(QPoint(0, 0)), window.size())
    assert frame.contains(tip.geometry().topLeft()) and tip.geometry().right() <= frame.right() + 1
    assert not tip.geometry().intersects(QRect(owner.mapToGlobal(QPoint(490, 2)), QRect(0, 0, 8, 8).size()))
    window.close()


def test_heatmap_cells_read_out_on_hover_and_with_arrow_keys():
    heat = Heatmap()
    grid = [[0] * 24 for _ in range(7)]
    grid[1][21] = 14
    matches = [[0] * 24 for _ in range(7)]
    matches[1][21] = 3
    heat.set_grid(grid, str, matches)
    window = host(heat)
    heat.hover = (1, 20)
    heat.setFocus()
    key(heat, Qt.Key.Key_Right)
    assert heat.hover == (1, 21) and Tip.instance().lines == ["Tuesday, 21:00", "14 chests · 3 matches"]
    key(heat, Qt.Key.Key_Up)
    assert Tip.instance().lines == ["Monday, 21:00", "No matches"]  # never an empty box
    assert "Monday, 21:00" in heat.accessibleDescription()
    window.close()


def test_chart_points_read_out_with_keys_including_matches_and_change():
    chart = SeriesChart("nothing")
    chart.set_data([("01/11", 4), ("02/11", 9)], "line", str, [["1 match"], ["2 matches", "+5 vs the previous day"]])
    window = host(chart)
    chart.setFocus()
    app.processEvents()
    assert chart.hover == 1 and Tip.instance().lines == ["02/11", "9 chests", "2 matches", "+5 vs the previous day"]
    key(chart, Qt.Key.Key_Left)
    assert chart.hover == 0 and Tip.instance().lines[:2] == ["01/11", "4 chests"]
    chart.clearFocus()
    app.processEvents()
    assert not Tip.instance().isVisible()
    window.close()


def test_stepper_clamps_accepts_typing_and_shows_its_special_text():
    stepper = Stepper(0, 100, 10, step=5, special="No goal", presets=(("No goal", 0), ("50", 50)))
    seen = []
    stepper.valueChanged.connect(seen.append)
    stepper.minus.click()
    stepper.minus.click()
    stepper.minus.click()
    assert stepper.value() == 0 and stepper.edit.text() == "No goal" and not stepper.minus.isEnabled()
    stepper.edit.setText("250")
    stepper.edit.editingFinished.emit()
    assert stepper.value() == 100 and seen == [5, 0, 100]


def test_segmented_moves_with_arrow_keys_and_collapses_when_narrow():
    seg = Segmented((("7", "7d"), ("30", "30d"), ("0", "All")), "30", "Range")
    picked = []
    seg.changed.connect(picked.append)
    window = host(seg, (400, 60))
    seg.setFocus()
    key(seg, Qt.Key.Key_Right)
    key(seg, Qt.Key.Key_Right)  # already last: stays
    assert picked == ["0"] and seg.accessibleDescription() == "All"
    seg.resize(seg.minimumSizeHint().width(), seg.height())
    assert seg.collapsed()
    window.close()


def test_tables_use_the_rounded_row_highlight():
    from lootledger.controls import RowDelegate
    from lootledger.widgets import make_table
    assert isinstance(make_table().itemDelegate(), RowDelegate)


def test_visual_qa_script_renders_every_page(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import visual_qa
    assert visual_qa.main([str(tmp_path), "--quick"]) == 0
    names = {p.name for p in tmp_path.glob("*.png")}
    assert {f"pages-dark-1240x860-{page}.png" for page in visual_qa.PAGES} <= names
    assert any(n.startswith("tip-") for n in names) and (tmp_path / "checklist.md").exists()
