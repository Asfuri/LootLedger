"""Three guided selections; the remaining regions use adjustable HUD defaults."""
from copy import deepcopy
from pathlib import Path
import hashlib
import uuid

import cv2

from .vision import region


STEPS = (
    ("closed", "Closed chest", "Point at an unopened chest. Draw a tight box around the chest itself."),
    ("progress", "Interaction circle", "On the same picture, draw a box around the circle surrounding the interact key, beside SEARCH."),
    ("opened", "Opened chest", "Open that chest, then capture another picture. Draw a tight box around its opened shape."),
)


def completed_steps(config):
    states = {t["state"] for t in config.templates if Path(t["path"]).is_file()}
    return {"closed": "closed" in states and "hud" in states,
            "progress": config.progress_calibrated, "opened": "opened" in states}


def fit_image(frame, size):
    """Uploaded screenshots may be downscaled; retain the selected capture's pixel scale."""
    if not size or [frame.shape[1], frame.shape[0]] == size:
        return frame
    width, height = size
    if abs((frame.shape[1] / frame.shape[0]) / (width / height) - 1) > .02:
        raise ValueError("This picture has a different shape from your game capture. Use a full game screenshot.")
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_CUBIC)


def is_before_image(config, frame):
    digest = hashlib.sha256(frame.tobytes()).hexdigest()
    return any(t["state"] == "closed" and t.get("frame_sha256") == digest for t in config.templates)


def save_step(config, folder, state, frame, rect):
    candidate = deepcopy(config)
    if state not in {step[0] for step in STEPS}:
        raise ValueError("Unknown setup step")
    if state == "opened" and is_before_image(config, frame):
        raise ValueError("Capture a new picture after opening the chest first")
    candidate.regions["chest"] = rect
    candidate.validate()
    candidate.regions["chest"] = list(config.regions["chest"])
    height, width = frame.shape[:2]
    size = [width, height]
    if config.frame_size and config.frame_size != size:
        if state != "closed":
            raise ValueError("The capture size changed. Start with Closed chest again.")
        candidate.templates = []
        candidate.progress_calibrated = False
    candidate.frame_size = size
    folder = Path(folder)
    references = folder / "templates"
    references.mkdir(parents=True, exist_ok=True)

    def reference(kind, box):
        crop = region(frame, box)
        if min(crop.shape[:2]) < 8 or cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).std() < 4:
            raise ValueError("That box is too small or has too little detail. Draw it around the visible object.")
        ok, encoded = cv2.imencode(".png", crop)
        if not ok:
            raise ValueError("Cannot save setup picture")
        path = references / f"{kind}-{uuid.uuid4().hex[:10]}.png"
        path.write_bytes(encoded.tobytes())
        candidate.templates = [t for t in candidate.templates if not (t.get("guided") and t["state"] == kind)]
        candidate.templates.append({"path": str(path.resolve()), "state": kind, "type": "Unknown",
                                    "source": "User-selected setup picture", "guided": True,
                                    "frame_sha256": hashlib.sha256(frame.tobytes()).hexdigest()})

    if state == "progress":
        x, y, w, h = rect
        cx, cy = x + w / 2, y + h / 2
        side = min(max(w * width, h * height), 2 * cx * width, 2 * (1 - cx) * width,
                   2 * cy * height, 2 * (1 - cy) * height)
        if side < 12:
            raise ValueError("Include the whole interaction circle in your box")
        candidate.regions["progress"] = [cx - side / width / 2, cy - side / height / 2, side / width, side / height]
        left, top = max(0, cx - side / width), max(0, cy - side / height)
        right, bottom = min(1, cx + max(.16, side / width * 5)), min(1, cy + side / height)
        candidate.regions["search"] = [left, top, right - left, bottom - top]
        candidate.progress_calibrated = True
    else:
        reference(state, rect)
        if state == "closed":
            # This is a search area, not the position of the example chest.
            x, y, w, h = rect
            left, top = max(0, min(.20, x - .08)), max(0, min(.20, y - .08))
            right, bottom = min(1, max(.85, x + w + .08)), min(1, max(.88, y + h + .08))
            candidate.regions["chest"] = [left, top, right - left, bottom - top]
            reference("hud", candidate.regions["hud"])
    candidate.validate()
    # The picture is retained for returning to the guide; it is not detection evidence.
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("Cannot save setup preview")
    preview = folder / "setup-preview.tmp"
    preview.write_bytes(encoded.tobytes())
    preview.replace(folder / "setup-preview.png")
    candidate.save(folder / "config.json")
    return candidate
