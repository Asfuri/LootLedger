"""Draw the app icon (Material Symbols "inventory_2" on an amber rounded square) at the usual Windows
sizes and pack them into crates/app/assets/lootledger.ico. Needs PySide6 (the old app's dependency)."""
from pathlib import Path
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "lootledger/assets/fonts/MaterialSymbolsRounded.ttf"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(size, family):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#e8b04f"))  # the default amber accent
    radius = size * 0.22
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    font = QFont(family)
    font.setPixelSize(round(size * 0.72))
    painter.setFont(font)
    painter.setPen(QColor("#3f2a00"))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "inventory_2")
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def main():
    app = QGuiApplication(sys.argv)
    family = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(FONT)))[0]
    images = [draw(size, family) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in zip(SIZES, images):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        blobs += png
    out = ROOT / "crates/app/assets/lootledger.ico"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(header + entries + blobs)
    print(f"{out}: {out.stat().st_size:,} bytes")
    del app


if __name__ == "__main__":
    main()
