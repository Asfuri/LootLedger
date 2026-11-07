"""Dashboard statistics: plain Python over openings and matches (no Qt, no SQL).

Times are local. A day is a calendar date and weeks start on Monday.
"""
from collections import Counter, namedtuple
from datetime import timedelta
import statistics

Ev = namedtuple("Ev", "when amount chest_type source match_id")
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
SESSION_GAP = timedelta(minutes=30)
RECENT = 20


def _span(per_day, start, end):
    return sum(value for day, value in per_day.items() if start <= day <= end)


def _peak_hour(events):
    """Most chests opened in any rolling 60 minutes, as (count, when the window ended)."""
    times = sorted(events, key=lambda e: e.when)
    best, low, window = (0, None), 0, 0
    for event in times:
        window += event.amount
        while event.when - times[low].when >= HOUR:
            window -= times[low].amount
            low += 1
        if window > best[0]:
            best = (window, event.when)
    return best


def _streaks(per_day, today):
    """(longest run of consecutive days with chests, current run ending today or yesterday)."""
    days = sorted(day for day, value in per_day.items() if value > 0)
    longest = run = 0
    previous = None
    for day in days:
        run = run + 1 if previous is not None and day - previous == DAY else 1
        longest = max(longest, run)
        previous = day
    current, day = 0, today if per_day.get(today) else today - DAY
    while per_day.get(day, 0) > 0:
        current += 1
        day -= DAY
    return longest, current


def _longest_session(analyzed):
    """Matches start within SESSION_GAP of the previous one's end are one session. Returns the longest."""
    best = current = None
    for match in analyzed:
        end = match["started"] + timedelta(seconds=match["seconds"])
        if current and match["started"] - current["end"] <= SESSION_GAP:
            current["end"] = max(current["end"], end)
            current["chests"] += match["total"]
            current["matches"] += 1
        else:
            current = {"start": match["started"], "end": end, "chests": match["total"], "matches": 1}
        if best is None or current["end"] - current["start"] > best["end"] - best["start"]:
            best = dict(current)
    return best


def series(per_day, grain, start, end):
    """Counts per day, week or month from start to end inclusive, including empty periods."""
    if grain == "week":
        key = lambda day: day - timedelta(days=day.weekday())
    elif grain == "month":
        key = lambda day: day.replace(day=1)
    else:
        key = lambda day: day
    buckets = {}
    cursor, last = key(start), key(end)
    while cursor <= last:
        buckets[cursor] = 0
        if grain == "week":
            cursor += timedelta(days=7)
        elif grain == "month":
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            cursor += DAY
    for day, value in per_day.items():
        if start <= day <= end and key(day) in buckets:
            buckets[key(day)] += value
    return sorted(buckets.items())


def trend(snap, grain, days, key="per_day"):
    """Chart points for the trend card (key="match_days" counts matches instead). days=0 means everything."""
    today = snap["today_date"]
    start = today - timedelta(days=days - 1) if days else min(snap["per_day"], default=today)
    return series(snap[key], grain, start, today)


def last_days(snap, count):
    today = snap["today_date"]
    return [snap["per_day"].get(today - timedelta(days=offset), 0) for offset in range(count - 1, -1, -1)]


RARE = ("Rare chest", "Relic chest", "Buried chest")


def _squad(meta, include_broken):
    """Everyone the replay showed in one match, most chests first. Your counts come from your own events."""
    people = []
    for p in meta["players"]:
        counts = p.get("counts") or {}
        opened = sum(c.get("opened", 0) for c in counts.values())
        broken = sum(c.get("broken", 0) for c in counts.values()) if include_broken else 0
        types = {name: c.get("opened", 0) + (c.get("broken", 0) if include_broken else 0) for name, c in counts.items()}
        anonymous = p["key"].startswith("anon-")  # no account id and no name in the replay
        people.append({"key": p["key"], "name": p["name"], "me": p["me"], "bot": p["bot"], "anonymous": anonymous,
                       "unranked": p["bot"] or anonymous, "opened": opened, "broken": broken,
                       "total": opened + broken,
                       "types": {name: n for name, n in types.items() if n}, "containers": p.get("containers") or {}})
    people.sort(key=lambda p: (-p["total"], -p["opened"], not p["me"], p["name"]))
    return people


def tag(person):
    """Short label after a name: you, bot, or unnamed."""
    return " · you" if person["me"] else " · bot" if person["bot"] else " · unnamed" if person["anonymous"] else ""


def _mvp(squad):
    """Key of the player with the most chests, or None on a tie. Bots and unnamed players are never MVP."""
    ranked = sorted((p for p in squad if p["total"] and not p["unranked"]), key=lambda p: (-p["total"], -p["opened"]))
    if not ranked or (len(ranked) > 1 and (ranked[0]["total"], ranked[0]["opened"]) == (ranked[1]["total"], ranked[1]["opened"])):
        return None
    return ranked[0]["key"]


def board(rows):
    """Everyone across these match rows, merged by stable id, most chests first. Bots are listed but not ranked."""
    people = {}
    for row in sorted(rows, key=lambda r: r["when"]):  # oldest first, so the newest name wins
        for p in row["squad"] or []:
            person = people.setdefault(p["key"], {"key": p["key"], "name": p["name"], "me": p["me"], "bot": p["bot"],
                                                  "anonymous": p["anonymous"], "unranked": p["unranked"],
                                                  "matches": 0, "total": 0, "opened": 0, "broken": 0,
                                                  "types": Counter(), "best": 0, "best_when": None, "last": None})
            person["name"] = p["name"]
            person["matches"] += 1
            person["total"] += p["total"]
            person["opened"] += p["opened"]
            person["broken"] += p["broken"]
            person["types"].update(p["types"])
            if p["total"] > person["best"]:
                person["best"], person["best_when"] = p["total"], row["when"]
            person["last"] = row["when"]
    ranked = sorted(people.values(), key=lambda x: (x["unranked"], -x["total"], -x["matches"], x["name"]))
    for person in ranked:
        person["per_match"] = person["total"] / person["matches"]
        person["rare"] = sum(person["types"][name] for name in RARE)
    return ranked


def records(ranked):
    """Records among teammates (you, bots and unnamed players excluded): most chests, best single match, most together."""
    mates = [p for p in ranked if not p["me"] and not p["unranked"]]
    return {"most_chests": max(mates, key=lambda p: p["total"], default=None),
            "best_match": max(mates, key=lambda p: p["best"], default=None),
            "most_played": max(mates, key=lambda p: p["matches"], default=None)}


def profile(rows, key):
    """One player's matches with you, oldest first: their chests and yours in each."""
    history = []
    for row in sorted(rows, key=lambda r: r["when"]):
        for p in row["squad"] or []:
            if p["key"] == key:
                mine = next((q["total"] for q in row["squad"] if q["me"]), 0)
                history.append({"id": row["id"], "when": row["when"], "mode": row["mode"], "total": p["total"],
                                "opened": p["opened"], "broken": p["broken"], "types": p["types"], "mine": mine})
    return history


def compute(events, matches, now, session_start=None, include_broken=True):
    today = now.date()
    per_day, types, match_types = Counter(), Counter(), {}
    heat = [[0] * 24 for _ in range(7)]
    broken = 0
    for event in events:
        per_day[event.when.date()] += event.amount
        types[event.chest_type] += event.amount
        heat[event.when.weekday()][event.when.hour] += event.amount
        if event.source == "replay-broken":
            broken += event.amount
        if event.match_id:
            match_types.setdefault(event.match_id, Counter())[event.chest_type] += event.amount

    analyzed = sorted((m for m in matches if m["meta"] is not None), key=lambda m: m["started"])
    heat_matches, match_days = [[0] * 24 for _ in range(7)], Counter()  # for the tooltips
    for m in analyzed:
        heat_matches[m["started"].weekday()][m["started"].hour] += 1
        match_days[m["started"].date()] += 1
    analyzed_ids = {m["id"] for m in analyzed}
    modes, containers, team_types, team_containers = {}, Counter(), Counter(), Counter()
    team_opened = team_broken = unattributed = 0
    rows = []
    for m in matches:
        meta = m["meta"] or {}
        analyzed_row = m["id"] in analyzed_ids
        team = 0
        for name, counts in (meta.get("team") or {}).items():
            opened_n, broken_n = counts.get("opened", 0), counts.get("broken", 0)
            count = opened_n + (broken_n if include_broken else 0)
            team += count
            if analyzed_row:
                team_types[name] += count
                team_opened += opened_n
                team_broken += (broken_n if include_broken else 0)
        squad = _squad(meta, include_broken) if "players" in meta else None
        if analyzed_row:
            bucket = modes.setdefault(meta.get("mode") or "Unknown mode", {"matches": 0, "chests": 0})
            bucket["matches"] += 1
            bucket["chests"] += m["total"]
            containers.update(meta.get("containers") or {})
            unattributed += meta.get("unattributed", 0)
            for p in squad or []:
                if not p["me"]:
                    team_containers.update(p["containers"])
        rows.append({
            "id": m["id"], "when": m["started"], "seconds": m["seconds"], "count": m["total"],
            "broken": m["broken"], "mode": meta.get("mode") or ("Unknown mode" if meta else "Manual"),
            "types": match_types.get(m["id"], Counter()), "team": team,
            "ammo": (meta.get("containers") or {}).get("Ammo box", 0),
            "placement": meta.get("placement"), "players": meta.get("total_players"),
            "teammates": [name for name in (meta.get("teammates") or []) if name],
            "squad": squad, "mvp": _mvp(squad) if squad else None,
            "squad_total": sum(p["total"] for p in squad) if squad else 0,
            "unattributed": meta.get("unattributed", 0),
        })
    rows.sort(key=lambda row: row["when"], reverse=True)

    totals = [m["total"] for m in analyzed]
    replay_chests = sum(totals)
    playtime = sum(m["seconds"] for m in analyzed)
    team_total = sum(team_types.values())
    best_day = max(per_day.items(), key=lambda kv: kv[1]) if per_day else None
    streak_longest, streak_current = _streaks(per_day, today)
    month = today.replace(day=1)
    week = today - timedelta(days=today.weekday())
    last_week = week - timedelta(days=7)
    last_month = (month - DAY).replace(day=1)
    return {
        "today_date": today, "per_day": per_day,
        "all": sum(per_day.values()), "broken": broken, "types": types,
        "containers": containers, "modes": modes,
        "today": per_day[today], "today_prev": per_day[today - DAY],
        "week": _span(per_day, week, today), "week_prev": _span(per_day, last_week, last_week + (today - week)),
        "month": _span(per_day, month, today), "month_prev": _span(per_day, last_month, last_month + (today - month)),
        "session": sum(e.amount for e in events if session_start and e.when >= session_start),
        "matches": len(analyzed), "match_chests": replay_chests,
        "avg": replay_chests / len(analyzed) if analyzed else None,
        "median": statistics.median(totals) if totals else None,
        "best": max(totals) if totals else None, "worst": min(totals) if totals else None,
        "recent_totals": totals[-RECENT:],
        "playtime": playtime, "per_hour": replay_chests * 3600 / playtime if playtime else 0.0,
        "last": next((row for row in rows if row["id"] in analyzed_ids), None),
        "best_day": best_day if best_day and best_day[1] else None,
        "streak_longest": streak_longest, "streak_current": streak_current,
        "session_best": _longest_session(analyzed), "peak_hour": _peak_hour(events) if events else (0, None),
        "heat": heat, "heat_matches": heat_matches, "match_days": match_days,
        "team_total": team_total, "team_types": team_types,
        "team_opened": team_opened, "team_broken": team_broken, "team_containers": team_containers,
        "unattributed": unattributed, "board": board(rows),
        "older_matches": sum(1 for m in analyzed if "players" not in m["meta"]),
        "team_per_match": team_total / len(analyzed) if analyzed else None,
        "your_share": replay_chests / (replay_chests + team_total) if replay_chests + team_total else None,
        "player": analyzed[-1]["meta"].get("owner") if analyzed else None,
        "partial": sum(1 for m in analyzed if not m["meta"].get("complete", True)),
        "match_rows": rows,
    }
