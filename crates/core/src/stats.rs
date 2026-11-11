//! Dashboard statistics, a port of lootledger/stats.py and features.py: plain data over openings and
//! matches, no SQL and no UI. Times are local; a day is a calendar date and weeks start on Monday.

use chrono::{DateTime, Datelike, Duration, Local, NaiveDate, Timelike};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};

pub const SESSION_GAP_MINUTES: i64 = 30;
const RECENT: usize = 20;
pub const RARE: [&str; 3] = ["Rare chest", "Relic chest", "Buried chest"];

/// One counted opening.
#[derive(Debug, Clone)]
pub struct Ev {
    pub when: DateTime<Local>,
    pub amount: i64,
    pub chest_type: String,
    pub source: String,
    pub match_id: Option<String>,
}

/// One match as the history query returns it.
#[derive(Debug, Clone)]
pub struct MatchIn {
    pub id: String,
    pub started: DateTime<Local>,
    pub seconds: f64,
    pub total: i64,
    pub broken: i64,
    pub meta: Option<Value>,
    pub note: String,
    pub tags: String,
    pub favorite: bool,
}

/// Counts that keep the first-seen order of keys and sort like Python's Counter.most_common.
#[derive(Debug, Clone, Default)]
pub struct Counter {
    pub items: Vec<(String, i64)>,
}

impl Counter {
    pub fn add(&mut self, key: &str, n: i64) {
        match self.items.iter_mut().find(|(k, _)| k == key) {
            Some((_, v)) => *v += n,
            None => self.items.push((key.to_owned(), n)),
        }
    }
    pub fn get(&self, key: &str) -> i64 {
        self.items
            .iter()
            .find(|(k, _)| k == key)
            .map_or(0, |(_, v)| *v)
    }
    /// Highest first; ties keep insertion order (Python's sort is stable).
    pub fn most_common(&self) -> Vec<(String, i64)> {
        let mut items = self.items.clone();
        items.sort_by_key(|x| std::cmp::Reverse(x.1));
        items
    }
    pub fn total(&self) -> i64 {
        self.items.iter().map(|(_, v)| v).sum()
    }
    pub fn keys(&self) -> impl Iterator<Item = &str> {
        self.items.iter().map(|(k, _)| k.as_str())
    }
}

#[derive(Debug, Clone)]
pub struct SquadMember {
    pub key: String,
    pub name: String,
    pub me: bool,
    pub bot: bool,
    pub anonymous: bool,
    pub unranked: bool,
    pub opened: i64,
    pub broken: i64,
    pub total: i64,
    pub types: Counter,
    pub containers: Counter,
}

#[derive(Debug, Clone)]
pub struct MatchRow {
    pub id: String,
    pub when: DateTime<Local>,
    pub seconds: f64,
    pub count: i64,
    pub broken: i64,
    pub mode: String,
    pub types: Counter,
    pub team: i64,
    pub ammo: i64,
    pub placement: Option<i64>,
    pub players: Option<i64>,
    pub teammates: Vec<String>,
    pub squad: Option<Vec<SquadMember>>,
    pub mvp: Option<String>,
    pub squad_total: i64,
    pub unattributed: i64,
    /// The recorder's match stats (damage, accuracy, materials...), when the replay had them.
    pub stats: Option<Value>,
    pub note: String,
    pub tags: String,
    pub favorite: bool,
}

#[derive(Debug, Clone)]
pub struct Person {
    pub key: String,
    pub name: String,
    pub me: bool,
    pub bot: bool,
    pub anonymous: bool,
    pub unranked: bool,
    pub matches: i64,
    pub total: i64,
    pub opened: i64,
    pub broken: i64,
    pub types: Counter,
    pub best: i64,
    pub best_when: Option<DateTime<Local>>,
    pub last: Option<DateTime<Local>>,
    pub per_match: f64,
    pub rare: i64,
}

#[derive(Debug, Clone, Copy)]
pub struct Mode {
    pub matches: i64,
    pub chests: i64,
}

#[derive(Debug, Clone)]
pub struct Session {
    pub start: DateTime<Local>,
    pub end: DateTime<Local>,
    pub matches: i64,
    pub chests: i64,
    pub seconds: f64,
    pub per_hour: f64,
}

#[derive(Debug, Clone)]
pub struct Snapshot {
    pub today_date: NaiveDate,
    pub per_day: BTreeMap<NaiveDate, i64>,
    pub all: i64,
    pub broken: i64,
    pub types: Counter,
    pub containers: Counter,
    pub modes: Vec<(String, Mode)>,
    pub today: i64,
    pub today_prev: i64,
    pub week: i64,
    pub week_prev: i64,
    pub month: i64,
    pub month_prev: i64,
    pub session: i64,
    pub matches: i64,
    pub match_chests: i64,
    pub avg: Option<f64>,
    pub median: Option<f64>,
    pub best: Option<i64>,
    pub worst: Option<i64>,
    pub recent_totals: Vec<i64>,
    pub playtime: f64,
    pub per_hour: f64,
    pub last: Option<MatchRow>,
    pub best_day: Option<(NaiveDate, i64)>,
    pub streak_longest: i64,
    pub streak_current: i64,
    pub session_best: Option<Session>,
    pub peak_hour: (i64, Option<DateTime<Local>>),
    pub heat: [[i64; 24]; 7],
    pub heat_matches: [[i64; 24]; 7],
    pub match_days: BTreeMap<NaiveDate, i64>,
    pub team_total: i64,
    pub team_types: Counter,
    pub team_opened: i64,
    pub team_broken: i64,
    pub team_containers: Counter,
    pub unattributed: i64,
    pub board: Vec<Person>,
    pub older_matches: i64,
    pub team_per_match: Option<f64>,
    pub your_share: Option<f64>,
    pub player: Option<String>,
    pub partial: i64,
    pub match_rows: Vec<MatchRow>,
}

fn span(per_day: &BTreeMap<NaiveDate, i64>, start: NaiveDate, end: NaiveDate) -> i64 {
    if start > end {
        return 0;
    }
    per_day.range(start..=end).map(|(_, v)| v).sum()
}

fn peak_hour(events: &[Ev]) -> (i64, Option<DateTime<Local>>) {
    let mut times: Vec<&Ev> = events.iter().collect();
    times.sort_by_key(|e| e.when);
    let (mut best, mut low, mut window) = ((0, None), 0usize, 0i64);
    for event in &times {
        window += event.amount;
        while event.when - times[low].when >= Duration::hours(1) {
            window -= times[low].amount;
            low += 1;
        }
        if window > best.0 {
            best = (window, Some(event.when));
        }
    }
    best
}

fn streaks(per_day: &BTreeMap<NaiveDate, i64>, today: NaiveDate) -> (i64, i64) {
    let (mut longest, mut run, mut previous) = (0, 0, None::<NaiveDate>);
    for (&day, _) in per_day.iter().filter(|(_, v)| **v > 0) {
        run = if previous.is_some_and(|p| day - p == Duration::days(1)) {
            run + 1
        } else {
            1
        };
        longest = longest.max(run);
        previous = Some(day);
    }
    let positive = |d: &NaiveDate| per_day.get(d).copied().unwrap_or(0) > 0;
    let mut day = if positive(&today) {
        today
    } else {
        today - Duration::days(1)
    };
    let mut current = 0;
    while positive(&day) {
        current += 1;
        day -= Duration::days(1);
    }
    (longest, current)
}

fn seconds(s: f64) -> Duration {
    Duration::milliseconds((s * 1000.0) as i64)
}

fn longest_session(analyzed: &[&MatchIn]) -> Option<Session> {
    let gap = Duration::minutes(SESSION_GAP_MINUTES);
    let (mut best, mut current): (Option<Session>, Option<Session>) = (None, None);
    for m in analyzed {
        let end = m.started + seconds(m.seconds);
        match current.as_mut() {
            Some(c) if m.started - c.end <= gap => {
                c.end = c.end.max(end);
                c.chests += m.total;
                c.matches += 1;
            }
            _ => {
                current = Some(Session {
                    start: m.started,
                    end,
                    matches: 1,
                    chests: m.total,
                    seconds: 0.0,
                    per_hour: 0.0,
                })
            }
        }
        let c = current.as_ref().expect("session");
        if best
            .as_ref()
            .is_none_or(|b| c.end - c.start > b.end - b.start)
        {
            best = Some(c.clone());
        }
    }
    best
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Grain {
    Day,
    Week,
    Month,
}

fn grain_key(grain: Grain, day: NaiveDate) -> NaiveDate {
    match grain {
        Grain::Day => day,
        Grain::Week => day - Duration::days(day.weekday().num_days_from_monday() as i64),
        Grain::Month => day.with_day(1).expect("first of month"),
    }
}

/// Counts per day, week or month from start to end inclusive, including empty periods.
pub fn series(
    per_day: &BTreeMap<NaiveDate, i64>,
    grain: Grain,
    start: NaiveDate,
    end: NaiveDate,
) -> Vec<(NaiveDate, i64)> {
    let mut buckets = BTreeMap::new();
    let (mut cursor, last) = (grain_key(grain, start), grain_key(grain, end));
    while cursor <= last {
        buckets.insert(cursor, 0);
        cursor = match grain {
            Grain::Day => cursor + Duration::days(1),
            Grain::Week => cursor + Duration::days(7),
            Grain::Month => (cursor.with_day(28).expect("28th") + Duration::days(4))
                .with_day(1)
                .expect("first"),
        };
    }
    for (&day, &value) in per_day {
        if start <= day
            && day <= end
            && let Some(b) = buckets.get_mut(&grain_key(grain, day))
        {
            *b += value;
        }
    }
    buckets.into_iter().collect()
}

/// Chart points for the trend card; `matches` counts matches instead of chests. days=0 means everything.
pub fn trend(snap: &Snapshot, grain: Grain, days: i64, matches: bool) -> Vec<(NaiveDate, i64)> {
    let today = snap.today_date;
    let start = if days > 0 {
        today - Duration::days(days - 1)
    } else {
        snap.per_day.keys().next().copied().unwrap_or(today)
    };
    series(
        if matches {
            &snap.match_days
        } else {
            &snap.per_day
        },
        grain,
        start,
        today,
    )
}

pub fn last_days(snap: &Snapshot, count: i64) -> Vec<i64> {
    (0..count)
        .rev()
        .map(|offset| {
            snap.per_day
                .get(&(snap.today_date - Duration::days(offset)))
                .copied()
                .unwrap_or(0)
        })
        .collect()
}

fn squad(meta: &Value, include_broken: bool) -> Vec<SquadMember> {
    let mut people: Vec<SquadMember> = Vec::new();
    for p in meta["players"].as_array().into_iter().flatten() {
        let mut types = Counter::default();
        let (mut opened, mut broken) = (0, 0);
        for (name, c) in p["counts"].as_object().into_iter().flatten() {
            let o = c["opened"].as_i64().unwrap_or(0);
            let b = if include_broken {
                c["broken"].as_i64().unwrap_or(0)
            } else {
                0
            };
            opened += o;
            broken += b;
            if o + b != 0 {
                types.add(name, o + b);
            }
        }
        let mut containers = Counter::default();
        for (name, n) in p["containers"].as_object().into_iter().flatten() {
            containers.add(name, n.as_i64().unwrap_or(0));
        }
        let key = p["key"].as_str().unwrap_or("").to_owned();
        let bot = p["bot"].as_bool().unwrap_or(false);
        let anonymous = key.starts_with("anon-");
        people.push(SquadMember {
            name: p["name"].as_str().unwrap_or("").to_owned(),
            me: p["me"].as_bool().unwrap_or(false),
            unranked: bot || anonymous,
            key,
            bot,
            anonymous,
            opened,
            broken,
            total: opened + broken,
            types,
            containers,
        });
    }
    people.sort_by(|a, b| {
        (-a.total, -a.opened, !a.me, &a.name).cmp(&(-b.total, -b.opened, !b.me, &b.name))
    });
    people
}

/// Short label after a name: you, bot, or unnamed.
pub fn tag(p: &SquadMember) -> &'static str {
    if p.me {
        " · you"
    } else if p.bot {
        " · bot"
    } else if p.anonymous {
        " · unnamed"
    } else {
        ""
    }
}

fn mvp(squad: &[SquadMember]) -> Option<String> {
    let mut ranked: Vec<&SquadMember> = squad
        .iter()
        .filter(|p| p.total > 0 && !p.unranked)
        .collect();
    ranked.sort_by_key(|p| (-p.total, -p.opened));
    match ranked.as_slice() {
        [] => None,
        [a, b, ..] if (a.total, a.opened) == (b.total, b.opened) => None,
        [a, ..] => Some(a.key.clone()),
    }
}

/// Everyone across these match rows, merged by stable id, most chests first. Bots are listed, not ranked.
pub fn board(rows: &[MatchRow]) -> Vec<Person> {
    let mut order: Vec<&MatchRow> = rows.iter().collect();
    order.sort_by_key(|r| r.when);
    let mut people: Vec<Person> = Vec::new();
    let mut index: HashMap<String, usize> = HashMap::new();
    for row in order {
        for p in row.squad.iter().flatten() {
            let at = *index.entry(p.key.clone()).or_insert_with(|| {
                people.push(Person {
                    key: p.key.clone(),
                    name: p.name.clone(),
                    me: p.me,
                    bot: p.bot,
                    anonymous: p.anonymous,
                    unranked: p.unranked,
                    matches: 0,
                    total: 0,
                    opened: 0,
                    broken: 0,
                    types: Counter::default(),
                    best: 0,
                    best_when: None,
                    last: None,
                    per_match: 0.0,
                    rare: 0,
                });
                people.len() - 1
            });
            let person = &mut people[at];
            person.name = p.name.clone();
            person.matches += 1;
            person.total += p.total;
            person.opened += p.opened;
            person.broken += p.broken;
            for (name, n) in &p.types.items {
                person.types.add(name, *n);
            }
            if p.total > person.best {
                person.best = p.total;
                person.best_when = Some(row.when);
            }
            person.last = Some(row.when);
        }
    }
    people.sort_by(|a, b| {
        (a.unranked, -a.total, -a.matches, &a.name)
            .cmp(&(b.unranked, -b.total, -b.matches, &b.name))
    });
    for person in &mut people {
        person.per_match = person.total as f64 / person.matches as f64;
        person.rare = RARE.iter().map(|n| person.types.get(n)).sum();
    }
    people
}

pub struct Records<'a> {
    pub most_chests: Option<&'a Person>,
    pub best_match: Option<&'a Person>,
    pub most_played: Option<&'a Person>,
}

/// max() that keeps the first of equal values, like Python's.
fn first_max<'a>(items: &[&'a Person], key: impl Fn(&Person) -> i64) -> Option<&'a Person> {
    let mut best: Option<&Person> = None;
    for p in items {
        if best.is_none_or(|b| key(p) > key(b)) {
            best = Some(p);
        }
    }
    best
}

/// Records among teammates (you, bots and unnamed players excluded).
pub fn records(ranked: &[Person]) -> Records<'_> {
    let mates: Vec<&Person> = ranked.iter().filter(|p| !p.me && !p.unranked).collect();
    Records {
        most_chests: first_max(&mates, |p| p.total),
        best_match: first_max(&mates, |p| p.best),
        most_played: first_max(&mates, |p| p.matches),
    }
}

pub struct ProfileRow {
    pub id: String,
    pub when: DateTime<Local>,
    pub mode: String,
    pub total: i64,
    pub opened: i64,
    pub broken: i64,
    pub types: Counter,
    pub mine: i64,
}

/// One player's matches with you, oldest first: their chests and yours in each.
pub fn profile(rows: &[MatchRow], key: &str) -> Vec<ProfileRow> {
    let mut order: Vec<&MatchRow> = rows.iter().collect();
    order.sort_by_key(|r| r.when);
    let mut out = Vec::new();
    for row in order {
        let Some(squad) = &row.squad else { continue };
        for p in squad.iter().filter(|p| p.key == key) {
            out.push(ProfileRow {
                id: row.id.clone(),
                when: row.when,
                mode: row.mode.clone(),
                total: p.total,
                opened: p.opened,
                broken: p.broken,
                types: p.types.clone(),
                mine: squad.iter().find(|q| q.me).map_or(0, |q| q.total),
            });
        }
    }
    out
}

fn median(values: &[i64]) -> Option<f64> {
    let mut v = values.to_vec();
    v.sort();
    let n = v.len();
    match n {
        0 => None,
        _ if n % 2 == 1 => Some(v[n / 2] as f64),
        _ => Some((v[n / 2 - 1] + v[n / 2]) as f64 / 2.0),
    }
}

fn first_of_month(d: NaiveDate) -> NaiveDate {
    d.with_day(1).expect("first of month")
}

pub fn compute(
    events: &[Ev],
    matches: &[MatchIn],
    now: DateTime<Local>,
    session_start: Option<DateTime<Local>>,
    include_broken: bool,
) -> Snapshot {
    let today = now.date_naive();
    let mut per_day: BTreeMap<NaiveDate, i64> = BTreeMap::new();
    let mut types = Counter::default();
    let mut match_types: HashMap<&str, Counter> = HashMap::new();
    let mut heat = [[0i64; 24]; 7];
    let mut broken = 0;
    for e in events {
        *per_day.entry(e.when.date_naive()).or_default() += e.amount;
        types.add(&e.chest_type, e.amount);
        heat[e.when.weekday().num_days_from_monday() as usize][e.when.hour() as usize] += e.amount;
        if e.source == "replay-broken" {
            broken += e.amount;
        }
        if let Some(id) = e.match_id.as_deref().filter(|s| !s.is_empty()) {
            match_types
                .entry(id)
                .or_default()
                .add(&e.chest_type, e.amount);
        }
    }

    let mut analyzed: Vec<&MatchIn> = matches.iter().filter(|m| m.meta.is_some()).collect();
    analyzed.sort_by_key(|m| m.started);
    let mut heat_matches = [[0i64; 24]; 7];
    let mut match_days: BTreeMap<NaiveDate, i64> = BTreeMap::new();
    for m in &analyzed {
        heat_matches[m.started.weekday().num_days_from_monday() as usize]
            [m.started.hour() as usize] += 1;
        *match_days.entry(m.started.date_naive()).or_default() += 1;
    }
    let analyzed_ids: HashSet<&str> = analyzed.iter().map(|m| m.id.as_str()).collect();
    let mut modes: Vec<(String, Mode)> = Vec::new();
    let (mut containers, mut team_types, mut team_containers) =
        (Counter::default(), Counter::default(), Counter::default());
    let (mut team_opened, mut team_broken, mut unattributed) = (0, 0, 0);
    let mut rows = Vec::new();
    let empty = Value::Null;
    for m in matches {
        let meta = m.meta.as_ref().unwrap_or(&empty);
        let analyzed_row = analyzed_ids.contains(m.id.as_str());
        let mut team = 0;
        for (name, counts) in meta["team"].as_object().into_iter().flatten() {
            let opened_n = counts["opened"].as_i64().unwrap_or(0);
            let broken_n = counts["broken"].as_i64().unwrap_or(0);
            let count = opened_n + if include_broken { broken_n } else { 0 };
            team += count;
            if analyzed_row {
                team_types.add(name, count);
                team_opened += opened_n;
                team_broken += if include_broken { broken_n } else { 0 };
            }
        }
        let squad_rows = meta.get("players").map(|_| squad(meta, include_broken));
        let mode_name = meta["mode"]
            .as_str()
            .filter(|s| !s.is_empty())
            .map(str::to_owned);
        if analyzed_row {
            let name = mode_name.clone().unwrap_or_else(|| "Unknown mode".into());
            match modes.iter_mut().find(|(n, _)| *n == name) {
                Some((_, b)) => {
                    b.matches += 1;
                    b.chests += m.total;
                }
                None => modes.push((
                    name,
                    Mode {
                        matches: 1,
                        chests: m.total,
                    },
                )),
            }
            for (name, n) in meta["containers"].as_object().into_iter().flatten() {
                containers.add(name, n.as_i64().unwrap_or(0));
            }
            unattributed += meta["unattributed"].as_i64().unwrap_or(0);
            for p in squad_rows.iter().flatten().filter(|p| !p.me) {
                for (name, n) in &p.containers.items {
                    team_containers.add(name, *n);
                }
            }
        }
        let has_meta = meta.as_object().is_some_and(|o| !o.is_empty());
        rows.push(MatchRow {
            id: m.id.clone(),
            when: m.started,
            seconds: m.seconds,
            count: m.total,
            broken: m.broken,
            mode: mode_name.unwrap_or_else(|| {
                if has_meta {
                    "Unknown mode".into()
                } else {
                    "Manual".into()
                }
            }),
            types: match_types.get(m.id.as_str()).cloned().unwrap_or_default(),
            team,
            ammo: meta["containers"]["Ammo box"].as_i64().unwrap_or(0),
            placement: meta["placement"].as_i64(),
            players: meta["total_players"].as_i64(),
            teammates: meta["teammates"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|n| n.as_str().filter(|s| !s.is_empty()).map(str::to_owned))
                .collect(),
            mvp: squad_rows.as_deref().and_then(mvp),
            squad_total: squad_rows.iter().flatten().map(|p| p.total).sum(),
            squad: squad_rows,
            unattributed: meta["unattributed"].as_i64().unwrap_or(0),
            stats: meta
                .get("stats")
                .filter(|s| s.as_object().is_some_and(|o| !o.is_empty()))
                .cloned(),
            note: m.note.clone(),
            tags: m.tags.clone(),
            favorite: m.favorite,
        });
    }
    rows.sort_by_key(|r| std::cmp::Reverse(r.when));

    let totals: Vec<i64> = analyzed.iter().map(|m| m.total).collect();
    let replay_chests: i64 = totals.iter().sum();
    let playtime: f64 = analyzed.iter().map(|m| m.seconds).sum();
    let team_total = team_types.total();
    let mut best_day: Option<(NaiveDate, i64)> = None;
    for (&day, &v) in &per_day {
        if best_day.is_none_or(|(_, b)| v > b) {
            best_day = Some((day, v));
        }
    }
    let (streak_longest, streak_current) = streaks(&per_day, today);
    let month = first_of_month(today);
    let week = today - Duration::days(today.weekday().num_days_from_monday() as i64);
    let last_week = week - Duration::days(7);
    let last_month = first_of_month(month - Duration::days(1));
    let day = Duration::days(1);
    let n = analyzed.len() as f64;
    let last = rows
        .iter()
        .find(|r| analyzed_ids.contains(r.id.as_str()))
        .cloned();
    let board = board(&rows);
    Snapshot {
        today_date: today,
        all: per_day.values().sum(),
        broken,
        types,
        containers,
        modes,
        today: per_day.get(&today).copied().unwrap_or(0),
        today_prev: per_day.get(&(today - day)).copied().unwrap_or(0),
        week: span(&per_day, week, today),
        week_prev: span(&per_day, last_week, last_week + (today - week)),
        month: span(&per_day, month, today),
        month_prev: span(&per_day, last_month, last_month + (today - month)),
        session: events
            .iter()
            .filter(|e| session_start.is_some_and(|s| e.when >= s))
            .map(|e| e.amount)
            .sum(),
        matches: analyzed.len() as i64,
        match_chests: replay_chests,
        avg: (!analyzed.is_empty()).then(|| replay_chests as f64 / n),
        median: median(&totals),
        best: totals.iter().max().copied(),
        worst: totals.iter().min().copied(),
        recent_totals: totals[totals.len().saturating_sub(RECENT)..].to_vec(),
        playtime,
        per_hour: if playtime > 0.0 {
            replay_chests as f64 * 3600.0 / playtime
        } else {
            0.0
        },
        last,
        best_day: best_day.filter(|(_, v)| *v != 0),
        streak_longest,
        streak_current,
        session_best: longest_session(&analyzed),
        peak_hour: if events.is_empty() {
            (0, None)
        } else {
            peak_hour(events)
        },
        heat,
        heat_matches,
        match_days,
        team_total,
        team_types,
        team_opened,
        team_broken,
        team_containers,
        unattributed,
        board,
        older_matches: analyzed
            .iter()
            .filter(|m| m.meta.as_ref().is_some_and(|v| v.get("players").is_none()))
            .count() as i64,
        team_per_match: (!analyzed.is_empty()).then(|| team_total as f64 / n),
        your_share: (replay_chests + team_total != 0)
            .then(|| replay_chests as f64 / (replay_chests + team_total) as f64),
        player: analyzed
            .last()
            .and_then(|m| m.meta.as_ref()?["owner"].as_str().map(str::to_owned)),
        partial: analyzed
            .iter()
            .filter(|m| {
                !m.meta
                    .as_ref()
                    .and_then(|v| v["complete"].as_bool())
                    .unwrap_or(true)
            })
            .count() as i64,
        per_day,
        match_rows: rows,
    }
}

/// Finished matches grouped into play sessions (gap over 30 minutes starts a new one), newest first.
pub fn sessions(rows: &[MatchRow]) -> Vec<Session> {
    let mut order: Vec<&MatchRow> = rows.iter().filter(|r| r.mode != "Manual").collect();
    order.sort_by_key(|r| r.when);
    let gap = Duration::minutes(SESSION_GAP_MINUTES);
    let mut result: Vec<Session> = Vec::new();
    for row in order {
        let end = row.when + seconds(row.seconds);
        match result.last_mut() {
            Some(c) if row.when - c.end <= gap => {
                c.end = c.end.max(end);
                c.matches += 1;
                c.chests += row.count;
                c.seconds += row.seconds;
            }
            _ => result.push(Session {
                start: row.when,
                end,
                matches: 1,
                chests: row.count,
                seconds: row.seconds,
                per_hour: 0.0,
            }),
        }
    }
    for s in &mut result {
        s.per_hour = if s.seconds > 0.0 {
            s.chests as f64 * 3600.0 / s.seconds
        } else {
            0.0
        };
    }
    result.reverse();
    result
}

pub struct Goal {
    pub name: &'static str,
    pub target: i64,
    pub done: i64,
    pub share: f64,
    pub reached: bool,
}

/// Progress towards the daily and weekly goals (0 = off).
pub fn goals(snap: &Snapshot, daily: i64, weekly: i64) -> Vec<Goal> {
    [
        ("Today", daily, snap.today),
        ("This week", weekly, snap.week),
    ]
    .into_iter()
    .filter(|(_, target, _)| *target > 0)
    .map(|(name, target, done)| Goal {
        name,
        target,
        done,
        share: (done as f64 / target as f64).min(1.0),
        reached: done >= target,
    })
    .collect()
}

pub struct Achievement {
    pub id: String,
    pub title: String,
    pub detail: String,
    pub unlocked: bool,
}

pub const MILESTONES: [i64; 7] = [100, 500, 1000, 2500, 5000, 10000, 25000];
pub const BEST_MATCH: [i64; 3] = [25, 40, 60];

fn grouped(n: i64) -> String {
    let digits = n.to_string();
    let mut out = String::new();
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    out
}

/// Every achievement, unlocked or not.
pub fn achievements(snap: &Snapshot) -> Vec<Achievement> {
    let (total, best) = (snap.all, snap.best.unwrap_or(0));
    let mut items: Vec<(String, String, String, bool)> = MILESTONES
        .iter()
        .map(|&n| {
            (
                format!("chests-{n}"),
                format!("{} chests", grouped(n)),
                format!("Open {} chests in total", grouped(n)),
                total >= n,
            )
        })
        .collect();
    items.extend(BEST_MATCH.iter().map(|&n| {
        (
            format!("match-{n}"),
            format!("{n} in one match"),
            format!("Open {n} chests in a single match"),
            best >= n,
        )
    }));
    let fixed = [
        (
            "first-relic",
            "First relic chest",
            "Open a relic chest",
            snap.types.get("Relic chest") > 0,
        ),
        (
            "first-buried",
            "Treasure hunter",
            "Dig up a buried chest",
            snap.types.get("Buried chest") > 0,
        ),
        (
            "first-sprite",
            "Sprite poster",
            "Open a sprite poster chest",
            snap.types.get("Sprite poster chest") > 0,
        ),
        (
            "streak-7",
            "Week streak",
            "Open chests 7 days in a row",
            snap.streak_longest >= 7,
        ),
        (
            "matches-100",
            "100 matches",
            "Have 100 matches read from replays",
            snap.matches >= 100,
        ),
    ];
    items.extend(
        fixed
            .iter()
            .map(|(i, t, d, u)| (i.to_string(), t.to_string(), d.to_string(), *u)),
    );
    items
        .into_iter()
        .map(|(id, title, detail, unlocked)| Achievement {
            id,
            title,
            detail,
            unlocked,
        })
        .collect()
}

pub struct Period {
    pub chests: i64,
    pub matches: i64,
    pub broken: i64,
    pub per_match: f64,
}

/// Chests, matches and broken-open chests between two dates (inclusive).
pub fn period(snap: &Snapshot, start: NaiveDate, end: NaiveDate) -> Period {
    let rows: Vec<&MatchRow> = snap
        .match_rows
        .iter()
        .filter(|r| (start..=end).contains(&r.when.date_naive()))
        .collect();
    let played: Vec<&&MatchRow> = rows.iter().filter(|r| r.mode != "Manual").collect();
    let matches = played.len() as i64;
    Period {
        chests: span(&snap.per_day, start, end),
        matches,
        broken: rows.iter().map(|r| r.broken).sum(),
        per_match: if matches > 0 {
            played.iter().map(|r| r.count).sum::<i64>() as f64 / matches as f64
        } else {
            0.0
        },
    }
}

/// Two periods side by side with the change: (name, first, second, change).
pub fn compare(
    snap: &Snapshot,
    first: (NaiveDate, NaiveDate),
    second: (NaiveDate, NaiveDate),
) -> Vec<(&'static str, f64, f64, f64)> {
    let (a, b) = (
        period(snap, first.0, first.1),
        period(snap, second.0, second.1),
    );
    [
        ("Chests", a.chests as f64, b.chests as f64),
        ("Matches", a.matches as f64, b.matches as f64),
        ("Chests per match", a.per_match, b.per_match),
        ("Broken open", a.broken as f64, b.broken as f64),
    ]
    .into_iter()
    .map(|(n, x, y)| (n, x, y, y - x))
    .collect()
}

/// Drop rate for the Pirate Shop Token for a match started at `when`.
///
/// Default rate is 1 in 137,500 (~0.000727%).
/// During Saturday Treasure Hours (Fortnite.GG drop rates):
/// - Session 1: 14:00 - 16:00 ET (19:00 - 21:00 UTC) -> 1 in 91,667 (1.5× boost)
/// - Session 2: 21:00 - 23:00 ET (02:00 - 04:00 UTC Sunday) -> 1 in 91,667 (1 in 68,750 on Nov 7)
pub fn token_rate(when: &DateTime<Local>) -> f64 {
    let utc = when.to_utc();
    let weekday = utc.weekday();
    let hour = utc.hour();

    // Nov 7 evening window (02:00 - 04:00 UTC on Nov 8) had a special 2x boost (1 in 68,750)
    if utc.date_naive() == NaiveDate::from_ymd_opt(2026, 11, 8).unwrap() && (2..4).contains(&hour) {
        return 1.0 / 68750.0;
    }

    // Weekly Saturday Treasure Hours (1.5x boost: 1 in 91,667)
    // Session 1: Saturday 19:00 - 21:00 UTC
    // Session 2: Sunday 02:00 - 04:00 UTC (Saturday evening in North America)
    if (weekday == chrono::Weekday::Sat && (19..21).contains(&hour))
        || (weekday == chrono::Weekday::Sun && (2..4).contains(&hour))
    {
        return 1.0 / 91667.0;
    }

    1.0 / 137500.0
}

pub fn is_treasure_hour(when: &DateTime<Local>) -> bool {
    token_rate(when) > (1.0 / 137500.0) + 1e-12
}

#[derive(Debug, Clone, PartialEq)]
pub struct TokenDayPoint {
    pub date: NaiveDate,
    pub matches: i64,
    pub chests_me: i64,
    pub chests_squad: i64,
    pub cum_chests_me: i64,
    pub cum_chests_squad: i64,
    pub cum_prob_me: f64,
    pub cum_prob_squad: f64,
    pub had_treasure_hour: bool,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct TokenSummary {
    pub total_chests_me: i64,
    pub total_chests_squad: i64,
    pub prob_me: f64,
    pub prob_squad: f64,
    pub treasure_hour_chests: i64,
    pub days: Vec<TokenDayPoint>,
    pub recent_cum_probs: Vec<f64>,
}

pub fn token_summary(snap: &Snapshot) -> TokenSummary {
    if snap.match_rows.is_empty() {
        return TokenSummary::default();
    }

    let mut matches = snap.match_rows.clone();
    matches.sort_by_key(|m| m.when);

    let mut days_points: BTreeMap<NaiveDate, TokenDayPoint> = BTreeMap::new();
    let mut log_not_me = 0.0f64;
    let mut log_not_squad = 0.0f64;
    let mut cum_me = 0i64;
    let mut cum_squad = 0i64;
    let mut th_chests = 0i64;

    for m in &matches {
        let me = m.count.max(0);
        let sq = m.squad_total.max(me).max(0);
        let rate = token_rate(&m.when);
        let is_th = is_treasure_hour(&m.when);

        if is_th {
            th_chests += sq;
        }

        cum_me += me;
        cum_squad += sq;

        let ln_fail = (1.0 - rate).ln();
        log_not_me += me as f64 * ln_fail;
        log_not_squad += sq as f64 * ln_fail;

        let day = m.when.date_naive();
        let prob_me = 1.0 - log_not_me.exp();
        let prob_sq = 1.0 - log_not_squad.exp();

        let entry = days_points.entry(day).or_insert_with(|| TokenDayPoint {
            date: day,
            matches: 0,
            chests_me: 0,
            chests_squad: 0,
            cum_chests_me: 0,
            cum_chests_squad: 0,
            cum_prob_me: 0.0,
            cum_prob_squad: 0.0,
            had_treasure_hour: false,
        });

        entry.matches += 1;
        entry.chests_me += me;
        entry.chests_squad += sq;
        entry.cum_chests_me = cum_me;
        entry.cum_chests_squad = cum_squad;
        entry.cum_prob_me = prob_me;
        entry.cum_prob_squad = prob_sq;
        if is_th {
            entry.had_treasure_hour = true;
        }
    }

    let days: Vec<TokenDayPoint> = days_points.into_values().collect();
    let recent_cum_probs: Vec<f64> = days
        .iter()
        .rev()
        .take(14)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .map(|d| d.cum_prob_squad * 100.0)
        .collect();

    let final_prob_me = 1.0 - log_not_me.exp();
    let final_prob_squad = 1.0 - log_not_squad.exp();

    TokenSummary {
        total_chests_me: cum_me,
        total_chests_squad: cum_squad,
        prob_me: final_prob_me,
        prob_squad: final_prob_squad,
        treasure_hour_chests: th_chests,
        days,
        recent_cum_probs,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn at(d: u32, h: u32, m: u32) -> DateTime<Local> {
        Local.with_ymd_and_hms(2026, 11, d, h, m, 0).unwrap()
    }

    fn ev(when: DateTime<Local>, amount: i64, kind: &str, source: &str) -> Ev {
        Ev {
            when,
            amount,
            chest_type: kind.into(),
            source: source.into(),
            match_id: Some("m1".into()),
        }
    }

    #[test]
    fn totals_streaks_and_periods() {
        let events = vec![
            ev(at(2, 10, 0), 3, "Chest", "replay"),
            ev(at(3, 10, 0), 2, "Rare chest", "replay-broken"),
            ev(at(5, 10, 0), 4, "Chest", "replay"),
            ev(at(6, 10, 30), 5, "Chest", "replay"),
            ev(at(6, 11, 0), 1, "Chest", "replay"),
        ];
        let meta = serde_json::json!({"mode": "Solo", "players": [{"key": "epic-a", "name": "Me", "me": true, "bot": false,
            "counts": {"Chest": {"opened": 9, "broken": 0}}}, {"key": "epic-b", "name": "Mate", "me": false, "bot": false,
            "counts": {"Chest": {"opened": 4, "broken": 1}}}], "team": {"Chest": {"opened": 4, "broken": 1}}});
        let m = MatchIn {
            id: "m1".into(),
            started: at(6, 10, 0),
            seconds: 1200.0,
            total: 15,
            broken: 2,
            meta: Some(meta),
            note: String::new(),
            tags: String::new(),
            favorite: false,
        };
        let s = compute(&events, &[m], at(6, 12, 0), None, true);
        assert_eq!((s.all, s.broken, s.today, s.today_prev), (15, 2, 6, 4));
        assert_eq!((s.streak_longest, s.streak_current), (2, 2));
        assert_eq!(s.week, 15); // Monday 2 Nov to Friday 6 Nov holds every opening
        assert_eq!(s.peak_hour.0, 6);
        assert_eq!(s.team_total, 5);
        assert_eq!(s.board[0].name, "Me");
        assert_eq!(s.last.as_ref().unwrap().mvp.as_deref(), Some("epic-a"));
        assert_eq!(
            series(
                &s.per_day,
                Grain::Week,
                at(2, 0, 0).date_naive(),
                at(6, 0, 0).date_naive()
            ),
            vec![(at(2, 0, 0).date_naive(), 15)]
        );
        assert!(goals(&s, 6, 0)[0].reached);
        assert!(achievements(&s).iter().all(|a| !a.unlocked));
    }

    #[test]
    fn token_chance_math_and_treasure_hours() {
        use chrono::Utc;
        // Saturday 7 Nov 2026 19:30 UTC -> Saturday Session 1 (Treasure Hour)
        let th1_utc = Utc.with_ymd_and_hms(2026, 11, 7, 19, 30, 0).unwrap();
        let th1_local = DateTime::<Local>::from(th1_utc);
        assert!(is_treasure_hour(&th1_local));
        assert!((token_rate(&th1_local) - (1.0 / 91667.0)).abs() < 1e-12);

        // Sunday 8 Nov 2026 02:30 UTC -> Saturday 21:30 ET (Nov 7 special 2x window)
        let th2_utc = Utc.with_ymd_and_hms(2026, 11, 8, 2, 30, 0).unwrap();
        let th2_local = DateTime::<Local>::from(th2_utc);
        assert!(is_treasure_hour(&th2_local));
        assert!((token_rate(&th2_local) - (1.0 / 68750.0)).abs() < 1e-12);

        // Regular Monday match -> Standard 1 in 137,500
        let normal_utc = Utc.with_ymd_and_hms(2026, 11, 9, 14, 0, 0).unwrap();
        let normal_local = DateTime::<Local>::from(normal_utc);
        assert!(!is_treasure_hour(&normal_local));
        assert!((token_rate(&normal_local) - (1.0 / 137500.0)).abs() < 1e-12);

        // Test cumulative probability calculation
        // 95,310 chests at standard rate should yield approx 50% chance
        let m1 = MatchRow {
            id: "m1".into(),
            when: normal_local,
            seconds: 600.0,
            count: 45310,
            broken: 0,
            mode: "Squads".into(),
            types: Counter::default(),
            team: 95310,
            ammo: 0,
            placement: Some(1),
            players: Some(4),
            teammates: vec!["p2".into(), "p3".into(), "p4".into()],
            mvp: None,
            squad_total: 95310,
            squad: None,
            unattributed: 0,
            stats: None,
            note: String::new(),
            tags: String::new(),
            favorite: false,
        };

        let snap = Snapshot {
            today_date: NaiveDate::from_ymd_opt(2026, 11, 9).unwrap(),
            per_day: BTreeMap::new(),
            all: 45310,
            broken: 0,
            types: Counter::default(),
            containers: Counter::default(),
            modes: vec![],
            today: 0,
            today_prev: 0,
            week: 0,
            week_prev: 0,
            month: 0,
            month_prev: 0,
            session: 0,
            matches: 1,
            match_chests: 45310,
            avg: None,
            median: None,
            best: None,
            worst: None,
            recent_totals: vec![],
            playtime: 0.0,
            per_hour: 0.0,
            last: None,
            best_day: None,
            streak_longest: 0,
            streak_current: 0,
            session_best: None,
            peak_hour: (0, None),
            heat: [[0; 24]; 7],
            heat_matches: [[0; 24]; 7],
            match_days: BTreeMap::new(),
            team_total: 95310,
            team_types: Counter::default(),
            team_opened: 0,
            team_broken: 0,
            team_containers: Counter::default(),
            unattributed: 0,
            board: vec![],
            older_matches: 0,
            team_per_match: None,
            your_share: None,
            player: None,
            partial: 0,
            match_rows: vec![m1],
        };

        let summary = token_summary(&snap);
        assert_eq!(summary.total_chests_me, 45310);
        assert_eq!(summary.total_chests_squad, 95310);
        // At 95310 chests, squad prob should be very close to 50% (0.499997..)
        assert!((summary.prob_squad - 0.50).abs() < 0.005);
        // Personal prob at 45310 chests should be ~28%
        assert!((summary.prob_me - 0.28).abs() < 0.02);
        assert_eq!(summary.days.len(), 1);
        assert_eq!(summary.days[0].cum_chests_squad, 95310);
    }
}
