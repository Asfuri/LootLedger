#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod cards;
mod config;
mod discord;
mod i18n;
mod icons;
mod live;
#[cfg(windows)]
mod native;
mod pages;
mod prefs;
mod theme;
mod update;

use chrono::{DateTime, Datelike, Local, NaiveDate};
use lootledger_core::{model::Replay, stats::Grain, store::Store};
use prefs::{Item, Prefs};
use serde_json::{Value, json};
use slint::{ComponentHandle, Model, SharedString, Timer, TimerMode};
use std::{
    cell::RefCell,
    collections::HashMap,
    path::{Path, PathBuf},
    rc::Rc,
    time::{Duration, Instant},
};

slint::include_modules!();

const VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Clone, Copy)]
enum ScanNote {
    None,
    WaitingFirst,
    Checking,
    Reading(usize, usize),
}

struct App {
    ui: slint::Weak<AppWindow>,
    folder: PathBuf,
    prefs: Prefs,
    config: config::Config,
    store: Option<Store>,
    store_error: Option<String>,
    snap: Option<lootledger_core::stats::Snapshot>,
    snap_key: Option<StatsKey>,
    /// The statistics the cards were last built from: switching pages skips the rebuild when unchanged.
    cards_key: Option<StatsKey>,
    session_start: DateTime<Local>,
    tracker: live::Tracker,
    live_replay: Option<Replay>,
    ended_id: Option<String>,
    pop_id: i32,
    scanning: bool,
    scan_note: ScanNote,
    scan_error: Option<String>,
    last_scan: Option<DateTime<Local>>,
    columns: [i32; 2],
    trend: [(i64, Grain); 2],
    compare: [[NaiveDate; 4]; 2],
    theme: theme::Theme,
    reveal_timer: Rc<Timer>,
    countups: Vec<CountUp>,
    pages: pages::State,
    commands: Vec<(String, Command)>,
    shown_commands: Vec<usize>,
    theme_dirty: bool,
    hotkeys_busy: Vec<String>,
    treasure: lootledger_core::stats::TreasureStore,
    treasure_hours: Vec<lootledger_core::stats::TreasureWindow>,
    discord: discord::Client,
    discord_status: String,
}

/// What the statistics depend on: the ledger version, whether broken-open chests count, and today's date.
type StatsKey = ((i64, u64), bool, NaiveDate);

/// A stat value counting up after new data: (grid, row, column, from, to, decimals).
struct CountUp {
    grid: usize,
    row: usize,
    col: usize,
    from: f64,
    to: f64,
    decimals: usize,
}

thread_local! {
    static OFFSCREEN: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
    static OVERLAY: RefCell<Option<Overlay>> = const { RefCell::new(None) };
    static POPUP: RefCell<Option<(MatchPopup, u64)>> = const { RefCell::new(None) };
    static APP: RefCell<Option<Rc<RefCell<App>>>> = const { RefCell::new(None) };
}

fn with_app<R>(f: impl FnOnce(&mut App) -> R) -> Option<R> {
    let app = APP.with(|a| a.borrow().clone())?;
    let mut app = app.borrow_mut();
    Some(f(&mut app))
}

fn current_lang() -> i18n::Lang {
    with_app(|a| i18n::from_code(&a.prefs.language)).unwrap_or_default()
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // --snap=DIR: render each page off-screen, unfocused, save screenshots and quit (visual QA).
    let snap_dir = std::env::args().find_map(|a| a.strip_prefix("--snap=").map(PathBuf::from));
    OFFSCREEN.with(|o| o.set(snap_dir.is_some()));
    slint::BackendSelector::new()
        .backend_name("winit".into())
        .renderer_name(
            if cfg!(feature = "femtovg") {
                "femtovg"
            } else {
                "software"
            }
            .into(),
        )
        .with_winit_window_attributes_hook(|attributes| {
            // Off-screen and unfocused: the summary image and screenshot runs never take focus from a game.
            if OFFSCREEN.with(|o| o.get()) {
                attributes.with_active(false).with_position(
                    slint::winit_030::winit::dpi::PhysicalPosition::new(-6000, -6000),
                )
            } else {
                attributes
            }
        })
        .select()?;
    let ui = AppWindow::new()?;
    let folder = std::env::args()
        .find_map(|a| a.strip_prefix("--data=").map(PathBuf::from))
        .unwrap_or_else(config::data_dir);
    let prefs = Prefs::read(&folder.join("ui-settings.json"));
    let initial_lang = i18n::from_code(&prefs.language);
    let config = config::Config::read(&folder.join("config.json"));
    let (store, store_error) = match open_store(&folder, initial_lang) {
        Ok(s) => (Some(s), None),
        Err(e) => (None, Some(e)),
    };
    let today = Local::now().date_naive();
    let default_trend = (prefs.default_range, Grain::Day);
    let treasure = lootledger_core::stats::TreasureStore::read(&folder.join("treasure-hours.json"));
    let treasure_hours = treasure.all_windows();
    let discord = discord::Client::new(|status| {
        let _ = slint::invoke_from_event_loop(move || {
            let text = with_app(|a| {
                a.discord_status = status.clone();
                i18n::from_code(&a.prefs.language).discord_status(&status)
            })
            .unwrap_or(status);
            if let Some(ui) = window() {
                ui.global::<Settings>().set_discord_status(text.into());
            }
        });
    });
    let app = App {
        ui: ui.as_weak(),
        folder: folder.clone(),
        theme: theme::build(&prefs, true),
        prefs,
        config,
        store,
        store_error,
        snap: None,
        snap_key: None,
        cards_key: None,
        session_start: Local::now(),
        tracker: live::Tracker::new(config::fortnite_log()),
        live_replay: None,
        ended_id: None,
        pop_id: 0,
        scanning: false,
        scan_note: ScanNote::WaitingFirst,
        scan_error: None,
        last_scan: None,
        columns: [3, 3],
        trend: [default_trend, default_trend],
        compare: [cards::default_compare(today); 2],
        reveal_timer: Rc::new(Timer::default()),
        countups: Vec::new(),
        pages: pages::State::new(),
        commands: Vec::new(),
        shown_commands: Vec::new(),
        theme_dirty: false,
        hotkeys_busy: Vec::new(),
        treasure,
        treasure_hours,
        discord,
        discord_status: String::new(),
    };
    let app = Rc::new(RefCell::new(app));
    APP.with(|a| *a.borrow_mut() = Some(app.clone()));

    i18n::apply(&ui, initial_lang);
    apply_theme();
    fill_settings();
    wire(&ui);
    #[cfg(windows)]
    native::install(&ui);
    restore_geometry(&ui);
    // Hotkeys need the window handle, which exists once the window is shown.
    Timer::single_shot(Duration::from_millis(300), || {
        configure_hotkeys();
        apply_overlay();
    });

    let scan_timer = Timer::default();
    let live_timer = Timer::default();
    let clock_timer = Timer::default();
    apply_timers(&scan_timer, &live_timer);
    // The session card shows the match clock (once a second while a match is live) and the session time
    // (every 30 s otherwise).
    let ticks = std::cell::Cell::new(0u32);
    clock_timer.start(TimerMode::Repeated, Duration::from_secs(1), move || {
        ticks.set(ticks.get().wrapping_add(1));
        let live = with_app(|a| a.tracker.state == live::State::Live).unwrap_or(false);
        if live || ticks.get().is_multiple_of(30) {
            refresh_live();
        }
        if ticks.get().is_multiple_of(30) {
            refresh_discord();
        }
    });
    let timers = Rc::new((scan_timer, live_timer));
    {
        let timers = timers.clone();
        ui.global::<Settings>().on_set(move |name, value| {
            set_setting(&name, &value);
            if matches!(
                name.as_str(),
                "auto_watch" | "scan_seconds" | "live_tracking" | "live_seconds"
            ) {
                apply_timers(&timers.0, &timers.1);
            }
        });
    }
    refresh(true);
    if !std::env::args().any(|a| a.starts_with("--snap=")) {
        Timer::single_shot(Duration::from_millis(400), startup_dialog);
        if let Ok(exe) = std::env::current_exe() {
            update::cleanup(&exe);
        }
        // Development builds never replace themselves.
        if !cfg!(debug_assertions) && with_app(|a| a.prefs.auto_update).unwrap_or(false) {
            Timer::single_shot(Duration::from_secs(5), || check_update(false));
        }
        if with_app(|a| a.prefs.auto_treasure_hours).unwrap_or(false) {
            Timer::single_shot(Duration::from_secs(2), || sync_treasure_hours(false));
        }
    }
    let auto = with_app(|a| a.config.auto_watch()).unwrap_or(false);
    if auto {
        Timer::single_shot(Duration::from_millis(150), scan);
    }
    if let Some(seconds) = std::env::args().find_map(|s| {
        s.strip_prefix("--quit-after=")
            .and_then(|s| s.parse::<u64>().ok())
    }) {
        Timer::single_shot(Duration::from_secs(seconds), || {
            let _ = slint::quit_event_loop();
        });
    }
    let _snapper = snap_dir.map(|dir| snapshots(&ui, dir));
    ui.run()?;
    with_app(|a| a.discord.shutdown());
    if !std::env::args().any(|a| a.starts_with("--snap=")) {
        save_geometry(&ui);
        install_update(false);
    }
    Ok(())
}

/// Screenshots of every page (dark then light) as BMP files, for visual QA without a visible window.
fn snapshots(ui: &AppWindow, dir: PathBuf) -> Timer {
    let _ = std::fs::create_dir_all(&dir);
    let size = std::env::args()
        .find_map(|a| a.strip_prefix("--size=").map(str::to_owned))
        .and_then(|s| {
            s.split_once('x')
                .and_then(|(w, h)| Some((w.parse::<f32>().ok()?, h.parse::<f32>().ok()?)))
        })
        .unwrap_or((1240.0, 860.0));
    ui.window()
        .set_size(slint::LogicalSize::new(size.0, size.1));
    let step = Rc::new(std::cell::Cell::new(0usize));
    let timer = Timer::default();
    timer.start(TimerMode::Repeated, Duration::from_millis(900), move || {
        let Some(ui) = window() else { return };
        let n = step.get();
        let shots: Vec<(i32, &str)> = [0, 4, 6, 1, 3, 5, 2]
            .iter()
            .flat_map(|p| [(*p, "dark"), (*p, "light")])
            .collect();
        if n > 0 && n <= shots.len() {
            let (page, scheme) = shots[n - 1];
            if let Ok(pixels) = ui.window().take_snapshot() {
                let _ = std::fs::write(dir.join(format!("page{page}-{scheme}.bmp")), bmp(&pixels));
            }
        }
        if n >= shots.len() {
            if n == shots.len() && std::env::args().any(|a| a.starts_with("--summary-out=")) {
                share_summary(false);
                step.set(n + 1);
                return;
            }
            if n == shots.len() + 1 && std::env::args().any(|a| a.starts_with("--recap-out=")) {
                share_image(true, false);
                step.set(n + 1);
                return;
            }
            let _ = slint::quit_event_loop();
            return;
        }
        let (page, scheme) = shots[n];
        if std::env::args().any(|a| a == "--whats-new") {
            let lang = current_lang();
            let rows = whats_new(lang)
                .iter()
                .map(|line| vec![(format!("•  {line}"), 4)])
                .collect();
            info(
                &format!("{} {VERSION}", lang.t("What's new in", "Novidades no")),
                rows,
                "",
            );
        }
        with_app(|a| a.prefs.theme = scheme.into());
        apply_theme();
        ui.set_page(page);
        refresh(false);
        // Show the detail panels too: the newest match and the top teammate.
        let pages = ui.global::<Pages>();
        if let Some(id) = with_app(|a| {
            a.snap
                .as_ref()
                .and_then(|s| s.match_rows.first().map(|r| r.id.clone()))
        })
        .flatten()
        {
            pages.invoke_select("matches".into(), id.into());
        }
        if let Some(key) =
            with_app(|a| a.pages.ranked.iter().find(|p| !p.me).map(|p| p.key.clone())).flatten()
        {
            pages.invoke_select("team".into(), key.into());
        }
        if let Some(id) = with_app(|a| {
            a.snap.as_ref().and_then(|s| {
                lootledger_core::stats::latest_session(&s.match_rows)
                    .first()
                    .map(|r| r.id.clone())
            })
        })
        .flatten()
        {
            pages.invoke_select("sessions".into(), id.into());
        }
        step.set(n + 1);
    });
    timer
}

fn bmp(pixels: &slint::SharedPixelBuffer<slint::Rgba8Pixel>) -> Vec<u8> {
    let (w, h) = (pixels.width() as usize, pixels.height() as usize);
    let size = 54 + w * h * 4;
    let mut out = Vec::with_capacity(size);
    out.extend_from_slice(b"BM");
    out.extend_from_slice(&(size as u32).to_le_bytes());
    out.extend_from_slice(&[0; 4]);
    out.extend_from_slice(&54u32.to_le_bytes());
    out.extend_from_slice(&40u32.to_le_bytes());
    out.extend_from_slice(&(w as i32).to_le_bytes());
    out.extend_from_slice(&(-(h as i32)).to_le_bytes());
    out.extend_from_slice(&1u16.to_le_bytes());
    out.extend_from_slice(&32u16.to_le_bytes());
    out.extend_from_slice(&[0; 24]);
    for p in pixels.as_slice() {
        out.extend_from_slice(&[p.b, p.g, p.r, 255]);
    }
    out
}

/// Opens the shared ledger. The first time the Rust app opens it, a backup is made first.
fn open_store(folder: &Path, lang: i18n::Lang) -> Result<Store, String> {
    let path = folder.join("ledger.sqlite");
    let store = Store::open(&path).map_err(|e| {
        format!(
            "{}: {e}",
            lang.t(
                "Could not open the ledger",
                "Não foi possível abrir o registro"
            )
        )
    })?;
    let marker = folder
        .join("backups")
        .join(format!("before-lootledger-{VERSION}.sqlite"));
    if path.exists() && !marker.exists() {
        store.backup(&marker).map_err(|e| {
            format!(
                "{}: {e}",
                lang.t(
                    "Could not back up the ledger before first use",
                    "Não foi possível fazer backup do registro antes do primeiro uso"
                )
            )
        })?;
    }
    Ok(store)
}

fn window() -> Option<AppWindow> {
    with_app(|a| a.ui.upgrade()).flatten()
}

fn snack(text: impl Into<SharedString>) {
    let Some(ui) = window() else { return };
    ui.set_snack(text.into());
    let id = ui.get_snack_id() + 1;
    ui.set_snack_id(id);
    Timer::single_shot(Duration::from_millis(4000), move || {
        if let Some(ui) = window()
            && ui.get_snack_id() == id
        {
            ui.set_snack("".into());
        }
    });
}

fn report<T, E: std::fmt::Display>(result: Result<T, E>) -> Option<T> {
    match result {
        Ok(v) => Some(v),
        Err(e) => {
            snack(e.to_string());
            None
        }
    }
}

// ---- Theme ---------------------------------------------------------------------------------------

fn motion_level(prefs: &Prefs) -> &str {
    if prefs.motion == "full" && !theme::os_animations_enabled() {
        "reduced"
    } else {
        prefs.motion.as_str()
    }
}

fn apply_theme() {
    let Some(ui) = window() else { return };
    with_app(|app| {
        let p = &app.prefs;
        let dark = match p.theme.as_str() {
            "dark" => true,
            "light" => false,
            _ => theme::system_dark(),
        };
        app.theme = theme::build(p, dark);
        let t = &app.theme;
        let tokens = ui.global::<Tokens>();
        let c = |role: &str| cards::color(t.color(role));
        tokens.set_dark(dark);
        tokens.set_primary(c("primary"));
        tokens.set_on_primary(c("on_primary"));
        tokens.set_primary_container(c("primary_container"));
        tokens.set_on_primary_container(c("on_primary_container"));
        tokens.set_secondary(c("secondary"));
        tokens.set_secondary_container(c("secondary_container"));
        tokens.set_on_secondary_container(c("on_secondary_container"));
        tokens.set_tertiary(c("tertiary"));
        tokens.set_tertiary_container(c("tertiary_container"));
        tokens.set_on_tertiary_container(c("on_tertiary_container"));
        tokens.set_error(c("error"));
        tokens.set_on_error(c("on_error"));
        tokens.set_error_container(c("error_container"));
        tokens.set_on_error_container(c("on_error_container"));
        tokens.set_surface(c("surface"));
        tokens.set_on_surface(c("on_surface"));
        tokens.set_on_surface_variant(c("on_surface_variant"));
        tokens.set_outline(c("outline"));
        tokens.set_outline_variant(c("outline_variant"));
        tokens.set_container_lowest(c("surface_container_lowest"));
        tokens.set_container_low(c("surface_container_low"));
        tokens.set_container(c("surface_container"));
        tokens.set_container_high(c("surface_container_high"));
        tokens.set_container_highest(c("surface_container_highest"));
        tokens.set_inverse_surface(c("inverse_surface"));
        tokens.set_inverse_on_surface(c("inverse_on_surface"));
        tokens.set_chart(cards::model(
            t.chart.iter().map(|x| cards::color(*x)).collect(),
        ));
        tokens.set_tonal(p.background == "tonal");
        let scale = match p.font_scale.as_str() {
            "S" => 0.9,
            "L" => 1.15,
            "XL" => 1.3,
            _ => 1.0,
        };
        let px = |v: f32| (v * scale).round();
        tokens.set_display(px(44.0));
        tokens.set_headline(px(24.0));
        tokens.set_title(px(16.0));
        tokens.set_body(px(14.0));
        tokens.set_label(px(12.0));
        tokens.set_icon(px(24.0));
        let density = if p.density == "compact" { 0.8 } else { 1.0 };
        let sp = |v: f32| (v * density).round().max(2.0);
        tokens.set_xxs(sp(2.0));
        tokens.set_xs(sp(4.0));
        tokens.set_s(sp(8.0));
        tokens.set_m(sp(12.0));
        tokens.set_l(sp(16.0));
        tokens.set_xl(sp(24.0));
        tokens.set_button_height((40.0 * density).round());
        let corner = match p.corners.as_str() {
            "sharp" => 0.25,
            "round" => 1.4,
            _ => 1.0,
        };
        let r = |v: f32| (v * corner).round();
        tokens.set_r_xs(r(4.0));
        tokens.set_r_sm(r(8.0));
        tokens.set_r_md(r(12.0));
        tokens.set_r_lg(r(16.0));
        tokens.set_r_xl(r(28.0));
        tokens.set_r_card(r(20.0));
        tokens.set_sharp(p.corners == "sharp");
        let level = motion_level(p);
        tokens.set_motion(level != "off");
        tokens.set_full_motion(level == "full");
        ui.global::<Palette>().set_color_scheme(if dark {
            slint::language::ColorScheme::Dark
        } else {
            slint::language::ColorScheme::Light
        });
        ui.set_show_page_title(p.show_page_title);
        app.theme_dirty = true;
    });
}

// ---- Settings ------------------------------------------------------------------------------------

fn index_of(options: &[&str], value: &str) -> i32 {
    options.iter().position(|o| *o == value).unwrap_or(0) as i32
}

fn fill_settings() {
    let Some(ui) = window() else { return };
    with_app(|app| {
        let (p, c, s) = (&app.prefs, &app.config, ui.global::<Settings>());
        let lang = i18n::from_code(&p.language);
        s.set_language(
            i18n::LANGUAGES
                .iter()
                .position(|(code, _)| *code == lang.code())
                .unwrap_or(0) as i32,
        );
        s.set_language_names(cards::model(lang.language_names()));
        s.set_theme(index_of(&["light", "dark", "system"], &p.theme));
        s.set_seed(p.seed.clone().into());
        s.set_seeds(cards::model(
            theme::SEEDS
                .iter()
                .map(|(_, hex)| cards::color(theme::hex_to_rgb(hex)))
                .collect(),
        ));
        s.set_seed_names(cards::model(
            theme::SEEDS
                .iter()
                .map(|(n, _)| SharedString::from(lang.seed_name(n)))
                .collect(),
        ));
        s.set_seed_index(
            theme::SEEDS
                .iter()
                .position(|(_, hex)| hex.eq_ignore_ascii_case(&p.seed))
                .map_or(-1, |i| i as i32),
        );
        s.set_contrast(p.contrast);
        s.set_corners(index_of(&["sharp", "default", "round"], &p.corners));
        s.set_density(index_of(&["compact", "comfortable"], &p.density));
        s.set_font_scale(index_of(&["S", "M", "L", "XL"], &p.font_scale));
        s.set_colorblind(p.colorblind);
        s.set_chart_style(index_of(&["bar", "line", "smooth", "area"], &p.chart_style));
        s.set_background(index_of(&["solid", "tonal"], &p.background));
        s.set_motion(index_of(&["full", "reduced", "off"], &p.motion));
        s.set_show_page_title(p.show_page_title);
        s.set_tile_names(cards::model(
            cards::STAT_TITLES
                .iter()
                .map(|t| SharedString::from(lang.tile_chip_title(t.0)))
                .collect(),
        ));
        s.set_tiles_on(cards::model(
            cards::STAT_TITLES
                .iter()
                .map(|t| p.layout.iter().any(|i| i.id == format!("stat:{}", t.0)))
                .collect(),
        ));
        s.set_time_24h(p.time_24h);
        s.set_date_format(index_of(&["dmy", "mdy", "iso"], &p.date_format));
        s.set_separators(index_of(&[",", ".", " ", ""], &p.separators));
        s.set_playtime(index_of(&["hm", "decimal"], &p.playtime));
        s.set_default_range(
            prefs::RANGES
                .iter()
                .position(|r| *r == p.default_range)
                .unwrap_or(1) as i32,
        );
        s.set_folder(c.replay_folder().to_string_lossy().into_owned().into());
        s.set_auto_watch(c.auto_watch());
        s.set_scan_seconds(c.scan_seconds() as i32);
        s.set_count_broken(c.count_broken());
        s.set_live_tracking(p.live_tracking);
        s.set_live_seconds(
            [1, 2, 5, 10]
                .iter()
                .position(|v| *v == p.live_seconds)
                .unwrap_or(1) as i32,
        );
        s.set_overlay(p.overlay);
        s.set_overlay_opacity(p.overlay_opacity as i32);
        s.set_overlay_size(index_of(&["S", "M", "L"], &p.overlay_size));
        s.set_overlay_corner(index_of(
            &[
                "free",
                "top_left",
                "top_right",
                "bottom_left",
                "bottom_right",
            ],
            &p.overlay_corner,
        ));
        s.set_overlay_click_through(p.overlay_click_through);
        s.set_overlay_teammates(p.overlay_teammates);
        s.set_sound(p.sound);
        s.set_match_popup(p.match_popup);
        s.set_volume(p.volume as i32);
        s.set_goal_daily(p.goal_daily as i32);
        s.set_goal_weekly(p.goal_weekly as i32);
        s.set_celebrate(p.celebrate);
        s.set_auto_treasure_hours(p.auto_treasure_hours);
        let now_local = Local::now();
        let now_utc = chrono::Utc::now();
        let count = app.treasure_hours.len();
        let status = if let Some((boost, end_opt, _)) =
            lootledger_core::stats::active_treasure_window(&now_local, &app.treasure_hours)
        {
            let until = end_opt
                .map(|e| {
                    format!(
                        " {} {}",
                        lang.t("until", "até"),
                        p.clock_time(e.with_timezone(&Local))
                    )
                })
                .unwrap_or_default();
            match lang {
                i18n::Lang::En => {
                    format!("⚡ ACTIVE NOW ({boost:.2}×{until}) · {count} windows loaded.")
                }
                i18n::Lang::PtBr => {
                    format!("⚡ ATIVO AGORA ({boost:.2}×{until}) · {count} janelas carregadas.")
                }
            }
            .replace(".00×", "×")
        } else if let Some(next) =
            lootledger_core::stats::next_treasure_window(&now_local, &app.treasure_hours)
        {
            let ns = next.start_utc.with_timezone(&Local);
            let ne = next.end_utc.with_timezone(&Local);
            match lang {
                i18n::Lang::En => format!(
                    "Next: {} {}–{} ({:.2}×) · {count} windows loaded.",
                    p.full_date(ns.date_naive()),
                    p.clock_time(ns),
                    p.clock_time(ne),
                    next.boost
                ),
                i18n::Lang::PtBr => format!(
                    "Próximo: {} {}–{} ({:.2}×) · {count} janelas carregadas.",
                    p.full_date(ns.date_naive()),
                    p.clock_time(ns),
                    p.clock_time(ne),
                    next.boost
                ),
            }
            .replace(".00×", "×")
        } else {
            match lang {
                i18n::Lang::En => format!(
                    "Fetches official & extended Treasure Hours from GitHub ({count} loaded)."
                ),
                i18n::Lang::PtBr => format!(
                    "Busca Horários do Tesouro oficiais e estendidos no GitHub ({count} carregados)."
                ),
            }
        };
        s.set_treasure_status(status.into());
        if s.get_th_date().is_empty() {
            s.set_th_date(p.full_date(now_local.date_naive()).into());
        }
        if s.get_th_start().is_empty() {
            s.set_th_start("16:00".into());
        }
        if s.get_th_end().is_empty() {
            s.set_th_end("20:00".into());
        }
        if s.get_th_boost().is_empty() {
            s.set_th_boost("1.5x".into());
        }
        let mut sorted_th = app.treasure_hours.clone();
        sorted_th.sort_by(|a, b| {
            b.start_utc
                .cmp(&a.start_utc)
                .then_with(|| a.synced.cmp(&b.synced))
        });
        let th_items: Vec<TreasureHourItem> = sorted_th
            .into_iter()
            .map(|w| {
                let s_local = w.start_utc.with_timezone(&Local);
                let e_local = w.end_utc.with_timezone(&Local);
                let when = if s_local.date_naive() == e_local.date_naive() {
                    format!(
                        "{} · {}–{}",
                        p.full_date(s_local.date_naive()),
                        p.clock_time(s_local),
                        p.clock_time(e_local)
                    )
                } else {
                    format!(
                        "{} {} – {} {}",
                        p.full_date(s_local.date_naive()),
                        p.clock_time(s_local),
                        p.full_date(e_local.date_naive()),
                        p.clock_time(e_local)
                    )
                };
                let denom = (lootledger_core::stats::BASE_TOKEN_DENOM / w.boost).round() as i64;
                let boost = format!(
                    "{:.2}× (1 {} {})",
                    w.boost,
                    lang.t("in", "em"),
                    p.int(denom)
                )
                .replace(".00×", "×");
                let active = now_utc >= w.start_utc && now_utc < w.end_utc;
                let source = if active {
                    format!(
                        "{} · {}",
                        lang.t("LIVE", "AO VIVO"),
                        lang.treasure_label("", w.synced)
                    )
                } else {
                    lang.treasure_label(&w.label, w.synced)
                };
                TreasureHourItem {
                    id: w.id.into(),
                    when: when.into(),
                    boost: boost.into(),
                    source: source.into(),
                    custom: !w.synced,
                    active,
                }
            })
            .collect();
        s.set_treasure_hours(cards::model(th_items));
        s.set_hotkey_add(c.hotkey("hotkey_add").into());
        s.set_hotkey_undo(c.hotkey("hotkey_undo").into());
        s.set_hotkey_overlay(p.hotkey_overlay.clone().into());
        s.set_data_folder(app.folder.to_string_lossy().into_owned().into());
        s.set_version(VERSION.into());
        s.set_auto_update(p.auto_update);
        s.set_discord_rpc(p.discord_rpc);
        s.set_discord_app_id(p.discord_app_id.clone().into());
        s.set_discord_only_in_game(p.discord_only_in_game);
        s.set_discord_status(lang.discord_status(&app.discord_status).into());
    });
}

/// A setting changed in the UI. Choice controls send an index, switches "true"/"false", fields text.
fn set_setting(name: &str, value: &str) {
    let index = value.parse::<usize>().unwrap_or(0);
    let on = value == "true";
    let pick = |options: &[&str]| json!(options.get(index).copied().unwrap_or(options[0]));
    let l = current_lang();
    let pref = match name {
        "language" => Some((
            "language",
            json!(i18n::LANGUAGES.get(index).map_or("en", |x| x.0)),
        )),
        "theme" => Some(("theme", pick(&["light", "dark", "system"]))),
        "seed-index" => Some((
            "seed",
            json!(theme::SEEDS.get(index).map_or("#e8b04f", |s| s.1)),
        )),
        "seed" => {
            let hex = value.trim().to_ascii_lowercase();
            let hex = if hex.starts_with('#') {
                hex
            } else {
                format!("#{hex}")
            };
            if !prefs::valid_hex(&hex) {
                snack(l.t("Use a colour like #e8b04f", "Use uma cor como #e8b04f"));
                fill_settings();
                return;
            }
            Some(("seed", json!(hex)))
        }
        "corners" => Some(("corners", pick(&["sharp", "default", "round"]))),
        "density" => Some(("density", pick(&["compact", "comfortable"]))),
        "font_scale" => Some(("font_scale", pick(&["S", "M", "L", "XL"]))),
        "chart_style" => Some(("chart_style", pick(&["bar", "line", "smooth", "area"]))),
        "background" => Some(("background", pick(&["solid", "tonal"]))),
        "motion" => Some(("motion", pick(&["full", "reduced", "off"]))),
        "date_format" => Some(("date_format", pick(&["dmy", "mdy", "iso"]))),
        "separators" => Some(("separators", pick(&[",", ".", " ", ""]))),
        "playtime" => Some(("playtime", pick(&["hm", "decimal"]))),
        "default_range" => Some((
            "default_range",
            json!(prefs::RANGES.get(index).copied().unwrap_or(30)),
        )),
        "live_seconds" => Some((
            "live_seconds",
            json!([1, 2, 5, 10].get(index).copied().unwrap_or(2)),
        )),
        "overlay_size" => Some(("overlay_size", pick(&["S", "M", "L"]))),
        "overlay_corner" => Some((
            "overlay_corner",
            pick(&[
                "free",
                "top_left",
                "top_right",
                "bottom_left",
                "bottom_right",
            ]),
        )),
        "contrast"
        | "colorblind"
        | "show_page_title"
        | "auto_update"
        | "auto_treasure_hours"
        | "discord_rpc"
        | "discord_only_in_game"
        | "time_24h"
        | "live_tracking"
        | "overlay"
        | "overlay_click_through"
        | "overlay_teammates"
        | "sound"
        | "match_popup"
        | "celebrate" => Some((name, json!(on))),
        "overlay_opacity" | "volume" | "goal_daily" | "goal_weekly" => {
            Some((name, json!(value.parse::<i64>().unwrap_or(0))))
        }
        "hotkey_overlay" => Some(("hotkey_overlay", json!(value.trim()))),
        "discord_app_id" => {
            let trimmed = value.trim();
            if !trimmed.is_empty() && !prefs::valid_discord_app_id(trimmed) {
                snack(l.t(
                    "Discord Application ID must be 17–22 digits",
                    "O Application ID do Discord precisa ter 17 a 22 dígitos",
                ));
            }
            Some(("discord_app_id", json!(trimmed)))
        }
        _ => None,
    };
    if let Some((key, v)) = pref {
        let pending_app_id = if matches!(key, "discord_rpc" | "discord_only_in_game") {
            window().map(|ui| {
                ui.global::<Settings>()
                    .get_discord_app_id()
                    .trim()
                    .to_owned()
            })
        } else {
            None
        };
        with_app(|app| {
            app.prefs.set(key, &v);
            if let Some(id) = pending_app_id
                && id != app.prefs.discord_app_id
            {
                app.prefs.discord_app_id = id;
            }
            report(app.prefs.save(&app.folder.join("ui-settings.json")));
        });
        if key == "language"
            && let Some(ui) = window()
        {
            i18n::apply(&ui, current_lang());
        }
        if key.starts_with("overlay") {
            apply_overlay();
        }
        if key == "hotkey_overlay" {
            configure_hotkeys();
        }
        if key.starts_with("discord_") || key == "separators" {
            refresh_discord();
        }
        if key == "default_range" {
            let days = with_app(|a| a.prefs.default_range).unwrap_or(30);
            with_app(|a| a.trend = [(days, a.trend[0].1), (days, a.trend[1].1)]);
        }
        if matches!(
            key,
            "theme"
                | "seed"
                | "contrast"
                | "corners"
                | "density"
                | "font_scale"
                | "background"
                | "colorblind"
                | "motion"
                | "show_page_title"
        ) {
            apply_theme();
        }
        fill_settings();
        refresh(key == "language");
        return;
    }
    if let Some(i) = name
        .strip_prefix("tile:")
        .and_then(|i| i.parse::<usize>().ok())
    {
        let id = format!("stat:{}", cards::STAT_TITLES.get(i).map_or("", |t| t.0));
        with_app(|app| {
            let present = app.prefs.layout.iter().any(|x| x.id == id);
            if on && !present {
                app.prefs.layout.push(Item {
                    span: prefs::default_span(&id).unwrap_or(1),
                    id,
                });
            } else if !on {
                app.prefs.layout.retain(|x| x.id != id);
            }
        });
        save_layout();
        fill_settings();
        return;
    }
    let config_value = match name {
        "replay_folder" | "hotkey_add" | "hotkey_undo" => json!(value.trim()),
        "auto_watch" | "count_broken" => json!(on),
        "scan_seconds" => json!(value.parse::<i64>().unwrap_or(20)),
        _ => return,
    };
    let result = with_app(|app| app.config.set(name, config_value)).unwrap_or(Ok(()));
    report(result);
    if name.starts_with("hotkey") {
        configure_hotkeys();
    }
    with_app(|a| a.snap_key = None);
    fill_settings();
    refresh(false);
}

fn apply_timers(scan_timer: &Timer, live_timer: &Timer) {
    let (auto, every, tracking, live_every) = with_app(|a| {
        (
            a.config.auto_watch(),
            a.config.scan_seconds(),
            a.prefs.live_tracking,
            a.prefs.live_seconds,
        )
    })
    .unwrap_or((false, 20, false, 2));
    if auto {
        scan_timer.start(TimerMode::Repeated, Duration::from_secs(every as u64), scan);
    } else {
        scan_timer.stop();
    }
    if tracking {
        live_timer.start(
            TimerMode::Repeated,
            Duration::from_secs(live_every as u64),
            poll_live,
        );
    } else {
        live_timer.stop();
        with_app(|a| a.tracker.state = live::State::Idle);
    }
}

// ---- Replays and the live match ------------------------------------------------------------------

fn scan() {
    if std::env::args().any(|a| a.starts_with("--snap=")) {
        return; // screenshot runs show the ledger as it is and never import replays
    }
    let Some((folder, path, include_broken)) = with_app(|app| {
        if app.scanning || app.store.is_none() {
            return None;
        }
        let lang = i18n::from_code(&app.prefs.language);
        let folder = app.config.replay_folder();
        if !folder.is_dir() {
            app.scan_error = Some(match lang {
                i18n::Lang::En => format!(
                    "Replay folder not found: {}. Turn on Record Replays in Fortnite (Settings → Game → Replays) and play a match, or choose the folder in Settings.",
                    folder.display()
                ),
                i18n::Lang::PtBr => format!(
                    "Pasta de replays não encontrada: {}. Ative Gravar Replays no Fortnite (Configurações → Jogo → Replays) e jogue uma partida, ou escolha a pasta em Configurações.",
                    folder.display()
                ),
            });
            return None;
        }
        app.scan_error = None;
        app.scanning = true;
        app.scan_note = ScanNote::Checking;
        Some((folder, app.folder.join("ledger.sqlite"), app.config.count_broken()))
    })
    .flatten()
    else {
        refresh_status();
        return;
    };
    let _ = include_broken;
    refresh_status();
    std::thread::spawn(move || {
        // Its own connection: imports never block the window.
        let result = match Store::open(&path) {
            Ok(mut store) => live::scan(&mut store, &folder, |done, total| {
                if total > 1 {
                    let _ = slint::invoke_from_event_loop(move || {
                        with_app(|a| a.scan_note = ScanNote::Reading(done, total));
                        refresh_status();
                    });
                }
            }),
            Err(e) => live::ScanResult {
                live: None,
                error: Some(e.to_string()),
            },
        };
        let _ = slint::invoke_from_event_loop(move || scan_finished(result));
    });
}

/// Every recorded prize as CSV or JSON rows: when, match, type, tier, who got it and where from.
fn export_rewards() {
    let rows = with_app(|app| {
        let snap = app.snap.as_ref()?;
        let mut out = Vec::new();
        for row in snap.match_rows.iter().rev() {
            for r in &row.rewards {
                let who = match r.by.as_str() {
                    "me" => "You",
                    "team" => "Teammate",
                    "other" => "Other player",
                    _ => "Unknown",
                };
                let at = row.when + chrono::Duration::milliseconds((r.t * 1000.0).round() as i64);
                out.push(
                    serde_json::json!({
                        "when": at.format("%Y-%m-%d %H:%M:%S").to_string(),
                        "match_id": row.id,
                        "mode": row.mode,
                        "reward": if r.recognized() { r.category.clone() } else { String::new() },
                        "tier": r.tier,
                        "prize_id": r.prize,
                        "received_by": who,
                        "player": r.player.clone().unwrap_or_default(),
                        "chest": r.chest.clone().unwrap_or_default(),
                        "replay_time": prefs::elapsed(r.t),
                    })
                    .as_object()
                    .cloned()?,
                );
            }
        }
        Some(out)
    })
    .flatten()
    .unwrap_or_default();
    if rows.is_empty() {
        let lang = current_lang();
        snack(lang.t(
            "No rewards recorded yet",
            "Nenhuma recompensa registrada ainda",
        ));
        return;
    }
    let fields = [
        "when",
        "match_id",
        "mode",
        "reward",
        "tier",
        "prize_id",
        "received_by",
        "player",
        "chest",
        "replay_time",
    ];
    if let Some(path) = rfd::FileDialog::new()
        .set_file_name("lootledger-rewards.csv")
        .add_filter("CSV", &["csv"])
        .add_filter("JSON", &["json"])
        .save_file()
        && report(lootledger_core::store::export_rows(&path, &rows, &fields)).is_some()
    {
        let lang = current_lang();
        snack(match lang {
            i18n::Lang::En => format!("Exported {} rewards", rows.len()),
            i18n::Lang::PtBr => format!("{} recompensas exportadas", rows.len()),
        });
    }
}

fn scan_finished(result: live::ScanResult) {
    let again = with_app(|app| {
        app.scanning = false;
        app.live_replay = result.live;
        app.scan_error = result.error.clone();
        app.scan_note = ScanNote::None;
        app.last_scan = Some(Local::now());
        app.tracker.state == live::State::Saving && result.error.is_none()
    })
    .unwrap_or(false);
    let counted = again && match_counted();
    if again && !counted {
        Timer::single_shot(Duration::from_secs(1), scan); // that check started before the replay was finished
    }
    refresh(false);
    if counted {
        show_match_popup();
    }
}

/// The corner card after a match is counted. It never takes focus, and closes after 8 s or on a click.
fn show_match_popup() {
    let Some(ui) = window() else { return };
    let Some((heading, count, unit, detail, corner)) = with_app(|app| {
        let p = &app.prefs;
        let lang = i18n::from_code(&p.language);
        let snap = app.snap.as_ref()?;
        let id = app.ended_id.as_ref()?;
        let row = snap.match_rows.iter().find(|r| &r.id == id)?;
        if !p.match_popup {
            return None;
        }
        let place = row
            .placement
            .map(|n| format!(" · #{n}"))
            .unwrap_or_default();
        // Stay clear of the pop-out counter.
        let corner = if p.overlay && p.overlay_corner == "bottom-right" {
            "top-right"
        } else {
            "bottom-right"
        };
        Some((
            format!(
                "{} · {}{place}",
                lang.t("Match counted", "Partida contada"),
                lang.mode_name(&row.mode)
            ),
            p.int(row.count),
            lang.chest_word(row.count),
            cards::popup_detail(row.count, snap, p),
            corner,
        ))
    })
    .flatten() else {
        return;
    };
    // Created off-screen and inactive (see the window hook in main), then moved into its corner.
    let offscreen = OFFSCREEN.with(|o| o.replace(true));
    let popup = MatchPopup::new().ok();
    if let Some(w) = &popup {
        let tokens = ui.global::<Tokens>();
        w.set_heading(heading.into());
        w.set_count(count.into());
        w.set_unit(unit.into());
        w.set_detail(detail.into());
        w.set_surface(tokens.get_container_high());
        w.set_outline(tokens.get_outline_variant());
        w.set_ink(tokens.get_on_surface());
        w.set_muted(tokens.get_on_surface_variant());
        w.set_accent(tokens.get_primary());
        w.set_radius(tokens.get_r_lg());
        w.set_pad(tokens.get_m());
        let _ = w.show();
    }
    OFFSCREEN.with(|o| o.set(offscreen));
    let Some(popup) = popup else { return };
    #[cfg(windows)]
    native::style_overlay(popup.window(), 100, false);
    if !offscreen {
        place_in_corner(popup.window(), corner, true); // screenshot runs keep it off-screen
    }
    let weak = popup.as_weak();
    popup.on_dismiss(move || {
        if let Some(w) = weak.upgrade() {
            let _ = w.hide();
        }
    });
    let id = POPUP.with(|slot| {
        let mut slot = slot.borrow_mut();
        let id = slot.as_ref().map_or(0, |(_, id)| id + 1);
        if let Some((old, _)) = slot.replace((popup, id)) {
            let _ = old.hide();
        }
        id
    });
    Timer::single_shot(Duration::from_secs(8), move || {
        POPUP.with(|slot| {
            let mut slot = slot.borrow_mut();
            if slot.as_ref().is_some_and(|(_, current)| *current == id)
                && let Some((w, _)) = slot.take()
            {
                let _ = w.hide();
            }
        });
    });
}

/// Hand-over: the finished replay went through the normal import, so the live view shows that match.
fn match_counted() -> bool {
    let counted = with_app(|app| {
        let name = app.tracker.file_name()?;
        let store = app.store.as_ref()?;
        if !store.replay_files().ok()?.contains_key(&name) {
            return None;
        }
        app.tracker.counted();
        app.ended_id = store.match_for_file(&name).ok().flatten();
        app.pop_id += 1;
        app.snap_key = None;
        Some(app.prefs.sound)
    })
    .flatten();
    match counted {
        Some(sound) => {
            if sound {
                with_app(|a| live::chime(&a.folder, a.prefs.volume));
            }
            true
        }
        None => false,
    }
}

fn poll_live() {
    let (before, after, was_running, now_running) = with_app(|app| {
        let before = app.tracker.state;
        let was_running = app.tracker.game_running();
        let folder = app.config.replay_folder();
        let after = app.tracker.poll(&folder);
        let now_running = app.tracker.game_running();
        (before, after, was_running, now_running)
    })
    .unwrap_or((live::State::Idle, live::State::Idle, false, false));
    if after == live::State::Saving && before != live::State::Saving {
        scan(); // the match just ended: read its replay now instead of at the next check
    }
    if after != before {
        refresh_status();
        refresh_live();
    }
    if after != before || was_running != now_running {
        refresh_discord();
    }
}

fn state_name(state: live::State) -> &'static str {
    match state {
        live::State::Idle => "idle",
        live::State::Waiting => "waiting",
        live::State::Live => "live",
        live::State::Saving => "saving",
        live::State::Ended => "ended",
    }
}

fn live_view(app: &App) -> cards::LiveView {
    let snap = app.snap.as_ref();
    let ended = app
        .ended_id
        .as_ref()
        .and_then(|id| snap?.match_rows.iter().find(|r| &r.id == id).cloned());
    let live_count = app
        .live_replay
        .as_ref()
        .filter(|r| !r.events.is_empty())
        .map(|r| {
            let (mine, meta) = r.summarize();
            let count = mine
                .iter()
                .filter(|(e, _)| app.config.count_broken() || e.kind == "opened")
                .count() as i64;
            (count, meta["mode"].as_str().unwrap_or("").to_owned())
        });
    cards::LiveView {
        state: state_name(app.tracker.state),
        elapsed: app.tracker.elapsed(),
        locked: app.tracker.locked(),
        live_count,
        ended,
        pop_id: app.pop_id,
    }
}

fn health(app: &App) -> cards::Health {
    let lang = i18n::from_code(&app.prefs.language);
    let folder = app.config.replay_folder();
    let files = live::replays(&folder);
    let newest = files
        .last()
        .and_then(|(_, m)| m.modified().ok())
        .map(live::seconds);
    let game = std::fs::metadata(config::fortnite_log())
        .and_then(|m| m.modified())
        .ok()
        .map(live::seconds);
    let now = live::seconds(std::time::SystemTime::now());
    let played_without_replay =
        game.is_some_and(|g| now - g < 86400.0 && newest.is_none_or(|n| g - n > 3.0 * 3600.0));
    let fix = lang.t(
        "In Fortnite: Settings → Game → Replays → Record Replays: On. Then play a match.",
        "No Fortnite: Configurações → Jogo → Replays → Gravar Replays: Ligado. Depois jogue uma partida.",
    );
    let checks = vec![
        (
            lang.t("Replay folder found", "Pasta de replays encontrada")
                .to_owned(),
            folder.is_dir(),
            match lang {
                i18n::Lang::En => format!(
                    "Fortnite creates {} after its first recorded match. {fix}",
                    folder.display()
                ),
                i18n::Lang::PtBr => format!(
                    "O Fortnite cria {} após a primeira partida gravada. {fix}",
                    folder.display()
                ),
            },
        ),
        (
            lang.t(
                "Fortnite has saved replays",
                "O Fortnite tem replays salvos",
            )
            .to_owned(),
            !files.is_empty(),
            fix.to_owned(),
        ),
        (
            lang.t(
                "Recent matches were recorded",
                "Partidas recentes foram gravadas",
            )
            .to_owned(),
            !files.is_empty() && !played_without_replay,
            match lang {
                i18n::Lang::En => format!(
                    "Fortnite ran in the last day but saved no replay for hours. Record Replays may be off. {fix}"
                ),
                i18n::Lang::PtBr => format!(
                    "O Fortnite rodou nas últimas 24 h mas não salvou replay há horas. Gravar Replays pode estar desativado. {fix}"
                ),
            },
        ),
    ];
    let (read, unreadable) = app
        .store
        .as_ref()
        .and_then(|s| s.replay_file_counts().ok())
        .unwrap_or((0, 0));
    cards::Health {
        checks,
        replays: files.len(),
        newest,
        read,
        unreadable,
        watching: if app.config.auto_watch() {
            let every = app.config.scan_seconds();
            match lang {
                i18n::Lang::En => format!("Checking every {every} s"),
                i18n::Lang::PtBr => format!("Verificando a cada {every} s"),
            }
        } else {
            lang.t(
                "Automatic checks are off",
                "Verificação automática desativada",
            )
            .into()
        },
        last_scan: app.last_scan,
    }
}

// ---- Dashboard -----------------------------------------------------------------------------------

fn stats_key(app: &App) -> Option<StatsKey> {
    Some((
        app.store.as_ref()?.version().unwrap_or((0, 0)),
        app.config.count_broken(),
        Local::now().date_naive(),
    ))
}

fn snapshot(app: &mut App, force: bool) -> bool {
    let Some(key) = stats_key(app) else {
        return false;
    };
    let Some(store) = app.store.as_ref() else {
        return false;
    };
    if !force && app.snap_key == Some(key) && app.snap.is_some() {
        return false;
    }
    match store.snapshot(app.config.count_broken(), Some(app.session_start)) {
        Ok(snap) => {
            app.snap = Some(snap);
            app.snap_key = Some(key);
            true
        }
        Err(e) => {
            app.store_error = Some(e.to_string());
            false
        }
    }
}

fn context<'a>(
    app: &'a App,
    grid: usize,
    snap: &'a lootledger_core::stats::Snapshot,
    needs_health: bool,
) -> cards::Context<'a> {
    cards::Context {
        snap,
        prefs: &app.prefs,
        theme: &app.theme,
        live: live_view(app),
        health: needs_health.then(|| health(app)),
        trend: app.trend[grid],
        compare: app.compare[grid],
        treasure_hours: &app.treasure_hours,
        synced_prizes: &app.treasure.prizes,
    }
}

/// Rebuild the cards. `force` recomputes the statistics even if the ledger did not change.
fn refresh(force: bool) {
    let Some(ui) = window() else { return };
    let built = with_app(|app| {
        let lang = i18n::from_code(&app.prefs.language);
        let changed = snapshot(app, force);
        let snap = app.snap.take()?;
        let layout: Vec<(String, i32)> = app
            .prefs
            .layout
            .iter()
            .map(|i| (i.id.clone(), i.span))
            .collect();
        let stats_layout: Vec<(String, i32)> = cards::STATS_ORDER
            .iter()
            .map(|id| ((*id).to_owned(), prefs::default_span(id).unwrap_or(1)))
            .collect();
        let mut grids = Vec::new();
        for (grid, items) in [layout, stats_layout].into_iter().enumerate() {
            let needs_health = items.iter().any(|(id, _)| id == "health");
            let ctx = context(app, grid, &snap, needs_health);
            let built: Vec<CardData> = items
                .iter()
                .map(|(id, span)| cards::build(id, *span, &ctx))
                .collect();
            let targets: Vec<(String, f64, usize)> = items
                .iter()
                .filter_map(|(id, _)| {
                    let key = id.strip_prefix("stat:")?;
                    match cards::stat_value(key, &ctx).0 {
                        cards::Value::Number(v, d) => Some((id.clone(), v, d)),
                        cards::Value::Text(_) => None,
                    }
                })
                .collect();
            grids.push((built, targets));
        }
        let who = snap
            .player
            .clone()
            .unwrap_or_else(|| lang.t("Your replays", "Seus replays").into());
        let subtitle = match lang {
            i18n::Lang::En => format!("{who} · {} matches read", snap.matches),
            i18n::Lang::PtBr => format!("{who} · {} partidas lidas", snap.matches),
        };
        let stats_subtitle = match lang {
            i18n::Lang::En => format!(
                "Computed from {} and your corrections",
                lang.matches_count(snap.matches)
            ),
            i18n::Lang::PtBr => format!(
                "Calculado com base em {} e suas correções",
                lang.matches_count(snap.matches)
            ),
        };
        app.snap = Some(snap);
        let missing: Vec<SharedString> = prefs::WIDGETS
            .iter()
            .filter(|(id, _)| !app.prefs.layout.iter().any(|i| i.id == *id))
            .map(|(id, _)| SharedString::from(cards::title_of(id, lang).0))
            .collect();
        Some((
            grids,
            subtitle,
            stats_subtitle,
            changed,
            missing,
            app.columns,
        ))
    })
    .flatten();
    let Some((grids, subtitle, stats_subtitle, changed, missing, columns)) = built else {
        let error = with_app(|a| a.store_error.clone()).flatten();
        let fallback = current_lang().t("No ledger yet", "Nenhum registro ainda");
        ui.set_overview_subtitle(error.unwrap_or_else(|| fallback.into()).into());
        refresh_status();
        return;
    };
    let mut countups = Vec::new();
    for (grid, (built, targets)) in grids.into_iter().enumerate() {
        // Count the stat values up from what was shown before (Full motion only).
        let previous = previous_values(&ui, grid);
        let rows = cards::pack(built, columns[grid]);
        for (r, row) in rows.iter().enumerate() {
            for (c, card) in row.cards.iter().enumerate() {
                if let Some((_, to, decimals)) = targets
                    .iter()
                    .find(|(id, _, _)| id.as_str() == card.id.as_str())
                {
                    let from = previous.get(card.id.as_str()).copied().unwrap_or(0.0);
                    if changed && (from - to).abs() > 1e-9 {
                        countups.push(CountUp {
                            grid,
                            row: r,
                            col: c,
                            from,
                            to: *to,
                            decimals: *decimals,
                        });
                    }
                }
            }
        }
        let model = cards::model(rows);
        if grid == 0 {
            ui.set_overview_rows(model)
        } else {
            ui.set_stats_rows(model)
        }
    }
    ui.set_overview_subtitle(subtitle.into());
    ui.set_stats_subtitle(stats_subtitle.into());
    let theme_dirty = with_app(|a| std::mem::take(&mut a.theme_dirty)).unwrap_or(false);
    if changed || force || theme_dirty {
        fill_pages(&ui);
        announce();
    }
    ui.set_missing_widgets(cards::model(missing));
    with_app(|a| a.cards_key = a.snap_key);
    refresh_status();
    refresh_overlay();
    refresh_discord();
    if changed {
        with_app(|a| a.countups = countups);
        animate_in();
    }
}

/// Refill Matches, Openings and Teammates from the current snapshot and the openings list.
fn fill_pages(ui: &AppWindow) {
    with_app(|app| {
        let Some(store) = app.store.as_ref() else {
            return;
        };
        app.pages.entries = pages::load_entries(store);
        app.pages.synced_prizes = app.treasure.prizes.clone();
        let Some(snap) = app.snap.as_ref() else {
            return;
        };
        pages::fill(
            ui,
            &mut app.pages,
            snap,
            &app.prefs,
            &app.theme,
            app.config.count_broken(),
        );
    });
    refresh_marks(ui);
}

/// Timelines for the selected match and the Openings page's chosen match.
fn refresh_marks(ui: &AppWindow) {
    with_app(|app| {
        let (Some(store), Some(snap)) = (app.store.as_ref(), app.snap.as_ref()) else {
            return;
        };
        let lang = i18n::from_code(&app.prefs.language);
        let broken = app.config.count_broken();
        for (target, id) in [
            ("detail", Some(app.pages.selected_match.clone())),
            ("open", pages::selected_entry_match(ui, &app.pages)),
        ] {
            let Some(row) = id.and_then(|id| snap.match_rows.iter().find(|r| r.id == id)) else {
                continue;
            };
            let marks = store.match_marks(&row.id, broken).unwrap_or_default();
            pages::set_detail_marks(ui, &marks, row.seconds, &app.theme, lang, target);
        }
    });
}

/// After a write: rebuild statistics, cards and pages.
fn changed_data() {
    with_app(|a| a.snap_key = None);
    refresh(false);
}

fn page_action(action: &str) {
    let Some(ui) = window() else { return };
    let l = current_lang();
    let selected = with_app(|a| a.pages.selected_entry.clone()).unwrap_or_default();
    match action {
        "correct" => {
            let found = with_app(|a| {
                a.pages
                    .entries
                    .iter()
                    .find(|(x, _)| x.id == selected)
                    .map(|(x, _)| x.clone())
            })
            .flatten();
            match found {
                Some(entry) => {
                    let g = ui.global::<Pages>();
                    g.set_correct_type(entry.chest_type.into());
                    g.set_correct_count(entry.amount as i32);
                    g.set_correct_reason(entry.reason.into());
                    g.set_correcting(true);
                }
                None => snack(l.t("Select an opening first", "Selecione uma abertura primeiro")),
            }
            return;
        }
        "export" | "export-csv" | "export-json" => {
            let openings = action == "export";
            let rows = with_app(|a| {
                if openings {
                    pages::visible_entry_rows(&a.pages)
                } else {
                    pages::people_rows(&a.pages)
                }
            })
            .unwrap_or_default();
            if rows.is_empty() {
                snack(if openings {
                    l.t(
                        "No openings match the current filters",
                        "Nenhuma abertura corresponde aos filtros",
                    )
                } else {
                    l.t(
                        "No teammates in this view",
                        "Nenhum colega nesta visualização",
                    )
                });
                return;
            }
            let (name, filters): (&str, &[(&str, &str)]) = match action {
                "export" => (
                    "lootledger-openings.csv",
                    &[("CSV", "csv"), ("JSON", "json")],
                ),
                "export-csv" => ("LootLedger-teammates.csv", &[("CSV", "csv")]),
                _ => ("LootLedger-teammates.json", &[("JSON", "json")]),
            };
            let mut dialog = rfd::FileDialog::new().set_file_name(name);
            for (label, ext) in filters {
                dialog = dialog.add_filter(*label, &[*ext]);
            }
            if let Some(path) = dialog.save_file() {
                let fields: &[&str] = if openings {
                    &pages::EVENT_FIELDS
                } else {
                    pages::people_fields()
                };
                if report(lootledger_core::store::export_rows(&path, &rows, fields)).is_some() {
                    snack(format!(
                        "{} {} {}",
                        l.t("Exported", "Exportado:"),
                        rows.len(),
                        if openings {
                            l.t("openings", "aberturas")
                        } else {
                            l.t("people", "pessoas")
                        }
                    ));
                }
            }
            return;
        }
        _ => {}
    }
    let result: Result<Option<String>, String> = with_app(|app| {
        let store = app.store.as_mut().ok_or_else(|| {
            l.t("The ledger is not open", "O registro não está aberto")
                .to_owned()
        })?;
        let e = |e: lootledger_core::store::Error| e.to_string();
        match action {
            "undo" => Ok(store.undo().map_err(e)?.then(|| {
                l.t("Last opening removed", "Última abertura removida")
                    .to_owned()
            })),
            "add" => store
                .add_correction(1, "Chest")
                .map(|_| {
                    Some(
                        l.t(
                            "Added one chest to the latest match",
                            "Um baú adicionado à última partida",
                        )
                        .to_owned(),
                    )
                })
                .map_err(e),
            "remove" | "restore" | "apply-correct" if selected.is_empty() => Err(l
                .t("Select an opening first", "Selecione uma abertura primeiro")
                .into()),
            "remove" => store
                .edit(&selected, Some("undone"), None, None)
                .map(|_| None)
                .map_err(e),
            "restore" => store
                .edit(&selected, Some("confirmed"), None, None)
                .map(|_| None)
                .map_err(e),
            "apply-correct" => {
                let g = ui.global::<Pages>();
                let result = store
                    .edit(
                        &selected,
                        None,
                        Some(g.get_correct_type().as_str()),
                        Some(g.get_correct_count() as i64),
                    )
                    .map(|_| None)
                    .map_err(e);
                if result.is_ok() {
                    g.set_correcting(false);
                }
                result
            }
            _ => Ok(None),
        }
    })
    .unwrap_or(Ok(None));
    match result {
        Ok(message) => {
            changed_data();
            if let Some(m) = message {
                snack(m);
            }
        }
        Err(message) => snack(message),
    }
}

fn previous_values(ui: &AppWindow, grid: usize) -> HashMap<String, f64> {
    let rows = if grid == 0 {
        ui.get_overview_rows()
    } else {
        ui.get_stats_rows()
    };
    let separators = with_app(|a| a.prefs.separators.clone()).unwrap_or_default();
    let mut out = HashMap::new();
    for row in rows.iter() {
        for card in row.cards.iter() {
            if card.kind == "stat" {
                let digits: String = card
                    .value
                    .chars()
                    .filter(|c| !separators.contains(*c) || separators.is_empty())
                    .map(|c| {
                        if c == ',' && separators == "." {
                            '.'
                        } else {
                            c
                        }
                    })
                    .collect();
                if let Ok(v) = digits.parse::<f64>() {
                    out.insert(card.id.to_string(), v);
                }
            }
        }
    }
    out
}

/// Charts draw in and stat values count up over 600 ms, then the timer stops (no idle timers).
fn animate_in() {
    let Some(ui) = window() else { return };
    let full = ui.global::<Tokens>().get_full_motion();
    let anim = ui.global::<Anim>();
    let Some(timer) = with_app(|a| a.reveal_timer.clone()) else {
        return;
    };
    if !full {
        anim.set_reveal(1.0);
        finish_countups(&ui, 1.0);
        return;
    }
    anim.set_reveal(0.0);
    let start = Instant::now();
    timer.start(TimerMode::Repeated, Duration::from_millis(16), move || {
        let t = (start.elapsed().as_secs_f32() / 0.6).min(1.0);
        let eased = 1.0 - (1.0 - t).powi(3);
        if let Some(ui) = window() {
            ui.global::<Anim>().set_reveal(eased);
            finish_countups(&ui, eased as f64);
        }
        if t >= 1.0
            && let Some(timer) = with_app(|a| a.reveal_timer.clone())
        {
            timer.stop();
        }
    });
}

fn finish_countups(ui: &AppWindow, t: f64) {
    with_app(|app| {
        for c in &app.countups {
            let rows = if c.grid == 0 {
                ui.get_overview_rows()
            } else {
                ui.get_stats_rows()
            };
            let Some(row) = rows.row_data(c.row) else {
                continue;
            };
            let Some(mut card) = row.cards.row_data(c.col) else {
                continue;
            };
            card.value = app
                .prefs
                .number(c.from + (c.to - c.from) * t, c.decimals)
                .into();
            row.cards.set_row_data(c.col, card);
        }
        if t >= 1.0 {
            app.countups.clear();
        }
    });
}

/// Rebuild only the live card (once a second during a match).
fn refresh_live() {
    let Some(ui) = window() else { return };
    with_app(|app| {
        let Some(snap) = app.snap.take() else { return };
        for grid in 0..2 {
            let rows = if grid == 0 {
                ui.get_overview_rows()
            } else {
                ui.get_stats_rows()
            };
            for row in rows.iter() {
                for (c, card) in row.cards.iter().enumerate() {
                    if card.id == "live" {
                        let ctx = context(app, grid, &snap, false);
                        row.cards
                            .set_row_data(c, cards::build("live", card.span, &ctx));
                    }
                }
            }
        }
        app.snap = Some(snap);
    });
    refresh_status();
    refresh_overlay();
}

fn refresh_status() {
    let Some(ui) = window() else { return };
    with_app(|app| {
        let lang = i18n::from_code(&app.prefs.language);
        let partial = app.snap.as_ref().map_or(0, |s| s.partial);
        let (mut text, tone) = if let Some(e) = &app.scan_error {
            (e.clone(), 3)
        } else if let Some(e) = &app.store_error {
            (e.clone(), 3)
        } else if !matches!(app.scan_note, ScanNote::None) {
            let note = match app.scan_note {
                ScanNote::None => String::new(),
                ScanNote::WaitingFirst => lang
                    .t(
                        "Waiting for the first replay check",
                        "Aguardando a primeira verificação de replays",
                    )
                    .to_owned(),
                ScanNote::Checking => lang
                    .t("Checking replays…", "Verificando replays…")
                    .to_owned(),
                ScanNote::Reading(done, total) => match lang {
                    i18n::Lang::En => format!("Reading replays {done}/{total}…"),
                    i18n::Lang::PtBr => format!("Lendo replays {done}/{total}…"),
                },
            };
            (note, 0)
        } else if app.tracker.state == live::State::Live {
            (
                if app.tracker.locked() {
                    lang.t(
                        "Match in progress · its chests are counted when it ends (Fortnite encrypts the replay until then)",
                        "Partida em andamento · os baús são contados ao terminar (o Fortnite criptografa o replay até lá)",
                    )
                    .to_owned()
                } else {
                    lang.t("Match in progress", "Partida em andamento")
                        .to_owned()
                },
                2,
            )
        } else {
            let folder = app.config.replay_folder();
            (
                match lang {
                    i18n::Lang::En => format!(
                        "Watching {} · finished matches are added automatically",
                        folder.display()
                    ),
                    i18n::Lang::PtBr => format!(
                        "Monitorando {} · partidas finalizadas são adicionadas automaticamente",
                        folder.display()
                    ),
                },
                0,
            )
        };
        if partial > 0 && app.scan_error.is_none() {
            text += &match lang {
                i18n::Lang::En => format!(" · {partial} replay(s) read partly (see Matches)"),
                i18n::Lang::PtBr => {
                    format!(" · {partial} replay(s) lido(s) parcialmente (veja Partidas)")
                }
            };
        }
        if let Some(t) = app.last_scan {
            text += &format!(
                " · {} {}",
                lang.t("checked", "verificado às"),
                t.format("%H:%M:%S")
            );
        }
        ui.set_status(text.into());
        ui.set_status_tone(tone);
        let (chip, chip_tone) = match app.tracker.state {
            live::State::Live => (
                format!(
                    "{} · {}",
                    lang.t("Live", "Ao vivo"),
                    prefs::elapsed(app.tracker.elapsed().unwrap_or(0.0))
                ),
                1,
            ),
            live::State::Saving => (
                lang.t("Reading the replay…", "Lendo o replay…").to_owned(),
                2,
            ),
            live::State::Ended => (lang.t("Match counted", "Partida contada").to_owned(), 3),
            _ => (String::new(), 0),
        };
        ui.set_live_chip(chip.into());
        ui.set_live_chip_tone(chip_tone);
    });
}

fn save_layout() {
    with_app(|app| report(app.prefs.save(&app.folder.join("ui-settings.json"))));
    with_app(|a| a.snap_key = None);
    refresh(false);
}

// ---- Callbacks -----------------------------------------------------------------------------------

fn wire(ui: &AppWindow) {
    ui.on_columns_changed(|n| {
        if with_app(|a| std::mem::replace(&mut a.columns[0], n) != n).unwrap_or(false) {
            refresh(false);
        }
    });
    ui.on_stats_columns_changed(|n| {
        if with_app(|a| std::mem::replace(&mut a.columns[1], n) != n).unwrap_or(false) {
            refresh(false);
        }
    });
    ui.on_navigate(|page| {
        // Every change rebuilds the cards when it happens; a page switch only catches up on what changed since.
        let stale =
            with_app(|a| a.theme_dirty || a.cards_key.is_none() || a.cards_key != stats_key(a))
                .unwrap_or(true);
        if (page == 0 || page == 4) && stale {
            refresh(false);
        }
    });
    let dash = ui.global::<Dash>();
    dash.on_move(|from, to| {
        with_app(|app| {
            let n = app.prefs.layout.len() as i32;
            if from < 0 || from >= n {
                return;
            }
            let to = to.clamp(0, n - 1);
            let item = app.prefs.layout.remove(from as usize);
            app.prefs.layout.insert(to as usize, item);
        });
        save_layout();
    });
    dash.on_resize(|index, span| {
        with_app(|app| {
            if let Some(item) = app.prefs.layout.get_mut(index as usize) {
                item.span = span.clamp(1, 2);
            }
        });
        save_layout();
    });
    dash.on_remove(|index| {
        with_app(|app| {
            if (index as usize) < app.prefs.layout.len() {
                app.prefs.layout.remove(index as usize);
            }
        });
        save_layout();
        fill_settings();
    });
    ui.on_add_widget(|index| {
        with_app(|app| {
            let missing: Vec<&str> = prefs::WIDGETS
                .iter()
                .map(|w| w.0)
                .filter(|id| !app.prefs.layout.iter().any(|i| i.id == *id))
                .collect();
            if let Some(id) = missing.get(index as usize) {
                app.prefs.layout.push(Item {
                    id: (*id).into(),
                    span: prefs::default_span(id).unwrap_or(1),
                });
            }
        });
        save_layout();
        fill_settings();
    });
    ui.on_reset_layout(|| {
        with_app(|app| app.prefs.layout = prefs::default_layout());
        save_layout();
        fill_settings();
    });
    let grid_of = |ui: &AppWindow| if ui.get_page() == 4 { 1 } else { 0 };
    {
        let weak = ui.as_weak();
        dash.on_trend_range(move |_, i| {
            let grid = weak.upgrade().map_or(0, |u| grid_of(&u));
            with_app(|a| a.trend[grid].0 = prefs::RANGES.get(i as usize).copied().unwrap_or(30));
            refresh(false);
        });
    }
    {
        let weak = ui.as_weak();
        dash.on_trend_grain(move |_, i| {
            let grid = weak.upgrade().map_or(0, |u| grid_of(&u));
            with_app(|a| {
                a.trend[grid].1 = [Grain::Day, Grain::Week, Grain::Month][(i as usize).min(2)]
            });
            refresh(false);
        });
    }
    dash.on_chart_style(|i| set_setting("chart_style", &i.to_string()));
    {
        let weak = ui.as_weak();
        dash.on_compare_date(move |_, slot, text| {
            let grid = weak.upgrade().map_or(0, |u| grid_of(&u));
            let parsed = with_app(|a| parse_date(&text, &a.prefs.date_format)).flatten();
            match parsed {
                Some(day) => {
                    with_app(|a| a.compare[grid][(slot as usize).min(3)] = day);
                }
                None => snack(current_lang().t(
                    "Use the date format from Settings → Formats",
                    "Use o formato de data de Configurações → Formatos",
                )),
            }
            refresh(false);
        });
    }
    ui.on_overview_action(|action| match action.as_str() {
        "scan" => scan(),
        "overlay" => toggle_overlay(),
        "Copy summary image" => share_summary(true),
        "Save summary image…" => share_summary(false),
        "Copy weekly recap" => share_image(true, true),
        "Save weekly recap…" => share_image(true, false),
        _ => {}
    });
    let settings = ui.global::<Settings>();
    settings.on_action(|action| settings_action(&action));
    settings.on_add_treasure_hour(|date, start, end, boost| {
        add_treasure_hour(&date, &start, &end, &boost);
    });
    settings.on_remove_treasure_hour(|id| {
        remove_treasure_hour(&id);
    });
    ui.on_shortcut(|which| match which.as_str() {
        "palette" => open_palette(),
        _ => show_shortcuts(),
    });
    ui.on_palette_query(|q| palette_filter(&q));
    ui.on_palette_run(run_command);
    ui.on_info_run(|| install_update(true));
    let pg = ui.global::<Pages>();
    pg.on_changed(|table| {
        let Some(ui) = window() else { return };
        with_app(|app| {
            let Some(snap) = app.snap.as_ref() else {
                return;
            };
            match table.as_str() {
                "matches" => pages::matches(
                    &ui,
                    &app.pages,
                    snap,
                    &app.prefs,
                    &app.theme,
                    app.config.count_broken(),
                ),
                "entries" => pages::entries(&ui, &mut app.pages, snap, &app.prefs, &app.theme),
                "sessions" => pages::sessions(&ui, &mut app.pages, snap, &app.prefs, &app.theme),
                _ => pages::team(&ui, &mut app.pages, snap, &app.prefs, &app.theme),
            }
        });
        refresh_marks(&ui);
    });
    pg.on_sort(|table, column| {
        with_app(|app| {
            let sort = match table.as_str() {
                "matches" => &mut app.pages.match_sort,
                "entries" => &mut app.pages.entry_sort,
                "sessions" => &mut app.pages.session_sort,
                _ => &mut app.pages.team_sort,
            };
            // A new column starts descending for numbers and ascending for names.
            let text_column = match table.as_str() {
                "team" => column == 0,
                "sessions" => false,
                _ => column == 1,
            };
            *sort = if sort.0 == column {
                (column, !sort.1)
            } else {
                (column, !text_column)
            };
        });
        if let Some(ui) = window() {
            ui.global::<Pages>().invoke_changed(table);
        }
    });
    pg.on_select(|table, id| {
        with_app(|app| match table.as_str() {
            "matches" => app.pages.selected_match = id.to_string(),
            "entries" => app.pages.selected_entry = id.to_string(),
            "sessions" => app.pages.selected_session = id.to_string(),
            _ => app.pages.selected_person = id.to_string(),
        });
        if let Some(ui) = window() {
            ui.global::<Pages>().invoke_changed(table);
        }
    });
    pg.on_open_match(|id| {
        let Some(ui) = window() else { return };
        go_to(&ui, 1);
        ui.global::<Pages>().invoke_select("matches".into(), id);
    });
    pg.on_note(|field, value| {
        let result = with_app(|app| {
            let id = app.pages.selected_match.clone();
            let row = app
                .snap
                .as_ref()?
                .match_rows
                .iter()
                .find(|r| r.id == id)?
                .clone();
            let (mut note, mut tags, mut favorite) = (row.note, row.tags, row.favorite);
            match field.as_str() {
                "tags" => tags = value.to_string(),
                "note" => note = value.to_string(),
                _ => favorite = value == "true",
            }
            Some(app.store.as_mut()?.set_note(&id, &note, &tags, favorite))
        })
        .flatten();
        if let Some(r) = result
            && report(r).is_some()
        {
            changed_data();
        }
    });
    pg.on_action(|action| page_action(&action));
    ui.on_request_close(|| {
        with_app(|a| a.discord.shutdown());
        if let Some(ui) = window() {
            save_geometry(&ui);
            let _ = ui.hide();
        }
        let _ = slint::quit_event_loop();
    });
    let weak = ui.as_weak();
    ui.on_minimize(move || {
        if let Some(ui) = weak.upgrade() {
            use slint::winit_030::WinitWindowAccessor;
            ui.window().with_winit_window(|w| w.set_minimized(true));
        }
    });
    let weak = ui.as_weak();
    ui.on_maximize(move || {
        if let Some(ui) = weak.upgrade() {
            use slint::winit_030::WinitWindowAccessor;
            ui.window()
                .with_winit_window(|w| w.set_maximized(!w.is_maximized()));
        }
    });
}

fn parse_date(text: &str, format: &str) -> Option<NaiveDate> {
    let pattern = match format {
        "mdy" => "%m/%d/%Y",
        "iso" => "%Y-%m-%d",
        _ => "%d/%m/%Y",
    };
    NaiveDate::parse_from_str(text.trim(), pattern).ok()
}

fn open_path(path: &Path) {
    let _ = std::process::Command::new("explorer").arg(path).spawn();
}

fn settings_action(action: &str) {
    let l = current_lang();
    match action {
        "browse-folder" => {
            if let Some(folder) = rfd::FileDialog::new()
                .set_title(l.t("Choose the replay folder", "Escolha a pasta de replays"))
                .pick_folder()
            {
                set_setting("replay_folder", &folder.to_string_lossy());
            }
        }
        "open-replays" => {
            if let Some(f) = with_app(|a| a.config.replay_folder()) {
                open_path(&f);
            }
        }
        "rescan" => {
            let busy = with_app(|a| a.scanning).unwrap_or(true);
            if busy {
                snack(l.t(
                    "A replay check is running; try again in a moment",
                    "Uma verificação de replays está em andamento; tente em instantes",
                ));
                return;
            }
            if let Some(Some(r)) = with_app(|a| a.store.as_mut().map(|s| s.forget_replay_files())) {
                report(r);
            }
            scan();
        }
        "Export rewards" => export_rewards(),
        "Export ledger" => {
            if let Some(path) = rfd::FileDialog::new()
                .set_file_name("lootledger-export.json")
                .add_filter("JSON", &["json"])
                .add_filter("CSV", &["csv"])
                .save_file()
                && let Some(Some(r)) = with_app(|a| a.store.as_ref().map(|s| s.export(&path)))
                && report(r).is_some()
            {
                snack(l.t("Ledger exported", "Registro exportado"));
            }
        }
        "Create backup" => {
            let start = with_app(|a| a.folder.join("backups")).unwrap_or_default();
            let name = format!("lootledger-{}.sqlite", Local::now().format("%Y%m%d-%H%M%S"));
            if let Some(path) = rfd::FileDialog::new()
                .set_directory(start)
                .set_file_name(name)
                .add_filter(l.t("Ledger backup", "Backup do registro"), &["sqlite"])
                .save_file()
                && let Some(Some(r)) = with_app(|a| a.store.as_ref().map(|s| s.backup(&path)))
                && report(r).is_some()
            {
                snack(l.t("Backup created", "Backup criado"));
            }
        }
        "Restore backup" => {
            let start = with_app(|a| a.folder.join("backups")).unwrap_or_default();
            if let Some(path) = rfd::FileDialog::new()
                .set_directory(start)
                .add_filter(l.t("Ledger backup", "Backup do registro"), &["sqlite"])
                .pick_file()
                && confirm(
                    l.t("Restore this backup?", "Restaurar este backup?"),
                    l.t(
                        "Your current ledger is saved first, so you can go back.",
                        "Seu registro atual é salvo antes, para você poder voltar.",
                    ),
                )
                && let Some(Some(r)) = with_app(|a| a.store.as_mut().map(|s| s.restore(&path)))
                && let Some(safety) = report(r)
            {
                with_app(|a| a.snap_key = None);
                refresh(true);
                snack(format!(
                    "{} {}",
                    l.t(
                        "Backup restored. Your previous ledger was saved as",
                        "Backup restaurado. Seu registro anterior foi salvo em",
                    ),
                    safety.display()
                ));
            }
        }
        "Open data folder" => {
            if let Some(f) = with_app(|a| a.folder.clone()) {
                open_path(&f);
            }
        }
        "Export settings" => {
            if let Some(path) = rfd::FileDialog::new()
                .set_file_name("lootledger-settings.json")
                .add_filter(l.t("LootLedger settings", "Configurações do LootLedger"), &["json"])
                .save_file()
            {
                let payload = with_app(|a| {
                    json!({"app": "LootLedger", "settings": a.prefs.to_value(), "replays": {
                        "replay_folder": a.config.replay_folder().to_string_lossy(), "count_broken": a.config.count_broken(),
                        "scan_seconds": a.config.scan_seconds(), "auto_watch": a.config.auto_watch()}})
                });
                if let Some(p) = payload
                    && report(std::fs::write(
                        &path,
                        serde_json::to_vec_pretty(&p).unwrap_or_default(),
                    ))
                    .is_some()
                {
                    snack(l.t("Settings exported", "Configurações exportadas"));
                }
            }
        }
        "Import settings" => {
            if let Some(path) = rfd::FileDialog::new()
                .add_filter(l.t("LootLedger settings", "Configurações do LootLedger"), &["json"])
                .pick_file()
            {
                let data: Option<Value> = std::fs::read(&path)
                    .ok()
                    .and_then(|b| serde_json::from_slice(&b).ok());
                let Some(data) = data.filter(|d| d["app"] == "LootLedger") else {
                    snack(l.t(
                        "That file is not a LootLedger settings file.",
                        "Esse arquivo não é uma configuração do LootLedger.",
                    ));
                    return;
                };
                let result = with_app(|a| -> Result<(), String> {
                    for key in [
                        "replay_folder",
                        "count_broken",
                        "scan_seconds",
                        "auto_watch",
                    ] {
                        if let Some(v) = data["replays"].get(key) {
                            a.config.set(key, v.clone())?;
                        }
                    }
                    a.prefs = Prefs::from_value(&data["settings"]);
                    a.prefs
                        .save(&a.folder.join("ui-settings.json"))
                        .map_err(|e| e.to_string())
                });
                if report(result.unwrap_or(Ok(()))).is_some() {
                    let lang = current_lang();
                    if let Some(ui) = window() {
                        i18n::apply(&ui, lang);
                    }
                    apply_theme();
                    fill_settings();
                    with_app(|a| a.snap_key = None);
                    refresh(true);
                    snack(lang.t("Settings imported", "Configurações importadas"));
                }
            }
        }
        "sync-treasure-hours" => sync_treasure_hours(true),
        "Check for updates" => check_update(true),
        "Clear all data" => {
            if confirm(
                l.t(
                    "Clear all matches and openings?",
                    "Limpar todas as partidas e aberturas?",
                ),
                l.t(
                    "A backup is saved first. Replay files stay on your PC and are not read again until you choose Read all replays again.",
                    "Um backup é salvo antes. Os arquivos de replay continuam no PC e só serão lidos novamente se você escolher Ler todos os replays.",
                ),
            ) && let Some(Some(r)) = with_app(|a| a.store.as_mut().map(|s| s.clear()))
                && let Some(safety) = report(r)
            {
                with_app(|a| a.snap_key = None);
                refresh(true);
                snack(format!(
                    "{} {}",
                    l.t("All data cleared. Backup:", "Todos os dados foram limpos. Backup:"),
                    safety.display()
                ));
            }
        }
        "What's new" => {
            let rows = whats_new(l)
                .iter()
                .map(|line| vec![(format!("•  {line}"), 4)])
                .collect();
            info(
                &format!("{} {VERSION}", l.t("What's new in", "Novidades no")),
                rows,
                "",
            );
        }
        _ => {}
    }
}

/// A native yes/no question, modal to the window.
fn confirm(title: &str, text: &str) -> bool {
    rfd::MessageDialog::new()
        .set_title(title)
        .set_description(text)
        .set_buttons(rfd::MessageButtons::YesNo)
        .set_level(rfd::MessageLevel::Warning)
        .show()
        == rfd::MessageDialogResult::Yes
}

// ---- Command palette, shortcuts and startup dialogs --------------------------------------------

fn whats_new(lang: i18n::Lang) -> [&'static str; 3] {
    match lang {
        i18n::Lang::En => [
            "New Sessions tab (Ctrl+3): every play session with its length, matches, chests, pace, chart and teammates.",
            "New Rewards counter from treasure rolls: Overview tile, Rewards by type on Statistics, match/session details, and Export rewards in Settings.",
            "Your data still never leaves this PC; only the version check and the download go over the internet.",
        ],
        i18n::Lang::PtBr => [
            "Nova aba Sessões (Ctrl+3): todas as suas sessões com duração, partidas, baús, ritmo, gráfico e colegas.",
            "Novo contador de Recompensas das rolagens de tesouro: cartão na Visão geral, Recompensas por tipo em Estatísticas, detalhes de partida/sessão e Exportar recompensas em Configurações.",
            "Seus dados continuam sem sair deste PC; apenas a verificação de versão e o download usam a internet.",
        ],
    }
}

#[derive(Clone)]
enum Command {
    Page(i32),
    Pref(&'static str, &'static str),
    Toggle(&'static str),
    Scan,
    Shortcuts,
    Image(bool),
    Recap(bool),
    Match(String),
    Teammate(String),
}

fn commands(app: &App) -> Vec<(String, Command)> {
    let l = i18n::from_code(&app.prefs.language);
    let mut items: Vec<(String, Command)> = (0..7)
        .map(|i| {
            (
                format!("{} {}", l.t("Go to", "Ir para"), l.page_name(i)),
                Command::Page(i as i32),
            )
        })
        .collect();
    for (value, label) in [
        ("light", l.t("Light", "Claro")),
        ("dark", l.t("Dark", "Escuro")),
        ("system", l.t("System", "Sistema")),
    ] {
        items.push((
            format!("{}: {label}", l.t("Theme", "Tema")),
            Command::Pref("theme", value),
        ));
    }
    for (value, label) in [
        ("full", l.t("Full", "Completas")),
        ("reduced", l.t("Reduced", "Reduzidas")),
        ("off", l.t("Off", "Desativadas")),
    ] {
        items.push((
            format!("{}: {label}", l.t("Animations", "Animações")),
            Command::Pref("motion", value),
        ));
    }
    let p = &app.prefs;
    for (name, title, on) in [
        (
            "overlay",
            l.t("Pop-out counter", "Contador flutuante"),
            p.overlay,
        ),
        (
            "live_tracking",
            l.t("Track the current match", "Monitorar a partida atual"),
            p.live_tracking,
        ),
        (
            "colorblind",
            l.t(
                "Colourblind-safe chest colours",
                "Cores seguras para daltonismo",
            ),
            p.colorblind,
        ),
        (
            "sound",
            l.t("Sound when a match is counted", "Som ao contar partida"),
            p.sound,
        ),
        (
            "match_popup",
            l.t("Pop-up after each match", "Pop-up após cada partida"),
            p.match_popup,
        ),
    ] {
        let state = match (l, on) {
            (i18n::Lang::En, true) => "turn off",
            (i18n::Lang::En, false) => "turn on",
            (i18n::Lang::PtBr, true) => "desativar",
            (i18n::Lang::PtBr, false) => "ativar",
        };
        items.push((format!("{title}: {state}"), Command::Toggle(name)));
    }
    items.push((
        l.t("Check for new replays now", "Buscar novos replays agora")
            .into(),
        Command::Scan,
    ));
    items.push((
        l.t("Keyboard shortcuts", "Atalhos de teclado").into(),
        Command::Shortcuts,
    ));
    items.push((
        l.t("Copy summary image", "Copiar imagem resumo").into(),
        Command::Image(true),
    ));
    items.push((
        l.t("Save summary image…", "Salvar imagem resumo…").into(),
        Command::Image(false),
    ));
    items.push((
        l.t("Copy weekly recap", "Copiar resumo semanal").into(),
        Command::Recap(true),
    ));
    items.push((
        l.t("Save weekly recap…", "Salvar resumo semanal…").into(),
        Command::Recap(false),
    ));
    if let Some(snap) = &app.snap {
        for row in snap.match_rows.iter().take(200) {
            let tags = if row.tags.is_empty() {
                String::new()
            } else {
                format!(" · {}", row.tags)
            };
            items.push((
                format!(
                    "{}: {} · {} · {} {}{tags}",
                    l.t("Match", "Partida"),
                    l.mode_name(&row.mode),
                    p.when(row.when),
                    p.int(row.count),
                    l.chest_word(row.count)
                ),
                Command::Match(row.id.clone()),
            ));
        }
        for person in snap.board.iter().filter(|x| !x.me) {
            items.push((
                format!("{}: {}", l.t("Teammate", "Colega"), person.name),
                Command::Teammate(person.key.clone()),
            ));
        }
    }
    items
}

fn palette_filter(query: &str) {
    let Some(ui) = window() else { return };
    let words: Vec<String> = query
        .to_lowercase()
        .split_whitespace()
        .map(str::to_owned)
        .collect();
    let names = with_app(|app| {
        app.shown_commands = app
            .commands
            .iter()
            .enumerate()
            .filter(|(_, (name, _))| {
                let name = name.to_lowercase();
                words.iter().all(|w| name.contains(w.as_str()))
            })
            .map(|(i, _)| i)
            .collect();
        app.shown_commands
            .iter()
            .map(|&i| SharedString::from(app.commands[i].0.as_str()))
            .collect::<Vec<_>>()
    })
    .unwrap_or_default();
    ui.set_palette_items(cards::model(names));
    ui.set_palette_index(0);
}

fn open_palette() {
    let Some(ui) = window() else { return };
    with_app(|app| app.commands = commands(app));
    palette_filter("");
    ui.set_dialog(1);
}

fn go_to(ui: &AppWindow, page: i32) {
    ui.set_previous_page(ui.get_page());
    ui.set_page(page);
}

fn run_command(index: i32) {
    let Some(ui) = window() else { return };
    let command = with_app(|app| {
        app.shown_commands
            .get(index as usize)
            .and_then(|&i| app.commands.get(i))
            .map(|c| c.1.clone())
    })
    .flatten();
    ui.set_dialog(0);
    match command {
        Some(Command::Page(i)) => go_to(&ui, i),
        Some(Command::Pref(name, value)) => {
            let options: &[&str] = if name == "theme" {
                &["light", "dark", "system"]
            } else {
                &["full", "reduced", "off"]
            };
            set_setting(
                name,
                &options
                    .iter()
                    .position(|o| *o == value)
                    .unwrap_or(0)
                    .to_string(),
            );
        }
        Some(Command::Toggle(name)) => {
            let on =
                with_app(|a| a.prefs.to_value()[name].as_bool().unwrap_or(false)).unwrap_or(false);
            ui.global::<Settings>()
                .invoke_set(name.into(), if on { "false" } else { "true" }.into());
        }
        Some(Command::Scan) => scan(),
        Some(Command::Shortcuts) => show_shortcuts(),
        Some(Command::Image(copy)) => share_summary(copy),
        Some(Command::Recap(copy)) => share_image(true, copy),
        Some(Command::Match(id)) => {
            go_to(&ui, 1);
            ui.global::<Pages>()
                .invoke_select("matches".into(), id.into());
        }
        Some(Command::Teammate(key)) => {
            go_to(&ui, 5);
            ui.global::<Pages>()
                .invoke_select("team".into(), key.into());
        }
        None => {}
    }
}

fn info(title: &str, rows: Vec<Vec<(String, i32)>>, note: &str) {
    let Some(ui) = window() else { return };
    ui.set_info_title(title.into());
    ui.set_info_rows(cards::model(
        rows.into_iter()
            .map(|cells| TableRow {
                cells: cards::model(
                    cells
                        .into_iter()
                        .map(|(text, tone)| Cell {
                            text: text.into(),
                            tone,
                        })
                        .collect(),
                ),
                ..Default::default()
            })
            .collect(),
    ));
    ui.set_info_note(note.into());
    ui.set_info_action("".into());
    ui.set_dialog(2);
}

fn show_shortcuts() {
    let Some((add, undo, overlay, busy, l)) = with_app(|a| {
        (
            a.config.hotkey("hotkey_add"),
            a.config.hotkey("hotkey_undo"),
            a.prefs.hotkey_overlay.clone(),
            a.hotkeys_busy.clone(),
            i18n::from_code(&a.prefs.language),
        )
    }) else {
        return;
    };
    let mut rows = vec![
        vec![
            ("Ctrl+1 … Ctrl+7".to_owned(), 1),
            (l.t("Go to a page", "Ir para uma página").to_owned(), 0),
        ],
        vec![
            ("Ctrl+K".to_owned(), 1),
            (
                l.t(
                    "Command palette: pages, matches, teammates, settings",
                    "Paleta de comandos: páginas, partidas, colegas, configurações",
                )
                .to_owned(),
                0,
            ),
        ],
        vec![
            (l.t("? or F1", "? ou F1").to_owned(), 1),
            (l.t("This list", "Esta lista").to_owned(), 0),
        ],
        vec![
            ("Esc".to_owned(), 1),
            (l.t("Close a dialog", "Fechar diálogo").to_owned(), 0),
        ],
    ];
    for (name, text) in [
        (l.t("Add one chest", "Adicionar um baú"), add),
        (l.t("Undo last chest", "Desfazer último baú"), undo),
        (
            l.t("Show or hide the counter", "Mostrar ou ocultar contador"),
            overlay,
        ),
    ] {
        let state = if text.trim().is_empty() {
            l.t("off", "desativado")
        } else if busy.contains(&text) {
            l.t(
                "used by another app, so off",
                "usado por outro app, desativado",
            )
        } else {
            l.t("works in any app", "funciona em qualquer app")
        };
        rows.push(vec![
            (
                if text.is_empty() {
                    "–".to_owned()
                } else {
                    text
                },
                1,
            ),
            (format!("{name} · {state}"), 0),
        ]);
    }
    info(
        l.t("Keyboard shortcuts", "Atalhos de teclado"),
        rows,
        l.t(
            "Global shortcuts can be changed in Settings → Shortcuts. They only notice the keys; nothing is sent to Fortnite.",
            "Atalhos globais podem ser alterados em Configurações → Atalhos. Eles apenas detectam as teclas; nada é enviado ao Fortnite.",
        ),
    );
}

/// Onboarding the first time (a checklist), "What's new" after an update. Each is shown once.
fn startup_dialog() {
    let Some((seen, matches, checks, l)) = with_app(|app| {
        let seen = std::mem::replace(&mut app.prefs.seen_version, VERSION.to_owned());
        let _ = app.prefs.save(&app.folder.join("ui-settings.json"));
        (
            seen,
            app.snap.as_ref().map_or(0, |s| s.matches),
            health(app).checks,
            i18n::from_code(&app.prefs.language),
        )
    }) else {
        return;
    };
    if seen == VERSION {
        return;
    }
    if seen.is_empty() && matches == 0 {
        let mut rows = Vec::new();
        for (name, ok, fix) in checks {
            rows.push(vec![(
                format!("{}  {name}", if ok { "✓" } else { "!" }),
                if ok { 1 } else { 3 },
            )]);
            if !ok {
                rows.push(vec![(
                    format!("{}: {fix}", l.t("Fix it", "Como corrigir")),
                    0,
                )]);
            }
        }
        info(
            l.t("Set up in one step", "Configure em uma etapa"),
            rows,
            l.t(
                "Then just play. Finished matches are counted automatically; the Overview shows when a match is live.",
                "Depois é só jogar. Partidas terminadas são contadas automaticamente; a Visão geral mostra quando há uma partida ao vivo.",
            ),
        );
    } else {
        let rows = whats_new(l)
            .iter()
            .map(|line| vec![(format!("•  {line}"), 4)])
            .collect();
        info(
            &format!("{} {VERSION}", l.t("What's new in", "Novidades no")),
            rows,
            "",
        );
    }
}

/// Celebrate a reached goal or a new trophy once, inside LootLedger only (nothing leaves this PC).
fn announce() {
    let news = with_app(|app| {
        let lang = i18n::from_code(&app.prefs.language);
        let snap = app.snap.as_ref()?;
        let mut news = Vec::new();
        let unlocked: Vec<_> = lootledger_core::stats::achievements(snap)
            .into_iter()
            .filter(|a| a.unlocked)
            .collect();
        let fresh: Vec<_> = unlocked
            .iter()
            .filter(|a| !app.prefs.trophies.contains(&a.id))
            .collect();
        let mut changed = false;
        if !fresh.is_empty() {
            if !app.prefs.trophies.is_empty() || snap.matches == 0 {
                news.extend(fresh.iter().map(|a| {
                    let (title, _) = lang.achievement(&a.id, &a.title, &a.detail);
                    format!(
                        "{}: {title}",
                        lang.t("Trophy unlocked", "Troféu desbloqueado")
                    )
                }));
            }
            app.prefs.trophies = unlocked.iter().map(|a| a.id.clone()).collect(); // first run: marked silently
            changed = true;
        }
        let today = snap.today_date;
        let week = today.iso_week();
        for goal in lootledger_core::stats::goals(snap, app.prefs.goal_daily, app.prefs.goal_weekly)
        {
            let key = if goal.name == "Today" {
                format!("day:{today}")
            } else {
                format!("week:{}-{}", week.year(), week.week())
            };
            if goal.reached && !app.prefs.celebrated.contains(&key) {
                app.prefs.celebrated.push(key);
                let excess = app.prefs.celebrated.len().saturating_sub(20);
                app.prefs.celebrated.drain(..excess);
                let gname = lang.goal_name(goal.name).to_lowercase();
                news.push(format!(
                    "{}: {} {} {gname}",
                    lang.t("Goal reached", "Meta alcançada"),
                    goal.target,
                    lang.chest_word(goal.target)
                ));
                changed = true;
            }
        }
        if changed {
            let _ = app.prefs.save(&app.folder.join("ui-settings.json"));
        }
        (app.prefs.celebrate && !news.is_empty()).then(|| news.join(" · "))
    })
    .flatten();
    if let Some(text) = news {
        snack(text);
    }
}

// ---- Window geometry -----------------------------------------------------------------------------

fn restore_geometry(ui: &AppWindow) {
    // Stored in logical pixels, as LootLedger 0.7.1 (Qt) stores it.
    let (geometry, maximized) =
        with_app(|a| (a.prefs.window_geometry.clone(), a.prefs.window_maximized))
            .unwrap_or_default();
    if geometry.len() == 4 {
        let scale = ui.window().scale_factor();
        let (w, h) = (geometry[2].max(860) as f32, geometry[3].max(580) as f32);
        let (x, y) = (geometry[0] as f32 * scale, geometry[1] as f32 * scale);
        #[cfg(windows)]
        let (x, y) = {
            let (x, y) =
                native::on_screen(x as i32, y as i32, (w * scale) as i32, (h * scale) as i32);
            (x as f32, y as f32)
        };
        ui.window()
            .set_position(slint::PhysicalPosition::new(x as i32, y as i32));
        ui.window().set_size(slint::LogicalSize::new(w, h));
    }
    if maximized {
        use slint::winit_030::WinitWindowAccessor;
        ui.window().with_winit_window(|w| w.set_maximized(true));
    }
}

fn save_geometry(ui: &AppWindow) {
    use slint::winit_030::WinitWindowAccessor;
    let maximized = ui
        .window()
        .with_winit_window(|w| w.is_maximized())
        .unwrap_or(false);
    let scale = ui.window().scale_factor();
    let pos = ui.window().position().to_logical(scale);
    let size = ui.window().size().to_logical(scale);
    with_app(|app| {
        app.prefs.window_maximized = maximized;
        if !maximized && size.width > 0.0 {
            app.prefs.window_geometry = vec![
                pos.x.round() as i64,
                pos.y.round() as i64,
                size.width.round() as i64,
                size.height.round() as i64,
            ];
        }
        let _ = app.prefs.save(&app.folder.join("ui-settings.json"));
    });
}

// ---- Pop-out counter and global shortcuts ---------------------------------------------------------

fn toggle_overlay() {
    let on = with_app(|a| a.prefs.overlay).unwrap_or(false);
    set_setting("overlay", if on { "false" } else { "true" });
}

/// Show, place and style the counter window from the settings; hide it when it is off.
fn apply_overlay() {
    let Some((on, size, corner, geometry, opacity, through)) = with_app(|a| {
        let p = &a.prefs;
        (
            p.overlay,
            p.overlay_size.clone(),
            p.overlay_corner.clone(),
            p.overlay_geometry.clone(),
            p.overlay_opacity,
            p.overlay_click_through,
        )
    }) else {
        return;
    };
    if !on {
        OVERLAY.with(|o| {
            if let Some(w) = o.borrow().as_ref() {
                let _ = w.hide();
            }
        });
        return;
    }
    let created = OVERLAY.with(|o| o.borrow().is_some());
    if !created {
        let Ok(overlay) = Overlay::new() else { return };
        overlay.on_drag(|| {
            OVERLAY.with(|o| {
                if let Some(w) = o.borrow().as_ref() {
                    use slint::winit_030::WinitWindowAccessor;
                    let _ = w.window().with_winit_window(|win| win.drag_window());
                }
            });
        });
        // Save where it was put, once dragging pauses.
        let saver = Rc::new(Timer::default());
        use slint::winit_030::WinitWindowAccessor;
        overlay.window().on_winit_window_event(move |_, event| {
            if matches!(event, slint::winit_030::winit::event::WindowEvent::Moved(_)) {
                saver.start(
                    TimerMode::SingleShot,
                    Duration::from_millis(500),
                    save_overlay_position,
                );
            }
            slint::winit_030::EventResult::Propagate
        });
        OVERLAY.with(|o| *o.borrow_mut() = Some(overlay));
    }
    refresh_overlay();
    OVERLAY.with(|o| {
        let Some(w) = o.borrow().as_ref().map(|w| w.clone_strong()) else {
            return;
        };
        w.set_scale(match size.as_str() {
            "S" => 0.8,
            "L" => 1.3,
            _ => 1.0,
        });
        let _ = w.show();
        #[cfg(windows)]
        native::style_overlay(w.window(), opacity, through);
        let scale = w.window().scale_factor();
        let (ww, wh) = (
            w.window().size().width as i32,
            w.window().size().height as i32,
        );
        if corner == "free" {
            if geometry.len() == 4 {
                let (x, y) = (geometry[0] as f32 * scale, geometry[1] as f32 * scale);
                #[cfg(windows)]
                let (x, y) = {
                    let (x, y) = native::on_screen(x as i32, y as i32, ww, wh);
                    (x as f32, y as f32)
                };
                w.window()
                    .set_position(slint::PhysicalPosition::new(x as i32, y as i32));
            }
        } else {
            place_in_corner(w.window(), &corner, false);
        }
    });
}

/// Moves a window into a corner of its monitor (or the primary one), clear of a bottom taskbar.
fn place_in_corner(window: &slint::Window, corner: &str, primary: bool) {
    use slint::winit_030::WinitWindowAccessor;
    let (ww, wh) = (window.size().width as i32, window.size().height as i32);
    let area = window
        .with_winit_window(|win| {
            if primary {
                win.primary_monitor()
            } else {
                win.current_monitor()
            }
            .map(|m| (m.position(), m.size()))
        })
        .flatten();
    if let Some((pos, screen)) = area {
        let margin = (24.0 * window.scale_factor()) as i32;
        let x = if corner.ends_with("left") {
            pos.x + margin
        } else {
            pos.x + screen.width as i32 - ww - margin
        };
        let y = if corner.starts_with("top") {
            pos.y + margin
        } else {
            pos.y + screen.height as i32 - wh - margin * 3
        };
        window.set_position(slint::PhysicalPosition::new(x, y));
    }
}

fn save_overlay_position() {
    let position = OVERLAY.with(|o| {
        o.borrow().as_ref().map(|w| {
            let scale = w.window().scale_factor();
            let pos = w.window().position().to_logical(scale);
            let size = w.window().size().to_logical(scale);
            vec![
                pos.x.round() as i64,
                pos.y.round() as i64,
                size.width.round() as i64,
                size.height.round() as i64,
            ]
        })
    });
    if let Some(geometry) = position {
        with_app(|a| {
            if a.prefs.overlay_corner == "free" {
                a.prefs.overlay_geometry = geometry;
                let _ = a.prefs.save(&a.folder.join("ui-settings.json"));
            }
        });
    }
}

/// The counter's text: the live match while it runs, else the match just counted or the last one.
fn refresh_overlay() {
    let shown = OVERLAY.with(|o| o.borrow().is_some());
    if !shown {
        return;
    }
    let Some(ui) = window() else { return };
    let Some((heading, count, lines)) = with_app(|app| {
        let p = &app.prefs;
        let lang = i18n::from_code(&p.language);
        let snap = app.snap.as_ref()?;
        let view = live_view(app);
        if app.tracker.state == live::State::Live {
            let count = match (&view.live_count, view.locked) {
                (Some((n, _)), false) => p.int(*n),
                _ => "…".into(),
            };
            let lines = if view.locked {
                lang.t(
                    "Chests appear when the match ends",
                    "Os baús aparecem quando a partida termina",
                )
                .to_owned()
            } else {
                String::new()
            };
            return Some((
                format!(
                    "{} · {}",
                    lang.t("Live", "Ao vivo"),
                    prefs::elapsed(view.elapsed.unwrap_or(0.0))
                ),
                count,
                lines,
            ));
        }
        let row = view.ended.as_ref().or(snap.last.as_ref());
        let squad_match = row.map_or(0, |r| r.squad_total.max(r.count));
        let mut lines = vec![format!(
            "{}: {} · {}: {} · {}: {}",
            lang.t("Today", "Hoje"),
            p.int(snap.today),
            lang.t("Session", "Sessão"),
            p.int(snap.session),
            lang.t("Squad (match)", "Esquadrão (partida)"),
            p.int(squad_match)
        )];
        let mates: Vec<String> = row
            .and_then(|r| r.squad.as_ref())
            .into_iter()
            .flatten()
            .filter(|m| !m.me && m.total > 0)
            .take(3)
            .map(|m| format!("{} {}", m.name, p.int(m.total)))
            .collect();
        if p.overlay_teammates && !mates.is_empty() {
            lines.push(mates.join(" · "));
        }
        let summary = lootledger_core::stats::token_summary_with(snap, &app.treasure_hours);
        let pct = if summary.prob_squad >= 0.01 {
            format!("{:.1}%", summary.prob_squad * 100.0)
        } else if summary.prob_squad > 0.0 {
            format!("{:.2}%", summary.prob_squad * 100.0)
        } else {
            "0.0%".into()
        };
        lines.push(format!(
            "{}: {} · {}: {}",
            lang.t("Squad (total)", "Esquadrão (total)"),
            p.int(summary.total_chests_squad),
            lang.t("Token chance", "Chance de Token"),
            pct
        ));
        Some((
            if view.ended.is_some() {
                lang.t("This match", "Esta partida")
            } else {
                lang.t("Last match", "Última partida")
            }
            .to_owned(),
            row.map_or("–".to_owned(), |r| p.int(r.count)),
            lines.join("\n"),
        ))
    })
    .flatten() else {
        return;
    };
    let tokens = ui.global::<Tokens>();
    OVERLAY.with(|o| {
        if let Some(w) = o.borrow().as_ref() {
            w.set_heading(heading.into());
            w.set_count(count.into());
            w.set_lines(lines.into());
            w.set_surface(tokens.get_container_high());
            w.set_ink(tokens.get_on_surface());
            w.set_muted(tokens.get_on_surface_variant());
            w.set_accent(tokens.get_primary());
            w.set_radius(tokens.get_r_lg());
            w.set_pad(tokens.get_m());
        }
    });
}

fn refresh_discord() {
    with_app(|app| {
        let p = &app.prefs;
        let enabled = p.discord_rpc;
        let app_id = p.discord_app_id.trim().to_owned();
        let in_match = app.tracker.state == live::State::Live;
        let in_game = app.tracker.game_running();

        let activity = if !enabled
            || !prefs::valid_discord_app_id(&app_id)
            || (p.discord_only_in_game && !in_game)
        {
            None
        } else {
            let (last_match, today, squad_total, token_prob) = match app.snap.as_ref() {
                Some(snap) => {
                    let ended = app
                        .ended_id
                        .as_ref()
                        .and_then(|id| snap.match_rows.iter().find(|r| &r.id == id));
                    let last = ended.or(snap.last.as_ref()).map(|r| r.count);
                    let summary =
                        lootledger_core::stats::token_summary_with(snap, &app.treasure_hours);
                    (
                        last,
                        snap.today,
                        summary.total_chests_squad,
                        summary.prob_squad,
                    )
                }
                None => (None, 0, 0, 0.0),
            };
            Some(discord::format_activity(
                discord::StatusInput {
                    in_match,
                    in_game,
                    last_match,
                    today,
                    squad_total,
                    token_prob_squad: token_prob,
                    start_timestamp: app.tracker.started_unix(),
                },
                |n| p.int(n),
            ))
        };

        app.discord.update(discord::Desired {
            enabled,
            app_id,
            activity,
        });
    });
}

fn configure_hotkeys() {
    #[cfg(windows)]
    {
        let Some(keys) = with_app(|a| {
            vec![
                (1, a.config.hotkey("hotkey_add")),
                (2, a.config.hotkey("hotkey_undo")),
                (3, a.prefs.hotkey_overlay.clone()),
            ]
        }) else {
            return;
        };
        match native::register_hotkeys(&keys, on_hotkey) {
            Ok(busy) => {
                if !busy.is_empty() {
                    snack(format!(
                        "{}: {}",
                        current_lang().t(
                            "Shortcut already used by another app, so it is off",
                            "Atalho já usado por outro app, por isso está desativado",
                        ),
                        busy.join(", ")
                    ));
                }
                with_app(|a| a.hotkeys_busy = busy);
            }
            Err(e) => snack(e),
        }
    }
}

fn on_hotkey(id: i32) {
    match id {
        1 => page_action("add"),
        2 => page_action("undo"),
        3 => toggle_overlay(),
        _ => {}
    }
}

// ---- Summary image -------------------------------------------------------------------------------

fn share_summary(copy: bool) {
    share_image(false, copy);
}

/// The 1200×630 share card: all-time totals, or this week's recap (`week`). Drawn locally.
fn share_image(week: bool, copy: bool) {
    let Some(ui) = window() else { return };
    let l = current_lang();
    let Some((heading, total, caption, names, values, footer)) = with_app(|app| {
        let (snap, p) = (app.snap.as_ref()?, &app.prefs);
        let lang = i18n::from_code(&p.language);
        let player = snap
            .player
            .clone()
            .unwrap_or_else(|| lang.t("My chests", "Meus baús").into());
        if !week {
            let mate = snap.board.iter().find(|m| !m.me && !m.unranked);
            return Some((
                format!("LootLedger · {player}"),
                p.int(snap.all),
                lang.t("chests opened, all time", "baús abertos no total")
                    .to_owned(),
                [
                    lang.t("Today", "Hoje"),
                    lang.t("Best match", "Melhor partida"),
                    lang.t("Matches", "Partidas"),
                    lang.t("Top teammate", "Melhor colega"),
                ]
                .map(String::from)
                .to_vec(),
                vec![
                    p.int(snap.today),
                    p.int(snap.best.unwrap_or(0)),
                    p.int(snap.matches),
                    mate.map_or("–".into(), |m| format!("{} · {}", m.name, p.int(m.total))),
                ],
                format!(
                    "{} · {}",
                    lang.day_month_year(Local::now().date_naive(), true),
                    lang.t(
                        "counted from my Fortnite replays",
                        "contados dos meus replays do Fortnite",
                    )
                ),
            ));
        }
        let today = snap.today_date;
        let monday = today - chrono::Duration::days(today.weekday().num_days_from_monday() as i64);
        let rows: Vec<_> = snap
            .match_rows
            .iter()
            .filter(|r| r.mode != "Manual" && r.when.date_naive() >= monday)
            .cloned()
            .collect();
        let best = rows.iter().map(|r| r.count).max();
        let mate = lootledger_core::stats::board(&rows)
            .into_iter()
            .find(|m| !m.me && !m.unranked);
        let change = snap.week - snap.week_prev;
        let sign = if change > 0 {
            "+"
        } else if change < 0 {
            "−"
        } else {
            "±"
        };
        Some((
            format!(
                "{} {} · {player}",
                lang.t("LootLedger · week of", "LootLedger · semana de"),
                p.short_date(monday)
            ),
            p.int(snap.week),
            lang.t("chests opened this week", "baús abertos nesta semana")
                .to_owned(),
            [
                lang.t("Matches", "Partidas"),
                lang.t("Best match", "Melhor partida"),
                lang.t("vs last week", "vs semana passada"),
                lang.t("Top teammate", "Melhor colega"),
            ]
            .map(String::from)
            .to_vec(),
            vec![
                p.int(rows.len() as i64),
                best.map_or("–".into(), |b| p.int(b)),
                format!("{sign}{}", p.int(change.abs())),
                mate.map_or("–".into(), |m| format!("{} · {}", m.name, p.int(m.total))),
            ],
            format!(
                "{} – {} · {}",
                lang.day_month_year(monday, false),
                lang.day_month_year(today, true),
                lang.t(
                    "counted from my Fortnite replays",
                    "contados dos meus replays do Fortnite",
                )
            ),
        ))
    })
    .flatten() else {
        snack(l.t("Nothing to share yet", "Nada para compartilhar ainda"));
        return;
    };
    let tokens = ui.global::<Tokens>();
    OFFSCREEN.with(|o| o.set(true));
    let card = Summary::new();
    OFFSCREEN.with(|o| o.set(std::env::args().any(|a| a.starts_with("--snap="))));
    let Ok(card) = card else { return };
    card.set_surface(tokens.get_surface());
    card.set_card(tokens.get_primary_container());
    card.set_ink(tokens.get_on_primary_container());
    card.set_radius(tokens.get_r_xl());
    card.set_heading(heading.into());
    card.set_total(total.into());
    card.set_caption(caption.into());
    card.set_names(cards::model(
        names.into_iter().map(SharedString::from).collect(),
    ));
    card.set_values(cards::model(
        values.into_iter().map(SharedString::from).collect(),
    ));
    card.set_footer(footer.into());
    let _ = card.show();
    // One frame to render, then read the pixels back.
    Timer::single_shot(Duration::from_millis(150), move || {
        let l = current_lang();
        let pixels = card.window().take_snapshot();
        let _ = card.hide();
        let Ok(pixels) = pixels else {
            snack(l.t(
                "Could not draw the summary image",
                "Não foi possível gerar a imagem resumo",
            ));
            return;
        };
        let (w, h) = (pixels.width(), pixels.height());
        let rgba: Vec<u8> = pixels
            .as_slice()
            .iter()
            .flat_map(|p| [p.r, p.g, p.b, 255])
            .collect();
        if copy {
            #[cfg(windows)]
            if report(native::copy_image(w, h, &rgba)).is_some() {
                snack(if week {
                    l.t("Weekly recap copied", "Resumo semanal copiado")
                } else {
                    l.t("Summary image copied", "Imagem resumo copiada")
                });
            }
            return;
        }
        let fixed = {
            let flag = if week {
                "--recap-out="
            } else {
                "--summary-out="
            };
            std::env::args().find_map(|a| a.strip_prefix(flag).map(PathBuf::from))
        };
        if let Some(path) = fixed.or_else(|| {
            rfd::FileDialog::new()
                .set_file_name(if week {
                    "lootledger-week.png"
                } else {
                    "lootledger-summary.png"
                })
                .add_filter(l.t("PNG image", "Imagem PNG"), &["png"])
                .save_file()
        }) {
            let result = (|| -> Result<(), Box<dyn std::error::Error>> {
                let file = std::io::BufWriter::new(std::fs::File::create(&path)?);
                let mut encoder = png::Encoder::new(file, w, h);
                encoder.set_color(png::ColorType::Rgba);
                encoder.set_depth(png::BitDepth::Eight);
                encoder.write_header()?.write_image_data(&rgba)?;
                Ok(())
            })();
            if report(result).is_some() {
                snack(if week {
                    l.t("Weekly recap saved", "Resumo semanal salvo")
                } else {
                    l.t("Summary image saved", "Imagem resumo salva")
                });
            }
        }
    });
}

// ---- Updates ------------------------------------------------------------------------------------

/// Ask GitHub for a newer release and download it in the background. `manual` reports every outcome.
fn check_update(manual: bool) {
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    if manual {
        snack(current_lang().t("Checking for updates…", "Verificando atualizações…"));
    }
    std::thread::spawn(move || {
        let result = update::check(VERSION).and_then(|found| match found {
            Some(release) => update::download(&release, &exe).map(|_| Some(release.version)),
            None => Ok(None),
        });
        let _ = slint::invoke_from_event_loop(move || {
            let l = current_lang();
            match result {
                Ok(Some(version)) => {
                    info(
                        &format!("LootLedger {version} {}", l.t("is ready", "está pronto")),
                        vec![vec![(
                            l.t(
                                "It installs itself when you close LootLedger. Restart now to use it right away.",
                                "Ele é instalado automaticamente ao fechar o LootLedger. Reinicie agora para usar imediatamente.",
                            )
                            .to_owned(),
                            4,
                        )]],
                        l.t(
                            "Downloaded from this project's GitHub releases and checked against its published checksum.",
                            "Baixado dos lançamentos no GitHub deste projeto e verificado pelo checksum publicado.",
                        ),
                    );
                    if let Some(ui) = window() {
                        ui.set_info_action(l.t("Restart now", "Reiniciar agora").into());
                    }
                }
                Ok(None) if manual => snack(format!(
                    "{} ({VERSION})",
                    l.t(
                        "You have the latest version",
                        "Você já tem a versão mais recente"
                    )
                )),
                Err(e) if manual => snack(e),
                _ => {}
            }
        });
    });
}

/// Swap in a downloaded update; with `restart`, start the new version and close this one.
fn install_update(restart: bool) {
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    match update::apply(&exe) {
        Ok(true) if restart => {
            if let Some(ui) = window() {
                save_geometry(&ui);
            }
            if std::process::Command::new(&exe).spawn().is_ok() {
                let _ = slint::quit_event_loop();
            }
        }
        Ok(_) => {}
        Err(e) => snack(format!(
            "{}: {e}",
            current_lang().t(
                "Could not install the update",
                "Não foi possível instalar a atualização",
            )
        )),
    }
}

const TREASURE_HOURS_URL: &str =
    "https://raw.githubusercontent.com/LED-N/Fortnite-ChestCounter/main/content/content.json";

fn sync_treasure_hours(manual: bool) {
    let l = current_lang();
    if manual {
        snack(l.t(
            "Syncing Treasure Hours…",
            "Sincronizando Horários do Tesouro…",
        ));
    }
    std::thread::spawn(move || {
        let result = update::fetch_bytes(TREASURE_HOURS_URL).and_then(|bytes| {
            let text = std::str::from_utf8(&bytes).map_err(|_| {
                l.t(
                    "Treasure Hours file was not valid UTF-8.",
                    "O arquivo de Horários do Tesouro não é UTF-8 válido.",
                )
                .to_owned()
            })?;
            let windows = lootledger_core::stats::parse_ledn_treasure_hours(text)?;
            let prizes = lootledger_core::treasure::parse_ledn_prizes(text).ok();
            Ok((windows, prizes))
        });
        let _ = slint::invoke_from_event_loop(move || match result {
            Ok((windows, prizes)) => {
                let count = windows.len();
                let saved = with_app(|app| {
                    app.treasure.synced = windows;
                    if let Some(prizes) = prizes {
                        app.treasure.prizes = prizes;
                    }
                    app.treasure.last_synced = Some(chrono::Utc::now());
                    app.treasure_hours = app.treasure.all_windows();
                    app.treasure.save(&app.folder.join("treasure-hours.json"))
                });
                if let Some(r) = saved {
                    report(r);
                }
                fill_settings();
                refresh(true);
                if manual {
                    let msg = match current_lang() {
                        i18n::Lang::En => format!("Synced {count} Treasure Hours from GitHub"),
                        i18n::Lang::PtBr => {
                            format!("{count} Horários do Tesouro sincronizados do GitHub")
                        }
                    };
                    snack(msg);
                }
            }
            Err(e) if manual => snack(e),
            _ => {}
        });
    });
}

fn add_treasure_hour(date: &str, start: &str, end: &str, boost: &str) {
    let date_format = with_app(|a| a.prefs.date_format.clone()).unwrap_or_else(|| "dmy".into());
    match lootledger_core::stats::parse_custom_treasure_window(
        date,
        start,
        end,
        boost,
        &date_format,
    ) {
        Ok(win) => {
            let saved = with_app(|app| {
                app.treasure.custom.push(win);
                app.treasure_hours = app.treasure.all_windows();
                app.treasure.save(&app.folder.join("treasure-hours.json"))
            });
            if let Some(r) = saved {
                report(r);
            }
            fill_settings();
            refresh(true);
            snack(current_lang().t("Treasure Hour added", "Horário do Tesouro adicionado"));
        }
        Err(e) => snack(e),
    }
}

fn remove_treasure_hour(id: &str) {
    let saved = with_app(|app| {
        let before = app.treasure.custom.len();
        app.treasure.custom.retain(|w| w.id != id);
        if app.treasure.custom.len() == before {
            return None;
        }
        app.treasure_hours = app.treasure.all_windows();
        Some(app.treasure.save(&app.folder.join("treasure-hours.json")))
    })
    .flatten();
    if let Some(r) = saved {
        report(r);
        fill_settings();
        refresh(true);
        snack(current_lang().t(
            "Custom Treasure Hour removed",
            "Horário do Tesouro personalizado removido",
        ));
    }
}
