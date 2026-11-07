"""Explicit local smoke test for the source app and the frozen Windows executable.

Checks the bundled replay reader, the icon font, every page, corrections, and (when this PC
has a finished Fortnite replay) reading the newest one into a temporary ledger.
"""
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time


def main(output):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    from . import replay_reader, theme
    from .app import MainWindow
    from .config import Config
    from .prefs import Prefs
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"platform": platform.platform(), "python": sys.version, "frozen": bool(getattr(sys, "frozen", False)),
              "checks": {}}
    try:
        app = QApplication.instance() or QApplication([])
        # The offscreen Qt backend has no platform font database on Windows.
        for font in ("segoeui.ttf", "seguisb.ttf", "segoeuib.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
        app.setStyle("Fusion")
        report["checks"]["replay_reader_bundled"] = str(replay_reader.helper_path())
        report["checks"]["icon_font_loaded"] = theme.load_icon_font() == theme.ICON_FONT
        with tempfile.TemporaryDirectory(prefix="lootledger-smoke-") as temporary:
            folder = Path(temporary)
            garbage = folder / "not-a-replay.replay"
            garbage.write_bytes(b"\0" * 64)
            result = replay_reader.analyze([garbage])[0]
            assert result["ok"] is False and result["events"] == []
            report["checks"]["replay_reader_rejects_garbage"] = "passed"
            replays = sorted(replay_reader.default_folder().glob("*.replay"), key=lambda p: p.stat().st_mtime)
            finished = [p for p in replays if time.time() - p.stat().st_mtime > replay_reader.LIVE_WINDOW]
            Config(hotkey_add="", hotkey_undo="", replay_folder=str(folder / "replays")).save(folder / "config.json")
            Prefs(animations=False).save(folder / "ui-settings.json")
            (folder / "replays").mkdir()
            if finished:
                sample = finished[-1]
                (folder / "replays" / sample.name).write_bytes(sample.read_bytes())
            window = MainWindow(folder, scan_on_start=False)
            window.show()
            try:
                started = time.monotonic()
                window.scan()
                while window.scanner.running and time.monotonic() - started < 120:
                    app.processEvents()
                    time.sleep(.05)
                app.processEvents()
                assert not window.scan_error, window.scan_error
                if finished:
                    data = window.store.snapshot()
                    assert data["matches"] == 1
                    report["checks"]["real_replay"] = {"file": finished[-1].name, "your_chests": data["all"],
                                                       "broken": data["broken"], "teammates": data["team_total"]}
                    before = data["all"]
                    window.manual_add()
                    assert window.store.snapshot()["all"] == before + 1
                    window.undo()
                    assert window.store.snapshot()["all"] == before
                    report["checks"]["corrections"] = "passed (+1 then undo)"
                else:
                    report["checks"]["real_replay"] = "skipped (no finished Fortnite replay on this PC)"
                window.resize(1240, 1000)
                names = ("overview", "matches", "teammates", "openings", "statistics", "settings")
                for index, name in enumerate(names):
                    window.navigate(index)
                    app.processEvents()
                    window.grab().save(str(output / f"{name}.png"))
                report["checks"]["pages_rendered"] = len(names)
            finally:
                window.close()
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    (output / "smoke-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1
