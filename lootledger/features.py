"""Setup health, sessions, goals, achievements and period comparison. Plain Python over the snapshot (no Qt)."""
from datetime import timedelta
from pathlib import Path
import time

from .stats import SESSION_GAP

FIX_REPLAYS = "In Fortnite: Settings → Game → Replays → Record Replays: On. Then play a match."


def health(folder, replay_files, log, now=None):
    """Setup checklist and replay-reading health from files on disk and what the ledger has recorded.

    replay_files: {name: (size, mtime, status)} for every replay LootLedger has read.
    Fortnite keeps its Record Replays switch in its own cloud-synced settings, so "replays look on" is
    inferred: Fortnite ran recently but saved no replay since is the warning sign.
    """
    now = time.time() if now is None else now
    folder = Path(folder)
    files = sorted(folder.glob("*.replay"), key=lambda p: p.stat().st_mtime) if folder.is_dir() else []
    newest = files[-1].stat().st_mtime if files else None
    try:
        game = Path(log).stat().st_mtime
    except OSError:
        game = None
    played_without_replay = game is not None and now - game < 86400 and (newest is None or game - newest > 3 * 3600)
    checks = [
        ("Replay folder found", folder.is_dir(), f"Fortnite creates {folder} after its first recorded match. " + FIX_REPLAYS),
        ("Fortnite has saved replays", bool(files), FIX_REPLAYS),
        ("Recent matches were recorded", bool(files) and not played_without_replay,
         "Fortnite ran in the last day but saved no replay for hours. Record Replays may be off. " + FIX_REPLAYS),
    ]
    failed = [name for name, (_, _, status) in replay_files.items() if status == "skipped"]
    return {"checks": checks, "replays": len(files), "newest": newest, "read": len(replay_files),
            "unreadable": len(failed), "ok": all(ok for _, ok, _ in checks)}


def sessions(rows):
    """Finished matches grouped into play sessions: a gap of more than 30 minutes starts a new one. Newest first."""
    result = []
    for row in sorted((r for r in rows if r["mode"] != "Manual"), key=lambda r: r["when"]):
        end = row["when"] + timedelta(seconds=row["seconds"])
        if result and row["when"] - result[-1]["end"] <= SESSION_GAP:
            current = result[-1]
            current["end"] = max(current["end"], end)
            current["matches"] += 1
            current["chests"] += row["count"]
            current["seconds"] += row["seconds"]
        else:
            result.append({"start": row["when"], "end": end, "matches": 1, "chests": row["count"], "seconds": row["seconds"]})
    for session in result:
        session["per_hour"] = session["chests"] * 3600 / session["seconds"] if session["seconds"] else 0.0
    return result[::-1]


def goals(snap, daily, weekly):
    """Progress towards the daily and weekly chest goals (0 = off), with the current day streak."""
    out = []
    for name, target, done in (("Today", daily, snap["today"]), ("This week", weekly, snap["week"])):
        if target:
            out.append({"name": name, "target": target, "done": done, "share": min(done / target, 1.0),
                        "reached": done >= target})
    return {"goals": out, "streak": snap["streak_current"]}


MILESTONES = (100, 500, 1000, 2500, 5000, 10000, 25000)
BEST_MATCH = (25, 40, 60)


def achievements(snap):
    """Every achievement, unlocked or not: (id, title, detail, unlocked)."""
    total, best = snap["all"], snap["best"] or 0
    types = snap["types"]
    items = [(f"chests-{n}", f"{n:,} chests", f"Open {n:,} chests in total", total >= n) for n in MILESTONES]
    items += [(f"match-{n}", f"{n} in one match", f"Open {n} chests in a single match", best >= n) for n in BEST_MATCH]
    items += [("first-relic", "First relic chest", "Open a relic chest", types.get("Relic chest", 0) > 0),
              ("first-buried", "Treasure hunter", "Dig up a buried chest", types.get("Buried chest", 0) > 0),
              ("first-sprite", "Sprite poster", "Open a sprite poster chest", types.get("Sprite poster chest", 0) > 0),
              ("streak-7", "Week streak", "Open chests 7 days in a row", snap["streak_longest"] >= 7),
              ("matches-100", "100 matches", "Have 100 matches read from replays", snap["matches"] >= 100)]
    return [{"id": i, "title": t, "detail": d, "unlocked": u} for i, t, d, u in items]


def period(snap, start, end):
    """Chests, matches and broken-open chests between two dates (inclusive)."""
    rows = [r for r in snap["match_rows"] if start <= r["when"].date() <= end]
    chests = sum(value for day, value in snap["per_day"].items() if start <= day <= end)
    matches = sum(1 for r in rows if r["mode"] != "Manual")
    return {"chests": chests, "matches": matches, "broken": sum(r["broken"] for r in rows),
            "per_match": sum(r["count"] for r in rows if r["mode"] != "Manual") / matches if matches else 0.0,
            "days": (end - start).days + 1}


def compare(snap, first, second):
    """Two periods side by side, with the change from the first to the second."""
    a, b = period(snap, *first), period(snap, *second)
    return [(name, a[key], b[key], b[key] - a[key]) for name, key in
            (("Chests", "chests"), ("Matches", "matches"), ("Chests per match", "per_match"), ("Broken open", "broken"))]
