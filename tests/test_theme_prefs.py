from datetime import date, datetime
import json
import re

import pytest

from lootledger import theme
from lootledger.prefs import (WIDGETS, DEFAULT_LAYOUT, Prefs, clock_time, duration, elapsed, normalize_layout,
                              number, short_date)

HEX = re.compile(r"#[0-9a-f]{6}")


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("high", [False, True])
def test_text_and_outline_contrast_meets_wcag_aa(dark, high):
    tokens = theme.build(Prefs(contrast=high), dark, motion=False)
    c = tokens.c
    text_pairs = [("on_surface", "surface"), ("on_surface", "surface_container_high"),
                  ("on_surface_variant", "surface_container_high"), ("on_surface_variant", "surface_container_low"),
                  ("primary", "surface"), ("primary", "surface_container_high"), ("on_primary", "primary"),
                  ("on_secondary_container", "secondary_container"), ("on_primary_container", "primary_container"),
                  ("error", "surface"), ("inverse_on_surface", "inverse_surface")]
    for foreground, background in text_pairs:
        assert theme.contrast(c[foreground], c[background]) >= 4.5, (foreground, background)
    assert theme.contrast(c["outline"], c["surface"]) >= 3
    for colour in tokens.chart:
        assert theme.contrast(colour, c["surface_container_high"]) >= 3


@pytest.mark.parametrize("seed", list(theme.SEEDS.values()) + ["#808080", "#000000", "#ffffff"])
def test_every_role_is_a_valid_hex_colour_for_any_seed(seed):
    tokens = theme.build(Prefs(seed=seed), False, motion=True)
    assert all(HEX.fullmatch(value) for value in tokens.c.values())
    assert all(HEX.fullmatch(value) for value in tokens.chart)


def test_explicit_theme_choice_overrides_the_system():
    assert theme.is_dark("dark") is True
    assert theme.is_dark("light") is False


def test_presets_change_the_accent_and_keep_the_surfaces_neutral():
    amber = theme.build(Prefs(seed="#e8b04f"), False, motion=True).c
    violet = theme.build(Prefs(seed="#a98aee"), False, motion=True).c
    assert amber["primary"] != violet["primary"]
    assert theme.contrast(amber["surface"], violet["surface"]) < 1.05  # only a faint seed tint on the neutrals


def test_text_size_density_and_corners_scale_the_tokens():
    base = theme.build(Prefs(), False, motion=True)
    large = theme.build(Prefs(font_scale="XL"), False, motion=True)
    assert large.px["body"] > base.px["body"]
    compact = theme.build(Prefs(density="compact"), False, motion=True)
    assert compact.sp["m"] < base.sp["m"]
    sharp = theme.build(Prefs(corners="sharp"), False, motion=True)
    assert sharp.r["card"] < base.r["card"]


def test_stylesheet_uses_the_tokens_and_the_icon_font():
    tokens = theme.build(Prefs(), True, motion=True)
    sheet = theme.stylesheet(tokens)
    assert tokens.c["primary"] in sheet and tokens.c["surface"] in sheet
    assert theme.ICON_FONT in sheet
    tonal = theme.stylesheet(theme.build(Prefs(background="tonal"), False, motion=True))
    assert "qlineargradient" in tonal


def test_icon_font_and_its_licence_are_bundled():
    assert theme.FONT_FILE.is_file()
    assert theme.FONT_FILE.read_bytes()[:4] == b"\x00\x01\x00\x00"  # TrueType
    licence = theme.FONT_FILE.parent / "LICENSE-MaterialSymbols.txt"
    assert "Apache License" in licence.read_text(encoding="utf-8")


def test_unknown_preference_keys_and_bad_values_fall_back_to_defaults(tmp_path):
    path = tmp_path / "ui-settings.json"
    path.write_text(json.dumps({"version": 1, "theme": "neon", "seed": "red", "density": "compact",
                                "default_range": 13, "animations": "yes", "future_setting": 5}), encoding="utf-8")
    prefs = Prefs.read(path)
    assert prefs.theme == "system" and prefs.seed == "#e8b04f" and prefs.default_range == 30
    assert prefs.animations is True and prefs.density == "compact"


def test_corrupt_settings_file_is_ignored(tmp_path):
    path = tmp_path / "ui-settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert Prefs.read(path) == Prefs()
    path.write_text("[1, 2]", encoding="utf-8")
    assert Prefs.read(path) == Prefs()


def test_settings_round_trip(tmp_path):
    path = tmp_path / "nested" / "ui-settings.json"
    Prefs(theme="dark", contrast=True, default_range=90, separators=".").save(path)
    loaded = Prefs.read(path)
    assert (loaded.theme, loaded.contrast, loaded.default_range, loaded.separators) == ("dark", True, 90, ".")
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_layout_is_normalized_and_defaults_are_valid():
    assert normalize_layout([{"id": "trend", "span": 1}, {"id": "trend"}, {"id": "nope"},
                             {"id": "live", "span": 9}, "heat", None, {"id": ["bad"]}]) == [
        {"id": "trend", "span": 1}, {"id": "live", "span": 2}, {"id": "heat", "span": 2}]
    assert all(key in WIDGETS for key in DEFAULT_LAYOUT)
    assert len(Prefs().layout) == len(DEFAULT_LAYOUT)
    assert Prefs.from_dict({"layout": []}).layout == []  # an empty dashboard is a valid choice


def test_number_and_date_formats():
    assert number(1234.5, Prefs(separators=","), 1) == "1,234.5"
    assert number(1234.5, Prefs(separators="."), 1) == "1.234,5"
    assert number(1234, Prefs(separators=" ")) == "1 234"
    assert number(1234, Prefs(separators="")) == "1234"
    evening = datetime(2026, 11, 6, 21, 5)
    assert short_date(date(2026, 11, 6), Prefs(date_format="dmy")) == "06/11"
    assert short_date(date(2026, 11, 6), Prefs(date_format="mdy")) == "11/06"
    assert clock_time(evening, Prefs(time_24h=False)) == "9:05 PM"
    assert clock_time(evening, Prefs(time_24h=True)) == "21:05"


def test_duration_and_elapsed_formats():
    seconds = 12 * 3600 + 40 * 60
    assert duration(seconds, Prefs(playtime="hm")) == "12h 40m"
    assert duration(seconds, Prefs(playtime="decimal")) == "12.7 h"
    assert duration(45 * 60, Prefs()) == "45m"
    assert elapsed(754) == "12:34"
    assert elapsed(3723) == "1:02:03"
    assert elapsed(None) == "0:00"
