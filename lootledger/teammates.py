"""Teammates page: everyone who played with you, merged across matches, with records and a profile per person."""
from collections import Counter
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import stats, theme
from .prefs import RANGES, number, short_date, when
from .store import Store
from .stats import tag
from .widgets import (SeriesChart, autofit, bar_rows, clear_layout, fill, fit_columns, icon_button, label,
                      make_table, shrinkable)

HEADERS = ("Player", "Matches", "Chests", "Per match", "Searched", "Broken", "Rare+", "Best")  # Rare+ = rare, relic or buried
EXPORT_FIELDS = ("name", "you", "bot", "matches", "chests", "per_match", "searched", "broken_open",
                 "rare_or_better", "best_match", "last_together")
RECORDS = (("most_chests", "Most chests"), ("best_match", "Best single match"), ("most_played", "Played most with"))


def matches(count):
    return f"{count} match{'' if count == 1 else 'es'}"


def people(count):
    return f"{count} person" if count == 1 else f"{count} people"


def cells(person, prefs):
    """Text for the numeric columns of one person's row."""
    return [number(person["matches"], prefs), number(person["total"], prefs), number(person["per_match"], prefs, 1),
            number(person["opened"], prefs), number(person["broken"], prefs), number(person["rare"], prefs),
            number(person["best"], prefs)]


def export_row(person):
    return {"name": person["name"], "you": person["me"], "bot": person["bot"], "matches": person["matches"],
            "chests": person["total"], "per_match": round(person["per_match"], 2), "searched": person["opened"],
            "broken_open": person["broken"], "rare_or_better": person["rare"], "best_match": person["best"],
            "last_together": person["last"].date().isoformat() if person["last"] else ""}


class PeopleModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.rows, self.prefs = [], None

    def reset_rows(self, rows, prefs):
        self.beginResetModel()
        self.rows, self.prefs = rows, prefs
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        person, column = self.rows[index.row()], index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return person["name"] + tag(person)
            return cells(person, self.prefs)[column - 1]
        if role == Qt.ItemDataRole.UserRole:
            return [person["name"].lower(), person["matches"], person["total"], person["per_match"], person["opened"],
                    person["broken"], person["rare"], person["best"]][column]
        if role == Qt.ItemDataRole.TextAlignmentRole and column:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class TeammatesPanel(QWidget):
    """Filters, records, a sortable table of everyone you played with, and a profile for the chosen person."""
    exported = Signal(str)

    def __init__(self, prefs):
        super().__init__()
        t = theme.CURRENT
        self.prefs, self.snap, self.rows, self.ranked = prefs, None, [], []
        self.selected, self._busy = None, False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(t.sp["m"])

        bar = QHBoxLayout()
        bar.setSpacing(t.sp["s"])
        self.mode, self.range, self.minimum = QComboBox(), QComboBox(), QSpinBox()
        for days in RANGES:
            self.range.addItem("All time" if days == 0 else f"Last {days} days", days)
        self.range.setCurrentIndex(max(0, self.range.findData(prefs.default_range)))
        self.minimum.setRange(0, 999)
        self.minimum.setSpecialValueText("Any number of matches")
        self.minimum.setPrefix("At least ")
        shrinkable(self.mode, self.range, self.minimum)
        for widget in (self.mode, self.range, self.minimum):
            bar.addWidget(widget)
        self.mode.currentIndexChanged.connect(self.apply)
        self.range.currentIndexChanged.connect(self.apply)
        self.minimum.valueChanged.connect(self.apply)
        bar.addStretch(1)
        for icon, tip, suffix in (("table_view", "Export as CSV", ".csv"), ("data_object", "Export as JSON", ".json")):
            bar.addWidget(icon_button(icon, tip, lambda s=suffix: self.export(s)))
        outer.addLayout(bar)

        self.count = label("", "muted")
        self.note = label("", "muted")
        self.note.setWordWrap(True)
        outer.addWidget(self.count)
        outer.addWidget(self.note)

        records = QFrame()
        records.setObjectName("panel")
        records_row = QHBoxLayout(records)
        records_row.setContentsMargins(t.sp["m"], t.sp["m"], t.sp["m"], t.sp["m"])
        self.record_labels = {}
        for key, title in RECORDS:
            box = QVBoxLayout()
            value, detail = label("–", "value"), label("", "muted")
            value.setWordWrap(True)
            detail.setWordWrap(True)
            box.addWidget(label(title, "muted"))
            box.addWidget(value)
            box.addWidget(detail)
            box.addStretch()
            records_row.addLayout(box, 1)
            self.record_labels[key] = (value, detail)
        outer.addWidget(records)

        table_panel = QFrame()
        table_panel.setObjectName("panel")
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(t.sp["s"], t.sp["s"], t.sp["s"], t.sp["s"])
        self.model = PeopleModel()
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.table = make_table()
        self.table.setModel(self.proxy)
        self.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        self.table.selectionModel().currentRowChanged.connect(self.on_select)
        table_layout.addWidget(self.table)
        outer.addWidget(table_panel, 1)

        self.profile = QFrame()
        self.profile.setObjectName("panel")
        self.profile.hide()
        head = QVBoxLayout(self.profile)
        head.setContentsMargins(t.sp["l"], t.sp["l"], t.sp["l"], t.sp["l"])
        self.p_title, self.p_sub = label("", "value"), label("", "muted")
        self.p_stats = label("", "muted")
        self.p_stats.setWordWrap(True)
        head.addWidget(self.p_title)
        head.addWidget(self.p_sub)
        head.addWidget(self.p_stats)
        body = QHBoxLayout()
        body.setSpacing(t.sp["xl"])
        left = QVBoxLayout()
        left.addWidget(label("Chest types", "cardTitle"))
        self.p_types = QGridLayout()
        left.addLayout(self.p_types)
        left.addStretch()
        right = QVBoxLayout()
        right.addWidget(label("Chests per match", "cardTitle"))
        self.chart = SeriesChart("Matches together will chart here")
        right.addWidget(self.chart, 1)
        self.p_matches = QTableWidget(0, 4)
        self.p_matches.setHorizontalHeaderLabels(["When", "Mode", "Their chests", "Your chests"])
        self.p_matches.verticalHeader().hide()
        self.p_matches.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.p_matches.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.p_matches.setMinimumHeight(140)
        autofit(self.p_matches)
        right.addWidget(self.p_matches)
        body.addLayout(left, 1)
        body.addLayout(right, 2)
        head.addLayout(body)
        outer.addWidget(self.profile)

    def apply(self, *_):
        if self.snap is not None:
            self.refresh(self.snap, self.prefs)

    def refresh(self, snap, prefs):
        self.snap, self.prefs = snap, prefs
        self._busy = True
        fill(self.mode, [("All modes", None)] + [(name, name) for name in sorted(snap["modes"])])
        mode, days, minimum = self.mode.currentData(), self.range.currentData(), self.minimum.value()
        since = snap["today_date"] - timedelta(days=days - 1) if days else None
        self.rows = [r for r in snap["match_rows"] if r["squad"] is not None
                     and (not mode or r["mode"] == mode) and (since is None or r["when"].date() >= since)]
        self.ranked = [p for p in stats.board(self.rows) if p["matches"] >= minimum]
        self.model.reset_rows(self.ranked, prefs)
        fit_columns(self.table)
        best = stats.records(self.ranked)
        for key, _ in RECORDS:
            value, detail = self.record_labels[key]
            person = best[key]
            if person is None:
                value.setText("–")
                detail.setText("No teammates in this view")
            elif key == "most_chests":
                value.setText(f"{person['name']} · {number(person['total'], prefs)} chests")
                detail.setText(f"in {matches(person['matches'])}")
            elif key == "best_match":
                value.setText(f"{person['name']} · {number(person['best'], prefs)} in one match")
                detail.setText(when(person["best_when"], prefs) if person["best_when"] else "")
            else:
                value.setText(person["name"])
                detail.setText(f"{matches(person['matches'])} together")
        self.count.setText(f"{people(len(self.ranked))} across {matches(len(self.rows))} in this view")
        notes = []
        if snap["older_matches"]:
            notes.append(f"{snap['older_matches']} older matches have no per-player detail yet. They are read again "
                         "on the next scan while their replay files are still on disk.")
        notes.append(f"{number(snap['unattributed'], prefs)} chests were already open when your game first showed "
                     "them, so nobody is credited for them.")
        self.note.setText(" ".join(notes))
        self._busy = False
        self.reselect()

    def reselect(self):
        """Keep the same person selected when the rows are rebuilt; drop the profile if they are gone."""
        for position in range(self.proxy.rowCount()):
            index = self.proxy.index(position, 0)
            if self.model.rows[self.proxy.mapToSource(index).row()]["key"] == self.selected:
                self.table.selectRow(position)
                self.show_profile()
                return
        self.selected = None
        self.table.clearSelection()
        self.profile.hide()

    def on_select(self, current, previous):
        if self._busy:
            return
        if not current.isValid():
            self.selected = None
            self.profile.hide()
            return
        self.selected = self.model.rows[self.proxy.mapToSource(current).row()]["key"]
        self.show_profile()

    def show_profile(self):
        person = next((p for p in self.ranked if p["key"] == self.selected), None)
        if person is None:
            self.profile.hide()
            return
        prefs, history = self.prefs, stats.profile(self.rows, self.selected)
        span = (f" · first {short_date(history[0]['when'].date(), prefs)} · last {short_date(history[-1]['when'].date(), prefs)}"
                if history else "")
        self.p_title.setText(person["name"] + tag(person))
        self.p_sub.setText(f"{matches(person['matches'])} together{span}")
        self.p_stats.setText(
            f"{number(person['total'], prefs)} chests · {number(person['per_match'], prefs, 1)} per match · "
            f"{number(person['opened'], prefs)} searched · {number(person['broken'], prefs)} broken open · "
            f"{number(person['rare'], prefs)} rare or better · best {number(person['best'], prefs)}")
        self.chart.set_data([(short_date(h["when"].date(), prefs), h["total"]) for h in history],
                            prefs.chart_style, lambda v: number(v, prefs))
        types = Counter()
        for h in history:
            types.update(h["types"])
        clear_layout(self.p_types)
        bar_rows(self.p_types, [(name, n, number(n, prefs), theme.CURRENT.type_color(name))
                                for name, n in types.most_common()] or [("No chests", 0, "", None)])
        self.p_matches.setRowCount(0)
        for h in reversed(history):
            row = self.p_matches.rowCount()
            self.p_matches.insertRow(row)
            for column, text in enumerate((when(h["when"], prefs), h["mode"], number(h["total"], prefs),
                                           number(h["mine"], prefs))):
                self.p_matches.setItem(row, column, QTableWidgetItem(text))
        fit_columns(self.p_matches)
        self.profile.show()

    def export(self, suffix):
        name = "LootLedger-teammates" + suffix
        filter_text = "CSV (*.csv)" if suffix == ".csv" else "JSON (*.json)"
        path, _ = QFileDialog.getSaveFileName(self, "Export teammates", str(Path.home() / name), filter_text)
        if path:
            Store.export_rows(path, [export_row(p) for p in self.ranked], EXPORT_FIELDS)
            self.exported.emit(f"Exported {len(self.ranked)} people")
