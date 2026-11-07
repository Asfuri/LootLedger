import csv
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from . import stats
from .replay_reader import match_key, started_at, summarize

SCHEMA_VERSION = 3
NAMESPACE = uuid.UUID("2f9c6a4e-8d1b-4e57-9b0a-6c3e1d7f5a21")
EVENT_FIELDS = ("id", "match_id", "created", "video_time", "status", "chest_type", "amount",
                "source", "confidence", "reason", "evidence")

SCHEMA_V1 = """
    CREATE TABLE IF NOT EXISTS matches (
        id TEXT PRIMARY KEY, started TEXT NOT NULL, ended TEXT, seconds REAL NOT NULL DEFAULT 0);
    CREATE UNIQUE INDEX IF NOT EXISTS one_active ON matches((1)) WHERE ended IS NULL;
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY, match_id TEXT NOT NULL REFERENCES matches(id),
        created TEXT NOT NULL, video_time REAL, status TEXT NOT NULL
        CHECK(status IN ('confirmed','review','undone','rejected')),
        chest_type TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount > 0),
        source TEXT NOT NULL, confidence REAL NOT NULL, reason TEXT NOT NULL, evidence TEXT);
    CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY, created TEXT NOT NULL, event_id TEXT,
        action TEXT NOT NULL, detail TEXT NOT NULL);
"""
# Version 2: matches imported from Fortnite replays, and which replay files were already read.
SCHEMA_V2 = """
    CREATE TABLE IF NOT EXISTS match_meta (
        match_id TEXT PRIMARY KEY REFERENCES matches(id), key TEXT NOT NULL UNIQUE, meta TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS replay_files (
        file TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime REAL NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('imported','skipped')),
        match_id TEXT REFERENCES matches(id), scanned TEXT NOT NULL);
"""
# Version 3: your notes, tags and favourite flag per match. Kept apart from match_meta, which re-reads replace.
SCHEMA_V3 = """
    CREATE TABLE IF NOT EXISTS match_notes (
        match_id TEXT PRIMARY KEY REFERENCES matches(id), note TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '', favorite INTEGER NOT NULL DEFAULT 0);
"""
SCHEMAS = {1: SCHEMA_V1, 2: SCHEMA_V1 + SCHEMA_V2, 3: SCHEMA_V1 + SCHEMA_V2 + SCHEMA_V3}
REPLAY_SOURCES = ("replay", "replay-broken")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def schema_of(db):
    # sqlite_master keeps each CREATE statement's original layout; compare it whitespace-insensitively.
    query = "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
    return [(kind, name, table, " ".join(sql.split())) for kind, name, table, sql in db.execute(query)]


def _safe_cell(value):
    # Neutralize spreadsheet formulas in user-corrected text.
    return "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.include_broken = True
        self._snapshot, self._snapshot_key = None, None
        self._migrate()

    def _migrate(self):
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if 0 < version < SCHEMA_VERSION and self.db.execute("SELECT count(*) FROM matches").fetchone()[0]:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.backup(self.path.parent / "backups" / f"before-schema-v{SCHEMA_VERSION}-{stamp}.sqlite")
        self.db.executescript(SCHEMAS[SCHEMA_VERSION] + f"PRAGMA user_version={SCHEMA_VERSION};")

    def close(self):
        self.db.close()

    def active(self):
        return self.db.execute("SELECT * FROM matches WHERE ended IS NULL").fetchone()

    def start(self):
        if self.active():
            return self.active()["id"]
        match_id = str(uuid.uuid4())
        with self.db:
            self.db.execute("INSERT INTO matches(id,started) VALUES(?,?)", (match_id, utc_now()))
        return match_id

    def end(self):
        with self.db:
            self.db.execute("UPDATE matches SET ended=? WHERE ended IS NULL", (utc_now(),))

    def tick(self, seconds):
        if not 0 <= seconds <= 10:
            raise ValueError("Invalid active time increment")
        with self.db:
            self.db.execute("UPDATE matches SET seconds=seconds+? WHERE ended IS NULL", (seconds,))

    def add(self, event=None, *, amount=1, chest_type="Unknown", evidence=None, force_review=False, match_id=None):
        active = self.active()
        match_id = match_id or (active["id"] if active else None)
        if not match_id:
            raise ValueError("Start a match before recording an opening")
        if not isinstance(amount, int) or not 1 <= amount <= 10000:
            raise ValueError("Count must be between 1 and 10000")
        event_id = event.id if event else str(uuid.uuid4())
        status = "review" if force_review else (event.status if event else "confirmed")
        with self.db:
            result = self.db.execute("""INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING""", (
                event_id, match_id, utc_now(), event.time if event else None, status,
                event.chest_type if event else chest_type, amount, "automatic" if event else "manual correction",
                event.confidence if event else 1., event.reason if event else "Manual correction", evidence))
            if result.rowcount:
                self._audit(event_id, "added", asdict(event) if event else {"amount": amount, "type": chest_type})
        return event_id

    def add_correction(self, amount=1, chest_type="Chest"):
        """Manual +1: goes to the active manual match, else the most recent match."""
        active = self.active()
        latest = self.db.execute("SELECT id FROM matches ORDER BY started DESC LIMIT 1").fetchone()
        if not active and not latest:
            raise ValueError("No match yet. Play a match with replays enabled, then correct it here.")
        return self.add(amount=amount, chest_type=chest_type, match_id=(active or latest)["id"])

    def _audit(self, event_id, action, detail):
        self.db.execute("INSERT INTO audit(created,event_id,action,detail) VALUES(?,?,?,?)",
                        (utc_now(), event_id, action, json.dumps(detail)))

    def edit(self, event_id, *, status=None, chest_type=None, amount=None):
        old = self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if old is None:
            raise ValueError("Entry no longer exists")
        new = dict(old)
        if status is not None:
            if status not in ("confirmed", "review", "undone", "rejected"):
                raise ValueError("Invalid event status")
            new["status"] = status
        if chest_type is not None:
            if not chest_type.strip() or len(chest_type) > 80:
                raise ValueError("Type must contain 1–80 characters")
            new["chest_type"] = chest_type.strip()
        if amount is not None:
            if not isinstance(amount, int) or not 1 <= amount <= 10000:
                raise ValueError("Count must be between 1 and 10000")
            new["amount"] = amount
        with self.db:
            self.db.execute("UPDATE events SET status=?,chest_type=?,amount=? WHERE id=?",
                            (new["status"], new["chest_type"], new["amount"], event_id))
            self._audit(event_id, "edited", {"before": dict(old), "after": new})

    def undo(self):
        row = self.db.execute(
            "SELECT id FROM events WHERE status='confirmed' ORDER BY created DESC, rowid DESC LIMIT 1").fetchone()
        if row:
            self.edit(row["id"], status="undone")

    def entries(self, limit=500):
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM events ORDER BY created DESC, rowid DESC LIMIT ?", (limit,))]

    def match_events(self, match_id):
        """Counted openings in one match that have a time inside the replay (for the timeline)."""
        return [dict(row) for row in self.db.execute(
            f"SELECT e.video_time, e.chest_type, e.source FROM events e WHERE e.match_id=? AND {self._counted()} "
            "ORDER BY e.video_time", (match_id,))]

    def _counted(self, alias="e"):
        """SQL condition for events that count toward totals."""
        broken = "" if self.include_broken else f" AND {alias}.source != 'replay-broken'"
        return f"{alias}.status='confirmed'{broken}"

    def history(self):
        return [dict(row) for row in self.db.execute(f"""
            SELECT m.*, coalesce(sum(CASE WHEN {self._counted()} THEN e.amount ELSE 0 END),0) total,
                   coalesce(sum(CASE WHEN {self._counted()} AND e.source='replay-broken' THEN e.amount ELSE 0 END),0) broken,
                   mm.meta meta
            FROM matches m LEFT JOIN events e ON m.id=e.match_id LEFT JOIN match_meta mm ON mm.match_id=m.id
            GROUP BY m.id ORDER BY m.started DESC, m.rowid DESC
        """)]

    def stats(self):
        matches = self.history()
        completed = [m for m in matches if m["ended"]]
        active = next((m for m in matches if not m["ended"]), None)
        total = sum(m["total"] for m in matches)
        seconds = sum(m["seconds"] for m in matches)
        today = datetime.now().date()
        today_total = sum(row["amount"] for row in self.db.execute(
            f"SELECT created,amount FROM events e WHERE {self._counted()}")
            if datetime.fromisoformat(row["created"]).astimezone().date() == today)
        types = dict(self.db.execute(f"SELECT chest_type,sum(amount) FROM events e WHERE {self._counted()} GROUP BY chest_type"))
        return {"current": active["total"] if active else 0, "last": completed[0]["total"] if completed else 0,
                "all": total, "today": today_total, "per_hour": total * 3600 / seconds if seconds else 0,
                "average": sum(m["total"] for m in completed) / len(completed) if completed else 0,
                "best": max((m["total"] for m in completed), default=0), "types": types,
                "review": self.db.execute("SELECT count(*) FROM events WHERE status='review'").fetchone()[0]}

    def snapshot(self, session_start=None, now=None):
        """Everything the UI shows. Rebuilt only when the data, the broken-open setting or the day changes."""
        now = now or datetime.now().astimezone()
        key = (self.db.execute("PRAGMA data_version").fetchone()[0], self.db.total_changes,
               self.include_broken, now.date(), session_start)
        if key == self._snapshot_key:
            return self._snapshot
        events = [stats.Ev(datetime.fromisoformat(row[0]).astimezone(), row[1], row[2], row[3], row[4])
                  for row in self.db.execute(f"""SELECT e.created, e.amount, e.chest_type, e.source, e.match_id
                                                 FROM events e WHERE {self._counted()}""")]
        matches = [{"id": m["id"], "started": datetime.fromisoformat(m["started"]).astimezone(),
                    "seconds": m["seconds"], "total": m["total"], "broken": m["broken"],
                    "meta": json.loads(m["meta"]) if m["meta"] else None} for m in self.history()]
        snap = stats.compute(events, matches, now, session_start, self.include_broken)
        notes = self.notes()
        for row in snap["match_rows"]:
            row.update(notes.get(row["id"], {"note": "", "tags": "", "favorite": False}))
        snap["entries"] = [{**row, "when": datetime.fromisoformat(row["created"]).astimezone()}
                           for row in self.entries(2**31 - 1)]
        self._snapshot, self._snapshot_key = snap, key
        return snap

    # ---- Fortnite replays -------------------------------------------------------------------

    def replay_files(self):
        return {row["file"]: (row["size"], row["mtime"]) for row in self.db.execute("SELECT * FROM replay_files")}

    def replay_file_states(self):
        return {row["file"]: (row["size"], row["mtime"], row["status"]) for row in self.db.execute("SELECT * FROM replay_files")}

    def notes(self):
        return {row["match_id"]: {"note": row["note"], "tags": row["tags"], "favorite": bool(row["favorite"])}
                for row in self.db.execute("SELECT * FROM match_notes")}

    def set_note(self, match_id, **changes):
        """Change a match's note, tags (comma separated) or favourite flag. Text is limited to keep exports sane."""
        current = self.notes().get(match_id, {"note": "", "tags": "", "favorite": False})
        for key, value in changes.items():
            if key not in current:
                raise ValueError(f"Unknown note field: {key}")
            if isinstance(value, str) and len(value) > 2000:
                raise ValueError("Notes and tags are limited to 2000 characters")
            current[key] = value
        tags = ", ".join(dict.fromkeys(t.strip() for t in current["tags"].split(",") if t.strip()))
        with self.db:
            self.db.execute("""INSERT INTO match_notes VALUES(?,?,?,?) ON CONFLICT(match_id) DO UPDATE SET
                               note=excluded.note, tags=excluded.tags, favorite=excluded.favorite""",
                            (match_id, current["note"].strip(), tags, int(bool(current["favorite"]))))

    def match_for_file(self, file):
        row = self.db.execute("SELECT match_id FROM replay_files WHERE file=?", (file,)).fetchone()
        return row[0] if row else None

    def files_without_players(self):
        """Replay files whose match was read before per-player details existed."""
        return {row[0] for row in self.db.execute("""SELECT r.file FROM replay_files r
                                                     JOIN match_meta m ON m.match_id=r.match_id
                                                     WHERE r.status='imported' AND json_extract(m.meta,'$.players') IS NULL""")}

    def forget_replay_files(self):
        """Read every replay again on the next scan; imports are idempotent and keep your corrections."""
        with self.db:
            self.db.execute("DELETE FROM replay_files")

    def import_replay(self, result, file, size, mtime):
        """Save one analyzed replay as a match. Returns the match id, or None when skipped."""
        owner = result.get("owner")
        if not owner or not result.get("events"):
            # No recording player, or a mode without containers (e.g. Creative): nothing to count.
            with self.db:
                self._record_file(file, size, mtime, "skipped", None)
            return None
        key = match_key(result)
        match_id = str(uuid.uuid5(NAMESPACE, key))
        start = started_at(result, mtime)
        length = float(result.get("lengthSeconds") or 0)
        mine, meta = summarize(result)
        meta["key"] = key
        meta["complete"] = bool(result.get("ok"))
        with self.db:
            self.db.execute("""INSERT INTO matches(id,started,ended,seconds) VALUES(?,?,?,?)
                               ON CONFLICT(id) DO UPDATE SET ended=excluded.ended, seconds=excluded.seconds""",
                            (match_id, start.isoformat(), (start + timedelta(seconds=length)).isoformat(), length))
            self.db.execute("""INSERT INTO match_meta(match_id,key,meta) VALUES(?,?,?)
                               ON CONFLICT(match_id) DO UPDATE SET meta=excluded.meta""",
                            (match_id, key, json.dumps(meta)))
            added = 0
            for event in mine:
                event_id = str(uuid.uuid5(NAMESPACE, f'{key}:{event["actor"]}:{event["episode"]}'))
                kind = "Opened" if event["kind"] == "opened" else "Broken open (not searched)"
                added += self.db.execute("""INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING""", (
                    event_id, match_id, (start + timedelta(seconds=event["t"])).isoformat(), event["t"], "confirmed",
                    event["type"], 1, "replay" if event["kind"] == "opened" else "replay-broken", 1.,
                    f'{kind} · {event["cls"]} · {meta["file"]} at {event["t"]:.1f}s', None)).rowcount
            if added:
                self._audit(None, "replay imported", {"match": match_id, "file": file, "added": added})
            self._record_file(file, size, mtime, "imported", match_id)
        return match_id

    def _record_file(self, file, size, mtime, status, match_id):
        self.db.execute("""INSERT INTO replay_files VALUES(?,?,?,?,?,?) ON CONFLICT(file) DO UPDATE SET
                           size=excluded.size, mtime=excluded.mtime, status=excluded.status,
                           match_id=excluded.match_id, scanned=excluded.scanned""",
                        (file, size, mtime, status, match_id, utc_now()))

    def clear(self):
        """Delete all matches, openings and corrections. Replay files stay recorded, so they are not read again."""
        with self.db:
            self.db.execute("DELETE FROM events")
            self.db.execute("DELETE FROM match_notes")
            self.db.execute("DELETE FROM match_meta")
            self.db.execute("DELETE FROM audit")
            self.db.execute("UPDATE replay_files SET match_id=NULL")
            self.db.execute("DELETE FROM matches")
        self._snapshot_key = None

    # ---- Export, backup, restore -----------------------------------------------------------

    @staticmethod
    def export_rows(path, rows, fields=EVENT_FIELDS):
        """Write rows as CSV (by file extension) or JSON. Formula-like text is neutralized in CSV."""
        path = Path(path)
        if path.suffix.lower() == ".csv":
            with path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fields)
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: _safe_cell(row.get(field)) for field in fields})
        else:
            path.write_text(json.dumps({"schema": SCHEMA_VERSION, "exported": utc_now(), "rows": rows},
                                       indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    def export(self, path):
        path = Path(path)
        if path.suffix.lower() == ".csv":
            self.export_rows(path, self.entries(2**31 - 1))
        else:
            matches = self.history()
            for m in matches:
                m["meta"] = json.loads(m["meta"]) if m["meta"] else None
            path.write_text(json.dumps({"schema": SCHEMA_VERSION, "exported": utc_now(), "matches": matches,
                "events": self.entries(2**31 - 1), "notes": self.notes(), "audit": [dict(r) for r in self.db.execute("SELECT * FROM audit")]}, indent=2), encoding="utf-8")

    def backup(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() == self.path.resolve():
            raise ValueError("Choose a different backup file")
        temp = path.with_name(path.name + f".{uuid.uuid4().hex[:8]}.tmp")
        with closing(sqlite3.connect(temp)) as copy:
            self.db.backup(copy)
        temp.replace(path)

    def restore(self, path):
        path = Path(path)
        if path.resolve() == self.path.resolve():
            raise ValueError("Choose a backup file")
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
            source.execute("PRAGMA trusted_schema=OFF")
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup failed its integrity check")
            version = source.execute("PRAGMA user_version").fetchone()[0]
            if version not in SCHEMAS:
                raise ValueError("Unsupported backup version")
            with closing(sqlite3.connect(":memory:")) as reference:
                reference.executescript(SCHEMAS[version])
                if schema_of(source) != schema_of(reference):
                    raise ValueError("Backup contains an unexpected schema")
            if source.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Backup contains invalid match references")
            safety = self.path.with_name(f"before-restore-{uuid.uuid4().hex[:8]}.sqlite")
            self.backup(safety)
            # The SQLite backup API replaces the live database transactionally, including WAL.
            source.backup(self.db)
        self._snapshot_key = None
        self._migrate()
        return safety
