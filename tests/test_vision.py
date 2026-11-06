import sys

import cv2
import numpy as np
import pytest

from lootledger.vision import ChestLabel, Line, NotificationTracker, WindowsOCR, chest_xp_lines, ring_progress


def notification(amount="1,350", label="CHEST", purple=True):
    frame = np.zeros((120, 300, 3), np.uint8)
    frame[10:35, 20:200] = (220, 70, 190) if purple else (255, 255, 255)
    lines = [Line("+" + amount + " XP", 20, 10, 180, 25), Line(label, 65, 43, 80, 18)]
    return frame, lines


@pytest.mark.parametrize("amount", ["600", "1200", "1,350", "2.450"])
def test_exact_structured_label_independent_of_xp_amount(amount):
    frame, lines = notification(amount)
    assert len(chest_xp_lines(frame, lines, "CHEST")) == 1


@pytest.mark.parametrize("label", ["OPEN TREASURE CHESTS", "CHEST BONUS", "AMMO BOX", "CHESTS",
                                   "CHEST BONUS X2", "CHEST X0", "CHEST X100", "CHEST X2 BONUS"])
def test_quest_and_unrelated_text_do_not_match(label):
    frame, lines = notification(label=label)
    assert chest_xp_lines(frame, lines, "CHEST") == []


@pytest.mark.parametrize("label", ["CHEST X2", "CHEST ×2", "CHESTX2", "CHEST X2,"])
def test_exact_chest_award_multiplier_preserves_structure(label):
    frame, lines = notification(amount="1,122", label=label)
    assert chest_xp_lines(frame, lines, "CHEST")[0].count == 2
    assert chest_xp_lines(frame, [lines[1]], "CHEST") == []
    frame, lines = notification(label=label, purple=False)
    assert chest_xp_lines(frame, lines, "CHEST") == []


def test_rolling_xp_is_one_award_until_a_stable_label_increment():
    tracker = NotificationTracker()
    tokens = []
    for index, (amount, label) in enumerate((("600", "CHEST"), ("600", "CHEST"),
                                            ("600", "CHEST X2"), ("900", "CHEST X2"),
                                            ("1,122", "CHEST X2"), ("1,200", "CHEST X2"),
                                            ("1,200", "CHEST"), ("1,200", "CHEST X2"))):
        crop, lines = notification(amount=amount, label=label)
        tokens.append(tracker.update(chest_xp_lines(crop, lines, "CHEST"), index / 10))
    assert tokens[0] == []
    assert len(tokens[1]) == 1
    assert tokens[2] == tokens[1]
    assert len(tokens[3]) == 2 and tokens[3][0] == tokens[1][0]
    assert all(value == tokens[3] for value in tokens[4:])


def test_multiplier_requires_consecutive_readings_and_no_downgrade_recount():
    tracker = NotificationTracker()
    one = ChestLabel("CHEST", 20, 40, 80, 18)
    two = ChestLabel("CHEST X2", 20, 40, 80, 18, 2)
    tracker.update([one], 0)
    first = tracker.update([one], .1)
    assert tracker.update([two], .2) == first
    assert tracker.update([], .3) == []
    assert tracker.update([two], .4) == first
    both = tracker.update([two], .5)
    assert len(both) == 2
    assert tracker.update([one], .6) == both
    assert tracker.update([two], .7) == both


def test_structure_requires_purple_xp_above_label_and_keeps_overlap_rows_separate():
    frame, lines = notification(purple=False)
    assert chest_xp_lines(frame, lines, "CHEST") == []
    frame, lines = notification()
    assert chest_xp_lines(frame, [lines[1]], "CHEST") == []
    assert chest_xp_lines(frame, [Line("+ . XP", 20, 10, 180, 25), lines[1]], "CHEST") == []
    lines += [Line("+200 XP", 20, 77, 180, 15), Line("ELIMINATION", 30, 98, 100, 15)]
    assert len(chest_xp_lines(frame, lines, "CHEST")) == 1


def test_notification_persistence_disappearance_and_overlapping_labels():
    tracker = NotificationTracker()
    a = Line("CHEST", 20, 40, 80, 18)
    b = Line("CHEST", 20, 90, 80, 18)
    assert tracker.update([a], 0) == []
    first = tracker.update([a], .1)[0]
    assert tracker.update([a], .2) == [first]
    assert tracker.update([a, b], .3) == [first]
    both = tracker.update([a, b], .4)
    assert len(both) == 2 and both[0] == first and both[1] != first
    tracker.update([], 1.2)
    tracker.update([a], 1.3)
    assert tracker.update([a], 1.4)[0] != first


def test_ring_progress_increases_on_synthetic_arc():
    values = []
    for angle in (40, 160, 320):
        crop = np.zeros((100, 100, 3), np.uint8)
        cv2.ellipse(crop, (50, 50), (38, 38), 0, 0, angle, (255, 255, 255), 5)
        values.append(ring_progress(crop))
    assert .05 < values[0] < values[1] < values[2] < 1


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows OCR")
def test_windows_ocr_reads_generated_text():
    frame = np.zeros((100, 400, 3), np.uint8)
    cv2.putText(frame, "CHEST", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
    ocr = WindowsOCR("en-US")
    try:
        assert any(line.text.upper() == "CHEST" for line in ocr.read(frame))
    finally:
        ocr.close()


def test_model_perception_bounds_high_resolution_pixel_work():
    from lootledger.vision import Perception
    seen = []
    class Model:
        def observe(self, frame, stamp):
            seen.append((frame.shape[:2], stamp))
            return "observation"
    perception = Perception.__new__(Perception)
    perception.model = Model()
    assert perception.observe(np.zeros((1440, 2560, 3), np.uint8), 1.25) == "observation"
    assert seen == [((1080, 1920), 1.25)]


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows OCR")
def test_windows_ocr_works_in_capture_thread():
    from concurrent.futures import ThreadPoolExecutor
    def recognize():
        frame = np.zeros((100, 400, 3), np.uint8)
        cv2.putText(frame, "CHEST", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        ocr = WindowsOCR("en-US")
        try:
            return [line.text.upper() for line in ocr.read(frame)]
        finally:
            ocr.close()
    with ThreadPoolExecutor(1) as pool:
        assert "CHEST" in pool.submit(recognize).result(timeout=30)
