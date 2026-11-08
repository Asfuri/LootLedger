"""Old/new golden gate. Private replay results stay under ignored target/golden.

Default mode requires the Rust replay decoder. --summary-only tests attribution/storage
from existing C# JSON; it never counts as replay-parser parity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lootledger.replay_reader import analyze, match_key, summarize  # noqa: E402
from lootledger.store import NAMESPACE, Store  # noqa: E402


def expected(result):
    mine, meta = summarize(result)
    key = match_key(result)
    events = []
    for e in mine:
        events.append({**e, "id": str(uuid.uuid5(NAMESPACE, f'{key}:{e["actor"]}:{e["episode"]}'))})
    return {"key": key, "match_id": str(uuid.uuid5(NAMESPACE, key)), "events": events, "meta": meta}


def compare(a, b, location="root"):
    """Find the first real difference, treating missing optional fields as null."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(a.keys() | b.keys()):
            compare(a.get(key), b.get(key), f"{location}.{key}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            raise AssertionError(f"{location}: {len(a)} rows (old) != {len(b)} rows (Rust)")
        for index, (left, right) in enumerate(zip(a, b)):
            compare(left, right, f"{location}[{index}]")
    elif a != b:
        # Do not print player ids or names in logs. The path is enough to locate private fixtures.
        raise AssertionError(f"{location}: values differ")


def decoded(result):
    """The comparable part of a decoder result.

    The old reader sorts openings with an unstable sort, so equal times may come in either order; both
    are put in (time, actor, episode) order. Error texts are .NET exception messages: only whether a
    file failed is compared.
    """
    # "stats" is new in the Rust decoder (the old reader kept only eliminations from the same event).
    result = {k: v for k, v in result.items() if k not in ("schema", "file", "trace", "stats")}
    result["events"] = sorted(result.get("events") or [], key=lambda e: (e["t"], e["actor"], e["episode"]))
    result["error"] = bool(result.get("error"))
    return result


def run(cli, command, path):
    done = subprocess.run([str(cli), command, str(path)], capture_output=True, timeout=900,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode:
        raise RuntimeError(done.stderr.decode("utf-8", "replace").strip())
    return [json.loads(line) for line in done.stdout.decode("utf-8").splitlines() if line.strip()]


def storage_parity(cli, private, results):
    """Compare actual persisted rows, then edit/undo in Python and re-import in Rust."""
    with tempfile.TemporaryDirectory(prefix="lootledger-golden-") as temp:
        old_path, new_path = Path(temp) / "old.sqlite", Path(temp) / "new.sqlite"
        old_store = Store(old_path)
        try:
            for result in results:
                old_store.import_replay(result, result["file"], 1, 1.0)
            command = [str(cli), "import-jsonl", str(private), "--into", str(new_path)]
            done = subprocess.run(command, capture_output=True, timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if done.returncode:
                raise RuntimeError(done.stderr.decode("utf-8", "replace"))
            from contextlib import closing
            def saved_rows(db, table):
                db.row_factory = sqlite3.Row
                rows = [dict(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                if table == "match_meta":
                    for row in rows:
                        row["meta"] = json.loads(row["meta"])
                if table == "replay_files":
                    for row in rows:
                        row.pop("scanned")  # wall-clock audit timestamps differ between runs
                return rows
            with closing(sqlite3.connect(new_path)) as new_db:
                for table in ("matches", "events", "match_meta", "replay_files"):
                    compare(saved_rows(old_store.db, table), saved_rows(new_db, table), f"storage.{table}")
                # The old app must still be able to edit the Rust-created database.
            new_store = Store(new_path)
            try:
                row = new_store.entries(1)[0]
                new_store.edit(row["id"], amount=7, chest_type="Corrected chest")
                new_store.undo()
                before = new_store.stats()["all"]
            finally:
                new_store.close()
            done = subprocess.run(command, capture_output=True, timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if done.returncode:
                raise RuntimeError(done.stderr.decode("utf-8", "replace"))
            with closing(sqlite3.connect(new_path)) as db:
                total = db.execute("SELECT coalesce(sum(amount),0) FROM events WHERE status='confirmed'").fetchone()[0]
                compare(before, total, "storage.corrections_after_reimport")
            old_store.restore(new_path)
            compare(before, old_store.stats()["all"], "storage.python_restore_of_rust_ledger")
        finally:
            old_store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust", type=Path, default=ROOT / "target/debug/lootledger-cli.exe")
    parser.add_argument("--folder", type=Path)
    parser.add_argument("--old-jsonl", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "target/golden/report.json")
    args = parser.parse_args()
    if not args.folder and not args.old_jsonl and not args.fixture:
        parser.error("Pass --folder, --old-jsonl or --fixture")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"stage": "summary-only" if args.summary_only else "replay-parser", "passed": False,
              "parser_parity": False, "files": 0, "differences": []}
    try:
        files = sorted(args.folder.glob("*.replay")) if args.folder else []
        old = [json.loads(args.fixture.read_text(encoding="utf-8-sig"))] if args.fixture else ([json.loads(line) for line in args.old_jsonl.read_text(encoding="utf-8-sig").splitlines() if line.strip()] if args.old_jsonl else analyze(files))
        if not old:
            raise ValueError("Golden corpus is empty")
        if not args.summary_only:
            base = args.old_jsonl.resolve().parent if args.old_jsonl else Path.cwd()
            for index, result in enumerate(old):
                # Compare the actual decoded containers before summaries can hide any differences.
                actual = run(args.rust, "decode", base / result["file"])
                if len(actual) != 1:
                    raise AssertionError(f"replay[{index}]: expected one result")
                compare(decoded(result), decoded(actual[0]), f"replay[{index}]")
            report["parser_parity"] = True
        private = args.output.parent / "input.jsonl"
        private.write_text("\n".join(json.dumps(r) for r in old) + "\n", encoding="utf-8")
        actual = run(args.rust, "summarize-jsonl", private)
        compare([expected(r) for r in old], actual, "summaries")
        report["files"] = len(old)
        storage_parity(args.rust, private, old)
        report["storage_parity"] = True
        report["corpus_sha256"] = hashlib.sha256(private.read_bytes()).hexdigest()
        if args.ledger:
            from contextlib import closing
            with closing(sqlite3.connect(args.ledger.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                total = db.execute("SELECT coalesce(sum(amount),0) FROM events WHERE status='confirmed'").fetchone()[0]
                counts = db.execute("SELECT count(*),coalesce(sum(seconds),0) FROM matches").fetchone()
                summary = run(args.rust, "ledger-summary", args.ledger)[0]
                compare(total, summary["totals"]["chests"], "ledger.total")
                compare(counts[0], summary["totals"]["matches"], "ledger.matches")
                compare(counts[1], summary["totals"]["seconds"], "ledger.seconds")
                report["existing_ledger_read"] = True
        report["passed"] = True
    except Exception as error:
        report["differences"].append(f"{type(error).__name__}: {error}")
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
