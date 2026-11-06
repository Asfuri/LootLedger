from dataclasses import dataclass
import asyncio
import re
import unicodedata
from pathlib import Path

import cv2
import numpy as np
# Load the inference runtime before Windows OCR initializes native ML libraries.
import onnxruntime

from .detector import Observation, Target


@dataclass
class Line:
    text: str
    x: float
    y: float
    w: float
    h: float


@dataclass
class ChestLabel(Line):
    count: int = 1


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).upper().split())


def region(frame, rect):
    height, width = frame.shape[:2]
    x, y, w, h = rect
    return frame[round(y * height):round((y + h) * height),
                 round(x * width):round((x + w) * width)]


class WindowsOCR:
    """Windows' local OCR. No cloud API or downloaded recognition model."""
    def __init__(self, language):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        self.engine = OcrEngine.try_create_from_language(Language(language))
        if self.engine is None:
            raise RuntimeError(f"Install the Windows OCR language pack for {language} in Windows Settings")
        self.loop = asyncio.new_event_loop()

    async def _read(self, crop, words=False):
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
        from winrt.windows.storage.streams import DataWriter
        writer = DataWriter()
        bitmap = None
        try:
            pixels = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
            writer.write_bytes(pixels.tobytes())
            bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                         crop.shape[1], crop.shape[0])
            result = await self.engine.recognize_async(bitmap)
            lines = []
            for line in result.lines:
                if words:
                    for word in line.words:
                        b = word.bounding_rect
                        lines.append(Line(word.text, b.x, b.y, b.width, b.height))
                    continue
                boxes = [word.bounding_rect for word in line.words]
                if not boxes:
                    continue
                x, y = min(b.x for b in boxes), min(b.y for b in boxes)
                lines.append(Line(line.text, x, y, max(b.x + b.width for b in boxes) - x,
                                  max(b.y + b.height for b in boxes) - y))
            return lines
        finally:
            if bitmap is not None:
                bitmap.close()
            writer.close()

    def read(self, crop, words=False):
        # Upscaling improves small HUD text; return boxes in original crop coordinates.
        enlarged = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        result = self.loop.run_until_complete(self._read(enlarged, words))
        return [Line(l.text, l.x / 2, l.y / 2, l.w / 2, l.h / 2) for l in result]

    def close(self):
        self.loop.close()


def chest_xp_lines(crop, lines, label):
    """Exact chest label with optional award multiplier, paired with purple XP."""
    labels = []
    for line in lines:
        match = re.fullmatch(re.escape(normalized(label)) + r"(?:\s*[X×]\s*([1-9]\d?))?", normalized(line.text).rstrip(".,"))
        if match is None:
            continue
        candidates = [above for above in lines
                      if re.fullmatch(r"[+＋]\s*\d[\d\s.,]*\s*XP", normalized(above.text))
                      and .3 * line.h <= line.y - above.y <= 3.5 * max(line.h, above.h)
                      and abs((line.x + line.w / 2) - (above.x + above.w / 2)) <= max(above.w, line.w)]
        if not candidates:
            continue
        above = min(candidates, key=lambda a: abs(line.y - a.y))
        patch = crop[max(0, int(above.y)):int(above.y + above.h + 1),
                     max(0, int(above.x)):int(above.x + above.w + 1)]
        if patch.size:
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            purple = cv2.inRange(hsv, (120, 65, 65), (170, 255, 255))
            if np.mean(purple > 0) >= .035:
                labels.append(ChestLabel(line.text, line.x, line.y, line.w, line.h, int(match[1] or 1)))
    return labels


class NotificationTracker:
    def __init__(self):
        self.items = {}
        self.serial = 0

    def update(self, lines, stamp):
        self.items = {k: v for k, v in self.items.items() if stamp - v[1] <= .6}
        available = set(self.items)
        tokens = []
        for line in sorted(lines, key=lambda l: l.y):
            nearest = min(available, key=lambda k: abs(self.items[k][0] - line.y), default=None)
            if nearest is not None and abs(self.items[nearest][0] - line.y) <= max(18, line.h * 1.4):
                key = nearest
                available.remove(key)
            else:
                self.serial += 1
                key = f"xp-{self.serial}"
            count = getattr(line, "count", 1)
            _, _, previous_count, hits, confirmed = self.items.get(key, (line.y, stamp, 0, 0, 0))
            hits = hits + 1 if count == previous_count else 1
            if hits >= 2:
                confirmed = max(confirmed, count)
            self.items[key] = (line.y, stamp, count, hits, confirmed)
            # A changing XP amount is never a new award; only a stable label increment is.
            tokens.extend(key if i == 1 else f"{key}:{i}" for i in range(1, confirmed + 1))
        for key in available:
            y, seen, count, _, confirmed = self.items[key]
            self.items[key] = (y, seen, count, 0, confirmed)
        return tokens


def ring_progress(crop):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    yy, xx = np.indices((h, w))
    radius = np.hypot(xx - w / 2, yy - h / 2)
    annulus = (radius >= min(h, w) * .29) & (radius <= min(h, w) * .46)
    angle = ((np.arctan2(yy - h / 2, xx - w / 2) + np.pi) / (2 * np.pi) * 72).astype(int) % 72
    hits = [np.any((gray > 205) & annulus & (angle == i)) for i in range(72)]
    return sum(hits) / 72


def overlap(a, b):
    x, y = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    area = max(0, right - x) * max(0, bottom - y)
    return area / max(1, a[2] * a[3] + b[2] * b[3] - area)


class Perception:
    def __init__(self, config, ocr):
        self.config, self.ocr = config, ocr
        self.model = None
        if config.detector_backend == "model":
            from .screenvision import ScreenPerception
            self.model = ScreenPerception(config, ocr)
            return
        self.templates = []
        for spec in config.templates:
            path = Path(spec["path"])
            bitmap = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
            if bitmap is None or min(bitmap.shape) < 8 or bitmap.std() < 4:
                raise ValueError(f"Invalid or featureless template: {path}")
            self.templates.append((spec, bitmap))
        self.objects = {}
        self.next_key = 0
        self.previous = None
        self.notifications = NotificationTracker()

    def matches(self, frame, state):
        hits = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        for spec, bitmap in self.templates:
            if spec["state"] != state:
                continue
            for scale in (.85, 1., 1.15):
                sample = cv2.resize(bitmap, None, fx=scale, fy=scale)
                if sample.shape[0] > gray.shape[0] or sample.shape[1] > gray.shape[1]:
                    continue
                score = cv2.matchTemplate(gray, sample, cv2.TM_CCOEFF_NORMED)
                for _ in range(4):
                    _, value, _, point = cv2.minMaxLoc(score)
                    if value < self.config.match_threshold:
                        break
                    x, y = point
                    h, w = sample.shape
                    hits.append((value, [x, y, w, h], spec.get("type", "Unknown"), state))
                    score[max(0, y - h // 2):y + h // 2 + 1, max(0, x - w // 2):x + w // 2 + 1] = -1
        kept = []
        for hit in sorted(hits, reverse=True):
            if not any(hit[2] == other[2] and overlap(hit[1], other[1]) > .25 for other in kept):
                kept.append(hit)
        return kept

    def observe(self, frame, stamp):
        if self.model is not None:
            # Keep HUD OCR and pixel work bounded on 1440p/4K displays.
            if frame.shape[0] > 1080:
                frame = cv2.resize(frame, (round(frame.shape[1] * 1080 / frame.shape[0]), 1080), interpolation=cv2.INTER_CUBIC)
            return self.model.observe(frame, stamp)
        cfg = self.config
        h, w = frame.shape[:2]
        if cfg.frame_size and cfg.frame_size != [w, h]:
            raise ValueError(f"Capture is {w}×{h}; recalibrate from {cfg.frame_size}")
        crops = {name: region(frame, rect) for name, rect in cfg.regions.items()}
        lines = {name: self.ocr.read(crops[name]) for name in ("xp", "search", "mode")}
        text = {name: " | ".join(l.text for l in values) for name, values in lines.items()}
        mode = normalized(text["mode"])
        blocked = any(normalized(word) in mode for word in cfg.blocked_labels)
        active = bool(self.matches(crops["hud"], "hud")) and not blocked
        if not active:
            self.objects.clear()
            self.previous = None
            self.notifications.update([], stamp)
            return Observation(stamp, False, text=text)

        chest = crops["chest"]
        gray = cv2.cvtColor(chest, cv2.COLOR_BGR2GRAY)
        # Track camera motion through local feature flow; a lost object gets no opened-state inference.
        if self.previous is not None:
            for item in self.objects.values():
                x, y, bw, bh = item["box"]
                mask = np.zeros_like(self.previous)
                mask[max(0, y):y + bh, max(0, x):x + bw] = 255
                points = cv2.goodFeaturesToTrack(self.previous, 25, .04, 4, mask=mask)
                item["flow"] = False
                if points is None:
                    continue
                moved, status, _ = cv2.calcOpticalFlowPyrLK(self.previous, gray, points, None)
                if moved is None:
                    continue
                valid = status.ravel() == 1
                if valid.sum() >= 4:
                    delta = (moved - points)[valid].reshape(-1, 2)
                    median = np.median(delta, axis=0)
                    if np.median(np.linalg.norm(delta - median, axis=1)) < 9:
                        item["box"] = [round(x + median[0]), round(y + median[1]), bw, bh]
                        item["flow"] = True
        detections = self.matches(chest, "closed") + self.matches(chest, "opened")
        detections.sort(reverse=True)
        association_age = max(.35, 1.5 / cfg.frame_hz)
        available = {k for k, v in self.objects.items() if stamp - v["seen"] <= association_age and v["flow"]}
        targets = []
        boxes = {}
        for score, box, kind, state in detections:
            if any(overlap(box, used) > .4 for used in boxes.values()):
                continue
            compatible = [k for k in available if not (state == "closed" and self.objects[k]["state"] == "opened")]
            nearest = max(compatible, key=lambda k: (overlap(box, self.objects[k]["box"]), self.objects[k]["seen"]), default=None)
            if nearest is not None and overlap(box, self.objects[nearest]["box"]) > .18:
                key = nearest
                available.remove(key)
            else:
                self.next_key += 1
                key = self.next_key
            # No claimed appearance classification unless the crop carries a source attribution.
            type_specs = [s for s, _ in self.templates if s["state"] == "closed" and s.get("type") == kind]
            supported = kind != "Unknown" and any(s.get("source") for s in type_specs)
            rivals = [hit[0] for hit in detections if state == "closed" and hit[3] == "closed"
                      and hit[2] != kind and overlap(box, hit[1]) > .4]
            if not supported or (rivals and score - max(rivals) < cfg.type_margin):
                kind = "Unknown"
            self.objects[key] = {"box": box, "seen": stamp, "flow": True, "state": state}
            targets.append(Target(key, score if state == "closed" else 0,
                                  score if state == "opened" else 0, kind))
            boxes[key] = box
        self.objects = {k: v for k, v in self.objects.items() if stamp - v["seen"] <= association_age}
        self.previous = gray
        cross_x = (.5 - cfg.regions["chest"][0]) * w
        cross_y = (.5 - cfg.regions["chest"][1]) * h
        focus = min(boxes, key=lambda k: (boxes[k][0] + boxes[k][2] / 2 - cross_x) ** 2
                    + (boxes[k][1] + boxes[k][3] / 2 - cross_y) ** 2, default=None)
        if focus is not None:
            box = boxes[focus]
            if abs(box[0] + box[2] / 2 - cross_x) > w * .13 or abs(box[1] + box[3] / 2 - cross_y) > h * .25:
                focus = None
        search = normalized(cfg.search_label) in re.findall(r"[\wÀ-ÿ]+", normalized(text["search"]))
        xp = self.notifications.update(chest_xp_lines(crops["xp"], lines["xp"], cfg.chest_label), stamp)
        return Observation(stamp, True, targets, search,
                           ring_progress(crops["progress"]) if search else None, xp, text, focus)
