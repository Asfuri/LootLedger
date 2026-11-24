//! Dashboard cards from the statistics snapshot: a port of lootledger/panels.py. Text, order and wording
//! follow the 0.7.1 cards; shapes for charts are computed here in a 0..100 view box.

use crate::i18n::{self, Lang};
use crate::prefs::Prefs;
use crate::theme::Theme;
use crate::{
    BarRow, CardData, Cell, ChartPoint, Check, Fact, HeatCell, RingData, Slice, TableRow, Trophy,
};
use chrono::{Datelike, Duration, Local, NaiveDate};
use lootledger_core::stats::{self, Grain, MatchRow, Snapshot};
use slint::{Color, ModelRc, SharedString, VecModel};
use std::f64::consts::PI;
use std::rc::Rc;

pub fn model<T: Clone + 'static>(items: Vec<T>) -> ModelRc<T> {
    ModelRc::from(Rc::new(VecModel::from(items)))
}

fn s(text: impl Into<SharedString>) -> SharedString {
    text.into()
}

pub fn color(rgb: [f64; 3]) -> Color {
    Color::from_rgb_u8(
        (rgb[0].clamp(0.0, 1.0) * 255.0).round() as u8,
        (rgb[1].clamp(0.0, 1.0) * 255.0).round() as u8,
        (rgb[2].clamp(0.0, 1.0) * 255.0).round() as u8,
    )
}

fn cell(text: impl Into<SharedString>, tone: i32) -> Cell {
    Cell {
        text: text.into(),
        tone,
    }
}

fn row(cells: Vec<Cell>) -> TableRow {
    TableRow {
        cells: model(cells),
        dot: Color::default(),
        has_dot: false,
    }
}

pub const STAT_TITLES: &[(&str, &str, &str)] = &[
    ("all", "All time", "all_inclusive"),
    ("today", "Today", "today"),
    ("week", "This week", "date_range"),
    ("month", "This month", "calendar_month"),
    ("last", "Last match", "sports_esports"),
    ("avg", "Chests per match", "query_stats"),
    ("best", "Best match", "trophy"),
    ("per_hour", "Chests per hour", "schedule"),
    ("playtime", "Time played", "timer"),
    ("matches", "Matches read", "list_alt"),
    ("session", "This session", "play_circle"),
    ("token", "Token chance", "military_tech"),
];
pub const TITLES: &[(&str, &str, &str)] = &[
    ("live", "Session overview", "play_circle"),
    ("trend", "Chests over time", "trending_up"),
    ("token", "Token drop chance", "military_tech"),
    ("types", "By chest type", "category"),
    ("modes", "By game mode", "tune"),
    ("heat", "When you open chests", "grid_on"),
    ("records", "Records", "workspace_premium"),
    ("teammates", "You and your team", "groups"),
    ("broken", "Searched vs broken open", "broken_image"),
    ("health", "Setup and replay health", "health_and_safety"),
    ("sessions", "Sessions", "timelapse"),
    ("goals", "Goals", "flag"),
    ("trophies", "Trophies", "trophy"),
    ("compare", "Compare periods", "compare_arrows"),
    ("stats", "Match stats", "bar_chart"),
    ("treasures", "Treasure rewards", "celebration"),
    ("seen_prizes", "Seen prizes nearby", "visibility"),
    ("rewards", "Rewards", "military_tech"),
    ("reward_types", "Rewards by type", "military_tech"),
];
pub const STATS_ORDER: &[&str] = &[
    "health",
    "trend",
    "token",
    "treasures",
    "seen_prizes",
    "types",
    "reward_types",
    "modes",
    "heat",
    "records",
    "stats",
    "sessions",
    "goals",
    "teammates",
    "broken",
    "compare",
    "trophies",
    "stat:all",
    "stat:today",
    "stat:week",
    "stat:month",
    "stat:last",
    "stat:avg",
    "stat:best",
    "stat:per_hour",
    "stat:playtime",
    "stat:matches",
    "stat:session",
    "stat:token",
    "rewards",
];

pub fn title_of(id: &str, lang: Lang) -> (&'static str, &'static str) {
    let icon = match id.strip_prefix("stat:") {
        Some(key) => STAT_TITLES.iter().find(|t| t.0 == key).map_or("", |t| t.2),
        None => TITLES.iter().find(|t| t.0 == id).map_or("", |t| t.2),
    };
    (lang.card_title(id), icon)
}

/// What the cards need besides the snapshot.
pub struct Context<'a> {
    pub snap: &'a Snapshot,
    pub prefs: &'a Prefs,
    pub theme: &'a Theme,
    pub live: LiveView,
    pub health: Option<Health>,
    pub trend: (i64, Grain),
    pub compare: [NaiveDate; 4],
    pub treasure_hours: &'a [stats::TreasureWindow],
    pub synced_prizes: &'a [lootledger_core::treasure::PrizeDef],
}

#[derive(Clone, Default)]
pub struct LiveView {
    pub state: &'static str,
    pub elapsed: Option<f64>,
    pub locked: bool,
    pub live_count: Option<(i64, String)>,
    pub ended: Option<MatchRow>,
    pub pop_id: i32,
}

#[derive(Clone)]
pub struct Health {
    pub checks: Vec<(String, bool, String)>,
    pub replays: usize,
    pub newest: Option<f64>,
    pub read: i64,
    pub unreadable: i64,
    pub watching: String,
    pub last_scan: Option<chrono::DateTime<Local>>,
}

fn lang_of(ctx: &Context) -> Lang {
    i18n::from_code(&ctx.prefs.language)
}

fn blank(id: &str, kind: &str, span: i32, ctx: &Context) -> CardData {
    let (title, icon) = title_of(id, lang_of(ctx));
    CardData {
        id: s(id),
        kind: s(kind),
        title: s(title),
        icon: s(crate::icons::glyph(icon)),
        span,
        live_dot: color(ctx.theme.color("outline")),
        pop_color: color(ctx.theme.color("on_primary_container")),
        dates: model(vec![]),
        ..Default::default()
    }
}

/// A sparkline (line and area) through these values, 4% padding top and bottom.
pub fn spark(values: &[f64]) -> (String, String) {
    if values.is_empty() {
        return (String::new(), String::new());
    }
    let peak = values.iter().cloned().fold(0.0f64, f64::max).max(1e-9);
    let n = values.len();
    let pts: Vec<(f64, f64)> = values
        .iter()
        .enumerate()
        .map(|(i, v)| {
            (
                if n == 1 {
                    50.0
                } else {
                    i as f64 / (n - 1) as f64 * 100.0
                },
                96.0 - v / peak * 92.0,
            )
        })
        .collect();
    let mut line = format!("M {:.2} {:.2}", pts[0].0, pts[0].1);
    if n == 1 {
        line = format!("M 0 {:.2} L 100 {:.2}", pts[0].1, pts[0].1);
    }
    for p in &pts[1..] {
        line.push_str(&format!(" L {:.2} {:.2}", p.0, p.1));
    }
    let (first, last) = if n == 1 {
        (0.0, 100.0)
    } else {
        (pts[0].0, pts[n - 1].0)
    };
    let area = format!("{line} L {last:.2} 100 L {first:.2} 100 Z");
    (line, area)
}

/// Chart line through bar centres; smooth uses Catmull-Rom curves. Returns (line, area).
pub fn series_path(values: &[f64], smooth: bool) -> (String, String) {
    if values.is_empty() {
        return (String::new(), String::new());
    }
    let peak = values.iter().cloned().fold(0.0f64, f64::max).max(1e-9);
    let n = values.len();
    let pts: Vec<(f64, f64)> = values
        .iter()
        .enumerate()
        .map(|(i, v)| ((i as f64 + 0.5) / n as f64 * 100.0, 100.0 - v / peak * 96.0))
        .collect();
    let mut line = format!("M {:.2} {:.2}", pts[0].0, pts[0].1);
    for i in 1..n {
        if smooth {
            let p0 = if i >= 2 { pts[i - 2] } else { pts[i - 1] };
            let (p1, p2) = (pts[i - 1], pts[i]);
            let p3 = pts[(i + 1).min(n - 1)];
            let c1 = (
                p1.0 + (p2.0 - p0.0) / 6.0,
                (p1.1 + (p2.1 - p0.1) / 6.0).clamp(0.0, 100.0),
            );
            let c2 = (
                p2.0 - (p3.0 - p1.0) / 6.0,
                (p2.1 - (p3.1 - p1.1) / 6.0).clamp(0.0, 100.0),
            );
            line.push_str(&format!(
                " C {:.2} {:.2} {:.2} {:.2} {:.2} {:.2}",
                c1.0, c1.1, c2.0, c2.1, p2.0, p2.1
            ));
        } else {
            line.push_str(&format!(" L {:.2} {:.2}", pts[i].0, pts[i].1));
        }
    }
    let area = format!("{line} L {:.2} 100 L {:.2} 100 Z", pts[n - 1].0, pts[0].0);
    (line, area)
}

/// An arc of a circle centred at 50,50, from fraction `start` for `sweep` of a turn, clockwise from the top.
pub fn arc(radius: f64, start: f64, sweep: f64) -> String {
    let point = |f: f64| {
        (
            50.0 + radius * (2.0 * PI * f).sin(),
            50.0 - radius * (2.0 * PI * f).cos(),
        )
    };
    if sweep >= 0.9999 {
        let (a, b) = (point(start), point(start + 0.5));
        return format!(
            "M {:.3} {:.3} A {r} {r} 0 1 1 {:.3} {:.3} A {r} {r} 0 1 1 {:.3} {:.3}",
            a.0,
            a.1,
            b.0,
            b.1,
            a.0,
            a.1,
            r = radius
        );
    }
    let (a, b) = (point(start), point(start + sweep));
    format!(
        "M {:.3} {:.3} A {r} {r} 0 {} 1 {:.3} {:.3}",
        a.0,
        a.1,
        if sweep > 0.5 { 1 } else { 0 },
        b.0,
        b.1,
        r = radius
    )
}

fn clock(seconds: f64) -> String {
    let s = seconds.max(0.0) as i64;
    format!("{}:{:02}", s / 60, s % 60)
}

fn last_days_tips(ctx: &Context, count: i64) -> Vec<SharedString> {
    let today = ctx.snap.today_date;
    (0..count)
        .map(|i| s(ctx.prefs.short_date(today - Duration::days(count - 1 - i))))
        .collect()
}

/// (value, decimals, detail, delta, spark values, spark tips) for one stat tile, as stat_value in panels.py.
pub enum Value {
    Number(f64, usize),
    Text(String),
}

/// What a stat tile shows: value, detail, change versus before, sparkline values and their tooltips.
pub type StatValue = (
    Value,
    String,
    Option<(i64, i64, &'static str)>,
    Vec<f64>,
    Vec<SharedString>,
);

pub fn stat_value(key: &str, ctx: &Context) -> StatValue {
    let (snap, p) = (ctx.snap, ctx.prefs);
    let lang = lang_of(ctx);
    let fourteen: Vec<f64> = stats::last_days(snap, 14)
        .into_iter()
        .map(|v| v as f64)
        .collect();
    let recent: Vec<f64> = snap.recent_totals.iter().map(|v| *v as f64).collect();
    let recent_tips: Vec<SharedString> = (0..recent.len())
        .map(|i| {
            s(match lang {
                Lang::En => format!("Match {} of your last {}", i + 1, recent.len()),
                Lang::PtBr => format!("Partida {} das últimas {}", i + 1, recent.len()),
            })
        })
        .collect();
    let day_tips = || last_days_tips(ctx, 14);
    let tips_for = |values: &[f64], tips: Vec<SharedString>| -> Vec<SharedString> {
        values
            .iter()
            .zip(tips)
            .map(|(v, t)| s(format!("{t} · {}", p.number(*v, 0))))
            .collect()
    };
    match key {
        "all" => {
            let detail = if snap.broken > 0 {
                format!(
                    "{} {}",
                    p.int(snap.broken),
                    lang.t("broken open", "quebrados")
                )
            } else {
                lang.t("searched chests", "baús abertos").into()
            };
            let tips = tips_for(&fourteen, day_tips());
            (
                Value::Number(snap.all as f64, 0),
                detail,
                None,
                fourteen,
                tips,
            )
        }
        "today" => {
            let tips = tips_for(&fourteen, day_tips());
            (
                Value::Number(snap.today as f64, 0),
                String::new(),
                Some((
                    snap.today,
                    snap.today_prev,
                    lang.t("vs yesterday", "em relação a ontem"),
                )),
                fourteen,
                tips,
            )
        }
        "week" => {
            let tips = tips_for(&fourteen, day_tips());
            (
                Value::Number(snap.week as f64, 0),
                String::new(),
                Some((
                    snap.week,
                    snap.week_prev,
                    lang.t(
                        "vs the same days last week",
                        "vs mesmos dias da semana passada",
                    ),
                )),
                fourteen,
                tips,
            )
        }
        "month" => {
            let tips = tips_for(&fourteen, day_tips());
            (
                Value::Number(snap.month as f64, 0),
                String::new(),
                Some((
                    snap.month,
                    snap.month_prev,
                    lang.t(
                        "vs the same days last month",
                        "vs mesmos dias do mês passado",
                    ),
                )),
                fourteen,
                tips,
            )
        }
        "session" => {
            let tips = tips_for(&fourteen, day_tips());
            (
                Value::Number(snap.session as f64, 0),
                lang.t("since LootLedger opened", "desde que o LootLedger abriu")
                    .into(),
                None,
                fourteen,
                tips,
            )
        }
        "matches" => {
            let tips = tips_for(&recent, recent_tips);
            (
                Value::Number(snap.matches as f64, 0),
                lang.t("replays read", "replays lidos").into(),
                None,
                recent,
                tips,
            )
        }
        "last" => match &snap.last {
            None => (
                Value::Text("–".into()),
                lang.t("No match read yet", "Nenhuma partida lida ainda")
                    .into(),
                None,
                vec![],
                vec![],
            ),
            Some(last) => {
                let place = last
                    .placement
                    .map(|n| format!(" · #{n}"))
                    .unwrap_or_default();
                let tips = tips_for(&recent, recent_tips);
                (
                    Value::Number(last.count as f64, 0),
                    format!("{}{place}", lang.mode_name(&last.mode)),
                    None,
                    recent,
                    tips,
                )
            }
        },
        _ if snap.matches == 0 => (
            Value::Text("–".into()),
            lang.t("Read a match to see this", "Leia uma partida para ver isto")
                .into(),
            None,
            vec![],
            vec![],
        ),
        "avg" => {
            let tips = tips_for(&recent, recent_tips);
            (
                Value::Number(snap.avg.unwrap_or(0.0), 1),
                format!(
                    "{} {}",
                    lang.t("median", "mediana"),
                    p.number(snap.median.unwrap_or(0.0), 1)
                ),
                None,
                recent,
                tips,
            )
        }
        "best" => {
            let tips = tips_for(&recent, recent_tips);
            (
                Value::Number(snap.best.unwrap_or(0) as f64, 0),
                format!(
                    "{} {}",
                    lang.t("lowest", "menor"),
                    p.int(snap.worst.unwrap_or(0))
                ),
                None,
                recent,
                tips,
            )
        }
        "per_hour" => {
            let tips = tips_for(&recent, recent_tips);
            (
                Value::Number(snap.per_hour, 1),
                format!("{} {}", lang.t("over", "em"), p.duration(snap.playtime)),
                None,
                recent,
                tips,
            )
        }
        "playtime" => {
            let tips = tips_for(&recent, recent_tips);
            (
                Value::Text(p.duration(snap.playtime)),
                lang.matches_count(snap.matches),
                None,
                recent,
                tips,
            )
        }
        "token" => {
            let summary = stats::token_summary(snap);
            let val_text = if summary.prob_squad >= 0.01 {
                format!("{:.1}%", summary.prob_squad * 100.0)
            } else if summary.prob_squad > 0.0 {
                format!("{:.2}%", summary.prob_squad * 100.0)
            } else {
                "0.0%".into()
            };
            let (target_pct, target_chests) = if summary.prob_squad < 0.50 {
                ("50%", 95310i64)
            } else if summary.prob_squad < 0.90 {
                ("90%", 316500i64)
            } else {
                ("99%", 633200i64)
            };
            let remaining = (target_chests - summary.total_chests_squad).max(0);
            let detail = if summary.total_chests_squad > 0 {
                match lang {
                    Lang::En => format!(
                        "Squad: {} chests · Next: {target_pct} (~{} to go)",
                        p.int(summary.total_chests_squad),
                        p.int(remaining)
                    ),
                    Lang::PtBr => format!(
                        "Esquadrão: {} baús · Próx.: {target_pct} (faltam ~{})",
                        p.int(summary.total_chests_squad),
                        p.int(remaining)
                    ),
                }
            } else {
                match lang {
                    Lang::En => format!(
                        "Next milestone: {target_pct} at ~{} chests",
                        p.int(target_chests)
                    ),
                    Lang::PtBr => format!(
                        "Próxima meta: {target_pct} em ~{} baús",
                        p.int(target_chests)
                    ),
                }
            };
            let spark_vals: Vec<f64> = summary.recent_cum_probs.clone();
            let tips: Vec<SharedString> = summary
                .days
                .iter()
                .rev()
                .take(spark_vals.len())
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .map(|d| {
                    s(format!(
                        "{} · {:.2}% ({} {})",
                        p.short_date(d.date),
                        d.cum_prob_squad * 100.0,
                        p.int(d.cum_chests_squad),
                        lang.chest_word(d.cum_chests_squad),
                    ))
                })
                .collect();
            (Value::Text(val_text), detail, None, spark_vals, tips)
        }
        _ => (Value::Text("–".into()), String::new(), None, vec![], vec![]),
    }
}

fn stat_card(key: &str, span: i32, ctx: &Context) -> CardData {
    let mut card = blank(&format!("stat:{key}"), "stat", span, ctx);
    let lang = lang_of(ctx);
    let (value, detail, delta, sparkv, tips) = stat_value(key, ctx);
    card.value = s(match value {
        Value::Number(v, d) => ctx.prefs.number(v, d),
        Value::Text(t) => t,
    });
    card.detail = s(detail);
    if let Some((current, previous, text)) = delta {
        let diff = current - previous;
        card.delta = s(match diff.signum() {
            1 => format!("▲ +{} {text}", ctx.prefs.int(diff.abs())),
            -1 => format!("▼ −{} {text}", ctx.prefs.int(diff.abs())),
            _ => format!("{} {text}", lang.t("No change", "Sem mudança")),
        });
        card.delta_tone = if diff > 0 { 2 } else { 0 };
    }
    let (line, area) = spark(&sparkv);
    card.spark_line = s(line);
    card.spark_area = s(area);
    card.spark_tips = model(tips);
    card
}

const RARITY: [&str; 3] = ["Relic chest", "Buried chest", "Rare chest"];

fn secs(seconds: f64) -> Duration {
    Duration::milliseconds((seconds * 1000.0).round() as i64)
}

fn fact(value: impl Into<SharedString>, label: &str) -> Fact {
    Fact {
        value: value.into(),
        label: label.into(),
    }
}

/// The session overview: your current play session (matches less than 30 minutes apart) or, when you are
/// not playing, the last one. The dot and its text still say what the game is doing right now. Only the
/// essentials are here (chests, a row of four numbers, the best match and a small chart); the Statistics
/// and Teammates pages have the rest.
fn live_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("live", "live", span, ctx);
    card.accent = true;
    let lang = lang_of(ctx);
    let (t, p, live) = (ctx.theme, ctx.prefs, &ctx.live);
    let (mut text, role) = match live.state {
        "waiting" => (
            lang.t("Waiting for a match", "Aguardando partida")
                .to_owned(),
            "secondary",
        ),
        "live" => (lang.t("Live", "Ao vivo").to_owned(), "error"),
        "saving" => (
            lang.t(
                "Match over · reading the replay…",
                "Partida encerrada · lendo o replay…",
            )
            .to_owned(),
            "tertiary",
        ),
        "ended" => (
            lang.t("Match counted", "Partida contada").to_owned(),
            "primary",
        ),
        _ => (
            lang.t(
                "Idle · Fortnite isn't running",
                "Inativo · Fortnite não está aberto",
            )
            .to_owned(),
            "outline",
        ),
    };
    card.live_dot = color(t.color(role));
    card.live_pulse = live.state == "live";
    if live.state == "live"
        && let Some(e) = live.elapsed
    {
        text += &format!(" · {}", clock(e));
    }
    card.detail = s(text);

    let now = Local::now();
    let in_game = matches!(live.state, "live" | "saving");
    let mut rows = stats::latest_session(&ctx.snap.match_rows);
    let last_end = rows.last().map(|r| r.when + secs(r.seconds));
    let recent = last_end.is_some_and(|e| now - e <= Duration::minutes(stats::SESSION_GAP_MINUTES));
    if in_game && !recent {
        rows.clear(); // the match in progress starts a new session
    }
    let active = in_game || (recent && matches!(live.state, "waiting" | "ended"));
    let playing = match (live.state, live.elapsed) {
        ("live", Some(e)) => e,
        _ => 0.0,
    };

    let chests: i64 = rows.iter().map(|r| r.count).sum();
    let in_matches: f64 = rows.iter().map(|r| r.seconds).sum();
    let start = rows
        .first()
        .map(|r| r.when)
        .or_else(|| active.then(|| now - secs(playing)));
    let end = if active { Some(now) } else { last_end };
    let in_session = match (start, end) {
        (Some(a), Some(b)) => ((b - a).num_milliseconds() as f64 / 1000.0).max(in_matches),
        _ => 0.0,
    };

    if rows.is_empty() && !active {
        card.value = s("–");
        card.note = s(lang.t(
            "Play a match and your session shows up here. Finished matches are added automatically. Fortnite must have Record Replays on.",
            "Jogue uma partida e sua sessão aparecerá aqui. Partidas encerradas entram automaticamente. O Fortnite precisa estar com Gravar Replays ativado.",
        ));
    } else {
        card.value = s(p.int(chests));
        card.caption = s(if active {
            lang.t("chests this session", "baús nesta sessão")
                .to_owned()
        } else {
            let ended = last_end.unwrap_or(now);
            let when = if ended.date_naive() == now.date_naive() {
                p.clock_time(ended)
            } else {
                format!(
                    "{} {}",
                    p.short_date(ended.date_naive()),
                    p.clock_time(ended)
                )
            };
            match lang {
                Lang::En => format!("chests in your last session (ended {when})"),
                Lang::PtBr => format!("baús na última sessão (encerrou às {when})"),
            }
        });
        let mut facts = vec![
            fact(
                p.int(rows.len() as i64),
                if rows.len() == 1 {
                    lang.t("match", "partida")
                } else {
                    lang.t("matches", "partidas")
                },
            ),
            fact(p.duration(in_session), lang.t("in session", "na sessão")),
        ];
        if rows.is_empty() {
            card.note = s(if live.state == "live" {
                lang.t(
                    "Your first match is in progress. It is counted when it ends.",
                    "Sua primeira partida está em andamento. Será contada quando terminar.",
                )
            } else {
                lang.t("Reading your first match…", "Lendo sua primeira partida…")
            });
        } else {
            facts.push(fact(
                p.number(chests as f64 / rows.len() as f64, 1),
                lang.t("chests per match", "baús por partida"),
            ));
            if in_matches > 0.0 {
                facts.push(fact(
                    p.number(chests as f64 * 3600.0 / in_matches, 0),
                    lang.t("chests per hour", "baús por hora"),
                ));
            }
            let won = rows
                .iter()
                .flat_map(|r| &r.rewards)
                .filter(|r| r.by == "me" && r.recognized())
                .count() as i64;
            if won > 0 {
                facts.push(fact(
                    p.int(won),
                    if won == 1 {
                        lang.t("reward", "recompensa")
                    } else {
                        lang.t("rewards", "recompensas")
                    },
                ));
            }
        }
        card.facts = model(facts);
        if rows.len() > 1 {
            if let Some(best) = rows
                .iter()
                .copied()
                .reduce(|a, b| if b.count > a.count { b } else { a })
            {
                let place = best
                    .placement
                    .map(|n| format!(" · #{n}"))
                    .unwrap_or_default();
                card.note = s(format!(
                    "{}: {} {}{place} · {}",
                    lang.t("Best match", "Melhor partida"),
                    p.int(best.count),
                    lang.chest_word(best.count),
                    lang.mode_name(&best.mode),
                ));
            }
            let values: Vec<f64> = rows.iter().map(|r| r.count as f64).collect();
            let (line, area) = spark(&values);
            card.spark_line = s(line);
            card.spark_area = s(area);
            card.spark_label = s(lang.t("Chests per match", "Baús por partida"));
            card.spark_tips = model(
                rows.iter()
                    .enumerate()
                    .map(|(i, r)| {
                        s(format!(
                            "{} {} · {} · {} {}",
                            lang.t("Match", "Partida"),
                            i + 1,
                            lang.mode_name(&r.mode),
                            p.int(r.count),
                            lang.chest_word(r.count),
                        ))
                    })
                    .collect::<Vec<_>>(),
            );
        }
    }
    // The chest count of the match that was just counted pops up beside the session total.
    if live.state == "ended"
        && let Some(row) = &live.ended
    {
        let rare = RARITY.iter().find(|n| row.types.get(n) > 0);
        card.pop = s(format!("+{}", row.count));
        card.pop_color = color(rare.map_or(t.color("on_primary_container"), |n| t.type_color(n)));
        card.pop_id = live.pop_id;
    }
    card
}

const GRAINS: [Grain; 3] = [Grain::Day, Grain::Week, Grain::Month];

fn trend_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("trend", "trend", span, ctx);
    let lang = lang_of(ctx);
    let (snap, p) = (ctx.snap, ctx.prefs);
    let (days, grain) = ctx.trend;
    card.range_index = stats_range_index(days);
    card.grain_index = GRAINS.iter().position(|g| *g == grain).unwrap_or(0) as i32;
    card.style_index = ["bar", "line", "smooth", "area"]
        .iter()
        .position(|x| *x == p.chart_style)
        .unwrap_or(0) as i32;
    let points = stats::trend(snap, grain, days, false);
    let played = stats::trend(snap, grain, days, true);
    let label = |day: NaiveDate| match grain {
        Grain::Day => p.short_date(day),
        Grain::Week => format!("{} {}", lang.t("Week of", "Semana de"), p.short_date(day)),
        Grain::Month => lang.month_year(day, false),
    };
    let peak = points.iter().map(|x| x.1).max().unwrap_or(0).max(1) as f64;
    let chart: Vec<ChartPoint> = points
        .iter()
        .enumerate()
        .map(|(i, (day, value))| {
            let matches = played.get(i).map_or(0, |x| x.1);
            let mut tip = format!(
                "{} · {} {}\n{}",
                label(*day),
                p.int(*value),
                lang.chest_word(*value),
                lang.matches_count(matches)
            );
            if i > 0 {
                let change = value - points[i - 1].1;
                let sign = if change > 0 {
                    "+"
                } else if change < 0 {
                    "−"
                } else {
                    "±"
                };
                let prev = match (lang, grain) {
                    (Lang::En, Grain::Day) => "vs the previous day",
                    (Lang::En, Grain::Week) => "vs the previous week",
                    (Lang::En, Grain::Month) => "vs the previous month",
                    (Lang::PtBr, Grain::Day) => "vs dia anterior",
                    (Lang::PtBr, Grain::Week) => "vs semana anterior",
                    (Lang::PtBr, Grain::Month) => "vs mês anterior",
                };
                tip += &format!("\n{sign}{} {prev}", p.int(change.abs()));
            }
            ChartPoint {
                label: s(label(*day)),
                value: (*value as f64 / peak) as f32,
                tip: s(tip),
            }
        })
        .collect();
    let values: Vec<f64> = points.iter().map(|x| x.1 as f64).collect();
    let (line, area) = series_path(&values, p.chart_style == "smooth");
    card.line = s(line);
    card.area = s(area);
    // About five axis labels, evenly spread, that never overlap.
    let n = points.len();
    let shown = n.min(5);
    let axis: Vec<SharedString> = (0..shown)
        .map(|k| {
            let i = if shown <= 1 {
                0
            } else {
                k * (n - 1) / (shown - 1)
            };
            let day = points[i].0;
            s(match grain {
                Grain::Month => lang.month_year(day, true),
                _ => p.short_date(day),
            })
        })
        .collect();
    card.axis = model(axis);
    let total: i64 = values.iter().map(|v| *v as i64).sum();
    card.empty = s(if total == 0 {
        lang.t(
            "No chests in this range yet",
            "Nenhum baú neste período ainda",
        )
    } else {
        ""
    });
    card.points = model(chart);
    card.caption = s(format!(
        "{} {} {}",
        p.int(total),
        lang.chest_word(total),
        lang.t("in this range", "neste período")
    ));
    card
}

fn token_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("token", "token", span, ctx);
    let lang = lang_of(ctx);
    let (snap, p) = (ctx.snap, ctx.prefs);
    card.style_index = ["bar", "line", "smooth", "area"]
        .iter()
        .position(|x| *x == p.chart_style)
        .unwrap_or(0) as i32;

    let summary = stats::token_summary_with(snap, ctx.treasure_hours);

    let format_pct = |prob: f64| {
        if prob >= 0.01 {
            format!("{:.1}%", prob * 100.0)
        } else if prob > 0.0 {
            format!("{:.2}%", prob * 100.0)
        } else {
            "0.0%".into()
        }
    };

    card.value = s(format_pct(summary.prob_squad));

    let (target_pct, target_chests) = if summary.prob_squad < 0.50 {
        ("50%", 95310i64)
    } else if summary.prob_squad < 0.90 {
        ("90%", 316500i64)
    } else {
        ("99%", 633200i64)
    };
    let remaining = (target_chests - summary.total_chests_squad).max(0);
    let milestone_msg = if remaining > 0 {
        match lang {
            Lang::En => format!(
                "Next milestone: {target_pct} chance at ~{} chests (~{} to go)",
                p.int(target_chests),
                p.int(remaining)
            ),
            Lang::PtBr => format!(
                "Próxima meta: {target_pct} de chance em ~{} baús (faltam ~{})",
                p.int(target_chests),
                p.int(remaining)
            ),
        }
    } else {
        match lang {
            Lang::En => format!(
                "Surpassed {target_pct} milestone! Total squad chests: {}",
                p.int(summary.total_chests_squad)
            ),
            Lang::PtBr => format!(
                "Meta de {target_pct} ultrapassada! Total do esquadrão: {} baús",
                p.int(summary.total_chests_squad)
            ),
        }
    };

    card.caption = s(milestone_msg);

    if summary.total_chests_squad > 0 {
        card.detail = s(match lang {
            Lang::En => format!(
                "Squad: {} ({} chests) · You: {} ({}) · Next: {target_pct} (~{} to go)",
                format_pct(summary.prob_squad),
                p.int(summary.total_chests_squad),
                format_pct(summary.prob_me),
                p.int(summary.total_chests_me),
                p.int(remaining),
            ),
            Lang::PtBr => format!(
                "Esquadrão: {} ({} baús) · Você: {} ({}) · Próx.: {target_pct} (faltam ~{})",
                format_pct(summary.prob_squad),
                p.int(summary.total_chests_squad),
                format_pct(summary.prob_me),
                p.int(summary.total_chests_me),
                p.int(remaining),
            ),
        });
    } else {
        card.detail = s(match lang {
            Lang::En => format!(
                "Squad: 0 chests · Next milestone: {target_pct} chance at ~{} chests",
                p.int(target_chests)
            ),
            Lang::PtBr => format!(
                "Esquadrão: 0 baús · Próxima meta: {target_pct} de chance em ~{} baús",
                p.int(target_chests)
            ),
        });
    }

    let now_local = Local::now();
    let th_note = if let Some((boost, end_opt, is_manual)) =
        stats::active_treasure_window(&now_local, ctx.treasure_hours)
    {
        let denom = (stats::BASE_TOKEN_DENOM / boost).round() as i64;
        let kind = if is_manual {
            lang.t("Manual", "Manual")
        } else {
            lang.t("Active", "Ativo")
        };
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
            Lang::En => format!(
                "⚡ {kind} Treasure Hour LIVE ({boost:.2}× boost{until} · 1 in {}){}",
                p.int(denom),
                if summary.treasure_hour_chests > 0 {
                    format!(" · {} boosted chests", p.int(summary.treasure_hour_chests))
                } else {
                    String::new()
                }
            ),
            Lang::PtBr => format!(
                "⚡ Hora do Poder ({kind}) AO VIVO ({boost:.2}× bônus{until} · 1 em {}){}",
                p.int(denom),
                if summary.treasure_hour_chests > 0 {
                    format!(" · {} baús com bônus", p.int(summary.treasure_hour_chests))
                } else {
                    String::new()
                }
            ),
        }
    } else if summary.treasure_hour_chests > 0 {
        match lang {
            Lang::En => format!(
                "Base odds: 1 in 137,500 · {} chests opened during Treasure Hours (Settings → Treasure Hours).",
                p.int(summary.treasure_hour_chests)
            ),
            Lang::PtBr => format!(
                "Chance base: 1 em {} · {} baús abertos em Horas do Poder (Configurações → Horas do Poder).",
                p.int(137_500),
                p.int(summary.treasure_hour_chests)
            ),
        }
    } else {
        match lang {
            Lang::En => "Base odds: 1 in 137,500 per chest · Configure boost windows in Settings → Treasure Hours.".to_owned(),
            Lang::PtBr => format!(
                "Chance base: 1 em {} por baú · Configure horários em Configurações → Horas do Poder.",
                p.int(137_500)
            ),
        }
    };

    if summary.days.is_empty() {
        card.empty = s(match lang {
            Lang::En => format!(
                "No matches read yet · Next milestone: {target_pct} at ~{} chests",
                p.int(target_chests)
            ),
            Lang::PtBr => format!(
                "Nenhuma partida lida ainda · Próxima meta: {target_pct} em ~{} baús",
                p.int(target_chests)
            ),
        });
        card.note = s(th_note);
        return card;
    }

    let peak = summary
        .days
        .iter()
        .map(|d| d.cum_prob_squad * 100.0)
        .fold(0.0f64, f64::max)
        .max(1e-6);

    let chart: Vec<ChartPoint> = summary
        .days
        .iter()
        .map(|d| {
            let label = p.short_date(d.date);
            let mut tip = match lang {
                Lang::En => format!(
                    "{} · {:.2}% chance\nSquad: {} chests (+{} today)\nYou: {} chests (+{} today)",
                    label,
                    d.cum_prob_squad * 100.0,
                    p.int(d.cum_chests_squad),
                    p.int(d.chests_squad),
                    p.int(d.cum_chests_me),
                    p.int(d.chests_me),
                ),
                Lang::PtBr => format!(
                    "{} · {:.2}% de chance\nEsquadrão: {} baús (+{} no dia)\nVocê: {} baús (+{} no dia)",
                    label,
                    d.cum_prob_squad * 100.0,
                    p.int(d.cum_chests_squad),
                    p.int(d.chests_squad),
                    p.int(d.cum_chests_me),
                    p.int(d.chests_me),
                ),
            };
            if d.had_treasure_hour {
                tip += lang.t(
                    "\n⚡ Includes Treasure Hour (boosted odds!)",
                    "\n⚡ Inclui Hora do Poder (chance aumentada!)",
                );
            }
            ChartPoint {
                label: s(label),
                value: ((d.cum_prob_squad * 100.0) / peak) as f32,
                tip: s(tip),
            }
        })
        .collect();

    let values: Vec<f64> = summary
        .days
        .iter()
        .map(|d| d.cum_prob_squad * 100.0)
        .collect();
    let (line, area) = series_path(&values, p.chart_style == "smooth");
    card.line = s(line);
    card.area = s(area);

    let n = summary.days.len();
    let shown = n.min(5);
    let axis: Vec<SharedString> = (0..shown)
        .map(|k| {
            let i = if shown <= 1 {
                0
            } else {
                k * (n - 1) / (shown - 1)
            };
            s(p.short_date(summary.days[i].date))
        })
        .collect();
    card.axis = model(axis);
    card.points = model(chart);
    card.note = s(th_note);
    card
}

pub fn stats_range_index(days: i64) -> i32 {
    crate::prefs::RANGES
        .iter()
        .position(|d| *d == days)
        .unwrap_or(1) as i32
}

fn types_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("types", "types", span, ctx);
    let lang = lang_of(ctx);
    let (snap, p, t) = (ctx.snap, ctx.prefs, ctx.theme);
    let types = snap.types.most_common();
    let total: i64 = types.iter().map(|x| x.1).sum::<i64>().max(1);
    let shown: Vec<&(String, i64)> = types.iter().filter(|x| x.1 > 0).collect();
    let gap = if shown.len() > 1 { 0.006 } else { 0.0 };
    let mut start = 0.0;
    let mut slices = Vec::new();
    for (name, value) in &shown {
        let sweep = *value as f64 / total as f64;
        slices.push(Slice {
            start: start as f32,
            sweep: sweep as f32,
            color: color(t.type_color(name)),
            tip: s(format!(
                "{} · {} ({}%)",
                lang.chest_type(name),
                p.int(*value),
                (sweep * 100.0).round()
            )),
            path: s(arc(40.0, start + gap / 2.0, (sweep - gap).max(0.002))),
        });
        start += sweep;
    }
    card.slices = model(slices);
    card.center = s(p.int(snap.all));
    card.caption = s(lang.chest_word(snap.all));
    let mut names: Vec<String> = types.iter().map(|x| x.0.clone()).collect();
    let mut extra: Vec<String> = snap
        .team_types
        .keys()
        .filter(|k| snap.types.get(k) == 0 && !names.iter().any(|n| n == k))
        .map(str::to_owned)
        .collect();
    extra.sort();
    names.extend(extra);
    let mut rows = vec![row(vec![
        cell(lang.t("Type", "Tipo"), 3),
        cell(lang.t("You", "Você"), 3),
        cell(lang.t("Teammates*", "Equipe*"), 3),
    ])];
    for name in &names {
        let mut r = row(vec![
            cell(lang.chest_type(name), 4),
            cell(p.int(snap.types.get(name)), 1),
            cell(p.int(snap.team_types.get(name)), 0),
        ]);
        r.dot = color(t.type_color(name));
        r.has_dot = true;
        rows.push(r);
    }
    if names.is_empty() {
        rows.push(row(vec![cell(
            lang.t("No chests yet", "Nenhum baú ainda"),
            0,
        )]));
    } else {
        rows.push(row(vec![
            cell("Total", 3),
            cell(p.int(snap.all), 1),
            cell(p.int(snap.team_total), 0),
        ]));
    }
    card.table = model(rows);
    card.note = s(lang.t(
        "*Only chests your replays recorded. Details on the Teammates page.",
        "*Somente baús registrados nos seus replays. Detalhes na aba Equipe.",
    ));
    card
}

fn bars(rows: Vec<(String, i64, String)>) -> ModelRc<BarRow> {
    let peak = rows.iter().map(|r| r.1).max().unwrap_or(0).max(1) as f32;
    model(
        rows.into_iter()
            .map(|(label, value, text)| BarRow {
                label: s(label),
                fraction: value as f32 / peak,
                text: s(text),
                ..Default::default()
            })
            .collect(),
    )
}

fn modes_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("modes", "bars", span, ctx);
    let lang = lang_of(ctx);
    let mut modes = ctx.snap.modes.clone();
    modes.sort_by_key(|m| std::cmp::Reverse(m.1.chests));
    modes.truncate(8);
    if modes.is_empty() {
        card.lines = model(vec![cell(
            lang.t(
                "Read a match to see your modes",
                "Leia uma partida para ver seus modos",
            ),
            0,
        )]);
    }
    card.bars = bars(
        modes
            .into_iter()
            .map(|(name, m)| {
                (
                    lang.mode_name(&name),
                    m.chests,
                    format!(
                        "{} · {}",
                        ctx.prefs.int(m.chests),
                        lang.matches_count(m.matches)
                    ),
                )
            })
            .collect(),
    );
    card
}

/// The reward types in a counter with their counts, most first (ties in the order the game lists them).
fn reward_counts(counts: &stats::Counter) -> Vec<(&'static str, i64)> {
    let mut found: Vec<(&'static str, i64)> = lootledger_core::model::reward_types()
        .map(|name| (name, counts.get(name)))
        .filter(|(_, n)| *n > 0)
        .collect();
    found.sort_by_key(|(_, n)| std::cmp::Reverse(*n));
    found
}

/// The Overview tile: the prizes your replays recorded from treasure rolls.
fn rewards_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("rewards", "stat", span, ctx);
    let lang = lang_of(ctx);
    let (snap, p) = (ctx.snap, ctx.prefs);
    card.value = s(p.int(snap.rewards.total()));
    // Only the top three types here; the Statistics page lists them all.
    let found = reward_counts(&snap.rewards);
    let mut parts: Vec<String> = found
        .iter()
        .take(3)
        .map(|(name, n)| format!("{} {}", lang.reward_category(name), p.int(*n)))
        .collect();
    if found.len() > 3 {
        parts.push(match lang {
            Lang::En => format!("+{} more", found.len() - 3),
            Lang::PtBr => format!("+{} mais", found.len() - 3),
        });
    }
    card.detail = s(if parts.is_empty() {
        lang.t("None recorded yet", "Nenhuma registrada ainda")
            .to_owned()
    } else {
        parts.join(" · ")
    });
    let mut extra = Vec::new();
    if snap.team_rewards.total() > 0 {
        extra.push(format!(
            "{} {}",
            lang.t("Teammates got", "Equipe ganhou"),
            p.int(snap.team_rewards.total())
        ));
    }
    if snap.unrecognized_rewards > 0 {
        extra.push(format!(
            "{} {}",
            p.int(snap.unrecognized_rewards),
            lang.t("not recognized", "não reconhecidas")
        ));
    }
    card.delta = s(extra.join(" · "));
    let today = snap.today_date;
    let days: Vec<(chrono::NaiveDate, f64)> = (0..14)
        .map(|i| {
            let day = today - Duration::days(13 - i);
            (day, snap.reward_days.get(&day).copied().unwrap_or(0) as f64)
        })
        .collect();
    let values: Vec<f64> = days.iter().map(|d| d.1).collect();
    let (line, area) = spark(&values);
    card.spark_line = s(line);
    card.spark_area = s(area);
    card.spark_tips = model(
        days.iter()
            .map(|(day, n)| s(format!("{} · {}", p.short_date(*day), p.number(*n, 0))))
            .collect::<Vec<_>>(),
    );
    card
}

/// The Statistics card: every reward type with how many you and your teammates got.
fn reward_types_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("reward_types", "bars", span, ctx);
    let lang = lang_of(ctx);
    let (snap, p) = (ctx.snap, ctx.prefs);
    let rows: Vec<(String, i64, String)> = lootledger_core::model::reward_types()
        .filter_map(|name| {
            let (mine, team) = (snap.rewards.get(name), snap.team_rewards.get(name));
            (mine + team > 0).then(|| {
                (
                    lang.reward_category(name),
                    mine + team,
                    format!(
                        "{} {} · {} {}",
                        lang.t("You", "Você"),
                        p.int(mine),
                        lang.t("Teammates", "Equipe"),
                        p.int(team)
                    ),
                )
            })
        })
        .collect();
    if rows.is_empty() {
        card.lines = model(vec![cell(
            lang.t(
                "No rewards recorded yet. They come from treasure rolls during the Treasure Hunt event.",
                "Nenhuma recompensa registrada ainda. Elas vêm das rolagens de tesouro durante o evento Caça ao Tesouro.",
            ),
            0,
        )]);
    }
    card.bars = bars(rows);
    let mut note = String::from(lang.t(
        "*Only prizes your replays recorded. A prize won far from you usually isn't, and Gizmos may not be saved at all, so these are minimums.",
        "*Apenas prêmios registrados nos seus replays. Prêmios ganhos longe de você normalmente não aparecem, e Gizmos podem não ser salvos — portanto são mínimos.",
    ));
    if snap.unrecognized_rewards > 0 {
        note += &match lang {
            Lang::En => format!(
                " {} prizes were not recognized and are left out of the types.",
                p.int(snap.unrecognized_rewards)
            ),
            Lang::PtBr => format!(
                " {} prêmios não foram reconhecidos e ficaram fora dos tipos.",
                p.int(snap.unrecognized_rewards)
            ),
        };
    }
    if snap.no_reward_data > 0 {
        note += &match lang {
            Lang::En => format!(
                " {} older matches were read before rewards were recorded.",
                p.int(snap.no_reward_data)
            ),
            Lang::PtBr => format!(
                " {} partidas antigas foram lidas antes do registro de recompensas.",
                p.int(snap.no_reward_data)
            ),
        };
    }
    card.note = s(note);
    card
}

fn heat_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("heat", "heat", span, ctx);
    let lang = lang_of(ctx);
    let (snap, p) = (ctx.snap, ctx.prefs);
    let peak = snap
        .heat
        .iter()
        .flatten()
        .max()
        .copied()
        .unwrap_or(0)
        .max(1) as f32;
    let mut cells = Vec::with_capacity(168);
    for (d, day) in snap.heat.iter().enumerate() {
        for (h, value) in day.iter().enumerate() {
            let matches = snap.heat_matches[d][h];
            cells.push(HeatCell {
                alpha: *value as f32 / peak,
                tip: s(format!(
                    "{} {:02}:00 · {} {} · {}",
                    lang.weekday(d),
                    h,
                    p.int(*value),
                    lang.chest_word(*value),
                    lang.matches_count(matches)
                )),
            });
        }
    }
    card.heat = model(cells);
    card.note = s(lang.t(
        "Local time · darker means more chests",
        "Horário local · mais escuro indica mais baús",
    ));
    card
}

fn records_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("records", "table", span, ctx);
    let lang = lang_of(ctx);
    let (snap, p) = (ctx.snap, ctx.prefs);
    let mut items = Vec::new();
    if let Some(best) = snap.best {
        items.push((
            lang.t("Best match", "Melhor partida"),
            format!("{} {}", p.int(best), lang.chest_word(best)),
        ));
    }
    if let Some((day, count)) = snap.best_day {
        items.push((
            lang.t("Best day", "Melhor dia"),
            format!("{} · {}", p.int(count), p.short_date(day)),
        ));
    }
    if let Some(session) = &snap.session_best {
        let length = (session.end - session.start).num_milliseconds() as f64 / 1000.0;
        items.push((
            lang.t("Longest session", "Sessão mais longa"),
            format!(
                "{} · {} {}",
                p.duration(length),
                p.int(session.chests),
                lang.chest_word(session.chests)
            ),
        ));
    }
    if snap.peak_hour.0 > 0 {
        items.push((
            lang.t("Most in one hour", "Máximo em uma hora"),
            p.int(snap.peak_hour.0),
        ));
    }
    items.push((
        lang.t("Longest daily streak", "Maior sequência diária"),
        lang.days_count(snap.streak_longest),
    ));
    items.push((
        lang.t("Current streak", "Sequência atual"),
        lang.days_count(snap.streak_current),
    ));
    card.table = model(
        items
            .into_iter()
            .map(|(n, v)| row(vec![cell(n, 0), cell(v, 1)]))
            .collect(),
    );
    card
}

fn team_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("teammates", "bars", span, ctx);
    let lang = lang_of(ctx);
    let (snap, p) = (ctx.snap, ctx.prefs);
    if snap.matches == 0 {
        card.lines = model(vec![cell(
            lang.t(
                "Read a match with teammates to compare.",
                "Leia uma partida com equipe para comparar.",
            ),
            0,
        )]);
        return card;
    }
    let (you, team) = (snap.match_chests, snap.team_total);
    let per_match_label = lang.t("per match", "por partida");
    let mut rows = vec![
        (
            lang.t("You", "Você").to_owned(),
            you,
            format!(
                "{} · {} {per_match_label}",
                p.int(you),
                p.number(snap.avg.unwrap_or(0.0), 1)
            ),
        ),
        (
            lang.t("Teammates", "Equipe").to_owned(),
            team,
            format!(
                "{} · {} {per_match_label}",
                p.int(team),
                p.number(snap.team_per_match.unwrap_or(0.0), 1)
            ),
        ),
    ];
    for m in snap.board.iter().filter(|m| !m.me && !m.unranked).take(3) {
        rows.push((
            m.name.clone(),
            m.total,
            format!(
                "{} {} {}",
                p.int(m.total),
                lang.t("in", "em"),
                lang.matches_count(m.matches)
            ),
        ));
    }
    card.bars = bars(rows);
    let share = snap
        .your_share
        .map(|x| match lang {
            Lang::En => format!(
                "You opened {}% of the chests your replays recorded. ",
                (x * 100.0).round()
            ),
            Lang::PtBr => format!(
                "Você abriu {}% dos baús registrados nos seus replays. ",
                (x * 100.0).round()
            ),
        })
        .unwrap_or_default();
    card.note = s(share
        + lang.t(
            "Teammate counts only include chests your replays recorded. Full squad breakdown: Teammates page.",
            "A contagem da equipe inclui só os baús registrados nos seus replays. Resumo completo na aba Equipe.",
        ));
    card
}

fn broken_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("broken", "table", span, ctx);
    let lang = lang_of(ctx);
    let (snap, p) = (ctx.snap, ctx.prefs);
    let searched = (snap.all - snap.broken, snap.team_opened);
    let broken = (snap.broken, snap.team_broken);
    let total = (searched.0 + broken.0, searched.1 + broken.1);
    let mut rows = vec![row(vec![
        cell("", 3),
        cell(lang.t("You", "Você"), 3),
        cell(lang.t("Teammates*", "Equipe*"), 3),
    ])];
    for (is_total, name, pair) in [
        (false, lang.t("Searched", "Abertos"), searched),
        (false, lang.t("Broken open", "Quebrados"), broken),
        (true, "Total", total),
    ] {
        rows.push(row(vec![
            cell(name, if is_total { 3 } else { 0 }),
            cell(p.int(pair.0), 1),
            cell(p.int(pair.1), 1),
        ]));
    }
    card.table = model(rows);
    let mut ammo: Vec<String> = snap
        .containers
        .keys()
        .chain(snap.team_containers.keys())
        .map(str::to_owned)
        .collect();
    ammo.sort();
    ammo.dedup();
    let mut notes = Vec::new();
    if !ammo.is_empty() {
        let prefix = lang.t("Not counted as chests: ", "Não contados como baús: ");
        let you_lbl = lang.t("you", "você");
        let team_lbl = lang.t("teammates", "equipe");
        notes.push(format!(
            "{prefix}{}",
            ammo.iter()
                .map(|n| format!(
                    "{}, {you_lbl} {} / {team_lbl} {}",
                    lang.container_name(n),
                    p.int(snap.containers.get(n)),
                    p.int(snap.team_containers.get(n))
                ))
                .collect::<Vec<_>>()
                .join(" · ")
        ));
    }
    notes.push(
        lang.t(
            "*Teammates: only chests your replays recorded. Broken open means the chest was destroyed before anyone searched it.",
            "*Equipe: apenas baús registrados nos seus replays. Quebrados significa baús destruídos antes de serem abertos.",
        )
        .into(),
    );
    card.note = s(notes.join("\n"));
    card
}

fn health_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("health", "health", span, ctx);
    let lang = lang_of(ctx);
    let Some(h) = &ctx.health else { return card };
    let p = ctx.prefs;
    let mut blocked = false;
    let mut checks = Vec::new();
    for (name, ok, fix) in &h.checks {
        let fix = if *ok {
            String::new()
        } else if blocked {
            lang.t("Waiting on the step above.", "Aguardando o passo anterior.")
                .into()
        } else {
            format!("{} {fix}", lang.t("Fix it:", "Corrigir:"))
        };
        if !ok {
            blocked = true; // later checks depend on earlier ones: one fix at a time
        }
        checks.push(Check {
            ok: *ok,
            title: s(name.clone()),
            fix: s(fix),
        });
    }
    card.checks = model(checks);
    let checked = h
        .last_scan
        .map_or(lang.t("not yet", "ainda não").to_owned(), |t| {
            t.format("%H:%M:%S").to_string()
        });
    let newest = h
        .newest
        .map_or(lang.t("none yet", "nenhum ainda").to_owned(), |t| {
            let ago = crate::prefs::elapsed(crate::live::seconds(std::time::SystemTime::now()) - t);
            match lang {
                Lang::En => format!("newest {ago} ago"),
                Lang::PtBr => format!("mais recente há {ago}"),
            }
        });
    card.note = s(match lang {
        Lang::En => format!(
            "{} · last check {checked}\n{} replays in the folder ({newest}) · {} read · {} could not be read",
            h.watching,
            p.int(h.replays as i64),
            p.int(h.read),
            p.int(h.unreadable)
        ),
        Lang::PtBr => format!(
            "{} · última verificação {checked}\n{} replays na pasta ({newest}) · {} lidos · {} não puderam ser lidos",
            h.watching,
            p.int(h.replays as i64),
            p.int(h.read),
            p.int(h.unreadable)
        ),
    });
    card
}

fn sessions_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("sessions", "bars", span, ctx);
    let lang = lang_of(ctx);
    let p = ctx.prefs;
    let found = stats::sessions(&ctx.snap.match_rows);
    let Some(last) = found.first() else {
        card.value = s("–");
        card.lines = model(vec![cell(
            lang.t(
                "Play a few matches: matches less than 30 minutes apart make a session.",
                "Jogue algumas partidas: intervalos menores que 30 minutos formam uma sessão.",
            ),
            0,
        )]);
        return card;
    };
    card.value = s(p.int(last.chests));
    let mut lines = vec![cell(
        format!(
            "{} · {} · {} · {} · {} {}",
            lang.t("Latest session", "Última sessão"),
            p.short_date(last.start.date_naive()),
            lang.matches_count(last.matches),
            p.duration(last.seconds),
            p.number(last.per_hour, 1),
            lang.t("chests per hour", "baús por hora"),
        ),
        0,
    )];
    let average = found.iter().map(|x| x.per_hour).sum::<f64>() / found.len() as f64;
    let per_hour_lbl = lang.t("per hour", "por hora");
    let mut parts = vec![format!(
        "{}: {} {per_hour_lbl}",
        lang.t("Average session", "Média por sessão"),
        p.number(average, 1)
    )];
    if let Some(prev) = found.get(1) {
        parts.insert(
            0,
            format!(
                "{}: {} {}, {} {per_hour_lbl}",
                lang.t("Previous", "Anterior"),
                p.int(prev.chests),
                lang.chest_word(prev.chests),
                p.number(prev.per_hour, 1)
            ),
        );
    }
    lines.push(cell(parts.join(" · "), 0));
    card.lines = model(lines);
    card.bars = bars(
        found
            .iter()
            .take(5)
            .map(|x| {
                (
                    p.short_date(x.start.date_naive()),
                    x.chests,
                    p.int(x.chests),
                )
            })
            .collect(),
    );
    card
}

fn goals_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("goals", "goals", span, ctx);
    let lang = lang_of(ctx);
    let p = ctx.prefs;
    let goals = stats::goals(ctx.snap, p.goal_daily, p.goal_weekly);
    card.rings = model(
        goals
            .iter()
            .map(|g| RingData {
                share: g.share as f32,
                text: s(format!("{}/{}", p.int(g.done), p.int(g.target))),
                caption: s(format!(
                    "{}{}",
                    lang.goal_name(g.name),
                    if g.reached {
                        lang.t(" · done", " · concluído")
                    } else {
                        ""
                    }
                )),
                path: s(arc(42.0, 0.0, g.share.max(0.001))),
            })
            .collect(),
    );
    let streak = ctx.snap.streak_current;
    let text = match lang {
        Lang::En => format!("Streak: {} in a row with chests.", lang.days_count(streak)),
        Lang::PtBr => format!("Sequência: {} seguidos com baús.", lang.days_count(streak)),
    };
    card.note = s(if goals.is_empty() {
        text + lang.t(
            " Set a daily or weekly goal in Settings → Goals.",
            " Defina uma meta diária ou semanal em Configurações → Metas.",
        )
    } else {
        text
    });
    card
}

fn trophies_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("trophies", "trophies", span, ctx);
    let lang = lang_of(ctx);
    let items = stats::achievements(ctx.snap);
    let unlocked = items.iter().filter(|i| i.unlocked).count();
    card.note = s(match lang {
        Lang::En => format!("{unlocked} of {} unlocked", items.len()),
        Lang::PtBr => format!("{unlocked} de {} desbloqueados", items.len()),
    });
    card.trophies = model(
        items
            .into_iter()
            .map(|i| {
                let (title, detail) = lang.achievement(&i.id, &i.title, &i.detail);
                Trophy {
                    title: s(title),
                    detail: s(detail),
                    unlocked: i.unlocked,
                }
            })
            .collect(),
    );
    card
}

pub fn default_compare(today: NaiveDate) -> [NaiveDate; 4] {
    let monday = today - Duration::days(today.weekday().num_days_from_monday() as i64);
    [
        monday - Duration::days(7),
        monday - Duration::days(1),
        monday,
        today,
    ]
}

fn compare_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("compare", "compare", span, ctx);
    let lang = lang_of(ctx);
    let (p, d) = (ctx.prefs, ctx.compare);
    card.dates = model(d.iter().map(|x| s(p.full_date(*x))).collect());
    let mut rows = vec![row(vec![
        cell("", 3),
        cell(lang.t("First", "Primeiro"), 3),
        cell(lang.t("Second", "Segundo"), 3),
        cell(lang.t("Change", "Variação"), 3),
    ])];
    for (name, a, b, change) in stats::compare(ctx.snap, (d[0], d[1]), (d[2], d[3])) {
        let decimals = if name == "Chests per match" { 1 } else { 0 };
        let sign = if change > 0.0 {
            "+"
        } else if change < 0.0 {
            "−"
        } else {
            "±"
        };
        rows.push(row(vec![
            cell(lang.compare_metric(name), 0),
            cell(p.number(a, decimals), 1),
            cell(p.number(b, decimals), 1),
            cell(
                format!("{sign}{}", p.number(change.abs(), decimals)),
                if change > 0.0 { 2 } else { 0 },
            ),
        ]));
    }
    card.table = model(rows);
    card
}

/// Match stats as the replay stores them, in display order: (label, key, how to show it).
pub const MATCH_STATS: &[(&str, &str, StatUnit)] = &[
    ("Damage to players", "damage_to_players", StatUnit::Count),
    ("Damage taken", "damage_taken", StatUnit::Count),
    ("Eliminations", "eliminations", StatUnit::Count),
    ("Assists", "assists", StatUnit::Count),
    ("Accuracy", "accuracy", StatUnit::Percent),
    ("Revives", "revives", StatUnit::Count),
    (
        "Damage to structures",
        "damage_to_structures",
        StatUnit::Count,
    ),
    ("Materials gathered", "materials_gathered", StatUnit::Count),
    ("Materials used", "materials_used", StatUnit::Count),
    ("Distance travelled", "distance", StatUnit::Distance),
];

#[derive(Clone, Copy, PartialEq)]
pub enum StatUnit {
    Count,
    Percent,
    /// Centimetres in the replay, shown in kilometres.
    Distance,
}

pub fn stat_text(p: &Prefs, unit: StatUnit, value: f64) -> String {
    match unit {
        StatUnit::Count => p.number(value, 0),
        StatUnit::Percent => format!("{}%", p.number(value * 100.0, 0)),
        StatUnit::Distance => format!("{} km", p.number(value / 100_000.0, 1)),
    }
}

fn stats_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("stats", "table", span, ctx);
    let lang = lang_of(ctx);
    let p = ctx.prefs;
    let with: Vec<&serde_json::Value> = ctx
        .snap
        .match_rows
        .iter()
        .filter_map(|r| r.stats.as_ref())
        .collect();
    if with.is_empty() {
        card.note = s(lang.t(
            "No match stats yet. They come from replays LootLedger reads from now on, and from older replays Fortnite still keeps.",
            "Sem estatísticas de partida ainda. Elas vêm dos próximos replays lidos e dos replays antigos que ainda estiverem no disco.",
        ));
        return card;
    }
    let mut rows = vec![row(vec![
        cell("", 3),
        cell(lang.t("Per match", "Por partida"), 3),
        cell(lang.t("Best", "Melhor"), 3),
        cell("Total", 3),
    ])];
    for (_, key, unit) in MATCH_STATS {
        let values: Vec<f64> = with.iter().filter_map(|st| st[*key].as_f64()).collect();
        let total: f64 = values.iter().sum();
        let best = values.iter().cloned().fold(0.0, f64::max);
        let average = total / values.len().max(1) as f64;
        let total_text = if *unit == StatUnit::Percent {
            "–".to_owned()
        } else {
            stat_text(p, *unit, total)
        };
        rows.push(row(vec![
            cell(lang.match_stat_label(key), 0),
            cell(stat_text(p, *unit, average), 1),
            cell(stat_text(p, *unit, best), 4),
            cell(total_text, 0),
        ]));
    }
    card.table = model(rows);
    let total_non_manual = ctx
        .snap
        .match_rows
        .iter()
        .filter(|r| r.mode != "Manual")
        .count();
    card.note = s(match lang {
        Lang::En => format!(
            "From {} of {} matches. Matches whose replay Fortnite has already deleted have no stats.",
            with.len(),
            total_non_manual
        ),
        Lang::PtBr => format!(
            "De {} de {} partidas. Partidas cujo replay já foi apagado pelo Fortnite não têm estatísticas.",
            with.len(),
            total_non_manual
        ),
    });
    card
}

fn treasures_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("treasures", "table", span, ctx);
    let lang = lang_of(ctx);
    let p = ctx.prefs;
    let mut entries = Vec::new();
    let (mut mine, mut team, mut golden) = (0usize, 0usize, 0usize);
    for r in &ctx.snap.match_rows {
        for d in &r.treasures {
            mine += 1;
            if d.source == "golden" {
                golden += 1;
            }
            entries.push((r.when, true, d));
        }
        for d in &r.team_treasures {
            team += 1;
            if d.source == "golden" {
                golden += 1;
            }
            entries.push((r.when, false, d));
        }
    }
    if entries.is_empty() {
        card.note = s(lang.t(
            "No treasure hunt rewards found yet. Drops from Golden Chests and Delilah gizmos in scanned replays appear here.",
            "Nenhuma recompensa de tesouro encontrada ainda. Recompensas de Baús Dourados e dispositivos nos replays analisados aparecerão aqui.",
        ));
        return card;
    }
    let mut rows = vec![row(vec![
        cell(lang.t("Reward", "Recompensa"), 3),
        cell(lang.t("Kind", "Tipo"), 3),
        cell(lang.t("Who", "Quem"), 3),
        cell(lang.t("When", "Quando"), 3),
    ])];
    for (when, is_me, drop) in entries.iter().take(8) {
        let who = if *is_me {
            lang.t("You", "Você").to_owned()
        } else {
            drop.player
                .as_deref()
                .filter(|name| !name.is_empty())
                .unwrap_or_else(|| lang.t("Teammate", "Colega"))
                .to_owned()
        };
        let item_tone = if drop.source == "golden" { 2 } else { 0 };
        let kind_text = format!(
            "{} · {}",
            lang.treasure_kind(&drop.kind),
            lang.treasure_source(&drop.source)
        );
        rows.push(row(vec![
            cell(lang.treasure_item_name(drop, ctx.synced_prizes), item_tone),
            cell(kind_text, 1),
            cell(who, 1),
            cell(p.when(*when), 1),
        ]));
    }
    card.table = model(rows);
    card.note = s(match lang {
        Lang::En => format!("{mine} for you · {team} for teammates · {golden} golden chest(s)"),
        Lang::PtBr => {
            format!("{mine} suas · {team} da equipe · {golden} baú(s) dourado(s)")
        }
    });
    card
}

fn seen_prizes_card(span: i32, ctx: &Context) -> CardData {
    let mut card = blank("seen_prizes", "table", span, ctx);
    let lang = lang_of(ctx);
    let p = ctx.prefs;
    let mut entries = Vec::new();
    for r in &ctx.snap.match_rows {
        for d in &r.seen_prizes {
            entries.push((r.when, d));
        }
    }
    if entries.is_empty() {
        card.note = s(lang.t(
            "No golden chest prizes seen from other players nearby (~150 m) yet.",
            "Nenhum prêmio de baú dourado visto de outros jogadores por perto (~150 m) ainda.",
        ));
        return card;
    }
    let total = entries.len();
    let mut rows = vec![row(vec![
        cell(lang.t("Prize", "Prêmio"), 3),
        cell(lang.t("Kind", "Tipo"), 3),
        cell(lang.t("Player", "Jogador"), 3),
        cell(lang.t("When", "Quando"), 3),
    ])];
    for (when, drop) in entries.iter().take(8) {
        let who = drop
            .player
            .as_deref()
            .filter(|name| !name.is_empty())
            .unwrap_or_else(|| lang.t("Nearby player", "Jogador próximo"))
            .to_owned();
        rows.push(row(vec![
            cell(lang.treasure_item_name(drop, ctx.synced_prizes), 2),
            cell(lang.treasure_kind(&drop.kind), 1),
            cell(who, 1),
            cell(p.when(*when), 1),
        ]));
    }
    card.table = model(rows);
    card.note = s(match lang {
        Lang::En => format!("{total} golden chest prize(s) spotted within ~150 m"),
        Lang::PtBr => format!("{total} prêmio(s) de baú dourado avistado(s) em ~150 m"),
    });
    card
}

pub fn build(id: &str, span: i32, ctx: &Context) -> CardData {
    if let Some(key) = id.strip_prefix("stat:") {
        return stat_card(key, span, ctx);
    }
    match id {
        "live" => live_card(span, ctx),
        "trend" => trend_card(span, ctx),
        "token" => token_card(span, ctx),
        "treasures" => treasures_card(span, ctx),
        "seen_prizes" => seen_prizes_card(span, ctx),
        "types" => types_card(span, ctx),
        "modes" => modes_card(span, ctx),
        "heat" => heat_card(span, ctx),
        "records" => records_card(span, ctx),
        "teammates" => team_card(span, ctx),
        "broken" => broken_card(span, ctx),
        "health" => health_card(span, ctx),
        "sessions" => sessions_card(span, ctx),
        "goals" => goals_card(span, ctx),
        "trophies" => trophies_card(span, ctx),
        "compare" => compare_card(span, ctx),
        "stats" => stats_card(span, ctx),
        "rewards" => rewards_card(span, ctx),
        "reward_types" => reward_types_card(span, ctx),
        _ => blank(id, "table", span, ctx),
    }
}

/// Place cards into rows of `columns`, as DashGrid.reflow: a card that does not fit starts the next row.
pub fn pack(cards: Vec<CardData>, columns: i32) -> Vec<crate::DashRow> {
    let columns = columns.max(1);
    let mut rows: Vec<(Vec<CardData>, i32, i32)> = Vec::new();
    let mut used = columns;
    for (i, mut card) in cards.into_iter().enumerate() {
        card.span = card.span.min(columns);
        if used + card.span > columns {
            rows.push((Vec::new(), 0, i as i32));
            used = 0;
        }
        used += card.span;
        let last = rows.last_mut().expect("row");
        last.1 += card.span;
        last.0.push(card);
    }
    rows.into_iter()
        .map(|(cards, used, first)| crate::DashRow {
            cards: model(cards),
            free: columns - used,
            first,
        })
        .collect()
}

/// The match pop-up's second line: how this match compares, then today's total.
pub fn popup_detail(count: i64, snap: &Snapshot, p: &Prefs) -> String {
    versus(count, snap.matches, snap.best, snap.avg, snap.today, p)
}

fn versus(
    count: i64,
    matches: i64,
    best: Option<i64>,
    avg: Option<f64>,
    today: i64,
    p: &Prefs,
) -> String {
    let lang = i18n::from_code(&p.language);
    let mut parts = Vec::new();
    if matches > 1 && best == Some(count) {
        parts.push(
            lang.t("Your best match yet", "Sua melhor partida até agora")
                .to_owned(),
        );
    } else if let Some(avg) = avg {
        let diff = (count as f64 - avg).round() as i64;
        let vs_avg = lang.t("vs your average", "da sua média");
        parts.push(match diff {
            0 => lang.t("Right on your average", "Na sua média").to_owned(),
            d if d > 0 => format!("+{} {vs_avg}", p.int(d)),
            d => format!("−{} {vs_avg}", p.int(-d)),
        });
    }
    parts.push(format!("{} {}", lang.t("Today", "Hoje"), p.int(today)));
    parts.join(" · ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn popup_compares_with_the_average_or_calls_a_best() {
        let p = Prefs::default();
        let line = |count| versus(count, 10, Some(40), Some(20.4), 1234, &p);
        assert_eq!(line(23), "+3 vs your average · Today 1,234");
        assert_eq!(line(17), "−3 vs your average · Today 1,234");
        assert_eq!(line(20), "Right on your average · Today 1,234");
        assert_eq!(line(40), "Your best match yet · Today 1,234");
        // The first match is not a "best" yet, and with no average only today is shown.
        assert_eq!(versus(5, 1, Some(5), None, 5, &p), "Today 5");
    }

    #[test]
    fn packing_wraps_wide_cards_like_the_old_grid() {
        let card = |span| CardData {
            span,
            ..Default::default()
        };
        let rows = pack(vec![card(2), card(1), card(1), card(2), card(1)], 3);
        let shape: Vec<(usize, i32, i32)> = rows
            .iter()
            .map(|r| (slint::Model::row_count(&r.cards), r.free, r.first))
            .collect();
        assert_eq!(shape, vec![(2, 0, 0), (2, 0, 2), (1, 2, 4)]);
        let narrow = pack(vec![card(2), card(1)], 1);
        assert_eq!(narrow.len(), 2);
    }

    #[test]
    fn arcs_and_lines_are_well_formed() {
        assert!(arc(40.0, 0.0, 0.25).starts_with("M 50.000 10.000 A 40 40 0 0 1 90.000 50.000"));
        assert!(arc(40.0, 0.0, 1.0).matches(" A ").count() == 2);
        let (line, area) = spark(&[0.0, 2.0, 4.0]);
        assert!(line.starts_with("M 0.00 96.00") && area.ends_with('Z'));
        let (smooth, _) = series_path(&[1.0, 3.0, 2.0], true);
        assert_eq!(smooth.matches(" C ").count(), 2);
    }
}
