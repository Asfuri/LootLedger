//! Spike: decrypt and decompress every data chunk of the replays in a folder (read-only).
use lootledger_core::container::{self, ChunkKind};
use std::time::Instant;

fn main() {
    let folder = std::env::args().nth(1).expect("folder");
    let mut files: Vec<_> = std::fs::read_dir(&folder)
        .unwrap()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|e| e == "replay"))
        .collect();
    files.sort();
    let (mut ok, mut failed, mut bytes, mut chunks, mut locked) = (0, 0, 0usize, 0usize, 0);
    let clock = Instant::now();
    for path in &files {
        let data = std::fs::read(path).unwrap();
        let info = match container::read_info(&data) {
            Ok(i) => i,
            Err(e) => {
                println!("{}: {e}", path.display());
                failed += 1;
                continue;
            }
        };
        if info.locked() {
            locked += 1;
            continue;
        }
        let mut good = true;
        for chunk in container::chunks(&data, &info).filter(|c| c.kind == ChunkKind::ReplayData) {
            match container::replay_data(&info, &chunk) {
                Ok(d) => {
                    bytes += d.frames.len();
                    chunks += 1;
                }
                Err(e) => {
                    println!("{}: {e}", path.display());
                    good = false;
                    break;
                }
            }
        }
        if good { ok += 1 } else { failed += 1 }
    }
    println!(
        "{ok} replays ok, {failed} failed, {locked} locked skipped, {chunks} data chunks, {} MB of frames, {:.2} s",
        bytes / 1_000_000,
        clock.elapsed().as_secs_f64()
    );
}
