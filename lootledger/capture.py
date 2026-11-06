import ctypes
from ctypes import wintypes
import sys

import mss
import numpy as np


def enable_dpi_awareness():
    if sys.platform == "win32":
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


def windows():
    if sys.platform != "win32":
        return []
    user = ctypes.windll.user32
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    found = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def collect(handle, _):
        title = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(handle, title, 512)
        if user.IsWindowVisible(handle) and title.value:
            found.append((int(handle), title.value))
        return True
    callback = callback_type(collect)
    user.EnumWindows(callback, 0)
    return found


class Capture:
    def __init__(self, selection):
        self.screen = mss.MSS()
        self.selection = selection

    def grab(self, *, require_foreground=True):
        source = self.selection
        if source["kind"] == "window":
            user = ctypes.windll.user32
            user.GetForegroundWindow.restype = wintypes.HWND
            user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            user.IsIconic.argtypes = [wintypes.HWND]
            handle = source["handle"]
            if user.IsIconic(handle) or (require_foreground and user.GetForegroundWindow() != handle):
                return None
            bounds, origin = wintypes.RECT(), wintypes.POINT(0, 0)
            if not user.GetClientRect(handle, ctypes.byref(bounds)) or not user.ClientToScreen(handle, ctypes.byref(origin)):
                raise RuntimeError("Selected window closed; select it again")
            area = {"left": origin.x, "top": origin.y, "width": bounds.right, "height": bounds.bottom}
        else:
            if not 1 <= source["index"] < len(self.screen.monitors):
                raise ValueError("Selected display disconnected")
            if require_foreground and sys.platform == "win32":
                # Monitor capture still requires the game to be the foreground window.
                user = ctypes.windll.user32
                user.GetForegroundWindow.restype = wintypes.HWND
                title = ctypes.create_unicode_buffer(512)
                user.GetWindowTextW(user.GetForegroundWindow(), title, 512)
                if "fortnite" not in title.value.lower():
                    return None
            area = self.screen.monitors[source["index"]]
        if area["width"] < 32 or area["height"] < 32:
            return None
        return np.asarray(self.screen.grab(area))[:, :, :3].copy()

    def close(self):
        self.screen.close()
