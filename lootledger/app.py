from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

from . import replay_reader
from .config import Config, data_dir
from .hotkeys import Hotkeys
from .store import Store
from .widgets import STYLE, BarChart, card, label

VERSION = "0.4"


def button(text, action, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(lambda checked=False: action())
    return widget


def table(headers, stretch=True):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setAlternatingRowColors(True)
    widget.verticalHeader().hide()
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setShowGrid(False)
    header = widget.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch if stretch else QHeaderView.ResizeMode.ResizeToContents)
    return widget


def populate(widget, rows, muted_rows=(), right_from=None):
    widget.setRowCount(len(rows))
    for index, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if right_from is not None and column >= right_from:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if index in muted_rows:
                item.setForeground(Qt.GlobalColor.gray)
            widget.setItem(index, column, item)


def local_time(value, pattern="%d/%m %H:%M"):
    return datetime.fromisoformat(value).astimezone().strftime(pattern)


def minutes(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


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
            error = f"{type(exc).__name__}: {exc}" if not isinstance(exc, (FileNotFoundError, RuntimeError)) else str(exc)
        finally:
            if store:
                store.close()
        self.finished.emit(live, error)


class MainWindow(QMainWindow):
    def __init__(self, folder=None, scan_on_start=True):
        super().__init__()
        self.folder = Path(folder) if folder else data_dir()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.config_path = self.folder / "config.json"
        self.config = Config.read(self.config_path)
        self.store = Store(self.folder / "ledger.sqlite")
        self.store.include_broken = self.config.count_broken
        self.session_start = datetime.now(timezone.utc)
        self.live = None
        self.last_scan = None
        self.scan_error = None
        self.scan_note = "Waiting for the first replay check"
        self.entry_rows = []
        self.scanner = Scanner(self.store.path)
        self.scanner.progress.connect(self.on_scan_progress)
        self.scanner.finished.connect(self.on_scan_finished)

        self.setWindowTitle("LootLedger · Chest tracker")
        self.resize(1240, 860)
        self.setMinimumSize(1000, 680)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(180)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 26, 16, 20)
        side.addWidget(label("LootLedger", "brand"))
        side.addWidget(label("CHEST TRACKER", "muted"))
        side.addSpacing(28)
        self.pages = QStackedWidget()
        self.nav = []
        for index, title in enumerate(("Overview", "Matches", "Openings", "Settings && data")):
            nav = button(title, lambda i=index: self.navigate(i))
            nav.setObjectName("nav")
            nav.setCheckable(True)
            self.nav.append(nav)
            side.addWidget(nav)
        side.addStretch()
        side.addWidget(label("Reads Fortnite replays", "muted"))
        side.addWidget(label(f"v{VERSION} · local only", "muted"))
        layout.addWidget(sidebar)
        layout.addWidget(self.pages)
        self.build_overview()
        self.build_matches()
        self.build_openings()
        self.build_settings()
        self.build_overlay()
        self.hotkeys = Hotkeys(self.on_hotkey)
        QApplication.instance().installNativeEventFilter(self.hotkeys)
        try:
            self.hotkeys.configure(self.config.hotkey_add, self.config.hotkey_undo)
        except ValueError as error:
            self.scan_note = str(error)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scan)
        self.timer.start(self.config.scan_seconds * 1000)
        self.navigate(0)
        self.refresh()
        self.statusBar().showMessage(f"Data: {self.folder}   ·   Replays: {self.replay_folder()}")
        if scan_on_start:
            QTimer.singleShot(150, self.scan)

    # ---- Layout --------------------------------------------------------------------------------

    def page(self, title=None, subtitle=None, scroll=False):
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        content.setObjectName("root")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(14)
        if title:
            layout.addWidget(label(title, "title"))
        if subtitle:
            text = label(subtitle, "muted")
            text.setWordWrap(True)
            layout.addWidget(text)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(content)
            outer_layout.addWidget(area)
        else:
            outer_layout.addWidget(content)
        self.pages.addWidget(outer)
        return layout

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        for number, nav in enumerate(self.nav):
            nav.setChecked(number == index)

    def build_overview(self):
        layout = self.page(scroll=True)
        header = QHBoxLayout()
        self.heading = label("Chest tracker", "title")
        header.addWidget(self.heading, 1)
        self.updated = label("", "muted")
        header.addWidget(self.updated)
        header.addWidget(button("Check now", self.scan))
        header.addWidget(button("Pop-out counter", self.toggle_overlay))
        layout.addLayout(header)
        self.status = label("", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.counters, self.details = {}, {}
        big = QHBoxLayout()
        for key, title, accent in (("current", "current match", False), ("last", "last match", False),
                                   ("all", "chests opened · all time", True)):
            widget, number, detail = card(title, " ", accent=accent)
            big.addWidget(widget)
            self.counters[key], self.details[key] = number, detail
        layout.addLayout(big)
        small = QHBoxLayout()
        for key, title in (("today", "today"), ("matches", "matches analyzed"), ("average", "chests per match"),
                           ("best", "best match"), ("per_hour", "chests per hour played"),
                           ("session", "since LootLedger opened")):
            widget, number, detail = card(title, large=False)
            small.addWidget(widget)
            self.counters[key], self.details[key] = number, detail
        layout.addLayout(small)
        layout.addWidget(label("CHESTS PER DAY (LAST 30 DAYS)", "section"))
        chart_panel = QFrame()
        chart_panel.setObjectName("panel")
        chart_layout = QVBoxLayout(chart_panel)
        self.day_chart = BarChart("Your chests will appear here after your first match with replays on")
        chart_layout.addWidget(self.day_chart)
        layout.addWidget(chart_panel)
        layout.addWidget(label("BY TYPE", "section"))
        self.type_table = table(["Type", "You", "Teammates (seen)"])
        self.type_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.type_table.setMinimumHeight(330)
        self.type_table.horizontalHeaderItem(0).setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header_view = self.type_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.type_table)
        note = label("Teammate counts include only what your replay recorded; chests opened far from you may be missing.", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def build_matches(self):
        layout = self.page("Matches", "One row per replay. Matches are read automatically after Fortnite saves the replay.")
        layout.addWidget(label("CHESTS PER MATCH (LAST 40)", "section"))
        self.match_chart = BarChart("Matches will appear here", height=130, labels=True, max_bar=42)
        layout.addWidget(self.match_chart)
        self.match_table = table(["Date", "Mode", "Place", "Your chests", "Broken open", "Teammates", "Ammo boxes", "Length"])
        layout.addWidget(self.match_table, 1)

    def build_openings(self):
        layout = self.page("Openings", "Every chest you opened, newest first. Use corrections only to fix mistakes; "
                                       "replays are read again without undoing your edits.")
        self.entries = table(["Time", "Type", "How", "Count", "Status", "Details"], stretch=False)
        self.entries.horizontalHeader().setStretchLastSection(True)
        self.entries.doubleClicked.connect(lambda _: self.safe(self.edit_entry))
        layout.addWidget(self.entries, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("Manual +1", lambda: self.safe(self.manual_add)))
        actions.addWidget(button("Undo last", lambda: self.safe(self.undo)))
        actions.addSpacing(16)
        for title, action in (("Remove entry", lambda: self.change_status("undone")),
                              ("Restore entry", lambda: self.change_status("confirmed")),
                              ("Correct entry…", self.edit_entry)):
            actions.addWidget(button(title, lambda fn=action: self.safe(fn)))
        actions.addStretch()
        layout.addLayout(actions)
        self.hotkey_hint = label("", "muted")
        layout.addWidget(self.hotkey_hint)

    def build_settings(self):
        layout = self.page("Settings & data", "LootLedger only reads the replay files Fortnite saves on this PC. "
                                              "No account, no uploads, no game memory, no network interception.", scroll=True)
        how = label("Turn on Fortnite → Settings → Game → Replays → Record Replays. Each finished match is counted "
                    "automatically. Fortnite deletes old replays, but LootLedger keeps the counts once read.", "muted")
        how.setWordWrap(True)
        layout.addWidget(how)
        form = QFormLayout()
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(self.config.replay_folder)
        self.folder_edit.setPlaceholderText(str(replay_reader.default_folder()))
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(button("Browse…", self.pick_folder))
        folder_row.addWidget(button("Open", lambda: self.safe(self.open_replays)))
        form.addRow("Replay folder", folder_row)
        self.broken_box = QCheckBox("Count chests you broke open (loot spilled by your damage) in totals")
        self.broken_box.setChecked(self.config.count_broken)
        form.addRow("Broken chests", self.broken_box)
        self.interval = QSpinBox()
        self.interval.setRange(5, 600)
        self.interval.setSuffix(" s")
        self.interval.setValue(self.config.scan_seconds)
        self.interval.setMaximumWidth(120)
        form.addRow("Check for replays every", self.interval)
        self.hotkey_fields = {}
        for key, title in (("hotkey_add", "Manual +1 hotkey"), ("hotkey_undo", "Undo hotkey")):
            edit = QLineEdit(getattr(self.config, key))
            self.hotkey_fields[key] = edit
            form.addRow(title, edit)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(button("Save settings", lambda: self.safe(self.save_settings), True))
        row.addWidget(button("Read all replays again", lambda: self.safe(self.rescan)))
        row.addStretch()
        layout.addLayout(row)
        data_actions = QGridLayout()
        for index, (title, action) in enumerate((("Export JSON / CSV", self.export_data), ("Create backup", self.backup_data),
                                                 ("Restore backup", self.restore_data), ("Open local data", self.open_data))):
            data_actions.addWidget(button(title, lambda fn=action: self.safe(fn)), index // 2, index % 2)
        layout.addLayout(data_actions)
        note = label("Backups contain matches, openings and your edit history. Restoring first saves a safety copy "
                     "of the current ledger.", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def build_overlay(self):
        self.overlay = QWidget(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.overlay.setWindowTitle("LootLedger counter")
        self.overlay.setObjectName("root")
        self.overlay.setStyleSheet(STYLE)
        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(16, 12, 16, 14)
        overlay_layout.setSpacing(2)
        self.overlay_title = label("Chests opened", "muted")
        self.overlay_count = label("0", "overlayNumber")
        self.overlay_lines = label("", "muted")
        for widget in (self.overlay_title, self.overlay_count, self.overlay_lines):
            overlay_layout.addWidget(widget)
        self.overlay.resize(250, 150)

    # ---- Replay scanning -------------------------------------------------------------------------

    def replay_folder(self):
        return Path(self.config.replay_folder) if self.config.replay_folder else replay_reader.default_folder()

    def scan(self):
        folder = self.replay_folder()
        if not folder.is_dir():
            self.scan_error = (f"Replay folder not found: {folder}. Turn on Record Replays in Fortnite "
                               "(Settings → Game → Replays) and play a match, or choose the folder in Settings.")
            self.refresh()
            return
        if self.scanner.start(folder):
            self.scan_note = "Checking replays…"
            self.refresh_status()

    def on_scan_progress(self, done, total):
        if total > 1:
            self.scan_note = f"Reading replays {done}/{total}…"
            self.refresh_status()

    def on_scan_finished(self, live, error):
        self.live, self.scan_error = live, error
        self.last_scan = datetime.now()
        self.scan_note = ""
        self.refresh()

    def rescan(self):
        if self.scanner.running:
            raise ValueError("A replay check is running; try again in a moment")
        self.store.forget_replay_files()
        self.scan()

    def live_count(self):
        if not self.live:
            return None
        mine, _ = replay_reader.summarize(self.live)
        return sum(1 for e in mine if self.config.count_broken or e["kind"] == "opened")

    # ---- Refresh -------------------------------------------------------------------------------

    def refresh_status(self):
        if self.scan_error:
            text, color = self.scan_error, "#e8b04f"
        elif self.scan_note:
            text, color = self.scan_note, "#8d8f9a"
        elif self.live:
            text, color = ("Match in progress · the count updates whenever Fortnite writes to the replay file", "#7ce7a6")
        else:
            text, color = (f"Watching {self.replay_folder()} · finished matches are added automatically", "#8d8f9a")
        if getattr(self, "partial", 0) and not self.scan_error:
            text += (f"  ·  {self.partial} replay(s) could only be read partly (see Matches); "
                     "update LootLedger if Fortnite changed its replay format")
        self.status.setText("●  " + text)
        self.status.setStyleSheet(f"color: {color};")
        if self.last_scan:
            self.updated.setText(f"Updated {self.last_scan:%H:%M:%S} · auto refresh")

    def refresh(self):
        data = self.store.dashboard(self.session_start)
        self.heading.setText("Chest tracker" + (f" · {data['player']}" if data["player"] else ""))
        live = self.live_count()
        self.counters["current"].setText("–" if live is None else f"{live:,}")
        self.details["current"].setText(
            f"In progress · {replay_reader.mode_name(self.live.get('playlist'))}" if self.live else "No match in progress")
        last = data["last_match"]
        self.counters["last"].setText(f"{data['last']:,}")
        self.details["last"].setText(
            f"{last['meta'].get('mode')} · {local_time(last['started'])}" + (
                f" · #{last['meta']['placement']}" if last["meta"].get("placement") else "") if last else "No match read yet")
        self.counters["all"].setText(f"{data['all']:,}")
        self.details["all"].setText(f"incl. {data['broken']:,} broken open" if data["broken"] and self.config.count_broken
                                    else "searched chests" if not self.config.count_broken else " ")
        self.counters["today"].setText(f"{data['today']:,}")
        self.counters["matches"].setText(f"{data['matches']:,}")
        self.counters["average"].setText(f"{data['average']:,.1f}")
        self.counters["best"].setText(f"{data['best']:,}")
        self.counters["per_hour"].setText(f"{data['per_hour']:,.0f}")
        self.counters["session"].setText(f"+{data['session_total']:,}")
        self.details["session"].setText(f"{data['session_matches']} match{'es' if data['session_matches'] != 1 else ''}")
        self.details["session"].setVisible(True)
        days = data["per_day"]
        self.day_chart.set_values([count for _, count in days], (days[0][0].strftime("%d/%m"), "today"))
        rows, muted = [], set()
        for name in sorted(set(data["types"]) | set(data["team"]), key=lambda n: (-data["types"].get(n, 0), n)):
            rows.append((name, data["types"].get(name, 0), data["team"].get(name, 0)))
        rows.append(("Total chests", data["all"], data["team_total"]))
        if self.config.count_broken:
            muted.add(len(rows))
            rows.append(("      of which broken open (not searched)", data["broken"], ""))
        for name, count in data["containers"].items():
            muted.add(len(rows))
            rows.append((f"{name} (not counted as a chest)", count, ""))
        populate(self.type_table, rows, muted, right_from=1)
        self.refresh_matches()
        self.refresh_entries()
        self.refresh_overlay(data, live)
        self.partial = data["partial"]
        self.refresh_status()

    def refresh_matches(self):
        matches = [m for m in self.store.history() if m["meta"] or m["total"]]
        rows = []
        for m in matches:
            meta = json.loads(m["meta"]) if m["meta"] else {}
            team = sum(c.get("opened", 0) + (c.get("broken", 0) if self.config.count_broken else 0)
                       for c in meta.get("team", {}).values())
            place = f"#{meta['placement']}" + (f" / {meta['total_players']}" if meta.get("total_players") else "") if meta.get("placement") else "–"
            mode = meta.get("mode", "Manual") + ("  (partly read)" if meta and not meta.get("complete", True) else "")
            rows.append((local_time(m["started"]), mode, place, m["total"],
                         m["broken"] if self.config.count_broken else "–", team if meta else "–",
                         meta.get("containers", {}).get("Ammo box", 0) if meta else "–", minutes(m["seconds"])))
        populate(self.match_table, rows, right_from=3)
        self.match_chart.set_values([m["total"] for m in reversed(matches[:40])])

    def refresh_entries(self):
        old_row = self.entries.currentRow()
        old_id = self.entry_rows[old_row]["id"] if 0 <= old_row < len(self.entry_rows) else None
        self.entry_rows = self.store.entries(1000)
        how = {"replay": "Opened", "replay-broken": "Broken open", "manual correction": "Manual", "automatic": "Screen (old)"}
        populate(self.entries, [(local_time(r["created"], "%d/%m %H:%M:%S"), r["chest_type"], how.get(r["source"], r["source"]),
                                 r["amount"], {"confirmed": "Counted", "undone": "Removed"}.get(r["status"], r["status"].capitalize()),
                                 r["reason"].split(" · ", 1)[-1]) for r in self.entry_rows])
        for index, row in enumerate(self.entry_rows):
            if row["id"] == old_id:
                self.entries.selectRow(index)
        keys = [k for k in (self.config.hotkey_add, self.config.hotkey_undo) if k]
        self.hotkey_hint.setText(f"Hotkeys: {self.config.hotkey_add or '—'} = +1 to the latest match, "
                                 f"{self.config.hotkey_undo or '—'} = undo last" if keys else "Hotkeys are off.")

    def refresh_overlay(self, data, live):
        if live is not None:
            self.overlay_title.setText("Chests · current match")
            self.overlay_count.setText(f"{live:,}")
        else:
            self.overlay_title.setText("Chests opened · all time")
            self.overlay_count.setText(f"{data['all']:,}")
        self.overlay_lines.setText(f"This session: +{data['session_total']:,} ({data['session_matches']} matches)\n"
                                   f"Last match: {data['last']:,} chests\nAll time: {data['all']:,}")

    # ---- Actions -------------------------------------------------------------------------------

    def safe(self, action):
        try:
            action()
        except Exception as error:
            QMessageBox.warning(self, "LootLedger", str(error))

    def toggle_overlay(self):
        self.overlay.setVisible(not self.overlay.isVisible())

    def manual_add(self):
        self.store.add_correction()
        self.refresh()

    def undo(self):
        self.store.undo()
        self.refresh()

    def on_hotkey(self, action):
        # Native hotkeys only observe key presses; they never send input to Fortnite.
        self.safe(self.manual_add if action == "add" else self.undo)

    def selected_entry(self):
        row = self.entries.currentRow()
        if not 0 <= row < len(self.entry_rows):
            raise ValueError("Select an entry first")
        return self.entry_rows[row]

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

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Fortnite replay folder", str(self.replay_folder()))
        if path:
            self.folder_edit.setText(path)

    def open_replays(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.replay_folder())))

    def save_settings(self):
        candidate = deepcopy(self.config)
        folder = self.folder_edit.text().strip()
        candidate.replay_folder = "" if folder and Path(folder) == replay_reader.default_folder() else folder
        candidate.count_broken = self.broken_box.isChecked()
        candidate.scan_seconds = self.interval.value()
        for key, edit in self.hotkey_fields.items():
            setattr(candidate, key, edit.text().strip())
        candidate.validate()
        try:
            self.hotkeys.configure(candidate.hotkey_add, candidate.hotkey_undo)
        except ValueError:
            self.hotkeys.configure(self.config.hotkey_add, self.config.hotkey_undo)
            raise
        candidate.save(self.config_path)
        folder_changed = candidate.replay_folder != self.config.replay_folder
        self.config = candidate
        self.store.include_broken = candidate.count_broken
        self.timer.start(candidate.scan_seconds * 1000)
        self.statusBar().showMessage(f"Data: {self.folder}   ·   Replays: {self.replay_folder()}")
        self.refresh()
        if folder_changed:
            self.scan()

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export data", "lootledger.json", "JSON (*.json);;CSV (*.csv)")
        if path:
            self.store.export(path)
            self.statusBar().showMessage("Export saved: " + path)

    def backup_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save ledger backup", "lootledger-backup.sqlite", "SQLite backup (*.sqlite)")
        if path:
            self.store.backup(path)
            self.statusBar().showMessage("Backup saved: " + path)

    def restore_data(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore ledger backup", "", "SQLite backup (*.sqlite)")
        if not path:
            return
        if self.scanner.running:
            raise ValueError("A replay check is running; try again in a moment")
        if QMessageBox.question(self, "Restore backup", "Replace the current ledger with this backup? A safety backup will be saved first.") != QMessageBox.StandardButton.Yes:
            return
        safety = self.store.restore(path)
        self.statusBar().showMessage(f"Backup restored. Previous ledger saved as {safety.name}")
        self.refresh()

    def open_data(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder.resolve())))

    def closeEvent(self, event):
        self.timer.stop()
        self.hotkeys.close()
        self.overlay.close()
        if self.scanner.thread:
            self.scanner.thread.join(timeout=5)
        self.store.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LootLedger")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    try:
        window = MainWindow()
    except Exception as error:
        QMessageBox.critical(None, "LootLedger could not start", str(error))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
