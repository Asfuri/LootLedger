//! Delilah treasure hunt prize catalog, ASCII template-id extraction, and gizmo helpers.
//! Mirrors LED-N/Fortnite-ChestCounter (`TreasureCatalog.cs` and `ReplayAnalyzer.cs`) so
//! weekly prizes, Pirate Shop Access, and gizmo weapons resolve cleanly offline and sync
//! new weeks automatically from `content/content.json`.

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const PIRATE_SHOP_PRIZE_ID: &str = "9f73f94d-2e61-4523-97d7-d61235d3365e";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PrizeDef {
    pub prize_id: String,
    pub item: String,
    pub kind: String,
    #[serde(default)]
    pub week: u8,
    #[serde(default)]
    pub week_label: String,
}

const BUILTIN_ROWS: &[(&str, &str, &str, u8, &str)] = &[
    (
        PIRATE_SHOP_PRIZE_ID,
        "Pirate Shop Access",
        "pirate-shop",
        0,
        "",
    ),
    // Week 1: A$AP Arrives
    (
        "DelilahPrize:dpid_item1",
        "Solid Gold A$AP Rocky",
        "outfit",
        1,
        "A$AP Arrives",
    ),
    (
        "DelilahPrize:dpid_item2",
        "Solid Gold A$AP Rocky's Gauntlets",
        "pickaxe",
        1,
        "A$AP Arrives",
    ),
    (
        "DelilahPrize:dpid_item3",
        "No Trespassing",
        "jam",
        1,
        "A$AP Arrives",
    ),
    (
        "DelilahPrize:dpid_item4",
        "Plunder in Paradise",
        "loading",
        1,
        "A$AP Arrives",
    ),
    (
        "DelilahPrize:dpid_item5",
        "Gold Mercedes-AMG G 63 Decal",
        "car",
        1,
        "A$AP Arrives",
    ),
    // Week 2: Lil Uzi Arrives
    (
        "DelilahPrize:dpid_item14",
        "Solid Gold Lil Uzi Vert",
        "outfit",
        2,
        "Lil Uzi Arrives",
    ),
    (
        "DelilahPrize:dpid_item15",
        "Diamond and Gold",
        "pickaxe",
        2,
        "Lil Uzi Arrives",
    ),
    (
        "DelilahPrize:dpid_item16",
        "London",
        "jam",
        2,
        "Lil Uzi Arrives",
    ),
    (
        "DelilahPrize:dpid_item17",
        "So Kawaii",
        "loading",
        2,
        "Lil Uzi Arrives",
    ),
    (
        "DelilahPrize:dpid_item18",
        "Gold Cadillac CT5-V Decal",
        "car",
        2,
        "Lil Uzi Arrives",
    ),
    // Week 3: Miku & Teto Arrive
    (
        "DelilahPrize:dpid_item19",
        "Solid Gold Miku",
        "outfit",
        3,
        "Miku & Teto Arrive",
    ),
    (
        "DelilahPrize:dpid_item20",
        "Miku's Takarabako",
        "pickaxe",
        3,
        "Miku & Teto Arrive",
    ),
    (
        "DelilahPrize:dpid_item21",
        "PPPP",
        "jam",
        3,
        "Miku & Teto Arrive",
    ),
    (
        "DelilahPrize:dpid_item22",
        "May Fortune Find You",
        "loading",
        3,
        "Miku & Teto Arrive",
    ),
    (
        "DelilahPrize:dpid_item23",
        "Gold Chevrolet Corvette ZR1 Decal",
        "car",
        3,
        "Miku & Teto Arrive",
    ),
    // Week 4: Oscar Arrives
    (
        "DelilahPrize:dpid_item24",
        "Week 4 Gold Outfit",
        "outfit",
        4,
        "Oscar Arrives",
    ),
    (
        "DelilahPrize:dpid_item25",
        "Week 4 Pickaxe or Back Bling",
        "pickaxe",
        4,
        "Oscar Arrives",
    ),
    (
        "DelilahPrize:dpid_item26",
        "Week 4 Jam Track",
        "jam",
        4,
        "Oscar Arrives",
    ),
    (
        "DelilahPrize:dpid_item27",
        "Week 4 Loading Screen",
        "loading",
        4,
        "Oscar Arrives",
    ),
    (
        "DelilahPrize:dpid_item28",
        "Week 4 Vehicle & Decal",
        "car",
        4,
        "Oscar Arrives",
    ),
    // Week 5: The Final Hunt
    (
        "DelilahPrize:dpid_item29",
        "Week 5 Gold Outfit",
        "outfit",
        5,
        "The Final Hunt",
    ),
    (
        "DelilahPrize:dpid_item30",
        "Week 5 Pickaxe or Back Bling",
        "pickaxe",
        5,
        "The Final Hunt",
    ),
    (
        "DelilahPrize:dpid_item31",
        "Week 5 Jam Track",
        "jam",
        5,
        "The Final Hunt",
    ),
    (
        "DelilahPrize:dpid_item32",
        "Week 5 Loading Screen",
        "loading",
        5,
        "The Final Hunt",
    ),
    (
        "DelilahPrize:dpid_item33",
        "Week 5 Vehicle & Decal",
        "car",
        5,
        "The Final Hunt",
    ),
];

pub fn builtin_prizes() -> Vec<PrizeDef> {
    BUILTIN_ROWS
        .iter()
        .map(|(prize_id, item, kind, week, week_label)| PrizeDef {
            prize_id: (*prize_id).into(),
            item: (*item).into(),
            kind: (*kind).into(),
            week: *week,
            week_label: (*week_label).into(),
        })
        .collect()
}

/// Parses prize definitions from LED-N's `content/content.json` (`pirateShop` and `weeks`).
pub fn parse_ledn_prizes(text: &str) -> Result<Vec<PrizeDef>, String> {
    let root: Value = serde_json::from_str(text).map_err(|e| format!("Invalid JSON: {e}"))?;
    let mut out = Vec::new();
    let push_prize = |obj: &Value, week: u8, week_label: &str, out: &mut Vec<PrizeDef>| {
        let Some(name) = obj["name"]
            .as_str()
            .map(str::trim)
            .filter(|s| !s.is_empty())
        else {
            return;
        };
        let kind = obj["kind"]
            .as_str()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .unwrap_or("other");
        for pid in obj["prizeIds"].as_array().into_iter().flatten() {
            if let Some(id) = pid.as_str().map(str::trim).filter(|s| !s.is_empty()) {
                out.push(PrizeDef {
                    prize_id: id.to_owned(),
                    item: name.to_owned(),
                    kind: kind.to_owned(),
                    week,
                    week_label: week_label.to_owned(),
                });
            }
        }
    };
    if root.get("pirateShop").is_some_and(Value::is_object) {
        push_prize(&root["pirateShop"], 0, "", &mut out);
    }
    for w in root["weeks"].as_array().into_iter().flatten() {
        let week = w["number"].as_u64().unwrap_or(0).min(u8::MAX as u64) as u8;
        let title = w["title"].as_str().unwrap_or("").trim();
        for p in w["prizes"].as_array().into_iter().flatten() {
            push_prize(p, week, title, &mut out);
        }
    }
    if out.is_empty() {
        return Err("No prize definitions found in content.json".into());
    }
    Ok(out)
}

/// Resolves a golden-chest `prize_id`, checking synced definitions before the built-in table.
pub fn resolve_prize(prize_id: &str, synced: &[PrizeDef]) -> Option<PrizeDef> {
    let id = prize_id.trim();
    if id.is_empty() {
        return None;
    }
    let find_in = |list: &[PrizeDef]| -> Option<PrizeDef> {
        list.iter()
            .find(|p| p.prize_id.eq_ignore_ascii_case(id))
            .cloned()
    };
    if let Some(hit) = find_in(synced) {
        return Some(hit);
    }
    if let Some((prefix, item, kind, week, week_label)) = BUILTIN_ROWS
        .iter()
        .find(|(pid, ..)| pid.eq_ignore_ascii_case(id))
    {
        return Some(PrizeDef {
            prize_id: (*prefix).into(),
            item: (*item).into(),
            kind: (*kind).into(),
            week: *week,
            week_label: (*week_label).into(),
        });
    }
    None
}

fn is_ident_tail(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_'
}

fn is_prize_tail(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-')
}

fn is_uuid_slice(s: &[u8]) -> bool {
    if s.len() != 36 {
        return false;
    }
    for (i, &b) in s.iter().enumerate() {
        let expected_dash = matches!(i, 8 | 13 | 18 | 23);
        if expected_dash {
            if b != b'-' {
                return false;
            }
        } else if !b.is_ascii_hexdigit() {
            return false;
        }
    }
    true
}

/// Extracts `"DelilahPrize:dpid_item4"` or a bare UUID (`9f73f94d-2e61-4523-97d7-d61235d3365e`)
/// from the raw bit payload of `BGA_DelilahTreasureHuntAnimatedChest::PrizeTemplateId`.
pub fn extract_prize_id(bytes: &[u8]) -> Option<String> {
    let ascii: Vec<u8> = bytes
        .iter()
        .map(|&b| if (32..127).contains(&b) { b } else { b' ' })
        .collect();

    let n = ascii.len();
    let mut i = 0;
    while i < n {
        if ascii[i] == b':' && i > 0 && i + 1 < n && is_prize_tail(ascii[i + 1]) {
            let mut start = i;
            while start > 0 && is_ident_tail(ascii[start - 1]) {
                start -= 1;
            }
            if start < i && ascii[start].is_ascii_alphabetic() {
                let mut end = i + 1;
                while end < n && is_prize_tail(ascii[end]) {
                    end += 1;
                }
                return Some(String::from_utf8_lossy(&ascii[start..end]).into_owned());
            }
        }
        if i + 36 <= n && is_uuid_slice(&ascii[i..i + 36]) {
            return Some(String::from_utf8_lossy(&ascii[i..i + 36]).to_ascii_lowercase());
        }
        i += 1;
    }
    None
}

pub fn is_golden_chest(path: &str) -> bool {
    if path.contains(':') {
        return false;
    }
    let seg = path.rsplit(['.', '/']).next().unwrap_or(path);
    seg.to_ascii_lowercase()
        .starts_with("bga_delilahtreasurehuntanimatedchest")
}

pub fn is_ability_system_component(path: &str) -> bool {
    !path.contains(':')
        && (path.ends_with("AbilitySystemComponent")
            || path.ends_with("AbilitySystemComponentAthena"))
}

pub fn is_event_consumable(path: &str) -> bool {
    path.to_ascii_lowercase()
        .contains("relicextractor_consumable")
}

pub fn is_treasure_weapon_blueprint(path: &str) -> bool {
    if path.contains(':') || !path.ends_with("_C") || is_event_consumable(path) {
        return false;
    }
    let lower = path.to_ascii_lowercase();
    [
        "flameceleb",
        "relicextractor",
        "relicfinder",
        "luckylocator",
        "smugglerextractionkey",
        "extractionaccelerat",
    ]
    .iter()
    .any(|k| lower.contains(k))
}

pub fn is_treasure_item(path: &str) -> bool {
    if is_event_consumable(path) {
        return false;
    }
    let lower = path.to_ascii_lowercase();
    [
        "relicextractor",
        "relicfinder",
        "luckylocator",
        "flameceleb",
        "smugglerextractionkey",
        "extractionaccelerat",
        "treasure",
        "pirateshop",
        "delilahshop",
    ]
    .iter()
    .any(|k| lower.contains(k))
}

/// Maps a gizmo blueprint/WID name (`WID_RelicFinder`, `B_FlameCeleb_C`, ...) to `(canonical_id, english_name)`.
pub fn gizmo_item_name(raw: &str) -> Option<(&'static str, &'static str)> {
    if raw.is_empty() || is_event_consumable(raw) {
        return None;
    }
    let normalized: String = raw
        .chars()
        .filter(|c| !matches!(c, '-' | '_' | ' '))
        .flat_map(|c| c.to_lowercase())
        .collect();
    for (needle, id, name) in [
        ("relicextractor", "gizmo:relic-extractor", "Relic Extractor"),
        ("relicfinder", "gizmo:relic-finder", "Relic Finder"),
        ("luckylocator", "gizmo:lucky-locator", "Lucky Locator"),
        ("flameceleb", "gizmo:flame-celeb", "Flame Flare"),
        ("flameflare", "gizmo:flame-celeb", "Flame Flare"),
        (
            "smugglerextractionkey",
            "gizmo:smuggler-key",
            "Smuggler Extraction Key",
        ),
        (
            "smugglerkey",
            "gizmo:smuggler-key",
            "Smuggler Extraction Key",
        ),
        (
            "extractionaccelerat",
            "gizmo:extraction-accelerator",
            "Extraction Accelerator",
        ),
        ("pirateshop", "gizmo:pirate-shop", "Pirate Shop Item"),
        ("delilahshop", "gizmo:pirate-shop", "Pirate Shop Item"),
        ("treasure", "gizmo:treasure", "Treasure Gizmo"),
    ] {
        if normalized.contains(needle) {
            return Some((id, name));
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_delilah_prize_ids_and_bare_guids() {
        let payload = b"\x01\x00\x17\0\0\0DelilahPrize:dpid_item19\0\x05\xff";
        assert_eq!(
            extract_prize_id(payload).as_deref(),
            Some("DelilahPrize:dpid_item19")
        );

        let token = b"\x00\x029F73F94D-2E61-4523-97D7-D61235D3365E\x00";
        assert_eq!(
            extract_prize_id(token).as_deref(),
            Some(PIRATE_SHOP_PRIZE_ID)
        );

        assert_eq!(extract_prize_id(b"\x01\x02\x03\x04"), None);
    }

    #[test]
    fn parses_ledn_prizes_and_resolves_overrides() {
        let json = r#"{
            "pirateShop": {
                "kind": "pirate-shop",
                "name": "Pirate Shop Access",
                "prizeIds": ["9f73f94d-2e61-4523-97d7-d61235d3365e"]
            },
            "weeks": [
                {
                    "number": 4,
                    "title": "Oscar Arrives",
                    "prizes": [
                        {
                            "kind": "outfit",
                            "name": "Solid Gold Oscar",
                            "prizeIds": ["DelilahPrize:dpid_item24"]
                        }
                    ]
                }
            ]
        }"#;
        let synced = parse_ledn_prizes(json).unwrap();
        assert_eq!(synced.len(), 2);

        let resolved = resolve_prize("delilahprize:dpid_item24", &synced).unwrap();
        assert_eq!(resolved.item, "Solid Gold Oscar");
        assert_eq!(resolved.week, 4);

        let builtin = resolve_prize("DelilahPrize:dpid_item19", &synced).unwrap();
        assert_eq!(builtin.item, "Solid Gold Miku");
        assert_eq!(builtin.kind, "outfit");
    }

    #[test]
    fn excludes_event_consumable_and_identifies_gizmos() {
        assert!(!is_treasure_weapon_blueprint(
            "/Game/.../B_RelicExtractor_Consumable.B_RelicExtractor_Consumable_C"
        ));
        assert!(is_treasure_weapon_blueprint(
            "/Game/.../B_RelicFinder.B_RelicFinder_C"
        ));
        assert_eq!(
            gizmo_item_name("WID_RelicExtractor_Consumable_Athena"),
            None
        );
        assert_eq!(
            gizmo_item_name("WID_FlameCeleb"),
            Some(("gizmo:flame-celeb", "Flame Flare"))
        );
    }
}
