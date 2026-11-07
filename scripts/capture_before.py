"""Capture the Python app's real Windows frame and rail, using isolated sample data."""
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from visual_qa import PAGES, window


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots/before-native")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    for theme in ("dark", "light"):
        win = window(app, theme, (1240, 860))
        win.hide()
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)
        win.move(80, 80)
        win.show()
        win.raise_()
        win.activateWindow()
        for index, name in enumerate(PAGES):
            win.navigate(index)
            QTest.qWait(250)
            rect = win.frameGeometry()
            image = win.screen().grabWindow(0, rect.x(), rect.y(), rect.width(), min(rect.height(), 360))
            if image.isNull() or not image.save(str(out / f"{name}-{theme}.png")):
                raise RuntimeError("Native frame capture failed")
        win.close()
        app.processEvents()
    print(f"Captured 12 native-frame images in {out}")


if __name__ == "__main__":
    main()
