import copy
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from lootledger import __version__, features
from lootledger.app import MainWindow
from lootledger.config import Config
from lootledger.prefs import Prefs
from lootledger.store import SCHEMA_V1, SCHEMA_V2, Store

FIXTURE = Path(__file__).parent / "fixtures" / "replay-squad.json"


def sample(session="s0", start=None):
    result = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result["sessionId"] = session
    if start:
        result["timestamp"] = start.isoformat()
    return result


def ledger(tmp_path, starts):
    store = Store(tmp_path / "ledger.sqlite")
    for index, start in enumerate(starts):
        store.import_replay(sample(f"s{index}", start), f"m{index}.replay", 10, 1.0 + index)
    return store


def test_sessions_split_on_a_30_minute_gap(tmp_path):
    base = datetime(2026, 11, 5, 18, 0)
    # three matches back to back (each ~16 min, 20 min apart), then one the next day
    store = ledger(tmp_path, [base, base + timedelta(minutes=20), base + timedelta(minutes=40), base + timedelta(days=1)])
    found = features.sessions(store.snapshot()["match_rows"])
    assert [s["matches"] for s in found] == [1, 3]
    assert found[1]["chests"] == 3 * 36 and found[1]["per_hour"] > 0
    store.close()


def test_goals_trophies_and_period_compare(tmp_path):
    today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    store = ledger(tmp_path, [today, today - timedelta(days=8)])
    snap = store.snapshot()
    g = features.goals(snap, 30, 1000)
    assert [x["reached"] for x in g["goals"]] == [True, False] and g["goals"][0]["share"] == 1.0
    assert features.goals(snap, 0, 0)["goals"] == []
    unlocked = {a["id"] for a in features.achievements(snap) if a["unlocked"]}
    assert {"first-relic", "match-25"} <= unlocked and "chests-100" not in unlocked
    rows = dict((name, (a, b, change)) for name, a, b, change in features.compare(
        snap, (today.date() - timedelta(days=8), today.date() - timedelta(days=8)), (today.date(), today.date())))
    assert rows["Chests"] == (36, 36, 0) and rows["Matches"] == (1, 1, 0)
    store.close()


def test_health_names_each_problem_and_its_fix(tmp_path):
    folder, log = tmp_path / "Demos", tmp_path / "FortniteGame.log"
    h = features.health(folder, {}, log)
    assert not h["ok"] and "Record Replays" in h["checks"][0][2]
    folder.mkdir()
    replay = folder / "a.replay"
    replay.write_bytes(b"x")
    old = time.time() - 6 * 3600
    os.utime(replay, (old, old))
    log.write_text("running")  # Fortnite ran just now, but the newest replay is six hours old
    h = features.health(folder, {"a.replay": (1, old, "skipped")}, log)
    assert [ok for _, ok, _ in h["checks"]] == [True, True, False] and h["unreadable"] == 1


def test_notes_tags_and_favourites_survive_a_re_read(tmp_path):
    store = ledger(tmp_path, [datetime(2026, 11, 5, 18, 0)])
    match_id = store.snapshot()["match_rows"][0]["id"]
    store.set_note(match_id, tags="ranked, with randoms, ranked", favorite=True)
    store.set_note(match_id, note="  great drop  ")
    store.import_replay(sample("s0", datetime(2026, 11, 5, 18, 0)), "m0.replay", 10, 1.0)  # meta is replaced
    row = store.snapshot()["match_rows"][0]
    assert (row["tags"], row["note"], row["favorite"]) == ("ranked, with randoms", "great drop", True)
    with pytest.raises(ValueError):
        store.set_note(match_id, note="x" * 3000)
    store.clear()
    assert store.notes() == {}
    store.close()


def test_upgrading_an_older_ledger_backs_it_up_first(tmp_path):
    path = tmp_path / "ledger.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA_V1 + SCHEMA_V2 + "PRAGMA user_version=2;")
        db.execute("INSERT INTO matches VALUES('m','2026-11-01T10:00:00+00:00','2026-11-01T10:10:00+00:00',600)")
    store = Store(path)
    backups = list((tmp_path / "backups").glob("before-schema-v3-*.sqlite"))
    assert len(backups) == 1 and store.db.execute("PRAGMA user_version").fetchone()[0] == 3
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2  # the untouched old ledger
    store.close()
    Store(path).close()  # already current: no second backup
    assert len(list((tmp_path / "backups").glob("*.sqlite"))) == 1


@pytest.fixture
def window(tmp_path):
    QApplication.instance() or QApplication([])
    Config(hotkey_add="", hotkey_undo="", replay_folder=str(tmp_path / "replays")).save(tmp_path / "config.json")
    Prefs(motion="off", hotkey_overlay="", goal_daily=10).save(tmp_path / "ui-settings.json")
    win = MainWindow(tmp_path, scan_on_start=False)
    win.show()
    yield win
    win.close()


def test_goal_and_trophies_are_announced_once(window):
    window.prefs.trophies = ["chests-100"]  # pretend an earlier version already announced something
    window.store.import_replay(sample("s1", datetime.now()), "a.replay", 10, 1.0)
    window.refresh()
    first = window.snackbar.text.text()
    assert "Goal reached" in first and "Trophy unlocked" in first
    window.snackbar.text.setText("")
    window.refresh()
    window._snap = None
    window.refresh()
    assert window.snackbar.text.text() == ""  # nothing repeated


def test_palette_finds_pages_matches_and_settings(window):
    window.store.import_replay(sample("s1", datetime(2026, 11, 5, 18, 0)), "a.replay", 10, 1.0)
    window.refresh()
    names = [name for name, _ in window.palette_items()]
    assert "Go to Teammates" in names and any(n.startswith("Match: Build Squad") for n in names)
    assert any(n.startswith("Teammate: ") for n in names) and "Theme: dark" in names
    dialog = window.open_palette()
    search = dialog.findChild(type(window.match_search))
    search.setText("go statistics")
    search.returnPressed.emit()
    assert window.pages.currentIndex() == 4


def test_summary_image_and_whats_new(window, tmp_path):
    window.store.import_replay(sample("s1", datetime(2026, 11, 5, 18, 0)), "a.replay", 10, 1.0)
    image = window.summary_image()
    assert (image.width(), image.height()) == (1200, 630) and not image.isNull()
    window.prefs.seen_version = "0.6.0"
    dialog = window.startup_dialog()
    assert __version__ in dialog.windowTitle() and window.prefs.seen_version == __version__
    dialog.close()
    assert window.startup_dialog() is None  # once per version
