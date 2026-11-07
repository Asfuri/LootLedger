import json
import time
import os
from pathlib import Path
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from lootledger import replay_reader, theme
from lootledger.app import MainWindow, source_row
from lootledger.config import Config
from lootledger.prefs import DEFAULT_LAYOUT, Prefs
from lootledger.store import EVENT_FIELDS, Store

FIXTURE = Path(__file__).parent / "fixtures" / "replay-squad.json"


def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    Config(hotkey_add="", hotkey_undo="", replay_folder=str(tmp_path / "replays")).save(tmp_path / "config.json")
    Prefs(motion="off").save(tmp_path / "ui-settings.json")
    win = MainWindow(tmp_path, scan_on_start=False)
    win.show()
    app.processEvents()
    yield win
    win.close()


def card(grid, key):
    return next(item for item in grid.cards if item.key == key)


def tile(window, stat):
    return card(window.stats_grid, f"stat:{stat}")


def test_overview_and_statistics_report_the_replay_totals(window):
    window.store.import_replay(sample(), "a.replay", 10, 1.0)
    window.refresh()
    assert tile(window, "all").value.text() == "36"
    assert tile(window, "last").value.text() == "36"
    assert "Build Squad" in tile(window, "last").detail.text()
    assert tile(window, "matches").value.text() == "1"
    assert window.sub_overview.text().endswith("1 matches read")
    types = window.store.snapshot()["types"]
    assert types["Chest"] == 31 and window.store.snapshot()["team_total"] == 17


def test_live_match_feeds_the_current_card_and_the_pop_out_counter(window):
    live_card = card(window.overview_grid, "live")
    window.tracker.state, window.tracker.started = "live", time.time() - 75
    window.tracker.facts = {"live": True, "locked": True, "recorded": 60.0, "chunks": 4}
    window.on_scan_finished({"file": "x.replay", "live": True, "locked": True, "events": []}, None)
    assert live_card.count.text() == "…" and "encrypts" in live_card.line.text()  # no invented numbers
    assert live_card.state.text().startswith("Live · 1:1")
    assert "counted when it ends" in window.status.text()
    assert window.overlay_count.text() == "…"
    live = sample()  # if Fortnite ever leaves the replay readable while recording, the count shows live
    live["events"] = live["events"][:40]
    expected = len(replay_reader.summarize(live)[0])
    window.tracker.facts = {"live": True, "locked": False, "recorded": 60.0, "chunks": 4}
    window.on_scan_finished(live, None)
    assert window.live_info["count"] == expected
    assert live_card.count.text() == f"{expected}"
    assert window.overlay_count.text() == f"{expected}"
    window.tracker.state = "idle"
    window.on_scan_finished(None, "Replay reader failed: test")
    assert live_card.count.text() == "–"
    assert "Replay reader failed" in window.status.text()


def test_finished_live_match_is_handed_to_the_import_and_shown_once(window, tmp_path):
    folder = Path(window.config.replay_folder)
    folder.mkdir()
    (folder / "a.replay").write_bytes(b"x")
    window.tracker.state, window.tracker.file = "saving", folder / "a.replay"
    window.store.import_replay(sample(), "a.replay", 10, 1.0)  # what the scan does with the finished replay
    window.on_scan_finished(None, None)
    live_card = card(window.overview_grid, "live")
    assert window.tracker.state == "ended" and live_card.count.text() == "36"
    assert "+36" == live_card.pop.text() and "Teammates:" in live_card.detail.text()
    assert window.store.snapshot()["all"] == 36  # the live view never writes to the ledger


def test_corrections_undo_and_the_broken_open_switch(window):
    window.store.import_replay(sample(), "a.replay", 10, 1.0)
    window.refresh()
    window.entry_status.setCurrentIndex(window.entry_status.findData(""))  # keep removed openings visible
    window.manual_add()
    assert window.store.snapshot()["all"] == 37
    window.undo()
    assert window.store.snapshot()["all"] == 36
    window.select_entry(next(e["id"] for e in window.store.snapshot()["entries"] if e["source"] == "replay"))
    window.change_status("undone")
    assert window.store.snapshot()["all"] == 35
    window.change_status("confirmed")
    window.broken_switch.setChecked(False)
    assert window.store.snapshot()["all"] == 27
    assert Config.read(window.config_path).count_broken is False


def test_missing_replay_folder_is_explained(window):
    window.scan()
    assert "Record Replays" in window.status.text()
    assert window.store.snapshot()["all"] == 0


def test_customize_add_remove_resize_reorder_and_reset(window):
    window.remove_widget("types")
    assert "types" not in {item["id"] for item in window.prefs.layout}
    window.add_widget("types")
    assert "types" in {item["id"] for item in window.prefs.layout}
    window.resize_widget("trend", 1)
    assert next(item for item in window.prefs.layout if item["id"] == "trend")["span"] == 1
    order = [item["id"] for item in window.prefs.layout]
    order.remove("live")
    order.append("live")
    window.on_reorder(order)
    assert [item.key for item in window.overview_grid.cards] == order
    window.reset_layout()
    assert [item["id"] for item in window.prefs.layout] == list(DEFAULT_LAYOUT)
    assert Prefs.read(window.prefs_path).layout == window.prefs.layout  # saved to the settings file


def test_matches_filters_and_the_detail_pane(window):
    window.store.import_replay(sample(), "a.replay", 10, 1.0)
    window.refresh()
    assert window.match_proxy.rowCount() == 1
    window.match_min.setValue(40)
    assert window.match_proxy.rowCount() == 0
    window.match_min.setValue(0)
    window.match_type.setCurrentIndex(window.match_type.findData("Rare chest"))
    assert window.match_proxy.rowCount() == 1
    window.match_type.setCurrentIndex(window.match_type.findData("Relic chest"))
    window.match_min.setValue(2)  # the match has one relic chest
    assert window.match_proxy.rowCount() == 0
    window.match_min.setValue(0)
    window.match_type.setCurrentIndex(0)
    window.match_search.setText("squad")
    assert window.match_proxy.rowCount() == 1
    window.match_search.setText("no such mode")
    assert window.match_proxy.rowCount() == 0
    window.match_search.clear()
    window.select_match(window.store.snapshot()["match_rows"][0]["id"])
    assert not window.detail.isHidden()


def test_openings_export_writes_only_the_rows_shown(window, tmp_path):
    window.store.import_replay(sample(), "a.replay", 10, 1.0)
    window.refresh()
    window.entry_status.setCurrentIndex(window.entry_status.findData("confirmed"))
    rows = window.visible_entries()
    target = tmp_path / "openings.csv"
    Store.export_rows(target, [{field: row[field] for field in EVENT_FIELDS} for row in rows])
    lines = target.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == len(rows) + 1
    assert lines[0].split(",") == list(EVENT_FIELDS)
    assert all(row["status"] == "confirmed" for row in rows)


def test_settings_apply_immediately_and_persist(window):
    window.set_pref("theme", "dark")
    assert theme.CURRENT.dark is True
    window.set_pref("seed", "#5b9cf0")
    assert theme.CURRENT.c["primary"] in window.styleSheet()
    assert theme.CURRENT.c["primary"] in window.overlay.styleSheet()
    assert Prefs.read(window.prefs_path).theme == "dark"
    window.set_pref("chart_style", "area")
    assert Prefs.read(window.prefs_path).chart_style == "area"


def test_settings_export_and_import_round_trip(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    target = tmp_path / "settings.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    window.set_pref("density", "compact")
    window.set_pref("date_format", "iso")
    window.export_settings()
    assert json.loads(target.read_text(encoding="utf-8"))["app"] == "LootLedger"
    window.set_pref("density", "comfortable")
    window.set_pref("date_format", "dmy")
    window.import_settings()
    assert window.prefs.density == "compact" and window.prefs.date_format == "iso"
    assert Prefs.read(window.prefs_path).date_format == "iso"


def test_import_rejects_files_that_are_not_settings(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    other = tmp_path / "other.json"
    other.write_text('{"hello": 1}', encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(other), ""))
    with pytest.raises(ValueError):
        window.import_settings()


def test_clear_data_backs_up_first_and_keeps_replays_unread(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    window.store.import_replay(sample(), "a.replay", 10, 1.0)
    window.refresh()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.clear_data()
    backups = list((window.folder / "backups").glob("before-clear-*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("SELECT sum(amount) FROM events").fetchone()[0] == 36  # the backup kept everything
    assert window.store.snapshot()["all"] == 0
    assert "a.replay" in window.store.replay_files()


def test_every_page_renders(window):
    for index in range(6):
        window.navigate(index)
        QApplication.instance().processEvents()
        assert window.pages.currentIndex() == index
        assert not window.grab().isNull()


def test_the_dashboard_grid_reflows_with_width(window):
    grid = window.overview_grid
    grid.resize(260, 400)
    grid.reflow(force=True)
    narrow_cols = grid._columns
    grid.resize(1100, 400)
    grid.reflow(force=True)
    assert narrow_cols == 1 and grid._columns >= 3
    live = card(grid, "live")
    assert grid.grid.getItemPosition(grid.grid.indexOf(live))[3] == min(live.span, grid._columns)


def test_source_row_ignores_stale_indexes(window):
    window.store.import_replay(sample(), "a.replay", 10, 1.0)
    window.refresh()
    stale = window.match_proxy.index(999, 0)
    assert source_row(window.match_proxy, window.match_model, stale) is None
