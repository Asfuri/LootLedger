from datetime import datetime, timedelta

from lootledger import stats
from lootledger.stats import Ev

NOW = datetime(2026, 11, 6, 15, 0).astimezone()  # a Friday, local time


def on(day_offset, hour=12, minute=0):
    """A local datetime `day_offset` days before NOW."""
    return (NOW - timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def at_date(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute).astimezone()


def event(when, amount=1, chest_type="Chest", source="replay", match_id="m1"):
    return Ev(when, amount, chest_type, source, match_id)


def match(match_id, started, seconds, total, mode="Build Squad", team=None, containers=None, broken=0):
    meta = {"mode": mode, "placement": 3, "team": team or {}, "containers": containers or {},
            "teammates": ["Friend"], "total_players": 80, "complete": True, "owner": "Player"}
    return {"id": match_id, "started": started, "seconds": seconds, "total": total, "broken": broken, "meta": meta}


def test_deltas_compare_the_same_days_in_the_previous_period():
    # Nov 6 is a Friday: this week is Mon Nov 2 - Fri Nov 6; last week's matching days are Oct 26 - Oct 30.
    events = [event(at_date(2026, 11, 6), 2), event(at_date(2026, 11, 5), 5), event(at_date(2026, 11, 2), 4),
              event(at_date(2026, 10, 30), 1), event(at_date(2026, 10, 27), 3), event(at_date(2026, 10, 3), 3)]
    snap = stats.compute(events, [], NOW)
    assert (snap["today"], snap["today_prev"]) == (2, 5)
    assert (snap["week"], snap["week_prev"]) == (11, 4)
    assert (snap["month"], snap["month_prev"]) == (11, 3)  # October 1-6 is the same span as this month so far
    assert snap["all"] == 2 + 5 + 4 + 1 + 3 + 3


def test_streaks_count_consecutive_days_and_the_current_run():
    days = [at_date(2026, 10, 30), at_date(2026, 10, 31), at_date(2026, 11, 1), at_date(2026, 11, 5), at_date(2026, 11, 6)]
    snap = stats.compute([event(day) for day in days], [], NOW)
    assert snap["streak_longest"] == 3
    assert snap["streak_current"] == 2


def test_current_streak_counts_from_yesterday_when_today_is_empty():
    snap = stats.compute([event(at_date(2026, 11, 4)), event(at_date(2026, 11, 5))], [], NOW)
    assert snap["streak_current"] == 2
    assert snap["today"] == 0


def test_series_includes_empty_periods_and_respects_grain():
    per_day = {at_date(2026, 11, 2).date(): 4, at_date(2026, 11, 6).date(): 2}
    days = stats.series(per_day, "day", at_date(2026, 11, 1).date(), at_date(2026, 11, 6).date())
    assert [value for _, value in days] == [0, 4, 0, 0, 0, 2]
    # Nov 1 is a Sunday, so its week starts on Mon Oct 26; the next week starts Mon Nov 2.
    weeks = stats.series(per_day, "week", at_date(2026, 11, 1).date(), at_date(2026, 11, 6).date())
    assert [value for _, value in weeks] == [0, 6]
    months = stats.series(per_day, "month", at_date(2026, 10, 20).date(), at_date(2026, 11, 6).date())
    assert [value for _, value in months] == [0, 6]


def test_trend_uses_the_range_and_all_time():
    snap = stats.compute([event(at_date(2026, 10, 1))], [], NOW)
    assert len(stats.trend(snap, "day", 7)) == 7
    assert len(stats.trend(snap, "day", 0)) == (NOW.date() - at_date(2026, 10, 1).date()).days + 1
    assert stats.last_days(snap, 3) == [0, 0, 0]


def test_peak_hour_is_a_rolling_hour():
    events = [event(at_date(2026, 11, 6, 10, 0), 5), event(at_date(2026, 11, 6, 10, 30), 4),
              event(at_date(2026, 11, 6, 10, 59), 3), event(at_date(2026, 11, 6, 13, 0), 10)]
    count, when = stats.compute(events, [], NOW)["peak_hour"]
    assert count == 12
    assert when == at_date(2026, 11, 6, 10, 59)


def test_longest_session_groups_matches_separated_by_short_gaps():
    matches = [match("a", at_date(2026, 11, 6, 10, 0), 30 * 60, 4),
               match("b", at_date(2026, 11, 6, 10, 40), 30 * 60, 6),
               match("c", at_date(2026, 11, 6, 14, 0), 20 * 60, 9)]
    session = stats.compute([], matches, NOW)["session_best"]
    assert session["matches"] == 2 and session["chests"] == 10
    assert session["start"] == at_date(2026, 11, 6, 10, 0)
    assert session["end"] == at_date(2026, 11, 6, 11, 10)


def test_team_share_follows_the_broken_open_setting():
    team = {"Chest": {"opened": 5, "broken": 1}}
    matches = [match("m1", at_date(2026, 11, 6, 10, 0), 600, 10, team=team, containers={"Ammo box": 3})]
    events = [event(at_date(2026, 11, 6, 10, 5), 10, match_id="m1")]
    with_broken = stats.compute(events, matches, NOW, include_broken=True)
    assert with_broken["team_total"] == 6
    assert with_broken["your_share"] == 10 / 16
    without = stats.compute(events, matches, NOW, include_broken=False)
    assert without["team_total"] == 5
    assert with_broken["containers"] == {"Ammo box": 3}


def test_modes_heatmap_and_match_rows():
    matches = [match("m1", at_date(2026, 11, 6, 10, 0), 600, 10, mode="Build Duo"),
               match("m2", at_date(2026, 11, 5, 20, 0), 900, 20, mode="Zero Build Squad")]
    events = [event(at_date(2026, 11, 6, 10, 5), 10, match_id="m1"), event(at_date(2026, 11, 5, 20, 5), 20, match_id="m2")]
    snap = stats.compute(events, matches, NOW)
    assert snap["modes"] == {"Build Duo": {"matches": 1, "chests": 10}, "Zero Build Squad": {"matches": 1, "chests": 20}}
    assert snap["heat"][at_date(2026, 11, 6).weekday()][10] == 10
    assert snap["match_rows"][0]["id"] == "m1" and snap["match_rows"][0]["types"]["Chest"] == 10
    assert snap["avg"] == 15 and snap["median"] == 15 and snap["best"] == 20 and snap["worst"] == 10


def test_empty_data_gives_safe_values():
    snap = stats.compute([], [], NOW)
    assert snap["avg"] is None and snap["median"] is None and snap["best"] is None
    assert snap["per_hour"] == 0.0 and snap["peak_hour"] == (0, None)
    assert snap["best_day"] is None and snap["session_best"] is None and snap["last"] is None
    assert snap["match_rows"] == [] and snap["your_share"] is None and snap["recent_totals"] == []
    assert (snap["streak_longest"], snap["streak_current"]) == (0, 0)
