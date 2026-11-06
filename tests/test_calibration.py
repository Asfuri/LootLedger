from dataclasses import asdict

import numpy as np
import pytest

from lootledger.calibration import completed_steps, fit_image, save_step
from lootledger.config import Config


def picture():
    return np.random.default_rng(19).integers(0, 255, (540, 960, 3), dtype=np.uint8)


def test_three_guided_selections_save_automatically_without_naming_types(tmp_path):
    frame = picture()
    config = save_step(Config(detector_backend="template"), tmp_path, "closed", frame, [.45, .43, .13, .18])
    assert {t["state"] for t in config.templates} == {"closed", "hud"}
    assert all(t["type"] == "Unknown" for t in config.templates)
    assert config.regions["chest"][2] > .5
    assert completed_steps(config) == {"closed": True, "progress": False, "opened": False}
    config = save_step(config, tmp_path, "progress", frame, [.56, .52, .03, .07])
    assert config.progress_calibrated
    x, y, w, h = config.regions["progress"]
    assert w * 960 == pytest.approx(h * 540)
    assert config.regions["search"][0] < x and config.regions["search"][2] > w
    after = frame.copy()
    after[0, 0] = 0
    config = save_step(config, tmp_path, "opened", after, [.45, .43, .13, .18])
    assert all(completed_steps(config).values())
    assert not config.calibration_errors()
    assert not config.validated()
    assert asdict(Config.read(tmp_path / "config.json")) == asdict(config)
    assert not (tmp_path / "ledger.sqlite").exists()


def test_closed_picture_cannot_also_be_saved_as_opened(tmp_path):
    frame = picture()
    config = save_step(Config(detector_backend="template"), tmp_path, "closed", frame, [.45, .43, .13, .18])
    with pytest.raises(ValueError, match="new picture"):
        save_step(config, tmp_path, "opened", frame, [.45, .43, .13, .18])
    assert "opened" not in {t["state"] for t in Config.read(tmp_path / "config.json").templates}


def test_invalid_box_does_not_overwrite_existing_setup(tmp_path):
    config = Config()
    config.save(tmp_path / "config.json")
    with pytest.raises(ValueError):
        save_step(config, tmp_path, "closed", picture(), [.95, .95, .2, .2])
    assert asdict(Config.read(tmp_path / "config.json")) == asdict(config)


def test_uploaded_screenshot_resizes_to_capture_without_changing_shape():
    assert fit_image(picture(), [1920, 1080]).shape == (1080, 1920, 3)
    with pytest.raises(ValueError, match="different shape"):
        fit_image(picture(), [1280, 1024])


def test_resolution_change_requires_new_closed_example(tmp_path):
    frame = picture()
    config = save_step(Config(detector_backend="template"), tmp_path, "closed", frame, [.45, .43, .13, .18])
    config = save_step(config, tmp_path, "progress", frame, [.56, .52, .03, .07])
    larger = fit_image(frame, [1920, 1080])
    with pytest.raises(ValueError, match="Start with Closed"):
        save_step(config, tmp_path, "progress", larger, [.56, .52, .03, .07])
    changed = save_step(config, tmp_path, "closed", larger, [.45, .43, .13, .18])
    assert changed.frame_size == [1920, 1080]
    assert not changed.progress_calibrated
