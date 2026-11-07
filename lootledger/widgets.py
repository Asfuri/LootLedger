"""Material 3 widgets: cards, buttons, switches, segmented controls, snackbar, charts and the dashboard grid."""
import math

from PySide6.QtCore import (QEvent, QMimeData, QObject, QPoint, QPointF, QPropertyAnimation, QRectF,
                            QTimer, QVariantAnimation, Qt, Signal)
from PySide6.QtGui import QColor, QDrag, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QFrame,
                               QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton, QTableView,
                               QVBoxLayout, QWidget)

from . import theme
from .controls import RowDelegate, Segmented, hide_tip, show_tip  # noqa: F401 (Segmented re-exported)
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
            item.widget().hide()  # deleteLater waits for the event loop; until then the old text would still paint
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


def wrapped(widget):
    widget.setWordWrap(True)
    return widget


class FilterBar(QWidget):
    """A search field and its filters on one row when they fit; otherwise the search gets its own row above,
    so no control is squeezed until its text is cut."""

    def __init__(self, search, controls):
        super().__init__()
        self.search, self.controls, self.wrapped = search, list(controls), None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(theme.CURRENT.sp["s"])
        if search is not None:
            search.setMinimumWidth(220)
        self.place(False)

    def needed(self):
        widths = [w.sizeHint().width() for w in self.controls]
        if self.search is not None:
            widths.append(self.search.minimumWidth())
        return sum(widths) + self.grid.spacing() * len(widths)

    def place(self, wrapped):
        if wrapped == self.wrapped:
            return
        self.wrapped = wrapped
        for widget in self.controls + ([self.search] if self.search is not None else []):
            self.grid.removeWidget(widget)
        for column in range(self.grid.columnCount()):
            self.grid.setColumnStretch(column, 0)
        row, column = (1, 0) if wrapped and self.search is not None else (0, 1 if self.search is not None else 0)
        if self.search is not None:
            self.grid.addWidget(self.search, 0, 0, 1, len(self.controls) + 1 if wrapped else 1)
            if not wrapped:
                self.grid.setColumnStretch(0, 1)
        for index, widget in enumerate(self.controls):
            self.grid.addWidget(widget, row, column + index)
        if wrapped or self.search is None:
            self.grid.setColumnStretch(column + len(self.controls), 1)  # left-aligned, the rest is space

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place(event.size().width() < self.needed())


class _FitColumns(QObject):
    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            fit_columns(self.parent())  # the view, or its viewport when a scrollbar appears or goes
        return False


def fit_columns(view):
    """Columns as wide as their contents when they fit; otherwise they share the width and long text elides,
    so a table never scrolls sideways."""
    header = view.horizontalHeader()
    needs = [min(max(view.sizeHintForColumn(c), header.sectionSizeHint(c)), 280) for c in range(header.count())]
    if needs:
        needs[-1] = min(needs[-1], 120)  # the last column stretches to fill whatever is left
    room = view.viewport().width()
    if sum(needs) <= room:
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(header.count() - 1, QHeaderView.ResizeMode.Interactive)  # fills what is left
        return
    # Narrow: the first column (what the row is) keeps its width if it can; the others shrink by the same share.
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    first = min(needs[0], room * 35 // 100)
    rest = sum(needs[1:]) or 1
    widths = [first] + [max(36, need * (room - first) // rest) for need in needs[1:]]
    widths[widths.index(max(widths))] -= max(0, sum(widths) - room)  # the 36 px floor can overshoot a little
    for column, width in enumerate(widths):
        header.resizeSection(column, width)


def autofit(view):
    """Refit the columns whenever the table is resized or shown (call fit_columns after new rows too)."""
    view.setItemDelegate(RowDelegate(view))  # hover and selection as one rounded row highlight
    view.verticalHeader().setDefaultSectionSize(theme.CURRENT.btn_h)  # row height follows density
    view.setMouseTracking(True)
    view._fit = _FitColumns(view)
    view.installEventFilter(view._fit)
    view.viewport().installEventFilter(view._fit)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setTextElideMode(Qt.TextElideMode.ElideRight)
    return view


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
    return autofit(view)


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
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; border-radius: {theme.CURRENT.r['xs']}px; }}")
        value_label = label(text, "muted")
        value_label.setWordWrap(True)
        layout.addWidget(wrapped(label(name)), index, 0)
        layout.addWidget(bar, index, 1)
        layout.addWidget(value_label, index, 2)
    layout.setColumnStretch(1, 1)


EMPHASIZED = theme.EMPHASIZED


def draw_in(widget, duration=700):
    """Run widget.progress from 0 to 1 so a chart draws in; jump straight to 1 unless motion is Full."""
    if not hasattr(widget, "_draw"):
        widget._draw = QVariantAnimation(widget)
        widget._draw.setStartValue(0.0)
        widget._draw.setEndValue(1.0)
        widget._draw.setEasingCurve(EMPHASIZED)
        widget._draw.valueChanged.connect(lambda value: (setattr(widget, "progress", value), widget.update()))
    widget._draw.stop()
    widget.progress = 0.0 if theme.CURRENT.full_motion else 1.0
    if theme.CURRENT.full_motion:
        widget._draw.setDuration(duration)
        widget._draw.start()
    widget.update()


def fade_in(widget, delay=0, duration=260):
    """Opacity 0 -> 1 after a delay (staggered entrances). The effect is removed when done, so painting stays cheap."""
    if not theme.CURRENT.full_motion:
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(EMPHASIZED)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    QTimer.singleShot(delay, anim.start)


def round_pen(color, width):
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)  # QPen() takes no cap keyword in PySide6
    return pen


class Ring(QWidget):
    """Progress towards a goal: an arc that sweeps to its share, the numbers in the middle."""

    def __init__(self):
        super().__init__()
        self.share, self.text, self.caption, self.progress = 0.0, "", "", 1.0
        self.setMinimumSize(110, 110)

    def set_value(self, share, text, caption):
        if (share, text) != (self.share, self.text):
            self.share, self.text, self.caption = share, text, caption
            self.setAccessibleName(f"{text} {caption}")
            draw_in(self)
        self.update()

    def paintEvent(self, event):
        c = theme.CURRENT.c
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 12
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        painter.setPen(round_pen(QColor(c["surface_container_highest"]), 10))
        painter.drawArc(rect, 0, 360 * 16)
        if self.share:
            painter.setPen(round_pen(QColor(c["primary"]), 10))
            painter.drawArc(rect, 90 * 16, round(-360 * 16 * self.share * self.progress))
        painter.setPen(QColor(c["on_surface"]))
        font = QFont(painter.font())
        font.setPixelSize(max(12, round(side * .2)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(rect.adjusted(0, -side * .08, 0, -side * .08), Qt.AlignmentFlag.AlignCenter, self.text)
        font.setPixelSize(max(10, round(side * .1)))
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(c["on_surface_variant"]))
        painter.drawText(rect.adjusted(0, side * .22, 0, side * .22), Qt.AlignmentFlag.AlignCenter, self.caption)


class Pulse(QWidget):
    """A status dot. It breathes while a match is live; with motion off it stays solid."""

    def __init__(self, size=12):
        super().__init__()
        self.setFixedSize(size, size)
        self.color, self.level = QColor(theme.CURRENT.c["outline"]), 1.0
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(1.0)
        self.anim.setKeyValueAt(.5, .3)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(1400)
        self.anim.setLoopCount(-1)
        self.anim.valueChanged.connect(self._step)

    def _step(self, value):
        self.level = value
        self.update()

    def set_color(self, color, pulsing):
        self.color = QColor(color)
        if pulsing and theme.CURRENT.full_motion:
            if self.anim.state() != QVariantAnimation.State.Running:
                self.anim.start()
        else:
            self.anim.stop()
            self.level = 1.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.color)
        color.setAlphaF(self.level)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(1, 1, self.width() - 2, self.height() - 2))


class Card(QFrame):
    """A filled M3 card with a title row. Editing tools (drag, width, remove) show only on the Overview page."""
    removed = Signal(str)
    resized = Signal(str, int)
    moved = Signal(str, int)  # -1 earlier, +1 later: the keyboard alternative to dragging

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
        earlier = icon_button("arrow_back", "Move earlier", lambda: self.moved.emit(self.key, -1))
        later = icon_button("arrow_forward", "Move later", lambda: self.moved.emit(self.key, 1))
        self.earlier, self.later = earlier, later
        for widget in (self.handle, earlier, later, self.size_button, self.remove_button):
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

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Resize) and self.width() > 0:
            # Grids don't ask for height-for-width, so wrapped text would overflow narrow cards: reserve it.
            need = self.layout().heightForWidth(self.width())
            if need > 0 and need != self.minimumHeight():
                self.setMinimumHeight(need)
        return result


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
        self.marker = QFrame(self)  # shows where a dragged card will land
        self.marker.setObjectName("dropMarker")
        self.marker.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.marker.hide()
        self.entered = False

    def set_cards(self, cards):
        keep = set(cards)
        for card in self.cards:
            if card not in keep:
                card.deleteLater()
        self.cards = list(cards)
        for card in self.cards:
            card.setParent(self)
        self.reflow(force=True)
        if not self.entered and self.cards:
            self.entered = True  # first fill only: cards arrive one after another instead of all at once
            for index, card in enumerate(self.cards):
                fade_in(card, delay=min(index, 10) * 40)

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

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)
        target = self.childAt(event.position().toPoint())
        while target is not None and target not in self.cards:
            target = target.parentWidget()
        if target is not None:
            self.marker.setGeometry(target.geometry())
            self.marker.show()
            self.marker.raise_()

    def dragLeaveEvent(self, event):
        self.marker.hide()

    def dropEvent(self, event):
        self.marker.hide()
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
        painter.drawRoundedRect(track, theme.pill(track.height()), theme.pill(track.height()))
        center_x, radius = (40, 8) if on else (18, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["on_primary"] if on else c["outline"]))
        painter.drawEllipse(QPointF(center_x, 16), radius, radius)
        if self.hasFocus():
            painter.setPen(QPen(QColor(c["primary"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0, 4, 52, 24), theme.pill(24), theme.pill(24))





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
        self.timer.timeout.connect(self.leave)

    def show_text(self, text, ms=3500):
        self.text.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        end = QPoint((parent.width() - self.width()) // 2, parent.height() - self.height() - 24)
        arriving = theme.CURRENT.motion and not self.isVisible()
        self.show()
        self.raise_()
        self.slide(end + QPoint(0, 24) if arriving else end, end)
        self.timer.start(ms)

    def slide(self, start, end, then=None):
        self.anim = QPropertyAnimation(self, b"pos", self)
        self.anim.setDuration(220 if theme.CURRENT.motion and start != end else 0)
        self.anim.setStartValue(start)
        self.anim.setEndValue(end)
        self.anim.setEasingCurve(EMPHASIZED)
        if then:
            self.anim.finished.connect(then)
        self.anim.start()

    def leave(self):
        """Slide down and out, instead of vanishing."""
        if not theme.CURRENT.motion:
            self.hide()
            return
        self.slide(self.pos(), self.pos() + QPoint(0, self.height() + 24), self.hide)


class SeriesChart(QWidget):
    """Bars, a line, a smooth line or an area over labelled points, with a crosshair and a tooltip per point.

    Hover it, or focus it and use Left/Right (Home/End), to read each point.
    """
    PAD = 12

    def __init__(self, empty):
        super().__init__()
        self.empty = empty
        self.points, self.details, self.style, self.fmt = [], [], "bar", str
        self.progress, self.hover = 1.0, -1
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.anim = QVariantAnimation(self)
        self.anim.setEasingCurve(EMPHASIZED)
        self.anim.valueChanged.connect(self._step)

    def set_data(self, points, style, fmt=str, details=None):
        """points: (label, value); details: extra tooltip lines per point (matches, change)."""
        points = list(points)
        self.fmt = fmt
        self.details = list(details) if details else [[] for _ in points]
        if points == self.points and style == self.style:
            self.update()
            return
        self.points, self.style = points, style
        self.hover = min(self.hover, len(points) - 1)
        total = sum(value for _, value in points)
        self.setAccessibleDescription(f"{fmt(total)} chests over {len(points)} periods")
        if theme.CURRENT.full_motion and any(value for _, value in points):
            self.anim.stop()
            self.anim.setStartValue(0.0)
            self.anim.setEndValue(1.0)
            self.anim.setDuration(600)
            self.anim.start()
        else:
            self.progress = 1.0
        self.update()

    def _step(self, value):
        self.progress = float(value)
        self.update()

    def _frame(self):
        return self.PAD, self.width() - self.PAD, 14, self.height() - 26

    def x_of(self, index):
        left, right, _, _ = self._frame()
        return left + (index + .5) * (right - left) / max(len(self.points), 1)

    def y_of(self, value, peak):
        _, _, top, bottom = self._frame()
        return bottom - (bottom - top) * value / peak * self.progress if peak else bottom

    def _path(self, xs, ys, smooth):
        path = QPainterPath(QPointF(xs[0], ys[0]))
        for i in range(1, len(xs)):
            if smooth:  # Catmull-Rom through the points, as cubic Beziers
                x0, y0 = xs[max(i - 2, 0)], ys[max(i - 2, 0)]
                x3, y3 = xs[min(i + 1, len(xs) - 1)], ys[min(i + 1, len(xs) - 1)]
                c1 = QPointF(xs[i - 1] + (xs[i] - x0) / 6, ys[i - 1] + (ys[i] - y0) / 6)
                c2 = QPointF(xs[i] - (x3 - xs[i - 1]) / 6, ys[i] - (y3 - ys[i - 1]) / 6)
                path.cubicTo(c1, c2, QPointF(xs[i], ys[i]))
            else:
                path.lineTo(xs[i], ys[i])
        return path

    def paintEvent(self, event):
        t = theme.CURRENT
        c = t.c
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, top, bottom = self._frame()
        peak = max((value for _, value in self.points), default=0)
        if not peak:
            painter.setPen(QColor(c["on_surface_variant"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty)
            return
        count = len(self.points)
        slot = (right - left) / count
        grid = QPen(theme.layer(c["outline_variant"], .7), 1, Qt.PenStyle.DashLine)
        painter.setPen(grid)
        for share in (.25, .5, .75):
            y = bottom - (bottom - top) * share
            painter.drawLine(QPointF(left, y), QPointF(right, y))
        painter.setPen(QPen(QColor(c["outline_variant"]), 1))
        painter.drawLine(QPointF(left, bottom), QPointF(right, bottom))
        if 0 <= self.hover < count:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.layer(c["on_surface"], .06))
            painter.drawRoundedRect(QRectF(left + self.hover * slot, top - 4, slot, bottom - top + 4), t.r["sm"], t.r["sm"])
        color = QColor(c["primary"])
        xs = [self.x_of(i) for i in range(count)]
        ys = [self.y_of(value, peak) for _, value in self.points]
        if self.style == "bar":
            bar = max(3.0, slot * .64)
            radius = min(bar / 2, t.r["sm"])
            painter.setPen(Qt.PenStyle.NoPen)
            for index, (x, y) in enumerate(zip(xs, ys)):
                if self.points[index][1] <= 0:
                    continue
                height_px = max(2.0, bottom - y)
                rect = QRectF(x - bar / 2, bottom - height_px, bar, height_px)
                corner = min(radius, height_px / 2)
                painter.setBrush(color if index == self.hover or self.hover < 0 else theme.layer(c["primary"], .75))
                painter.drawRoundedRect(rect, corner, corner)
                painter.drawRect(QRectF(rect.left(), rect.bottom() - corner, bar, corner))  # rounded top, flat base
        else:
            path = self._path(xs, ys, self.style in ("smooth", "area"))
            if self.style == "area":
                area = QPainterPath(path)
                area.lineTo(xs[-1], bottom)
                area.lineTo(xs[0], bottom)
                area.closeSubpath()
                gradient = QLinearGradient(0, top, 0, bottom)
                gradient.setColorAt(0, theme.layer(c["primary"], .35))
                gradient.setColorAt(1, theme.layer(c["primary"], 0))
                painter.fillPath(area, gradient)
            pen = QPen(color, 2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            if 0 <= self.hover < count:  # crosshair and the hovered point
                painter.setPen(QPen(theme.layer(c["on_surface"], .45), 1, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(xs[self.hover], top), QPointF(xs[self.hover], bottom))
                painter.setPen(QPen(QColor(c["surface_container_high"]), 2))
                painter.setBrush(color)
                painter.drawEllipse(QPointF(xs[self.hover], ys[self.hover]), 5, 5)
        self._labels(painter, xs, bottom)

    def _labels(self, painter, xs, bottom):
        """Evenly spaced, thinned so they never overlap; the last one stays inside the chart."""
        painter.setPen(QColor(theme.CURRENT.c["on_surface_variant"]))
        fm = painter.fontMetrics()
        widest = max(fm.horizontalAdvance(label) for label, _ in self.points) + 12
        count = len(self.points)
        room = max(self.width() - 2 * self.PAD, 1)
        step = max(1, math.ceil(count * widest / room))
        shown = list(range(0, count, step))
        if shown[-1] != count - 1:
            if xs[count - 1] - xs[shown[-1]] < widest:
                shown[-1] = count - 1  # swap the crowded one for the last label
            else:
                shown.append(count - 1)
        for index in shown:
            text = self.points[index][0]
            width = fm.horizontalAdvance(text)
            x = min(max(xs[index] - width / 2, 0), self.width() - width)
            painter.drawText(QRectF(x, bottom + 6, width + 1, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def _show(self, index):
        if not (0 <= index < len(self.points)):
            return
        peak = max((value for _, value in self.points), default=0)
        label, value = self.points[index]
        lines = [label, f"{self.fmt(value)} chests"] + list(self.details[index] if index < len(self.details) else [])
        x, y = self.x_of(index), self.y_of(value, peak)
        self.setAccessibleDescription(" · ".join(lines))
        show_tip(self, QRectF(x - 8, y - 8, 16, 16), lines)

    def _set_hover(self, index):
        if index != self.hover:
            self.hover = index
            self.update()
        self._show(index)

    def mouseMoveEvent(self, event):
        if self.points:
            left, right, _, _ = self._frame()
            index = int((event.position().x() - left) / ((right - left) / len(self.points)))
            self._set_hover(min(max(index, 0), len(self.points) - 1))

    def leaveEvent(self, event):
        if not self.hasFocus():
            self.hover = -1
            self.update()
        hide_tip(self)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self.points:
            self._set_hover(self.hover if self.hover >= 0 else len(self.points) - 1)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.hover = -1
        self.update()
        hide_tip(self)

    def keyPressEvent(self, event):
        moves = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}
        if self.points and event.key() in moves:
            self._set_hover(min(max(self.hover + moves[event.key()], 0), len(self.points) - 1))
        elif self.points and event.key() in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self._set_hover(0 if event.key() == Qt.Key.Key_Home else len(self.points) - 1)
        else:
            super().keyPressEvent(event)


class Donut(QWidget):
    """Share of each chest type: rounded arc segments with small gaps, the total in the middle.

    Hover a segment, or focus the chart and use Left/Right, to read its type, count and share.
    """

    def __init__(self):
        super().__init__()
        self.slices, self.center, self.caption, self.progress, self.hover = [], "", "", 1.0, -1
        self.fmt = str
        self.setMinimumSize(150, 150)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_slices(self, slices, center, caption, fmt=str):
        changed = list(slices) != self.slices
        self.slices, self.center, self.caption, self.fmt = list(slices), center, caption, fmt
        self.setAccessibleDescription(f"{center} {caption}")
        if changed:
            self.hover = -1
            draw_in(self)  # segments sweep round when the numbers change
        self.update()

    def _geometry(self):
        side = min(self.width(), self.height()) - 8
        thickness = max(10.0, side * .16)
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        return rect.adjusted(thickness / 2, thickness / 2, -thickness / 2, -thickness / 2), thickness, side

    def _spans(self):
        """(start, span) in degrees, clockwise from 12 o'clock, with a small gap between segments."""
        total = sum(value for _, value, _ in self.slices)
        gap = 4.0 if len(self.slices) > 1 else 0.0
        result, angle = [], 90.0
        for _, value, _ in self.slices:
            span = 360.0 * value / total if total else 0.0
            result.append((angle - gap / 2, -(max(span - gap, .5))))
            angle -= span
        return result

    def paintEvent(self, event):
        c = theme.CURRENT.c
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring, thickness, side = self._geometry()
        painter.setPen(QPen(QColor(c["surface_container_highest"]), thickness))
        painter.drawArc(ring, 0, 360 * 16)
        radius = ring.width() / 2
        cap = math.degrees(thickness / 2 / radius) if radius else 0  # round caps reach past the arc's ends
        for index, ((start, span), (_, value, color)) in enumerate(zip(self._spans(), self.slices)):
            span *= self.progress
            if not value or not span:
                continue
            width = thickness + (5 if index == self.hover else 0)
            drawn = span + 2 * cap if abs(span) > 2 * cap else span
            pen = QPen(QColor(color), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap if abs(span) > 2 * cap else Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            begin = start - cap if abs(span) > 2 * cap else start
            painter.drawArc(ring, round(begin * 16), round(drawn * 16))
        hole = ring.adjusted(thickness * .7, thickness * .7, -thickness * .7, -thickness * .7)
        top = QRectF(hole.left(), hole.top(), hole.width(), hole.height() * .56)
        bottom = QRectF(hole.left(), hole.top() + hole.height() * .56, hole.width(), hole.height() * .44)
        font = QFont(painter.font())
        font.setPixelSize(max(12, round(side * .14)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(c["on_surface"]))
        painter.drawText(top, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self.center)
        font.setPixelSize(max(10, round(side * .075)))
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(c["on_surface_variant"]))
        painter.drawText(bottom, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.caption)

    def _index_at(self, point):
        ring, thickness, _ = self._geometry()
        dx, dy = point.x() - ring.center().x(), ring.center().y() - point.y()
        distance = math.hypot(dx, dy)
        if abs(distance - ring.width() / 2) > thickness / 2 + 4:
            return -1
        angle = math.degrees(math.atan2(dy, dx))
        for index, (start, span) in enumerate(self._spans()):
            offset = (start - angle) % 360
            if offset <= -span + 4:
                return index
        return -1

    def _show(self, index):
        if not (0 <= index < len(self.slices)):
            hide_tip(self)
            return
        name, value, _ = self.slices[index]
        total = sum(v for _, v, _ in self.slices) or 1
        lines = [name, f"{self.fmt(value)} chests", f"{value / total:.0%} of {self.fmt(total)}"]
        self.setAccessibleDescription(" · ".join(lines))
        ring, _, _ = self._geometry()
        start, span = self._spans()[index]
        middle = math.radians(start + span / 2)
        point = QPointF(ring.center().x() + math.cos(middle) * ring.width() / 2,
                        ring.center().y() - math.sin(middle) * ring.width() / 2)
        show_tip(self, QRectF(point.x() - 6, point.y() - 6, 12, 12), lines)

    def mouseMoveEvent(self, event):
        index = self._index_at(event.position())
        if index != self.hover:
            self.hover = index
            self.update()
        self._show(index)

    def leaveEvent(self, event):
        self.hover = -1
        self.update()
        hide_tip(self)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self.slices:
            self.hover = max(self.hover, 0)
            self.update()
            self._show(self.hover)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.hover = -1
        self.update()
        hide_tip(self)

    def keyPressEvent(self, event):
        if self.slices and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.hover = (self.hover + (1 if event.key() == Qt.Key.Key_Right else -1)) % len(self.slices)
            self.update()
            self._show(self.hover)
        else:
            super().keyPressEvent(event)


class Heatmap(QWidget):
    """Chests by weekday (rows) and hour (columns). Darker means more; an empty cell keeps the track colour.

    Hover a cell, or focus the map and use the arrow keys, to read it. A legend runs from less to more.
    """
    DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    LEFT, TOP, LEGEND = 40, 20, 26

    def __init__(self):
        super().__init__()
        self.grid, self.matches, self.fmt = [[0] * 24 for _ in range(7)], None, str
        self.hover = None
        self.setMinimumHeight(190)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Chests by weekday and hour")

    def set_grid(self, grid, fmt, matches=None):
        self.grid, self.fmt, self.matches = grid, fmt, matches
        self.setAccessibleDescription(f"{fmt(sum(map(sum, grid)))} chests in total")
        self.update()

    def _sizes(self):
        return (self.width() - self.LEFT) / 24, (self.height() - self.TOP - self.LEGEND) / 7

    def cell_rect(self, day, hour):
        cell_w, cell_h = self._sizes()
        return QRectF(self.LEFT + hour * cell_w + 1.5, self.TOP + day * cell_h + 1.5, cell_w - 3, cell_h - 3)

    def shade(self, value, peak):
        c = theme.CURRENT.c
        if not value or not peak:
            return QColor(c["surface_container_highest"])
        return QColor(theme.mix(c["surface_container_highest"], c["primary"], .25 + .75 * math.sqrt(value / peak)))

    def paintEvent(self, event):
        t = theme.CURRENT
        c = t.c
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
        radius = min(t.r["xs"] + 1, cell_w / 3, cell_h / 3)
        for day in range(7):
            for hour in range(24):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.shade(self.grid[day][hour], peak))
                painter.drawRoundedRect(self.cell_rect(day, hour), radius, radius)
        if self.hover:
            painter.setPen(QPen(QColor(c["on_surface"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.cell_rect(*self.hover).adjusted(-1, -1, 1, 1), radius + 1, radius + 1)
        # legend: less -> more
        y = self.height() - self.LEGEND + 8
        swatch = 14
        painter.setPen(QColor(c["on_surface_variant"]))
        fm = painter.fontMetrics()
        x = self.width() - 5 * (swatch + 3) - fm.horizontalAdvance("More") - 8
        painter.drawText(QRectF(x - fm.horizontalAdvance("Less") - 8, y - 2, fm.horizontalAdvance("Less") + 4, swatch + 4),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "Less")
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(5):
            painter.setBrush(self.shade(step, 4) if step else self.shade(0, 4))
            painter.drawRoundedRect(QRectF(x + step * (swatch + 3), y, swatch, swatch), radius, radius)
        painter.setPen(QColor(c["on_surface_variant"]))
        painter.drawText(QRectF(x + 5 * (swatch + 3) + 4, y - 2, fm.horizontalAdvance("More") + 4, swatch + 4),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "More")

    def _show(self):
        if not self.hover:
            hide_tip(self)
            return
        day, hour = self.hover
        value = self.grid[day][hour]
        played = self.matches[day][hour] if self.matches else 0
        head = f"{self.NAMES[day]}, {hour:02d}:00"
        body = (f"{self.fmt(value)} chests · {played} match{'es' if played != 1 else ''}" if value or played
                else "No matches")
        self.setAccessibleDescription(f"{head} · {body}")
        show_tip(self, self.cell_rect(day, hour), [head, body])

    def mouseMoveEvent(self, event):
        cell_w, cell_h = self._sizes()
        hour = int((event.position().x() - self.LEFT) // cell_w) if cell_w > 0 else -1
        day = int((event.position().y() - self.TOP) // cell_h) if cell_h > 0 else -1
        cell = (day, hour) if 0 <= day < 7 and 0 <= hour < 24 else None
        if cell != self.hover:
            self.hover = cell
            self.update()
        self._show()

    def leaveEvent(self, event):
        if not self.hasFocus():
            self.hover = None
            self.update()
        hide_tip(self)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.hover = self.hover or (0, 12)
        self.update()
        self._show()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.hover = None
        self.update()
        hide_tip(self)

    def keyPressEvent(self, event):
        moves = {Qt.Key.Key_Left: (0, -1), Qt.Key.Key_Right: (0, 1), Qt.Key.Key_Up: (-1, 0), Qt.Key.Key_Down: (1, 0)}
        if event.key() in moves:
            day, hour = self.hover or (0, 12)
            dd, dh = moves[event.key()]
            self.hover = (min(max(day + dd, 0), 6), min(max(hour + dh, 0), 23))
            self.update()
            self._show()
        else:
            super().keyPressEvent(event)


class Sparkline(QWidget):
    """A small line of recent values with a soft fill. Hover it to read a point."""

    def __init__(self):
        super().__init__()
        self.values, self.labels, self.progress, self.hover = [], [], 1.0, -1
        self.setFixedHeight(40)
        self.setMouseTracking(True)

    def set_values(self, values, labels=None):
        self.labels = list(labels or [])
        if list(values) != self.values:
            self.values = list(values)
            draw_in(self, 900)  # the line draws from left to right

    def _points(self):
        values, peak = self.values, max(self.values, default=0)
        width, height = self.width(), self.height()
        step = (width - 8) / (len(values) - 1)
        return [QPointF(4 + i * step, height - 5 - (height - 10) * v / peak) for i, v in enumerate(values)]

    def paintEvent(self, event):
        c = theme.CURRENT.c
        if len(self.values) < 2 or not max(self.values):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        painter.setClipRect(QRectF(0, 0, width * self.progress, height))
        points = self._points()
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        fill = QPainterPath(path)
        fill.lineTo(points[-1].x(), height)
        fill.lineTo(points[0].x(), height)
        fill.closeSubpath()
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0, theme.layer(c["primary"], .28))
        gradient.setColorAt(1, theme.layer(c["primary"], 0))
        painter.fillPath(fill, gradient)
        pen = QPen(QColor(c["primary"]), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        if 0 <= self.hover < len(points):
            painter.setBrush(QColor(c["primary"]))
            painter.setPen(QPen(QColor(c["surface_container_high"]), 2))
            painter.drawEllipse(points[self.hover], 4, 4)

    def mouseMoveEvent(self, event):
        if len(self.values) < 2:
            return
        points = self._points()
        index = min(range(len(points)), key=lambda i: abs(points[i].x() - event.position().x()))
        self.hover = index
        self.update()
        name = self.labels[index] if index < len(self.labels) else ""
        show_tip(self, QRectF(points[index].x() - 5, points[index].y() - 5, 10, 10), [name, f"{self.values[index]:,} chests"])

    def leaveEvent(self, event):
        self.hover = -1
        self.update()
        hide_tip(self)


class Timeline(QWidget):
    """Openings placed along a match: one tick each, coloured by chest type. Marks are (seconds, type, text)."""
    PAD = 12

    def __init__(self, empty):
        super().__init__()
        self.empty, self.marks, self.duration, self.saved = empty, [], 1.0, None
        self.setMinimumHeight(72)
        self.setMouseTracking(True)

    def set_marks(self, marks, duration, saved=None):
        """saved: during a live match, how much of the elapsed time Fortnite has written to the replay."""
        self.marks = sorted(marks, key=lambda mark: mark[0])
        self.duration = max(float(duration or 0), 1.0)
        self.saved = saved
        self.update()

    def _x(self, offset):
        span = max(self.width() - 2 * self.PAD, 1)
        return self.PAD + span * min(max(offset / self.duration, 0.0), 1.0)

    def paintEvent(self, event):
        c = theme.CURRENT.c
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.height() - 22
        if not self.marks and self.saved is not None:  # live: the axis grows, the saved part is filled
            painter.setPen(round_pen(QColor(c["outline_variant"]), 4))
            painter.drawLine(QPointF(self.PAD, base), QPointF(self.width() - self.PAD, base))
            painter.setPen(round_pen(QColor(c["error"]), 4))
            painter.drawLine(QPointF(self.PAD, base), QPointF(self._x(self.saved), base))
            painter.setPen(QColor(c["on_surface_variant"]))
            painter.drawText(QRectF(self.PAD, base + 4, 80, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "0:00")
            painter.drawText(QRectF(self.width() - self.PAD - 120, base + 4, 120, 18),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, elapsed(self.duration))
            return
        elif not self.marks:
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
            mark_x = self._x(nearest[0])
            show_tip(self, QRectF(mark_x - 4, 12, 8, self.height() - 34), [elapsed(nearest[0]), nearest[2]])
        else:
            hide_tip(self)

    def leaveEvent(self, event):
        hide_tip(self)
