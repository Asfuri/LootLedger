import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = []

    def configure(self, add, undo):
        self.close()
        if sys.platform != "win32":
            return
        try:
            for identity, text in ((0x6A11, add), (0x6A12, undo)):
                if not text.strip():
                    continue
                parts = text.upper().replace(" ", "").split("+")
                modifiers = {"ALT": 1, "CTRL": 2, "SHIFT": 4, "WIN": 8}
                if not parts[:-1] or any(p not in modifiers for p in parts[:-1]):
                    raise ValueError("Hotkeys need Ctrl, Alt, Shift or Win plus a letter, digit or F1–F24")
                key = parts[-1]
                if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
                    code = 0x70 + int(key[1:]) - 1
                elif len(key) == 1 and key.isascii() and key.isalnum():
                    code = ord(key)
                else:
                    raise ValueError(f"Unsupported hotkey: {text}")
                flags = 0x4000
                for modifier in parts[:-1]:
                    flags |= modifiers[modifier]
                if not ctypes.windll.user32.RegisterHotKey(None, identity, flags, code):
                    raise ValueError(f"Hotkey is already in use: {text}")
                self.registered.append(identity)
        except Exception:
            self.close()
            raise

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x312 and msg.wParam in self.registered:
                self.callback("add" if msg.wParam == 0x6A11 else "undo")
                return True, 0
        return False, 0

    def close(self):
        for identity in self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, identity)
        self.registered.clear()
