#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use slint::{ComponentHandle, Model, ModelRc, VecModel};
use std::{
    cell::RefCell,
    path::PathBuf,
    rc::Rc,
    time::{Duration, Instant},
};

#[cfg(windows)]
mod native;
mod watcher;
slint::include_modules!();

pub(crate) struct FrameCapture {
    start: Instant,
    frames: Vec<f64>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
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
        .select()?;
    let ui = AppWindow::new()?;
    let exercise = std::env::args().any(|a| a == "--exercise");
    let frames = exercise.then(|| {
        Rc::new(RefCell::new(FrameCapture {
            start: Instant::now(),
            frames: Vec::new(),
        }))
    });
    let data_folder = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let config = std::fs::read(data_folder.join("LootLedger/config.json"))
        .ok()
        .and_then(|b| serde_json::from_slice::<serde_json::Value>(&b).ok())
        .unwrap_or_default();
    let replay_folder = config["replay_folder"]
        .as_str()
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| data_folder.join("FortniteGame/Saved/Demos"));
    let weak = ui.as_weak();
    let _watch = if config["auto_watch"].as_bool().unwrap_or(true) {
        Some(watcher::ReplayWatch::start(replay_folder, move |status| {
            let _ = weak.upgrade_in_event_loop(move |ui| ui.set_live_status(status.into()));
        }))
    } else {
        None
    };
    let ledger = std::env::args()
        .find_map(|a| a.strip_prefix("--ledger=").map(PathBuf::from))
        .or_else(|| {
            std::env::var_os("LOCALAPPDATA")
                .map(|p| PathBuf::from(p).join("LootLedger/ledger.sqlite"))
        });
    let store = ledger
        .filter(|p| p.is_file())
        .map(lootledger_core::store::Store::read_only)
        .transpose()?;
    let store = Rc::new(store);
    if let Some(store) = store.as_ref() {
        let totals = store.totals(true)?;
        ui.set_counts(ModelRc::from(Rc::new(VecModel::from(vec![
            totals.chests.to_string().into(),
            "—".into(),
            "—".into(),
            store
                .history(true, 0, 1)?
                .first()
                .map(|m| m.total.to_string())
                .unwrap_or_else(|| "0".into())
                .into(),
        ]))));
        ui.set_summary(format!("Read-only preview · Matches: {} · Chests: {} · corrections included. Replay-parser and UI parity gates are still pending.", totals.matches, totals.chests).into());
    }
    let weak = ui.as_weak();
    let source = store.clone();
    ui.on_navigate(move |page| {
        if let Some(ui) = weak.upgrade()
            && let Some(store) = source.as_ref()
            && let Err(error) = populate(&ui, store, page)
        {
            ui.set_summary(format!("Could not read ledger: {error}").into());
        }
    });
    #[cfg(windows)]
    native::install(&ui, frames.clone());
    let weak = ui.as_weak();
    ui.on_request_close(move || {
        if let Some(ui) = weak.upgrade() {
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
    let cards = Rc::new(VecModel::from(vec![
        "All time".into(),
        "Today".into(),
        "This week".into(),
        "Last match".into(),
    ]));
    ui.set_cards(ModelRc::from(cards.clone()));
    let weak = ui.as_weak();
    ui.on_reorder(move |from, to| {
        if from != to
            && from >= 0
            && to >= 0
            && (from as usize) < cards.row_count()
            && (to as usize) < cards.row_count()
        {
            let value = cards.row_data(from as usize).unwrap();
            cards.remove(from as usize);
            cards.insert(to as usize, value);
            if let Some(ui) = weak.upgrade() {
                let model = ui.get_counts();
                let mut values: Vec<_> = (0..model.row_count())
                    .filter_map(|i| model.row_data(i))
                    .collect();
                let value = values.remove(from as usize);
                values.insert(to as usize, value);
                ui.set_counts(ModelRc::from(Rc::new(VecModel::from(values))));
            }
        }
    });
    let timer = Rc::new(slint::Timer::default());
    let weak = ui.as_weak();
    ui.on_animate_chart(move || {
        if let Some(ui) = weak.upgrade()
            && !ui.global::<Tokens>().get_motion()
        {
            ui.set_progress(1.0);
            return;
        }
        let start = Instant::now();
        let weak = weak.clone();
        let stop = Rc::downgrade(&timer);
        timer.start(
            slint::TimerMode::Repeated,
            Duration::from_millis(16),
            move || {
                if let Some(ui) = weak.upgrade() {
                    let t = (start.elapsed().as_secs_f32() / 0.5).min(1.0);
                    ui.set_progress(1.0 - (1.0 - t).powi(3));
                    if t >= 1.0
                        && let Some(timer) = stop.upgrade()
                    {
                        timer.stop();
                    }
                } else if let Some(timer) = stop.upgrade() {
                    timer.stop();
                }
            },
        );
    });
    if let Some(seconds) = std::env::args().find_map(|s| {
        s.strip_prefix("--quit-after=")
            .and_then(|s| s.parse::<u64>().ok())
    }) {
        slint::Timer::single_shot(Duration::from_secs(seconds), || {
            let _ = slint::quit_event_loop();
        });
    }
    let _qa_timer = std::env::args()
        .find_map(|s| s.strip_prefix("--qa=").map(PathBuf::from))
        .and_then(|dir| qa(&ui, dir));
    let exercise_timer = slint::Timer::default();
    if exercise {
        let weak = ui.as_weak();
        exercise_timer.start(
            slint::TimerMode::Repeated,
            Duration::from_millis(400),
            move || {
                if let Some(ui) = weak.upgrade() {
                    ui.invoke_animate_chart();
                    ui.invoke_reorder(0, 1);
                }
            },
        );
    }
    ui.run()?;
    if let Some(frames) = frames
        && let Some(path) =
            std::env::args().find_map(|a| a.strip_prefix("--frame-report=").map(PathBuf::from))
    {
        {
            let capture = frames.borrow();
            let mut intervals: Vec<_> = capture
                .frames
                .windows(2)
                .filter(|p| p[0] >= 600.0 && p[1] <= 4800.0)
                .map(|p| p[1] - p[0])
                .collect();
            intervals.sort_by(f64::total_cmp);
            let percentile = |fraction: f64| {
                intervals
                    .get(((intervals.len().saturating_sub(1)) as f64 * fraction) as usize)
                    .copied()
            };
            let report = serde_json::json!({"renderer": if cfg!(feature="femtovg") {"femtovg"} else {"software"},
                "workload": "synthetic bar animation and scripted model reorder every 400ms",
                "redraw_events_ms": capture.frames, "median_redraw_interval_ms": percentile(0.5), "p95_redraw_interval_ms": percentile(0.95),
                "measured_interval_count": intervals.len(), "actual_present_times_measured": false,
                "physical_drag_tested": false});
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(path, serde_json::to_vec_pretty(&report)?)?;
        }
    }
    Ok(())
}

fn populate(
    ui: &AppWindow,
    store: &lootledger_core::store::Store,
    page: i32,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut rows = Vec::new();
    let headers: [&str; 4] = if page == 2 {
        ["When", "Type", "Amount", "Status"]
    } else if page == 4 {
        ["Player", "Chests", "Searched", "Broken"]
    } else {
        ["When", "Mode", "Chests", "Tags / note"]
    };
    if page == 2 {
        for e in store.entries(0, 200)? {
            rows.push(LedgerRow {
                first: e.created.into(),
                second: e.chest_type.into(),
                third: e.amount.to_string().into(),
                fourth: e.status.into(),
            });
        }
    } else if page == 4 {
        let mut people = std::collections::BTreeMap::<String, (String, u64, u64)>::new();
        for m in store.history(true, 0, u32::MAX)? {
            if let Some(meta) = m.meta
                && let Some(players) = meta["players"].as_array()
            {
                {
                    for player in players {
                        if player["me"].as_bool() == Some(true) {
                            continue;
                        }
                        let key = player["key"].as_str().unwrap_or("unknown").to_owned();
                        let name = player["name"].as_str().unwrap_or("Teammate").to_owned();
                        let person = people.entry(key).or_insert((name, 0, 0));
                        if let Some(counts) = player["counts"].as_object() {
                            for count in counts.values() {
                                person.1 += count["opened"].as_u64().unwrap_or(0);
                                person.2 += count["broken"].as_u64().unwrap_or(0);
                            }
                        }
                    }
                }
            }
        }
        for (_, (name, opened, broken)) in people {
            rows.push(LedgerRow {
                first: name.into(),
                second: (opened + broken).to_string().into(),
                third: opened.to_string().into(),
                fourth: broken.to_string().into(),
            });
        }
    } else if page == 1 {
        for m in store.history(true, 0, 200)? {
            rows.push(LedgerRow {
                first: m.started.into(),
                second: m
                    .meta
                    .as_ref()
                    .and_then(|v| v["mode"].as_str())
                    .unwrap_or("Manual")
                    .into(),
                third: m.total.to_string().into(),
                fourth: format!("{} {}", m.tags, m.note).trim().into(),
            });
        }
    }
    ui.set_headers(ModelRc::from(Rc::new(VecModel::from(
        headers.map(slint::SharedString::from).to_vec(),
    ))));
    ui.set_rows(ModelRc::from(Rc::new(VecModel::from(rows))));
    Ok(())
}

fn qa(ui: &AppWindow, dir: PathBuf) -> Option<Rc<slint::Timer>> {
    use std::io::Write;
    let weak = ui.as_weak();
    let timer = Rc::new(slint::Timer::default());
    let stop = Rc::downgrade(&timer);
    let index = Rc::new(std::cell::Cell::new(0));
    let mut failure = None;
    if let Err(e) = std::fs::create_dir_all(&dir) {
        failure = Some(e.to_string());
    }
    if let Some(e) = failure {
        eprintln!("Screenshot directory: {e}");
        return None;
    }
    timer.start(
        slint::TimerMode::Repeated,
        Duration::from_millis(400),
        move || {
            if let Some(ui) = weak.upgrade() {
                let n = index.get();
                if n > 0 {
                    let shot = n - 1;
                    let name = format!(
                        "page-{}-{}-{}.ppm",
                        shot % 6,
                        if (shot / 6) % 2 == 0 { "dark" } else { "light" },
                        shot / 12
                    );
                    let result = (|| -> Result<(), Box<dyn std::error::Error>> {
                        let pixels = ui.window().take_snapshot()?;
                        let mut file =
                            std::io::BufWriter::new(std::fs::File::create(dir.join(name))?);
                        write!(file, "P6\n{} {}\n255\n", pixels.width(), pixels.height())?;
                        for p in pixels.as_slice() {
                            file.write_all(&[p.r, p.g, p.b])?;
                        }
                        file.flush()?;
                        Ok(())
                    })();
                    if let Err(e) = result {
                        eprintln!("Screenshot failed: {e}");
                        if let Some(timer) = stop.upgrade() {
                            timer.stop();
                        }
                        let _ = slint::quit_event_loop();
                        return;
                    }
                }
                if n >= 36 {
                    if let Some(timer) = stop.upgrade() {
                        timer.stop();
                    }
                    let _ = slint::quit_event_loop();
                    return;
                }
                let sizes = [(900, 600), (1240, 860), (2560, 1080)];
                let (w, h) = sizes[(n / 12) as usize];
                ui.window()
                    .set_size(slint::LogicalSize::new(w as f32, h as f32));
                ui.global::<Tokens>().set_dark((n / 6) % 2 == 0);
                ui.global::<Tokens>().set_motion(false);
                ui.set_page(n % 6);
                index.set(n + 1);
            } else {
                if let Some(timer) = stop.upgrade() {
                    timer.stop();
                }
            }
        },
    );
    Some(timer)
}
