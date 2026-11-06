"""Runs the real replay reader on this PC's Fortnite replays (skipped elsewhere).

The two reference clips were labelled frame by frame before replay reading existed
(validation/reference-labels.json, validation/new-clip-labels.json). Their matches
were identified from upload times and the players-left count in each clip title.
"""
import json
from pathlib import Path

import pytest

from lootledger import replay_reader

DEMOS = replay_reader.default_folder()
VALIDATION = Path(__file__).resolve().parent.parent / "validation"
CLIPS = [  # replay file, clip start in replay seconds, labels file, clip length
    ("UnsavedReplay-2026.11.05-19.53.09.replay", 217.43, "reference-labels.json", 20.3),
    ("UnsavedReplay-2026.11.06-01.58.17.replay", 211.72, "new-clip-labels.json", 10.1),
]


def helper_or_skip():
    try:
        return replay_reader.helper_path()
    except FileNotFoundError:
        pytest.skip("replay reader not built (run build.ps1)")


@pytest.mark.parametrize("name,start,labels,length", CLIPS)
def test_labelled_clip_openings_match_replay(name, start, labels, length):
    helper = helper_or_skip()
    path = DEMOS / name
    if not path.is_file():
        pytest.skip(f"{name} is not on this PC (Fortnite deletes old replays)")
    result = replay_reader.analyze([path], helper=helper)[0]
    assert result["ok"], result.get("error")
    mine = [e["t"] - start for e in result["events"] if e["by"] == "me" and -0.5 <= e["t"] - start <= length + 0.5]
    expected = json.loads((VALIDATION / labels).read_text(encoding="utf-8"))["openings"]
    assert len(mine) == len(expected)  # no misses, no extra or duplicate events in the clip
    for found, label in zip(sorted(mine), expected):
        assert abs(found - label) < 0.25


def test_garbage_file_is_reported_not_crashing(tmp_path):
    helper = helper_or_skip()
    path = tmp_path / "broken.replay"
    path.write_bytes(b"\x01" * 100)
    result = replay_reader.analyze([path], helper=helper)[0]
    assert result["ok"] is False and result["events"] == []
