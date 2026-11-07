"""Shared, themed controls: the one tooltip, segmented buttons, steppers, selects, date fields, sliders, table rows.

Pages build controls only through these (a test fails on native QComboBox/QSpinBox/QDateEdit/QSlider elsewhere),
so every control follows the theme's colours, shapes and motion level.
"""
from PySide6.QtCore import (QEvent, QObject, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (QApplication, QComboBox, QDateEdit, QHBoxLayout, QLineEdit, QMenu, QPushButton, QSlider,
                               QStyle, QStyledItemDelegate, QWidget)

from . import theme


# ---- The one tooltip ---------------------------------------------------------------------------------------------

def tip_font(bold=False):
    font = QFont("Segoe UI")
    font.setPixelSize(max(12, min(13, theme.CURRENT.px["label"] + 1)))
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return font


class Tip(QWidget):
    """A plain M3 tooltip: inverse surface, rounded, soft shadow. Never takes focus or mouse events.

    show_for() places it above the hovered thing (below if there is no room), clamped inside the window and the
    screen, so it is never cut off and never covers what it describes.
    """
    SHADOW = 6
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        for attribute in (Qt.WidgetAttribute.WA_TranslucentBackground, Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          Qt.WidgetAttribute.WA_ShowWithoutActivating):
            self.setAttribute(attribute)
        self.lines, self.owner = [], None
        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade.setDuration(120)

    def show_for(self, owner, anchor, lines, cursor=None):
        """owner: the widget; anchor: QRect/QRectF in owner coordinates; lines: text (the first is bold)."""
        lines = [line for line in lines if line] or ["No data"]
        self.owner, self.lines = owner, lines
        bold, plain = QFontMetrics(tip_font(True)), QFontMetrics(tip_font())
        width = max([bold.horizontalAdvance(lines[0])] + [plain.horizontalAdvance(line) for line in lines[1:]])
        line_h = plain.height() + 2
        w, h = width + 24 + 2 * self.SHADOW, len(lines) * line_h + 16 + 2 * self.SHADOW
        anchor = QRectF(anchor).toRect()
        top_left = owner.mapToGlobal(anchor.topLeft())
        global_anchor = QRect(top_left, anchor.size())
        center_x = owner.mapToGlobal(cursor).x() if cursor is not None else global_anchor.center().x()
        frame = owner.window()
        bounds = QRect(frame.mapToGlobal(QPoint(0, 0)), frame.size())  # same frame as mapToGlobal above
        screen = (owner.screen() or QApplication.primaryScreen()).availableGeometry()
        bounds = bounds.intersected(screen) if bounds.intersects(screen) else screen
        x = min(max(center_x - w // 2, bounds.left()), bounds.right() - w)
        y = global_anchor.top() - h - 2  # above the hovered thing
        if y < bounds.top():
            y = global_anchor.bottom() + 2  # no room above: below it
        y = min(max(y, bounds.top()), bounds.bottom() - h)
        self.setGeometry(x, y, w, h)
        self.setAccessibleName(" · ".join(lines))
        if not self.isVisible():
            self.setWindowOpacity(0.0 if theme.CURRENT.motion else 1.0)
            self.show()
            if theme.CURRENT.motion:
                self.fade.stop()
                self.fade.setStartValue(0.0)
                self.fade.setEndValue(1.0)
                self.fade.start()
        self.update()

    def hide_for(self, owner=None):
        if owner is None or owner is self.owner:
            self.fade.stop()
            self.hide()  # instant on leave

    def paintEvent(self, event):
        c, r = theme.CURRENT.c, theme.CURRENT.r
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(self.rect()).adjusted(self.SHADOW, self.SHADOW - 2, -self.SHADOW, -self.SHADOW - 2)
        for step in range(self.SHADOW, 0, -1):  # soft elevation
            shade = QColor(0, 0, 0, 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shade)
            painter.drawRoundedRect(body.adjusted(-step, -step + 2, step, step + 2), r["sm"] + step, r["sm"] + step)
        painter.setBrush(QColor(c["inverse_surface"]))
        painter.drawRoundedRect(body, r["sm"], r["sm"])
        painter.setPen(QColor(c["inverse_on_surface"]))
        y = body.top() + 8
        for index, line in enumerate(self.lines):
            painter.setFont(tip_font(index == 0))
            height = QFontMetrics(painter.font()).height() + 2
            painter.drawText(QRectF(body.left() + 12, y, body.width() - 24, height),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
            y += height


def show_tip(owner, anchor, lines, cursor=None):
    Tip.instance().show_for(owner, anchor, lines, cursor)


def hide_tip(owner=None):
    Tip.instance().hide_for(owner)


class Polish(QObject):
    """Installed on the application: every setToolTip() text goes through the themed Tip, and menus and select
    popups get rounded, translucent windows so their stylesheet corners show."""

    WATCH = frozenset((QEvent.Type.ToolTip, QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide,
                       QEvent.Type.WindowDeactivate, QEvent.Type.Polish))

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in self.WATCH:  # runs for every event in the app: leave fast
            return False
        if kind == QEvent.Type.ToolTip and isinstance(watched, QWidget):
            if watched.toolTip():
                show_tip(watched, watched.rect(), watched.toolTip().split("\n"))
                return True
            return False  # let the parent offer its tooltip
        if kind in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide, QEvent.Type.WindowDeactivate):
            if isinstance(watched, QWidget) and Tip._instance is not None and Tip._instance.owner is watched:
                hide_tip(watched)
        elif kind == QEvent.Type.Polish and isinstance(watched, QWidget):
            if isinstance(watched, QMenu) or type(watched).__name__ == "QComboBoxPrivateContainer":
                watched.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
                watched.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
                watched.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        return False


def install(app):
    if not getattr(app, "_lootledger_polish", None):
        app._lootledger_polish = Polish(app)
        app.installEventFilter(app._lootledger_polish)


# ---- Segmented buttons ---------------------------------------------------------------------------------------------

class Segmented(QWidget):
    """M3 segmented buttons: a pill with dividers; the chosen segment is tonal with a check, and the fill slides.

    Too narrow for every segment, it collapses to one pill with the choice and a chevron that opens a menu.
    Left/Right change the choice; Enter or Space opens the menu when collapsed.
    """
    changed = Signal(str)

    def __init__(self, options, current, tip=""):
        super().__init__()
        self.options, self.current, self.hover = list(options), current, -1
        self.slide = 1.0
        self.from_index = self.index_of(current)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(220)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.valueChanged.connect(self._step)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName(tip)
        self.setAccessibleDescription(self.text_of(current))

    def index_of(self, key):
        return next((i for i, (k, _) in enumerate(self.options) if k == key), 0)

    def text_of(self, key):
        return next((text for k, text in self.options if k == key), "")

    def _step(self, value):
        self.slide = value
        self.update()

    def _metrics(self):
        font = QFont(self.font())
        font.setWeight(QFont.Weight.Medium)
        return QFontMetrics(font)

    def natural_width(self):
        fm = self._metrics()
        segment = max(fm.horizontalAdvance(text) for _, text in self.options) + 24 + 22  # padding + check icon
        return segment * len(self.options)

    def sizeHint(self):
        return QSize(self.natural_width(), theme.CURRENT.btn_h)

    def minimumSizeHint(self):
        fm = self._metrics()
        return QSize(max(fm.horizontalAdvance(text) for _, text in self.options) + 56, theme.CURRENT.btn_h)

    def collapsed(self):
        return self.width() < self.natural_width()

    def segment_rect(self, index):
        w = self.width() / len(self.options)
        return QRectF(index * w, 0, w, self.height())

    def select(self, key, emit=True):
        if key == self.current:
            return
        self.from_index, self.current = self.index_of(self.current), key
        self.setAccessibleDescription(self.text_of(key))
        if theme.CURRENT.full_motion and not self.collapsed():
            self.anim.stop()
            self.slide = 0.0
            self.anim.start()
        else:
            self.slide = 1.0
        self.update()
        if emit:
            self.changed.emit(key)

    def open_menu(self):
        menu = QMenu(self)
        for key, text in self.options:
            action = menu.addAction(text, lambda k=key: self.select(k))
            action.setCheckable(True)
            action.setChecked(key == self.current)
        menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.collapsed():
            self.open_menu()
            return
        index = min(int(event.position().x() // (self.width() / len(self.options))), len(self.options) - 1)
        self.select(self.options[index][0])

    def mouseMoveEvent(self, event):
        index = -1 if self.collapsed() else min(int(event.position().x() // (self.width() / len(self.options))),
                                                 len(self.options) - 1)
        if index != self.hover:
            self.hover = index
            self.update()

    def leaveEvent(self, event):
        self.hover = -1
        self.update()

    def keyPressEvent(self, event):
        index = self.index_of(self.current)
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = 1 if event.key() == Qt.Key.Key_Right else -1
            self.select(self.options[min(max(index + step, 0), len(self.options) - 1)][0])
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.collapsed():
            self.open_menu()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        t = theme.CURRENT
        c = t.c
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        radius = theme.pill(outer.height())
        shape = QPainterPath()
        shape.addRoundedRect(outer, radius, radius)
        painter.setClipPath(shape)
        icon_font = QFont(t.family)
        icon_font.setPixelSize(18)
        text_font = QFont(self.font())
        text_font.setWeight(QFont.Weight.Medium)
        if self.collapsed():
            painter.fillRect(outer, QColor(c["secondary_container"]))
            painter.setPen(QColor(c["on_secondary_container"]))
            painter.setFont(text_font)
            painter.drawText(outer.adjusted(16, 0, -36, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             self.text_of(self.current))
            painter.setFont(icon_font)
            painter.drawText(outer.adjusted(0, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             "expand_more")
        else:
            target = self.segment_rect(self.index_of(self.current))
            start = self.segment_rect(self.from_index)
            k = theme.EASE(self.slide)
            fill = QRectF(start.left() + (target.left() - start.left()) * k, 0, target.width(), self.height())
            painter.fillRect(fill, QColor(c["secondary_container"]))
            if 0 <= self.hover < len(self.options):
                layer = QColor(c["on_surface"])
                layer.setAlphaF(.08)
                painter.fillRect(self.segment_rect(self.hover), layer)
            painter.setPen(QPen(QColor(c["outline"]), 1))
            for index in range(1, len(self.options)):
                x = self.segment_rect(index).left()
                painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            for index, (key, text) in enumerate(self.options):
                rect = self.segment_rect(index)
                chosen = key == self.current
                painter.setPen(QColor(c["on_secondary_container" if chosen else "on_surface"]))
                fm = QFontMetrics(text_font)
                content = fm.horizontalAdvance(text) + (22 if chosen else 0)
                left = rect.center().x() - content / 2
                if chosen:
                    painter.setFont(icon_font)
                    painter.setOpacity(k)  # the check fades in with the slide
                    painter.drawText(QRectF(left, 0, 20, self.height()), Qt.AlignmentFlag.AlignCenter, "check")
                    painter.setOpacity(1.0)
                    left += 22
                painter.setFont(text_font)
                painter.drawText(QRectF(left, 0, rect.right() - left, self.height()),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        focused = self.hasFocus()
        painter.setPen(QPen(QColor(c["primary" if focused else "outline"]), 2 if focused else 1))
        painter.drawRoundedRect(outer, radius, radius)


# ---- Stepper (numbers) ---------------------------------------------------------------------------------------------

class Stepper(QWidget):
    """A pill number field: − value +, typing allowed, clamped to min/max, with optional presets.

    Mirrors the QSpinBox calls the pages use (value, setValue, valueChanged, setRange)."""
    valueChanged = Signal(int)

    def __init__(self, low, high, value, step=1, special="", prefix="", suffix="", presets=(), tip=""):
        super().__init__()
        self.setObjectName("stepper")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.low, self.high, self.step, self._value = low, high, step, None
        self.special, self.prefix, self.suffix = special, prefix, suffix
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(0)
        self.minus = self._button("remove", f"Less ({tip})" if tip else "Less", -1)
        self.edit = QLineEdit()
        self.edit.setObjectName("stepperText")
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit.setAccessibleName(tip or "Number")
        self.edit.editingFinished.connect(self._typed)
        self.plus = self._button("add", f"More ({tip})" if tip else "More", 1)
        row.addWidget(self.minus)
        row.addWidget(self.edit, 1)
        row.addWidget(self.plus)
        if presets:
            more = QPushButton("expand_more")
            more.setObjectName("stepperButton")
            more.setToolTip("Presets")
            more.setAccessibleName("Presets")
            more.clicked.connect(lambda checked=False: self._presets(presets))
            row.addWidget(more)
        font = QFont("Segoe UI")
        font.setPixelSize(theme.CURRENT.px["body"])  # the field's stylesheet font, not the default one
        widest = max(QFontMetrics(font).horizontalAdvance(self.text_for(v)) for v in (low, high))
        self.setMinimumWidth(widest + 32 * (3 if presets else 2) + 40)
        self.setFixedHeight(theme.CURRENT.btn_h)
        self.setValue(value)

    def _button(self, icon, tip, direction):
        button = QPushButton(icon)
        button.setObjectName("stepperButton")
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setAutoRepeat(True)
        button.clicked.connect(lambda checked=False: self.setValue(self._value + direction * self.step))
        return button

    def _presets(self, presets):
        menu = QMenu(self)
        for text, value in presets:
            if value is None:
                menu.addAction(text, lambda: (self.edit.setFocus(), self.edit.selectAll()))
            else:
                action = menu.addAction(text, lambda v=value: self.setValue(v))
                action.setCheckable(True)
                action.setChecked(value == self._value)
        menu.exec(self.mapToGlobal(QPoint(self.width() - 160, self.height() + 4)))

    def text_for(self, value):
        return self.special if value == self.low and self.special else f"{self.prefix}{value}{self.suffix}"

    def _typed(self):
        text = self.edit.text().strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        self.setValue(int(digits) if digits else self.low)

    def value(self):
        return self._value

    def setRange(self, low, high):
        self.low, self.high = low, high
        self.setValue(self._value if self._value is not None else low)

    def setValue(self, value):
        value = min(max(int(value), self.low), self.high)
        changed = value != self._value
        self._value = value
        self.edit.setText(self.text_for(value))
        self.minus.setEnabled(value > self.low)
        self.plus.setEnabled(value < self.high)
        if changed:
            self.valueChanged.emit(value)


# ---- Factories for the remaining Qt inputs (styled by the theme stylesheet) ---------------------------------------

def select(items=(), tip=""):
    """An M3-styled select (rounded field, chevron, rounded popup with a highlight). items: (text, data)."""
    combo = QComboBox()
    combo.setAccessibleName(tip)
    for text, data in items:
        combo.addItem(text, data)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(7)
    combo.setFixedHeight(theme.CURRENT.btn_h)
    return combo


def date_field(value, tip=""):
    field = QDateEdit(value)
    field.setCalendarPopup(True)
    field.setAccessibleName(tip)
    field.setFixedHeight(theme.CURRENT.btn_h)
    return field


def slider(low, high, value, tip=""):
    control = QSlider(Qt.Orientation.Horizontal)
    control.setRange(low, high)
    control.setValue(value)
    control.setAccessibleName(tip)
    control.setMinimumWidth(180)
    return control


class RowDelegate(QStyledItemDelegate):
    """Hover and selection as one rounded highlight across the whole row, instead of square cells."""

    def paint(self, painter, option, index):
        state = option.state
        selected = bool(state & QStyle.StateFlag.State_Selected)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            c = theme.CURRENT.c
            model = index.model()
            last = model.columnCount(index.parent()) - 1
            r = theme.CURRENT.r["sm"]
            rect = QRectF(option.rect)
            path = QPainterPath()
            left_round, right_round = index.column() == 0, index.column() == last
            grow_l, grow_r = (0 if left_round else r), (0 if right_round else r)
            path.addRoundedRect(rect.adjusted(-grow_l, 1, grow_r, -1), r, r)  # neighbours overlap: one seamless pill
            painter.save()
            painter.setClipRect(option.rect)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillPath(path, QColor(c["secondary_container"]) if selected else theme.layer(c["on_surface"], .08))
            painter.restore()
        option.state &= ~QStyle.StateFlag.State_Selected
        option.state &= ~QStyle.StateFlag.State_MouseOver
        if selected:
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme.CURRENT.c["on_secondary_container"]))
        super().paint(painter, option, index)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.state &= ~QStyle.StateFlag.State_HasFocus  # no dotted cell focus box; the table has a focus ring
