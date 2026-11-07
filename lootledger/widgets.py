"""Material 3 widgets: cards, buttons, switches, segmented controls, snackbar, charts and the dashboard grid."""
from PySide6.QtCore import QMimeData, QPointF, QRectF, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QButtonGroup, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton, QTableView, QToolTip,
                               QVBoxLayout, QWidget)

from . import theme
from .prefs import elapsed

DRAG_PREFIX = "lootledger-widget:"


def label(text="", name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def retone(widget, name):
    """Change a label's role (its stylesheet rule) after it exists."""
    widget.setObjectName(name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def icon_button(name, tip, action=None, checkable=False):
    """Material Symbols icon button. The icon is its ligature name; the tip is the accessible name."""
    widget = QPushButton(name)
    widget.setObjectName("iconButton")
    widget.setToolTip(tip)
    widget.setAccessibleName(tip)
    widget.setCheckable(checkable)
    if action:
        widget.clicked.connect(lambda checked=False: action())
    return widget


def button(text, action, variant="", tip=""):
    widget = QPushButton(text)
    if variant:
        widget.setObjectName(variant)
    if tip:
        widget.setToolTip(tip)
    widget.clicked.connect(lambda checked=False: action())
    return widget


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def fill(combo, items):
    """Replace a combo's items without emitting signals, keeping the current choice when it still exists."""
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for text, data in items:
        combo.addItem(text, data)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)


def make_table():
    view = QTableView()
    view.verticalHeader().hide()
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setShowGrid(False)
    view.setSortingEnabled(True)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    view.horizontalHeader().setResizeContentsPrecision(60)  # measure columns from the first rows only; thousands of rows would stall restyling
    view.horizontalHeader().setStretchLastSection(True)
    view.setMinimumHeight(160)
    return view


def bar_rows(layout, rows):
    """Aligned rows of (name, value, text, colour) with bars scaled to the largest value."""
    peak = max((row[1] for row in rows), default=0) or 1
    for index, (name, value, text, color) in enumerate(rows):
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(round(1000 * value / peak))
        bar.setTextVisible(False)
        bar.setMinimumWidth(40)
        if color:
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}")
        value_label = label(text, "muted")
        value_label.setWordWrap(True)
        layout.addWidget(label(name), index, 0)
        layout.addWidget(bar, index, 1)
        layout.addWidget(value_label, index, 2)
    layout.setColumnStretch(1, 1)


class Card(QFrame):
    """A filled M3 card with a title row. Editing tools (drag, width, remove) show only on the Overview page."""
    removed = Signal(str)
    resized = Signal(str, int)

    def __init__(self, title, icon=None, accent=False):
        super().__init__()
        t = theme.CURRENT
        self.key, self.span = "", 1
        self.setObjectName("cardAccent" if accent else "card")
        self.setAccessibleName(title)
        # A fixed floor, not the content's width, so narrow windows reflow instead of overflowing the page.
        self.setMinimumWidth(160)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.sp["l"], t.sp["l"], t.sp["l"], t.sp["l"])
        outer.setSpacing(t.sp["s"])
        head = QHBoxLayout()
        head.setSpacing(t.sp["s"])
        if icon:
            head.addWidget(label(icon, "iconOnAccent" if accent else "icon"))
        head.addWidget(label(title, "onAccent" if accent else "cardTitle"))
        head.addStretch()
        self.tools = QWidget()
        tools = QHBoxLayout(self.tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(0)
        self.handle = DragHandle(self)
        self.size_button = icon_button("zoom_out_map", "Change width", lambda: self.resized.emit(self.key, 3 - self.span))
        self.remove_button = icon_button("close", "Remove from dashboard", lambda: self.removed.emit(self.key))
        for widget in (self.handle, self.size_button, self.remove_button):
            tools.addWidget(widget)
        self.tools.hide()
        head.addWidget(self.tools)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(t.sp["s"])
        outer.addLayout(self.body)

    def set_editing(self, on):
        self.tools.setVisible(on)

    def refresh(self, ctx):
        """Subclasses redraw their content from ctx.snap (see panels.py)."""


class DragHandle(QPushButton):
    """Starts a drag that moves its card; DashGrid.dropEvent does the reordering."""

    def __init__(self, card):
        super().__init__("drag_indicator")
        self.card = card
        self._press = None
        self.setObjectName("iconButton")
        self.setToolTip("Drag to move")
        self.setAccessibleName("Drag to move")

    def mousePressEvent(self, event):
        self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press and (event.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance():
            self._press = None
            mime = QMimeData()
            mime.setText(DRAG_PREFIX + self.card.key)
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
        else:
            super().mouseMoveEvent(event)


class DashGrid(QWidget):
    """Cards placed in columns that depend on the width, each spanning one or two columns."""
    changed = Signal(list)  # card keys in their new order, after a drag

    def __init__(self, min_column=270):
        super().__init__()
        self.min_column = min_column
        self.cards = []
        self._columns = 0
        self.setAcceptDrops(True)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(theme.CURRENT.sp["m"])

    def set_cards(self, cards):
        keep = set(cards)
        for card in self.cards:
            if card not in keep:
                card.deleteLater()
        self.cards = list(cards)
        for card in self.cards:
            card.setParent(self)
        self.reflow(force=True)

    def reflow(self, force=False):
        gap = self.grid.spacing()
        columns = max(1, (self.width() + gap) // (self.min_column + gap))
        if columns == self._columns and not force:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for column in range(max(columns, 12)):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        row = col = 0
        for card in self.cards:
            span = min(card.span, columns)
            if col + span > columns:
                row, col = row + 1, 0
            self.grid.addWidget(card, row, col, 1, span)
            col += span

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def dragEnterEvent(self, event):
        if event.mimeData().hasText() and event.mimeData().text().startswith(DRAG_PREFIX):
            event.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, event):
        key = event.mimeData().text()[len(DRAG_PREFIX):]
        target = self.childAt(event.position().toPoint())
        while target is not None and target not in self.cards:
            target = target.parentWidget()
        if target is not None and target.key == key:
            return
        order = [card.key for card in self.cards if card.key != key]
        index = order.index(target.key) if target is not None else len(order)
        order.insert(index, key)
        event.acceptProposedAction()
        self.changed.emit(order)


class Switch(QAbstractButton):
    """M3 switch: a checkable track with a thumb."""

    def __init__(self, checked=False, tip=""):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(52, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip)
        self.setAccessibleName(tip or "Switch")

    def paintEvent(self, event):
        c = theme.CURRENT.c
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(2, 6, 48, 20)
        if on:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["primary"]))
        else:
            painter.setPen(QPen(QColor(c["outline"]), 2))
            painter.setBrush(QColor(c["surface_container_highest"]))
        painter.drawRoundedRect(track, 10, 10)
        center_x, radius = (40, 8) if on else (18, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["on_primary"] if on else c["outline"]))
        painter.drawEllipse(QPointF(center_x, 16), radius, radius)
        if self.hasFocus():
            painter.setPen(QPen(QColor(c["primary"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0, 4, 52, 24), 12, 12)


class Segmented(QFrame):
    """Exclusive segmented buttons. Emits the chosen key."""
    changed = Signal(str)

    def __init__(self, options, current, tip=""):
        super().__init__()
        self.setObjectName("segmented")
        self.setAccessibleName(tip)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for key, text in options:
            item = QPushButton(text)
            item.setObjectName("segment")
            item.setCheckable(True)
            item.setChecked(key == current)
            item.setToolTip(tip)
            item.clicked.connect(lambda checked=False, k=key: self.changed.emit(k))
            self.group.addButton(item)
            layout.addWidget(item)
            self.buttons[key] = item


class Snackbar(QFrame):
    """A short confirmation at the bottom of the window that disappears by itself."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("snackbar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        self.text = label("", "snackText")
        layout.addWidget(self.text)
        self.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_text(self, text, ms=3500):
        self.text.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 24)
        self.show()
        self.raise_()
        self.timer.start(ms)


class SeriesChart(QWidget):
    """Bars, a line or an area over labelled points. Bars grow in when data changes (unless motion is off)."""

    def __init__(self, empty):
        super().__init__()
        self.empty = empty
        self.points, self.style, self.fmt = [], "bar", str
        self.progress, self.hover = 1.0, -1
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        self.anim = QVariantAnimation(self)
        self.anim.valueChanged.connect(self._step)

    def set_data(self, points, style, fmt=str):
        points = list(points)
        self.fmt = fmt
        if points == self.points and style == self.style:
            self.update()
            return
        self.points, self.style = points, style
        total = sum(value for _, value in points)
        self.setAccessibleDescription(f"{fmt(total)} chests over {len(points)} periods")
        if theme.CURRENT.motion and any(value for _, value in points):
            self.anim.stop()
            self.anim.setStartValue(0.0)
            self.anim.setEndValue(1.0)
            self.anim.setDuration(280)
            self.anim.start()
        else:
            self.progress = 1.0
        self.update()

    def _step(self, value):
        self.progress = float(value)
        self.update()

    def paintEvent(self, event):
        c = theme.CURRENT.c
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        peak = max((value for _, value in self.points), default=0)
        if not peak:
            painter.setPen(QColor(c["on_surface_variant"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty)
            return
        top, bottom = 12, height - 24
        count = len(self.points)
        slot = width / count

        def y_of(value):
            return bottom - (bottom - top) * value / peak * self.progress

        painter.setPen(QPen(QColor(c["outline_variant"]), 1))
        painter.drawLine(QPointF(0, bottom), QPointF(width, bottom))
        color = QColor(c["primary"])
        if self.style == "bar":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            bar = max(3.0, slot * .68)
            for index, (_, value) in enumerate(self.points):
                if value <= 0:
                    continue
                height_px = max(2.0, bottom - y_of(value))
                x = index * slot + (slot - bar) / 2
                painter.drawRoundedRect(QRectF(x, bottom - height_px, bar, height_px), min(bar / 2, 6), min(bar / 2, 6))
        else:
            xs = [(index + .5) * slot for index in range(count)]
            path = QPainterPath(QPointF(xs[0], y_of(self.points[0][1])))
            for x, (_, value) in zip(xs[1:], self.points[1:]):
                path.lineTo(x, y_of(value))
            if self.style == "area":
                area = QPainterPath(path)
                area.lineTo(xs[-1], bottom)
                area.lineTo(xs[0], bottom)
                area.closeSubpath()
                fill = QColor(color)
                fill.setAlphaF(.25)
                painter.fillPath(area, fill)
            painter.setPen(QPen(color, 2.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            for x, (_, value) in zip(xs, self.points):
                painter.drawEllipse(QPointF(x, y_of(value)), 3, 3)
        painter.setPen(QColor(c["on_surface_variant"]))
        step = max(1, count // 6)
        for index in range(0, count, step):
            left = min(max((index + .5) * slot - 40, 0), max(width - 80, 0))  # keep edge labels inside the chart
            painter.drawText(QRectF(left, bottom + 4, 80, 18), Qt.AlignmentFlag.AlignCenter, self.points[index][0])

    def mouseMoveEvent(self, event):
        if not self.points:
            return
        index = min(len(self.points) - 1, max(0, int(event.position().x() / (self.width() / len(self.points)))))
        if index != self.hover:
            self.hover = index
            text, value = self.points[index]
            QToolTip.showText(event.globalPosition().toPoint(), f"{text}: {self.fmt(value)}", self)

    def leaveEvent(self, event):
        self.hover = -1
        QToolTip.hideText()
        super().leaveEvent(event)


class Donut(QWidget):
    """Share of each chest type, with a total in the middle."""

    def __init__(self):
        super().__init__()
        self.slices, self.center, self.caption = [], "", ""
        self.setMinimumSize(150, 150)

    def set_slices(self, slices, center, caption):
        self.slices, self.center, self.caption = list(slices), center, caption
        self.setAccessibleDescription(f"{center} {caption}")
        self.update()

    def paintEvent(self, event):
        c = theme.CURRENT.c
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 8
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        total = sum(value for _, value, _ in self.slices)
        if total:
            angle = 90 * 16
            for _, value, color in self.slices:
                span = round(-360 * 16 * value / total)
                painter.setPen(QPen(QColor(c["surface_container_high"]), 2))
                painter.setBrush(QColor(color))
                painter.drawPie(rect, angle, span)
                angle += span
        else:
            painter.setPen(QPen(QColor(c["outline_variant"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect)
        hole = rect.adjusted(side * .2, side * .2, -side * .2, -side * .2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["surface_container_high"]))
        painter.drawEllipse(hole)
        top = QRectF(hole.left(), hole.top(), hole.width(), hole.height() * .56)
        bottom = QRectF(hole.left(), hole.top() + hole.height() * .56, hole.width(), hole.height() * .44)
        font = QFont(painter.font())
        font.setPixelSize(max(12, round(side * .14)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(c["on_surface"]))
        painter.drawText(top, Qt.AlignmentFlag.AlignCenter, self.center)
        font.setPixelSize(max(10, round(side * .075)))
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(c["on_surface_variant"]))
        painter.drawText(bottom, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.caption)


class Heatmap(QWidget):
    """Chests by weekday (rows) and hour (columns), darker for more."""
    DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    LEFT, TOP = 40, 20

    def __init__(self):
        super().__init__()
        self.grid, self.fmt = [[0] * 24 for _ in range(7)], str
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        self.setAccessibleName("Chests by weekday and hour")

    def set_grid(self, grid, fmt):
        self.grid, self.fmt = grid, fmt
        self.setAccessibleDescription(f"{fmt(sum(map(sum, grid)))} chests in total")
        self.update()

    def _sizes(self):
        return (self.width() - self.LEFT) / 24, (self.height() - self.TOP) / 7

    def paintEvent(self, event):
        c = theme.CURRENT.c
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell_w, cell_h = self._sizes()
        peak = max(map(max, self.grid), default=0)
        painter.setPen(QColor(c["on_surface_variant"]))
        for day, name in enumerate(self.DAYS):
            painter.drawText(QRectF(0, self.TOP + day * cell_h, self.LEFT - 6, cell_h),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, name)
        for hour in (0, 6, 12, 18):
            painter.drawText(QRectF(self.LEFT + hour * cell_w, 0, cell_w * 6, self.TOP),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{hour:02d}:00")
        painter.setPen(Qt.PenStyle.NoPen)
        for day in range(7):
            for hour in range(24):
                value = self.grid[day][hour]
                shade = theme.mix(c["surface_container_highest"], c["primary"], .15 + .85 * value / peak) if value and peak else c["surface_container_highest"]
                painter.setBrush(QColor(shade))
                painter.drawRoundedRect(QRectF(self.LEFT + hour * cell_w + 2, self.TOP + day * cell_h + 2,
                                               cell_w - 4, cell_h - 4), 4, 4)

    def mouseMoveEvent(self, event):
        cell_w, cell_h = self._sizes()
        hour = int((event.position().x() - self.LEFT) // cell_w) if cell_w else -1
        day = int((event.position().y() - self.TOP) // cell_h) if cell_h else -1
        if 0 <= day < 7 and 0 <= hour < 24:
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{self.DAYS[day]} {hour:02d}:00 · {self.fmt(self.grid[day][hour])} chests", self)
        else:
            QToolTip.hideText()


class Sparkline(QWidget):
    """A small line of recent values with a soft fill."""

    def __init__(self):
        super().__init__()
        self.values = []
        self.setFixedHeight(40)

    def set_values(self, values):
        self.values = list(values)
        self.update()

    def paintEvent(self, event):
        c = theme.CURRENT.c
        values, peak = self.values, max(self.values, default=0)
        if len(values) < 2 or not peak:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        step = width / (len(values) - 1)

        def y_of(value):
            return height - 4 - (height - 8) * value / peak

        path = QPainterPath(QPointF(0, y_of(values[0])))
        for index, value in enumerate(values[1:], 1):
            path.lineTo(index * step, y_of(value))
        fill = QPainterPath(path)
        fill.lineTo(width, height)
        fill.lineTo(0, height)
        fill.closeSubpath()
        area = QColor(c["primary"])
        area.setAlphaF(.18)
        painter.fillPath(fill, area)
        painter.setPen(QPen(QColor(c["primary"]), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class Timeline(QWidget):
    """Openings placed along a match: one tick each, coloured by chest type. Marks are (seconds, type, text)."""
    PAD = 12

    def __init__(self, empty):
        super().__init__()
        self.empty, self.marks, self.duration = empty, [], 1.0
        self.setMinimumHeight(72)
        self.setMouseTracking(True)

    def set_marks(self, marks, duration):
        self.marks = sorted(marks, key=lambda mark: mark[0])
        self.duration = max(float(duration or 0), 1.0)
        self.update()

    def _x(self, offset):
        span = max(self.width() - 2 * self.PAD, 1)
        return self.PAD + span * min(max(offset / self.duration, 0.0), 1.0)

    def paintEvent(self, event):
        c = theme.CURRENT.c
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.height() - 22
        if not self.marks:
            painter.setPen(QColor(c["on_surface_variant"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty)
            return
        painter.setPen(QPen(QColor(c["outline_variant"]), 1))
        painter.drawLine(QPointF(self.PAD, base), QPointF(self.width() - self.PAD, base))
        for offset, name, _ in self.marks:
            x = self._x(offset)
            painter.setPen(QPen(QColor(theme.CURRENT.type_color(name)), 3))
            painter.drawLine(QPointF(x, 12), QPointF(x, base))
        painter.setPen(QColor(c["on_surface_variant"]))
        painter.drawText(QRectF(self.PAD, base + 4, 80, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "0:00")
        painter.drawText(QRectF(self.width() - self.PAD - 80, base + 4, 80, 18),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, elapsed(self.duration))

    def mouseMoveEvent(self, event):
        x = event.position().x()
        nearest = min(self.marks, key=lambda mark: abs(self._x(mark[0]) - x), default=None)
        if nearest and abs(self._x(nearest[0]) - x) <= 6:
            QToolTip.showText(event.globalPosition().toPoint(), f"{elapsed(nearest[0])} · {nearest[2]}", self)
        else:
            QToolTip.hideText()
