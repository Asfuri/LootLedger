//! Centralized internationalization (i18n) for LootLedger.
//! Language preference is stored as BCP 47 codes (`"en"`, `"pt-BR"`) in `ui-settings.json`.

use crate::cards::model;
use crate::{AppWindow, Dash, I18n, MenuOption};
use slint::{ComponentHandle, SharedString};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Lang {
    #[default]
    En,
    PtBr,
}

pub const LANGUAGES: &[(&str, &str)] = &[("en", "English"), ("pt-BR", "Português (Brasil)")];

pub fn from_code(code: &str) -> Lang {
    match code.trim().to_ascii_lowercase().as_str() {
        "pt-br" | "pt" => Lang::PtBr,
        _ => Lang::En,
    }
}

impl Lang {
    pub const fn code(self) -> &'static str {
        match self {
            Lang::En => "en",
            Lang::PtBr => "pt-BR",
        }
    }

    pub const fn t(self, en: &'static str, pt: &'static str) -> &'static str {
        match self {
            Lang::En => en,
            Lang::PtBr => pt,
        }
    }

    pub fn language_names(self) -> Vec<SharedString> {
        let _ = self;
        LANGUAGES
            .iter()
            .map(|(_, label)| SharedString::from(*label))
            .collect()
    }

    pub fn page_name(self, index: usize) -> &'static str {
        match index {
            0 => self.t("Overview", "Visão geral"),
            1 => self.t("Matches", "Partidas"),
            2 => self.t("Openings", "Aberturas"),
            3 => self.t("Statistics", "Estatísticas"),
            4 => self.t("Teammates", "Equipe"),
            _ => self.t("Settings", "Configurações"),
        }
    }

    pub fn seed_name(self, name: &str) -> String {
        match name {
            "Amber" => self.t("Amber", "Âmbar").to_owned(),
            "Violet" => self.t("Violet", "Violeta").to_owned(),
            "Blue" => self.t("Blue", "Azul").to_owned(),
            "Teal" => self.t("Teal", "Turquesa").to_owned(),
            "Rose" => self.t("Rose", "Rosa").to_owned(),
            "Green" => self.t("Green", "Verde").to_owned(),
            other => other.to_owned(),
        }
    }

    pub fn card_title(self, id: &str) -> &'static str {
        match id {
            "stat:all" | "all" => self.t("All time", "Todo o tempo"),
            "stat:today" | "today" => self.t("Today", "Hoje"),
            "stat:week" | "week" => self.t("This week", "Esta semana"),
            "stat:month" | "month" => self.t("This month", "Este mês"),
            "stat:last" | "last" => self.t("Last match", "Última partida"),
            "stat:avg" | "avg" => self.t("Chests per match", "Baús por partida"),
            "stat:best" | "best" => self.t("Best match", "Melhor partida"),
            "stat:per_hour" | "per_hour" => self.t("Chests per hour", "Baús por hora"),
            "stat:playtime" | "playtime" => self.t("Time played", "Tempo jogado"),
            "stat:matches" | "matches" => self.t("Matches read", "Partidas lidas"),
            "stat:session" | "session" => self.t("This session", "Esta sessão"),
            "stat:token" => self.t("Token chance", "Chance de Token"),
            "live" => self.t("Session overview", "Resumo da sessão"),
            "trend" => self.t("Chests over time", "Baús ao longo do tempo"),
            "token" => self.t("Token drop chance", "Chance de drop do Token"),
            "types" => self.t("By chest type", "Por tipo de baú"),
            "modes" => self.t("By game mode", "Por modo de jogo"),
            "heat" => self.t("When you open chests", "Horários de abertura"),
            "records" => self.t("Records", "Recordes"),
            "teammates" => self.t("You and your team", "Você e sua equipe"),
            "broken" => self.t("Searched vs broken open", "Abertos vs quebrados"),
            "health" => self.t("Setup and replay health", "Status e replays"),
            "sessions" => self.t("Sessions", "Sessões"),
            "goals" => self.t("Goals", "Metas"),
            "trophies" => self.t("Trophies", "Troféus"),
            "compare" => self.t("Compare periods", "Comparar períodos"),
            "stats" => self.t("Match stats", "Estatísticas de partida"),
            "treasures" => self.t("Treasure rewards", "Recompensas de tesouro"),
            "seen_prizes" => self.t("Seen prizes nearby", "Prêmios vistos por perto"),
            _ => "",
        }
    }

    pub fn tile_chip_title(self, key: &str) -> &'static str {
        match key {
            "avg" => self.t("Chests per match", "Baús / partida"),
            _ => self.card_title(key),
        }
    }

    pub fn chest_word(self, count: i64) -> &'static str {
        if count == 1 {
            self.t("chest", "baú")
        } else {
            self.t("chests", "baús")
        }
    }

    pub fn matches_count(self, n: i64) -> String {
        if n == 1 {
            self.t("1 match", "1 partida").to_owned()
        } else {
            format!("{n} {}", self.t("matches", "partidas"))
        }
    }

    pub fn days_count(self, n: i64) -> String {
        if n == 1 {
            self.t("1 day", "1 dia").to_owned()
        } else {
            format!("{n} {}", self.t("days", "dias"))
        }
    }

    pub fn people_count(self, n: usize) -> String {
        if n == 1 {
            self.t("1 person", "1 pessoa").to_owned()
        } else {
            format!("{n} {}", self.t("people", "pessoas"))
        }
    }

    pub fn weekday(self, index: usize) -> &'static str {
        match (self, index) {
            (Lang::En, 0) => "Monday",
            (Lang::En, 1) => "Tuesday",
            (Lang::En, 2) => "Wednesday",
            (Lang::En, 3) => "Thursday",
            (Lang::En, 4) => "Friday",
            (Lang::En, 5) => "Saturday",
            (Lang::En, _) => "Sunday",
            (Lang::PtBr, 0) => "Segunda",
            (Lang::PtBr, 1) => "Terça",
            (Lang::PtBr, 2) => "Quarta",
            (Lang::PtBr, 3) => "Quinta",
            (Lang::PtBr, 4) => "Sexta",
            (Lang::PtBr, 5) => "Sábado",
            (Lang::PtBr, _) => "Domingo",
        }
    }

    pub fn short_month(self, month: u32) -> &'static str {
        match (self, month) {
            (Lang::En, 1) => "Jan",
            (Lang::En, 2) => "Feb",
            (Lang::En, 3) => "Mar",
            (Lang::En, 4) => "Apr",
            (Lang::En, 5) => "May",
            (Lang::En, 6) => "Jun",
            (Lang::En, 7) => "Jul",
            (Lang::En, 8) => "Aug",
            (Lang::En, 9) => "Sep",
            (Lang::En, 10) => "Oct",
            (Lang::En, 11) => "Nov",
            (Lang::En, _) => "Dec",
            (Lang::PtBr, 1) => "Jan",
            (Lang::PtBr, 2) => "Fev",
            (Lang::PtBr, 3) => "Mar",
            (Lang::PtBr, 4) => "Abr",
            (Lang::PtBr, 5) => "Mai",
            (Lang::PtBr, 6) => "Jun",
            (Lang::PtBr, 7) => "Jul",
            (Lang::PtBr, 8) => "Ago",
            (Lang::PtBr, 9) => "Set",
            (Lang::PtBr, 10) => "Out",
            (Lang::PtBr, 11) => "Nov",
            (Lang::PtBr, _) => "Dez",
        }
    }

    pub fn month_year(self, day: chrono::NaiveDate, short_year: bool) -> String {
        use chrono::Datelike;
        let m = self.short_month(day.month());
        if short_year {
            format!("{m} {:02}", day.year() % 100)
        } else {
            format!("{m} {}", day.year())
        }
    }

    pub fn day_month_year(self, day: chrono::NaiveDate, with_year: bool) -> String {
        use chrono::Datelike;
        let m = self.short_month(day.month());
        if with_year {
            format!("{:02} {m} {}", day.day(), day.year())
        } else {
            format!("{:02} {m}", day.day())
        }
    }

    pub fn chest_type(self, raw: &str) -> String {
        match raw {
            "Chest" => self.t("Chest", "Baú").to_owned(),
            "Rare chest" => self.t("Rare chest", "Baú raro").to_owned(),
            "Relic chest" => self.t("Relic chest", "Baú de relíquia").to_owned(),
            "Buried chest" => self.t("Buried chest", "Baú enterrado").to_owned(),
            "Sprite poster chest" => self
                .t("Sprite poster chest", "Baú de pôster de Sprite")
                .to_owned(),
            other => other.to_owned(),
        }
    }

    pub fn mode_name(self, raw: &str) -> String {
        match raw {
            "Manual" => self.t("Manual", "Manual").to_owned(),
            "Unknown mode" => self.t("Unknown mode", "Modo desconhecido").to_owned(),
            other => other.to_owned(),
        }
    }

    pub fn container_name(self, raw: &str) -> String {
        match raw {
            "Ammo box" => self.t("Ammo box", "Caixa de munição").to_owned(),
            "Produce box" => self.t("Produce box", "Caixa de suprimentos").to_owned(),
            other => other.to_owned(),
        }
    }

    pub fn how(self, source: &str) -> String {
        match source {
            "replay" => self.t("Opened", "Aberto").to_owned(),
            "replay-broken" => self.t("Broken open", "Quebrado").to_owned(),
            "manual correction" => self.t("Manual", "Manual").to_owned(),
            "automatic" => self.t("Screen (old)", "Tela (antigo)").to_owned(),
            other => other.to_owned(),
        }
    }

    pub fn status(self, status: &str) -> String {
        match status {
            "confirmed" => self.t("Counted", "Contado").to_owned(),
            "undone" => self.t("Removed", "Removido").to_owned(),
            "review" => self.t("Review", "Revisar").to_owned(),
            "rejected" => self.t("Rejected", "Rejeitado").to_owned(),
            other => {
                let mut c = other.chars();
                c.next()
                    .map(|f| f.to_uppercase().collect::<String>() + c.as_str())
                    .unwrap_or_default()
            }
        }
    }

    pub fn squad_tag(self, me: bool, bot: bool, anonymous: bool) -> &'static str {
        if me {
            self.t(" · you", " · você")
        } else if bot {
            self.t(" · bot", " · bot")
        } else if anonymous {
            self.t(" · unnamed", " · sem nome")
        } else {
            ""
        }
    }

    pub fn goal_name(self, raw: &str) -> &'static str {
        match raw {
            "Today" => self.t("Today", "Hoje"),
            "This week" => self.t("This week", "Esta semana"),
            _ => "",
        }
    }

    pub fn compare_metric(self, raw: &str) -> &'static str {
        match raw {
            "Chests" => self.t("Chests", "Baús"),
            "Matches" => self.t("Matches", "Partidas"),
            "Chests per match" => self.t("Chests per match", "Baús por partida"),
            "Broken open" => self.t("Broken open", "Quebrados"),
            _ => "",
        }
    }

    pub fn match_stat_label(self, key: &str) -> &'static str {
        match key {
            "damage_to_players" => self.t("Damage to players", "Dano a jogadores"),
            "damage_taken" => self.t("Damage taken", "Dano recebido"),
            "eliminations" => self.t("Eliminations", "Eliminações"),
            "assists" => self.t("Assists", "Assistências"),
            "accuracy" => self.t("Accuracy", "Precisão"),
            "revives" => self.t("Revives", "Reanimações"),
            "damage_to_structures" => self.t("Damage to structures", "Dano a estruturas"),
            "materials_gathered" => self.t("Materials gathered", "Materiais coletados"),
            "materials_used" => self.t("Materials used", "Materiais usados"),
            "distance" => self.t("Distance travelled", "Distância percorrida"),
            _ => "",
        }
    }

    pub fn achievement(
        self,
        id: &str,
        fallback_title: &str,
        fallback_detail: &str,
    ) -> (String, String) {
        if self == Lang::En {
            return (fallback_title.to_owned(), fallback_detail.to_owned());
        }
        if let Some(rest) = id.strip_prefix("chests-")
            && let Ok(n) = rest.parse::<i64>()
        {
            let formatted = format_grouped_pt(n);
            return (
                format!("{formatted} baús"),
                format!("Abra {formatted} baús no total"),
            );
        }
        if let Some(rest) = id.strip_prefix("match-")
            && let Ok(n) = rest.parse::<i64>()
        {
            return (
                format!("{n} em uma partida"),
                format!("Abra {n} baús em uma única partida"),
            );
        }
        match id {
            "first-relic" => (
                "Primeiro baú de relíquia".into(),
                "Abra um baú de relíquia".into(),
            ),
            "first-buried" => (
                "Caçador de tesouros".into(),
                "Desenterre um baú enterrado".into(),
            ),
            "first-sprite" => (
                "Pôster de Sprite".into(),
                "Abra um baú de pôster de Sprite".into(),
            ),
            "streak-7" => (
                "Sequência de 7 dias".into(),
                "Abra baús por 7 dias seguidos".into(),
            ),
            "matches-100" => (
                "100 partidas".into(),
                "Tenha 100 partidas lidas dos replays".into(),
            ),
            _ => (fallback_title.to_owned(), fallback_detail.to_owned()),
        }
    }

    pub fn discord_status(self, raw: &str) -> String {
        if self == Lang::En || raw.is_empty() {
            return raw.to_owned();
        }
        match raw {
            "Paste a Discord Application ID below to connect." => {
                "Cole um Application ID do Discord abaixo para conectar.".into()
            }
            "Application ID must be 17–22 digits from the Discord Developer Portal." => {
                "O Application ID precisa ter 17 a 22 dígitos do Discord Developer Portal.".into()
            }
            "Ready · waiting for Fortnite to start." => {
                "Pronto · aguardando o Fortnite abrir.".into()
            }
            "Discord desktop app not detected (retrying…)." => {
                "App do Discord no PC não detectado (tentando novamente…).".into()
            }
            "Connected to Discord · showing status." => {
                "Conectado ao Discord · exibindo status.".into()
            }
            _ => {
                if let Some(msg) = raw.strip_prefix("Discord rejected Application ID: ") {
                    format!("O Discord recusou o Application ID: {msg}")
                } else if let Some(msg) = raw.strip_prefix("Discord error: ") {
                    format!("Erro do Discord: {msg}")
                } else {
                    raw.to_owned()
                }
            }
        }
    }

    pub fn treasure_label(self, raw: &str, synced: bool) -> String {
        if self == Lang::En {
            return if raw.is_empty() {
                if synced { "Auto" } else { "Manual" }.to_owned()
            } else {
                raw.to_owned()
            };
        }
        match raw {
            "Auto (confirmed)" => "Auto (confirmado)".into(),
            "Auto (expected)" => "Auto (previsto)".into(),
            "Manual" => "Manual".into(),
            "" => if synced { "Auto" } else { "Manual" }.to_owned(),
            other => other.to_owned(),
        }
    }

    pub fn treasure_kind(self, kind: &str) -> &'static str {
        match kind {
            "pirate-shop" => self.t("Pirate Shop", "Loja Pirata"),
            "outfit" => self.t("Outfit", "Traje"),
            "pickaxe" => self.t("Pickaxe", "Picareta"),
            "jam" => self.t("Jam Track", "Música"),
            "loading" => self.t("Loading Screen", "Tela de Carregamento"),
            "car" => self.t("Car / Decal", "Carro / Decalque"),
            "gizmo" => self.t("Gizmo", "Dispositivo"),
            "unknown" => self.t("Unknown", "Desconhecido"),
            _ => self.t("Other", "Outro"),
        }
    }

    pub fn treasure_source(self, source: &str) -> &'static str {
        match source {
            "golden" => self.t("Golden Chest", "Baú Dourado"),
            "handler" => self.t("Treasure Chest", "Baú de Tesouro"),
            _ => self.t("Other", "Outro"),
        }
    }

    pub fn treasure_item_name(
        self,
        drop: &lootledger_core::model::TreasureDrop,
        synced: &[lootledger_core::treasure::PrizeDef],
    ) -> String {
        let prize_lookup = drop
            .prize_id
            .as_deref()
            .or((!drop.raw_item.is_empty()).then_some(drop.raw_item.as_str()))
            .and_then(|id| lootledger_core::treasure::resolve_prize(id, synced));

        if let Some(prize) = prize_lookup {
            if prize
                .prize_id
                .eq_ignore_ascii_case(lootledger_core::treasure::PIRATE_SHOP_PRIZE_ID)
            {
                return self
                    .t("Pirate Shop Access", "Acesso à Loja Pirata")
                    .to_owned();
            }
            if self == Lang::PtBr {
                return match prize.item.as_str() {
                    "Week 4 Gold Outfit" => "Traje Dourado (Semana 4)".to_owned(),
                    "Week 4 Pickaxe or Back Bling" => "Picareta ou Acessório (Semana 4)".to_owned(),
                    "Week 4 Jam Track" => "Música (Semana 4)".to_owned(),
                    "Week 4 Loading Screen" => "Tela de Carregamento (Semana 4)".to_owned(),
                    "Week 4 Vehicle & Decal" => "Veículo e Decalque (Semana 4)".to_owned(),
                    "Week 5 Gold Outfit" => "Traje Dourado (Semana 5)".to_owned(),
                    "Week 5 Pickaxe or Back Bling" => "Picareta ou Acessório (Semana 5)".to_owned(),
                    "Week 5 Jam Track" => "Música (Semana 5)".to_owned(),
                    "Week 5 Loading Screen" => "Tela de Carregamento (Semana 5)".to_owned(),
                    "Week 5 Vehicle & Decal" => "Veículo e Decalque (Semana 5)".to_owned(),
                    _ => prize.item,
                };
            }
            return prize.item;
        }

        if let Some((canonical_id, eng_name)) =
            lootledger_core::treasure::gizmo_item_name(&drop.raw_item)
                .or_else(|| lootledger_core::treasure::gizmo_item_name(&drop.item))
        {
            return match canonical_id {
                "gizmo:relic-extractor" => self
                    .t("Relic Extractor", "Extrator de Relíquias")
                    .to_owned(),
                "gizmo:relic-finder" => self.t("Relic Finder", "Detector de Relíquias").to_owned(),
                "gizmo:lucky-locator" => self.t("Lucky Locator", "Localizador da Sorte").to_owned(),
                "gizmo:flame-celeb" => self.t("Flame Flare", "Sinalizador de Chamas").to_owned(),
                "gizmo:smuggler-key" => self
                    .t(
                        "Smuggler Extraction Key",
                        "Chave de Extração de Contrabandista",
                    )
                    .to_owned(),
                "gizmo:extraction-accelerator" => self
                    .t("Extraction Accelerator", "Acelerador de Extração")
                    .to_owned(),
                "gizmo:pirate-shop" => self.t("Pirate Shop Item", "Item da Loja Pirata").to_owned(),
                "gizmo:treasure" => self
                    .t("Treasure Gizmo", "Dispositivo de Tesouro")
                    .to_owned(),
                _ => eng_name.to_owned(),
            };
        }

        if !drop.item.is_empty() {
            return drop.item.clone();
        }
        if drop.kind == "unknown" {
            self.t(
                "Treasure reward (details unavailable)",
                "Recompensa de tesouro (detalhes indisponíveis)",
            )
            .to_owned()
        } else {
            self.t("Treasure Gizmo", "Dispositivo de Tesouro")
                .to_owned()
        }
    }
}

fn format_grouped_pt(n: i64) -> String {
    let digits = n.to_string();
    let mut out = String::new();
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push('.');
        }
        out.push(c);
    }
    out
}

pub fn apply(ui: &AppWindow, lang: Lang) {
    let g = ui.global::<I18n>();
    g.set_clear(lang.t("Clear", "Limpar").into());
    g.set_less(lang.t("Less", "Menos").into());
    g.set_presets(lang.t("Presets", "Predefinições").into());
    g.set_more(lang.t("More", "Mais").into());

    g.set_win_minimize(lang.t("Minimize", "Minimizar").into());
    g.set_win_restore(lang.t("Restore", "Restaurar").into());
    g.set_win_maximize(lang.t("Maximize", "Maximizar").into());
    g.set_win_close(lang.t("Close", "Fechar").into());

    g.set_nav_overview(lang.page_name(0).into());
    g.set_nav_matches(lang.page_name(1).into());
    g.set_nav_openings(lang.page_name(2).into());
    g.set_nav_statistics(lang.page_name(3).into());
    g.set_nav_teammates(lang.page_name(4).into());
    g.set_nav_settings(lang.page_name(5).into());

    g.set_sub_matches(
        lang.t(
            "Matches read from your replays. Select one to see its breakdown and timeline.",
            "Partidas lidas dos seus replays. Selecione uma para ver o resumo e a linha do tempo.",
        )
        .into(),
    );
    g.set_sub_openings(
        lang.t(
            "Every chest you opened, newest first. Corrections are recorded and never silently lost.",
            "Todos os baús abertos, dos mais recentes aos mais antigos. Correções ficam registradas.",
        )
        .into(),
    );
    g.set_sub_teammates(
        lang.t(
            "Everyone who played with you, merged across matches. Pick someone to see their profile.",
            "Todos que jogaram com você, somados entre partidas. Escolha alguém para ver o perfil.",
        )
        .into(),
    );
    g.set_sub_settings(
        lang.t(
            "Changes apply immediately. Your replays and ledger never leave this PC.",
            "As alterações valem na hora. Seus replays e registros nunca saem deste PC.",
        )
        .into(),
    );

    g.set_add_widget(lang.t("Add widget", "Adicionar bloco").into());
    g.set_reset_layout(lang.t("Reset layout", "Restaurar layout").into());
    g.set_tip_customize(
        lang.t("Customize the dashboard", "Personalizar painel")
            .into(),
    );
    g.set_tip_scan(
        lang.t("Check for new replays now", "Buscar novos replays agora")
            .into(),
    );
    g.set_tip_share(
        lang.t(
            "Share a summary image (saved or copied, never uploaded)",
            "Compartilhar imagem resumo (salva ou copiada, nunca enviada)",
        )
        .into(),
    );
    g.set_tip_overlay(lang.t("Pop-out counter", "Contador flutuante").into());
    g.set_tip_undo_opening(
        lang.t(
            "Undo the last counted opening",
            "Desfazer a última abertura contada",
        )
        .into(),
    );
    g.set_tip_export_openings(
        lang.t("Export the openings shown", "Exportar aberturas exibidas")
            .into(),
    );
    g.set_label_add_chest(lang.t("Add a manual chest", "Adicionar baú manual").into());
    g.set_palette_placeholder(
        lang.t(
            "Type a page, match, teammate or setting",
            "Digite uma página, partida, colega ou configuração",
        )
        .into(),
    );
    g.set_palette_label(lang.t("Command search", "Buscar comando").into());
    g.set_btn_later(lang.t("Later", "Depois").into());
    g.set_btn_ok(lang.t("OK", "OK").into());
    g.set_share_options(model(vec![
        MenuOption {
            id: "Copy summary image".into(),
            label: lang.t("Copy summary image", "Copiar imagem resumo").into(),
        },
        MenuOption {
            id: "Save summary image…".into(),
            label: lang
                .t("Save summary image…", "Salvar imagem resumo…")
                .into(),
        },
        MenuOption {
            id: "Copy weekly recap".into(),
            label: lang.t("Copy weekly recap", "Copiar resumo semanal").into(),
        },
        MenuOption {
            id: "Save weekly recap…".into(),
            label: lang
                .t("Save weekly recap…", "Salvar resumo semanal…")
                .into(),
        },
    ]));

    g.set_heat_label(
        lang.t(
            "Chests by weekday and hour",
            "Baús por dia da semana e hora",
        )
        .into(),
    );
    g.set_heat_days(model(
        match lang {
            Lang::En => ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            Lang::PtBr => ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"],
        }
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_heat_fewer(lang.t("Fewer", "Menos").into());
    g.set_heat_more(lang.t("More", "Mais").into());

    g.set_trend_ranges(model(
        ["7d", "30d", "90d", lang.t("All", "Tudo")]
            .iter()
            .map(|s| SharedString::from(*s))
            .collect(),
    ));
    g.set_trend_grains(model(
        [
            lang.t("Day", "Dia"),
            lang.t("Week", "Semana"),
            lang.t("Month", "Mês"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    let chart_styles = model(
        [
            lang.t("Bar", "Barras"),
            lang.t("Line", "Linha"),
            lang.t("Smooth", "Suave"),
            lang.t("Area", "Área"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    );
    g.set_chart_styles(chart_styles.clone());
    ui.global::<Dash>().set_style_names(chart_styles);

    g.set_label_date_range(lang.t("Date range", "Período").into());
    g.set_label_group_by(lang.t("Group by", "Agrupar por").into());
    g.set_label_chart_style(lang.t("Chart style", "Estilo do gráfico").into());
    g.set_status_done(lang.t("Done", "Concluído").into());
    g.set_status_attention(lang.t("Needs attention", "Requer atenção").into());
    g.set_trophy_unlocked_a11y(lang.t(", unlocked: ", ", desbloqueado: ").into());
    g.set_trophy_locked_a11y(lang.t(", locked: ", ", bloqueado: ").into());
    g.set_trophy_unlocked_tip(lang.t(" · unlocked", " · desbloqueado").into());
    g.set_trophy_locked_tip(lang.t(" · locked", " · bloqueado").into());
    g.set_compare_periods(model(
        [lang.t("First", "Primeiro"), lang.t("Second", "Segundo")]
            .iter()
            .map(|s| SharedString::from(*s))
            .collect(),
    ));
    g.set_compare_to(lang.t("to", "até").into());
    g.set_compare_from_suffix(lang.t(" period from", " período início").into());
    g.set_compare_to_suffix(lang.t(" period to", " período fim").into());
    g.set_tip_move_earlier(lang.t("Move earlier", "Mover para trás").into());
    g.set_tip_move_later(lang.t("Move later", "Mover para frente").into());
    g.set_tip_make_narrow(lang.t("Make narrow", "Diminuir largura").into());
    g.set_tip_make_wide(lang.t("Make wide", "Aumentar largura").into());
    g.set_tip_remove_widget(
        lang.t("Remove from the dashboard", "Remover do painel")
            .into(),
    );

    // Matches, Openings & Teammates
    g.set_sort_by_prefix(lang.t("Sort by ", "Ordenar por ").into());
    g.set_matches_search_placeholder(
        lang.t(
            "Search mode, date, tag or note",
            "Buscar modo, data, tag ou nota",
        )
        .into(),
    );
    g.set_label_game_mode(lang.t("Game mode", "Modo de jogo").into());
    g.set_label_chest_type(lang.t("Chest type", "Tipo de baú").into());
    g.set_label_min_chests(lang.t("Minimum chests", "Mínimo de baús").into());
    g.set_any_count(lang.t("Any count", "Qualquer qtd.").into());
    g.set_at_least_prefix(lang.t("At least ", "Pelo menos ").into());
    g.set_chip_favorites(lang.t("★ Favourites", "★ Favoritos").into());
    g.set_matches_empty(
        lang.t(
            "No matches yet. Turn on Record Replays in Fortnite, finish a match, and it appears here.",
            "Nenhuma partida ainda. Ative Gravar Replays no Fortnite, termine uma partida e ela aparecerá aqui.",
        )
        .into(),
    );
    g.set_match_headers(model(
        [
            lang.t("Date", "Data"),
            lang.t("Mode", "Modo"),
            lang.t("Place", "Posição"),
            lang.t("Chests", "Baús"),
            lang.t("Broken", "Quebrados"),
            lang.t("Teammates", "Equipe"),
            lang.t("Ammo", "Munição"),
            lang.t("Length", "Duração"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_tip_favorite_match(lang.t("Favourite match", "Favoritar partida").into());
    g.set_tip_close_details(
        lang.t("Close match details", "Fechar detalhes da partida")
            .into(),
    );
    g.set_tags_placeholder(
        lang.t(
            "Tags, e.g. ranked, with randoms",
            "Tags, ex.: ranqueada, trio",
        )
        .into(),
    );
    g.set_tags_label(lang.t("Match tags", "Tags da partida").into());
    g.set_note_placeholder(lang.t("Note", "Nota").into());
    g.set_note_label(lang.t("Match note", "Nota da partida").into());
    g.set_openings_during_match(
        lang.t("Openings during the match", "Aberturas durante a partida")
            .into(),
    );
    g.set_squad_breakdown_title(
        lang.t(
            "Squad: what each player opened or broke",
            "Esquadrão: o que cada jogador abriu ou quebrou",
        )
        .into(),
    );
    g.set_label_squad(lang.t("Squad", "Esquadrão").into());
    g.set_squad_headers(model(
        [
            lang.t("Player", "Jogador"),
            lang.t("Chests", "Baús"),
            lang.t("Searched", "Abertos"),
            lang.t("Broken open", "Quebrados"),
            lang.t("Share of squad", "% da equipe"),
            lang.t("Types", "Tipos"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_openings_search_placeholder(
        lang.t("Search type or details", "Buscar tipo ou detalhes")
            .into(),
    );
    g.set_label_match(lang.t("Match", "Partida").into());
    g.set_label_status(lang.t("Status", "Status").into());
    g.set_entry_statuses(model(
        [
            lang.t("Counted", "Contados"),
            lang.t("Removed", "Removidos"),
            lang.t("All statuses", "Todos os status"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_openings_empty(
        lang.t(
            "No openings yet. Play a match with Record Replays on.",
            "Nenhuma abertura ainda. Jogue uma partida com Gravar Replays ativado.",
        )
        .into(),
    );
    g.set_opening_headers(model(
        [
            lang.t("When", "Quando"),
            lang.t("Type", "Tipo"),
            lang.t("How", "Origem"),
            lang.t("Count", "Qtd."),
            lang.t("Status", "Status"),
            lang.t("Details", "Detalhes"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_btn_remove_entry(lang.t("Remove entry", "Remover registro").into());
    g.set_btn_restore_entry(lang.t("Restore entry", "Restaurar registro").into());
    g.set_btn_correct_entry(lang.t("Correct entry…", "Corrigir registro…").into());
    g.set_any_matches(
        lang.t("Any number of matches", "Qualquer nº de partidas")
            .into(),
    );
    g.set_matches_suffix(lang.t(" matches", " partidas").into());
    g.set_label_min_matches(
        lang.t("Minimum matches together", "Mínimo de partidas juntos")
            .into(),
    );
    g.set_tip_export_csv(lang.t("Export as CSV", "Exportar como CSV").into());
    g.set_tip_export_json(lang.t("Export as JSON", "Exportar como JSON").into());
    g.set_team_records_titles(model(
        [
            lang.t("Most chests", "Mais baús"),
            lang.t("Best single match", "Melhor partida"),
            lang.t("Played most with", "Mais partidas juntos"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_team_headers(model(
        [
            lang.t("Player", "Jogador"),
            lang.t("Matches", "Partidas"),
            lang.t("Chests", "Baús"),
            lang.t("Per match", "Por partida"),
            lang.t("Searched", "Abertos"),
            lang.t("Broken", "Quebrados"),
            lang.t("Rare+", "Raros+"),
            lang.t("Best", "Melhor"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_label_chest_types(lang.t("Chest types", "Tipos de baú").into());
    g.set_label_chests_per_match(lang.t("Chests per match", "Baús por partida").into());
    g.set_chart_together_empty(
        lang.t(
            "Matches together will chart here",
            "Partidas juntos aparecerão neste gráfico",
        )
        .into(),
    );
    g.set_label_matches_together(lang.t("Matches together", "Partidas juntos").into());
    g.set_profile_match_headers(model(
        [
            lang.t("When", "Quando"),
            lang.t("Mode", "Modo"),
            lang.t("Their chests", "Baús do jogador"),
            lang.t("Your chests", "Seus baús"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_correct_title(lang.t("Correct opening", "Corrigir abertura").into());
    g.set_label_count(lang.t("Count", "Quantidade").into());
    g.set_btn_cancel(lang.t("Cancel", "Cancelar").into());
    g.set_btn_save(lang.t("Save", "Salvar").into());

    // Settings
    apply_settings_strings(&g, lang);
}

fn apply_settings_strings(g: &I18n, lang: Lang) {
    g.set_set_appearance(lang.t("Appearance", "Aparência").into());
    g.set_set_language(lang.t("Language", "Idioma").into());
    g.set_set_language_hint(
        lang.t(
            "Switch language immediately without restarting.",
            "Altera o idioma na hora, sem reiniciar o aplicativo.",
        )
        .into(),
    );
    g.set_set_theme(lang.t("Theme", "Tema").into());
    g.set_set_theme_opts(model(
        [
            lang.t("Light", "Claro"),
            lang.t("Dark", "Escuro"),
            lang.t("System", "Sistema"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_set_theme_label(lang.t("Colour theme", "Tema de cores").into());
    g.set_set_accent(lang.t("Accent colour", "Cor de destaque").into());
    g.set_set_accent_hint(
        lang.t(
            "Presets or your own #rrggbb. Everything is tuned from it.",
            "Predefinições ou seu código #rrggbb. Toda a interface se adapta a ela.",
        )
        .into(),
    );
    g.set_set_accent_suffix(lang.t(" accent colour", " cor de destaque").into());
    g.set_set_accent_custom_label(
        lang.t("Custom accent colour", "Cor de destaque personalizada")
            .into(),
    );
    g.set_set_contrast(lang.t("Higher contrast", "Alto contraste").into());
    g.set_set_contrast_hint(
        lang.t(
            "Stronger outlines and muted text.",
            "Contornos mais fortes e texto mais legível.",
        )
        .into(),
    );
    g.set_set_corners(lang.t("Corners", "Cantos").into());
    g.set_set_corners_opts(model(
        [
            lang.t("Sharp", "Retos"),
            lang.t("Default", "Padrão"),
            lang.t("Round", "Arredondados"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_set_corners_label(lang.t("Corner radius", "Arredondamento dos cantos").into());
    g.set_set_density(lang.t("Density", "Densidade").into());
    g.set_set_density_opts(model(
        [
            lang.t("Compact", "Compacta"),
            lang.t("Comfortable", "Confortável"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_set_density_label(lang.t("Spacing", "Espaçamento").into());
    g.set_set_text_size(lang.t("Text size", "Tamanho do texto").into());
    g.set_set_colorblind(
        lang.t(
            "Colourblind-safe chest colours",
            "Cores para daltonismo nos baús",
        )
        .into(),
    );
    g.set_set_colorblind_hint(
        lang.t(
            "Chest types keep one colour everywhere. This swaps in a palette that stays apart for most colour vision.",
            "Cada tipo de baú mantém uma cor fixa. Ativa uma paleta mais fácil de distinguir.",
        )
        .into(),
    );
    g.set_set_background(lang.t("Background", "Fundo").into());
    g.set_set_background_hint(
        lang.t(
            "A soft tonal wash instead of a flat colour.",
            "Um tom suave em vez de cor chapada.",
        )
        .into(),
    );
    g.set_set_background_opts(model(
        [lang.t("Solid", "Sólido"), lang.t("Tonal", "Tonal")]
            .iter()
            .map(|s| SharedString::from(*s))
            .collect(),
    ));
    g.set_set_animations(lang.t("Animations", "Animações").into());
    g.set_set_animations_hint(
        lang.t(
            "Reduced keeps short fades only. Windows' 'Show animations' off means Reduced.",
            "Reduzido mantém apenas transições curtas. Desativar animações no Windows equivale a Reduzido.",
        )
        .into(),
    );
    g.set_set_animations_opts(model(
        [
            lang.t("Full", "Completas"),
            lang.t("Reduced", "Reduzidas"),
            lang.t("Off", "Desligadas"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_set_show_title(
        lang.t(
            "Show page title in title bar",
            "Mostrar nome da página na barra de título",
        )
        .into(),
    );
    g.set_set_show_title_hint(
        lang.t(
            "Off by default: the page title is already at the top of each page.",
            "Desativado por padrão: o título já aparece no topo de cada página.",
        )
        .into(),
    );

    g.set_set_tiles_section(lang.t("Overview tiles", "Blocos da Visão geral").into());
    g.set_set_tiles_row(lang.t("Summary tiles", "Blocos de resumo").into());
    g.set_set_tiles_hint(
        lang.t(
            "Choose which stats appear on Overview. Use Customize there to move and resize them.",
            "Escolha quais estatísticas aparecem na Visão geral. Use Personalizar lá para mover ou redimensionar.",
        )
        .into(),
    );

    g.set_set_formats(lang.t("Formats", "Formatos").into());
    g.set_set_24h(lang.t("24-hour clock", "Relógio 24 horas").into());
    g.set_set_date_format(lang.t("Date format", "Formato de data").into());
    g.set_set_separators(lang.t("Number separator", "Separador numérico").into());
    g.set_set_separators_label(lang.t("Thousands separator", "Separador de milhar").into());
    g.set_set_playtime(lang.t("Playtime shown as", "Tempo de jogo em").into());
    g.set_set_default_range(lang.t("Default date range", "Período padrão").into());
    g.set_set_default_range_hint(
        lang.t(
            "Used for the trend chart and the Matches filter.",
            "Usado no gráfico de evolução e no filtro de Partidas.",
        )
        .into(),
    );
    g.set_set_default_range_opts(model(
        [
            lang.t("7 days", "7 dias"),
            lang.t("30 days", "30 dias"),
            lang.t("90 days", "90 dias"),
            lang.t("All time", "Tudo"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));

    g.set_set_replays(lang.t("Replays", "Replays").into());
    g.set_set_replay_folder(lang.t("Replay folder", "Pasta de replays").into());
    g.set_set_replay_folder_hint(
        lang.t(
            "Fortnite's default is Saved\\Demos under FortniteGame.",
            "O padrão do Fortnite é Saved\\Demos dentro de FortniteGame.",
        )
        .into(),
    );
    g.set_tip_choose_replay_folder(
        lang.t("Choose the replay folder", "Escolher pasta de replays")
            .into(),
    );
    g.set_tip_open_replay_folder(
        lang.t("Open the replay folder", "Abrir pasta de replays")
            .into(),
    );
    g.set_set_auto_watch(
        lang.t("Watch for new replays", "Monitorar novos replays")
            .into(),
    );
    g.set_set_auto_watch_hint(
        lang.t(
            "Finished matches are added on their own.",
            "Partidas encerradas são adicionadas automaticamente.",
        )
        .into(),
    );
    g.set_set_auto_watch_label(
        lang.t(
            "Check for replays automatically",
            "Verificar replays automaticamente",
        )
        .into(),
    );
    g.set_set_check_every(lang.t("Check every", "Verificar a cada").into());
    g.set_set_check_every_suffix(" s".into());
    g.set_set_check_every_label(
        lang.t("Replay check interval", "Intervalo de leitura de replays")
            .into(),
    );
    g.set_set_count_broken(
        lang.t("Count broken-open chests", "Contar baús quebrados")
            .into(),
    );
    g.set_set_count_broken_hint(
        lang.t(
            "Chests destroyed by your damage before anyone searched them. Their loot still spills.",
            "Baús destruídos pelo seu dano antes de alguém abrir. O saque ainda cai no chão.",
        )
        .into(),
    );
    g.set_set_count_broken_label(
        lang.t(
            "Count chests you broke open",
            "Contar baús quebrados por você",
        )
        .into(),
    );
    g.set_set_rescan(
        lang.t("Read every replay again", "Reler todos os replays")
            .into(),
    );
    g.set_set_rescan_hint(
        lang.t(
            "Re-reads all replays Fortnite still keeps. Your corrections are kept.",
            "Lê novamente todos os replays que ainda estão no disco. Suas correções são mantidas.",
        )
        .into(),
    );
    g.set_set_rescan_btn(
        lang.t("Read all replays again", "Reler todos os replays")
            .into(),
    );

    g.set_set_live_section(
        lang.t("Live match and counter", "Partida ao vivo e contador")
            .into(),
    );
    g.set_set_live_privacy(
        lang.t(
            "LootLedger only reads files Fortnite writes on this PC: the replay and the game's log time. It never touches the Fortnite process: no injection, hooks, memory reading or drawing over the game. The counter is an ordinary LootLedger window that stays on top.",
            "O LootLedger lê apenas arquivos gravados pelo Fortnite neste PC: o replay e o horário do log do jogo. Nunca interage com o processo do Fortnite: sem injeção, hooks ou leitura de memória. O contador é uma janela comum sempre no topo.",
        )
        .into(),
    );
    g.set_set_live_track(
        lang.t("Track the current match", "Acompanhar partida atual")
            .into(),
    );
    g.set_set_live_track_hint(
        lang.t(
            "Fortnite encrypts the replay until the match ends, so the chest count arrives then, seconds after the match. During the match you see that it is live and how long it has run.",
            "O Fortnite criptografa o replay até o fim da partida, então a contagem chega segundos depois. Durante o jogo você vê que está ao vivo e o tempo decorrido.",
        )
        .into(),
    );
    g.set_set_live_every_hint(
        lang.t(
            "Fortnite saves the replay about every 20 s. Each check reads one file header.",
            "O Fortnite salva o replay a cada ~20 s. Cada checagem lê só o cabeçalho do arquivo.",
        )
        .into(),
    );
    g.set_set_live_every_label(lang.t("Live check interval", "Intervalo ao vivo").into());
    g.set_set_overlay(lang.t("Pop-out counter", "Contador flutuante").into());
    g.set_set_overlay_hint(
        lang.t(
            "A small always-on-top window with the count. Drag and resize it; it remembers where it was.",
            "Pequena janela sempre no topo com a contagem. Arraste para posicionar; ela lembra onde ficou.",
        )
        .into(),
    );
    g.set_set_overlay_opacity(lang.t("Counter opacity", "Opacidade do contador").into());
    g.set_set_overlay_size(lang.t("Counter size", "Tamanho do contador").into());
    g.set_set_overlay_corner(lang.t("Counter position", "Posição do contador").into());
    g.set_set_overlay_corner_opts(model(
        [
            lang.t("Where I put it", "Onde eu colocar"),
            lang.t("Top left", "Sup. esquerdo"),
            lang.t("Top right", "Sup. direito"),
            lang.t("Bottom left", "Inf. esquerdo"),
            lang.t("Bottom right", "Inf. direito"),
        ]
        .iter()
        .map(|s| SharedString::from(*s))
        .collect(),
    ));
    g.set_set_overlay_click(
        lang.t("Click through the counter", "Ignorar cliques no contador")
            .into(),
    );
    g.set_set_overlay_click_hint(
        lang.t(
            "Clicks pass to the window underneath. Turn this off here to move the counter again.",
            "Cliques passam direto para a janela atrás. Desative aqui para mover o contador novamente.",
        )
        .into(),
    );
    g.set_set_overlay_teammates(
        lang.t("Teammates in the counter", "Equipe no contador")
            .into(),
    );
    g.set_set_match_popup(
        lang.t("Pop-up after each match", "Aviso após cada partida")
            .into(),
    );
    g.set_set_match_popup_hint(
        lang.t(
            "Your chests, placement and how it compares, in the corner for a few seconds. It never takes focus from the game.",
            "Seus baús, colocação e comparativo no canto da tela por alguns segundos. Nunca tira o foco do jogo.",
        )
        .into(),
    );
    g.set_set_sound(
        lang.t("Sound when a match is counted", "Som ao contar partida")
            .into(),
    );
    g.set_set_volume(lang.t("Volume", "Volume").into());
    g.set_set_volume_label(lang.t("Sound volume", "Volume do som").into());

    g.set_set_discord_section(
        lang.t("Discord Rich Presence", "Discord Rich Presence")
            .into(),
    );
    g.set_set_discord_rpc(
        lang.t("Show status on Discord", "Mostrar status no Discord")
            .into(),
    );
    g.set_set_discord_rpc_hint(
        lang.t(
            "Displays your last match, today, squad total and Token chance on your Discord profile.",
            "Exibe última partida, hoje, total do esquadrão e chance do Token no seu perfil do Discord.",
        )
        .into(),
    );
    g.set_set_discord_app_id(
        lang.t("Discord Application ID", "Application ID do Discord")
            .into(),
    );
    g.set_set_discord_app_id_hint(
        lang.t(
            "Create an app at discord.com/developers/applications (its name is what appears after Playing) and paste its Application ID here.",
            "Crie um app em discord.com/developers/applications (o nome dele aparece após Jogando) e cole o Application ID aqui.",
        )
        .into(),
    );
    g.set_set_discord_app_id_placeholder(
        lang.t("e.g. 1234567890123456789", "ex.: 1234567890123456789")
            .into(),
    );
    g.set_set_discord_only_game(
        lang.t(
            "Only while Fortnite is running",
            "Somente com o Fortnite aberto",
        )
        .into(),
    );
    g.set_set_discord_only_game_hint(
        lang.t(
            "Turn off to show your stats on Discord whenever LootLedger is open.",
            "Desative para mostrar suas estatísticas no Discord sempre que o LootLedger estiver aberto.",
        )
        .into(),
    );

    g.set_set_goals_section(lang.t("Goals", "Metas").into());
    g.set_set_goal_daily(lang.t("Daily goal", "Meta diária").into());
    g.set_set_goal_daily_hint(
        lang.t(
            "Chests per day. Type a number or pick a preset.",
            "Baús por dia. Digite um número ou escolha uma opção.",
        )
        .into(),
    );
    g.set_set_goal_weekly(lang.t("Weekly goal", "Meta semanal").into());
    g.set_set_goal_weekly_hint(
        lang.t(
            "Chests per week, Monday to Sunday.",
            "Baús por semana, de segunda a domingo.",
        )
        .into(),
    );
    let no_goal = lang.t("No goal", "Sem meta");
    let custom = lang.t("Custom…", "Personalizar…");
    g.set_set_no_goal(no_goal.into());
    g.set_set_daily_presets(model(vec![
        no_goal.into(),
        "10".into(),
        "25".into(),
        "50".into(),
        "100".into(),
        custom.into(),
    ]));
    g.set_set_weekly_presets(model(vec![
        no_goal.into(),
        "50".into(),
        "100".into(),
        "250".into(),
        "500".into(),
        custom.into(),
    ]));
    g.set_set_celebrate(
        lang.t("Celebrate goals and trophies", "Comemorar metas e troféus")
            .into(),
    );
    g.set_set_celebrate_hint(
        lang.t(
            "A short message inside LootLedger. Nothing is sent anywhere.",
            "Um aviso curto dentro do LootLedger. Nada é enviado para fora.",
        )
        .into(),
    );

    g.set_set_th_section(
        lang.t(
            "Treasure Hours (Token boost)",
            "Horas do Poder / Tesouro (bônus do Token)",
        )
        .into(),
    );
    g.set_set_th_auto(
        lang.t(
            "Auto-sync official Treasure Hours",
            "Sincronizar horários oficiais automaticamente",
        )
        .into(),
    );
    g.set_set_th_sync_now(lang.t("Sync now", "Sincronizar agora").into());
    g.set_set_th_add_title(
        lang.t("Add custom Treasure Hour", "Adicionar horário manual")
            .into(),
    );
    g.set_set_th_add_hint(
        lang.t(
            "Local date, start–end time (e.g. 16:00 to 20:00) and boost multiplier (e.g. 1.5, 2x, or +50%). Custom entries override auto-synced odds for that window.",
            "Data local, início–fim (ex.: 16:00 às 20:00) e multiplicador (ex.: 1.5, 2x ou +50%). Horários manuais têm prioridade sobre os sincronizados.",
        )
        .into(),
    );
    g.set_set_th_date_placeholder(lang.t("dd/mm/yyyy", "dd/mm/aaaa").into());
    g.set_set_th_date_label(lang.t("Date", "Data").into());
    g.set_set_th_start_label(lang.t("Start time", "Início").into());
    g.set_set_th_end_label(lang.t("End time", "Fim").into());
    g.set_set_th_boost_label(lang.t("Boost", "Bônus").into());
    g.set_set_th_add_btn(lang.t("Add", "Adicionar").into());
    g.set_set_th_remove_tip(
        lang.t("Remove custom Treasure Hour", "Remover horário manual")
            .into(),
    );

    g.set_set_shortcuts_section(lang.t("Shortcuts", "Atalhos").into());
    g.set_set_hk_add(lang.t("Add one chest", "Adicionar um baú").into());
    g.set_set_hk_add_hint(
        lang.t(
            "Works in any app. Example: Ctrl+Alt+F8",
            "Funciona em qualquer aplicativo. Exemplo: Ctrl+Alt+F8",
        )
        .into(),
    );
    g.set_set_hk_add_label(lang.t("Manual +1 shortcut", "Atalho +1 manual").into());
    g.set_set_hk_undo(lang.t("Undo last chest", "Desfazer último baú").into());
    g.set_set_hk_undo_hint(
        lang.t("Example: Ctrl+Alt+F9", "Exemplo: Ctrl+Alt+F9")
            .into(),
    );
    g.set_set_hk_undo_label(lang.t("Undo shortcut", "Atalho desfazer").into());
    g.set_set_hk_overlay(
        lang.t("Show or hide the counter", "Mostrar ou ocultar contador")
            .into(),
    );
    g.set_set_hk_overlay_hint(
        lang.t(
            "Example: Ctrl+Alt+F10. Leave empty to turn a shortcut off. Press ? in LootLedger for all shortcuts.",
            "Exemplo: Ctrl+Alt+F10. Deixe vazio para desativar. Pressione ? no LootLedger para ver todos os atalhos.",
        )
        .into(),
    );
    g.set_set_hk_overlay_label(
        lang.t(
            "Show or hide the counter shortcut",
            "Atalho mostrar/ocultar contador",
        )
        .into(),
    );

    g.set_set_data_section(lang.t("Data", "Dados").into());
    g.set_set_data_row(
        lang.t("Ledger and settings", "Registro e configurações")
            .into(),
    );
    g.set_set_data_hint_prefix(lang.t("Stored in ", "Salvo em ").into());
    g.set_set_data_hint_suffix(
        lang.t(
            ". Backups hold matches, openings and your edit history.",
            ". Os backups guardam partidas, aberturas e histórico de edições.",
        )
        .into(),
    );
    g.set_data_col1(model(vec![
        MenuOption {
            id: "Export ledger".into(),
            label: lang.t("Export ledger", "Exportar registro").into(),
        },
        MenuOption {
            id: "Create backup".into(),
            label: lang.t("Create backup", "Criar backup").into(),
        },
    ]));
    g.set_data_col2(model(vec![
        MenuOption {
            id: "Restore backup".into(),
            label: lang.t("Restore backup", "Restaurar backup").into(),
        },
        MenuOption {
            id: "Open data folder".into(),
            label: lang.t("Open data folder", "Abrir pasta de dados").into(),
        },
    ]));
    g.set_data_col3(model(vec![
        MenuOption {
            id: "Export settings".into(),
            label: lang.t("Export settings", "Exportar configs").into(),
        },
        MenuOption {
            id: "Import settings".into(),
            label: lang.t("Import settings", "Importar configs").into(),
        },
    ]));
    g.set_set_check_updates(lang.t("Check for updates", "Verificar atualizações").into());
    g.set_set_clear_data(lang.t("Clear all data…", "Limpar todos os dados…").into());
    g.set_set_clear_data_note(
        lang.t(
            "Clearing saves a backup first. Replay files stay on your PC and are not read again until you choose Read all replays again.",
            "Um backup é salvo antes de limpar. Os arquivos de replay continuam no PC e não são relidos até você escolher Reler todos os replays.",
        )
        .into(),
    );

    g.set_set_about_section(lang.t("About", "Sobre").into());
    g.set_set_about_prefix("LootLedger ".into());
    g.set_set_about_suffix(
        lang.t(
            " · counts the chests you open in Fortnite from the replays on this PC. Your data never leaves this PC.",
            " · conta os baús abertos no Fortnite pelos replays neste PC. Seus dados nunca saem deste PC.",
        )
        .into(),
    );
    g.set_set_auto_update(
        lang.t("Update automatically", "Atualizar automaticamente")
            .into(),
    );
    g.set_set_auto_update_hint(
        lang.t(
            "Asks GitHub for a newer LootLedger and installs it when you close the app. Only the version check and the download go over the internet; none of your data is sent.",
            "Verifica no GitHub se há uma versão mais nova e instala ao fechar o app. Só a checagem e o download usam a internet; nenhum dado seu é enviado.",
        )
        .into(),
    );
    g.set_set_whats_new(lang.t("What's new", "Novidades").into());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_language_codes_with_english_fallback() {
        assert_eq!(from_code("en"), Lang::En);
        assert_eq!(from_code("pt-BR"), Lang::PtBr);
        assert_eq!(from_code("pt-br"), Lang::PtBr);
        assert_eq!(from_code("pt"), Lang::PtBr);
        assert_eq!(from_code("es"), Lang::En);
        assert_eq!(from_code(""), Lang::En);
        assert_eq!(Lang::En.code(), "en");
        assert_eq!(Lang::PtBr.code(), "pt-BR");
    }

    #[test]
    fn translates_core_terms_and_achievements() {
        assert_eq!(Lang::PtBr.chest_word(1), "baú");
        assert_eq!(Lang::PtBr.chest_word(2), "baús");
        assert_eq!(Lang::PtBr.chest_type("Rare chest"), "Baú raro");
        assert_eq!(Lang::PtBr.short_month(2), "Fev");
        let (title, detail) =
            Lang::PtBr.achievement("chests-1000", "1,000 chests", "Open 1,000 chests in total");
        assert_eq!(title, "1.000 baús");
        assert_eq!(detail, "Abra 1.000 baús no total");
    }

    #[test]
    fn translates_treasure_rewards() {
        use lootledger_core::model::TreasureDrop;
        assert_eq!(Lang::PtBr.treasure_kind("pirate-shop"), "Loja Pirata");
        assert_eq!(Lang::PtBr.treasure_source("golden"), "Baú Dourado");
        let drop = TreasureDrop {
            t: 10.0,
            by: "me".into(),
            source: "golden".into(),
            prize_id: Some(lootledger_core::treasure::PIRATE_SHOP_PRIZE_ID.into()),
            ..Default::default()
        };
        assert_eq!(
            Lang::PtBr.treasure_item_name(&drop, &[]),
            "Acesso à Loja Pirata"
        );
        let gizmo = TreasureDrop {
            t: 20.0,
            by: "me".into(),
            source: "handler".into(),
            raw_item: "WID_RelicFinder".into(),
            item: "Relic Finder".into(),
            kind: "gizmo".into(),
            ..Default::default()
        };
        assert_eq!(
            Lang::PtBr.treasure_item_name(&gizmo, &[]),
            "Detector de Relíquias"
        );
    }
}
