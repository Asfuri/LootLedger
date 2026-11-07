import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter

IDS = {"add": 0x6A11, "undo": 0x6A12, "overlay": 0x6A13}
MODIFIERS = {"ALT": 1, "CTRL": 2, "SHIFT": 4, "WIN": 8}


def parse(text):
    """'Ctrl+Alt+F8' -> (RegisterHotKey flags, virtual key). Raises ValueError for anything else."""
    parts = text.upper().replace(" ", "").split("+")
    if not parts[:-1] or any(p not in MODIFIERS for p in parts[:-1]):
        raise ValueError("Hotkeys need Ctrl, Alt, Shift or Win plus a letter, digit or F1–F24")
    key = parts[-1]
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        code = 0x70 + int(key[1:]) - 1
    elif len(key) == 1 and key.isascii() and key.isalnum():
        code = ord(key)
    else:
        raise ValueError(f"Unsupported hotkey: {text}")
    flags = 0x4000  # MOD_NOREPEAT
    for modifier in parts[:-1]:
        flags |= MODIFIERS[modifier]
    return flags, code


class Hotkeys(QAbstractNativeEventFilter):
    """System-wide shortcuts via RegisterHotKey. They only notice key presses; nothing is sent to other apps."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = []

    def configure(self, add, undo, overlay=""):
        """Register the shortcuts. Badly written ones raise ValueError before anything changes.
        Returns the shortcuts another app already owns: those are skipped, the others still work."""
        wanted = {name: text for name, text in (("add", add), ("undo", undo), ("overlay", overlay)) if text.strip()}
        parsed = {name: parse(text) for name, text in wanted.items()}
        self.close()
        if sys.platform != "win32":
            return []
        busy = []
        for name, (flags, code) in parsed.items():
            if ctypes.windll.user32.RegisterHotKey(None, IDS[name], flags, code):
                self.registered.append(IDS[name])
            else:
                busy.append(wanted[name])
        return busy

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x312 and msg.wParam in self.registered:
                self.callback(next(name for name, identity in IDS.items() if identity == msg.wParam))
                return True, 0
        return False, 0

    def close(self):
        for identity in self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, identity)
        self.registered.clear()
