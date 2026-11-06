import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from lootledger.app import MainWindow
from lootledger.config import Config

FIXTURE = Path(__file__).parent / "fixtures" / "replay-squad.json"


def window_with_match(tmp_path, **config):
    QApplication.instance() or QApplication([])
    Config(hotkey_add="", hotkey_undo="", replay_folder=str(tmp_path), **config).save(tmp_path / "config.json")
    window = MainWindow(tmp_path, scan_on_start=False)
    window.store.import_replay(json.loads(FIXTURE.read_text(encoding="utf-8")), "a.replay", 1, 1.0)
    window.refresh()
    return window


def test_overview_shows_replay_totals_types_and_team(tmp_path):
    window = window_with_match(tmp_path)
    try:
        assert window.heading.text() == "Chest tracker · Player"
        assert window.counters["all"].text() == "36"
        assert window.counters["last"].text() == "36"
        assert window.counters["matches"].text() == "1"
        assert window.counters["current"].text() == "–"
        types = {window.type_table.item(r, 0).text(): window.type_table.item(r, 1).text()
                 for r in range(window.type_table.rowCount())}
        assert types["Chest"] == "31" and types["Total chests"] == "36"
        assert types["Ammo box (not counted as a chest)"] == "1"
        assert types["      of which broken open (not searched)"] == "9"
        assert window.match_table.rowCount() == 1
        assert window.match_table.item(0, 2).text().startswith("#3")
        assert "Last match: 36 chests" in window.overlay_lines.text()
    finally:
        window.close()


def test_live_replay_feeds_current_match_and_overlay(tmp_path):
    window = window_with_match(tmp_path)
    try:
        live = json.loads(FIXTURE.read_text(encoding="utf-8"))
        live["events"] = live["events"][:40]
        window.on_scan_finished(live, None)
        expected = sum(1 for e in live["events"] if e["by"] == "me" and "Ammo" not in e["cls"])
        assert window.counters["current"].text() == str(expected)
        assert window.overlay_count.text() == str(expected)
        assert "Match in progress" in window.status.text()
        window.on_scan_finished(None, "Replay reader failed: test")
        assert window.counters["current"].text() == "–"
        assert "Replay reader failed" in window.status.text()
    finally:
        window.close()


def test_corrections_and_broken_toggle(tmp_path):
    window = window_with_match(tmp_path)
    try:
        window.manual_add()
        assert window.counters["all"].text() == "37"
        window.undo()
        assert window.counters["all"].text() == "36"
        window.entries.selectRow(next(i for i, row in enumerate(window.entry_rows) if row["source"] == "replay"))
        window.change_status("undone")
        assert window.counters["all"].text() == "35"
        window.change_status("confirmed")
        window.broken_box.setChecked(False)
        window.save_settings()
        assert window.counters["all"].text() == "27"
        assert Config.read(tmp_path / "config.json").count_broken is False
    finally:
        window.close()
    reopened = MainWindow(tmp_path, scan_on_start=False)
    try:
        assert reopened.counters["all"].text() == "27"
    finally:
        reopened.close()


def test_missing_replay_folder_is_explained(tmp_path):
    QApplication.instance() or QApplication([])
    Config(hotkey_add="", hotkey_undo="", replay_folder=str(tmp_path / "missing")).save(tmp_path / "config.json")
    window = MainWindow(tmp_path, scan_on_start=False)
    try:
        window.scan()
        assert "Record Replays" in window.status.text()
        assert window.counters["all"].text() == "0"
    finally:
        window.close()
