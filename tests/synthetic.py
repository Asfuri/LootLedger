"""Artificial geometry, not Fortnite imagery. Only a pipeline wiring fixture."""
from pathlib import Path

import cv2
import numpy as np

from lootledger.config import Config


def make_clip(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    random = np.random.default_rng(84)
    base = random.integers(35, 160, (42, 60, 3), dtype=np.uint8)
    closed, opened = base.copy(), base.copy()
    closed[:22] = random.integers(30, 240, (22, 60, 3), dtype=np.uint8)
    opened[:22] = random.integers(30, 240, (22, 60, 3), dtype=np.uint8)
    hud = random.integers(40, 245, (25, 45, 3), dtype=np.uint8)
    templates = []
    for state, image in (("closed", closed), ("opened", opened), ("hud", hud)):
        path = folder / f"{state}.png"
        cv2.imwrite(str(path), image)
        templates.append({"path": str(path.resolve()), "state": state, "type": "Unknown"})
    config = Config(detector_backend="template", match_threshold=.82, frame_size=[960, 540], templates=templates, frame_hz=10, progress_calibrated=True, regions={
        "chest": [.30, .32, .30, .38], "search": [.63, .50, .30, .12],
        "progress": [.75, .69, .10, .1777777778], "xp": [.55, .20, .40, .23],
        "hud": [.02, .85, .15, .10], "mode": [.10, .02, .70, .13]})
    config_path = folder / "config.json"
    config.save(config_path)
    path = folder / "synthetic.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (960, 540))
    if not writer.isOpened():
        raise RuntimeError("MJPG video encoder unavailable")
    frames = []
    try:
        for index in range(40):
            frame = np.full((540, 960, 3), 12, dtype=np.uint8)
            frame[465:490, 25:70] = hud
            # Two artificial opening cycles, 1.6 s apart; notification clears between them.
            phase = index % 16
            present = index < 32 and 1 <= phase <= 10
            if present:
                frame[252:294, 450:510] = closed if phase <= 6 else opened
            if present and phase <= 6:
                cv2.putText(frame, "SEARCH", (615, 312), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2)
                angle = min(350, 20 + (phase - 1) * 70)
                cv2.ellipse(frame, (768, 420), (36, 36), 0, 0, angle, (255, 255, 255), 4)
            if index < 32 and 7 <= phase <= 12:
                cv2.putText(frame, "+1350 XP", (575, 142), cv2.FONT_HERSHEY_SIMPLEX, .9, (230, 85, 195), 2)
                cv2.putText(frame, "CHEST", (606, 173), cv2.FONT_HERSHEY_SIMPLEX, .7, (255, 255, 255), 2)
            frames.append(frame)
            writer.write(frame)
    finally:
        writer.release()
    return path, config_path, frames
