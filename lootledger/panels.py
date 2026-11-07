"""Dashboard cards. Each card reads the shared snapshot and redraws itself on refresh."""
from PySide6.QtCore import QEasingCurve, QVariantAnimation
from PySide6.QtWidgets import QHBoxLayout, QGridLayout

from . import stats, theme
from .prefs import duration, elapsed, number, short_date
from .widgets import Card, Donut, Heatmap, Segmented, SeriesChart, Sparkline, bar_rows, clear_layout, label

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
        self.shown, self.animation = None, None
        self.value = label("–", "number")
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
        self.shown = value
        if ctx.motion and start != value:
            if self.animation:
                self.animation.stop()
            self.animation = QVariantAnimation(self)
            self.animation.setStartValue(float(start))
            self.animation.setEndValue(float(value))
            self.animation.setDuration(600)
            self.animation.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
            self.animation.valueChanged.connect(lambda v: self.value.setText(text(float(v))))
            self.animation.finished.connect(lambda: self.value.setText(text(value)))
            self.animation.start()
        else:
            self.value.setText(text(value))


class LiveCard(Card):
    def __init__(self):
        super().__init__(*TITLES["live"], accent=True)
        self.count = label("–", "onAccentNumber")
        self.line = label("", "onAccent")
        self.line.setWordWrap(True)
        self.body.addWidget(self.count)
        self.body.addWidget(self.line)
        self.body.addStretch()

    def refresh(self, ctx):
        live = ctx.live
        if live is None:
            self.count.setText("–")
            self.line.setText("No match in progress. Finished matches are added automatically.")
            return
        self.count.setText(number(live["count"], ctx.prefs))
        parts = [live["mode"]]
        if live["elapsed"] is not None:
            parts.append(f"running {elapsed(live['elapsed'])}")
        self.line.setText(" · ".join(parts))


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
        self.body.addStretch()

    def refresh(self, ctx):
        snap, prefs = ctx.snap, ctx.prefs
        clear_layout(self.table)
        types = snap["types"].most_common()
        self.donut.set_slices([(name, value, theme.CURRENT.type_color(name)) for name, value in types if value],
                              number(snap["all"], prefs), "chests")
        for column, text in enumerate(("", "Type", "You", "Teammates")):
            self.table.addWidget(label(text, "cardTitle"), 0, column)
        for index, (name, value) in enumerate(types, 1):
            dot = label("●")
            dot.setStyleSheet(f"color: {theme.CURRENT.type_color(name)};")
            dot.setAccessibleName(name)
            self.table.addWidget(dot, index, 0)
            self.table.addWidget(label(name), index, 1)
            self.table.addWidget(label(number(value, prefs), "value"), index, 2)
            self.table.addWidget(label(number(snap["team_types"].get(name, 0), prefs), "muted"), index, 3)
        if types:
            self.table.addWidget(label("Total", "cardTitle"), len(types) + 1, 1)
            self.table.addWidget(label(number(snap["all"], prefs), "value"), len(types) + 1, 2)
            self.table.addWidget(label(number(snap["team_total"], prefs), "muted"), len(types) + 1, 3)
        else:
            self.table.addWidget(label("No chests yet", "muted"), 1, 1, 1, 3)
        self.table.setColumnStretch(1, 1)


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
        items.append(("Longest daily streak", f"{snap['streak_longest']} days"))
        items.append(("Current streak", f"{snap['streak_current']} days"))
        for index, (name, value) in enumerate(items):
            value_label = label(value, "value")
            value_label.setWordWrap(True)
            self.grid.addWidget(label(name, "muted"), index, 0)
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
        bar_rows(self.rows, [
            ("You", you, f"{number(you, prefs)} · {number(snap['avg'], prefs, 1)} per match", None),
            ("Teammates", team, f"{number(team, prefs)} · {number(snap['team_per_match'] or 0, prefs, 1)} per match", None),
        ])
        share = snap["your_share"]
        self.note.setText((f"You opened {share:.0%} of the chests your replays recorded. " if share is not None else "")
                          + "Teammate counts only include chests your replays recorded.")


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
        searched = snap["all"] - snap["broken"]
        share = round(100 * snap["broken"] / snap["all"]) if snap["all"] else 0
        bar_rows(self.rows, [
            ("Searched", searched, number(searched, prefs), None),
            ("Broken open", snap["broken"], f"{number(snap['broken'], prefs)} · {share}%", theme.CURRENT.c["tertiary"]),
        ])
        others = [f"{name.lower()}s {number(count, prefs)}" for name, count in snap["containers"].items()]
        self.extra.setText("Not counted as chests: " + ", ".join(others) if others else
                           "Broken open means the chest was destroyed before anyone searched it.")


def make_panel(key, prefs, set_pref):
    if key == "live":
        return LiveCard()
    if key.startswith("stat:"):
        return StatTile(key[5:])
    if key == "trend":
        return TrendCard(prefs, set_pref)
    return {"types": TypesCard, "modes": ModesCard, "heat": HeatCard, "records": RecordsCard,
            "teammates": TeamCard, "broken": BrokenCard}[key]()
