import json
import sqlite3

import pytest

from lootledger.detector import Event
from lootledger.store import Store


def test_immediate_durability_recovery_stats_and_undo(tmp_path):
    path = tmp_path / "ledger.sqlite"
    store = Store(path)
    first = store.start()
    store.add(amount=2)
    with sqlite3.connect(path) as other:
        assert other.execute("SELECT sum(amount) FROM events").fetchone()[0] == 2
    store.close()
    recovered = Store(path)
    assert recovered.active()["id"] == first
    assert recovered.stats()["current"] == 2
    recovered.tick(2)
    recovered.end()
    recovered.start()
    recovered.add()
    stats = recovered.stats()
    assert (stats["all"], stats["last"], stats["average"], stats["best"], stats["today"]) == (3, 2, 2, 2, 3)
    recovered.undo()
    assert recovered.stats()["all"] == 2
    recovered.close()


def test_review_confirmation_type_correction_and_event_idempotence(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    store.start()
    event = Event("fixed", 3.2, "review", "Unknown", .7, "ambiguous", 1)
    store.add(event)
    store.add(event)
    assert len(store.entries()) == 1
    assert store.stats()["all"] == 0
    store.edit("fixed", status="confirmed", chest_type="User corrected type")
    assert store.stats()["types"] == {"User corrected type": 1}
    store.edit("fixed", status="undone")
    assert store.stats()["all"] == 0
    assert store.db.execute("SELECT count(*) FROM audit").fetchone()[0] == 3
    store.close()


def test_backups_include_wal_and_restore_safety_copy_and_exports(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    store.start()
    store.add(amount=4)
    backup = tmp_path / "backup.sqlite"
    store.backup(backup)
    store.add(amount=3)
    safety = store.restore(backup)
    assert store.stats()["all"] == 4
    with sqlite3.connect(safety) as previous:
        assert previous.execute("SELECT sum(amount) FROM events").fetchone()[0] == 7
    store.export(tmp_path / "export.json")
    assert json.loads((tmp_path / "export.json").read_text())["events"][0]["amount"] == 4
    store.edit(store.entries()[0]["id"], chest_type="=FORMULA()")
    store.export(tmp_path / "export.csv")
    assert "'=FORMULA()" in (tmp_path / "export.csv").read_text(encoding="utf-8-sig")
    store.close()


def test_invalid_backup_and_counts_preserve_live_data(tmp_path):
    store = Store(tmp_path / "data.sqlite")
    with pytest.raises(ValueError):
        store.add()
    store.start()
    store.add()
    with pytest.raises(ValueError):
        store.add(amount=0)
    bad = tmp_path / "bad.sqlite"
    with sqlite3.connect(bad) as db:
        db.execute("CREATE TABLE unrelated(x)")
    with pytest.raises(ValueError):
        store.restore(bad)
    assert store.stats()["all"] == 1
    store.close()
