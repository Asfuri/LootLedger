//! Discord Rich Presence integration via local Discord IPC pipe/socket.
//!
//! Communicates asynchronously with the Discord desktop client on Windows (named pipe)
//! and Linux/macOS (Unix domain socket) without blocking the Slint UI thread.

use std::{
    io::{Read, Write},
    sync::mpsc::{Sender, channel},
    thread,
    time::{Duration, Instant},
};

#[cfg(unix)]
use std::os::unix::net::UnixStream;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActivityData {
    pub details: String,
    pub state: String,
    pub start_timestamp: Option<i64>,
}

enum Command {
    Update {
        app_id: String,
        activity: Option<ActivityData>,
    },
    Clear,
}

pub struct DiscordClient {
    tx: Sender<Command>,
}

impl DiscordClient {
    pub fn new() -> Self {
        let (tx, rx) = channel::<Command>();
        thread::Builder::new()
            .name("discord-rpc".into())
            .spawn(move || {
                run_worker(rx);
            })
            .expect("failed to spawn discord-rpc thread");
        Self { tx }
    }

    pub fn update(
        &self,
        app_id: &str,
        details: String,
        state: String,
        start_timestamp: Option<i64>,
    ) {
        let _ = self.tx.send(Command::Update {
            app_id: app_id.trim().to_string(),
            activity: Some(ActivityData {
                details,
                state,
                start_timestamp,
            }),
        });
    }

    pub fn clear(&self) {
        let _ = self.tx.send(Command::Clear);
    }
}

enum IpcStream {
    #[cfg(unix)]
    Unix(UnixStream),
    #[cfg(windows)]
    Windows(std::fs::File),
}

impl Read for IpcStream {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        match self {
            #[cfg(unix)]
            Self::Unix(s) => s.read(buf),
            #[cfg(windows)]
            Self::Windows(f) => f.read(buf),
        }
    }
}

impl Write for IpcStream {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        match self {
            #[cfg(unix)]
            Self::Unix(s) => s.write(buf),
            #[cfg(windows)]
            Self::Windows(f) => f.write(buf),
        }
    }

    fn flush(&mut self) -> std::io::Result<()> {
        match self {
            #[cfg(unix)]
            Self::Unix(s) => s.flush(),
            #[cfg(windows)]
            Self::Windows(f) => f.flush(),
        }
    }
}

fn connect_ipc() -> std::io::Result<IpcStream> {
    #[cfg(unix)]
    {
        let dirs = [
            std::env::var("XDG_RUNTIME_DIR").ok(),
            std::env::var("TMPDIR").ok(),
            std::env::var("TMP").ok(),
            std::env::var("TEMP").ok(),
            Some("/tmp".to_string()),
        ];
        for dir in dirs.into_iter().flatten() {
            let base = std::path::Path::new(&dir);
            for i in 0..10 {
                let path = base.join(format!("discord-ipc-{i}"));
                if let Ok(stream) = UnixStream::connect(&path) {
                    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
                    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
                    return Ok(IpcStream::Unix(stream));
                }
            }
        }
        Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "Could not connect to any discord-ipc socket",
        ))
    }
    #[cfg(windows)]
    {
        use std::fs::OpenOptions;
        for i in 0..10 {
            let pipe_name = format!(r"\\.\pipe\discord-ipc-{i}");
            if let Ok(file) = OpenOptions::new().read(true).write(true).open(&pipe_name) {
                return Ok(IpcStream::Windows(file));
            }
        }
        Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "Could not connect to any discord-ipc named pipe",
        ))
    }
}

fn send_frame<W: Write>(writer: &mut W, opcode: u32, payload: &str) -> std::io::Result<()> {
    let bytes = payload.as_bytes();
    let len = bytes.len() as u32;
    writer.write_all(&opcode.to_le_bytes())?;
    writer.write_all(&len.to_le_bytes())?;
    writer.write_all(bytes)?;
    writer.flush()?;
    Ok(())
}

fn read_frame<R: Read>(reader: &mut R) -> std::io::Result<(u32, String)> {
    let mut header = [0u8; 8];
    reader.read_exact(&mut header)?;
    let opcode = u32::from_le_bytes(header[0..4].try_into().unwrap());
    let length = u32::from_le_bytes(header[4..8].try_into().unwrap()) as usize;
    if length > 65536 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "Discord frame too large",
        ));
    }
    let mut buf = vec![0u8; length];
    reader.read_exact(&mut buf)?;
    let text = String::from_utf8(buf)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
    Ok((opcode, text))
}

fn run_worker(rx: std::sync::mpsc::Receiver<Command>) {
    let mut current_app_id = String::new();
    let mut current_activity: Option<ActivityData> = None;
    let mut stream: Option<IpcStream> = None;
    let mut last_connect_attempt = Instant::now() - Duration::from_secs(10);
    let mut nonce: u64 = 0;

    loop {
        let cmd = match rx.recv_timeout(Duration::from_millis(500)) {
            Ok(c) => Some(c),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => None,
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        };

        let mut dirty = false;
        if let Some(cmd) = cmd {
            match cmd {
                Command::Update { app_id, activity } => {
                    if app_id != current_app_id {
                        stream = None;
                        current_app_id = app_id;
                    }
                    if current_activity != activity {
                        current_activity = activity;
                        dirty = true;
                    }
                }
                Command::Clear => {
                    if current_activity.is_some() {
                        current_activity = None;
                        dirty = true;
                    }
                }
            }
        }

        if current_app_id.is_empty() {
            if stream.is_some() {
                stream = None;
            }
            continue;
        }

        if stream.is_none() && (dirty || current_activity.is_some()) {
            if last_connect_attempt.elapsed() >= Duration::from_secs(5) {
                last_connect_attempt = Instant::now();
                if let Ok(mut s) = connect_ipc() {
                    let handshake = serde_json::json!({
                        "v": 1,
                        "client_id": current_app_id
                    })
                    .to_string();
                    if send_frame(&mut s, 0, &handshake).is_ok() {
                        if let Ok((_op, _resp)) = read_frame(&mut s) {
                            stream = Some(s);
                            dirty = true;
                        }
                    }
                }
            }
        }

        if dirty {
            if let Some(ref mut s) = stream {
                nonce += 1;
                let payload = match &current_activity {
                    Some(act) => {
                        let mut activity_map = serde_json::Map::new();
                        activity_map.insert(
                            "details".into(),
                            serde_json::Value::String(act.details.clone()),
                        );
                        activity_map
                            .insert("state".into(), serde_json::Value::String(act.state.clone()));
                        if let Some(ts) = act.start_timestamp {
                            activity_map
                                .insert("timestamps".into(), serde_json::json!({ "start": ts }));
                        }
                        activity_map.insert(
                            "assets".into(),
                            serde_json::json!({
                                "large_text": "LootLedger",
                                "small_text": "Fortnite Chest Counter"
                            }),
                        );
                        serde_json::json!({
                            "cmd": "SET_ACTIVITY",
                            "args": {
                                "pid": std::process::id(),
                                "activity": activity_map
                            },
                            "nonce": nonce.to_string()
                        })
                    }
                    None => serde_json::json!({
                        "cmd": "SET_ACTIVITY",
                        "args": {
                            "pid": std::process::id(),
                            "activity": null
                        },
                        "nonce": nonce.to_string()
                    }),
                }
                .to_string();

                if send_frame(s, 1, &payload).is_err() {
                    stream = None;
                } else {
                    let _ = read_frame(s);
                }
            }
        }
    }
}
