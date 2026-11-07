//! ReadDirectoryChangesW through notify; the worker sleeps when there are no filesystem events.
use lootledger_core::tail::Tail;
use notify::{Config, Event, RecommendedWatcher, RecursiveMode, Watcher};
use std::{
    collections::{HashMap, HashSet},
    path::{Path, PathBuf},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

enum Message {
    Changed(notify::Result<Event>),
    Stop,
}

pub struct ReplayWatch {
    tx: mpsc::Sender<Message>,
    worker: Option<thread::JoinHandle<()>>,
}

impl ReplayWatch {
    pub fn start(folder: PathBuf, report: impl Fn(String) + Send + 'static) -> Self {
        let (tx, rx) = mpsc::channel();
        let events = tx.clone();
        let worker = thread::spawn(move || {
            let mut watcher = match RecommendedWatcher::new(
                move |event| {
                    let _ = events.send(Message::Changed(event));
                },
                Config::default(),
            ) {
                Ok(watcher) => watcher,
                Err(error) => {
                    report(format!("Replay watcher could not start: {error}"));
                    return;
                }
            };
            if let Err(error) = watcher.watch(&folder, RecursiveMode::NonRecursive) {
                report(format!("Replay folder is unavailable: {error}"));
                return;
            }
            let mut tails = HashMap::<PathBuf, Tail>::new();
            report(
                "Watching local replay files. Imports remain in the Python app during migration."
                    .into(),
            );
            if let Ok(files) = std::fs::read_dir(&folder)
                && let Some(newest) = files
                    .filter_map(Result::ok)
                    .filter(|e| replay(&e.path()))
                    .max_by_key(|e| e.metadata().and_then(|m| m.modified()).ok())
            {
                refresh(&mut tails, &newest.path(), &report);
            }
            while let Ok(message) = rx.recv() {
                let mut pending = HashSet::new();
                match message {
                    Message::Stop => return,
                    Message::Changed(Ok(event)) => {
                        pending.extend(event.paths.into_iter().filter(|p| replay(p)));
                    }
                    Message::Changed(Err(error)) => {
                        report(format!("Replay watcher error: {error}"));
                        continue;
                    }
                }
                if pending.is_empty() {
                    continue;
                }
                // A quiet period with a one-second cap, so continuous writes cannot starve updates.
                let deadline = Instant::now() + Duration::from_secs(1);
                loop {
                    if Instant::now() >= deadline {
                        break;
                    }
                    match rx.recv_timeout(Duration::from_millis(200)) {
                        Ok(Message::Stop) => return,
                        Ok(Message::Changed(Ok(event))) => {
                            pending.extend(event.paths.into_iter().filter(|p| replay(p)));
                        }
                        Ok(Message::Changed(Err(error))) => {
                            report(format!("Replay watcher error: {error}"))
                        }
                        Err(mpsc::RecvTimeoutError::Timeout) => break,
                        Err(mpsc::RecvTimeoutError::Disconnected) => return,
                    }
                }
                let mut pending: Vec<_> = pending.into_iter().collect();
                pending.sort_by_key(|path| {
                    (
                        path.metadata().and_then(|m| m.modified()).ok(),
                        path.clone(),
                    )
                });
                for path in pending {
                    if path.is_file() {
                        refresh(&mut tails, &path, &report);
                    } else {
                        tails.remove(&path);
                    }
                }
            }
        });
        Self {
            tx,
            worker: Some(worker),
        }
    }
}

impl Drop for ReplayWatch {
    fn drop(&mut self) {
        let _ = self.tx.send(Message::Stop);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

fn replay(path: &Path) -> bool {
    path.extension()
        .is_some_and(|e| e.eq_ignore_ascii_case("replay"))
}
fn refresh(tails: &mut HashMap<PathBuf, Tail>, path: &Path, report: &impl Fn(String)) {
    match tails.entry(path.to_owned()).or_default().refresh(path) {
        Ok(state) if state.live => report(format!(
            "Live replay · {}s saved · {} complete chunks. {}",
            state.recorded_ms / 1000,
            state.chunks,
            if state.locked {
                "Chests are encrypted until the match ends."
            } else {
                "Rust chest decoding is still pending."
            }
        )),
        Ok(_) => report(
            "Replay finalized. Finished imports remain in the Python app during migration.".into(),
        ),
        Err(_) => report(
            "Replay header is incomplete or unavailable; waiting for the next file change.".into(),
        ),
    }
}
