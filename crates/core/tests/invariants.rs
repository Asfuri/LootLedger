use lootledger_core::{
    model::{Replay, classify},
    store::Store,
};
use proptest::prelude::*;

proptest! {
    #![proptest_config(ProptestConfig::with_cases(32))]
    #[test]
    fn partial_to_final_reimport_never_double_counts_or_resurrects_corrections(
        cut in 0usize..170, repetitions in 1usize..5, include_broken in any::<bool>()) {
        let full: Replay = serde_json::from_str(include_str!("../../../tests/fixtures/replay-squad.json")).unwrap();
        let mut partial = full.clone();
        partial.events.truncate(cut);
        partial.ok = false;
        let dir = tempfile::tempdir().unwrap();
        let mut store = Store::open(dir.path().join("ledger.sqlite")).unwrap();
        store.import_replay(&partial, "live.replay", 1, 1.0).unwrap();
        for _ in 0..repetitions { store.import_replay(&full, "live.replay", 2, 2.0).unwrap(); }
        let events = store.entries(0, u32::MAX).unwrap();
        let total = store.totals(include_broken).unwrap();
        let counted: Vec<_> = events.iter().filter(|e| include_broken || e.source != "replay-broken").collect();
        let searched: i64 = counted.iter().filter(|e| e.source != "replay-broken").map(|e| e.amount).sum();
        prop_assert_eq!(total.chests, searched + total.broken);
        prop_assert_eq!(total.chests, counted.iter().map(|e| e.amount).sum::<i64>());
        let expected = full.events.iter().filter(|e| e.by == "me" && classify(&e.cls).1).count();
        prop_assert_eq!(events.len(), expected);
        let first = events.first().unwrap();
        store.edit(&first.id, Some("undone"), None, None).unwrap();
        store.import_replay(&full, "live.replay", 3, 3.0).unwrap();
        prop_assert_eq!(store.totals(true).unwrap().chests, expected as i64 - first.amount);
    }
}
