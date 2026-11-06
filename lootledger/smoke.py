"""Explicit local smoke test for the source app and the frozen Windows executable.

Checks the dashboard, corrections, the bundled replay reader and, when this PC has
Fortnite replays, reading the newest finished one into a temporary ledger.
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
    from . import replay_reader
    from .app import MainWindow
    from .config import Config
    from .widgets import STYLE
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
        app.setStyleSheet(STYLE)
        helper = replay_reader.helper_path()
        report["checks"]["replay_reader_bundled"] = str(helper)
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
                    data = window.store.dashboard()
                    assert data["matches"] == 1
                    report["checks"]["real_replay"] = {"file": finished[-1].name, "your_chests": data["all"],
                                                       "broken": data["broken"], "teammates": data["team_total"]}
                else:
                    report["checks"]["real_replay"] = "skipped (no finished Fortnite replay on this PC)"
                before = window.store.dashboard()["all"]
                if finished:
                    window.manual_add()
                    assert window.store.dashboard()["all"] == before + 1
                    window.undo()
                    assert window.store.dashboard()["all"] == before
                    report["checks"]["corrections"] = "passed (+1 then undo)"
                window.resize(1240, 1000)
                app.processEvents()
                window.grab().save(str(output / "overview.png"))
                for index, name in ((1, "matches"), (2, "openings"), (3, "settings")):
                    window.navigate(index)
                    app.processEvents()
                    window.grab().save(str(output / f"{name}.png"))
                report["checks"]["dashboard_rendered"] = "passed"
            finally:
                window.close()
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    (output / "smoke-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1
