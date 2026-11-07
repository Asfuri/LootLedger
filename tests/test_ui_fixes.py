import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QDialog

from lootledger import hotkeys
from lootledger.app import MainWindow
from lootledger.config import Config
from lootledger.prefs import Prefs
from lootledger.widgets import DRAG_PREFIX

FIXTURE = Path(__file__).parent / "fixtures" / "replay-squad.json"


def make(folder):
    QApplication.instance() or QApplication([])
    win = MainWindow(folder, scan_on_start=False)
    win.show()
    QApplication.processEvents()
    return win


@pytest.fixture
def window(tmp_path):
    Config(hotkey_add="", hotkey_undo="", replay_folder=str(tmp_path / "replays")).save(tmp_path / "config.json")
    Prefs(motion="off", hotkey_overlay="").save(tmp_path / "ui-settings.json")
    win = make(tmp_path)
    yield win
    win.close()


def test_dropping_a_card_on_another_moves_it_there(window):
    grid = window.overview_grid
    grid.resize(1100, 900)
    grid.reflow(force=True)
    QApplication.processEvents()
    order = [card.key for card in grid.cards]
    target = grid.cards[0]
    mime = QMimeData()
    mime.setText(DRAG_PREFIX + order[2])
    point = QPointF(target.geometry().center())
    event = QDropEvent(point, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    grid.dropEvent(event)
    assert [item["id"] for item in window.prefs.layout][0] == order[2]


def test_cards_move_with_the_keyboard_and_focus_follows(window):
    first = [item["id"] for item in window.prefs.layout]
    window.move_widget(first[1], -1)
    assert [item["id"] for item in window.prefs.layout][:2] == [first[1], first[0]]
    window.move_widget(first[1], -1)  # already first: stays put
    assert [item["id"] for item in window.prefs.layout][0] == first[1]


def test_shortcut_list_shows_each_global_shortcut_and_its_state(window):
    window.hotkeys_busy = ["Ctrl+Alt+F8"]
    window.config.hotkey_add = "Ctrl+Alt+F8"
    dialog = window.show_shortcuts()
    texts = [w.text() for w in dialog.findChildren(type(window.status))]
    assert "Ctrl+K" in texts and any("used by another app" in t for t in texts) and any("off" in t for t in texts)
    dialog.close()


def test_badly_written_hotkey_changes_nothing_and_a_taken_one_is_reported(monkeypatch):
    keys = hotkeys.Hotkeys(lambda action: None)
    with pytest.raises(ValueError):
        keys.configure("Ctrl+Alt+F8", "nonsense", "")
    assert keys.registered == []
    if os.name == "nt":
        monkeypatch.setattr(hotkeys.ctypes.windll.user32, "RegisterHotKey", lambda *a: 0)
        assert keys.configure("Ctrl+Alt+F8", "", "Ctrl+Alt+F10") == ["Ctrl+Alt+F8", "Ctrl+Alt+F10"]


def test_window_place_and_counter_survive_a_restart(tmp_path):
    Config(hotkey_add="", hotkey_undo="", replay_folder=str(tmp_path / "replays")).save(tmp_path / "config.json")
    Prefs(motion="off", hotkey_overlay="", overlay=True).save(tmp_path / "ui-settings.json")
    win = make(tmp_path)
    win.resize(1000, 700)
    win.close()
    saved = json.loads((tmp_path / "ui-settings.json").read_text(encoding="utf-8"))
    assert saved["window_geometry"][2:] == [1000, 700]
    assert saved["overlay"] is True  # quitting closes the counter, but that is not turning it off
    again = make(tmp_path)
    assert (again.width(), again.height()) == (1000, 700) and again.overlay.isVisible()
    again.close()


def test_tables_fit_a_small_window_without_sideways_scrolling(window):
    window.store.import_replay(json.loads(FIXTURE.read_text(encoding="utf-8")), "a.replay", 10, 1.0)
    window.resize(860, 580)
    window.refresh()
    for index, table in ((1, window.match_table), (3, window.entries), (2, window.team_panel.table)):
        window.navigate(index)
        QApplication.processEvents()
        assert table.horizontalHeader().length() <= table.viewport().width() + 2


def test_every_page_paints_without_errors(window, capfd):
    """Paint errors in Python overrides only print to stderr (and can crash a full repaint): catch them."""
    import time
    from PySide6.QtWidgets import QScrollArea
    window.store.import_replay(json.loads(FIXTURE.read_text(encoding="utf-8")), "a.replay", 10, 1.0)
    window.prefs.goal_daily, window.prefs.goal_weekly = 30, 300
    window.tracker.state, window.tracker.started = "live", time.time() - 90
    window.tracker.facts = {"live": True, "locked": True, "recorded": 60.0, "chunks": 4}
    window.refresh()
    for index in range(6):
        window.navigate(index)
        QApplication.processEvents()
        area = window.pages.currentWidget().findChild(QScrollArea)
        (area.widget() if area else window).grab()
    window.overlay.grab()
    assert "Error calling Python override" not in capfd.readouterr().err
