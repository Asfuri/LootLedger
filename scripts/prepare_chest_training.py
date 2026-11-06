"""Prepare local, reviewable chest-state crops from the supplied recording.

These are training annotations. Testing this recording afterwards is a regression
check, not independent accuracy validation. No pictures are added to the ledger.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


# Approximate annotation windows in the supplied 1920x1080 recording.
# Transition/loot-only frames are excluded; gold pixels tighten each window.
ANNOTATIONS = [
    (0.8, "closed", [890, 430, 1150, 740]),
    (1.0, "closed", [890, 430, 1150, 740]),
    (1.3, "closed", [890, 430, 1150, 740]),
    (1.45, "closed", [890, 430, 1150, 740]),
    (1.9, "opened", [950, 500, 1280, 900]),
    (2.0, "opened", [950, 500, 1280, 900]),
    (9.8, "closed", [790, 430, 1050, 840]),
    (10.0, "closed", [790, 430, 1050, 840]),
    (10.25, "closed", [790, 430, 1050, 840]),
    (10.45, "closed", [790, 430, 1050, 840]),
    (11.0, "closed", [790, 440, 1050, 760]),
    (11.25, "closed", [790, 440, 1050, 760]),
    (11.5, "closed", [790, 440, 1050, 760]),
    (11.65, "closed", [790, 440, 1050, 760]),
    (12.2, "opened", [740, 430, 1090, 850]),
    (16.6, "closed", [740, 500, 1060, 880]),
    (16.9, "closed", [740, 500, 1060, 880]),
    (17.15, "closed", [740, 500, 1060, 880]),
]


def prepare(video, profile, output):
    output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError("Cannot open the supplied recording")
    manifest = {"video": str(video.resolve()), "independent_validation": False,
                "note": "Small training set from four ornate gold chests; broader chest types and negatives unverified.",
                "crops": [], "backgrounds": [], "frames": [], "scene_backgrounds": []}
    tiles = []
    try:
        for index, (stamp, state, window) in enumerate(ANNOTATIONS):
            capture.set(cv2.CAP_PROP_POS_MSEC, stamp * 1000)
            ok, frame = capture.read()
            if not ok:
                raise ValueError(f"Missing annotated frame {stamp}")
            x1, y1, x2, y2 = window
            crop = frame[y1:y2, x1:x2]
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, (12, 90, 110), (45, 255, 255))
            points = cv2.findNonZero(mask)
            if points is None or len(points) < 100:
                raise ValueError(f"Review annotation at {stamp}: no chest pixels")
            x, y, w, h = cv2.boundingRect(points)
            x, y = max(0, x - 6), max(0, y - 6)
            right, bottom = min(crop.shape[1], x + w + 12), min(crop.shape[0], y + h + 12)
            crop = crop[y:bottom, x:right]
            path = output / f"{state}-{index:02d}.png"
            cv2.imwrite(str(path), crop)
            manifest["crops"].append({"file": path.name, "state": state, "time": stamp,
                                      "box": [x1 + x, y1 + y, x1 + right, y1 + bottom]})
            full_path = output / f"scene-{index:02d}.jpg"
            cv2.imwrite(str(full_path), frame)
            boxes = [[x1 + x, y1 + y, x1 + right, y1 + bottom]]
            labels = [1 if state == "closed" else 2]
            secondary = ([0, 800, 225, 1080], 1) if 9.8 <= stamp <= 10.45 else (
                        ([1180, 780, 1810, 1080], 2) if 11 <= stamp <= 12.2 else None)
            if secondary:
                (sx1, sy1, sx2, sy2), slabel = secondary
                extra = cv2.inRange(cv2.cvtColor(frame[sy1:sy2, sx1:sx2], cv2.COLOR_BGR2HSV),
                                    (12, 90, 110), (45, 255, 255))
                extra = cv2.morphologyEx(extra, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
                _, _, stats, _ = cv2.connectedComponentsWithStats(extra)
                if len(stats) > 1:
                    ex, ey, ew, eh, area = max(stats[1:], key=lambda s: s[4])
                    if ew > 60 and eh > 60 and area > 500:
                        boxes.append([max(0, int(sx1 + ex - 5)), max(0, int(sy1 + ey - 5)),
                                      min(1920, int(sx1 + ex + ew + 5)), min(1080, int(sy1 + ey + eh + 5))])
                        labels.append(slabel)
            manifest["frames"].append({"file": full_path.name, "state": state, "boxes": boxes, "labels": labels})
            tile = np.full((220, 260, 3), 22, np.uint8)
            ratio = min(250 / crop.shape[1], 190 / crop.shape[0])
            small = cv2.resize(crop, None, fx=ratio, fy=ratio)
            tile[:small.shape[0], :small.shape[1]] = small
            cv2.putText(tile, f"{state} {stamp:.2f}s", (5, 213), cv2.FONT_HERSHEY_SIMPLEX,
                        .55, (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(tile)
        for index, stamp in enumerate((0, 3, 5, 7, 9, 13, 14, 16, 18)):
            capture.set(cv2.CAP_PROP_POS_MSEC, stamp * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            # These upper-left environment patches contain no chests or HUD.
            path = output / f"background-{index}.jpg"
            cv2.imwrite(str(path), frame[100:450, 20:650])
            manifest["backgrounds"].append(path.name)
        for stamp in (3., 6.):
            capture.set(cv2.CAP_PROP_POS_MSEC, stamp * 1000)
            ok, frame = capture.read()
            if ok:
                path = output / f"player-background-{stamp:.0f}.jpg"
                cv2.imwrite(str(path), frame)
                manifest["scene_backgrounds"].append(path.name)
    finally:
        capture.release()
    config = json.loads(profile.read_text(encoding="utf-8"))
    for spec in config["templates"]:
        if spec["state"] not in ("closed", "opened"):
            continue
        path = output / f"setup-{spec['state']}.png"
        path.write_bytes(Path(spec["path"]).read_bytes())
        manifest["crops"].append({"file": path.name, "state": spec["state"], "source": "User setup crop"})
    (output / "annotations.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tiles += [np.zeros((220, 260, 3), np.uint8)] * ((4 - len(tiles) % 4) % 4)
    cv2.imwrite(str(output / "review.jpg"), np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]))
    print(f"Prepared {len(manifest['crops'])} annotated crops; inspect {output / 'review.jpg'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("local-data/chest-training"))
    args = parser.parse_args()
    cv2.setNumThreads(2)
    prepare(args.video, args.profile, args.output)
