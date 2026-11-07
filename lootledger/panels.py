"""Dashboard cards. Each card reads the shared snapshot and redraws itself on refresh."""
import time

from PySide6.QtCore import QDate, QEasingCurve, QPropertyAnimation, QVariantAnimation, Qt
from PySide6.QtWidgets import QDateEdit, QGraphicsOpacityEffect, QHBoxLayout, QGridLayout, QVBoxLayout

from . import features, stats, theme
from .prefs import duration, elapsed, number, short_date
from .widgets import (Card, Donut, Heatmap, Pulse, Ring, Segmented, SeriesChart, Sparkline, Timeline, bar_rows,
                      clear_layout, label, wrapped)

STAT_TITLES = {
    "all": ("All time", "all_inclusive"),
    "today": ("Today", "today"),
    "week": ("This week", "date_range"),
    "month": ("This month", "calendar_month"),
    "last": ("Last match", "sports_esports"),
    "avg": ("Chests per match", "query_stats"),
    "best": ("Best match", "emoji_events"),
    "per_hour": ("Chests per hour", "schedule"),
    "playtime": ("Time played", "timer"),
    "matches": ("Matches read", "list_alt"),
    "session": ("This session", "play_circle"),
}
TITLES = {
    "live": ("Current match", "sports_esports"),
    "trend": ("Chests over time", "trending_up"),
    "types": ("By chest type", "category"),
    "modes": ("By game mode", "tune"),
    "heat": ("When you open chests", "grid_on"),
    "records": ("Records", "workspace_premium"),
    "teammates": ("You and your team", "groups"),
    "broken": ("Searched vs broken open", "broken_image"),
    "health": ("Setup and replay health", "health_and_safety"),
    "sessions": ("Sessions", "timelapse"),
    "goals": ("Goals", "flag"),
    "trophies": ("Trophies", "emoji_events"),
    "compare": ("Compare periods", "compare_arrows"),
}
GRAINS = (("day", "Day"), ("week", "Week"), ("month", "Month"))
TREND_RANGES = (("7", "7d"), ("30", "30d"), ("90", "90d"), ("0", "All"))
CHART_STYLES = (("bar", "Bar"), ("line", "Line"), ("area", "Area"))


def widget_title(key):
    return STAT_TITLES[key[5:]][0] if key.startswith("stat:") else TITLES[key][0]


def stat_value(key, snap, prefs):
    """(value, decimals, detail, delta, sparkline) for one stat tile. Text values are shown unchanged."""
    recent = snap["recent_totals"]
    if key == "all":
        detail = f"{number(snap['broken'], prefs)} broken open" if snap["broken"] else "searched chests"
        return snap["all"], 0, detail, None, stats.last_days(snap, 14)
    if key == "today":
        return snap["today"], 0, "", (snap["today"], snap["today_prev"], "vs yesterday"), stats.last_days(snap, 14)
    if key == "week":
        return snap["week"], 0, "", (snap["week"], snap["week_prev"], "vs the same days last week"), stats.last_days(snap, 14)
    if key == "month":
        return snap["month"], 0, "", (snap["month"], snap["month_prev"], "vs the same days last month"), stats.last_days(snap, 14)
    if key == "session":
        return snap["session"], 0, "since LootLedger opened", None, stats.last_days(snap, 14)
    if key == "matches":
        return snap["matches"], 0, "replays read", None, recent
    if key == "last":
        last = snap["last"]
        if last is None:
            return "–", 0, "No match read yet", None, None
        place = f" · #{last['placement']}" if last["placement"] else ""
        return last["count"], 0, f"{last['mode']}{place}", None, recent
    if snap["matches"] == 0:
        return "–", 0, "Read a match to see this", None, None
    if key == "avg":
        return snap["avg"], 1, f"median {number(snap['median'], prefs, 1)}", None, recent
    if key == "best":
        return snap["best"], 0, f"lowest {number(snap['worst'], prefs)}", None, recent
    if key == "per_hour":
        return snap["per_hour"], 1, f"over {duration(snap['playtime'], prefs)}", None, recent
    if key == "playtime":
        return duration(snap["playtime"], prefs), 0, f"{snap['matches']} matches", None, recent
    raise KeyError(key)


class StatTile(Card):
    def __init__(self, key):
        super().__init__(*STAT_TITLES[key])
        self.stat = key
        self.shown, self.fmt = None, str
        self.value = label("–", "number")
        self.animation = QVariantAnimation(self)  # one per tile, reused for every change
        self.animation.setDuration(600)
        self.animation.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        self.animation.valueChanged.connect(lambda v: self.value.setText(self.fmt(float(v))))
        self.detail = label("", "muted")
        self.delta = label("", "muted")
        for widget in (self.detail, self.delta):
            widget.setWordWrap(True)
        for widget in (self.value, self.detail, self.delta):
            self.body.addWidget(widget)
        self.body.addStretch()
        self.spark = Sparkline()
        self.body.addWidget(self.spark)

    def refresh(self, ctx):
        value, decimals, detail, delta, spark = stat_value(self.stat, ctx.snap, ctx.prefs)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
        self.delta.setVisible(bool(delta))
        if delta:
            current, previous, text = delta
            diff = current - previous
            arrow = "▲ +" if diff > 0 else "▼ −" if diff < 0 else ""
            self.delta.setText(f"{arrow}{number(abs(diff), ctx.prefs)} {text}" if diff else f"No change {text}")
            color_key = "primary" if diff > 0 else "on_surface_variant"
            self.delta.setStyleSheet(f"color: {theme.CURRENT.c[color_key]};")
        self.spark.setVisible(bool(spark))
        if spark:
            self.spark.set_values(spark)
        self.show_value(value, decimals, ctx)

    def show_value(self, value, decimals, ctx):
        if isinstance(value, str):
            self.value.setText(value)
            self.shown = None
            return

        def text(v):
            return number(v, ctx.prefs, decimals)

        start = self.shown if isinstance(self.shown, (int, float)) else 0
        self.shown, self.fmt = value, text
        self.animation.stop()
        if theme.CURRENT.full_motion and start != value:
            self.animation.setStartValue(float(start))
            self.animation.setEndValue(float(value))  # ends exactly on the value: no extra 'finished' handler needed
            self.animation.start()
        else:
            self.value.setText(text(value))


LIVE_STATES = {"idle": ("Idle · Fortnite isn't running", "outline"), "waiting": ("Waiting for a match", "secondary"),
               "live": ("Live", "error"), "saving": ("Match over · reading the replay…", "tertiary"),
               "ended": ("Match counted", "primary")}
RARITY = ("Relic chest", "Buried chest", "Rare chest")  # rarest first: picks the "+N" flash colour


def days(count):
    return f"{count} day" if count == 1 else f"{count} days"


def clock(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def match_lines(row, prefs):
    """Plain-text breakdown of a finished match: your split, pace, types and teammates."""
    minutes = row["seconds"] / 60 if row["seconds"] else 0
    pace = f" · {number(row['count'] / minutes, prefs, 1)} per minute" if minutes else ""
    head = f"{row['mode']} · {number(row['count'] - row['broken'], prefs)} searched · {number(row['broken'], prefs)} broken open{pace}"
    types = " · ".join(f"{name} {number(count, prefs)}" for name, count in row["types"].most_common())
    mates = [p for p in row["squad"] or [] if not p["me"] and p["total"]]
    team = ("Teammates: " + " · ".join(f"{p['name']} {number(p['total'], prefs)}" for p in mates)) if mates else ""
    return head, "\n".join(part for part in (types, team) if part)


class LiveCard(Card):
    """The current match. While Fortnite records, the replay is encrypted, so the count arrives when it ends."""

    def __init__(self):
        super().__init__(*TITLES["live"], accent=True)
        head = QHBoxLayout()
        head.setSpacing(theme.CURRENT.sp["s"])
        self.dot = Pulse()
        self.state = label("", "onAccent")
        head.addWidget(self.dot)
        head.addWidget(self.state, 1)
        self.body.addLayout(head)
        row = QHBoxLayout()
        self.count = label("–", "onAccentNumber")
        self.pop = label("", "onAccentNumber")
        self.pop_fade = QGraphicsOpacityEffect(self.pop)
        self.pop.setGraphicsEffect(self.pop_fade)
        self.pop_fade.setOpacity(0)
        row.addWidget(self.count)
        row.addWidget(self.pop)
        row.addStretch()
        self.body.addLayout(row)
        self.line, self.detail = label("", "onAccent"), label("", "onAccent")
        for widget in (self.line, self.detail):
            widget.setWordWrap(True)
            self.body.addWidget(widget)
        self.timeline = Timeline("")
        self.body.addWidget(self.timeline)
        self.body.addStretch()
        self.counter = QVariantAnimation(self)
        self.counter.setDuration(900)
        self.counter.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        self.counter.valueChanged.connect(lambda v: self.count.setText(str(round(v))))
        self.fade = QPropertyAnimation(self.pop_fade, b"opacity", self)
        self.fade.setDuration(1800)
        self.fade.setKeyValueAt(.15, 1.0)
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(0.0)
        self.announced = None

    def refresh(self, ctx):
        track = getattr(ctx, "track", None) or {"state": "idle", "elapsed": None, "recorded": 0, "locked": False}
        state = track["state"]
        text, color = LIVE_STATES[state]
        self.dot.set_color(theme.CURRENT.c[color], state == "live")
        prefs, row = ctx.prefs, getattr(ctx, "ended", None)
        if state == "live" and track["elapsed"] is not None:
            text += f" · {clock(track['elapsed'])}"
        self.state.setText(text)
        self.timeline.setVisible(state in ("live", "ended"))
        if state == "live" and ctx.live and not track["locked"]:
            self.count.setText(number(ctx.live["count"], prefs))  # only if Fortnite leaves the replay readable
            self.line.setText(f"{ctx.live['mode']} · updates every ~20 s, when Fortnite saves the replay")
            self.detail.setText("")
            self.timeline.set_marks([], max(track["recorded"], 1))
        elif state == "live":
            self.count.setText("…")
            self.line.setText("Chests appear when the match ends. Fortnite encrypts the replay while it records.")
            self.detail.setText(f"Replay saved up to {clock(track['recorded'])} · Fortnite saves about every 20 s")
            self.timeline.set_marks([], max(track["elapsed"] or 0, track["recorded"], 1), saved=track["recorded"])
        elif state == "ended" and row:
            self.line.setText(match_lines(row, prefs)[0])
            self.detail.setText(match_lines(row, prefs)[1])
            self.timeline.set_marks(getattr(ctx, "ended_marks", []), row["seconds"])
            if self.announced != row["id"]:
                self.announced = row["id"]
                self.celebrate(row, theme.CURRENT.full_motion)
            else:
                self.count.setText(number(row["count"], prefs))
        else:
            self.count.setText("…" if state == "saving" else "–")
            self.line.setText("Reading the finished replay." if state == "saving" else
                              "Finished matches are added automatically. Fortnite must have Record Replays on.")
            self.detail.setText("")
        if self.accessibleDescription() != text:
            self.setAccessibleDescription(text)  # screen readers hear state changes, not every update

    def celebrate(self, row, motion):
        """Count up to the match total, then a '+N' that fades, tinted by the rarest chest in the match."""
        rare = next((name for name in RARITY if row["types"].get(name)), None)
        tint = theme.CURRENT.type_color(rare) if rare else theme.CURRENT.c["on_primary_container"]
        self.pop.setText(f"+{row['count']}")
        self.pop.setStyleSheet(f"color: {tint};")
        self.setAccessibleDescription(f"Match counted: {row['count']} chests")
        if not motion:
            self.count.setText(str(row["count"]))
            self.pop_fade.setOpacity(0)
            return
        self.counter.stop()
        self.counter.setStartValue(0.0)
        self.counter.setEndValue(float(row["count"]))
        self.counter.start()
        self.fade.stop()
        self.fade.start()


class TrendCard(Card):
    def __init__(self, prefs, set_pref):
        super().__init__(*TITLES["trend"])
        self.days, self.grain, self.set_pref = prefs.default_range, "day", set_pref
        self._ctx = None
        controls = QHBoxLayout()
        self.range_seg = Segmented(TREND_RANGES, str(self.days), "Date range")
        self.range_seg.changed.connect(lambda key: self._set("days", int(key)))
        self.grain_seg = Segmented(GRAINS, self.grain, "Group by")
        self.grain_seg.changed.connect(lambda key: self._set("grain", key))
        controls.addWidget(self.range_seg)
        controls.addWidget(self.grain_seg)
        controls.addStretch()
        self.body.addLayout(controls)
        self.chart = SeriesChart("No chests in this range yet")
        self.body.addWidget(self.chart, 1)
        footer = QHBoxLayout()
        self.caption = label("", "muted")
        footer.addWidget(self.caption, 1)
        self.style_seg = Segmented(CHART_STYLES, prefs.chart_style, "Chart style")
        self.style_seg.changed.connect(lambda key: self.set_pref("chart_style", key))
        footer.addWidget(self.style_seg)
        self.body.addLayout(footer)

    def _set(self, name, value):
        setattr(self, name, value)
        self._redraw()

    def refresh(self, ctx):
        self._ctx = ctx
        self._redraw()

    def _redraw(self):
        ctx = self._ctx
        if ctx is None:
            return
        points = stats.trend(ctx.snap, self.grain, self.days)
        formatted = {"day": short_date, "week": short_date}.get(self.grain)
        labels = [(formatted(day, ctx.prefs) if formatted else day.strftime("%b %Y"), value) for day, value in points]
        self.chart.set_data(labels, ctx.prefs.chart_style, lambda v: number(v, ctx.prefs))
        total = sum(value for _, value in points)
        self.caption.setText(f"{number(total, ctx.prefs)} chests in this range")


class TypesCard(Card):
    def __init__(self):
        super().__init__(*TITLES["types"])
        row = QHBoxLayout()
        self.donut = Donut()
        row.addWidget(self.donut)
        self.table = QGridLayout()
        self.table.setHorizontalSpacing(theme.CURRENT.sp["m"])
        row.addLayout(self.table, 1)
        self.body.addLayout(row)
        self.note = label("", "muted")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)
        self.body.addStretch()

    def refresh(self, ctx):
        snap, prefs = ctx.snap, ctx.prefs
        clear_layout(self.table)
        types = snap["types"].most_common()
        self.donut.set_slices([(name, value, theme.CURRENT.type_color(name)) for name, value in types if value],
                              number(snap["all"], prefs), "chests")
        # Rows cover every type either side opened, so the teammate column always adds up to its total.
        names = [name for name, _ in types] + sorted(set(snap["team_types"]) - set(snap["types"]))
        for column, text in enumerate(("", "Type", "You", "Teammates*")):
            self.table.addWidget(label(text, "cardTitle"), 0, column)
        for index, name in enumerate(names, 1):
            dot = label("●")
            dot.setStyleSheet(f"color: {theme.CURRENT.type_color(name)};")
            dot.setAccessibleName(name)
            self.table.addWidget(dot, index, 0)
            self.table.addWidget(label(name), index, 1)
            self.table.addWidget(label(number(snap["types"].get(name, 0), prefs), "value"), index, 2)
            self.table.addWidget(label(number(snap["team_types"].get(name, 0), prefs), "muted"), index, 3)
        if names:
            self.table.addWidget(label("Total", "cardTitle"), len(names) + 1, 1)
            self.table.addWidget(label(number(snap["all"], prefs), "value"), len(names) + 1, 2)
            self.table.addWidget(label(number(snap["team_total"], prefs), "muted"), len(names) + 1, 3)
        else:
            self.table.addWidget(label("No chests yet", "muted"), 1, 1, 1, 3)
        self.table.setColumnStretch(1, 1)
        self.note.setText("*Only chests your replays recorded. Details on the Teammates page.")


class ModesCard(Card):
    def __init__(self):
        super().__init__(*TITLES["modes"])
        self.rows = QGridLayout()
        self.body.addLayout(self.rows)
        self.body.addStretch()

    def refresh(self, ctx):
        clear_layout(self.rows)
        modes = sorted(ctx.snap["modes"].items(), key=lambda kv: -kv[1]["chests"])[:8]
        if not modes:
            self.rows.addWidget(label("Read a match to see your modes", "muted"), 0, 0)
            return
        rows = [(name, info["chests"], f"{number(info['chests'], ctx.prefs)} · {info['matches']} "
                 f"match{'es' if info['matches'] != 1 else ''}", None) for name, info in modes]
        bar_rows(self.rows, rows)


class HeatCard(Card):
    def __init__(self):
        super().__init__(*TITLES["heat"])
        self.heat = Heatmap()
        self.body.addWidget(self.heat, 1)
        self.body.addWidget(label("Local time · darker means more chests", "muted"))

    def refresh(self, ctx):
        self.heat.set_grid(ctx.snap["heat"], lambda v: number(v, ctx.prefs))


class RecordsCard(Card):
    def __init__(self):
        super().__init__(*TITLES["records"])
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(theme.CURRENT.sp["m"])
        self.body.addLayout(self.grid)
        self.body.addStretch()

    def refresh(self, ctx):
        snap, prefs = ctx.snap, ctx.prefs
        clear_layout(self.grid)
        items = []
        if snap["best"] is not None:
            items.append(("Best match", f"{number(snap['best'], prefs)} chests"))
        if snap["best_day"]:
            day, count = snap["best_day"]
            items.append(("Best day", f"{number(count, prefs)} · {short_date(day, prefs)}"))
        if snap["session_best"]:
            session = snap["session_best"]
            length = (session["end"] - session["start"]).total_seconds()
            items.append(("Longest session", f"{duration(length, prefs)} · {number(session['chests'], prefs)} chests"))
        if snap["peak_hour"][0]:
            items.append(("Most in one hour", number(snap["peak_hour"][0], prefs)))
        items.append(("Longest daily streak", days(snap["streak_longest"])))
        items.append(("Current streak", days(snap["streak_current"])))
        for index, (name, value) in enumerate(items):
            value_label = label(value, "value")
            value_label.setWordWrap(True)
            self.grid.addWidget(wrapped(label(name, "muted")), index, 0)
            self.grid.addWidget(value_label, index, 1)
        self.grid.setColumnStretch(1, 1)


class TeamCard(Card):
    def __init__(self):
        super().__init__(*TITLES["teammates"])
        self.rows = QGridLayout()
        self.body.addLayout(self.rows)
        self.note = label("", "muted")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)
        self.body.addStretch()

    def refresh(self, ctx):
        snap, prefs = ctx.snap, ctx.prefs
        clear_layout(self.rows)
        if not snap["matches"]:
            self.rows.addWidget(label("Read a match with teammates to compare.", "muted"), 0, 0)
            self.note.setText("")
            return
        you, team = snap["match_chests"], snap["team_total"]
        mates = [p for p in snap["board"] if not p["me"] and not p["unranked"]][:3]
        bar_rows(self.rows, [
            ("You", you, f"{number(you, prefs)} · {number(snap['avg'], prefs, 1)} per match", None),
            ("Teammates", team, f"{number(team, prefs)} · {number(snap['team_per_match'] or 0, prefs, 1)} per match", None),
        ] + [(p["name"], p["total"], f"{number(p['total'], prefs)} in {p['matches']} "
              f"match{'es' if p['matches'] != 1 else ''}", None) for p in mates])
        share = snap["your_share"]
        self.note.setText((f"You opened {share:.0%} of the chests your replays recorded. " if share is not None else "")
                          + "Teammate counts only include chests your replays recorded. Full squad breakdown: Teammates page.")


class BrokenCard(Card):
    def __init__(self):
        super().__init__(*TITLES["broken"])
        self.rows = QGridLayout()
        self.body.addLayout(self.rows)
        self.extra = label("", "muted")
        self.extra.setWordWrap(True)
        self.body.addWidget(self.extra)
        self.body.addStretch()

    def refresh(self, ctx):
        snap, prefs = ctx.snap, ctx.prefs
        clear_layout(self.rows)
        for column, text in enumerate(("", "You", "Teammates*")):
            self.rows.addWidget(label(text, "cardTitle"), 0, column)
        searched = (snap["all"] - snap["broken"], snap["team_opened"])
        broken = (snap["broken"], snap["team_broken"])
        total = (searched[0] + broken[0], searched[1] + broken[1])
        for row, (name, pair) in enumerate((("Searched", searched), ("Broken open", broken), ("Total", total)), 1):
            self.rows.addWidget(wrapped(label(name, "cardTitle" if name == "Total" else "muted")), row, 0)
            self.rows.addWidget(label(number(pair[0], prefs), "value"), row, 1)
            self.rows.addWidget(label(number(pair[1], prefs), "value"), row, 2)
        self.rows.setColumnStretch(0, 1)
        ammo = sorted(set(snap["containers"]) | set(snap["team_containers"]))
        notes = []
        if ammo:
            notes.append("Not counted as chests: " + " · ".join(
                f"{name}, you {number(snap['containers'].get(name, 0), prefs)} / teammates "
                f"{number(snap['team_containers'].get(name, 0), prefs)}" for name in ammo))
        notes.append("*Teammates: only chests your replays recorded. Broken open means the chest was destroyed "
                     "before anyone searched it.")
        self.extra.setText("\n".join(notes))


class HealthCard(Card):
    """First-run checklist with the fix for each problem, and how replay reading is going."""

    def __init__(self):
        super().__init__(*TITLES["health"])
        self.rows = QGridLayout()
        self.rows.setHorizontalSpacing(theme.CURRENT.sp["s"])
        self.body.addLayout(self.rows)
        self.facts = wrapped(label("", "muted"))
        self.body.addWidget(self.facts)
        self.body.addStretch()

    def refresh(self, ctx):
        h, prefs = getattr(ctx, "health", None), ctx.prefs
        clear_layout(self.rows)
        if not h:
            return
        blocked = False
        for index, (name, ok, fix) in enumerate(h["checks"]):
            icon = label("check_circle" if ok else "error", "icon")
            icon.setStyleSheet(f"color: {theme.CURRENT.c['primary' if ok else 'error']};")
            icon.setAccessibleName("Done" if ok else "Needs attention")
            text = QVBoxLayout()
            text.addWidget(wrapped(label(name)))
            if not ok:  # later checks depend on earlier ones: one fix at a time
                text.addWidget(wrapped(label("Waiting on the step above." if blocked else "Fix it: " + fix, "muted")))
                blocked = True
            self.rows.addWidget(icon, index, 0, Qt.AlignmentFlag.AlignTop)
            self.rows.addLayout(text, index, 1)
        self.rows.setColumnStretch(1, 1)
        checked = ctx.last_scan.strftime("%H:%M:%S") if getattr(ctx, "last_scan", None) else "not yet"
        newest = f"newest {elapsed(time.time() - h['newest'])} ago" if h["newest"] else "none yet"
        self.facts.setText(f"{ctx.watching} · last check {checked}\n"
                           f"{number(h['replays'], prefs)} replays in the folder ({newest}) · "
                           f"{number(h['read'], prefs)} read · {number(h['unreadable'], prefs)} could not be read")


class SessionsCard(Card):
    """The latest play session (matches less than 30 minutes apart) against the one before and the average."""

    def __init__(self):
        super().__init__(*TITLES["sessions"])
        self.value = label("–", "number")
        self.line = wrapped(label("", "muted"))
        self.compare = wrapped(label("", "muted"))
        self.rows = QGridLayout()
        for widget in (self.value, self.line, self.compare):
            self.body.addWidget(widget)
        self.body.addLayout(self.rows)
        self.body.addStretch()

    def refresh(self, ctx):
        prefs = ctx.prefs
        found = features.sessions(ctx.snap["match_rows"])
        clear_layout(self.rows)
        if not found:
            self.value.setText("–")
            self.line.setText("Play a few matches: matches less than 30 minutes apart make a session.")
            self.compare.setText("")
            return
        last = found[0]
        self.value.setText(number(last["chests"], prefs))
        self.line.setText(f"Latest session · {short_date(last['start'].date(), prefs)} · {last['matches']} "
                          f"match{'es' if last['matches'] != 1 else ''} · {duration(last['seconds'], prefs)} · "
                          f"{number(last['per_hour'], prefs, 1)} chests per hour")
        average = sum(s["per_hour"] for s in found) / len(found)
        parts = [f"Average session: {number(average, prefs, 1)} per hour"]
        if len(found) > 1:
            parts.insert(0, f"Previous: {number(found[1]['chests'], prefs)} chests, "
                            f"{number(found[1]['per_hour'], prefs, 1)} per hour")
        self.compare.setText(" · ".join(parts))
        bar_rows(self.rows, [(short_date(s["start"].date(), prefs), s["chests"], number(s["chests"], prefs), None)
                             for s in found[:5]])


class GoalsCard(Card):
    """Daily and weekly goals as rings, and the day streak."""

    def __init__(self):
        super().__init__(*TITLES["goals"])
        row = QHBoxLayout()
        self.rings = [Ring(), Ring()]
        for ring in self.rings:
            row.addWidget(ring)
        self.body.addLayout(row)
        self.line = wrapped(label("", "muted"))
        self.body.addWidget(self.line)
        self.body.addStretch()

    def refresh(self, ctx):
        prefs = ctx.prefs
        g = features.goals(ctx.snap, prefs.goal_daily, prefs.goal_weekly)
        for ring, goal in zip(self.rings, g["goals"] + [None, None]):
            ring.setVisible(goal is not None)
            if goal:
                ring.set_value(goal["share"], f"{number(goal['done'], prefs)}/{number(goal['target'], prefs)}",
                               goal["name"] + (" · done" if goal["reached"] else ""))
        streak = f"Streak: {g['streak']} day{'s' if g['streak'] != 1 else ''} in a row with chests."
        self.line.setText(streak if g["goals"] else streak + " Set a daily or weekly goal in Settings → Goals.")


class TrophiesCard(Card):
    """Milestones, unlocked ones in colour. The window announces new ones, once."""

    def __init__(self):
        super().__init__(*TITLES["trophies"])
        self.count = label("", "muted")
        self.body.addWidget(self.count)
        self.grid = QGridLayout()
        self.grid.setSpacing(theme.CURRENT.sp["s"])
        self.body.addLayout(self.grid)
        self.body.addStretch()

    def refresh(self, ctx):
        items = features.achievements(ctx.snap)
        clear_layout(self.grid)
        self.count.setText(f"{sum(i['unlocked'] for i in items)} of {len(items)} unlocked")
        columns = 4 if self.span > 1 else 2
        for index, item in enumerate(items):
            box = QVBoxLayout()
            icon = label("emoji_events", "icon")
            icon.setStyleSheet(f"color: {theme.CURRENT.c['primary' if item['unlocked'] else 'outline_variant']};"
                               f"font-size: {theme.CURRENT.px['headline']}px;")
            name = wrapped(label(item["title"], "value" if item["unlocked"] else "muted"))
            name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            state = "unlocked" if item["unlocked"] else "locked"
            for widget in (icon, name):
                widget.setToolTip(f"{item['detail']} · {state}")
                widget.setAccessibleName(f"{item['title']}, {state}: {item['detail']}")
                box.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
            self.grid.addLayout(box, index // columns, index % columns)


class CompareCard(Card):
    """Any two date ranges side by side, with the change."""

    def __init__(self):
        super().__init__(*TITLES["compare"])
        today = QDate.currentDate()
        monday = today.addDays(1 - today.dayOfWeek())
        self.edits, self.ctx = [], None
        for name, start, end in (("First", monday.addDays(-7), monday.addDays(-1)), ("Second", monday, today)):
            row = QHBoxLayout()
            row.addWidget(label(name, "muted"))
            for value, tip in ((start, "from"), (end, "to")):
                edit = QDateEdit(value)
                edit.setCalendarPopup(True)
                edit.setAccessibleName(f"{name} period {tip}")
                edit.dateChanged.connect(lambda *_: self.redraw())
                row.addWidget(edit)
                self.edits.append(edit)
            row.addStretch()
            self.body.addLayout(row)
        self.table = QGridLayout()
        self.table.setHorizontalSpacing(theme.CURRENT.sp["l"])
        self.body.addLayout(self.table)
        self.body.addStretch()

    def refresh(self, ctx):
        self.ctx = ctx
        self.redraw()

    def redraw(self):
        if self.ctx is None:
            return
        prefs = self.ctx.prefs
        dates = [edit.date().toPython() for edit in self.edits]
        rows = features.compare(self.ctx.snap, (dates[0], dates[1]), (dates[2], dates[3]))
        clear_layout(self.table)
        for column, text in enumerate(("", "First", "Second", "Change")):
            self.table.addWidget(label(text, "cardTitle"), 0, column)
        for index, (name, a, b, change) in enumerate(rows, 1):
            decimals = 1 if name == "Chests per match" else 0
            sign = "+" if change > 0 else "−" if change < 0 else "±"
            self.table.addWidget(wrapped(label(name, "muted")), index, 0)
            self.table.addWidget(label(number(a, prefs, decimals), "value"), index, 1)
            self.table.addWidget(label(number(b, prefs, decimals), "value"), index, 2)
            delta = label(f"{sign}{number(abs(change), prefs, decimals)}", "value")
            delta.setStyleSheet(f"color: {theme.CURRENT.c['primary' if change > 0 else 'on_surface_variant']};")
            self.table.addWidget(delta, index, 3)
        self.table.setColumnStretch(0, 1)


def make_panel(key, prefs, set_pref):
    if key == "live":
        return LiveCard()
    if key.startswith("stat:"):
        return StatTile(key[5:])
    if key == "trend":
        return TrendCard(prefs, set_pref)
    return {"types": TypesCard, "modes": ModesCard, "heat": HeatCard, "records": RecordsCard,
            "teammates": TeamCard, "broken": BrokenCard, "health": HealthCard, "sessions": SessionsCard,
            "goals": GoalsCard, "trophies": TrophiesCard, "compare": CompareCard}[key]()
