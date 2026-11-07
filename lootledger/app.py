"""LootLedger desktop window: navigation rail, pages, dashboard customization and actions."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from types import SimpleNamespace
import sys
import threading
import time

from PySide6.QtCore import (QAbstractTableModel, QEasingCurve, QModelIndex, QObject, QPropertyAnimation, QRectF,
                            QSortFilterProxyModel, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import replay_reader, stats, theme
from .config import Config, data_dir
from .hotkeys import Hotkeys
from .panels import STAT_TITLES, make_panel, widget_title
from .prefs import RANGES, WIDGETS, Prefs, default_layout, elapsed, number, when
from .store import EVENT_FIELDS, Store
from .teammates import TeammatesPanel
from .widgets import (Card, DashGrid, Segmented, Snackbar, Switch, Timeline, bar_rows, clear_layout, fill, icon_button,
                      label, make_table, retone)

NAV = (("Overview", "dashboard"), ("Matches", "sports_esports"), ("Teammates", "groups"), ("Openings", "inventory_2"),
       ("Statistics", "insights"), ("Settings", "settings"))
STATS_ORDER = ("trend", "types", "modes", "heat", "records", "teammates", "broken") + tuple(
    f"stat:{key}" for key in STAT_TITLES)
REPLAY_KEYS = ("replay_folder", "count_broken", "scan_seconds", "auto_watch")
RANGE_CHOICES = tuple((days, "All time" if days == 0 else f"Last {days} days") for days in RANGES)
SEEDS = {"Amber": "#e8b04f", "Violet": "#a98aee", "Blue": "#5b9cf0",
         "Teal": "#3fb8a0", "Rose": "#e8718f", "Green": "#7cc46a"}


def source_row(proxy, model, index):
    source = proxy.mapToSource(index)
    return model.rows[source.row()] if source.isValid() else None


class Scanner(QObject):
    """Reads new replays on a background thread with its own database connection."""
    progress = Signal(int, int)
    finished = Signal(object, object)  # in-progress replay result (or None), error text (or None)

    def __init__(self, database):
        super().__init__()
        self.database = database
        self.thread = None

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, folder):
        if self.running:
            return False
        self.thread = threading.Thread(target=self._run, args=(Path(folder),), daemon=True)
        self.thread.start()
        return True

    def _run(self, folder):
        live = error = store = None
        try:
            store = Store(self.database)
            live = replay_reader.scan(store, folder, progress=self.progress.emit)
        except Exception as exc:  # Reported in the UI; the next scan retries.
            error = str(exc) if isinstance(exc, (FileNotFoundError, RuntimeError)) else f"{type(exc).__name__}: {exc}"
        finally:
            if store:
                store.close()
        self.finished.emit(live, error)


class NavButton(QAbstractButton):
    """Navigation rail item, painted directly: an icon in a pill, with the page name beneath."""

    def __init__(self, icon, title):
        super().__init__()
        self.icon, self.title = icon, title
        self.setCheckable(True)
        self.setFixedSize(88, 72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(title)
        self.setAccessibleName(title)

    def paintEvent(self, event):
        t = theme.CURRENT
        c = t.c
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pill = QRectF((self.width() - 56) / 2, 4, 56, 32)
        if on or self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["secondary_container"] if on else theme.mix(c["surface"], c["on_surface"], .08)))
            painter.drawRoundedRect(pill, 16, 16)
        if self.hasFocus():
            painter.setPen(QPen(QColor(c["primary"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(pill.adjusted(-2, -2, 2, 2), 18, 18)
        icon_font = QFont(t.family)
        icon_font.setPixelSize(t.px["icon"])
        painter.setFont(icon_font)
        painter.setPen(QColor(c["on_secondary_container"] if on else c["on_surface_variant"]))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.icon)
        text_font = QFont()
        text_font.setPixelSize(t.px["label"])
        text_font.setWeight(QFont.Weight.DemiBold if on else QFont.Weight.Medium)
        painter.setFont(text_font)
        painter.setPen(QColor(c["on_surface"] if on else c["on_surface_variant"]))
        painter.drawText(QRectF(0, 40, self.width(), 24), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.title)


class RowFilter(QSortFilterProxyModel):
    """Sorts by each column's UserRole key and filters rows with the source model's accepts()."""

    def __init__(self):
        super().__init__()
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.conditions = {}

    def set_conditions(self, **conditions):
        self.beginFilterChange()
        self.conditions = conditions
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row_index, source_parent):
        model = self.sourceModel()
        return model.accepts(model.rows[source_row_index], self.conditions)


class MatchModel(QAbstractTableModel):
    HEADERS = ("Date", "Mode", "Place", "Chests", "Broken open", "Teammates", "Ammo boxes", "Length")

    def __init__(self):
        super().__init__()
        self.rows, self.prefs, self.count_broken, self.type_name = [], None, True, None

    def reset_rows(self, rows, prefs, count_broken, type_name):
        self.beginResetModel()
        self.rows, self.prefs, self.count_broken, self.type_name = rows, prefs, count_broken, type_name
        self.endResetModel()

    def chests(self, row):
        return row["types"][self.type_name] if self.type_name else row["count"]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, column = self.rows[index.row()], index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self.text(row, column)
        if role == Qt.ItemDataRole.UserRole:
            return [row["when"].timestamp(), row["mode"], row["placement"] or 10**6, self.chests(row),
                    row["broken"], row["team"], row["ammo"], row["seconds"]][column]
        if role == Qt.ItemDataRole.TextAlignmentRole and column >= 2:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def text(self, row, column):
        p = self.prefs
        if column == 0:
            return when(row["when"], p)
        if column == 1:
            return row["mode"]
        if column == 2:
            if not row["placement"]:
                return "–"
            return f"#{row['placement']}" + (f" / {row['players']}" if row["players"] else "")
        if column == 3:
            return number(self.chests(row), p)
        if column == 4:
            return number(row["broken"], p) if self.count_broken else "–"
        if column == 5:
            return number(row["team"], p)
        if column == 6:
            return number(row["ammo"], p)
        return elapsed(row["seconds"])

    @staticmethod
    def accepts(row, cond):
        type_name = cond.get("type")
        count = row["types"][type_name] if type_name else row["count"]
        if type_name and not count:
            return False
        if count < cond.get("minimum", 0):
            return False
        if cond.get("mode") and row["mode"] != cond["mode"]:
            return False
        since = cond.get("since")
        if since and row["when"].date() < since:
            return False
        text = cond.get("text", "").lower()
        return not text or text in f"{row['mode']} {row['when']:%Y-%m-%d}".lower()


class EntryModel(QAbstractTableModel):
    HEADERS = ("When", "Type", "How", "Count", "Status", "Details")
    HOW = {"replay": "Opened", "replay-broken": "Broken open", "manual correction": "Manual", "automatic": "Screen (old)"}
    STATUS = {"confirmed": "Counted", "undone": "Removed", "review": "Review", "rejected": "Rejected"}

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
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, column = self.rows[index.row()], index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self.text(row, column)
        if role == Qt.ItemDataRole.UserRole:
            return [row["when"].timestamp(), row["chest_type"], self.HOW.get(row["source"], row["source"]),
                    row["amount"], row["status"], row["reason"]][column]
        if role == Qt.ItemDataRole.TextAlignmentRole and column == 3:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def text(self, row, column):
        if column == 0:
            return when(row["when"], self.prefs)
        if column == 1:
            return row["chest_type"]
        if column == 2:
            return self.HOW.get(row["source"], row["source"])
        if column == 3:
            return number(row["amount"], self.prefs)
        if column == 4:
            return self.STATUS.get(row["status"], row["status"].capitalize())
        return row["reason"].split(" · ", 1)[-1]

    @staticmethod
    def accepts(row, cond):
        if cond.get("type") and row["chest_type"] != cond["type"]:
            return False
        if cond.get("match") and row["match_id"] != cond["match"]:
            return False
        if cond.get("status") and row["status"] != cond["status"]:
            return False
        text = cond.get("text", "").lower()
        return not text or text in f"{row['chest_type']} {row['reason']}".lower()


class MatchDetail(QFrame):
    """The selected match: chests by type, and when each one happened during the replay."""
    closed = Signal()

    def __init__(self):
        super().__init__()
        t = theme.CURRENT
        self.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.sp["l"], t.sp["l"], t.sp["l"], t.sp["l"])
        head = QHBoxLayout()
        titles = QVBoxLayout()
        self.title = label("", "value")
        self.sub = label("", "muted")
        self.sub.setWordWrap(True)
        titles.addWidget(self.title)
        titles.addWidget(self.sub)
        head.addLayout(titles, 1)
        head.addWidget(icon_button("close", "Close match details", self.closed.emit))
        outer.addLayout(head)
        body = QHBoxLayout()
        body.setSpacing(t.sp["xl"])
        self.bars = QGridLayout()
        body.addLayout(self.bars, 1)
        right = QVBoxLayout()
        right.addWidget(label("Openings during the match", "cardTitle"))
        self.timeline = Timeline("No timed openings in this replay")
        right.addWidget(self.timeline, 1)
        body.addLayout(right, 1)
        outer.addLayout(body)
        outer.addWidget(label("Squad: what each player opened or broke", "cardTitle"))
        self.squad_note = label("", "muted")
        self.squad_note.setWordWrap(True)
        outer.addWidget(self.squad_note)
        self.squad = QTableWidget(0, 6)
        self.squad.setHorizontalHeaderLabels(["Player", "Chests", "Searched", "Broken open", "Share of squad", "Types"])
        self.squad.verticalHeader().hide()
        self.squad.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.squad.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.squad.setShowGrid(False)
        self.squad.setWordWrap(True)
        self.squad.horizontalHeader().setStretchLastSection(True)
        self.squad.setMaximumHeight(260)
        outer.addWidget(self.squad)
        self.hide()

    def show_match(self, row, marks, prefs):
        self.title.setText(f"{row['mode']} · {when(row['when'], prefs)}")
        place = (f"#{row['placement']}" + (f" of {row['players']}" if row["players"] else "")
                 if row["placement"] else "No placement recorded")
        team = f" · with {', '.join(row['teammates'][:3])}" if row["teammates"] else ""
        self.sub.setText(f"{place} · {elapsed(row['seconds'])} long · {number(row['count'], prefs)} chests{team}")
        clear_layout(self.bars)
        rows = [(name, count, number(count, prefs), theme.CURRENT.type_color(name))
                for name, count in row["types"].most_common()]
        bar_rows(self.bars, rows or [("No chests opened", 0, "", None)])
        self.squad.setRowCount(0)
        squad = row["squad"]
        self.squad_note.setText("This older match has no per-player detail. It is read again on the next scan, "
                                "while its replay file is still on disk." if squad is None else "")
        for person in squad or []:
            index = self.squad.rowCount()
            self.squad.insertRow(index)
            types = ", ".join(f"{name} {number(count, prefs)}"
                              for name, count in sorted(person["types"].items(), key=lambda kv: -kv[1]))
            cells = (person["name"] + stats.tag(person) + (" · MVP" if person["key"] == row["mvp"] else ""),
                     number(person["total"], prefs), number(person["opened"], prefs), number(person["broken"], prefs), "", types)
            for column, text in enumerate(cells):
                self.squad.setItem(index, column, QTableWidgetItem(text))
            share = QProgressBar()
            share.setRange(0, 100)
            share.setValue(round(100 * person["total"] / (row["squad_total"] or 1)))
            share.setTextVisible(True)
            share.setFormat("%p%")
            share.setMinimumHeight(20)
            self.squad.setCellWidget(index, 4, share)
        self.squad.resizeColumnsToContents()
        self.squad.resizeRowsToContents()
        self.timeline.set_marks(marks, row["seconds"])
        self.show()


class MainWindow(QMainWindow):
    def __init__(self, folder=None, scan_on_start=True):
        super().__init__()
        self.folder = Path(folder) if folder else data_dir()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.config_path = self.folder / "config.json"
        self.prefs_path = self.folder / "ui-settings.json"
        self.config = Config.read(self.config_path)
        self.prefs = Prefs.read(self.prefs_path)
        self.store = Store(self.folder / "ledger.sqlite")
        self.store.include_broken = self.config.count_broken
        self.session_start = datetime.now().astimezone()
        self.live, self.live_info, self.last_scan = None, None, None
        self.scan_error, self.scan_note = None, "Waiting for the first replay check"
        self.editing = False
        self._snap, self._filters_ready = None, False
        self.icon_family = theme.load_icon_font()
        self.scanner = Scanner(self.store.path)
        self.scanner.progress.connect(self.on_scan_progress)
        self.scanner.finished.connect(self.on_scan_finished)
        self.setWindowTitle("LootLedger")
        self.resize(1240, 860)
        self.setMinimumSize(880, 620)
        self.apply_theme()
        self.build_shell()
        self.build_overlay()
        self.hotkeys = Hotkeys(self.on_hotkey)
        QApplication.instance().installNativeEventFilter(self.hotkeys)
        try:
            self.hotkeys.configure(self.config.hotkey_add, self.config.hotkey_undo)
        except ValueError as error:
            self.scan_note = str(error)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scan)
        self.apply_timer()
        self.rebuild_grids()
        self.navigate(0)
        self.refresh()
        QGuiApplication.styleHints().colorSchemeChanged.connect(self.on_system_theme)
        if scan_on_start and self.config.auto_watch:
            QTimer.singleShot(150, self.scan)

    # ---- Shell and pages -----------------------------------------------------------------------

    def build_shell(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(104)
        side = QVBoxLayout(rail)
        side.setContentsMargins(8, 16, 8, 16)
        side.setSpacing(6)
        side.addWidget(label("inventory_2", "iconAccent"), 0, Qt.AlignmentFlag.AlignHCenter)
        side.addWidget(label("LootLedger", "railLabel"), 0, Qt.AlignmentFlag.AlignHCenter)
        side.addSpacing(10)
        self.nav, group = [], QButtonGroup(self)
        group.setExclusive(True)
        for index, (title, icon) in enumerate(NAV):
            item = NavButton(icon, title)
            item.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            group.addButton(item)
            side.addWidget(item)
            self.nav.append(item)
        side.addStretch()
        side.addWidget(label("Local only", "railLabel"), 0, Qt.AlignmentFlag.AlignHCenter)
        row.addWidget(rail)
        self.pages = QStackedWidget()
        row.addWidget(self.pages, 1)
        self.snackbar = Snackbar(root)
        self.build_overview()
        self.build_matches()
        self.build_teammates()
        self.build_openings()
        self.build_statistics()
        self.build_settings()
        self.shortcuts = []
        for index in range(len(NAV)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda i=index: self.navigate(i))
            self.shortcuts.append(shortcut)

    def page(self, title, subtitle="", actions=(), scroll=True):
        """Create a page. Returns (layout for the page body, subtitle label)."""
        t = theme.CURRENT
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        content.setObjectName("root")
        wrap = QHBoxLayout(content)
        wrap.setContentsMargins(t.sp["xl"], t.sp["xl"], t.sp["xl"], t.sp["xl"])
        column = QWidget()
        column.setMaximumWidth(1600)  # keeps very wide windows readable
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(t.sp["m"])
        head = QHBoxLayout()
        head.setSpacing(t.sp["s"])
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(title, "title"))
        sub = label(subtitle, "muted")
        sub.setWordWrap(True)
        sub.setVisible(bool(subtitle))
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        for action in actions:
            head.addWidget(action)
        layout.addLayout(head)
        wrap.addStretch(1)
        wrap.addWidget(column, 100)
        wrap.addStretch(1)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(content)
            outer_layout.addWidget(area)
        else:
            outer_layout.addWidget(content)
        self.pages.addWidget(outer)
        return layout, sub

    def navigate(self, index):
        for position, item in enumerate(self.nav):
            item.setChecked(position == index)
        if self.pages.currentIndex() == index:
            return
        if getattr(self, "page_animation", None):
            self.page_animation.stop()
        self.pages.setCurrentIndex(index)
        page = self.pages.currentWidget()
        if theme.CURRENT.motion:
            effect = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(effect)
            self.page_animation = QPropertyAnimation(effect, b"opacity", self)
            self.page_animation.setDuration(220)
            self.page_animation.setStartValue(0.0)
            self.page_animation.setEndValue(1.0)
            self.page_animation.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
            self.page_animation.finished.connect(lambda: page.setGraphicsEffect(None))
            self.page_animation.start()

    def build_overview(self):
        self.edit_add = QPushButton("Add widget")
        self.edit_add.setObjectName("outlined")
        self.edit_add.setMenu(QMenu(self))
        self.edit_reset = QPushButton("Reset layout")
        self.edit_reset.setObjectName("text")
        self.edit_reset.clicked.connect(lambda checked=False: self.safe(self.reset_layout))
        self.edit_tools = QWidget()
        tools = QHBoxLayout(self.edit_tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.addWidget(self.edit_add)
        tools.addWidget(self.edit_reset)
        self.edit_tools.hide()
        self.edit_button = icon_button("tune", "Customize the dashboard", self.toggle_editing, checkable=True)
        check = icon_button("refresh", "Check for new replays now", lambda: self.safe(self.scan))
        popout = icon_button("picture_in_picture_alt", "Pop-out counter", self.toggle_overlay)
        layout, self.sub_overview = self.page("Overview", "", [self.edit_tools, self.edit_button, check, popout])
        self.status = label("", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.overview_grid = DashGrid()
        self.overview_grid.changed.connect(self.on_reorder)
        layout.addWidget(self.overview_grid)

    def build_matches(self):
        layout, self.sub_matches = self.page("Matches", "Matches read from your replays. Select one to see its breakdown and timeline.", scroll=False)
        bar = QHBoxLayout()
        bar.setSpacing(theme.CURRENT.sp["s"])
        self.match_search = QLineEdit()
        self.match_search.setPlaceholderText("Search mode or date, e.g. 2026-11-06")
        self.match_search.setClearButtonEnabled(True)
        self.match_range = QComboBox()
        for days, text in RANGE_CHOICES:
            self.match_range.addItem(text, days)
        self.match_range.setCurrentIndex(max(0, self.match_range.findData(self.prefs.default_range)))
        self.match_mode = QComboBox()
        self.match_type = QComboBox()
        self.match_min = QSpinBox()
        self.match_min.setMinimumWidth(120)
        self.match_min.setRange(0, 999)
        self.match_min.setSpecialValueText("Any count")
        self.match_min.setPrefix("At least ")
        bar.addWidget(self.match_search, 1)
        for widget in (self.match_range, self.match_mode, self.match_type, self.match_min):
            bar.addWidget(widget)
        layout.addLayout(bar)
        self.match_count = label("", "muted")
        layout.addWidget(self.match_count)
        self.match_empty = label("No matches yet. Turn on Record Replays in Fortnite, finish a match, and it appears here.", "muted")
        self.match_empty.setWordWrap(True)
        layout.addWidget(self.match_empty)
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(theme.CURRENT.sp["s"], theme.CURRENT.sp["s"], theme.CURRENT.sp["s"], theme.CURRENT.sp["s"])
        self.match_model = MatchModel()
        self.match_proxy = RowFilter()
        self.match_proxy.setSourceModel(self.match_model)
        self.match_table = make_table()
        self.match_table.setModel(self.match_proxy)
        self.match_table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self.match_table.selectionModel().currentRowChanged.connect(self.on_match_selected)
        panel_layout.addWidget(self.match_table)
        layout.addWidget(panel, 1)
        self.detail = MatchDetail()
        self.detail.closed.connect(self.close_detail)
        layout.addWidget(self.detail)
        self.match_search.textChanged.connect(lambda _: self.apply_match_filters())
        self.match_range.currentIndexChanged.connect(lambda _: self.apply_match_filters())
        self.match_mode.currentIndexChanged.connect(lambda _: self.apply_match_filters())
        self.match_type.currentIndexChanged.connect(lambda _: self.apply_match_filters())
        self.match_min.valueChanged.connect(lambda _: self.apply_match_filters())

    def build_teammates(self):
        layout, _ = self.page("Teammates", "Everyone who played with you, merged across matches. Pick someone to see their profile.",
                              scroll=True)
        self.team_panel = TeammatesPanel(self.prefs)
        self.team_panel.exported.connect(self.snackbar.show_text)
        layout.addWidget(self.team_panel)

    def build_openings(self):
        fab = QPushButton("add")
        fab.setObjectName("fab")
        fab.setToolTip("Add a manual chest to the latest match")
        fab.setAccessibleName("Add a manual chest")
        fab.clicked.connect(lambda checked=False: self.safe(self.manual_add))
        undo = icon_button("undo", "Undo the last counted opening", lambda: self.safe(self.undo))
        export = icon_button("download", "Export the openings shown", lambda: self.safe(self.export_openings))
        layout, self.sub_openings = self.page("Openings", "Every chest you opened, newest first. Corrections are recorded and never silently lost.",
                                              [undo, export, fab], scroll=False)
        self.open_title = label("", "cardTitle")
        layout.addWidget(self.open_title)
        self.open_timeline = Timeline("Choose a match to see when its openings happened")
        self.open_timeline.setMinimumHeight(96)
        layout.addWidget(self.open_timeline)
        bar = QHBoxLayout()
        bar.setSpacing(theme.CURRENT.sp["s"])
        self.entry_search = QLineEdit()
        self.entry_search.setPlaceholderText("Search type or details")
        self.entry_search.setClearButtonEnabled(True)
        self.open_match = QComboBox()
        self.entry_type = QComboBox()
        self.entry_status = QComboBox()
        for text, data in (("Counted", "confirmed"), ("Removed", "undone"), ("All statuses", "")):
            self.entry_status.addItem(text, data)
        bar.addWidget(self.entry_search, 1)
        for widget in (self.open_match, self.entry_type, self.entry_status):
            bar.addWidget(widget)
        layout.addLayout(bar)
        self.entry_empty = label("No openings yet. Play a match with Record Replays on.", "muted")
        layout.addWidget(self.entry_empty)
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(theme.CURRENT.sp["s"], theme.CURRENT.sp["s"], theme.CURRENT.sp["s"], theme.CURRENT.sp["s"])
        self.entry_model = EntryModel()
        self.entry_proxy = RowFilter()
        self.entry_proxy.setSourceModel(self.entry_model)
        self.entries = make_table()
        self.entries.setModel(self.entry_proxy)
        self.entries.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self.entries.doubleClicked.connect(lambda _: self.safe(self.edit_entry))
        panel_layout.addWidget(self.entries)
        layout.addWidget(panel, 1)
        actions = QHBoxLayout()
        for title, action in (("Remove entry", lambda: self.change_status("undone")),
                              ("Restore entry", lambda: self.change_status("confirmed")),
                              ("Correct entry…", self.edit_entry)):
            actions.addWidget(button_for(title, action))
        actions.addStretch()
        layout.addLayout(actions)
        self.entry_search.textChanged.connect(lambda _: self.apply_entry_filters())
        self.open_match.currentIndexChanged.connect(lambda _: self.apply_entry_filters())
        self.entry_type.currentIndexChanged.connect(lambda _: self.apply_entry_filters())
        self.entry_status.currentIndexChanged.connect(lambda _: self.apply_entry_filters())

    def build_statistics(self):
        layout, self.sub_stats = self.page("Statistics", "")
        self.stats_grid = DashGrid()
        layout.addWidget(self.stats_grid)

    def build_settings(self):
        layout, self.sub_settings = self.page(
            "Settings", "Changes apply immediately. Your replays and ledger never leave this PC.")
        self.settings_host = QVBoxLayout()
        self.settings_host.setSpacing(theme.CURRENT.sp["m"])
        layout.addLayout(self.settings_host)
        self.fill_settings()
        layout.addStretch()

    def fill_settings(self):
        clear_layout(self.settings_host)
        self.appearance_card()
        self.tiles_card()
        self.formats_card()
        self.replays_card()
        self.shortcuts_card()
        self.data_card()

    def settings_card(self, title, icon):
        t = theme.CURRENT
        card = Card(title, icon)
        grid = QGridLayout()
        grid.setHorizontalSpacing(t.sp["l"])
        grid.setVerticalSpacing(t.sp["m"])
        grid.setColumnStretch(0, 1)
        card.body.addLayout(grid)
        self.settings_host.addWidget(card)
        return grid

    @staticmethod
    def setting_row(grid, name, control, hint=""):
        row = grid.rowCount()
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(name))
        if hint:
            note = label(hint, "muted")
            note.setWordWrap(True)
            text.addWidget(note)
        grid.addLayout(text, row, 0)
        grid.addWidget(control, row, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def choice(self, name, options, current, tip, cast=str):
        control = Segmented(options, current, tip)
        control.changed.connect(lambda key: self.set_pref(name, cast(key)))
        return control

    def switch(self, name, checked, tip):
        control = Switch(checked, tip)
        control.toggled.connect(lambda on: self.set_pref(name, bool(on)))
        return control

    def appearance_card(self):
        p = self.prefs
        grid = self.settings_card("Appearance", "palette")
        self.setting_row(grid, "Theme", self.choice("theme", (("light", "Light"), ("dark", "Dark"), ("system", "System")),
                                                    p.theme, "Colour theme"))
        accent = QWidget()
        row = QHBoxLayout(accent)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.CURRENT.sp["s"])
        c = theme.CURRENT.c
        for name, color in SEEDS.items():
            swatch = QPushButton()
            ring = c["on_surface"] if color.lower() == p.seed.lower() else c["surface_container_high"]
            swatch.setStyleSheet(f"QPushButton {{ background: {color}; border: 3px solid {ring}; border-radius: 14px; "
                                 "min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; padding: 0px; }}")
            swatch.setToolTip(name)
            swatch.setAccessibleName(f"{name} accent colour")
            swatch.clicked.connect(lambda checked=False, value=color: self.set_pref("seed", value))
            row.addWidget(swatch)
        self.seed_edit = QLineEdit(p.seed)
        self.seed_edit.setPlaceholderText("#rrggbb")
        self.seed_edit.setMaximumWidth(110)
        self.seed_edit.setAccessibleName("Custom accent colour")
        self.seed_edit.editingFinished.connect(lambda: self.safe(self.save_seed))
        row.addWidget(self.seed_edit)
        self.setting_row(grid, "Accent colour", accent, "Presets or your own #rrggbb. Everything is tuned from it.")
        self.setting_row(grid, "Higher contrast", self.switch("contrast", p.contrast, "Higher contrast"),
                         "Stronger outlines and muted text.")
        self.setting_row(grid, "Corners", self.choice("corners", (("sharp", "Sharp"), ("default", "Default"), ("round", "Round")),
                                                      p.corners, "Corner radius"))
        self.setting_row(grid, "Density", self.choice("density", (("compact", "Compact"), ("comfortable", "Comfortable")),
                                                      p.density, "Spacing"))
        self.setting_row(grid, "Text size", self.choice("font_scale", (("S", "S"), ("M", "M"), ("L", "L"), ("XL", "XL")),
                                                        p.font_scale, "Text size"))
        self.setting_row(grid, "Chart style", self.choice("chart_style", (("bar", "Bar"), ("line", "Line"), ("area", "Area")),
                                                          p.chart_style, "Chart style"))
        self.setting_row(grid, "Background", self.choice("background", (("solid", "Solid"), ("tonal", "Tonal")),
                                                         p.background, "Background"),
                         "A soft tonal wash instead of a flat colour.")
        self.setting_row(grid, "Animations", self.switch("animations", p.animations, "Animations"),
                         "Count-up numbers and transitions. Windows' 'Show animations' setting is also respected.")

    def tiles_card(self):
        grid = self.settings_card("Overview tiles", "dashboard_customize")
        present = {item["id"] for item in self.prefs.layout}
        holder = QWidget()
        chips = QGridLayout(holder)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(theme.CURRENT.sp["s"])
        for index, key in enumerate(STAT_TITLES):
            chip = QPushButton(STAT_TITLES[key][0])
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setChecked(f"stat:{key}" in present)
            chip.toggled.connect(lambda on, k=f"stat:{key}": self.toggle_widget(k, on))
            chips.addWidget(chip, index // 3, index % 3)
        self.setting_row(grid, "Summary tiles", holder,
                         "Choose which stats appear on Overview. Use Customize there to move and resize them.")

    def formats_card(self):
        p = self.prefs
        grid = self.settings_card("Formats", "schedule")
        self.setting_row(grid, "24-hour clock", self.switch("time_24h", p.time_24h, "24-hour clock"))
        self.setting_row(grid, "Date format", self.choice("date_format", (("dmy", "dd/mm/yyyy"), ("mdy", "mm/dd/yyyy"),
                                                                       ("iso", "yyyy-mm-dd")), p.date_format, "Date format"))
        self.setting_row(grid, "Number separator", self.choice("separators", ((",", "1,234"), (".", "1.234"), (" ", "1 234"),
                                                                             ("", "1234")), p.separators, "Thousands separator"))
        self.setting_row(grid, "Playtime shown as", self.choice("playtime", (("hm", "12h 40m"), ("decimal", "12.7 h")),
                                                                p.playtime, "Playtime"))
        self.setting_row(grid, "Default date range", self.choice("default_range", (("7", "7 days"), ("30", "30 days"),
                                                                                    ("90", "90 days"), ("0", "All time")),
                                                                 str(p.default_range), "Default date range", cast=int),
                         "Used for the trend chart and the Matches filter.")

    def replays_card(self):
        t = theme.CURRENT
        grid = self.settings_card("Replays", "folder_open")
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(t.sp["s"])
        self.folder_edit = QLineEdit(self.config.replay_folder or str(replay_reader.default_folder()))
        self.folder_edit.setMinimumWidth(260)
        self.folder_edit.setAccessibleName("Replay folder")
        self.folder_edit.editingFinished.connect(lambda: self.safe(self.save_folder))
        row.addWidget(self.folder_edit)
        browse = icon_button("folder", "Choose the replay folder", lambda: self.safe(self.browse_folder))
        row.addWidget(browse)
        row.addWidget(icon_button("open_in_new", "Open the replay folder", lambda: self.safe(self.open_replays)))
        self.setting_row(grid, "Replay folder", holder, "Fortnite's default is Saved\\Demos under FortniteGame.")
        self.auto_switch = Switch(self.config.auto_watch, "Check for replays automatically")
        self.auto_switch.toggled.connect(lambda on: self.safe(lambda: self.update_config(auto_watch=bool(on))))
        self.setting_row(grid, "Watch for new replays", self.auto_switch, "Finished matches are added on their own.")
        self.interval = QSpinBox()
        self.interval.setRange(5, 600)
        self.interval.setSuffix(" s")
        self.interval.setValue(self.config.scan_seconds)
        self.interval.setMaximumWidth(110)
        self.interval.valueChanged.connect(lambda value: self.safe(lambda: self.update_config(scan_seconds=value)))
        self.setting_row(grid, "Check every", self.interval)
        self.broken_switch = Switch(self.config.count_broken, "Count chests you broke open")
        self.broken_switch.toggled.connect(lambda on: self.safe(lambda: self.set_count_broken(bool(on))))
        self.setting_row(grid, "Count broken-open chests", self.broken_switch,
                         "Chests destroyed by your damage before anyone searched them. Their loot still spills.")
        self.setting_row(grid, "Read every replay again", button_for("Read all replays again", lambda: self.safe(self.rescan)),
                         "Re-reads all replays Fortnite still keeps. Your corrections are kept.")

    def shortcuts_card(self):
        grid = self.settings_card("Shortcuts", "keyboard")
        self.hotkey_add = QLineEdit(self.config.hotkey_add)
        self.hotkey_undo = QLineEdit(self.config.hotkey_undo)
        for edit, name in ((self.hotkey_add, "Manual +1 shortcut"), (self.hotkey_undo, "Undo shortcut")):
            edit.setMaximumWidth(200)
            edit.setAccessibleName(name)
            edit.editingFinished.connect(lambda: self.safe(self.save_hotkeys))
        self.setting_row(grid, "Add one chest", self.hotkey_add, "Works in any app. Example: Ctrl+Alt+F8")
        self.setting_row(grid, "Undo last chest", self.hotkey_undo, "Example: Ctrl+Alt+F9")

    def data_card(self):
        t = theme.CURRENT
        grid = self.settings_card("Data", "database")
        buttons = QGridLayout()
        buttons.setSpacing(t.sp["s"])
        actions = (("Export ledger", self.export_data, ""), ("Create backup", self.backup_data, ""),
                   ("Restore backup", self.restore_data, ""), ("Open data folder", self.open_data, ""),
                   ("Export settings", self.export_settings, ""), ("Import settings", self.import_settings, ""),
                   ("Clear all data…", self.clear_data, "danger"))
        for index, (text, action, variant) in enumerate(actions):
            buttons.addWidget(button_for(text, action, variant), index // 2, index % 2)
        holder = QWidget()
        holder.setLayout(buttons)
        self.setting_row(grid, "Ledger and settings", holder,
                         f"Stored in {self.folder}. Backups hold matches, openings and your edit history.")
        clear_note = label("Clearing saves a backup first. Replay files stay on your PC and are not read again "
                           "until you choose Read all replays again.", "muted")
        clear_note.setWordWrap(True)
        grid.addWidget(clear_note, grid.rowCount(), 0, 1, 2)

    # ---- Theme and dashboard -------------------------------------------------------------------

    def apply_theme(self):
        motion = self.prefs.animations and theme.os_animations_enabled()
        tokens = theme.build(self.prefs, theme.is_dark(self.prefs.theme), motion, self.icon_family)
        sheet = theme.stylesheet(tokens)
        # Window-level sheet: restyling the whole application re-lays out every widget and takes seconds.
        self.setStyleSheet(sheet)
        if hasattr(self, "overlay"):
            self.overlay.setStyleSheet(sheet)
        theme.apply_tooltips(tokens)

    def apply_prefs(self):
        self.apply_theme()
        self._snap = None
        self.rebuild_grids()
        self.refresh()

    def set_pref(self, name, value):
        setattr(self.prefs, name, value)
        self.prefs.save(self.prefs_path)
        if name == "chart_style":
            self.refresh()
        elif name in ("time_24h", "date_format", "separators", "playtime", "default_range"):
            self._snap = None  # text formats only: no need to rebuild any card
            self.refresh()
        elif name in ("corners", "font_scale", "background", "animations"):
            self.apply_theme()  # sizes and shapes come from the stylesheet
            self.refresh()
        else:
            self.apply_prefs()  # colours, contrast and density are built into the cards
            if name == "seed":
                self.fill_settings()

    def on_system_theme(self, *args):
        if self.prefs.theme == "system":
            self.apply_prefs()

    def make_card(self, key, span):
        card = make_panel(key, self.prefs, self.set_pref)
        card.key, card.span = key, span
        card.removed.connect(self.remove_widget)
        card.resized.connect(self.resize_widget)
        return card

    def rebuild_overview(self):
        self.overview_grid.set_cards([self.make_card(item["id"], item["span"]) for item in self.prefs.layout])
        for card in self.overview_grid.cards:
            card.set_editing(self.editing)

    def rebuild_grids(self):
        self.rebuild_overview()
        self.stats_grid.set_cards([self.make_card(key, WIDGETS[key]) for key in STATS_ORDER])

    def toggle_editing(self):
        self.editing = self.edit_button.isChecked()
        self.edit_tools.setVisible(self.editing)
        for card in self.overview_grid.cards:
            card.set_editing(self.editing)
        self.fill_add_menu()

    def fill_add_menu(self):
        menu = self.edit_add.menu()
        menu.clear()
        present = {item["id"] for item in self.prefs.layout}
        missing = [key for key in WIDGETS if key not in present]
        for key in missing:
            action = menu.addAction(widget_title(key))
            action.triggered.connect(lambda checked=False, k=key: self.add_widget(k))
        if not missing:
            menu.addAction("Everything is on the dashboard").setEnabled(False)

    def save_layout(self):
        self.prefs.save(self.prefs_path)
        self.rebuild_overview()
        self.fill_add_menu()
        self.refresh()

    def on_reorder(self, order):
        by_id = {item["id"]: item for item in self.prefs.layout}
        self.prefs.layout = [by_id[key] for key in order if key in by_id]
        self.save_layout()

    def remove_widget(self, key):
        self.prefs.layout = [item for item in self.prefs.layout if item["id"] != key]
        self.save_layout()

    def add_widget(self, key):
        self.prefs.layout = [*self.prefs.layout, {"id": key, "span": WIDGETS[key]}]
        self.save_layout()

    def resize_widget(self, key, span):
        for item in self.prefs.layout:
            if item["id"] == key:
                item["span"] = span
        self.save_layout()

    def toggle_widget(self, key, on):
        if on and key not in {item["id"] for item in self.prefs.layout}:
            self.add_widget(key)
        elif not on:
            self.remove_widget(key)

    def reset_layout(self):
        self.prefs.layout = default_layout()
        self.save_layout()

    # ---- Refresh -------------------------------------------------------------------------------

    def refresh(self):
        snap = self.store.snapshot(self.session_start)
        ctx = SimpleNamespace(snap=snap, prefs=self.prefs, live=self.live_info, motion=theme.CURRENT.motion)
        for grid in (self.overview_grid, self.stats_grid):
            for card in grid.cards:
                card.refresh(ctx)
        self.sub_overview.setText(f"{snap['player'] or 'Your replays'} · {snap['matches']} matches read")
        self.sub_stats.setText(f"Computed from {snap['matches']} matches and your corrections")
        if snap is not self._snap:
            self._snap = snap
            self.fill_filters(snap)
            self.apply_match_filters()
            self.apply_entry_filters()
        self.team_panel.refresh(snap, self.prefs)
        self.refresh_status()
        self.refresh_overlay(snap)

    def fill_filters(self, snap):
        fill(self.match_mode, [("All modes", None)] + [(name, name) for name in sorted(snap["modes"])])
        types = sorted({e["chest_type"] for e in snap["entries"]} | set(snap["types"]))
        type_items = [("All types", None)] + [(name, name) for name in types]
        fill(self.match_type, type_items)
        fill(self.entry_type, type_items)
        matches = snap["match_rows"]
        fill(self.open_match, [("All matches", None)] + [(f"{r['mode']} · {when(r['when'], self.prefs)}", r["id"])
                                                          for r in matches])
        if not self._filters_ready and matches:
            self.open_match.setCurrentIndex(1)  # start with the latest match
        self._filters_ready = True

    def match_conditions(self):
        days = self.match_range.currentData()
        since = (datetime.now().astimezone() - timedelta(days=days - 1)).date() if days else None  # today plus the last N-1 days
        return dict(since=since, mode=self.match_mode.currentData(), minimum=self.match_min.value(),
                    type=self.match_type.currentData(), text=self.match_search.text().strip())

    def apply_match_filters(self):
        rows = self._snap["match_rows"] if self._snap else []
        selected = self.selected_match_id()
        self.match_model.reset_rows(rows, self.prefs, self.config.count_broken, self.match_type.currentData())
        self.match_proxy.set_conditions(**self.match_conditions())
        self.match_empty.setVisible(not rows)
        self.match_count.setText(f"{self.match_proxy.rowCount()} of {len(rows)} matches" if rows else "")
        self.select_match(selected)

    def selected_match_id(self):
        row = source_row(self.match_proxy, self.match_model, self.match_table.currentIndex())
        return row["id"] if row else None

    def select_match(self, match_id):
        for position in range(self.match_proxy.rowCount()):
            row = source_row(self.match_proxy, self.match_model, self.match_proxy.index(position, 0))
            if row and row["id"] == match_id:
                self.match_table.selectRow(position)
                return
        self.match_table.clearSelection()
        self.detail.hide()

    def on_match_selected(self, current, previous):
        row = source_row(self.match_proxy, self.match_model, current)
        if row is None:
            self.detail.hide()
            return
        self.detail.show_match(row, self.marks_for(row["id"]), self.prefs)

    def close_detail(self):
        self.detail.hide()
        self.match_table.clearSelection()

    def marks_for(self, match_id):
        return [(row["video_time"], row["chest_type"],
                 row["chest_type"] + (" · broken open" if row["source"] == "replay-broken" else ""))
                for row in self.store.match_events(match_id) if row["video_time"] is not None]

    def entry_conditions(self):
        return dict(type=self.entry_type.currentData(), match=self.open_match.currentData(),
                    status=self.entry_status.currentData() or None, text=self.entry_search.text().strip())

    def apply_entry_filters(self):
        rows = self._snap["entries"] if self._snap else []
        selected = self.selected_entry_id()
        self.entry_model.reset_rows(rows, self.prefs)
        self.entry_proxy.set_conditions(**self.entry_conditions())
        self.entry_empty.setVisible(not rows)
        self.select_entry(selected)
        self.update_open_timeline()

    def selected_entry_id(self):
        row = source_row(self.entry_proxy, self.entry_model, self.entries.currentIndex())
        return row["id"] if row else None

    def select_entry(self, entry_id):
        for position in range(self.entry_proxy.rowCount()):
            row = source_row(self.entry_proxy, self.entry_model, self.entry_proxy.index(position, 0))
            if row and row["id"] == entry_id:
                self.entries.selectRow(position)
                return
        self.entries.clearSelection()

    def update_open_timeline(self):
        match_id = self.open_match.currentData()
        row = next((r for r in self._snap["match_rows"] if r["id"] == match_id), None) if match_id and self._snap else None
        if row is None:
            self.open_title.setText("Choose a match above to see when its openings happened")
            self.open_timeline.set_marks([], 1)
            return
        self.open_title.setText(f"{row['mode']} · {when(row['when'], self.prefs)} · {number(row['count'], self.prefs)} chests")
        self.open_timeline.set_marks(self.marks_for(match_id), row["seconds"])

    def refresh_status(self):
        partial = self._snap["partial"] if self._snap else 0
        if self.scan_error:
            text, tone = self.scan_error, "bad"
        elif self.scan_note:
            text, tone = self.scan_note, "muted"
        elif self.live_info:
            text, tone = "Match in progress · the count updates while Fortnite writes the replay", "good"
        else:
            text, tone = f"Watching {self.replay_folder()} · finished matches are added automatically", "muted"
        if partial and not self.scan_error:
            text += f" · {partial} replay(s) read partly (see Matches)"
        if self.last_scan:
            text += f" · checked {self.last_scan:%H:%M:%S}"
        self.status.setText("●  " + text)
        retone(self.status, tone)

    def refresh_overlay(self, snap):
        if self.live_info:
            self.overlay_title.setText("Chests · current match")
            self.overlay_count.setText(number(self.live_info["count"], self.prefs))
        else:
            self.overlay_title.setText("Chests opened · all time")
            self.overlay_count.setText(number(snap["all"], self.prefs))
        last = snap["last"]["count"] if snap["last"] else 0
        self.overlay_lines.setText(f"This session: +{number(snap['session'], self.prefs)}\n"
                                   f"Last match: {number(last, self.prefs)} chests\n"
                                   f"All time: {number(snap['all'], self.prefs)}")

    def build_overlay(self):
        self.overlay = QWidget(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.overlay.setWindowTitle("LootLedger counter")
        self.overlay.setObjectName("root")
        layout = QVBoxLayout(self.overlay)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(2)
        self.overlay_title = label("Chests opened", "muted")
        self.overlay_count = label("0", "numberAccent")
        self.overlay_lines = label("", "muted")
        for widget in (self.overlay_title, self.overlay_count, self.overlay_lines):
            layout.addWidget(widget)
        self.overlay.resize(260, 170)
        self.overlay.setStyleSheet(self.styleSheet())

    def toggle_overlay(self):
        self.overlay.setVisible(not self.overlay.isVisible())

    # ---- Replays -------------------------------------------------------------------------------

    def replay_folder(self):
        return Path(self.config.replay_folder) if self.config.replay_folder else replay_reader.default_folder()

    def apply_timer(self):
        if self.config.auto_watch:
            self.timer.start(self.config.scan_seconds * 1000)
        else:
            self.timer.stop()

    def scan(self):
        folder = self.replay_folder()
        if not folder.is_dir():
            self.scan_error = (f"Replay folder not found: {folder}. Turn on Record Replays in Fortnite "
                               "(Settings → Game → Replays) and play a match, or choose the folder in Settings.")
            self.refresh_status()
            return
        self.scan_error = None
        if self.scanner.start(folder):
            self.scan_note = "Checking replays…"
            self.refresh_status()

    def on_scan_progress(self, done, total):
        if total > 1:
            self.scan_note = f"Reading replays {done}/{total}…"
            self.refresh_status()

    def on_scan_finished(self, live, error):
        self.live = live
        self.live_info = self.live_summary(live)
        self.scan_error = error
        self.scan_note = ""
        self.last_scan = datetime.now()
        self.refresh()

    def live_summary(self, live):
        if not live:
            return None
        mine, meta = replay_reader.summarize(live)
        count = sum(1 for e in mine if self.config.count_broken or e["kind"] == "opened")
        try:
            started = Path(live["file"]).stat().st_ctime  # Windows: creation time = match start
        except (OSError, KeyError):
            started = None
        return {"count": count, "mode": meta["mode"], "elapsed": time.time() - started if started else None}

    def rescan(self):
        if self.scanner.running:
            raise ValueError("A replay check is running; try again in a moment")
        self.store.forget_replay_files()
        self.scan()

    def update_config(self, **changes):
        candidate = deepcopy(self.config)
        for key, value in changes.items():
            setattr(candidate, key, value)
        candidate.validate()
        candidate.save(self.config_path)
        self.config = candidate
        self.store.include_broken = candidate.count_broken
        self.apply_timer()
        self.refresh()

    def set_count_broken(self, on):
        self.update_config(count_broken=on)

    def save_folder(self):
        default = str(replay_reader.default_folder())
        text = self.folder_edit.text().strip()
        value = "" if not text or text == default else text
        if value == self.config.replay_folder:
            return
        self.update_config(replay_folder=value)
        self.scan()
        self.snackbar.show_text("Replay folder saved")

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Fortnite replay folder", str(self.replay_folder()))
        if path:
            self.folder_edit.setText(path)
            self.save_folder()

    def save_seed(self):
        value = self.seed_edit.text().strip().lower()
        if not value.startswith("#"):
            value = "#" + value
        if not re.fullmatch(r"#[0-9a-f]{6}", value):
            raise ValueError("Enter a colour as #rrggbb, for example #e8b04f")
        if value != self.prefs.seed:
            self.set_pref("seed", value)

    def save_hotkeys(self):
        add, undo = self.hotkey_add.text().strip(), self.hotkey_undo.text().strip()
        if (add, undo) == (self.config.hotkey_add, self.config.hotkey_undo):
            return
        try:
            self.hotkeys.configure(add, undo)
        except ValueError:
            self.hotkeys.configure(self.config.hotkey_add, self.config.hotkey_undo)
            raise
        self.update_config(hotkey_add=add, hotkey_undo=undo)
        self.snackbar.show_text("Shortcuts saved")

    def on_hotkey(self, action):
        # Native hotkeys only observe key presses; they never send input to Fortnite.
        self.safe(self.manual_add if action == "add" else self.undo)

    # ---- Actions -------------------------------------------------------------------------------

    def safe(self, action):
        try:
            action()
        except Exception as error:
            QMessageBox.warning(self, "LootLedger", str(error))

    def manual_add(self):
        self.store.add_correction()
        self.refresh()

    def undo(self):
        self.store.undo()
        self.refresh()

    def selected_entry(self):
        row = source_row(self.entry_proxy, self.entry_model, self.entries.currentIndex())
        if row is None:
            raise ValueError("Select an opening first")
        return row

    def change_status(self, status):
        self.store.edit(self.selected_entry()["id"], status=status)
        self.refresh()

    def edit_entry(self):
        entry = self.selected_entry()
        dialog = QDialog(self)
        dialog.setWindowTitle("Correct opening")
        layout = QFormLayout(dialog)
        chest_type = QLineEdit(entry["chest_type"])
        amount = QSpinBox()
        amount.setRange(1, 10000)
        amount.setValue(entry["amount"])
        layout.addRow("Chest type", chest_type)
        layout.addRow("Count", amount)
        reason = label(entry["reason"], "muted")
        reason.setWordWrap(True)
        layout.addRow(reason)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addRow(actions)
        if dialog.exec():
            self.store.edit(entry["id"], chest_type=chest_type.text(), amount=amount.value())
            self.refresh()

    def visible_entries(self):
        return [source_row(self.entry_proxy, self.entry_model, self.entry_proxy.index(position, 0))
                for position in range(self.entry_proxy.rowCount())]

    def export_openings(self):
        rows = self.visible_entries()
        if not rows:
            raise ValueError("No openings match the current filters")
        path, _ = QFileDialog.getSaveFileName(self, "Export openings", "lootledger-openings.csv",
                                              "CSV (*.csv);;JSON (*.json)")
        if path:
            Store.export_rows(path, [{field: row[field] for field in EVENT_FIELDS} for row in rows])
            self.snackbar.show_text(f"Exported {len(rows)} openings")

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export ledger", "lootledger.json", "JSON (*.json);;CSV (*.csv)")
        if path:
            self.store.export(path)
            self.snackbar.show_text("Ledger exported")

    def backup_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save ledger backup", "lootledger-backup.sqlite", "SQLite backup (*.sqlite)")
        if path:
            self.store.backup(path)
            self.snackbar.show_text("Backup saved")

    def restore_data(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore ledger backup", "", "SQLite backup (*.sqlite)")
        if not path:
            return
        if self.scanner.running:
            raise ValueError("A replay check is running; try again in a moment")
        if QMessageBox.question(self, "Restore backup", "Replace the current ledger with this backup? A safety backup will be saved first.") != QMessageBox.StandardButton.Yes:
            return
        safety = self.store.restore(path)
        self.refresh()
        self.snackbar.show_text(f"Backup restored. Previous ledger saved as {safety.name}")

    def clear_data(self):
        if self.scanner.running:
            raise ValueError("Wait for the replay check to finish, then clear again")
        answer = QMessageBox.question(
            self, "Clear all LootLedger data?",
            "This deletes every counted chest, match and correction in LootLedger. A backup is saved first.\n\n"
            "Your replay files stay on your PC and are not read again unless you choose Read all replays again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        backups = self.folder / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / f"before-clear-{datetime.now():%Y%m%d-%H%M%S}.sqlite"
        self.store.backup(backup)
        self.store.clear()
        self.live, self.live_info = None, None
        self.refresh()
        self.snackbar.show_text(f"Data cleared. Backup kept: {backup.name}")

    def export_settings(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", "lootledger-settings.json", "LootLedger settings (*.json)")
        if path:
            payload = {"app": "LootLedger", "settings": self.prefs.to_dict(),
                       "replays": {key: getattr(self.config, key) for key in REPLAY_KEYS}}
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.snackbar.show_text("Settings exported")

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", "", "LootLedger settings (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("That file is not a LootLedger settings file.") from error
        if not isinstance(data, dict) or data.get("app") != "LootLedger":
            raise ValueError("That file is not a LootLedger settings file.")
        candidate = deepcopy(self.config)
        replays = data.get("replays") or {}
        for key in REPLAY_KEYS:
            if key in replays:
                setattr(candidate, key, replays[key])
        candidate.validate()
        self.prefs = Prefs.from_dict(data.get("settings") or {})
        self.prefs.save(self.prefs_path)
        self.config = candidate
        self.config.save(self.config_path)
        self.store.include_broken = self.config.count_broken
        self.apply_timer()
        self.apply_prefs()
        self.fill_settings()
        self.snackbar.show_text("Settings imported")

    def open_data(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder.resolve())))

    def open_replays(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.replay_folder())))

    def closeEvent(self, event):
        self.timer.stop()
        self.hotkeys.close()
        self.overlay.close()
        if self.scanner.thread:
            self.scanner.thread.join(timeout=5)
        self.store.close()
        event.accept()


def button_for(text, action, variant=""):
    widget = QPushButton(text)
    if variant:
        widget.setObjectName(variant)
    widget.clicked.connect(lambda checked=False: action())
    return widget


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LootLedger")
    app.setStyle("Fusion")
    try:
        window = MainWindow()
    except Exception as error:
        QMessageBox.critical(None, "LootLedger could not start", str(error))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
