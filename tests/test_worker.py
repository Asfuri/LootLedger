import numpy as np

from lootledger.config import Config
from lootledger.detector import Observation, Target
from lootledger.store import Store
from lootledger.worker import TrackingWorker
import lootledger.worker as module


def test_worker_commits_review_event_before_notifying_ui(tmp_path, monkeypatch):
    ledger = Store(tmp_path / "ledger.sqlite")
    ledger.start()
    worker = TrackingWorker(Config(), "context", tmp_path / "evidence")

    class Capture:
        def __init__(self, selection):
            self.count = 0

        def grab(self):
            self.count += 1
            if self.count > 6:
                worker.stopping.set()
                return None
            return np.zeros((32, 32, 3), np.uint8)

        def close(self):
            pass

    class OCR:
        def __init__(self, language):
            pass

        def close(self):
            pass

        def read(self, crop):
            return []

    class Vision:
        def __init__(self, config, ocr):
            self.count = 0

        def observe(self, frame, stamp):
            step = self.count
            self.count += 1
            closed = step < 4
            return Observation(step / 10, True, [Target(1, .99 if closed else 0, 0 if closed else .99)],
                               closed, (.1, .2, .5, .95, None, None)[step], [] if closed else ["xp"], focus=1)

    monkeypatch.setattr(module, "Capture", Capture)
    monkeypatch.setattr(module, "WindowsOCR", OCR)
    monkeypatch.setattr(module, "Perception", Vision)
    observed = []

    def saved(event, evidence, context):
        rows = ledger.entries()
        observed.append((event.status, rows[0]["status"], ledger.stats()["all"]))

    worker.detection.connect(saved)
    worker.run()
    assert observed == [("review", "review", 0)]
    assert not (tmp_path / "evidence").exists()
    ledger.close()
