use lootledger_core::{model::Replay, store::Store};
use serde_json::json;
use std::{
    io::{self, BufRead, Write},
    path::Path,
};

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let mut out = io::BufWriter::new(io::stdout().lock());
    match args.first().map(String::as_str) {
        Some("export") if args.len() == 3 => { Store::read_only(&args[1])?.export(Path::new(&args[2]))?; }
        Some("import-jsonl") if args.len() == 4 && args[2] == "--into" => {
            let mut store = Store::open(&args[3])?;
            let mut imported = 0;
            for line in io::BufReader::new(std::fs::File::open(&args[1])?).lines() {
                let replay: Replay = serde_json::from_str(&line?)?;
                if store.import_replay(&replay, &replay.file, 1, 1.0)?.is_some() { imported += 1; }
            }
            writeln!(out, "{}", json!({"results_imported": imported, "totals": store.totals(true)?}))?;
        }
        Some("summarize-jsonl") if args.len() == 2 => {
            for line in io::BufReader::new(std::fs::File::open(&args[1])?).lines() {
                let replay: Replay = serde_json::from_str(&line?)?;
                replay.validate()?;
                let (mine, meta) = replay.summarize();
                let events: Vec<_> = mine.into_iter().map(|(event, kind)| {
                    let mut value = serde_json::to_value(event).expect("serializable event");
                    value["type"] = json!(kind);
                    value["id"] = json!(replay.event_id(event));
                    value
                }).collect();
                writeln!(out, "{}", json!({"key": replay.key(), "match_id": replay.match_id(), "events": events, "meta": meta}))?;
            }
        }
        Some("snapshot") if args.len() == 2 => {
            // The dashboard numbers, for comparing with the Python app's statistics.
            let s = Store::read_only(Path::new(&args[1]))?.snapshot(true, None)?;
            let days: serde_json::Map<String, serde_json::Value> = s.per_day.iter().map(|(d, v)| (d.to_string(), json!(v))).collect();
            writeln!(out, "{}", json!({
                "all": s.all, "broken": s.broken, "today": s.today, "today_prev": s.today_prev, "week": s.week,
                "week_prev": s.week_prev, "month": s.month, "month_prev": s.month_prev, "matches": s.matches,
                "match_chests": s.match_chests, "avg": s.avg, "median": s.median, "best": s.best, "worst": s.worst,
                "recent_totals": s.recent_totals, "playtime": s.playtime, "per_hour": s.per_hour,
                "streak_longest": s.streak_longest, "streak_current": s.streak_current, "peak_hour": s.peak_hour.0,
                "team_total": s.team_total, "team_opened": s.team_opened, "team_broken": s.team_broken,
                "unattributed": s.unattributed, "older_matches": s.older_matches, "partial": s.partial,
                "types": s.types.most_common(), "team_types": s.team_types.most_common(),
                "modes": s.modes.iter().map(|(n, m)| (n.clone(), m.matches, m.chests)).collect::<Vec<_>>(),
                "board": s.board.iter().map(|p| (p.key.clone(), p.matches, p.total, p.opened, p.broken, p.best, p.rare)).collect::<Vec<_>>(),
                "best_day": s.best_day.map(|(d, v)| (d.to_string(), v)), "per_day": days,
                "heat": s.heat, "sessions": lootledger_core::stats::sessions(&s.match_rows).iter().map(|x| (x.matches, x.chests)).collect::<Vec<_>>(),
                "last": s.last.as_ref().map(|r| (r.id.clone(), r.count, r.mvp.clone(), r.squad_total, r.team)),
                "rows": s.match_rows.iter().map(|r| (r.id.clone(), r.count, r.broken, r.mode.clone(), r.team, r.ammo, r.mvp.clone(), r.squad_total)).collect::<Vec<_>>(),
            }))?;
        }
        Some("ledger-summary") if args.len() == 2 => {
            let store = Store::read_only(Path::new(&args[1]))?;
            writeln!(out, "{}", json!({"totals": store.totals(true)?, "history": store.history(true, 0, u32::MAX)?}))?;
        }
        Some("inspect-replay") if args.len() == 2 => {
            use lootledger_core::container;
            let data = std::fs::read(&args[1])?;
            let info = container::read_info(&data)?;
            writeln!(out, "{}", json!({"live": info.live, "locked": info.locked(), "length_ms": info.length_ms,
                "chunks": container::chunks(&data, &info).count(), "chest_parser_ready": false}))?;
        }
        Some("decode") if args.len() >= 2 => {
            for file in &args[1..] {
                let replay = lootledger_core::replay::decode(file, &std::fs::read(file)?);
                writeln!(out, "{}", serde_json::to_string(&replay)?)?;
            }
        }
        _ => return Err("Usage: lootledger-cli summarize-jsonl RESULTS | import-jsonl RESULTS --into LEDGER | ledger-summary LEDGER | export LEDGER OUTPUT | inspect-replay REPLAY | decode REPLAY...".into()),
    }
    out.flush()?;
    Ok(())
}

fn main() {
    if let Err(e) = run() {
        eprintln!("{e}");
        std::process::exit(1);
    }
}
