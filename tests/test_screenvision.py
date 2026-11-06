import cv2
import numpy as np

from lootledger.config import Config
from lootledger.screenvision import ChestModel, decode_boxes, health_hud, search_evidence, ScreenPerception


def test_health_values_and_background_can_change_without_pausing():
    for background, length in ((15, 210), (70, 90)):
        crop = np.full((65, 350, 3), background, np.uint8)
        crop[32:50, 20:20 + length] = (20, 220, 70)
        assert health_hud(crop, 1920)
    assert not health_hud(np.zeros((65, 350, 3), np.uint8), 1920)
    assert not health_hud(np.full((65, 350, 3), (200, 60, 10), np.uint8), 1920)


def test_low_health_requires_a_health_symbol_beside_the_remaining_bar():
    crop = np.zeros((65, 350, 3), np.uint8)
    crop[32:50, 28:30] = (20, 220, 70)
    assert not health_hud(crop, 1920)
    cv2.line(crop, (8, 39), (20, 39), (255, 255, 255), 3)
    cv2.line(crop, (14, 33), (14, 45), (255, 255, 255), 3)
    assert health_hud(crop, 1920)


def test_ssd_zero_offsets_preserve_anchors_and_positive_offsets_move_centers():
    anchors = np.array([[10, 20, 50, 80], [100, 100, 180, 200]], np.float32)
    np.testing.assert_allclose(decode_boxes(np.zeros((2, 4)), anchors, [10, 10, 5, 5]), anchors)
    shifted = decode_boxes(np.array([[10, 0, 0, 0], [0, 10, 0, 0]]), anchors, [10, 10, 5, 5])
    np.testing.assert_allclose(shifted[0], [50, 20, 90, 80])
    np.testing.assert_allclose(shifted[1], [100, 200, 180, 300])


def test_spectating_blocks_personal_looking_hud_before_chest_inference(monkeypatch):
    import lootledger.screenvision as module

    class Model:
        provider = "test"
        def detect(self, frame, threshold):
            raise AssertionError("Spectating must not reach chest recognition")

    class OCR:
        def read(self, crop):
            from lootledger.vision import Line
            return [Line("SPECTATING", 0, 0, 100, 20)]

    monkeypatch.setattr(module, "ChestModel", Model)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[1000:1020, 60:280] = (20, 220, 70)
    cv2.putText(frame, "SPECTATING", (750, 140), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    obs = ScreenPerception(Config(), OCR()).observe(frame, 0)
    assert not obs.active and not obs.targets and not obs.xp_tokens


def test_original_profiles_migrate_to_model_without_requiring_reference_images(tmp_path):
    import json
    original = {"frame_size": [2560, 1440], "match_threshold": .82, "templates": []}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(original))
    config = Config.read(path)
    assert config.detector_backend == "model"
    assert config.match_threshold == .55
    assert json.loads(path.read_text()) == original


def test_search_circle_follows_the_label_to_a_different_screen_position(monkeypatch):
    from lootledger.vision import Line
    # Isolate ring geometry; glyph localization has its own rendered-text test.
    monkeypatch.setattr("lootledger.screenvision.text_bands", lambda image, scale: [[0, 0, image.shape[1], image.shape[0]]])
    values = []
    for shift, angle, text_height in ((0, 65, 9), (180, 330, 19)):
        frame = np.full((1080, 1920, 3), 35, np.uint8)
        cx, cy = 1100 + shift, 620 + shift // 2
        cv2.rectangle(frame, (cx - 28, cy - 28), (cx + 125, cy + 28), (25, 25, 25), -1)
        cv2.circle(frame, (cx, cy), 20, (110, 110, 110), 2)
        cv2.ellipse(frame, (cx, cy), (20, 20), 0, 0, angle, (255, 255, 255), 3)
        box = [980 + shift, 500 + shift // 2, 180, 250]
        left, top = round(box[0] + box[2] * .15), round(box[1] - box[3] * .1)

        class OCR:
            def read(self, crop, words=False):
                assert words
                return [Line("SEARCH", cx + 33 - left, cy - text_height / 2 - top, 51, text_height)]

        found, progress, _ = search_evidence(frame, box, OCR(), "SEARCH")
        assert found and progress is not None
        values.append(progress)
    assert values[0] < .5 and values[1] > .85


def test_model_boxes_map_back_to_different_resolutions_and_positions():
    for width, height, x in ((1920, 1080, 400), (2560, 1440, 1500)):
        model = ChestModel.__new__(ChestModel)
        model.size, model.card = 512, {"box_coder_weights": [10, 10, 5, 5]}
        scale = 512 / width
        top = (512 - round(height * scale)) // 2
        expected = np.array([x, 300, 180, 240], np.float64)
        model.anchors = np.array([[x * scale, 300 * scale + top,
                                   (x + 180) * scale, 540 * scale + top]], np.float32)

        class Net:
            def run(self, names, inputs):
                assert inputs["image"].shape == (1, 3, 512, 512)
                return np.zeros((1, 1, 4), np.float32), np.array([[[0, 9, 0]]], np.float32)

        model.session = Net()
        detections = model.detect(np.zeros((height, width, 3), np.uint8), .55)
        assert len(detections) == 1 and detections[0][2] == "closed"
        np.testing.assert_allclose(detections[0][1], expected, atol=.01)


def test_bundled_model_loads_and_rejects_a_blank_scene():
    assert ChestModel().detect(np.zeros((540, 960, 3), np.uint8), .55) == []


def test_text_bands_keep_rendered_labels_and_reject_a_solid_purple_jewel():
    from lootledger.screenvision import text_bands, notification_crops
    from lootledger.vision import WindowsOCR
    frame = np.zeros((180, 500, 3), np.uint8)
    cv2.putText(frame, "SEARCH", (70, 75), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
    bands = text_bands(frame)
    assert bands
    ocr = WindowsOCR("en-US")
    try:
        assert any("SEARCH" == line.text.upper() for x,y,w,h in bands
                   for line in ocr.read(frame[y:y+h,x:x+w]))
    finally:
        ocr.close()
    frame[:] = 0
    cv2.fillConvexPoly(frame, np.array([[60, 35], [120, 45], [105, 70], [50, 65]]), (220, 70, 190))
    assert notification_crops(frame) == []


def test_short_model_gap_uses_verified_motion_only_as_uncertain_evidence(monkeypatch):
    import lootledger.screenvision as module

    class Model:
        provider = "fixture"
        def __init__(self):
            self.calls = 0
        def detect(self, frame, threshold):
            self.calls += 1
            return [(.99, [500, 350, 240, 260], "closed")] if self.calls == 1 else []

    monkeypatch.setattr(module, "ChestModel", Model)
    vision = ScreenPerception(Config(), None)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[350:610, 500:740] = np.random.default_rng(7).integers(0, 256, (260, 240, 3), dtype=np.uint8)
    targets, _ = vision.objects_at(frame, 0)
    key = targets[0].key
    vision.objects[key]["prompt_at"] = 0
    moved = cv2.warpAffine(frame, np.float32([[1, 0, 10], [0, 1, 8]]), (1920, 1080))
    targets, _ = vision.objects_at(moved, .1)
    assert len(targets) == 1 and targets[0].key == key
    assert targets[0].uncertain and targets[0].opened == 0
    vision.objects[key]["prompt_at"] = 1.6
    assert vision.objects_at(moved, 1.6)[0] == []


def test_camera_cut_does_not_coast_a_previous_chest(monkeypatch):
    import lootledger.screenvision as module

    class Model:
        provider = "fixture"
        def __init__(self):
            self.calls = 0
        def detect(self, frame, threshold):
            self.calls += 1
            return [(.99, [500, 350, 240, 260], "closed")] if self.calls == 1 else []

    monkeypatch.setattr(module, "ChestModel", Model)
    vision = ScreenPerception(Config(), None)
    rng = np.random.default_rng(9)
    frame = rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8)
    targets, _ = vision.objects_at(frame, 0)
    vision.objects[targets[0].key]["prompt_at"] = 0
    assert vision.objects_at(np.zeros_like(frame), .1)[0] == []


def test_fresh_opened_detection_can_rejoin_recent_search_only_as_uncertain(monkeypatch):
    import lootledger.screenvision as module
    class Model:
        provider = "fixture"
        def __init__(self):
            self.calls = 0
        def detect(self, frame, threshold):
            self.calls += 1
            return [(.99, [500, 350, 240, 260], "closed" if self.calls == 1 else "opened")]
    monkeypatch.setattr(module, "ChestModel", Model)
    vision = ScreenPerception(Config(), None)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    targets, _ = vision.objects_at(frame, 0)
    key = targets[0].key
    vision.objects[key]["prompt_at"] = 0
    targets, _ = vision.objects_at(frame, 1.)
    assert len(targets) == 1 and targets[0].key == key and targets[0].uncertain
    assert targets[0].opened == .99
