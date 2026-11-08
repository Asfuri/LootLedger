//! UI preferences (ui-settings.json), read and written exactly like lootledger/prefs.py, and the number,
//! date and duration formats they control.

use chrono::{DateTime, Local, NaiveDate};
use serde_json::{Map, Value, json};
use std::path::Path;

/// Widget id and default width in dashboard columns.
pub const WIDGETS: &[(&str, i32)] = &[
    ("live", 2),
    ("stat:all", 1),
    ("stat:today", 1),
    ("stat:week", 1),
    ("stat:month", 1),
    ("stat:last", 1),
    ("stat:avg", 1),
    ("stat:best", 1),
    ("stat:per_hour", 1),
    ("stat:playtime", 1),
    ("stat:matches", 1),
    ("stat:session", 1),
    ("trend", 2),
    ("types", 2),
    ("modes", 1),
    ("heat", 2),
    ("records", 1),
    ("teammates", 1),
    ("broken", 1),
    ("health", 2),
    ("sessions", 1),
    ("goals", 1),
    ("trophies", 2),
    ("compare", 2),
];
pub const DEFAULT_LAYOUT: &[&str] = &[
    "live",
    "stat:all",
    "stat:today",
    "stat:week",
    "stat:last",
    "stat:avg",
    "stat:per_hour",
    "trend",
    "types",
    "goals",
    "sessions",
    "records",
    "teammates",
];
pub const RANGES: [i64; 4] = [7, 30, 90, 0];

pub fn default_span(id: &str) -> Option<i32> {
    WIDGETS.iter().find(|(k, _)| *k == id).map(|(_, s)| *s)
}

#[derive(Debug, Clone, PartialEq)]
pub struct Item {
    pub id: String,
    pub span: i32,
}

pub fn default_layout() -> Vec<Item> {
    DEFAULT_LAYOUT
        .iter()
        .map(|id| Item {
            id: (*id).into(),
            span: default_span(id).unwrap_or(1),
        })
        .collect()
}

/// Known, unique widget ids in order; a missing or invalid span falls back to the widget's default.
pub fn normalize_layout(items: &Value) -> Vec<Item> {
    let mut out: Vec<Item> = Vec::new();
    for item in items.as_array().into_iter().flatten() {
        let id = item.get("id").and_then(Value::as_str).or(item.as_str());
        let Some(id) = id else { continue };
        let Some(default) = default_span(id) else {
            continue;
        };
        if out.iter().any(|i| i.id == id) {
            continue;
        }
        let span = item
            .get("span")
            .and_then(Value::as_i64)
            .filter(|s| *s == 1 || *s == 2)
            .map_or(default, |s| s as i32);
        out.push(Item {
            id: id.into(),
            span,
        });
    }
    out
}

macro_rules! prefs {
    ($($name:ident: $ty:ty = $default:expr),* $(,)?) => {
        #[derive(Debug, Clone, PartialEq)]
        pub struct Prefs { $(pub $name: $ty,)* pub layout: Vec<Item> }
        impl Default for Prefs {
            fn default() -> Self { Prefs { $($name: $default,)* layout: default_layout() } }
        }
        impl Prefs {
            fn load_fields(&mut self, data: &Map<String, Value>) {
                $(if let Some(v) = data.get(stringify!($name)) { Load::load(&mut self.$name, stringify!($name), v); })*
            }
            fn fields(&self) -> Map<String, Value> {
                let mut m = Map::new();
                $(m.insert(stringify!($name).into(), json!(self.$name));)*
                m
            }
        }
    };
}

prefs! {
    theme: String = "system".into(),
    seed: String = "#e8b04f".into(),
    contrast: bool = false,
    corners: String = "default".into(),
    density: String = "comfortable".into(),
    font_scale: String = "M".into(),
    chart_style: String = "bar".into(),
    motion: String = "full".into(),
    background: String = "solid".into(),
    time_24h: bool = true,
    date_format: String = "dmy".into(),
    separators: String = ",".into(),
    playtime: String = "hm".into(),
    default_range: i64 = 30,
    live_tracking: bool = true,
    live_seconds: i64 = 2,
    overlay: bool = false,
    overlay_opacity: i64 = 90,
    overlay_size: String = "M".into(),
    overlay_corner: String = "free".into(),
    overlay_click_through: bool = false,
    overlay_teammates: bool = true,
    overlay_geometry: Vec<i64> = Vec::new(),
    hotkey_overlay: String = "Ctrl+Alt+F10".into(),
    sound: bool = false,
    volume: i64 = 50,
    window_geometry: Vec<i64> = Vec::new(),
    window_maximized: bool = false,
    goal_daily: i64 = 0,
    goal_weekly: i64 = 0,
    celebrate: bool = true,
    celebrated: Vec<String> = Vec::new(),
    trophies: Vec<String> = Vec::new(),
    colorblind: bool = false,
    seen_version: String = String::new(),
    show_page_title: bool = false,
}

/// Allowed values of the choice fields.
pub fn choices(name: &str) -> Option<&'static [&'static str]> {
    Some(match name {
        "theme" => &["light", "dark", "system"],
        "corners" => &["sharp", "default", "round"],
        "density" => &["compact", "comfortable"],
        "font_scale" => &["S", "M", "L", "XL"],
        "chart_style" => &["bar", "line", "smooth", "area"],
        "background" => &["solid", "tonal"],
        "date_format" => &["dmy", "mdy", "iso"],
        "separators" => &[",", ".", " ", ""],
        "playtime" => &["hm", "decimal"],
        "motion" => &["full", "reduced", "off"],
        "overlay_size" => &["S", "M", "L"],
        "overlay_corner" => &[
            "free",
            "top_left",
            "top_right",
            "bottom_left",
            "bottom_right",
        ],
        _ => return None,
    })
}

fn int_range(name: &str) -> Option<(i64, i64)> {
    Some(match name {
        "live_seconds" => (1, 10),
        "overlay_opacity" => (30, 100),
        "volume" => (0, 100),
        "goal_daily" => (0, 10000),
        "goal_weekly" => (0, 100000),
        _ => return None,
    })
}

pub fn valid_hex(text: &str) -> bool {
    text.len() == 7 && text.starts_with('#') && text[1..].chars().all(|c| c.is_ascii_hexdigit())
}

/// Each field type knows how to take a JSON value; a wrong type or invalid value keeps the default.
trait Load {
    fn load(&mut self, name: &str, value: &Value);
}

impl Load for bool {
    fn load(&mut self, _: &str, value: &Value) {
        if let Some(v) = value.as_bool() {
            *self = v;
        }
    }
}

impl Load for String {
    fn load(&mut self, name: &str, value: &Value) {
        let Some(v) = value.as_str() else { return };
        if choices(name).is_some_and(|c| !c.contains(&v)) || (name == "seed" && !valid_hex(v)) {
            return;
        }
        *self = v.to_owned();
    }
}

impl Load for i64 {
    fn load(&mut self, name: &str, value: &Value) {
        // Python's type() check: a JSON true/false or 1.0 is not an int.
        let Some(v) = value.as_i64().filter(|_| value.is_i64() || value.is_u64()) else {
            return;
        };
        if (name == "default_range" && !RANGES.contains(&v))
            || int_range(name).is_some_and(|(lo, hi)| !(lo..=hi).contains(&v))
        {
            return;
        }
        *self = v;
    }
}

impl Load for Vec<i64> {
    fn load(&mut self, _: &str, value: &Value) {
        let Some(items) = value.as_array() else {
            return;
        };
        let ints: Vec<i64> = items
            .iter()
            .filter_map(|v| v.as_i64().filter(|_| v.is_i64() || v.is_u64()))
            .collect();
        if ints.len() == 4 && items.len() == 4 {
            *self = ints;
        }
    }
}

impl Load for Vec<String> {
    fn load(&mut self, _: &str, value: &Value) {
        let Some(items) = value.as_array() else {
            return;
        };
        if items.iter().all(Value::is_string) {
            *self = items
                .iter()
                .filter_map(|v| v.as_str().map(str::to_owned))
                .collect();
        }
    }
}

impl Prefs {
    pub fn from_value(data: &Value) -> Prefs {
        let mut prefs = Prefs::default();
        let Some(map) = data.as_object() else {
            return prefs;
        };
        prefs.load_fields(map);
        if !map.contains_key("motion") && map.get("animations") == Some(&Value::Bool(false)) {
            prefs.motion = "off".into(); // settings saved before the motion levels existed
        }
        if let Some(layout) = map.get("layout") {
            prefs.layout = normalize_layout(layout);
        }
        prefs
    }

    /// Unreadable preferences never stop the app; they are not ledger data.
    pub fn read(path: &Path) -> Prefs {
        std::fs::read(path)
            .ok()
            .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
            .map(|v| Prefs::from_value(&v))
            .unwrap_or_default()
    }

    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("version".into(), json!(1));
        m.extend(self.fields());
        m.insert(
            "layout".into(),
            Value::Array(
                self.layout
                    .iter()
                    .map(|i| json!({"id": i.id, "span": i.span}))
                    .collect(),
            ),
        );
        m.insert("animations".into(), json!(self.motion != "off")); // read by LootLedger 0.6 and older
        Value::Object(m)
    }

    /// Atomic: write a temporary file, then replace.
    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let temp = path.with_extension("tmp");
        std::fs::write(&temp, serde_json::to_vec_pretty(&self.to_value())?)?;
        std::fs::rename(&temp, path)
    }

    /// Set one field from the UI by name. Returns false for an unknown name or an invalid value.
    pub fn set(&mut self, name: &str, value: &Value) -> bool {
        let before = self.clone();
        let mut map = Map::new();
        map.insert(name.into(), value.clone());
        self.load_fields(&map);
        *self != before || self.fields().get(name) == Some(value)
    }

    /// 1,234 / 1.234 / 1 234 / 1234, with the decimal mark matching the separator style.
    pub fn number(&self, value: f64, decimals: usize) -> String {
        let text = format!("{:.*}", decimals, value.abs());
        let (int, frac) = text
            .split_once('.')
            .map_or((text.as_str(), None), |(i, f)| (i, Some(f)));
        let mut out = String::new();
        for (i, c) in int.chars().enumerate() {
            if i > 0 && (int.len() - i) % 3 == 0 {
                out.push_str(&self.separators);
            }
            out.push(c);
        }
        if let Some(frac) = frac {
            out.push(if self.separators == "." { ',' } else { '.' });
            out.push_str(frac);
        }
        if value < 0.0 && text.chars().any(|c| c != '0' && c != '.') {
            out.insert(0, '-');
        }
        out
    }

    pub fn int(&self, value: i64) -> String {
        self.number(value as f64, 0)
    }

    pub fn short_date(&self, day: NaiveDate) -> String {
        day.format(match self.date_format.as_str() {
            "mdy" => "%m/%d",
            "iso" => "%m-%d",
            _ => "%d/%m",
        })
        .to_string()
    }

    pub fn full_date(&self, day: NaiveDate) -> String {
        day.format(match self.date_format.as_str() {
            "mdy" => "%m/%d/%Y",
            "iso" => "%Y-%m-%d",
            _ => "%d/%m/%Y",
        })
        .to_string()
    }

    pub fn clock_time(&self, moment: DateTime<Local>) -> String {
        if self.time_24h {
            moment.format("%H:%M").to_string()
        } else {
            moment
                .format("%I:%M %p")
                .to_string()
                .trim_start_matches('0')
                .to_owned()
        }
    }

    pub fn when(&self, moment: DateTime<Local>) -> String {
        format!(
            "{} {}",
            self.full_date(moment.date_naive()),
            self.clock_time(moment)
        )
    }

    /// Playtime as '12h 40m' or as decimal hours, depending on the playtime setting.
    pub fn duration(&self, seconds: f64) -> String {
        let seconds = seconds.max(0.0) as i64;
        if self.playtime == "decimal" {
            return format!("{} h", self.number(seconds as f64 / 3600.0, 1));
        }
        let (hours, minutes) = (seconds / 3600, seconds / 60 % 60);
        if hours > 0 {
            format!("{hours}h {minutes:02}m")
        } else {
            format!("{minutes}m")
        }
    }
}

/// Clock style for a match timer: 12:34 or 1:02:03.
pub fn elapsed(seconds: f64) -> String {
    let s = seconds.max(0.0) as i64;
    let (h, m, sec) = (s / 3600, s % 3600 / 60, s % 60);
    if h > 0 {
        format!("{h}:{m:02}:{sec:02}")
    } else {
        format!("{m}:{sec:02}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invalid_values_fall_back_and_old_files_load() {
        let p = Prefs::from_value(
            &json!({"theme": "neon", "seed": "#12345g", "volume": 300, "default_range": 30,
            "animations": false, "layout": ["trend", {"id": "trend"}, {"id": "nope"}, {"id": "types", "span": 7}],
            "goal_daily": true, "window_geometry": [1, 2, 3], "corners": "round"}),
        );
        assert_eq!(
            (
                p.theme.as_str(),
                p.seed.as_str(),
                p.volume,
                p.motion.as_str()
            ),
            ("system", "#e8b04f", 50, "off")
        );
        assert_eq!(p.corners, "round");
        assert_eq!(p.goal_daily, 0);
        assert!(p.window_geometry.is_empty());
        assert_eq!(
            p.layout,
            vec![
                Item {
                    id: "trend".into(),
                    span: 2
                },
                Item {
                    id: "types".into(),
                    span: 2
                }
            ]
        );
        let back = Prefs::from_value(&p.to_value());
        assert_eq!(back, p);
        assert_eq!(p.to_value()["animations"], json!(false));
    }

    #[test]
    fn numbers_and_durations_match_the_python_formats() {
        let mut p = Prefs::default();
        assert_eq!(p.number(1234567.0, 0), "1,234,567");
        assert_eq!(p.number(24.25, 1), "24.2"); // Python rounds half to even here too
        p.separators = ".".into();
        assert_eq!(p.number(1234.5, 1), "1.234,5");
        p.separators = String::new();
        assert_eq!(p.int(1234), "1234");
        assert_eq!(p.duration(3.0 * 3600.0 + 5.0 * 60.0), "3h 05m");
        assert_eq!(p.duration(59.0 * 60.0), "59m");
        p.playtime = "decimal".into();
        assert_eq!(p.duration(5400.0), "1.5 h");
        assert_eq!(elapsed(3725.0), "1:02:05");
        assert!(p.set("theme", &json!("dark")) && p.theme == "dark");
        assert!(!p.set("theme", &json!("neon")));
    }
}
