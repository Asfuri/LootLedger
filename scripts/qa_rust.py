"""Exercise the Rust window against synthetic data; no game keys or game handles are used.

Writes native hit-test/window results and 36 page/theme/size captures. Screenshot review,
physical mouse use, Snap Layouts and mixed-monitor DPI still require a real-display pass.
"""
import argparse
from contextlib import closing
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from bench_release import tree, windows, u32

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lootledger.store import Store  # noqa: E402


def point(x, y):
    return w.LPARAM((x & 65535) | ((y & 65535) << 16))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "target/rust-qa")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    u32.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
    u32.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
    u32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    u32.SendMessageW.restype = w.LPARAM
    u32.GetDpiForWindow.argtypes = [w.HWND]
    u32.IsZoomed.argtypes = [w.HWND]
    with tempfile.TemporaryDirectory(prefix="lootledger-rust-qa-") as temp, tempfile.TemporaryDirectory(prefix="capture-", dir=out) as capture:
        folder = Path(temp) / "LootLedger"
        folder.mkdir()
        store = Store(folder / "ledger.sqlite")
        try:
            fixture = json.loads((ROOT / "tests/fixtures/replay-squad.json").read_text(encoding="utf-8"))
            store.import_replay(fixture, "sample.replay", 1, 1.0)
        finally:
            store.close()
        (folder / "config.json").write_text('{"auto_watch":false}', encoding="utf-8")
        env = {**os.environ, "LOCALAPPDATA": temp}
        log = (out / "stderr.txt").open("w", encoding="utf-8")
        proc = subprocess.Popen([str(args.exe.resolve()), f"--qa={capture}", "--quit-after=60"], env=env, stderr=log)
        try:
            deadline = time.monotonic() + 45
            handles = []
            while not handles and time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f"App exited early: {proc.returncode}")
                handles = windows(tree(proc.pid))
                time.sleep(.05)
            if not handles:
                raise TimeoutError("No app window")
            hwnd = handles[0]
            time.sleep(.15)
            rect = w.RECT()
            if not u32.GetWindowRect(hwnd, c.byref(rect)):
                raise c.WinError()
            scale = u32.GetDpiForWindow(hwnd) / 96
            x, y = rect.left, rect.top
            width, height = rect.right - x, rect.bottom - y
            tests = [
                ("caption", x + width // 2, y + round(20 * scale), 2),
                ("snap_maximize_target", x + width - round(69 * scale), y + round(20 * scale), 9),
                ("close_is_interactive_client", x + width - round(23 * scale), y + round(20 * scale), 1),
                ("top_left_resize", x + 1, y + 1, 13),
                ("bottom_right_resize", x + width - 1, y + height - 1, 17),
            ]
            report = {"dpi": scale * 96, "synthetic_messages_only": True, "checks": {}, "physical_mouse_tested": False,
                      "snap_layout_popup_tested": False, "mixed_monitor_dpi_tested": False}
            title = c.create_unicode_buffer(512)
            u32.GetWindowTextW(hwnd, title, len(title))
            report["window"] = {"title": title.value, "x": x, "y": y, "width": width, "height": height}
            for name, px, py, expected in tests:
                actual = u32.SendMessageW(hwnd, 0x84, 0, point(px, py))
                report["checks"][name] = {"expected": expected, "actual": actual, "passed": actual == expected}
            u32.SendMessageW(hwnd, 0x112, 0xF030, 0)  # maximize this app only
            time.sleep(.15)
            report["checks"]["maximize"] = {"passed": bool(u32.IsZoomed(hwnd))}
            u32.SendMessageW(hwnd, 0x112, 0xF120, 0)
            time.sleep(.15)
            report["checks"]["restore"] = {"passed": not bool(u32.IsZoomed(hwnd))}
            proc.wait(timeout=70)
            if proc.returncode:
                raise RuntimeError(f"App exited: {proc.returncode}")
            captures = list(Path(capture).glob("page-*.ppm"))
            report["captures"] = len(captures)
            report["passed"] = all(check["passed"] for check in report["checks"].values()) and len(captures) == 36
            # Conversion is a developer convenience; the Rust binary itself has no Qt dependency.
            from PySide6.QtGui import QImage
            for path in captures:
                image = QImage(str(path))
                if image.isNull() or not image.save(str(out / path.with_suffix(".png").name)):
                    raise RuntimeError(f"Could not convert {path.name}")
                path.unlink()
            (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            return 0 if report["passed"] else 1
        finally:
            if proc.poll() is None:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                proc.wait(timeout=10)
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
