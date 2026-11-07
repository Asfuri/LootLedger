import json
import os
from pathlib import Path
import struct
import time

from lootledger.live import Tracker
from lootledger.replay_reader import peek, scan
from lootledger.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "replay-squad.json"


def replay_bytes(live, key=b"", chunks=((0, 20000), (20000, 40000)), cut=0):
    """A minimal local replay in Fortnite's layout: header, then data chunks with start and end times (ms)."""
    name = "x\0".encode()
    head = struct.pack("<IIi", 0x1CA2E27F, 7, 0) + struct.pack("<III", 40000, 1, 1)
    head += struct.pack("<i", len(name)) + name + struct.pack("<I", int(live)) + struct.pack("<q", 0)
    head += struct.pack("<III", 1, 1, len(key)) + key
    body = b"".join(struct.pack("<IiII", 1, 8 + 64, start, end) + b"\0" * 64 for start, end in chunks)
    data = head + body
    return data[:len(data) - cut] if cut else data


def test_peek_reads_the_live_flag_the_missing_key_and_the_saved_time(tmp_path):
    path = tmp_path / "a.replay"
    path.write_bytes(replay_bytes(live=True))
    assert peek(path) == {"live": True, "locked": True, "recorded": 40.0, "chunks": 2}
    path.write_bytes(replay_bytes(live=False, key=b"k" * 32))
    assert peek(path)["locked"] is False and peek(path)["live"] is False
    path.write_bytes(replay_bytes(live=True, cut=10))  # the last chunk is still being written
    assert peek(path)["recorded"] == 20.0
    path.write_bytes(b"not a replay")
    assert peek(path) is None


def test_tracker_goes_waiting_live_saving_ended(tmp_path):
    folder, log = tmp_path / "Demos", tmp_path / "FortniteGame.log"
    folder.mkdir()
    tracker = Tracker(log)
    assert tracker.poll(folder) == "idle"
    log.write_text("running")
    assert tracker.poll(folder) == "waiting"
    replay = folder / "match.replay"
    replay.write_bytes(replay_bytes(live=True))
    assert tracker.poll(folder) == "live" and tracker.info()["locked"]
    replay.write_bytes(replay_bytes(live=True, chunks=((0, 20000), (20000, 40000), (40000, 60000))))
    assert tracker.poll(folder) == "live" and tracker.info()["recorded"] == 60.0
    replay.write_bytes(replay_bytes(live=False, key=b"k" * 32))  # Fortnite finished the replay
    assert tracker.poll(folder) == "saving"
    assert tracker.poll(folder) == "saving"  # waits for the import
    tracker.counted()
    assert tracker.poll(folder) == "ended"
    old = time.time() - 600
    os.utime(replay, (old, old))
    assert tracker.poll(folder) == "ended"  # stays on the last match until the next one starts


def test_scan_leaves_a_locked_live_replay_alone_then_imports_it_once_finished(tmp_path):
    folder = tmp_path / "Demos"
    folder.mkdir()
    replay = folder / "match.replay"
    replay.write_bytes(replay_bytes(live=True))
    calls = []

    def analyzer(paths, helper=None):
        calls.append([Path(p).name for p in paths])
        result = json.loads(FIXTURE.read_text(encoding="utf-8"))
        return [dict(result, file=str(p)) for p in paths]

    store = Store(tmp_path / "ledger.sqlite")
    live = scan(store, folder, analyzer=analyzer)
    assert live["locked"] and calls == [] and store.replay_files() == {}  # nothing decoded, nothing recorded
    replay.write_bytes(replay_bytes(live=False, key=b"k" * 32))
    assert scan(store, folder, analyzer=analyzer) is None
    assert calls == [["match.replay"]] and store.snapshot()["all"] == 36
    assert store.match_for_file("match.replay") == store.snapshot()["match_rows"][0]["id"]
    scan(store, folder, analyzer=analyzer)
    assert store.snapshot()["all"] == 36  # read once; a re-read could not double count anyway
    store.close()
