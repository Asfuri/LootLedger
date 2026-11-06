from lootledger.config import Config
from lootledger.detector import Detector
from lootledger.vision import Line, Perception
from copy import deepcopy

from .synthetic import make_clip


class FixtureOCR:
    def __init__(self):
        self.frame_index = 0
        self.call = 0

    def read(self, crop):
        part = self.call % 3
        self.call += 1
        phase = self.frame_index % 16
        if part == 0 and self.frame_index < 32 and 7 <= phase <= 12:
            return [Line("+1350 XP", 47, 15, 150, 22), Line("CHEST", 78, 47, 85, 18)]
        if part == 1 and self.frame_index < 32 and 1 <= phase <= 6:
            return [Line("SEARCH", 10, 15, 100, 22)]
        return []


def test_images_flow_regions_progress_and_temporal_fusion(tmp_path):
    _, config_path, frames = make_clip(tmp_path)
    config = Config.read(config_path)
    ocr = FixtureOCR()
    perception, detector = Perception(config, ocr), Detector(config)
    events = []
    for index, frame in enumerate(frames):
        ocr.frame_index = index
        observation = perception.observe(frame, index / 10)
        events.extend(detector.feed(observation))
    assert len(events) == 2
    assert all(e.status == "confirmed" for e in events)
    assert events[1].time - events[0].time < 2


def test_new_closed_chest_at_same_position_does_not_need_blank_frames(tmp_path):
    _, path, frames = make_clip(tmp_path)
    config = Config.read(path)
    ocr = FixtureOCR()
    perception, detector = Perception(config, ocr), Detector(config)
    events = []
    sequence = list(range(1, 11)) + list(range(17, 27))
    for step, frame_index in enumerate(sequence):
        ocr.frame_index = frame_index
        observation = perception.observe(frames[frame_index], step / 10)
        events.extend(detector.feed(observation))
    assert len(events) == 2
    assert events[0].target != events[1].target


def test_active_hud_does_not_override_spectating_text(tmp_path):
    _, path, frames = make_clip(tmp_path)
    config = Config.read(path)

    class SpectatorOCR(FixtureOCR):
        def read(self, crop):
            if self.call % 3 == 2:
                self.call += 1
                return [Line("SPECTATING", 0, 0, 120, 20)]
            return super().read(crop)

    observation = Perception(config, SpectatorOCR()).observe(frames[2], .2)
    assert not observation.active
    assert observation.targets == []


def test_ambiguous_appearance_type_stays_unknown(tmp_path):
    _, path, frames = make_clip(tmp_path)
    config = Config.read(path)
    first = config.templates[0]
    first.update(type="User type A", source="synthetic fixture, not a Fortnite category")
    second = deepcopy(first)
    second["type"] = "User type B"
    config.templates.append(second)
    observation = Perception(config, FixtureOCR()).observe(frames[2], .2)
    assert len(observation.targets) == 1
    assert observation.targets[0].chest_type == "Unknown"
