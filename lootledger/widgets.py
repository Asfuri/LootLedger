"""Material 3 widgets: cards, buttons, switches, segmented controls, snackbar, charts and the dashboard grid."""
from PySide6.QtCore import (QEasingCurve, QEvent, QMimeData, QObject, QPoint, QPointF, QPropertyAnimation, QRectF,
                            QTimer, QVariantAnimation, Qt, Signal)
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QButtonGroup, QFrame,
                               QGraphicsOpacityEffect, QGridLayout,
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


def shrinkable(*widgets):
    """Filter controls that may get narrower than their longest item, so filter bars fit small windows."""
    for widget in widgets:
        if hasattr(widget, "setMinimumContentsLength"):
            widget.setSizeAdjustPolicy(widget.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(7)
        else:
            widget.setMinimumWidth(90)


def wrapped(widget):
    widget.setWordWrap(True)
    return widget


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
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}")
        value_label = label(text, "muted")
        value_label.setWordWrap(True)
        layout.addWidget(wrapped(label(name)), index, 0)
        layout.addWidget(bar, index, 1)
        layout.addWidget(value_label, index, 2)
    layout.setColumnStretch(1, 1)


EMPHASIZED = QEasingCurve(QEasingCurve.Type.BezierSpline)  # Material 3 "emphasized decelerate"
EMPHASIZED.addCubicBezierSegment(QPointF(.05, .7), QPointF(.1, 1), QPointF(1, 1))


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
        self.color, self.level = QColor("#888"), 1.0
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
        self.slices, self.center, self.caption, self.progress = [], "", "", 1.0
        self.setMinimumSize(150, 150)

    def set_slices(self, slices, center, caption):
        changed = list(slices) != self.slices
        self.slices, self.center, self.caption = list(slices), center, caption
        self.setAccessibleDescription(f"{center} {caption}")
        if changed:
            draw_in(self)  # segments sweep round when the numbers change
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
                span = round(-360 * 16 * value / total * self.progress)
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
        self.values, self.progress = [], 1.0
        self.setFixedHeight(40)

    def set_values(self, values):
        if list(values) != self.values:
            self.values = list(values)
            draw_in(self, 900)  # the line draws from left to right

    def paintEvent(self, event):
        c = theme.CURRENT.c
        values, peak = self.values, max(self.values, default=0)
        if len(values) < 2 or not peak:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        painter.setClipRect(QRectF(0, 0, width * self.progress, height))
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
            QToolTip.showText(event.globalPosition().toPoint(), f"{elapsed(nearest[0])} · {nearest[2]}", self)
        else:
            QToolTip.hideText()
