"""UI preferences (ui-settings.json) and the number, date and duration formats they control."""
from dataclasses import asdict, dataclass, field, fields
import json
from pathlib import Path
import re

WIDGETS = {  # widget id -> default width in dashboard columns
    "live": 2,
    **{f"stat:{key}": 1 for key in ("all", "today", "week", "month", "last", "avg", "best",
                                     "per_hour", "playtime", "matches", "session")},
    "trend": 2, "types": 2, "modes": 1, "heat": 2, "records": 1, "teammates": 1, "broken": 1,
}
DEFAULT_LAYOUT = ("live", "stat:all", "stat:today", "stat:week", "stat:last", "stat:avg", "stat:per_hour",
                  "trend", "types", "records", "teammates")
RANGES = (7, 30, 90, 0)  # days; 0 means all time
CHOICES = {
    "theme": ("light", "dark", "system"), "corners": ("sharp", "default", "round"),
    "density": ("compact", "comfortable"), "font_scale": ("S", "M", "L", "XL"),
    "chart_style": ("bar", "line", "area"), "background": ("solid", "tonal"),
    "date_format": ("dmy", "mdy", "iso"), "separators": (",", ".", " ", ""), "playtime": ("hm", "decimal"),
}
HEX = re.compile(r"#[0-9a-fA-F]{6}")


def default_layout():
    return [{"id": key, "span": WIDGETS[key]} for key in DEFAULT_LAYOUT]


def normalize_layout(items):
    """Keep known, unique widget ids in order; a missing or invalid span falls back to the widget's default."""
    result, seen = [], set()
    for item in items if isinstance(items, list) else []:
        key = item.get("id") if isinstance(item, dict) else item
        if not isinstance(key, str) or key not in WIDGETS or key in seen:
            continue
        span = item.get("span") if isinstance(item, dict) else None
        result.append({"id": key, "span": span if span in (1, 2) else WIDGETS[key]})
        seen.add(key)
    return result


@dataclass
class Prefs:
    theme: str = "system"
    seed: str = "#e8b04f"
    contrast: bool = False
    corners: str = "default"
    density: str = "comfortable"
    font_scale: str = "M"
    chart_style: str = "bar"
    animations: bool = True
    background: str = "solid"
    time_24h: bool = True
    date_format: str = "dmy"
    separators: str = ","
    playtime: str = "hm"
    default_range: int = 30
    layout: list = field(default_factory=default_layout)

    @classmethod
    def from_dict(cls, data):
        """Load known keys only. Unknown keys and invalid values fall back to defaults, so old and new files both load."""
        base = cls()
        values = {}
        for item in fields(cls):
            if item.name == "layout" or item.name not in data:
                continue
            value = data[item.name]
            if type(value) is not type(getattr(base, item.name)):
                continue
            if item.name in CHOICES and value not in CHOICES[item.name]:
                continue
            if item.name == "seed" and not HEX.fullmatch(value):
                continue
            if item.name == "default_range" and value not in RANGES:
                continue
            values[item.name] = value
        if "layout" in data:
            values["layout"] = normalize_layout(data["layout"])
        return cls(**values)

    @classmethod
    def read(cls, path):
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if not isinstance(data, dict):
                raise ValueError("settings file is not an object")
            return cls.from_dict(data)
        except (OSError, ValueError):
            return cls()  # unreadable preferences must never stop the app; they are not ledger data

    def to_dict(self):
        return {"version": 1, **asdict(self)}

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        temp.replace(path)


def number(value, prefs, decimals=0):
    """1,234 / 1.234 / 1 234 / 1234, with the decimal mark matching the separator style."""
    text = f"{value:,.{decimals}f}"
    decimal = "," if prefs.separators == "." else "."
    return text.replace(",", "\0").replace(".", decimal).replace("\0", prefs.separators)


def short_date(day, prefs):
    return {"dmy": day.strftime("%d/%m"), "mdy": day.strftime("%m/%d"), "iso": day.strftime("%m-%d")}[prefs.date_format]


def full_date(day, prefs):
    return {"dmy": day.strftime("%d/%m/%Y"), "mdy": day.strftime("%m/%d/%Y"),
            "iso": day.strftime("%Y-%m-%d")}[prefs.date_format]


def clock_time(moment, prefs):
    return moment.strftime("%H:%M") if prefs.time_24h else moment.strftime("%I:%M %p").lstrip("0")


def when(moment, prefs):
    return f"{full_date(moment.date(), prefs)} {clock_time(moment, prefs)}"


def duration(seconds, prefs):
    """Playtime as '12h 40m' or as decimal hours, depending on the playtime setting."""
    seconds = int(seconds or 0)
    if prefs.playtime == "decimal":
        return f"{number(seconds / 3600, prefs, 1)} h"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def elapsed(seconds):
    """Clock style for a match timer: 12:34 or 1:02:03."""
    seconds = int(seconds or 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
