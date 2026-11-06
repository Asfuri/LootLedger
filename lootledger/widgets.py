from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

ACCENT = "#e8b04f"

STYLE = """
* { font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog, QWidget#root { background: #121216; color: #e9eaee; }
QStatusBar { background: #121216; color: #8d8f9a; font-size: 11px; }
QLabel { color: #e9eaee; background: transparent; }
QLabel#muted { color: #8d8f9a; }
QLabel#section { color: #b9bbc5; font-size: 14px; font-weight: 700; letter-spacing: 0.5px; }
QLabel#title { font-size: 24px; font-weight: 700; }
QLabel#brand { font-size: 21px; font-weight: 800; color: #e8b04f; }
QLabel#number { font-size: 40px; font-weight: 700; }
QLabel#accentNumber { font-size: 40px; font-weight: 700; color: #e8b04f; }
QLabel#smallNumber { font-size: 24px; font-weight: 700; }
QLabel#overlayNumber { font-size: 36px; font-weight: 800; color: #e8b04f; }
QFrame#card { background: #1b1b21; border: 1px solid #2b2b33; border-radius: 10px; }
QFrame#accentCard { background: #33291a; border: 1px solid #5a4523; border-radius: 10px; }
QFrame#panel { background: #1b1b21; border: 1px solid #2b2b33; border-radius: 10px; }
QFrame#sidebar { background: #16161b; border-right: 1px solid #26262e; }
QPushButton { color: #e9eaee; background: #26262e; border: 1px solid #36363f;
              padding: 8px 14px; border-radius: 7px; font-weight: 600; }
QPushButton:hover { background: #32323b; border-color: #8f7440; }
QPushButton:pressed { background: #3f3524; }
QPushButton:checked { background: #3a3020; border-color: #e8b04f; }
QPushButton:disabled { color: #6b6c76; background: #1b1b21; border-color: #26262e; }
QPushButton#primary { background: #e8b04f; color: #1a1408; border-color: #f1c46f; }
QPushButton#primary:disabled { background: #26262e; color: #6b6c76; border-color: #36363f; }
QPushButton#nav { text-align: left; padding: 11px 12px; background: transparent; border: none; }
QPushButton#nav:checked { background: #2c261b; color: #f1c46f; }
QTableWidget { background: #1b1b21; alternate-background-color: #1f1f26; color: #dcdde3;
               border: 1px solid #2b2b33; border-radius: 8px; gridline-color: #2b2b33;
               selection-background-color: #4a3c22; selection-color: white; }
QHeaderView::section { background: #1b1b21; color: #8d8f9a; padding: 9px; border: none;
                       border-bottom: 1px solid #2b2b33; font-weight: 700; }
QLineEdit, QComboBox, QSpinBox { background: #22222a; color: #e9eaee;
                 border: 1px solid #3a3a44; border-radius: 5px; padding: 6px; }
QCheckBox { color: #dcdde3; spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #686a76; border-radius: 4px; background: #22222a; }
QCheckBox::indicator:checked { background: #e8b04f; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 9px; background: #16161b; }
QScrollBar::handle:vertical { background: #3e3e48; border-radius: 4px; min-height: 24px; }
QToolTip { color: #e9eaee; background: #26262e; border: 1px solid #686a76; }
"""


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def card(title, subtitle="", large=True, accent=False):
    """A counter card: number first, caption below. Returns (card, number label, caption label)."""
    widget = QFrame()
    widget.setObjectName("accentCard" if accent else "card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 14, 18, 15)
    layout.setSpacing(2)
    value = label("0", ("accentNumber" if accent else "number") if large else "smallNumber")
    layout.addWidget(value)
    caption = label(title, "muted")
    caption.setWordWrap(True)
    layout.addWidget(caption)
    detail = label(subtitle, "muted")
    detail.setWordWrap(True)
    layout.addWidget(detail)
    detail.setVisible(bool(subtitle))
    layout.addStretch()
    return widget, value, detail


class BarChart(QWidget):
    """Simple bar chart: values with optional first/last captions."""

    def __init__(self, empty="Nothing to show yet", height=150, labels=False, max_bar=None):
        super().__init__()
        self.values = []
        self.captions = ("", "")
        self.empty = empty
        self.show_values = labels
        self.max_bar = max_bar
        self.setMinimumHeight(height)

    def set_values(self, values, captions=("", "")):
        self.values = list(values)
        self.captions = captions
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.values or not any(self.values):
            painter.setPen(QColor("#8d8f9a"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty)
            return
        bottom = self.height() - 22
        top = 16 if self.show_values else 6
        maximum = max(max(self.values), 1)
        step = self.width() / len(self.values)
        if self.max_bar:
            step = min(step, self.max_bar)
        for i, value in enumerate(self.values):
            height = (bottom - top) * value / maximum
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT if value else "#2b2b33"))
            bar = QRectF(i * step + 2, bottom - max(height, 2), max(3, step - 4), max(height, 2))
            painter.drawRoundedRect(bar, 2, 2)
            if self.show_values and value:
                painter.setPen(QColor("#b9bbc5"))
                painter.drawText(QRectF(i * step, bar.top() - 16, step, 15),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, str(value))
        painter.setPen(QColor("#8d8f9a"))
        caption_box = QRectF(0, bottom + 4, self.width(), 18)
        painter.drawText(caption_box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.captions[0])
        painter.drawText(caption_box, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.captions[1])
