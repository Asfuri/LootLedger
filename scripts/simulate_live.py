"""Replay a real match as if Fortnite were recording it, and check the live hand-over end to end.

    python scripts/simulate_live.py [finished.replay] [--seconds 0.3]

A temporary folder gets the replay the way Fortnite writes it during a match: header marked live, no
encryption key, data chunks appended over time. Then the finished file replaces it. The tracker must go
live -> saving, the scan must not decode the locked file, and the final count must equal a direct import
of the same replay. Nothing is written outside the temporary folder. Exit code 1 on any mismatch.
"""
import shutil
from pathlib import Path
import struct
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lootledger.live import Tracker  # noqa: E402
from lootledger.replay_reader import analyze, default_folder, scan  # noqa: E402
from lootledger.store import Store  # noqa: E402


def layout(data):
    """Offsets of the live flag, the key length and the end of the header in a local replay."""
    pos = 8
    if struct.unpack_from("<I", data, 4)[0] >= 7:
        pos += 4 + struct.unpack_from("<I", data, 8)[0] * 20
    pos += 12
    name = struct.unpack_from("<i", data, pos)[0]
    pos += 4 + (name if name >= 0 else -name * 2)
    live_at = pos
    pos += 4 + 8 + 4 + 4
    key_at = pos
    return live_at, key_at, key_at + 4 + struct.unpack_from("<I", data, key_at)[0]


def recording(data):
    """The header as Fortnite writes it while recording (live, no key), and the chunk boundaries after it."""
    live_at, key_at, end = layout(data)
    head = bytearray(data[:key_at]) + struct.pack("<I", 0)
    struct.pack_into("<I", head, live_at, 1)
    bounds, pos = [], end
    while pos + 8 <= len(data):
        size = struct.unpack_from("<i", data, pos + 4)[0]
        if size <= 0:
            break
        pos += 8 + size
        bounds.append(pos)
    return bytes(head), end, bounds


def main(argv):
    pause = float(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else .3
    files = [a for a in argv if a.endswith(".replay")]
    source = Path(files[0]) if files else max(default_folder().glob("*.replay"), key=lambda p: p.stat().st_mtime)
    data = source.read_bytes()
    head, start, bounds = recording(data)
    work = Path(tempfile.mkdtemp(prefix="lootledger-live-"))
    folder, log = work / "Demos", work / "FortniteGame.log"
    folder.mkdir()
    log.write_text("game running")
    target = folder / source.name
    tracker, store, states, problems = Tracker(log), Store(work / "ledger.sqlite"), [], []
    print(f"simulating {source.name}: {len(bounds)} chunks, {len(data) // 1024} KB")
    previous = start
    for index, bound in enumerate(bounds):
        with target.open("ab" if index else "wb") as out:
            if not index:
                out.write(head)
            out.write(data[previous:bound])
        previous = bound
        states.append(tracker.poll(folder))
        if index % 25 == 0:
            live = scan(store, folder, analyzer=analyze)
            if not (live and live.get("locked")) or store.replay_files():
                problems.append(f"chunk {index}: the scan decoded or recorded the file while it was live")
        time.sleep(pause)
    target.write_bytes(data)  # Fortnite finalizes: live off, key written
    states.append(tracker.poll(folder))
    started = time.perf_counter()
    scan(store, folder, analyzer=analyze)
    took = time.perf_counter() - started
    if target.name in store.replay_files():
        tracker.counted()
    states.append(tracker.poll(folder))
    final = store.snapshot()["all"]
    scan(store, folder, analyzer=analyze)
    store.forget_replay_files()
    scan(store, folder, analyzer=analyze)  # a second full read must not add anything
    again = store.snapshot()["all"]
    direct = Store(work / "direct.sqlite")
    direct.import_replay(analyze([source])[0], source.name, len(data), source.stat().st_mtime)
    expected = direct.snapshot()["all"]
    order = [s for i, s in enumerate(states) if i == 0 or states[i - 1] != s]
    print("states:", " -> ".join(order))
    print(f"count after the hand-over: {final}; after re-reading: {again}; direct import: {expected}; "
          f"read the finished replay in {took:.1f} s")
    if order != ["live", "saving", "ended"]:
        problems.append(f"unexpected states {order}")
    if not final == again == expected:
        problems.append("counts differ")
    store.close()
    direct.close()
    shutil.rmtree(work, ignore_errors=True)  # the copied replay
    for problem in problems:
        print("FAIL:", problem)
    print("ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
