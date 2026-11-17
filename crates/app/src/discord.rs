//! Discord Rich Presence over Discord's local IPC pipe (`discord-ipc-0`..`9`).
//! Speaks directly to the local Discord desktop client without extra dependencies or game hooks.

use serde_json::{Value, json};
use std::{
    io::{self, Read, Write},
    sync::mpsc::{self, RecvTimeoutError},
    time::Duration,
};

const OP_HANDSHAKE: u32 = 0;
const OP_FRAME: u32 = 1;
const OP_CLOSE: u32 = 2;
const OP_PING: u32 = 3;
const OP_PONG: u32 = 4;

const MAX_FRAME_BYTES: usize = 1024 * 1024;
const RETRY_INTERVAL: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Activity {
    pub details: String,
    pub state: String,
    pub start_timestamp: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Desired {
    pub enabled: bool,
    pub app_id: String,
    pub activity: Option<Activity>,
}

pub fn format_token_pct(prob_squad: f64) -> String {
    if prob_squad >= 0.01 {
        format!("{:.1}%", prob_squad * 100.0)
    } else if prob_squad > 0.0 {
        format!("{:.2}%", prob_squad * 100.0)
    } else {
        "0.0%".into()
    }
}

#[derive(Debug, Clone, Copy)]
pub struct StatusInput {
    pub in_match: bool,
    pub in_game: bool,
    pub last_match: Option<i64>,
    pub today: i64,
    pub squad_total: i64,
    pub token_prob_squad: f64,
    pub start_timestamp: Option<i64>,
}

pub fn format_activity(input: StatusInput, format_int: impl Fn(i64) -> String) -> Activity {
    let last = input
        .last_match
        .map(&format_int)
        .unwrap_or_else(|| "–".to_owned());
    let today_text = format_int(input.today);
    let prefix = if input.in_match {
        "In match · "
    } else if input.in_game {
        "In lobby · "
    } else {
        ""
    };
    let details = format!("{prefix}Last: {last} · Today: {today_text}");
    let state = format!(
        "Total: {} · Token: {}",
        format_int(input.squad_total),
        format_token_pct(input.token_prob_squad)
    );
    Activity {
        details,
        state,
        start_timestamp: if input.in_match {
            input.start_timestamp
        } else {
            None
        },
    }
}

pub fn build_set_activity(pid: u32, activity: Option<&Activity>, nonce: u64) -> Value {
    let act = match activity {
        Some(a) => {
            let mut obj = serde_json::Map::new();
            obj.insert("details".into(), json!(a.details));
            obj.insert("state".into(), json!(a.state));
            if let Some(ts) = a.start_timestamp {
                obj.insert("timestamps".into(), json!({ "start": ts }));
            }
            Value::Object(obj)
        }
        None => Value::Null,
    };
    json!({
        "cmd": "SET_ACTIVITY",
        "args": {
            "pid": pid,
            "activity": act,
        },
        "nonce": nonce.to_string(),
    })
}

pub fn write_frame<W: Write + ?Sized>(w: &mut W, op: u32, payload: &Value) -> io::Result<()> {
    let body = serde_json::to_vec(payload).map_err(io::Error::other)?;
    let len = u32::try_from(body.len())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "IPC payload too large"))?;
    let mut header = [0u8; 8];
    header[0..4].copy_from_slice(&op.to_le_bytes());
    header[4..8].copy_from_slice(&len.to_le_bytes());
    w.write_all(&header)?;
    w.write_all(&body)?;
    w.flush()
}

pub fn read_frame<R: Read + ?Sized>(r: &mut R) -> io::Result<(u32, Value)> {
    let mut header = [0u8; 8];
    r.read_exact(&mut header)?;
    let op = u32::from_le_bytes(header[0..4].try_into().expect("4 bytes"));
    let len = u32::from_le_bytes(header[4..8].try_into().expect("4 bytes")) as usize;
    if len > MAX_FRAME_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Discord IPC frame exceeded size limit",
        ));
    }
    let mut buf = vec![0u8; len];
    r.read_exact(&mut buf)?;
    let val =
        serde_json::from_slice(&buf).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    Ok((op, val))
}

trait IpcStream: Read + Write + Send {}
impl<T: Read + Write + Send> IpcStream for T {}

#[cfg(windows)]
fn open_pipe(slot: usize) -> Option<Box<dyn IpcStream>> {
    let path = format!(r"\\.\pipe\discord-ipc-{slot}");
    std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .ok()
        .map(|f| Box::new(f) as Box<dyn IpcStream>)
}

#[cfg(unix)]
fn open_pipe(slot: usize) -> Option<Box<dyn IpcStream>> {
    use std::os::unix::net::UnixStream;
    let mut dirs = Vec::new();
    if let Ok(runtime) = std::env::var("XDG_RUNTIME_DIR") {
        dirs.push(runtime);
    }
    if let Ok(tmp) = std::env::var("TMPDIR") {
        dirs.push(tmp);
    }
    dirs.push("/tmp".into());
    for dir in dirs {
        let path = std::path::Path::new(&dir).join(format!("discord-ipc-{slot}"));
        if let Ok(stream) = UnixStream::connect(&path) {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
            return Some(Box::new(stream));
        }
    }
    None
}

#[cfg(not(any(windows, unix)))]
fn open_pipe(_slot: usize) -> Option<Box<dyn IpcStream>> {
    None
}

enum ConnectError {
    NotRunning,
    Rejected(String),
}

fn read_reply(stream: &mut dyn IpcStream) -> io::Result<Value> {
    loop {
        let (op, val) = read_frame(stream)?;
        match op {
            OP_PING => {
                write_frame(stream, OP_PONG, &val)?;
            }
            OP_CLOSE => {
                return Err(io::Error::new(
                    io::ErrorKind::ConnectionReset,
                    val["message"]
                        .as_str()
                        .unwrap_or("Discord closed the IPC connection"),
                ));
            }
            OP_FRAME => return Ok(val),
            _ => {}
        }
    }
}

fn connect_and_handshake(app_id: &str) -> Result<Box<dyn IpcStream>, ConnectError> {
    for slot in 0..10 {
        let Some(mut stream) = open_pipe(slot) else {
            continue;
        };
        let hello = json!({ "v": 1, "client_id": app_id });
        if write_frame(&mut *stream, OP_HANDSHAKE, &hello).is_err() {
            continue;
        }
        match read_reply(&mut *stream) {
            Ok(reply) => {
                if reply["evt"] == "ERROR" {
                    let msg = reply["data"]["message"]
                        .as_str()
                        .unwrap_or("invalid Application ID")
                        .to_owned();
                    return Err(ConnectError::Rejected(msg));
                }
                return Ok(stream);
            }
            Err(_) => continue,
        }
    }
    Err(ConnectError::NotRunning)
}

fn send_set_activity(
    stream: &mut dyn IpcStream,
    pid: u32,
    activity: Option<&Activity>,
    nonce: &mut u64,
) -> Result<(), ConnectError> {
    *nonce += 1;
    let frame = build_set_activity(pid, activity, *nonce);
    write_frame(stream, OP_FRAME, &frame).map_err(|_| ConnectError::NotRunning)?;
    let reply = read_reply(stream).map_err(|_| ConnectError::NotRunning)?;
    if reply["evt"] == "ERROR" {
        let msg = reply["data"]["message"]
            .as_str()
            .unwrap_or("Discord rejected activity update")
            .to_owned();
        return Err(ConnectError::Rejected(msg));
    }
    Ok(())
}

fn close_conn(conn: &mut Option<(String, Box<dyn IpcStream>)>) {
    if let Some((_, mut stream)) = conn.take() {
        let _ = write_frame(&mut *stream, OP_CLOSE, &json!({}));
    }
}

enum Cmd {
    Update(Desired),
    Shutdown,
}

pub struct Client {
    tx: mpsc::Sender<Cmd>,
    last_sent: Option<Desired>,
}

impl Client {
    pub fn new(on_status: impl Fn(String) + Send + 'static) -> Client {
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || worker(rx, on_status));
        Client {
            tx,
            last_sent: None,
        }
    }

    pub fn update(&mut self, desired: Desired) {
        if self.last_sent.as_ref() == Some(&desired) {
            return;
        }
        self.last_sent = Some(desired.clone());
        let _ = self.tx.send(Cmd::Update(desired));
    }

    pub fn shutdown(&mut self) {
        self.last_sent = None;
        let _ = self.tx.send(Cmd::Shutdown);
    }
}

fn valid_app_id(id: &str) -> bool {
    let s = id.trim();
    !s.is_empty() && (17..=22).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_digit())
}

fn worker(rx: mpsc::Receiver<Cmd>, on_status: impl Fn(String)) {
    let pid = std::process::id();
    let mut desired = Desired::default();
    let mut conn: Option<(String, Box<dyn IpcStream>)> = None;
    let mut applied: Option<Activity> = None;
    let mut nonce = 0u64;
    let mut last_status = String::new();
    let mut publish_status = |text: String| {
        if text != last_status {
            last_status = text.clone();
            on_status(text);
        }
    };

    loop {
        let msg = if desired.enabled && valid_app_id(&desired.app_id) && desired.activity.is_some()
        {
            match rx.recv_timeout(RETRY_INTERVAL) {
                Ok(c) => Some(c),
                Err(RecvTimeoutError::Timeout) => None,
                Err(RecvTimeoutError::Disconnected) => break,
            }
        } else {
            match rx.recv() {
                Ok(c) => Some(c),
                Err(_) => break,
            }
        };

        if let Some(cmd) = msg {
            let mut shutdown = matches!(cmd, Cmd::Shutdown);
            if let Cmd::Update(d) = cmd {
                desired = d;
            }
            while let Ok(next) = rx.try_recv() {
                match next {
                    Cmd::Update(d) => desired = d,
                    Cmd::Shutdown => shutdown = true,
                }
            }
            if shutdown {
                if let Some((_, ref mut stream)) = conn
                    && applied.is_some()
                {
                    let _ = send_set_activity(&mut **stream, pid, None, &mut nonce);
                }
                close_conn(&mut conn);
                break;
            }
        }

        if !desired.enabled {
            if let Some((_, ref mut stream)) = conn
                && applied.is_some()
            {
                let _ = send_set_activity(&mut **stream, pid, None, &mut nonce);
            }
            applied = None;
            close_conn(&mut conn);
            publish_status(String::new());
            continue;
        }

        let app_id = desired.app_id.trim();
        if app_id.is_empty() {
            applied = None;
            close_conn(&mut conn);
            publish_status("Paste a Discord Application ID below to connect.".into());
            continue;
        }
        if !valid_app_id(app_id) {
            applied = None;
            close_conn(&mut conn);
            publish_status(
                "Application ID must be 17–22 digits from the Discord Developer Portal.".into(),
            );
            continue;
        }

        let Some(ref wanted) = desired.activity else {
            if let Some((_, ref mut stream)) = conn
                && applied.is_some()
            {
                let _ = send_set_activity(&mut **stream, pid, None, &mut nonce);
            }
            applied = None;
            close_conn(&mut conn);
            publish_status("Ready · waiting for Fortnite to start.".into());
            continue;
        };

        if conn.as_ref().is_some_and(|(id, _)| id != app_id) {
            applied = None;
            close_conn(&mut conn);
        }

        if conn.is_none() {
            match connect_and_handshake(app_id) {
                Ok(stream) => {
                    conn = Some((app_id.to_owned(), stream));
                    applied = None;
                }
                Err(ConnectError::Rejected(msg)) => {
                    publish_status(format!("Discord rejected Application ID: {msg}"));
                    continue;
                }
                Err(ConnectError::NotRunning) => {
                    publish_status("Discord desktop app not detected (retrying…).".into());
                    continue;
                }
            }
        }

        if applied.as_ref() != Some(wanted)
            && let Some((_, ref mut stream)) = conn
        {
            match send_set_activity(&mut **stream, pid, Some(wanted), &mut nonce) {
                Ok(()) => {
                    applied = Some(wanted.clone());
                    publish_status("Connected to Discord · showing status.".into());
                }
                Err(ConnectError::Rejected(msg)) => {
                    applied = None;
                    close_conn(&mut conn);
                    publish_status(format!("Discord error: {msg}"));
                }
                Err(ConnectError::NotRunning) => {
                    applied = None;
                    close_conn(&mut conn);
                    publish_status("Discord desktop app not detected (retrying…).".into());
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn frame_round_trip_matches_discord_ipc_wire_format() {
        let mut buf = Vec::new();
        let hello = json!({ "v": 1, "client_id": "123456789012345678" });
        write_frame(&mut buf, OP_HANDSHAKE, &hello).unwrap();

        assert_eq!(&buf[0..4], &0u32.to_le_bytes());
        let expected_len = serde_json::to_vec(&hello).unwrap().len() as u32;
        assert_eq!(&buf[4..8], &expected_len.to_le_bytes());

        let mut cursor = Cursor::new(buf);
        let (op, decoded) = read_frame(&mut cursor).unwrap();
        assert_eq!(op, OP_HANDSHAKE);
        assert_eq!(decoded, hello);
    }

    #[test]
    fn formats_live_lobby_and_idle_activities() {
        let fmt = |n: i64| {
            if n >= 1000 {
                format!("{},{:03}", n / 1000, n % 1000)
            } else {
                n.to_string()
            }
        };

        let live = format_activity(
            StatusInput {
                in_match: true,
                in_game: true,
                last_match: Some(12),
                today: 45,
                squad_total: 1234,
                token_prob_squad: 0.0124,
                start_timestamp: Some(1700000000),
            },
            fmt,
        );
        assert_eq!(live.details, "In match · Last: 12 · Today: 45");
        assert_eq!(live.state, "Total: 1,234 · Token: 1.2%");
        assert_eq!(live.start_timestamp, Some(1700000000));

        let lobby = format_activity(
            StatusInput {
                in_match: false,
                in_game: true,
                last_match: Some(12),
                today: 45,
                squad_total: 1234,
                token_prob_squad: 0.0042,
                start_timestamp: Some(1700000000),
            },
            fmt,
        );
        assert_eq!(lobby.details, "In lobby · Last: 12 · Today: 45");
        assert_eq!(lobby.state, "Total: 1,234 · Token: 0.42%");
        assert_eq!(lobby.start_timestamp, None);

        let always = format_activity(
            StatusInput {
                in_match: false,
                in_game: false,
                last_match: None,
                today: 0,
                squad_total: 0,
                token_prob_squad: 0.0,
                start_timestamp: None,
            },
            fmt,
        );
        assert_eq!(always.details, "Last: – · Today: 0");
        assert_eq!(always.state, "Total: 0 · Token: 0.0%");
    }

    #[test]
    fn builds_set_and_clear_activity_payloads() {
        let act = Activity {
            details: "In match · Last: 12 · Today: 45".into(),
            state: "Total: 1,234 · Token: 1.2%".into(),
            start_timestamp: Some(1700000000),
        };
        let set = build_set_activity(42, Some(&act), 7);
        assert_eq!(set["cmd"], "SET_ACTIVITY");
        assert_eq!(set["args"]["pid"], 42);
        assert_eq!(set["args"]["activity"]["details"], act.details);
        assert_eq!(set["args"]["activity"]["timestamps"]["start"], 1700000000);
        assert_eq!(set["nonce"], "7");

        let cleared = build_set_activity(42, None, 8);
        assert_eq!(cleared["cmd"], "SET_ACTIVITY");
        assert!(cleared["args"]["activity"].is_null());
    }
}
