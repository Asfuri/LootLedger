"""Run the real worker against a clocked, lossless video fixture and a temporary ledger.

This checks skipped frames and saving at wall-clock speed. It does not test actual
Fortnite capture, foreground selection, or the UI rendering workload.
"""
import argparse
from dataclasses import asdict
import bisect
import json
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time

import cv2
import numpy as np
from PySide6.QtCore import QCoreApplication

from .analyze import compare
from .config import Config
from .store import Store
from .worker import TrackingWorker
from . import worker as module


def replay(video, config, labels, output, height=None):
    # Predecode without advancing the clock. A file-backed buffer preserves pixels
    # without pinning several GB of frames in the game's RAM or encoding PNGs.
    scratch = Path("local-data").resolve()
    scratch.mkdir(exist_ok=True)
    cv2.setNumThreads(2)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError("Cannot open recording")
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width, native_height = int(capture.get(3)), int(capture.get(4))
    if count <= 0 or min(width, native_height) < 32:
        raise ValueError("Recording has no usable frames")
    size = [round(width * height / native_height), height] if height else [width, native_height]
    needed = count * size[0] * size[1] * 3
    if needed + 512 * 1024**2 > shutil.disk_usage(scratch).free:
        raise ValueError("Not enough temporary disk space for a lossless replay")
    cache_file = tempfile.TemporaryFile(dir=scratch)
    frames = np.memmap(cache_file, dtype=np.uint8, mode="w+", shape=(count, size[1], size[0], 3))
    stamps = []
    while True:
        ok, image = capture.read()
        if not ok:
            break
        stamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if height:
            image = cv2.resize(image, tuple(size))
        frames[len(stamps)] = image
        stamps.append(stamp)
    fps = capture.get(cv2.CAP_PROP_FPS)
    capture.release()
    frames.flush()
    if not stamps or fps <= 0 or stamps != sorted(stamps):
        raise ValueError("Recording needs ordered frame timestamps")
    duration = stamps[-1] + 1 / fps
    truth = json.loads(Path(labels).read_text(encoding="utf-8"))
    app = QCoreApplication.instance() or QCoreApplication([])
    events, statuses, samples = [], [], []
    original_capture, original_vision = module.Capture, module.Perception
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Prepared {len(stamps)} lossless frames at {size[0]}x{size[1]}; starting timed worker.", flush=True)
    with tempfile.TemporaryDirectory(prefix="worker-replay-", dir=scratch) as temporary:
        folder = Path(temporary).resolve()
        assert folder.is_relative_to(scratch) and folder != scratch
        config.evidence = False
        ledger = Store(folder / "ledger.sqlite")
        ledger.start()
        worker = TrackingWorker(config, "replay", folder / "evidence")

        class VideoCapture:
            def __init__(self, selection):
                self.started = None

            def grab(self):
                if self.started is None:
                    self.started = time.monotonic()
                elapsed = time.monotonic() - self.started
                if elapsed >= duration:
                    worker.stopping.set()
                    return None
                index = max(0, bisect.bisect_right(stamps, elapsed) - 1)
                return frames[index].copy()

            def close(self):
                pass

        class TimedVision:
            def __init__(self, cfg, ocr):
                self.vision = original_vision(cfg, ocr)

            def observe(self, image, stamp):
                started = time.perf_counter()
                obs = self.vision.observe(image, stamp)
                samples.append({"time": stamp, "processing_ms": (time.perf_counter() - started) * 1000,
                                "observation": asdict(obs)})
                return obs

        module.Capture, module.Perception = VideoCapture, TimedVision
        worker.detection.connect(lambda event, evidence, context: events.append(asdict(event)))
        worker.status.connect(lambda status, detail: statuses.append([status, detail]))
        try:
            worker.run()
            saved = ledger.entries()
            assert {event["id"] for event in events} <= {row["id"] for row in saved}, "Worker must save before notifying"
            events = [{"id": row["id"], "time": row["video_time"], "status": row["status"],
                       "chest_type": row["chest_type"], "confidence": row["confidence"], "reason": row["reason"]}
                      for row in saved]
            metrics = compare([{**event, "status": "confirmed"} for event in events], truth)
            values = sorted(sample["processing_ms"] for sample in samples)
            report = {"video": str(Path(video).resolve()), "capture_size": size,
                      "frozen": bool(getattr(sys, "frozen", False)), "config_sha256": config.fingerprint(),
                      "duration": duration, "frames_processed": len(samples),
                      "effective_sampling_hz": len(samples) / duration,
                      "median_processing_ms": statistics.median(values) if values else None,
                      "p95_processing_ms": values[max(0, round(.95 * len(values)) - 1)] if values else None,
                      "events": events, "confirmed_total": ledger.stats()["all"],
                      "candidate_metrics": {key: metrics[key] for key in ("matched", "missed", "false", "duplicates")},
                      "errors": [detail for status, detail in statuses if status == "Needs calibration"],
                      "actual_game_capture_tested": False, "release_gate": False,
                      "note": "Timed worker, real-time lossless replay, temporary SQLite ledger. Development clip; not held-out accuracy."}
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            output.with_suffix(".frames.jsonl").write_text("\n".join(json.dumps(row) for row in samples), encoding="utf-8")
            return report
        finally:
            module.Capture, module.Perception = original_capture, original_vision
            ledger.close()
            frames._mmap.close()
            cache_file.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--height", type=int)
    args = parser.parse_args()
    if args.height is not None and not 360 <= args.height <= 2160:
        parser.error("Replay height must be 360-2160 pixels")
    print(json.dumps(replay(args.video, Config.read(args.config), args.labels, args.output, args.height), indent=2))


if __name__ == "__main__":
    main()
