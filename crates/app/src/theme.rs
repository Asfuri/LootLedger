//! Material 3 colour roles from a seed colour, a port of lootledger/theme.py: tonal palettes are built in
//! OKLCH (lightness, chroma and hue of the seed) and placed at Material's tone numbers.

use crate::prefs::Prefs;
use std::f64::consts::PI;

pub const SEEDS: &[(&str, &str)] = &[
    ("Amber", "#e8b04f"),
    ("Violet", "#a98aee"),
    ("Blue", "#5b9cf0"),
    ("Teal", "#3fb8a0"),
    ("Rose", "#e8718f"),
    ("Green", "#7cc46a"),
];
pub const TYPE_ORDER: [&str; 5] = [
    "Chest",
    "Rare chest",
    "Relic chest",
    "Buried chest",
    "Sprite poster chest",
];
const RARITY_HUES: [f64; 5] = [75.0, 250.0, 300.0, 150.0, 350.0];
const OKABE_ITO_LIGHT: [&str; 6] = [
    "#c47f00", "#0072b2", "#b5578f", "#00845f", "#d55e00", "#7a7a7a",
];
const OKABE_ITO_DARK: [&str; 6] = [
    "#e69f00", "#56b4e9", "#cc79a7", "#009e73", "#f0e442", "#a0a0a0",
];

/// Role name and (light tone, dark tone).
const ROLES: &[(&str, u8, u8)] = &[
    ("primary", 40, 80),
    ("on_primary", 100, 20),
    ("primary_container", 90, 30),
    ("on_primary_container", 10, 90),
    ("secondary", 40, 80),
    ("on_secondary", 100, 20),
    ("secondary_container", 90, 30),
    ("on_secondary_container", 10, 90),
    ("tertiary", 40, 80),
    ("on_tertiary", 100, 20),
    ("tertiary_container", 90, 30),
    ("on_tertiary_container", 10, 90),
    ("error", 40, 80),
    ("on_error", 100, 20),
    ("error_container", 90, 30),
    ("on_error_container", 10, 90),
    ("surface", 98, 6),
    ("on_surface", 10, 90),
    ("on_surface_variant", 30, 80),
    ("outline", 50, 60),
    ("outline_variant", 80, 30),
    ("surface_container_lowest", 100, 4),
    ("surface_container_low", 96, 10),
    ("surface_container", 94, 12),
    ("surface_container_high", 92, 17),
    ("surface_container_highest", 90, 22),
    ("inverse_surface", 20, 90),
    ("inverse_on_surface", 95, 20),
];

pub type Rgb = [f64; 3];

pub fn hex_to_rgb(text: &str) -> Rgb {
    let t = text.trim_start_matches('#');
    let channel = |i: usize| {
        u8::from_str_radix(t.get(i..i + 2).unwrap_or("00"), 16).unwrap_or(0) as f64 / 255.0
    };
    [channel(0), channel(2), channel(4)]
}

pub fn rgb_to_hex(rgb: Rgb) -> String {
    rgb.iter()
        .map(|v| format!("{:02x}", (v.clamp(0.0, 1.0) * 255.0).round() as u8))
        .fold("#".to_owned(), |a, b| a + &b)
}

fn linear(v: f64) -> f64 {
    if v <= 0.04045 {
        v / 12.92
    } else {
        ((v + 0.055) / 1.055).powf(2.4)
    }
}

fn encode(v: f64) -> f64 {
    if v <= 0.0031308 {
        12.92 * v
    } else {
        1.055 * v.powf(1.0 / 2.4) - 0.055
    }
}

#[cfg(test)]
pub fn luminance(c: Rgb) -> f64 {
    0.2126 * linear(c[0]) + 0.7152 * linear(c[1]) + 0.0722 * linear(c[2])
}

/// WCAG contrast ratio.
#[cfg(test)]
pub fn contrast(a: Rgb, b: Rgb) -> f64 {
    let (x, y) = (luminance(a), luminance(b));
    (x.max(y) + 0.05) / (x.min(y) + 0.05)
}

fn to_oklab(rgb: Rgb) -> Rgb {
    let [r, g, b] = rgb.map(linear);
    let l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b).cbrt();
    let m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b).cbrt();
    let s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b).cbrt();
    [
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    ]
}

fn to_srgb(lab: Rgb) -> Rgb {
    let [lightness, a, b] = lab;
    let l = (lightness + 0.3963377774 * a + 0.2158037573 * b).powi(3);
    let m = (lightness - 0.1055613458 * a - 0.0638541728 * b).powi(3);
    let s = (lightness - 0.0894841775 * a - 1.2914855480 * b).powi(3);
    [
        encode(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
        encode(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
        encode(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
    ]
}

/// Colour at Material tone t with the given OKLCH hue and chroma, pulled inside the sRGB gamut.
pub fn tone(hue: f64, chroma: f64, t: f64) -> Rgb {
    let lightness = if t > 0.0 {
        ((t + 16.0) / 116.0).min(1.0)
    } else {
        0.0
    };
    let at = |c: f64| to_srgb([lightness, c * hue.cos(), c * hue.sin()]);
    let inside = |rgb: Rgb| rgb.iter().all(|v| (-1e-6..=1.0 + 1e-6).contains(v));
    let (mut low, mut high) = (0.0, chroma);
    if !inside(at(high)) {
        for _ in 0..28 {
            let middle = (low + high) / 2.0;
            if inside(at(middle)) {
                low = middle
            } else {
                high = middle
            }
        }
        high = low;
    }
    // Python's rgb_to_hex clamps; round-trip through hex so the values match exactly.
    hex_to_rgb(&rgb_to_hex(at(high)))
}

fn palette_of(name: &str) -> &'static str {
    for accent in ["primary", "secondary", "tertiary", "error"] {
        if name == accent
            || name.starts_with(&format!("{accent}_"))
            || name.starts_with(&format!("on_{accent}"))
        {
            return accent;
        }
    }
    if matches!(name, "on_surface_variant" | "outline" | "outline_variant") {
        "neutral_variant"
    } else {
        "neutral"
    }
}

pub struct Theme {
    pub colors: Vec<(&'static str, Rgb)>,
    /// Six categorical colours in TYPE_ORDER order, then "other".
    pub chart: [Rgb; 6],
}

impl Theme {
    pub fn color(&self, role: &str) -> Rgb {
        self.colors
            .iter()
            .find(|(n, _)| *n == role)
            .map(|(_, c)| *c)
            .unwrap_or([1.0, 0.0, 1.0])
    }
    pub fn type_color(&self, name: &str) -> Rgb {
        TYPE_ORDER
            .iter()
            .position(|t| *t == name)
            .map_or(self.chart[5], |i| self.chart[i])
    }
}

pub fn build(prefs: &Prefs, dark: bool) -> Theme {
    let lab = to_oklab(hex_to_rgb(&prefs.seed));
    let chroma = lab[1].hypot(lab[2]).max(0.06);
    let hue = lab[2].atan2(lab[1]);
    let palette = |name: &str| -> (f64, f64) {
        match name {
            "primary" => (hue, chroma),
            "secondary" => (hue, chroma * 0.35),
            "tertiary" => (hue + PI / 3.0, chroma * 0.6),
            "error" => (25f64.to_radians(), 0.17),
            "neutral_variant" => (hue, 0.02),
            _ => (hue, 0.008),
        }
    };
    let overrides: &[(&str, u8)] = match (dark, prefs.contrast) {
        (false, true) => &[
            ("on_surface_variant", 22),
            ("outline", 40),
            ("outline_variant", 62),
        ],
        (true, true) => &[
            ("on_surface_variant", 88),
            ("outline", 72),
            ("outline_variant", 45),
        ],
        _ => &[],
    };
    let colors = ROLES
        .iter()
        .map(|&(name, light, dark_tone)| {
            let t = overrides
                .iter()
                .find(|(n, _)| *n == name)
                .map_or(if dark { dark_tone } else { light }, |(_, t)| *t);
            let (h, c) = palette(palette_of(name));
            (name, tone(h, c, t as f64))
        })
        .collect();
    let chart = if prefs.colorblind {
        (if dark {
            OKABE_ITO_DARK
        } else {
            OKABE_ITO_LIGHT
        })
        .map(hex_to_rgb)
    } else {
        let t = if dark { 75.0 } else { 45.0 };
        let mut c = [[0.0; 3]; 6];
        for (i, h) in RARITY_HUES.iter().enumerate() {
            c[i] = tone(h.to_radians(), 0.13, t);
        }
        c[5] = tone(0.0, 0.0, if dark { 70.0 } else { 50.0 });
        c
    };
    Theme { colors, chart }
}

/// Windows' "Show animations" setting (reduced motion).
pub fn os_animations_enabled() -> bool {
    #[cfg(windows)]
    {
        use windows::Win32::UI::WindowsAndMessaging::{
            SPI_GETCLIENTAREAANIMATION, SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS, SystemParametersInfoW,
        };
        let mut flag = windows::core::BOOL(1);
        // SAFETY: SPI_GETCLIENTAREAANIMATION writes one BOOL into the pointer we pass.
        let ok = unsafe {
            SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION,
                0,
                Some(&mut flag as *mut _ as *mut _),
                SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS(0),
            )
        };
        if ok.is_err() {
            return true;
        }
        flag.as_bool()
    }
    #[cfg(not(windows))]
    true
}

/// Whether Windows apps use the dark theme (AppsUseLightTheme = 0).
pub fn system_dark() -> bool {
    #[cfg(windows)]
    {
        use windows::Win32::System::Registry::{HKEY_CURRENT_USER, RRF_RT_REG_DWORD, RegGetValueW};
        use windows::core::w;
        let mut value: u32 = 1;
        let mut size = std::mem::size_of::<u32>() as u32;
        // SAFETY: reads one DWORD into `value`, whose size we pass.
        let status = unsafe {
            RegGetValueW(
                HKEY_CURRENT_USER,
                w!("Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize"),
                w!("AppsUseLightTheme"),
                RRF_RT_REG_DWORD,
                None,
                Some(&mut value as *mut u32 as *mut _),
                Some(&mut size),
            )
        };
        status.is_ok() && value == 0
    }
    #[cfg(not(windows))]
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roles_keep_text_readable_for_every_preset() {
        for (_, seed) in SEEDS {
            for dark in [false, true] {
                for high in [false, true] {
                    let prefs = Prefs {
                        seed: (*seed).into(),
                        contrast: high,
                        ..Prefs::default()
                    };
                    let t = build(&prefs, dark);
                    assert!(contrast(t.color("on_surface"), t.color("surface")) >= 7.0);
                    assert!(
                        contrast(
                            t.color("on_surface_variant"),
                            t.color("surface_container_high")
                        ) >= 4.5
                    );
                    assert!(contrast(t.color("on_primary"), t.color("primary")) >= 4.5);
                    assert!(
                        contrast(
                            t.color("on_primary_container"),
                            t.color("primary_container")
                        ) >= 4.5
                    );
                }
            }
        }
    }

    #[test]
    fn matches_the_python_palette() {
        // Values printed by lootledger.theme.build in the 0.7.1 app.
        let t = build(&Prefs::default(), true);
        let hex = |role: &str| rgb_to_hex(t.color(role));
        assert_eq!(
            [
                hex("primary"),
                hex("surface"),
                hex("on_surface_variant"),
                hex("primary_container")
            ],
            ["#f4bc5c", "#161310", "#cec5b8", "#5e4000"]
        );
        assert_eq!(rgb_to_hex(t.chart[1]), "#7fbeff");
        let t = build(
            &Prefs {
                seed: "#e8718f".into(),
                contrast: true,
                ..Prefs::default()
            },
            false,
        );
        let hex = |role: &str| rgb_to_hex(t.color(role));
        assert_eq!(
            [
                hex("primary"),
                hex("surface"),
                hex("outline"),
                hex("tertiary_container")
            ],
            ["#9f2e52", "#fff7f8", "#695a5d", "#ffdbb9"]
        );
        assert_eq!(rgb_to_hex(t.chart[0]), "#8f6000");
    }
}
