from dataclasses import asdict
import json

from lootledger.analyze import REQUIRED_SCENARIOS, compare
from lootledger.config import Config


def test_metrics_are_one_to_one_and_count_duplicates_and_misses():
    events = [{"time": t, "status": "confirmed"} for t in (1, 1.1, 9)]
    events.append({"time": 4, "status": "review"})
    result = compare(events, {"openings": [1, 4], "real_footage": True})
    assert (result["matched"], result["missed"], result["false"], result["duplicates"]) == (1, 1, 1, 1)
    assert not result["release_gate"]


def test_synthetic_data_cannot_pass_real_footage_gate():
    timestamps = list(range(0, 40, 4))
    events = [{"time": t, "status": "confirmed"} for t in timestamps]
    labels = {"openings": timestamps, "real_footage": False, "scenarios": sorted(REQUIRED_SCENARIOS)}
    assert not compare(events, labels)["release_gate"]
    labels["real_footage"] = True
    assert compare(events, labels)["release_gate"]


def test_timestamp_matching_does_not_greedily_steal_a_later_opening():
    events = [{"time": t, "status": "confirmed"} for t in (1.4, 2)]
    result = compare(events, {"openings": [1, 1.6]}, tolerance=.7)
    assert result["matched"] == 2
    assert not result["release_gate"]


def test_profile_changes_invalidate_validation_and_saved_config_roundtrips(tmp_path):
    config = Config()
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"config_sha256": config.fingerprint(), "real_footage": True, "release_gate": True}))
    config.validation_report = str(report)
    assert config.validated()
    config.regions["xp"][0] = .51
    assert not config.validated()
    path = tmp_path / "config.json"
    config.save(path)
    assert asdict(Config.read(path)) == asdict(config)


def test_detector_revision_invalidates_previous_footage_approval(tmp_path, monkeypatch):
    import lootledger.config as module
    config = Config()
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"config_sha256": config.fingerprint(), "real_footage": True, "release_gate": True}))
    config.validation_report = str(report)
    assert config.validated()
    monkeypatch.setattr(module, "DETECTOR_REVISION", module.DETECTOR_REVISION + 1)
    assert not config.validated()
