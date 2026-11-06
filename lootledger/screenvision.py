"""Local chest-state recognition and moving interaction evidence.

The bundled small training set does not establish general gameplay accuracy.
The worker's footage gate keeps unvalidated events in review.
"""
import json
import math

import cv2
import numpy as np
import onnxruntime as ort

from .config import model_folder
from .detector import Observation, Target
from .vision import Line, NotificationTracker, chest_xp_lines, normalized, overlap, region, ring_progress


def health_hud(crop, frame_width):
    """Recognize health-bar geometry instead of matching health values/background."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (38, 85, 90), (90, 255, 255))
    count, _, stats, _ = cv2.connectedComponentsWithStats(green)
    for x, y, w, h, area in stats[1:]:
        if w >= frame_width * .035 and 3 <= h <= crop.shape[0] * .65 and w / h >= 4 and area / (w * h) > .6:
            return True
    # At low health only a narrow green sliver remains. Require the adjacent + icon.
    white = cv2.inRange(hsv, (0, 0, 175), (179, 70, 255))
    count, _, stats, _ = cv2.connectedComponentsWithStats(white)
    for x, y, w, h, area in stats[1:]:
        if min(w, h) < 5 or not .65 < w / h < 1.5 or not .3 < area / (w * h) < .85:
            continue
        patch = white[y:y + h, x:x + w] > 0
        if patch[h // 2].mean() > .7 and patch[:, w // 2].mean() > .7:
            if np.count_nonzero(green[max(0, y - h):y + 2 * h, x + w:]) >= 8:
                return True
    return False


def decode_boxes(regression, anchors, weights):
    sizes = anchors[:, 2:] - anchors[:, :2]
    centers = anchors[:, :2] + sizes / 2
    delta = regression / np.asarray(weights)
    predicted_centers = delta[:, :2] * sizes + centers
    predicted_sizes = np.exp(np.minimum(delta[:, 2:], math.log(1000 / 16))) * sizes
    return np.column_stack((predicted_centers - predicted_sizes / 2, predicted_centers + predicted_sizes / 2))


class ChestModel:
    def __init__(self):
        folder = model_folder()
        self.card = json.loads((folder / "chest-model.json").read_text(encoding="utf-8"))
        self.size = self.card["input_size"]
        with np.load(folder / "chest-anchors.npz", allow_pickle=False) as data:
            self.anchors = data["anchors"].copy()
        cv2.setNumThreads(2)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        providers = ["DmlExecutionProvider", "CPUExecutionProvider"] if "DmlExecutionProvider" in ort.get_available_providers() else ["CPUExecutionProvider"]
        try:
            self.session = ort.InferenceSession(str(folder / "chest-state.onnx"), sess_options=options, providers=providers)
        except Exception:
            if providers == ["CPUExecutionProvider"]:
                raise
            self.session = ort.InferenceSession(str(folder / "chest-state.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
        self.provider = self.session.get_providers()[0]
        self.session.run(["boxes", "logits"], {"image": np.zeros((1, 3, self.size, self.size), np.float32)})

    def detect(self, frame, threshold):
        h, w = frame.shape[:2]
        scale = min(self.size / w, self.size / h)
        width, height = round(w * scale), round(h * scale)
        left, top = (self.size - width) // 2, (self.size - height) // 2
        image = np.full((self.size, self.size, 3), 114, np.uint8)
        image[top:top + height, left:left + width] = cv2.resize(frame, (width, height))
        regression, logits = self.session.run(["boxes", "logits"],
            {"image": cv2.dnn.blobFromImage(image, 1 / 255, swapRB=True)})
        values = logits[0] - np.max(logits[0], axis=1, keepdims=True)
        probabilities = np.exp(values)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        states = probabilities[:, 1:].argmax(axis=1) + 1
        scores = probabilities[np.arange(len(states)), states]
        selected = np.flatnonzero(scores >= threshold)
        if not len(selected):
            return []
        boxes = decode_boxes(regression[0, selected], self.anchors[selected], self.card["box_coder_weights"])
        boxes[:, [0, 2]] = (boxes[:, [0, 2]] - left) / scale
        boxes[:, [1, 3]] = (boxes[:, [1, 3]] - top) / scale
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
        xywh = boxes.copy()
        xywh[:, 2:] -= xywh[:, :2]
        kept = cv2.dnn.NMSBoxes(xywh.tolist(), scores[selected].tolist(), threshold, .4)
        return [(float(scores[selected[i]]), xywh[i].tolist(),
                 "closed" if states[selected[i]] == 1 else "opened")
                for i in np.asarray(kept).reshape(-1) if min(xywh[i, 2:]) >= 8]


def text_bands(crop, scale=1., *, purple=False):
    """Limit OCR to rows of separate text-sized glyphs, excluding solid jewels/edges."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = (cv2.inRange(hsv, (120, 65, 90), (170, 255, 255)) if purple else
            cv2.inRange(hsv, (0, 0, 190), (179, 95, 255)))
    _, _, glyphs, _ = cv2.connectedComponentsWithStats(mask)
    kernel = np.ones((max(1, round(scale)), max(3, round((13 if purple else 7) * scale))), np.uint8)
    merged = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    _, _, rows, _ = cv2.connectedComponentsWithStats(merged)
    result = []
    for x, y, w, h, area in rows[1:]:
        if not (6 * scale <= h <= 48 * scale and 22 * scale <= w <= 650 * scale and w / h >= 1.8):
            continue
        letters = glyphs[1:]
        inside = ((letters[:, 0] >= x) & (letters[:, 1] >= y)
                  & (letters[:, 0] + letters[:, 2] <= x + w)
                  & (letters[:, 1] + letters[:, 3] <= y + h)
                  & (letters[:, 3] >= 3 * scale)
                  & (letters[:, 2] <= (w if purple else h * 1.5)))
        if np.count_nonzero(inside) < (2 if purple else 3):
            continue
        # Windows OCR drops tightly clipped short words; retain dark context.
        pad = max(12, round(12 * scale))
        left, top = max(0, x - pad), max(0, y - pad)
        right, bottom = min(crop.shape[1], x + w + pad), min(crop.shape[0], y + h + pad)
        result.append([left, top, right - left, bottom - top])
    return sorted(result, key=lambda box: box[1])[:16]


def search_evidence(frame, box, ocr, label, cache=None):
    """Anchor the key circle to exact SEARCH word geometry near this chest."""
    height, width = frame.shape[:2]
    x, y, w, h = box
    if cache is None:
        cache = {}
    center = (x + w / 2, y + h / 2)
    left, top = max(0, round(x + w * .15)), max(0, round(y - h * .1))
    right, bottom = min(width, round(x + w + width * .085)), min(height, round(y + h * 1.1))
    crop = frame[top:bottom, left:right]
    if not crop.size:
        return False, None, ""
    words = []
    if "label" in cache:
        tx, ty, tw, th = cache["label"]
        dx, dy = center[0] - cache["center"][0], center[1] - cache["center"][1]
        margin = max(18, th * 2.5)
        nx1, ny1 = max(0, round(tx + dx - margin)), max(0, round(ty + dy - margin))
        nx2, ny2 = min(width, round(tx + dx + tw + margin)), min(height, round(ty + dy + th + margin))
        if nx2 > nx1 and ny2 > ny1:
            local_image = frame[ny1:ny2, nx1:nx2]
            if "bitmap" in cache and min(local_image.shape[:2]) >= min(cache["bitmap"].shape):
                gray = cv2.cvtColor(local_image, cv2.COLOR_BGR2GRAY)
                if gray.shape[0] >= cache["bitmap"].shape[0] and gray.shape[1] >= cache["bitmap"].shape[1]:
                    _, value, _, point = cv2.minMaxLoc(cv2.matchTemplate(gray, cache["bitmap"], cv2.TM_CCOEFF_NORMED))
                    if value >= .9:
                        words = [Line(label, point[0] + 2, point[1] + 2, tw, th)]
                        left, top = nx1, ny1
            if not words:
                local = ocr.read(local_image, words=True)
                if normalized(label) in normalized(" ".join(word.text for word in local)):
                    words = local
                    left, top = nx1, ny1
    if not words:
        for bx, by, bw, bh in text_bands(crop, height / 1080):
            part = ocr.read(crop[by:by + bh, bx:bx + bw], words=True)
            words.extend(Line(word.text, word.x + bx, word.y + by, word.w, word.h) for word in part)
            if normalized(label) in normalized(" ".join(word.text for word in words)):
                break
    text = " ".join(word.text for word in words)
    length = len(normalized(label).split())
    for i in range(len(words) - length + 1):
        phrase = words[i:i + length]
        if normalized(" ".join(word.text for word in phrase)) != normalized(label):
            continue
        tx, ty = min(p.x for p in phrase) + left, min(p.y for p in phrase) + top
        text_height = max(p.y + p.h for p in phrase) + top - ty
        text_width = max(p.x + p.w for p in phrase) + left - tx
        cache.update(label=[tx, ty, text_width, text_height], center=center)
        if "bitmap" not in cache:
            bitmap = frame[max(0, round(ty - 2)):min(height, round(ty + text_height + 2)),
                           max(0, round(tx - 2)):min(width, round(tx + text_width + 2))]
            gray = cv2.cvtColor(bitmap, cv2.COLOR_BGR2GRAY)
            if gray.std() >= 12:
                cache["bitmap"] = gray
        # shortcut: key geometry is verified on the supplied English UI; validate other layouts before automatic totals.
        characters = max(1, len(normalized(label).replace(" ", "")))
        # OCR height changes with shadows; word width is stable across these frames.
        unit = text_width / characters * 1.3
        radius = unit * 1.8
        cx, cy = tx - unit * 3, ty + text_height / 2
        left, top = max(0, round(cx - radius * 1.3)), max(0, round(cy - radius * 1.3))
        right, bottom = min(width, round(cx + radius * 1.3)), min(height, round(cy + radius * 1.3))
        return True, ring_progress(frame[top:bottom, left:right]), text
    cache.clear()
    return False, None, text


def notification_crops(crop):
    boxes = []
    for x, y, w, h in text_bands(crop, purple=True):
        if w <= crop.shape[1] * .95:
            left, top = max(0, x - max(40, w // 2)), max(0, y - 10)
            right, bottom = min(crop.shape[1], x + w + max(30, w // 3)), min(crop.shape[0], y + 12 + max(60, (h - 24) * 4))
            if not any(overlap([left, top, right - left, bottom - top], other) > .3 for other in boxes):
                boxes.append([left, top, right - left, bottom - top])
    return sorted(boxes, key=lambda b: b[2], reverse=True)[:3]


class ScreenPerception:
    def __init__(self, config, ocr):
        self.config, self.ocr = config, ocr
        self.chests = ChestModel()
        self.notifications = NotificationTracker()
        self.objects = {}
        self.prompts = {}
        self.cycles = {}
        self.serial = 0
        self.previous = None
        self.mode_time = -10
        self.mode = ""
        self.frame_shape = None
        self.xp_zoom = 4 / 3

    def objects_at(self, frame, stamp):
        scale = min(1., 540 / frame.shape[0])
        small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        followed = set()
        if self.previous is not None:
            for key, item in self.objects.items():
                x, y, w, h = map(round, item["box"])
                left, top = max(0, round(x * scale)), max(0, round(y * scale))
                right, bottom = min(gray.shape[1], round((x + w) * scale)), min(gray.shape[0], round((y + h) * scale))
                if right <= left or bottom <= top:
                    continue
                points = cv2.goodFeaturesToTrack(self.previous[top:bottom, left:right], 20, .03, 5)
                if points is None:
                    continue
                points += np.array([left, top], np.float32)
                moved, status, errors = cv2.calcOpticalFlowPyrLK(self.previous, gray, points, None)
                if moved is None:
                    continue
                returned, back_status, _ = cv2.calcOpticalFlowPyrLK(gray, self.previous, moved, None)
                if returned is None:
                    continue
                valid = ((status.ravel() == 1) & (back_status.ravel() == 1)
                         & (np.linalg.norm((returned - points).reshape(-1, 2), axis=1) < 1.5))
                if valid.sum() >= 4:
                    delta = (moved - points)[valid].reshape(-1, 2)
                    shift = np.median(delta, axis=0)
                    if (np.median(np.linalg.norm(delta - shift, axis=1)) < 12 * scale
                            and np.median(errors[valid]) < 30):
                        item["box"] = [x + shift[0] / scale, y + shift[1] / scale, w, h]
                        followed.add(key)
        available = {k for k, v in self.objects.items() if stamp - v["seen"] <= 1.5}
        targets, boxes = [], {}
        for score, box, state in self.chests.detect(frame, self.config.match_threshold):
            compatible = [k for k in available if not (state == "closed" and self.objects[k].get("opened_hits", 0) >= 2)]
            def association(key):
                item = self.objects[key]
                return max(overlap(box, item["box"]), .9 * overlap(box, item.get("detected_box", item["box"])))
            nearest = max(compatible, key=association, default=None)
            uncertain = False
            if nearest is not None and association(nearest) > .18:
                key = nearest
                uncertain = bool(nearest not in followed or overlap(box, self.objects[key]["box"]) < .18)
                available.remove(key)
            else:
                self.serial += 1
                key = self.serial
            opened_hits = self.objects.get(key, {}).get("opened_hits", 0) + 1 if state == "opened" else 0
            previous = self.objects.get(key, {})
            self.objects[key] = {"box": box, "detected_box": box, "seen": stamp, "state": state, "opened_hits": opened_hits,
                                 "score": score, "prompt_at": previous.get("prompt_at", -10)}
            boxes[key] = box
            targets.append(Target(key, score if state == "closed" else 0,
                                  score if state == "opened" else 0, "Unknown", uncertain))
        # Follow an already recognized interaction through short model gaps. Motion
        # never supplies opened-state proof, and propagated targets stay uncertain.
        for key in available & followed:
            item = self.objects[key]
            if item["state"] == "closed" and stamp - item.get("prompt_at", -10) <= .5:
                box = item["box"]
                if not any(overlap(box, detected) > .25 for detected in boxes.values()):
                    boxes[key] = box
                    targets.append(Target(key, item["score"], 0, "Unknown", True))
        self.objects = {k: v for k, v in self.objects.items() if stamp - v["seen"] <= 1.5}
        self.prompts = {k: v for k, v in self.prompts.items() if k in self.objects}
        self.cycles = {k: v for k, v in self.cycles.items() if k in self.objects}
        self.previous = gray
        return targets, boxes

    def observe(self, frame, stamp):
        cfg = self.config
        height, width = frame.shape[:2]
        if self.frame_shape != frame.shape[:2]:
            self.objects.clear()
            self.prompts.clear()
            self.cycles.clear()
            self.previous = None
            self.frame_shape = frame.shape[:2]
        if stamp - self.mode_time >= .5:
            crop = region(frame, cfg.regions["mode"])
            lines = []
            for bx, by, bw, bh in text_bands(crop, height / 1080):
                lines.extend(self.ocr.read(crop[by:by + bh, bx:bx + bw]))
            self.mode = " | ".join(line.text for line in lines)
            self.mode_time = stamp
        blocked = any(normalized(word) in normalized(self.mode) for word in cfg.blocked_labels)
        active = health_hud(region(frame, cfg.regions["hud"]), width) and not blocked
        text = {"mode": self.mode, "model": "Local chest-state recognizer · review pending validation", "runtime": self.chests.provider}
        if not active:
            self.objects.clear()
            self.prompts.clear()
            self.cycles.clear()
            self.previous = None
            self.notifications.update([], stamp)
            return Observation(stamp, False, text=text)
        targets, boxes = self.objects_at(frame, stamp)
        focus = min(boxes, key=lambda k: (boxes[k][0] + boxes[k][2] / 2 - width / 2) ** 2
                    + (boxes[k][1] + boxes[k][3] / 2 - height / 2) ** 2, default=None)
        search, progress, search_text = False, None, ""
        if focus is not None:
            x, y, w, h = boxes[focus]
            if abs(x + w / 2 - width / 2) > width * .2 or abs(y + h / 2 - height / 2) > height * .35:
                focus = None
        if focus is not None:
            search, progress, search_text = search_evidence(frame, boxes[focus], self.ocr,
                cfg.search_label, self.prompts.setdefault(focus, {}))
            if search:
                self.objects[focus]["prompt_at"] = stamp
            cycle = self.cycles.setdefault(focus, {"max": 0, "ended": False})
            if search and progress is not None:
                # A new low-to-high interaction after completion has its own event identity,
                # even if a fast camera turn puts a different chest in the same image box.
                if cycle["ended"] and cycle["max"] >= .8 and progress <= .5:
                    previous = focus
                    self.serial += 1
                    focus = self.serial
                    self.objects[focus] = self.objects.pop(previous)
                    self.prompts[focus] = self.prompts.pop(previous)
                    for target in targets:
                        if target.key == previous:
                            target.key = focus
                    cycle = {"max": 0, "ended": False}
                    self.cycles[focus] = cycle
                cycle["max"] = max(cycle["max"], progress)
                cycle["ended"] = False
        for key, cycle in self.cycles.items():
            if key != focus or not search:
                cycle["ended"] = True
        xp_crop = region(frame, cfg.regions["xp"])
        if height != 1080:
            xp_crop = cv2.resize(xp_crop, None, fx=1080 / height, fy=1080 / height, interpolation=cv2.INTER_CUBIC)
        xp_lines = []
        for x, y, w, h in notification_crops(xp_crop):
            image = xp_crop[y:y + h, x:x + w]
            scales = [self.xp_zoom] + [zoom for zoom in (4 / 3, 1.5, 2.) if zoom != self.xp_zoom]
            for scale in scales:
                enlarged = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                lines = [Line(line.text, x + line.x / scale, y + line.y / scale,
                              line.w / scale, line.h / scale) for line in self.ocr.read(enlarged)]
                xp_lines.extend(lines)
                if chest_xp_lines(xp_crop, lines, cfg.chest_label):
                    self.xp_zoom = scale
                    break
        labels = []
        for line in chest_xp_lines(xp_crop, xp_lines, cfg.chest_label):
            if not any(overlap([line.x, line.y, line.w, line.h], [other.x, other.y, other.w, other.h]) > .3
                       for other in labels):
                labels.append(line)
        xp_tokens = self.notifications.update(labels, stamp)
        text.update(search=search_text, xp=" | ".join(line.text for line in xp_lines),
                    chests=f"{len(targets)} located", progress="—" if progress is None else f"{progress:.2f}")
        return Observation(stamp, True, targets, search, progress, xp_tokens, text, focus)
