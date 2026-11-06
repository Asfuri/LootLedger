from collections import deque
from dataclasses import asdict
from pathlib import Path
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from .capture import Capture
from .detector import Detector
from .store import Store
from .vision import Perception, WindowsOCR, region


class TrackingWorker(QThread):
    status = Signal(str, str)
    preview = Signal(object, object)
    detection = Signal(object, object, str)

    def __init__(self, config, context, folder):
        super().__init__()
        self.config, self.context, self.folder = config, context, Path(folder)
        self.stopping = threading.Event()

    def run(self):
        capture, ocr, ledger, detector = None, None, None, None
        try:
            cfg = self.config
            ledger = Store(self.folder.parent / "ledger.sqlite")
            self.status.emit("Paused", "Loading local recognizer and OCR…")
            capture, ocr = Capture(cfg.capture), WindowsOCR(cfg.language)
            perception, detector = Perception(cfg, ocr), Detector(cfg)
            warmup = np.zeros((45, 180, 3), np.uint8)
            cv2.putText(warmup, "SEARCH", (5, 30), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2)
            ocr.read(warmup)
            validated = cfg.validated()
            recent = deque(maxlen=round(cfg.frame_hz * cfg.timeout))
            scan_times = deque(maxlen=20)
            start, last_preview = time.monotonic(), 0
            while not self.stopping.is_set():
                tick = time.monotonic()
                frame = capture.grab()
                if frame is None:
                    scan_times.clear()
                    detector.reset()
                    self.status.emit("Paused", "Game is not visible in the foreground")
                else:
                    obs = perception.observe(frame, tick - start)
                    # Keep only small crops in memory, only when evidence storage is enabled.
                    if cfg.evidence:
                        recent.append((obs.time, {name: region(frame, cfg.regions[name]).copy()
                                                  for name in ("chest", "search", "xp")}))
                    events = detector.feed(obs)
                    if obs.active:
                        scan_times.append(tick)
                    else:
                        scan_times.clear()
                    rate = ((len(scan_times) - 1) / (scan_times[-1] - scan_times[0])) if len(scan_times) >= 3 else None
                    detail = "Validated profile" if validated else "Review mode · footage validation pending"
                    if rate is not None:
                        detail += f" · {rate:.1f} scans/s" + (" · slow scanning" if rate < 6 else "")
                    self.status.emit("Tracking" if obs.active else "Paused",
                                     detail if obs.active else "Active-play HUD absent or blocked mode visible")
                    for event in events:
                        if not validated:
                            event.status = "review"
                            event.reason += "; unvalidated profile"
                        evidence = str(self.folder / event.id) if cfg.evidence else None
                        # Persist before optional image I/O and before the UI receives a queued signal.
                        ledger.add(event, evidence=evidence)
                        if cfg.evidence:
                            try:
                                folder = Path(evidence)
                                folder.mkdir(parents=True, exist_ok=True)
                                snapshots = [recent[0], recent[len(recent) // 2], recent[-1]]
                                for index, (stamp, crops) in enumerate(snapshots):
                                    for name, crop in crops.items():
                                        ok, data = cv2.imencode(".png", crop)
                                        if not ok:
                                            raise RuntimeError("Failed to encode evidence")
                                        (folder / f"{index}-{stamp:.3f}-{name}.png").write_bytes(data.tobytes())
                                import json
                                (folder / "event.json").write_text(json.dumps(asdict(event), indent=2), encoding="utf-8")
                            except (OSError, RuntimeError) as error:
                                self.status.emit("Tracking", f"Opening saved; evidence unavailable: {error}")
                        self.detection.emit(event, evidence, self.context)
                    if tick - last_preview >= .5:
                        self.preview.emit(frame, obs)
                        last_preview = tick
                self.stopping.wait(max(0, 1 / cfg.frame_hz - (time.monotonic() - tick)))
        except Exception as error:
            self.status.emit("Needs calibration", str(error))
        finally:
            if ledger:
                if detector:
                    for event in detector.finish():
                        ledger.add(event, force_review=True)
                ledger.close()
            if ocr:
                ocr.close()
            if capture:
                capture.close()

    def stop(self):
        self.stopping.set()
        self.wait()
