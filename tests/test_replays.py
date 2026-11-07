import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3

import pytest

from lootledger import replay_reader
from lootledger.replay_reader import classify, mode_name, scan, summarize
from lootledger.store import SCHEMA_V1, Store

FIXTURE = Path(__file__).parent / "fixtures" / "replay-squad.json"


def sample():
    """An anonymized real result: today's 17:23 squad replay (27 opened + 9 broken chests by the owner)."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_classification_uses_fortnite_class_names():
    assert classify("Tiered_Chest_Athena_C") == ("Chest", True)
    assert classify("AlwaysSpawn_NormalChest_C") == ("Chest", True)
    assert classify("AlwaysSpawn_RareChest_C") == ("Rare chest", True)
    assert classify("B_TieredChest_Relics_C") == ("Relic chest", True)
    assert classify("B_Athena_BuriedChest_RelicFinder_C") == ("Buried chest", True)
    assert classify("B_SpritePosters_Booty_Chest_C") == ("Sprite poster chest", True)
    assert classify("Tiered_Ammo_Athena_C") == ("Ammo box", False)
    assert classify("FoodBox_Produce_Athena_C") == ("Food box", False)
    assert classify("Some_New_Chest_C") == ("Other chest", True)
    assert classify("Barrel_Thing_C") == ("Other container", False)
    assert mode_name("Playlist_NoBuildBR_Trio") == "Zero Build Trio"
    assert mode_name("Playlist_HabaneroDuo") == "Ranked Build Duo"
    assert mode_name("playlist_trios") == "Build Trio"
    assert mode_name("Playlist_FigmentSquad") == "FigmentSquad"


def test_summary_keeps_only_your_chests_and_separates_team_and_containers():
    mine, meta = summarize(sample())
    assert len(mine) == 36
    assert sum(e["kind"] == "opened" for e in mine) == 27
    assert {e["type"] for e in mine if e["kind"] == "broken"} == {"Chest", "Rare chest", "Relic chest"}
    assert meta["containers"] == {"Ammo box": 1}
    assert sum(c["opened"] + c["broken"] for c in meta["team"].values()) == 17
    assert meta["placement"] == 3 and meta["mode"] == "Build Squad"


def test_import_is_idempotent_and_keeps_corrections(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    result = sample()
    match_id = store.import_replay(result, "a.replay", 10, 1.0)
    data = store.snapshot()
    assert (data["all"], data["broken"], data["matches"], data["last"]["count"]) == (36, 9, 1, 36)
    assert data["types"] == {"Chest": 31, "Rare chest": 4, "Relic chest": 1}
    assert data["containers"] == {"Ammo box": 1} and data["team_total"] == 17
    removed = store.entries()[0]["id"]
    store.edit(removed, status="undone")
    # Same match read again, also as a renamed copy: no duplicates, and the removal sticks.
    assert store.import_replay(copy.deepcopy(result), "a.replay", 10, 1.0) == match_id
    assert store.import_replay(copy.deepcopy(result), "renamed copy.replay", 10, 2.0) == match_id
    assert store.snapshot()["all"] == 35
    assert len(store.entries(10_000)) == 36
    removed_source = store.db.execute("SELECT source FROM events WHERE id=?", (removed,)).fetchone()[0]
    store.include_broken = False
    data = store.snapshot()
    assert data["all"] == 27 - (removed_source == "replay")
    assert (data["broken"], data["team_total"]) == (0, 12)
    store.close()


def test_event_times_follow_the_replay_clock(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    result = sample()
    store.import_replay(result, "a.replay", 10, 1.0)
    match = store.history()[0]
    started = datetime.fromisoformat(match["started"])
    assert started == datetime.fromisoformat(result["timestamp"]).astimezone()
    assert match["seconds"] == pytest.approx(result["lengthSeconds"])
    first = min(store.entries(), key=lambda e: e["created"])
    assert datetime.fromisoformat(first["created"]) - started == timedelta(seconds=first["video_time"])
    timeline = store.match_events(match["id"])
    assert len(timeline) == 36 and all(row["video_time"] is not None for row in timeline)
    store.close()


def test_manual_correction_goes_to_latest_match_and_undo(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    with pytest.raises(ValueError):
        store.add_correction()
    store.import_replay(sample(), "a.replay", 10, 1.0)
    store.add_correction()
    assert store.snapshot()["all"] == 37
    store.undo()
    assert store.snapshot()["all"] == 36
    store.close()


def test_partly_read_replay_is_kept_and_flagged(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    store.import_replay({**sample(), "ok": False, "error": "ArgumentOutOfRangeException: start"}, "a.replay", 10, 1.0)
    data = store.snapshot()
    assert (data["partial"], data["all"]) == (1, 36)
    store.close()


def test_skips_replays_without_containers_or_owner(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    empty = {**sample(), "events": []}
    assert store.import_replay(empty, "creative.replay", 5, 1.0) is None
    assert store.import_replay({**sample(), "owner": None}, "server.replay", 5, 1.0) is None
    assert store.snapshot()["matches"] == 0
    assert set(store.replay_files()) == {"creative.replay", "server.replay"}
    store.close()


def test_scan_reads_only_new_files_and_holds_back_the_live_match(tmp_path):
    folder = tmp_path / "Demos"
    folder.mkdir()
    for name in ("old.replay", "live.replay"):
        (folder / name).write_bytes(b"x")
    now = datetime.now(timezone.utc).timestamp()
    os.utime(folder / "old.replay", (now - 3600, now - 3600))
    calls = []

    def fake(paths, helper=None):
        calls.append([Path(p).name for p in paths])
        results = []
        for path in paths:
            result = sample()
            result["file"] = str(path)
            result["live"] = Path(path).name == "live.replay"
            result["sessionId"] = Path(path).stem
            results.append(result)
        return results

    store = Store(tmp_path / "ledger.sqlite")
    live = scan(store, folder, now=now, analyzer=fake)
    assert live and Path(live["file"]).name == "live.replay"
    assert store.snapshot()["matches"] == 1
    live = scan(store, folder, now=now, analyzer=fake)
    assert calls[-1] == ["live.replay"]  # finished replays are not read twice
    # A replay still flagged live but untouched for longer than the live window was abandoned: import it.
    later = now + replay_reader.LIVE_WINDOW + 60
    assert scan(store, folder, now=later, analyzer=fake) is None
    assert store.snapshot()["matches"] == 2
    store.close()


def test_clear_keeps_replay_files_unread_until_forgotten(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    store.import_replay(sample(), "a.replay", 10, 1.0)
    before = store.snapshot()
    assert before["all"] == 36
    store.clear()
    assert store.snapshot()["all"] == 0 and store.snapshot()["match_rows"] == []
    assert "a.replay" in store.replay_files()  # a scan would now skip this file
    store.forget_replay_files()
    store.import_replay(sample(), "a.replay", 10, 1.0)
    assert store.snapshot()["all"] == 36
    store.close()


def test_snapshot_is_reused_until_the_data_changes(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    store.import_replay(sample(), "a.replay", 10, 1.0)
    first = store.snapshot()
    assert store.snapshot() is first
    store.add_correction()
    assert store.snapshot() is not first and store.snapshot()["all"] == 37
    store.close()


def test_restores_backups_from_previous_version(tmp_path):
    old = tmp_path / "v1.sqlite"
    with sqlite3.connect(old) as db:
        db.executescript(SCHEMA_V1 + "PRAGMA user_version=1;")
        db.execute("INSERT INTO matches VALUES('m','2026-11-01T10:00:00+00:00','2026-11-01T10:10:00+00:00',600)")
        db.execute("""INSERT INTO events VALUES('e','m','2026-11-01T10:05:00+00:00',NULL,'confirmed','Chest',2,
                      'manual correction',1,'Manual correction',NULL)""")
    store = Store(tmp_path / "ledger.sqlite")
    store.import_replay(sample(), "a.replay", 10, 1.0)
    store.restore(old)
    assert store.stats()["all"] == 2
    assert store.snapshot()["all"] == 2  # restoring invalidates the cached snapshot
    assert store.replay_files() == {}  # replays are read again after restoring an older ledger
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
    store.close()
