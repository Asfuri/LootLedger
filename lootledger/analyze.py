"""Offline pipeline and one-to-one comparison against human-labelled footage."""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path

import cv2

from .config import Config, model_folder
from .calibration import fit_image
from .detector import Detector
from .vision import Perception, WindowsOCR, region

REQUIRED_SCENARIOS = {"openings", "other_containers", "cancelled_searches", "overlapping_xp", "rapid_openings", "spectating"}


def compare(events, labels, tolerance=.5):
    truth = labels["openings"]
    if not .01 <= tolerance <= 5:
        raise ValueError("Timestamp tolerance must be 0.01–5 seconds")
    if any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 for t in truth):
        raise ValueError("Labels must contain nonnegative opening timestamps")
    remaining = set(range(len(truth)))
    confirmed = [e for e in events if e["status"] == "confirmed"]
    matched, false, duplicate = [], [], []
    for event in sorted(confirmed, key=lambda e: e["time"]):
        choices = [i for i in remaining if abs(truth[i] - event["time"]) <= tolerance]
        if choices:
            i = min(choices, key=lambda i: truth[i])
            remaining.remove(i)
            matched.append({"truth": truth[i], "detected": event["time"]})
        elif any(abs(t - event["time"]) <= tolerance for t in truth):
            duplicate.append(event["time"])
        else:
            false.append(event["time"])
    scenarios = set(labels.get("scenarios", []))
    real = labels.get("real_footage") is True
    return {"ground_truth": len(truth), "timestamp_tolerance": tolerance,
            "confirmed_candidates": len(confirmed), "matched": len(matched),
            "missed": len(remaining), "false": len(false), "duplicates": len(duplicate),
            "missed_timestamps": [truth[i] for i in sorted(remaining)], "false_timestamps": false,
            "duplicate_timestamps": duplicate, "pairs": matched,
            "review_candidates": sum(e["status"] == "review" for e in events),
            "real_footage": real,
            # This is a minimum local release gate, not a statistical accuracy guarantee.
            "release_gate": bool(real and len(truth) >= 10 and REQUIRED_SCENARIOS <= scenarios
                                 and tolerance <= .5 and not remaining and not false and not duplicate)}


def analyze(video, config, output, labels=None, evidence_dir=None, tolerance=.5):
    started = time.perf_counter()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"Cannot decode video: {video}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        capture.release()
        raise ValueError("Video has no usable frame rate")
    if config.calibration_errors():
        capture.release()
        raise ValueError("; ".join(config.calibration_errors()))
    ocr = WindowsOCR(config.language)
    events, frames, sample_times = [], 0, []
    try:
        perception, detector = Perception(config, ocr), Detector(config)
        initialization_seconds = time.perf_counter() - started
        # Decode in order so variable notification sequences are not skipped by inaccurate seeks.
        index, next_sample = 0, 0.
        with output.with_suffix(".frames.jsonl").open("w", encoding="utf-8") as trace:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                stamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if stamp <= 0 and index:
                    stamp = index / fps
                index += 1
                if stamp + .0001 < next_sample:
                    continue
                next_sample = stamp + 1 / config.frame_hz
                sample_started = time.perf_counter()
                obs = perception.observe(fit_image(frame, config.frame_size) if config.detector_backend == "template" else frame, stamp)
                detected = detector.feed(obs)
                sample_times.append(time.perf_counter() - sample_started)
                for event in detected:
                    payload = asdict(event)
                    if evidence_dir is not None and config.evidence:
                        folder = Path(evidence_dir) / event.id
                        folder.mkdir(parents=True, exist_ok=True)
                        for name in ("chest", "search", "xp"):
                            ok, encoded = cv2.imencode(".png", region(frame, config.regions[name]))
                            if ok:
                                (folder / f"{name}.png").write_bytes(encoded.tobytes())
                        payload["evidence"] = str(folder)
                    events.append(payload)
                trace.write(json.dumps(asdict(obs)) + "\n")
                frames += 1
            events.extend(asdict(event) for event in detector.finish())
    finally:
        ocr.close()
        capture.release()
    digest = hashlib.sha256()
    with Path(video).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    report = {"video": str(Path(video).resolve()), "video_sha256": digest.hexdigest(),
              "config_sha256": config.fingerprint(), "frames_analyzed": frames, "events": events,
              "real_footage": False, "release_gate": False,
              "note": "Candidate confirmation is not an accuracy claim. Compare against human labels."}
    if labels:
        truth = json.loads(Path(labels).read_text(encoding="utf-8"))
        report.update(compare(events, truth, tolerance))
        candidates = compare([{**event, "status": "confirmed"} for event in events], truth, tolerance)
        report["candidate_metrics"] = {key: candidates[key] for key in
            ("ground_truth", "matched", "missed", "false", "duplicates", "pairs")}
    if config.detector_backend == "model":
        card = json.loads((model_folder() / "chest-model.json").read_text(encoding="utf-8"))
        report["model_training_overlap"] = report["video_sha256"] in card.get("training_video_sha256", [])
        if report["model_training_overlap"]:
            report["release_gate"] = False
            report["note"] = "Training-source regression only. This recording cannot approve the model for automatic totals."
    report["elapsed_seconds"] = time.perf_counter() - started
    report["processing_fps"] = frames / report["elapsed_seconds"]
    report["initialization_seconds"] = initialization_seconds
    report["sample_processing_seconds"] = sum(sample_times)
    report["median_frame_processing_ms"] = statistics.median(sample_times) * 1000 if sample_times else 0
    report["p95_frame_processing_ms"] = sorted(sample_times)[max(0, math.ceil(len(sample_times) * .95) - 1)] * 1000 if sample_times else 0
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Analyze footage without changing your chest ledger")
    parser.add_argument("video", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("analysis.json"))
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--tolerance", type=float, default=.5)
    args = parser.parse_args()
    try:
        report = analyze(args.video, Config.read(args.config), args.output, args.labels, args.evidence_dir, args.tolerance)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"Analysis failed: {error}\n")
    print(json.dumps({k: v for k, v in report.items() if k != "events"}, indent=2))
    for event in report["events"]:
        print(f'{event["time"]:8.3f}s  {event["status"]:9}  {event["confidence"]:.2f}  {event["reason"]}')


if __name__ == "__main__":
    main()
