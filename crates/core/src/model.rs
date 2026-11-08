//! Stable identities and attribution, matching lootledger/replay_reader.py.
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use uuid::Uuid;

pub const NAMESPACE: Uuid = Uuid::from_u128(0x2f9c6a4e8d1b4e579b0a6c3e1d7f5a21);

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Player {
    pub epic_id: Option<String>,
    pub name: Option<String>,
    pub team: Option<i64>,
    pub bot: Option<bool>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Opening {
    pub t: f64,
    pub cls: String,
    pub kind: String,
    pub by: String,
    pub player: Option<String>,
    pub player_id: Option<String>,
    pub pawn: Option<u32>,
    pub actor: u32,
    pub episode: u32,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Replay {
    pub file: String,
    pub ok: bool,
    #[serde(default)]
    pub live: bool,
    pub timestamp: Option<String>,
    #[serde(default)]
    pub length_seconds: f64,
    pub session_id: Option<String>,
    pub playlist: Option<String>,
    pub branch: Option<String>,
    pub team_size: Option<i64>,
    pub placement: Option<i64>,
    pub total_players: Option<i64>,
    pub eliminations: Option<i64>,
    /// Damage, accuracy, materials and more (Rust decoder only; absent in 0.7.1 results).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stats: Option<Value>,
    pub owner: Option<Player>,
    #[serde(default)]
    pub teammates: Vec<Player>,
    #[serde(default)]
    pub events: Vec<Opening>,
    pub error: Option<String>,
}

pub fn player_key(epic: Option<&str>, name: Option<&str>) -> Option<String> {
    if let Some(epic) = epic.filter(|s| !s.is_empty()) {
        let hash = Sha256::digest(epic.as_bytes());
        return Some(format!(
            "epic-{}",
            hash[..8]
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        ));
    }
    name.filter(|s| !s.is_empty())
        .map(|name| format!("name-{name}"))
}

pub fn classify(class: &str) -> (&'static str, bool) {
    let text = class.to_ascii_lowercase();
    for (pattern, name) in [
        ("ammo", "Ammo box"),
        ("foodbox", "Food box"),
        ("fishing", "Fishing barrel"),
    ] {
        if text.contains(pattern) {
            return (name, false);
        }
    }
    for (patterns, name) in [
        (&["rarechest"][..], "Rare chest"),
        (&["buriedchest"][..], "Buried chest"),
        (&["spriteposters", "booty_chest"][..], "Sprite poster chest"),
        (&["relic", "extraction"][..], "Relic chest"),
        (&["lootcannon"][..], "Loot cannon chest"),
        (
            &["tiered_chest", "normalchest", "factionchest"][..],
            "Chest",
        ),
        (&["chest"][..], "Other chest"),
    ] {
        if patterns.iter().any(|p| text.contains(p)) {
            return (name, true);
        }
    }
    ("Other container", false)
}

pub fn file_name(file: &str) -> &str {
    // Backslashes must work in fixtures and exports even when tests run on Linux.
    file.rsplit(['/', '\\']).next().unwrap_or(file)
}

pub fn mode_name(playlist: Option<&str>) -> String {
    let Some(playlist) = playlist.filter(|p| !p.is_empty()) else {
        return "Unknown mode".into();
    };
    let text = playlist.to_ascii_lowercase();
    if ![
        "playlist_default",
        "playlist_nobuildbr",
        "playlist_trios",
        "playlist_habanero",
    ]
    .iter()
    .any(|p| text.starts_with(p))
    {
        return if text.starts_with("playlist_") {
            playlist[9..].to_owned()
        } else {
            playlist.to_owned()
        };
    }
    let team = [
        ("solo", "Solo"),
        ("duo", "Duo"),
        ("trio", "Trio"),
        ("squad", "Squad"),
    ]
    .iter()
    .find(|(key, _)| text.contains(key))
    .map(|(_, v)| *v)
    .unwrap_or("");
    format!(
        "{}{} {team}",
        if text.contains("habanero") {
            "Ranked "
        } else {
            ""
        },
        if text.contains("nobuild") {
            "Zero Build"
        } else {
            "Build"
        }
    )
    .trim()
    .to_owned()
}

impl Replay {
    pub fn key(&self) -> String {
        self.session_id
            .as_ref()
            .filter(|s| !s.is_empty())
            .map(|session| {
                format!(
                    "{session}:{}",
                    self.owner
                        .as_ref()
                        .and_then(|p| p.epic_id.as_deref())
                        .filter(|s| !s.is_empty())
                        .unwrap_or("unknown")
                )
            })
            .unwrap_or_else(|| format!("file:{}", file_name(&self.file)))
    }
    pub fn match_id(&self) -> String {
        Uuid::new_v5(&NAMESPACE, self.key().as_bytes()).to_string()
    }
    pub fn event_id(&self, event: &Opening) -> String {
        Uuid::new_v5(
            &NAMESPACE,
            format!("{}:{}:{}", self.key(), event.actor, event.episode).as_bytes(),
        )
        .to_string()
    }
    pub fn validate(&self) -> Result<(), String> {
        if !self.length_seconds.is_finite()
            || !(0.0..=u32::MAX as f64 / 1000.0).contains(&self.length_seconds)
        {
            return Err("Invalid replay duration".into());
        }
        for e in &self.events {
            if !e.t.is_finite()
                || !(0.0..=u32::MAX as f64 / 1000.0).contains(&e.t)
                || !["opened", "broken"].contains(&e.kind.as_str())
                || !["me", "team", "other", "unknown"].contains(&e.by.as_str())
            {
                return Err("Invalid replay opening".into());
            }
        }
        Ok(())
    }
    pub fn summarize(&self) -> (Vec<(&Opening, &'static str)>, Value) {
        let owner = self.owner.clone().unwrap_or_default();
        let me = player_key(owner.epic_id.as_deref(), owner.name.as_deref())
            .unwrap_or_else(|| "me".into());
        let mut players: BTreeMap<String, Value> = BTreeMap::new();
        let mut order = vec![me.clone()];
        let seat = |key: &str, name: Option<&str>, team: Option<i64>, bot: bool| {
            json!({
                "key": key, "name": name.filter(|s| !s.is_empty()).unwrap_or("Teammate"), "me": key == me,
                "bot": bot, "team": team, "counts": {}, "containers": {}
            })
        };
        players.insert(
            me.clone(),
            seat(&me, owner.name.as_deref(), owner.team, false),
        );
        for mate in &self.teammates {
            if let Some(key) = player_key(mate.epic_id.as_deref(), mate.name.as_deref()) {
                if !players.contains_key(&key) {
                    order.push(key.clone());
                }
                players.entry(key.clone()).or_insert_with(|| {
                    seat(
                        &key,
                        mate.name.as_deref(),
                        mate.team,
                        mate.bot.unwrap_or(false),
                    )
                });
            }
        }
        let (mut mine, mut containers, mut team, mut teammates) =
            (Vec::new(), json!({}), json!({}), json!({}));
        let mut unattributed = 0;
        for event in &self.events {
            let (name, chest) = classify(&event.cls);
            if event.by == "unknown" {
                unattributed += i32::from(chest);
                continue;
            }
            if event.by != "me" && event.by != "team" {
                continue;
            }
            let key = if event.by == "me" {
                me.clone()
            } else {
                player_key(event.player_id.as_deref(), event.player.as_deref()).unwrap_or_else(
                    || {
                        format!(
                            "anon-{}",
                            event
                                .pawn
                                .map(|n| n.to_string())
                                .unwrap_or_else(|| "None".into())
                        )
                    },
                )
            };
            if !players.contains_key(&key) {
                order.push(key.clone());
            }
            let person = players
                .entry(key.clone())
                .or_insert_with(|| seat(&key, event.player.as_deref(), None, false));
            if event.by == "me" {
                if chest {
                    mine.push((event, name));
                } else {
                    increment(&mut containers, name);
                }
            } else if chest {
                count_type(&mut team, name, &event.kind);
                increment(
                    &mut teammates,
                    event
                        .player
                        .as_deref()
                        .filter(|s| !s.is_empty())
                        .unwrap_or("Teammate"),
                );
            }
            if chest {
                count_type(&mut person["counts"], name, &event.kind);
            } else {
                increment(&mut person["containers"], name);
            }
        }
        // Python's stable sort keeps first-seen order for equal names and counts.
        let mut ordered: Vec<Value> = order
            .into_iter()
            .map(|key| players.remove(&key).unwrap())
            .collect();
        let total = |p: &Value| {
            p["counts"]
                .as_object()
                .unwrap()
                .values()
                .map(|c| c["opened"].as_u64().unwrap_or(0) + c["broken"].as_u64().unwrap_or(0))
                .sum::<u64>()
        };
        ordered.sort_by(|a, b| {
            b["me"]
                .as_bool()
                .cmp(&a["me"].as_bool())
                .then_with(|| total(b).cmp(&total(a)))
                .then_with(|| a["name"].as_str().cmp(&b["name"].as_str()))
        });
        let mut meta = json!({
            "file": file_name(&self.file), "playlist": self.playlist, "mode": mode_name(self.playlist.as_deref()),
            "placement": self.placement, "total_players": self.total_players, "eliminations": self.eliminations,
            "length": self.length_seconds, "owner": owner.name, "owner_id": owner.epic_id,
            "teammates": self.teammates.iter().filter_map(|p| p.name.as_deref().filter(|s| !s.is_empty())).collect::<Vec<_>>(),
            "containers": containers, "team": team, "team_players": teammates, "complete": self.ok,
            "error": self.error, "branch": self.branch, "players": ordered, "unattributed": unattributed,
        });
        if let Some(stats) = &self.stats {
            meta["stats"] = stats.clone();
        }
        (mine, meta)
    }
}

fn increment(map: &mut Value, key: &str) {
    map[key] = json!(map[key].as_i64().unwrap_or(0) + 1);
}
fn count_type(map: &mut Value, name: &str, kind: &str) {
    if map[name].is_null() {
        map[name] = json!({"opened": 0, "broken": 0});
    }
    increment(&mut map[name], kind);
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ammo_does_not_count_even_when_class_contains_chest() {
        assert_eq!(classify("Tiered_Chest_Ammo_C"), ("Ammo box", false));
        assert_eq!(classify("Athena_RareChest_C"), ("Rare chest", true));
    }
    #[test]
    fn fixture_totals_and_stable_identities() {
        let r: Replay =
            serde_json::from_str(include_str!("../tests/fixtures/replay-squad.json")).unwrap();
        r.validate().unwrap();
        let (mine, meta) = r.summarize();
        assert!(!mine.is_empty());
        let owner = r.owner.as_ref().unwrap();
        assert_eq!(
            meta["players"][0]["key"],
            player_key(owner.epic_id.as_deref(), owner.name.as_deref()).unwrap()
        );
        assert_eq!(
            r.match_id(),
            Uuid::new_v5(&NAMESPACE, r.key().as_bytes()).to_string()
        );
        assert_eq!(mode_name(Some("Playlist_NoBuildBR_Duo")), "Zero Build Duo");
    }
}
