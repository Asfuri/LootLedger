import copy
import csv
from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

from lootledger import stats
from lootledger.app import MainWindow
from lootledger.config import Config
from lootledger.prefs import Prefs
from lootledger.replay_reader import classify, player_key, scan, summarize
from lootledger.store import Store
from lootledger.teammates import EXPORT_FIELDS, export_row

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "replay-squad.json"
IDS = {"Teammate 1": "epic-a1", "Teammate 2": "epic-b2"}  # the fixture's teammates are anonymised and have no ids


def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def with_ids(result):
    """Give the fixture the ids a real replay has: an account id on each teammate and each teammate's chest."""
    for mate in result["teammates"]:
        mate["epicId"] = IDS.get(mate["name"])
    for event in result["events"]:
        if event["by"] == "team":
            event["playerId"] = IDS[event["player"]]
    return result


def later_match(result, session, hours=1):
    """The same squad in another match, with a later start and a different session id."""
    copy_ = copy.deepcopy(result)
    copy_["sessionId"] = session
    start = datetime.fromisoformat(copy_["timestamp"]) + timedelta(hours=hours)
    copy_["timestamp"] = start.isoformat()
    return copy_


def test_players_list_you_then_each_teammate_and_totals_add_up():
    mine, meta = summarize(sample())
    players = {p["name"]: p for p in meta["players"]}
    assert meta["players"][0]["me"] and meta["players"][0]["name"] == "Player"
    assert sum(c["opened"] + c["broken"] for c in players["Player"]["counts"].values()) == len(mine) == 36
    mates = [p for p in meta["players"] if not p["me"]]
    assert sum(c["opened"] + c["broken"] for p in mates for c in p["counts"].values()) == 17
    assert sum(c["broken"] for p in mates for c in p["counts"].values()) == 5
    assert players["Teammate 3"]["counts"] == {}  # in the squad but no chest seen: still listed


def test_teammate_broken_open_and_searched_are_kept_apart_in_the_snapshot(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    store.import_replay(with_ids(sample()), "a.replay", 10, 1.0)
    snap = store.snapshot()
    assert (snap["team_opened"], snap["team_broken"], snap["team_total"]) == (12, 5, 17)
    assert sum(snap["team_types"].values()) == snap["team_total"]
    store.include_broken = False
    snap = store.snapshot()
    assert (snap["team_opened"], snap["team_broken"], snap["team_total"]) == (12, 0, 12)
    store.close()


def test_every_person_in_a_match_adds_up_and_types_match_totals(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    store.import_replay(with_ids(sample()), "a.replay", 10, 1.0)
    row = store.snapshot()["match_rows"][0]
    for person in row["squad"]:
        assert person["total"] == person["opened"] + person["broken"]
        assert sum(person["types"].values()) == person["total"]
    assert sum(p["total"] for p in row["squad"]) == row["squad_total"] == 53
    store.include_broken = False  # with broken-open chests switched off, the same rules hold
    for person in store.snapshot()["match_rows"][0]["squad"]:
        assert person["total"] == person["opened"] + person["broken"]
        assert sum(person["types"].values()) == person["total"]
    store.close()


def test_chests_nobody_was_seen_opening_are_counted_apart(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    expected = sum(1 for e in sample()["events"] if e["by"] == "unknown" and classify(e["cls"])[1])
    store.import_replay(sample(), "a.replay", 10, 1.0)
    assert store.snapshot()["unattributed"] == expected > 0
    store.close()


def test_renamed_teammate_is_one_person_across_matches(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    first = with_ids(sample())
    store.import_replay(first, "a.replay", 10, 1.0)
    second = later_match(first, "session-2")
    for event in second["events"]:
        if event.get("player") == "Teammate 1":
            event["player"] = "Renamed One"
    for mate in second["teammates"]:
        if mate["name"] == "Teammate 1":
            mate["name"] = "Renamed One"
    store.import_replay(second, "b.replay", 10, 2.0)
    board = store.snapshot()["board"]
    mate = next(p for p in board if p["key"] == player_key("epic-a1", None))
    assert (mate["matches"], mate["name"], mate["total"]) == (2, "Renamed One", 32)
    assert sum(1 for p in board if p["key"] == player_key("epic-a1", None)) == 1
    store.close()


def test_mvp_goes_to_the_top_player_and_never_on_a_tie():
    def person(key, total, opened=None, unranked=False):
        return {"key": key, "total": total, "opened": total if opened is None else opened, "unranked": unranked,
                "bot": False, "me": key == "me"}

    assert stats._mvp([person("me", 9), person("a", 4)]) == "me"
    assert stats._mvp([person("me", 5), person("a", 5)]) is None  # tie on chests and on searched
    assert stats._mvp([person("me", 5, 3), person("a", 5, 4)]) == "a"  # more searched wins the tie-break
    assert stats._mvp([person("bot", 30, unranked=True), person("a", 4)]) == "a"  # bots are never MVP
    assert stats._mvp([person("a", 0)]) is None


def test_bots_and_unnamed_players_are_listed_but_not_ranked_or_recorded(tmp_path):
    result = with_ids(sample())
    result["teammates"][1]["bot"] = True  # Teammate 2 is a bot
    for event in result["events"]:
        if event.get("player") == "Teammate 1" and event["kind"] == "broken":
            event["player"], event["playerId"] = None, None  # an unnamed player with no id
            break
    store = Store(tmp_path / "ledger.sqlite")
    store.import_replay(result, "a.replay", 10, 1.0)
    board = store.snapshot()["board"]
    unnamed = [p for p in board if p["anonymous"]]
    bot = next(p for p in board if p["bot"])
    assert unnamed and bot["name"] == "Teammate 2" and bot["unranked"]
    assert all(p["unranked"] for p in board if p["anonymous"] or p["bot"])
    records = stats.records([p for p in board])
    assert records["most_chests"]["name"] != "Teammate 2"
    assert stats.tag(bot) == " · bot" and stats.tag(unnamed[0]) == " · unnamed"
    store.close()


def test_matches_read_before_player_detail_are_read_again_without_double_counting(tmp_path, monkeypatch):
    folder = tmp_path / "Demos"
    folder.mkdir()
    replay = folder / "a.replay"
    replay.write_bytes(b"x" * 10)
    stat = replay.stat()
    store = Store(tmp_path / "ledger.sqlite")
    store.import_replay(with_ids(sample()), "a.replay", stat.st_size, stat.st_mtime)
    removed = store.entries()[0]["id"]
    store.edit(removed, status="undone")
    with store.db:  # simulate a match saved by an older version: no per-player detail
        store.db.execute("UPDATE match_meta SET meta=json_remove(meta, '$.players')")
    before = store.snapshot()
    assert before["older_matches"] == 1 and before["match_rows"][0]["squad"] is None
    assert store.files_without_players() == {"a.replay"}
    calls = []

    def analyzer(paths, helper=None):
        calls.append([Path(p).name for p in paths])
        return [with_ids(sample()) for _ in paths]

    scan(store, folder, analyzer=analyzer)
    assert calls == [["a.replay"]]  # read again even though the file did not change
    snap = store.snapshot()
    assert snap["older_matches"] == 0 and snap["match_rows"][0]["squad"] is not None
    assert snap["all"] == 35  # same chests: nothing doubled, and the removal is kept
    store.close()


def test_verify_script_passes_on_the_known_match():
    spec = importlib.util.spec_from_file_location("verify_replays", ROOT / "scripts" / "verify_replays.py")
    verify = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify)
    assert [problems for _, _, problems in verify.run_offline()] == [[]]


def test_export_rows_have_the_documented_fields(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    store.import_replay(with_ids(sample()), "a.replay", 10, 1.0)
    board = store.snapshot()["board"]
    rows = [export_row(p) for p in board]
    store.export_rows(tmp_path / "team.csv", rows, EXPORT_FIELDS)
    with open(tmp_path / "team.csv", encoding="utf-8-sig") as handle:
        read = list(csv.DictReader(handle))
    assert list(read[0]) == list(EXPORT_FIELDS) and len(read) == len(board)
    store.export_rows(tmp_path / "team.json", rows, EXPORT_FIELDS)
    assert json.loads((tmp_path / "team.json").read_text(encoding="utf-8"))["rows"][0]["name"]
    assert "epic-a1" not in (tmp_path / "team.json").read_text(encoding="utf-8")  # ids never leave the ledger
    store.close()


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    Config(hotkey_add="", hotkey_undo="", replay_folder=str(tmp_path / "replays")).save(tmp_path / "config.json")
    Prefs(animations=False).save(tmp_path / "ui-settings.json")
    win = MainWindow(tmp_path, scan_on_start=False)
    win.show()
    app.processEvents()
    yield win
    win.close()


def test_teammates_page_filters_profile_and_export(window, tmp_path, monkeypatch):
    window.store.import_replay(with_ids(sample()), "a.replay", 10, 1.0)
    window.refresh()
    panel = window.team_panel
    assert panel.model.rowCount() == 4  # you plus three teammates
    window.navigate(2)
    panel.selected = player_key("epic-a1", None)
    panel.reselect()
    assert not panel.profile.isHidden() and panel.p_title.text() == "Teammate 1"
    assert panel.p_matches.rowCount() == 1
    panel.minimum.setValue(2)
    assert panel.model.rowCount() == 0  # every person here has one match
    panel.minimum.setValue(0)
    assert panel.model.rowCount() == 4
    assert "Teammate 1" in panel.record_labels["most_chests"][0].text()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "out.csv"), ""))
    panel.export(".csv")
    assert len((tmp_path / "out.csv").read_text(encoding="utf-8-sig").splitlines()) == 5
    window.detail.show_match(window.store.snapshot()["match_rows"][0], [], window.prefs)
    squad = window.detail.squad
    assert squad.rowCount() == 4  # you, two teammates who opened chests, and one who did not
    assert squad.item(0, 0).text().startswith("Player") and "MVP" in squad.item(0, 0).text()
    assert [squad.item(r, 1).text() for r in range(squad.rowCount())] == ["36", "16", "1", "0"]
    assert squad.item(0, 5).text().startswith("Chest 31")


def test_overview_shows_teammate_only_types_and_broken_open_for_teammates(window):
    result = with_ids(sample())
    for event in result["events"]:
        if event["by"] == "team" and event["kind"] == "broken":
            event["cls"] = "B_Athena_BuriedChest_RelicFinder_C"  # a type you never opened
            break
    window.store.import_replay(result, "a.replay", 10, 1.0)
    window.refresh()
    types = next(c for c in window.stats_grid.cards if c.key == "types")
    texts = [types.table.itemAt(i).widget().text() for i in range(types.table.count())
             if hasattr(types.table.itemAt(i).widget(), "text")]
    assert "Buried chest" in texts and "Teammates*" in texts
    snap = window.store.snapshot()
    assert sum(snap["team_types"].values()) == snap["team_total"]
    broken = next(c for c in window.stats_grid.cards if c.key == "broken")
    cells = [broken.rows.itemAtPosition(r, 2).widget().text() for r in range(1, 4)]
    assert cells == [str(snap["team_opened"]), str(snap["team_broken"]), str(snap["team_total"])]
