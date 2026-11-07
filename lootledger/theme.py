"""Material 3 colour roles, type scale and the Qt stylesheet built from them.

Qt stylesheets have no CSS variables, so every colour and size lives in one Tokens
object and the stylesheet is generated from it. Tonal palettes are built in OKLCH
(lightness, chroma and hue of the seed) and placed at Material's tone numbers. That
approximates Material's HCT palettes; the tests check the contrast it produces.
"""
from dataclasses import dataclass
import ctypes
import math
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QToolTip

FONT_FILE = Path(__file__).resolve().parent / "assets" / "fonts" / "MaterialSymbolsRounded.ttf"
ICON_FONT = "Material Symbols Rounded"
SEEDS = {"Amber": "#e8b04f", "Violet": "#a98aee", "Blue": "#5b9cf0",
         "Teal": "#3fb8a0", "Rose": "#e8718f", "Green": "#7cc46a"}
FONT_SCALES = {"S": .9, "M": 1.0, "L": 1.15, "XL": 1.3}
CORNERS = {"sharp": .4, "default": 1.0, "round": 1.4}
DENSITY = {"compact": .8, "comfortable": 1.0}
TYPE_ORDER = ("Chest", "Rare chest", "Relic chest", "Buried chest", "Sprite poster chest")
ACCENTS = ("primary", "secondary", "tertiary", "error")
SIZES = {"display": 44, "headline": 24, "title": 16, "body": 14, "label": 12, "icon": 22}
SPACE = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24}
RADII = {"sm": 8, "card": 20, "lg": 28}
# Chest types keep one colour everywhere, whatever the accent: Chest gold, Rare blue, Relic purple, Buried green,
# Sprite poster pink, anything else grey. The colourblind option uses the Okabe-Ito palette instead.
RARITY_HUES = (75, 250, 300, 150, 350)
OKABE_ITO = {False: ("#c47f00", "#0072b2", "#b5578f", "#00845f", "#d55e00", "#7a7a7a"),
             True: ("#e69f00", "#56b4e9", "#cc79a7", "#009e73", "#f0e442", "#a0a0a0")}

# Material tone numbers per role (0 black, 100 white).
LIGHT = dict(
    primary=40, on_primary=100, primary_container=90, on_primary_container=10,
    secondary=40, on_secondary=100, secondary_container=90, on_secondary_container=10,
    tertiary=40, on_tertiary=100, tertiary_container=90, on_tertiary_container=10,
    error=40, on_error=100, error_container=90, on_error_container=10,
    surface=98, on_surface=10, on_surface_variant=30, outline=50, outline_variant=80,
    surface_container_lowest=100, surface_container_low=96, surface_container=94,
    surface_container_high=92, surface_container_highest=90,
    inverse_surface=20, inverse_on_surface=95,
)
DARK = dict(
    primary=80, on_primary=20, primary_container=30, on_primary_container=90,
    secondary=80, on_secondary=20, secondary_container=30, on_secondary_container=90,
    tertiary=80, on_tertiary=20, tertiary_container=30, on_tertiary_container=90,
    error=80, on_error=20, error_container=30, on_error_container=90,
    surface=6, on_surface=90, on_surface_variant=80, outline=60, outline_variant=30,
    surface_container_lowest=4, surface_container_low=10, surface_container=12,
    surface_container_high=17, surface_container_highest=22,
    inverse_surface=90, inverse_on_surface=20,
)
# (dark, higher contrast) -> tone changes for muted text and outlines.
OVERRIDES = {
    (False, False): {},
    (False, True): {"on_surface_variant": 22, "outline": 40, "outline_variant": 62},
    (True, False): {},
    (True, True): {"on_surface_variant": 88, "outline": 72, "outline_variant": 45},
}

CURRENT = None  # Tokens in use; painted widgets read it on every paint.


@dataclass(frozen=True)
class Tokens:
    dark: bool
    c: dict          # colour role -> hex
    chart: tuple     # six categorical colours, in TYPE_ORDER order for chest types
    px: dict         # font sizes in px, scaled by the text-size setting
    sp: dict         # spacing in px, scaled by density
    r: dict          # corner radii in px, scaled by the corner setting
    btn_h: int
    background: str
    motion: bool
    family: str
    full_motion: bool = True  # False at the Reduced level: short fades only, no count-ups or loops

    def type_color(self, name):
        return self.chart[TYPE_ORDER.index(name)] if name in TYPE_ORDER else self.chart[-1]


def hex_to_rgb(text):
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#" + "".join(f"{round(min(1.0, max(0.0, v)) * 255):02x}" for v in rgb)


def mix(a, b, amount):
    """Blend colour a towards b in sRGB; used for hover, pressed and focus state layers."""
    return rgb_to_hex(tuple(x + (y - x) * amount for x, y in zip(hex_to_rgb(a), hex_to_rgb(b))))


def _linear(v):
    return v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4


def _encode(v):
    return 12.92 * v if v <= .0031308 else 1.055 * v ** (1 / 2.4) - .055


def _cbrt(v):
    return math.copysign(abs(v) ** (1 / 3), v)


def luminance(color):
    r, g, b = (_linear(v) for v in hex_to_rgb(color))
    return .2126 * r + .7152 * g + .0722 * b


def contrast(a, b):
    """WCAG contrast ratio between two hex colours."""
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


def _to_oklab(rgb):
    r, g, b = (_linear(v) for v in rgb)
    l = _cbrt(.4122214708 * r + .5363325363 * g + .0514459929 * b)
    m = _cbrt(.2119034982 * r + .6806995451 * g + .1073969566 * b)
    s = _cbrt(.0883024619 * r + .2817188376 * g + .6299787005 * b)
    return (.2104542553 * l + .7936177850 * m - .0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + .4505937099 * s,
            .0259040371 * l + .7827717662 * m - .8086757660 * s)


def _to_srgb(lab):
    lightness, a, b = lab
    l_ = lightness + .3963377774 * a + .2158037573 * b
    m_ = lightness - .1055613458 * a - .0638541728 * b
    s_ = lightness - .0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return tuple(_encode(v) for v in (
        4.0767416621 * l - 3.3077115913 * m + .2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - .3413193965 * s,
        -.0041960863 * l - .7034186147 * m + 1.7076147010 * s))


def tone(hue, chroma, t):
    """Colour at Material tone t with the given OKLCH hue and chroma, pulled inside the sRGB gamut."""
    lightness = min((t + 16) / 116, 1.0) if t > 0 else 0.0

    def at(c):
        return _to_srgb((lightness, c * math.cos(hue), c * math.sin(hue)))

    def inside(rgb):
        return all(-1e-6 <= v <= 1 + 1e-6 for v in rgb)

    low, high = 0.0, chroma
    if not inside(at(high)):
        for _ in range(28):
            middle = (low + high) / 2
            low, high = (middle, high) if inside(at(middle)) else (low, middle)
        high = low
    return rgb_to_hex(at(high))


def _palette_of(name):
    for accent in ACCENTS:
        if name == accent or name.startswith(accent + "_") or name.startswith("on_" + accent):
            return accent
    return "neutral_variant" if name in ("on_surface_variant", "outline", "outline_variant") else "neutral"


def build(prefs, dark, motion, family=ICON_FONT, full=True):
    """Create the tokens for these preferences and make them the ones painted widgets use."""
    global CURRENT
    lab = _to_oklab(hex_to_rgb(prefs.seed))
    chroma, hue = max(math.hypot(lab[1], lab[2]), .06), math.atan2(lab[2], lab[1])
    palettes = {"primary": (hue, chroma), "secondary": (hue, chroma * .35),
                "tertiary": (hue + math.pi / 3, chroma * .6), "error": (math.radians(25), .17),
                "neutral": (hue, .008), "neutral_variant": (hue, .02)}
    tones = {**(DARK if dark else LIGHT), **OVERRIDES[(dark, prefs.contrast)]}
    colors = {name: tone(*palettes[_palette_of(name)], t) for name, t in tones.items()}
    density = DENSITY[prefs.density]
    CURRENT = Tokens(
        dark=dark, c=colors,
        chart=OKABE_ITO[dark] if prefs.colorblind else tuple(
            tone(math.radians(h), .13, 75 if dark else 45) for h in RARITY_HUES) + (tone(0, 0, 70 if dark else 50),),
        px={k: round(v * FONT_SCALES[prefs.font_scale]) for k, v in SIZES.items()},
        sp={k: max(2, round(v * density)) for k, v in SPACE.items()},
        r={k: round(v * CORNERS[prefs.corners]) for k, v in RADII.items()},
        btn_h=round(40 * density), background=prefs.background, motion=motion, family=family,
        full_motion=motion and full)
    return CURRENT


def apply_tooltips(T):
    """Tooltips are top-level popups, so they take the palette, not the window stylesheet."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(T.c["inverse_surface"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(T.c["inverse_on_surface"]))
    QToolTip.setPalette(palette)


def is_dark(preference):
    if preference in ("dark", "light"):
        return preference == "dark"
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def os_animations_enabled():
    """Windows' 'Show animations' setting (reduced motion); other systems always allow motion."""
    if sys.platform != "win32":
        return True
    flag = ctypes.c_int(1)
    try:
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)  # SPI_GETCLIENTAREAANIMATION
    except OSError:
        return True
    return bool(flag.value)


def load_icon_font():
    font_id = QFontDatabase.addApplicationFont(str(FONT_FILE)) if FONT_FILE.is_file() else -1
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    return families[0] if families else ICON_FONT


def stylesheet(T):
    c, px, r = T.c, T.px, T.r
    surface, primary, on_primary = c["surface"], c["primary"], c["on_primary"]
    secondary, on_secondary = c["secondary_container"], c["on_secondary_container"]
    state = mix(surface, c["on_surface"], .08)
    primary_state = mix(surface, primary, .08)
    disabled_bg = mix(surface, c["on_surface"], .12)
    disabled_fg = mix(surface, c["on_surface"], .38)
    root = (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {surface}, "
            f"stop:1 {mix(surface, c['primary_container'], .35)})" if T.background == "tonal" else surface)
    family = T.family
    return f"""
    * {{ font-family: "Segoe UI"; font-size: {px['body']}px; color: {c['on_surface']}; }}
    QMainWindow {{ background: {surface}; }}
    QWidget#root {{ background: {root}; }}
    QLabel {{ background: transparent; }}
    QLabel#title {{ font-size: {px['headline']}px; font-weight: 600; }}
    QLabel#muted {{ color: {c['on_surface_variant']}; }}
    QLabel#good {{ color: {primary}; }}
    QLabel#bad {{ color: {c['error']}; }}
    QLabel#cardTitle {{ color: {c['on_surface_variant']}; font-size: {px['label']}px; font-weight: 600; }}
    QLabel#value {{ font-size: {px['title']}px; font-weight: 600; }}
    QLabel#number {{ font-size: {px['display']}px; font-weight: 600; }}
    QLabel#numberAccent {{ font-size: {px['display']}px; font-weight: 600; color: {primary}; }}
    QLabel#onAccent {{ color: {c['on_primary_container']}; }}
    QLabel#onAccentNumber {{ font-size: {px['display']}px; font-weight: 600; color: {c['on_primary_container']}; }}
    QLabel#railLabel {{ color: {c['on_surface_variant']}; font-size: {px['label']}px; font-weight: 500; }}
    QLabel#snackText {{ color: {c['inverse_on_surface']}; }}
    QLabel#icon {{ font-family: "{family}"; font-size: {px['icon']}px; color: {c['on_surface_variant']}; }}
    QLabel#iconAccent {{ font-family: "{family}"; font-size: {px['headline']}px; color: {primary}; }}
    QLabel#iconOnAccent {{ font-family: "{family}"; font-size: {px['icon']}px; color: {c['on_primary_container']}; }}
    QFrame#card {{ background: {c['surface_container_high']}; border-radius: {r['card']}px; }}
    QFrame#cardAccent {{ background: {c['primary_container']}; border-radius: {r['card']}px; }}
    QFrame#panel {{ background: {c['surface_container_low']}; border-radius: {r['sm']}px; }}
    QFrame#segmented {{ background: transparent; border: 1px solid {c['outline']}; border-radius: 999px; }}
    QFrame#snackbar {{ background: {c['inverse_surface']}; border-radius: {r['sm']}px; }}
    QFrame#rail {{ background: {surface}; }}

    QPushButton {{ background: {secondary}; color: {on_secondary}; border: 2px solid transparent;
                   border-radius: 999px; padding: 6px 20px; min-height: {T.btn_h}px; font-weight: 600; }}
    QPushButton:hover {{ background: {mix(secondary, on_secondary, .08)}; }}
    QPushButton:pressed {{ background: {mix(secondary, on_secondary, .12)}; }}
    QPushButton:disabled {{ background: {disabled_bg}; color: {disabled_fg}; }}
    QPushButton#filled {{ background: {primary}; color: {on_primary}; }}
    QPushButton#filled:hover {{ background: {mix(primary, on_primary, .08)}; }}
    QPushButton#filled:pressed {{ background: {mix(primary, on_primary, .12)}; }}
    QPushButton#filled:disabled, QPushButton#outlined:disabled, QPushButton#text:disabled {{
        background: {disabled_bg}; color: {disabled_fg}; }}
    QPushButton#outlined {{ background: transparent; color: {primary}; border: 1px solid {c['outline']}; }}
    QPushButton#outlined:hover {{ background: {primary_state}; }}
    QPushButton#text {{ background: transparent; color: {primary}; padding: 6px 12px; }}
    QPushButton#text:hover {{ background: {primary_state}; }}
    QPushButton#danger {{ background: transparent; color: {c['error']}; border: 1px solid {c['error']}; }}
    QPushButton#danger:hover {{ background: {mix(surface, c['error'], .08)}; }}
    QPushButton#iconButton {{ font-family: "{family}"; font-size: {px['icon']}px; background: transparent;
                              color: {c['on_surface_variant']}; border: 2px solid transparent; border-radius: 20px;
                              min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; padding: 0px; }}
    QPushButton#iconButton:hover {{ background: {state}; color: {c['on_surface']}; }}
    QPushButton#iconButton:pressed {{ background: {mix(surface, c['on_surface'], .12)}; }}
    QPushButton#iconButton:checked {{ background: {secondary}; color: {on_secondary}; }}
    QPushButton#iconButton:disabled {{ background: transparent; color: {disabled_fg}; }}
    QPushButton#fab {{ font-family: "{family}"; font-size: 26px; background: {c['primary_container']};
                       color: {c['on_primary_container']}; border: none; border-radius: {r['lg']}px;
                       min-width: 56px; max-width: 56px; min-height: 56px; max-height: 56px; padding: 0px; }}
    QPushButton#fab:hover {{ background: {mix(c['primary_container'], c['on_primary_container'], .08)}; }}
    QPushButton#segment {{ background: transparent; color: {c['on_surface_variant']}; border: 2px solid transparent;
                           border-radius: 999px; padding: 4px 12px; min-height: 0px; font-weight: 500; }}
    QPushButton#segment:hover {{ background: {state}; }}
    QPushButton#segment:checked {{ background: {secondary}; color: {on_secondary}; }}
    QPushButton#chip {{ background: transparent; color: {c['on_surface_variant']}; border: 1px solid {c['outline']};
                        border-radius: {r['sm']}px; padding: 4px 12px; min-height: 0px; font-weight: 500; }}
    QPushButton#chip:hover {{ background: {state}; }}
    QPushButton#chip:checked {{ background: {secondary}; color: {on_secondary}; border-color: {secondary}; }}
    QPushButton:focus, QPushButton#filled:focus, QPushButton#outlined:focus, QPushButton#text:focus,
    QPushButton#danger:focus, QPushButton#iconButton:focus, QPushButton#fab:focus,
    QPushButton#segment:focus, QPushButton#chip:focus {{ border-color: {primary}; }}

    QLineEdit, QSpinBox, QComboBox {{ background: {c['surface_container_highest']}; color: {c['on_surface']};
                                      border: 1px solid {c['outline_variant']}; border-radius: {r['sm']}px;
                                      padding: 6px 10px; min-height: 22px;
                                      selection-background-color: {primary}; selection-color: {on_primary}; }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 2px solid {primary}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{ background: {c['surface_container_highest']}; color: {c['on_surface']};
                                  selection-background-color: {secondary}; selection-color: {on_secondary};
                                  border: none; padding: 4px; }}
    QTableView {{ background: {c['surface_container_low']}; color: {c['on_surface']}; border: none;
                  gridline-color: transparent; selection-background-color: {secondary};
                  selection-color: {on_secondary}; }}
    QTableView::item {{ padding: 6px 8px; border: none; }}
    QTableView::item:hover {{ background: {state}; }}
    QTableView::item:selected {{ background: {secondary}; color: {on_secondary}; }}
    QTableView:focus {{ border: 2px solid {primary}; }}
    QFrame#dropMarker {{ border: 3px dashed {primary}; border-radius: {r['card']}px; background: {primary_state}; }}
    QHeaderView {{ background: {c['surface_container_low']}; }}
    QHeaderView::section {{ background: {c['surface_container_low']}; color: {c['on_surface_variant']};
                            border: none; border-bottom: 1px solid {c['outline_variant']}; padding: 8px;
                            font-size: {px['label']}px; font-weight: 600; }}
    QTableCornerButton::section {{ background: {c['surface_container_low']}; border: none; }}
    QProgressBar {{ background: {c['surface_container_highest']}; border: none; border-radius: 4px;
                    min-height: 8px; max-height: 8px; }}
    QProgressBar::chunk {{ background: {primary}; border-radius: 4px; }}
    QScrollArea {{ background: {surface}; border: none; }}
    QWidget#qt_scrollarea_viewport {{ background: {surface}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0px; }}
    QScrollBar::handle:vertical {{ background: {c['outline_variant']}; border-radius: 4px; min-height: 32px; margin: 2px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QMenu {{ background: {c['surface_container_high']}; color: {c['on_surface']}; border: none;
             border-radius: {r['sm']}px; padding: 6px; }}
    QMenu::item {{ padding: 8px 16px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {secondary}; color: {on_secondary}; }}
    QMessageBox, QDialog {{ background: {c['surface_container_high']}; }}
    """
