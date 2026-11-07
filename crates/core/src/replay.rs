//! The replay decoder: a port of the vendored C# reader (Unreal.Core ReplayReader, the Fortnite reader and
//! FortniteReplayBuilder) limited to what LootLedger.ReplayReader/ChestReplayReader.cs needs, with the same
//! results. It keeps the old reader's quirks on purpose, because they change which openings are counted:
//! the export-group path matching, "incompatible" fields, the places where an exception aborts a packet,
//! a bunch or the whole file, and the builder's KeyNotFoundException for a pawn whose player state is
//! unknown (which also skips that pawn's mapping).
//!
//! Not ported because they cannot change the result: fast-array (delta) properties, RPCs (none are
//! registered at ParseMode.Normal), cosmetics, the kill feed, weapons, safe zones and checkpoints.

use crate::bits::{
    BitReader, ByteReader, END_ARRAY, END_BUNCH, END_CONTENT, END_FIELD, Exc, R, Ver, exc, hex,
};
use crate::container;
use crate::model::{Opening, Player, Replay};
use crate::tables::{GAME_STATE, PLAYER_PAWN, PLAYER_STATE};
use std::collections::{HashMap, HashSet};

const MAX_CHANNELS: usize = 32767;

/// How a replicated property is read (RepLayoutCmdType, plus the C# property type where it matters).
#[derive(Debug, Clone, Copy)]
pub enum Kind {
    Bool,
    U32,
    I32,
    I16,
    U16,
    U64,
    Byte,
    F32,
    F64,
    Str,
    NetId,
    Guid,
    Enum,
    Skip,
    Vector,
    Vector2D,
    Packed(i32, u32),
    Rotator,
    Name,
    /// A complex property type: consumed whole, never an error.
    Opaque,
    /// A dynamic array of this element kind (None: an element type the old reader ignores).
    Array(Option<&'static Kind>),
}

#[derive(Debug, Clone)]
enum Val {
    Bool(bool),
    Int(i64),
    Str(String),
    Other,
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Class {
    PlayerState,
    GameState,
    PlayerPawn,
    AnyPawn,
    Container,
    /// Registered by the old reader at ParseMode.Normal but irrelevant to chests.
    Other,
}

const ANY_PAWN: &[(&str, Kind)] = &[("PlayerState", Kind::Guid)];
const CONTAINER: &[(&str, Kind)] = &[
    ("bAlreadySearched", Kind::Bool),
    ("bDestroyed", Kind::Bool),
    ("SearchingPawn", Kind::Guid),
    ("SearchAnimationCount", Kind::U32),
];

impl Class {
    fn fields(self) -> Option<&'static [(&'static str, Kind)]> {
        match self {
            Class::PlayerState => Some(PLAYER_STATE),
            Class::GameState => Some(GAME_STATE),
            Class::PlayerPawn => Some(PLAYER_PAWN),
            Class::AnyPawn => Some(ANY_PAWN),
            Class::Container => Some(CONTAINER),
            Class::Other => None,
        }
    }
}

/// The export groups the old reader registers at ParseMode.Normal.
fn registered(path: &str) -> Option<Class> {
    Some(match path {
        "/Script/FortniteGame.FortPlayerStateAthena" => Class::PlayerState,
        "/Game/Athena/Athena_GameState.Athena_GameState_C" => Class::GameState,
        "/Game/Athena/PlayerPawn_Athena.PlayerPawn_Athena_C" => Class::PlayerPawn,
        "/Script/FortniteGame.ActiveGameplayModifier"
        | "/Script/FortniteGame.FortInventory"
        | "/Script/FortniteGame.FortPickupAthena"
        | "/Game/Spectating/BP_ReplayPC_Athena.BP_ReplayPC_Athena_C"
        | "/Game/Athena/SafeZone/SafeZoneIndicator.SafeZoneIndicator_C"
        | "CurrentPlaylistInfo" => Class::Other,
        _ => return None,
    })
}

/// ChestReplayReader's fallback regexes: `^[^:]*(?i:chest|ammo|/containers/|booty|lootcannon)[^:]*_C$` and
/// `^[^:]*(?i:pawn)[^:/]*_C$`.
fn fallback(path: &str) -> Option<Class> {
    if path.contains(':') || !path.ends_with("_C") {
        return None;
    }
    let head = path[..path.len() - 2].to_ascii_lowercase();
    if ["chest", "ammo", "/containers/", "booty", "lootcannon"]
        .iter()
        .any(|k| head.contains(k))
    {
        return Some(Class::Container);
    }
    let segment = head.rsplit('/').next().unwrap_or("");
    segment.contains("pawn").then_some(Class::AnyPawn)
}

pub fn remove_all_path_prefixes(path: &str) -> &str {
    for (i, c) in path.char_indices().rev() {
        match c {
            '.' => return &path[i + 1..],
            '/' => return path,
            _ => {}
        }
    }
    path.strip_prefix("Default__").unwrap_or(path)
}

fn clean_path_suffix(path: &str) -> &str {
    path.trim_end_matches(|c: char| c.is_ascii_digit() || c == '_')
}

struct Export {
    name: String,
    incompatible: bool,
    /// Cached index into the class field table (None inside: not a field of the class).
    prop: Option<Option<usize>>,
}

struct Group {
    /// The export-group map key (the path as received).
    key: String,
    /// PathName (ClassNetCache groups have their prefixes removed).
    path: String,
    path_index: u32,
    len: u32,
    exports: HashMap<u32, Export>,
}

#[derive(Default)]
struct Channel {
    actor: Option<(u32, Option<u32>)>,
    ignore: HashSet<String>,
}

#[derive(Clone, Copy, Default)]
struct Bunch {
    ch: u32,
    seq: i32,
    open: bool,
    close: bool,
    reliable: bool,
    partial: bool,
    initial: bool,
    last: bool,
    exports: bool,
    must_map: bool,
}

/// FortniteReplayBuilder's player data, reduced to what the result uses.
struct PlayerData {
    epic: Option<String>,
    bot_id: Option<String>,
    name: Option<String>,
    team: Option<i64>,
    owner: bool,
}

#[derive(Default)]
struct Builder {
    session: Option<String>,
    team_size: Option<i64>,
    recorder: Option<u32>,
    playlist: Option<String>,
    actor_to_channel: HashMap<u32, u32>,
    channel_to_actor: HashMap<u32, u32>,
    queued: HashMap<u32, Vec<(u32, u32)>>,
    spectators: HashSet<u32>,
    players: Vec<PlayerData>,
    player_of_channel: HashMap<u32, usize>,
    placement: Option<u32>,
    total_players: Option<u32>,
    eliminations: Option<u32>,
}

struct Episode {
    t: f32,
    kind: &'static str,
    pawn: Option<u32>,
}

struct Container {
    cls: String,
    pawn: Option<u32>,
    animations: u32,
    current: Option<usize>,
    searched: bool,
    destroyed: bool,
    episodes: Vec<Episode>,
}

#[derive(Clone, Default)]
struct StateInfo {
    epic: Option<String>,
    team: Option<i64>,
    bot: Option<bool>,
}

/// ChestReplayReader's own state.
#[derive(Default)]
struct Chest {
    containers: Vec<(u32, Container)>,
    container_of: HashMap<u32, usize>,
    pawn_to_state: HashMap<u32, u32>,
    states: Vec<(u32, StateInfo)>,
    state_of: HashMap<u32, usize>,
    recorder: Option<u32>,
    session: Option<String>,
    playlist: Option<String>,
    team_size: Option<i64>,
}

struct Values(Vec<(&'static str, Val)>);

impl Values {
    fn get(&self, name: &str) -> Option<&Val> {
        self.0
            .iter()
            .rev()
            .find(|(n, _)| *n == name)
            .map(|(_, v)| v)
    }
    fn int(&self, name: &str) -> Option<i64> {
        match self.get(name) {
            Some(Val::Int(v)) => Some(*v),
            _ => None,
        }
    }
    fn bool(&self, name: &str) -> Option<bool> {
        match self.get(name) {
            Some(Val::Bool(v)) => Some(*v),
            _ => None,
        }
    }
    fn str(&self, name: &str) -> Option<String> {
        match self.get(name) {
            Some(Val::Str(v)) => Some(v.clone()),
            _ => None,
        }
    }
    fn len(&self, name: &str) -> Option<i64> {
        self.int(name)
    }
}

struct Decoder {
    info: container::Info,
    ver: Ver,
    branch: Option<String>,
    groups: Vec<Group>,
    by_path: HashMap<String, usize>,
    from_index: HashMap<u32, usize>,
    guid_paths: HashMap<u32, String>,
    guid_group: HashMap<u32, usize>,
    cleaned: HashMap<u32, String>,
    failed: HashSet<String>,
    resolved: HashMap<String, Option<Class>>,
    group_class: HashMap<usize, Option<Class>>,
    external: HashMap<u32, Vec<u8>>,
    channels: Vec<Option<Channel>>,
    in_packet_id: i32,
    in_reliable: i32,
    partial: Option<(Bunch, BitReader<'static>)>,
    packet_temp: [usize; 4],
    cmd: BitReader<'static>,
    frame_time: f32,
    builder: Builder,
    chest: Chest,
}

/// Decode a replay file's bytes like `ChestReplayReader.Analyze`.
pub fn decode(file: &str, data: &[u8]) -> Replay {
    let mut d = Decoder {
        info: container::Info {
            version: 0,
            length_ms: 0,
            network_version: 0,
            changelist: 0,
            friendly_name: String::new(),
            live: false,
            timestamp: 0,
            compressed: false,
            encrypted: false,
            key: Vec::new(),
            chunks_start: 0,
        },
        ver: Ver::default(),
        branch: None,
        groups: Vec::new(),
        by_path: HashMap::new(),
        from_index: HashMap::new(),
        guid_paths: HashMap::new(),
        guid_group: HashMap::new(),
        cleaned: HashMap::new(),
        failed: HashSet::new(),
        resolved: HashMap::new(),
        group_class: HashMap::new(),
        external: HashMap::new(),
        channels: (0..MAX_CHANNELS).map(|_| None).collect(),
        in_packet_id: 0,
        in_reliable: 0,
        partial: None,
        packet_temp: [0; 4],
        cmd: BitReader::owned(Vec::new(), 0, Ver::default()),
        frame_time: 0.0,
        builder: Builder::default(),
        chest: Chest::default(),
    };
    let outcome = d.read(data);
    d.fill(file, outcome)
}

fn container_exc(e: container::Error) -> Exc {
    Exc(match e {
        container::Error::Decrypt => {
            "CryptographicException: Padding is invalid and cannot be removed.".into()
        }
        other => format!("InvalidReplayException: {other}"),
    })
}

impl Decoder {
    fn read(&mut self, data: &[u8]) -> R<()> {
        let info = container::read_info(data).map_err(container_exc)?;
        if !info.live && info.encrypted && info.key.is_empty() {
            return exc(
                "InvalidReplayException: Completed replay is marked encrypted but has no key!",
            );
        }
        if info.live && info.encrypted {
            return exc(
                "InvalidReplayException: Replay is marked encrypted but not yet marked as completed!",
            );
        }
        let mut r = ByteReader::new(data, Ver::default());
        r.pos = info.chunks_start;
        self.info = info;
        while !r.at_end() {
            let kind = r.u32()?;
            let size = r.i32()?;
            let offset = r.pos;
            if size <= 0 || size as i64 + offset as i64 > i32::MAX as i64 {
                return Ok(());
            }
            match kind {
                0 => self.header(&mut r)?,
                1 => self.replay_data(&mut r, size)?,
                3 => self.event(&mut r)?,
                _ => {}
            }
            r.pos = offset + size as usize;
        }
        Ok(())
    }

    fn header(&mut self, r: &mut ByteReader<'_>) -> R<()> {
        if r.u32()? != 0x2CF5_A13D {
            return exc("InvalidReplayException: Header.Magic != NETWORK_DEMO_MAGIC");
        }
        let network = r.u32()?;
        if network <= 5 {
            return exc("InvalidReplayException: Header.Version < MIN_NETWORK_DEMO_VERSION");
        }
        if network >= 19 {
            let count = r.i32()?;
            r.skip(count as i64 * 20);
        }
        r.u32()?; // checksum
        let engine = r.u32()?;
        r.u32()?; // game protocol
        if network >= 12 {
            r.take(16)?;
        }
        if network >= 11 {
            r.u16()?;
            r.u16()?;
            r.u16()?;
            r.u32()?;
            self.branch = Some(r.fstring()?);
        } else {
            r.u32()?;
        }
        if network >= 18 {
            r.take(12)?;
        }
        if network <= 6 {
            return exc("NotImplementedException: HISTORY_MULTIPLE_LEVELS not supported yet.");
        }
        let levels = r.u32()?;
        for _ in 0..levels {
            r.fstring()?;
            r.u32()?;
        }
        let flags = if network >= 9 { r.u32()? } else { 0 };
        let specific = r.u32()?;
        for _ in 0..specific {
            r.fstring()?;
        }
        if network >= 17 {
            r.take(16)?;
            r.fstring()?;
            r.u8()?;
            r.u8()?;
        }
        self.ver = Ver {
            engine,
            network,
            flags,
        };
        self.cmd.ver = self.ver;
        Ok(())
    }

    fn payload(&self, r: &mut ByteReader<'_>, size: i64) -> R<Vec<u8>> {
        let bytes = r.take(size)?;
        container::decrypt(&self.info, bytes).map_err(container_exc)
    }

    fn replay_data(&mut self, r: &mut ByteReader<'_>, chunk_size: i32) -> R<()> {
        let v = self.info.version;
        // The old reader tests these versions with Enum.HasFlag, i.e. as bit masks.
        let length = if v & 4 == 4 {
            r.u32()?;
            r.u32()?;
            r.u32()? as i32
        } else {
            chunk_size
        };
        if v & 6 == 6 {
            r.i32()?;
        }
        let bytes = self.payload(r, length as i64)?;
        let frames = container::decompress(&self.info, bytes).map_err(container_exc)?;
        let mut f = ByteReader::new(&frames, self.ver);
        while !f.at_end() {
            self.demo_frame(&mut f)?;
        }
        Ok(())
    }

    fn event(&mut self, r: &mut ByteReader<'_>) -> R<()> {
        r.fstring()?;
        let group = r.fstring()?;
        let metadata = r.fstring()?;
        r.u32()?;
        r.u32()?;
        let size = r.i32()?;
        let data = self.payload(r, size as i64)?;
        let mut e = ByteReader::new(&data, self.ver);
        if group == "playerElim" {
            return self
                .elimination(&mut e)
                .map_err(|err| Exc(format!("PlayerEliminationException: {}", err.0)));
        }
        match metadata.as_str() {
            "AthenaMatchStats" => {
                e.u32()?;
                e.f32()?;
                e.u32()?;
                let eliminations = e.u32()?;
                for _ in 0..8 {
                    e.u32()?;
                }
                self.builder.eliminations = Some(eliminations);
            }
            "AthenaMatchTeamStats" => {
                e.u32()?;
                let position = e.u32()?;
                let total = e.u32()?;
                self.builder.placement = Some(position);
                self.builder.total_players = Some(total);
            }
            "PlayerStateEncryptionKey" => {
                e.take(32)?;
            }
            _ => {}
        }
        Ok(())
    }

    /// Read only for its exceptions: a malformed elimination stops the whole old reader.
    fn elimination(&self, e: &mut ByteReader<'_>) -> R<()> {
        let version = e.i32()?;
        if version >= 3 {
            e.skip(1);
            if version >= 6 {
                e.take(40)?;
            }
            e.take(40)?;
        } else {
            let (major, minor) = self.branch_version();
            if major <= 4 && minor < 2 {
                e.skip(8);
            } else if major == 4 && minor <= 2 {
                e.skip(36);
            }
        }
        if self.ver.engine >= 34 {
            e.skip(80);
        }
        for _ in 0..2 {
            if version < 6 {
                e.fstring()?;
            } else {
                match e.u8()? {
                    0x10 => {
                        e.fstring()?;
                    }
                    0x11 => {
                        let n = e.u8()?;
                        e.take(n as i64)?;
                    }
                    _ => {}
                }
            }
        }
        e.u8()?;
        e.u32()?;
        Ok(())
    }

    fn branch_version(&self) -> (i32, i32) {
        let Some(rest) = self
            .branch
            .as_deref()
            .and_then(|b| b.split("++Fortnite+Release-").nth(1))
        else {
            return (0, 0);
        };
        let mut parts = rest.splitn(2, '.');
        let major = parts.next().and_then(|m| m.parse().ok()).unwrap_or(0);
        let minor = parts.next().map(|m| {
            m.chars()
                .take_while(char::is_ascii_digit)
                .collect::<String>()
        });
        (major, minor.and_then(|m| m.parse().ok()).unwrap_or(0))
    }

    fn demo_frame(&mut self, f: &mut ByteReader<'_>) -> R<()> {
        if self.ver.network >= 6 {
            f.i32()?;
        }
        self.frame_time = f.f32()?;
        if self.ver.network >= 10 {
            self.net_field_exports(f)?;
            self.net_export_guids(f)?;
        }
        let levels = f.int_packed()?;
        for _ in 0..levels {
            f.fstring()?;
            if !self.ver.streaming_fixes() {
                f.fstring()?;
                f.take(40)?;
            }
        }
        if self.ver.streaming_fixes() {
            f.u64()?;
        }
        loop {
            let bits = f.int_packed()?;
            if bits == 0 {
                break;
            }
            let guid = f.int_packed()?;
            let bytes = f.take((bits.wrapping_add(7) >> 3) as i64)?;
            self.external.insert(guid, bytes.to_vec());
        }
        if self.ver.game_specific_frame_data() {
            let skip = f.u64()?;
            if skip > 0 {
                f.skip(skip as i32 as i64);
            }
        }
        loop {
            if self.ver.streaming_fixes() {
                f.int_packed()?;
            }
            let size = f.i32()?;
            if size == 0 || !(0..=2048).contains(&size) {
                return Ok(());
            }
            let start = f.pos;
            f.take(size as i64)?;
            self.raw_packet(&f.data[start..], size as usize)?;
        }
    }

    fn net_field_export_bytes(f: &mut ByteReader<'_>, engine: u32) -> R<Option<(u32, String)>> {
        if !f.bool()? {
            return Ok(None);
        }
        let handle = f.int_packed()?;
        f.u32()?;
        let name = if engine < 9 {
            let name = f.fstring()?;
            f.fstring()?;
            name
        } else if engine < 10 {
            f.fstring()?
        } else {
            f.fname()?
        };
        Ok(Some((handle, name)))
    }

    fn net_field_export_bits(ar: &mut BitReader<'_>) -> R<Option<(u32, String)>> {
        if !ar.read_bit() {
            return Ok(None);
        }
        let handle = ar.read_int_packed()?;
        ar.read_u32()?;
        let engine = ar.ver.engine;
        let name = if engine < 9 {
            let name = ar.read_fstring()?;
            ar.read_fstring()?;
            name
        } else if engine < 10 {
            ar.read_fstring()?
        } else {
            ar.read_fname()?
        };
        Ok(Some((handle, name)))
    }

    fn add_group(&mut self, path: String, path_index: u32, len: u32) -> usize {
        let shown = if path.ends_with("ClassNetCache") {
            remove_all_path_prefixes(&path).to_owned()
        } else {
            path.clone()
        };
        let at = self.groups.len();
        self.by_path.insert(path.clone(), at);
        self.groups.push(Group {
            key: path,
            path: shown,
            path_index,
            len,
            exports: HashMap::new(),
        });
        self.from_index.insert(path_index, at);
        at
    }

    fn set_export(&mut self, group: Option<usize>, field: Option<(u32, String)>) {
        if let (Some(g), Some((handle, name))) = (group, field) {
            let group = &mut self.groups[g];
            if handle < group.len {
                group.exports.insert(
                    handle,
                    Export {
                        name,
                        incompatible: false,
                        prop: None,
                    },
                );
            }
        }
    }

    fn net_field_exports(&mut self, f: &mut ByteReader<'_>) -> R<()> {
        let count = f.int_packed()?;
        for _ in 0..count {
            let path_index = f.int_packed()?;
            let group = if f.int_packed()? == 1 {
                let path = f.fstring()?;
                let len = f.int_packed()?;
                match self.by_path.get(&path) {
                    Some(&g) => {
                        // Exports grow as more are encountered.
                        self.groups[g].len = self.groups[g].len.max(len);
                        Some(g)
                    }
                    None => Some(self.add_group(path, path_index, len)),
                }
            } else {
                self.from_index.get(&path_index).copied()
            };
            let field = Self::net_field_export_bytes(f, self.ver.engine)?;
            self.set_export(group, field);
        }
        Ok(())
    }

    fn net_export_guids(&mut self, f: &mut ByteReader<'_>) -> R<()> {
        let count = f.int_packed()?;
        for _ in 0..count {
            let size = f.i32()?;
            let start = f.pos;
            f.take(size as i64)?;
            let data = f.data;
            let mut reader =
                BitReader::borrowed(&data[start..], size as usize, size as usize * 8, self.ver);
            self.load_object(&mut reader, true, 0)?;
        }
        Ok(())
    }

    fn raw_packet(&mut self, data: &[u8], size: usize) -> R<()> {
        let last = data[size - 1];
        if last == 0 {
            return exc(
                "MalformedPacketException: Malformed packet: Received packet with 0's in last byte of packet",
            );
        }
        let bits = size * 8 - 1 - (last.leading_zeros() as usize);
        let mut packet = BitReader::borrowed(data, size, bits, self.ver);
        packet.temp = self.packet_temp;
        // The old reader logs and drops the rest of a packet that throws.
        let _ = self.packet(&mut packet);
        self.packet_temp = packet.temp;
        Ok(())
    }

    fn packet(&mut self, p: &mut BitReader<'_>) -> R<()> {
        self.in_packet_id += 1;
        let engine = self.ver.engine;
        while !p.at_end() {
            if engine < 8 {
                p.read_bit();
            }
            let mut b = Bunch::default();
            let control = p.read_bit();
            b.open = control && p.read_bit();
            b.close = control && p.read_bit();
            if engine < 7 {
                let _ = b.close && p.read_bit();
            } else if b.close {
                p.read_serialized_int(15);
            }
            p.read_bit(); // replication paused
            b.reliable = p.read_bit();
            b.ch = if engine < 3 {
                p.read_serialized_int(10240)
            } else {
                p.read_int_packed()?
            };
            b.exports = p.read_bit();
            b.must_map = p.read_bit();
            b.partial = p.read_bit();
            b.seq = if b.reliable {
                self.in_reliable + 1
            } else if b.partial {
                self.in_packet_id
            } else {
                0
            };
            b.initial = b.partial && p.read_bit();
            if b.partial && engine >= 36 {
                p.read_bit();
            }
            b.last = b.partial && p.read_bit();
            if engine < 6 {
                p.read_serialized_int(8);
            } else if b.reliable || b.open {
                p.read_fname()?;
            }
            let ch = b.ch as usize;
            if ch >= MAX_CHANNELS {
                return exc("IndexOutOfRangeException: Index was outside the bounds of the array.");
            }
            let bits = p.read_serialized_int(16384) as i64;
            if b.partial {
                let bytes = p.read_bits(bits)?;
                let mut archive = BitReader::owned(bytes, bits as usize, self.ver);
                if p.error {
                    break;
                }
                if b.exports {
                    self.net_guid_bunch(&mut archive)?;
                }
                self.channels[ch].get_or_insert_with(Channel::default);
                let _ = self.next_partial(b, archive);
            } else {
                p.set_temp_end(bits, END_BUNCH);
                if p.error {
                    break;
                }
                if b.exports {
                    self.net_guid_bunch(p)?;
                }
                self.channels[ch].get_or_insert_with(Channel::default);
                if b.reliable {
                    self.in_reliable = b.seq;
                }
                let _ = self.sequenced(b, p);
                p.restore_temp_end(END_BUNCH);
            }
        }
        Ok(())
    }

    fn net_guid_bunch(&mut self, ar: &mut BitReader<'_>) -> R<()> {
        if ar.read_bit() {
            let count = ar.read_u32()?;
            for _ in 0..count {
                if ar.error {
                    break; // every further iteration reads nothing and changes nothing
                }
                let path_index = ar.read_int_packed()?;
                let group = if ar.read_bit() {
                    let path = ar.read_fstring()?;
                    let len = ar.read_u32()?;
                    match self.by_path.get(&path) {
                        Some(&g) => Some(g),
                        None => Some(self.add_group(path, path_index, len)),
                    }
                } else {
                    self.from_index.get(&path_index).copied()
                };
                let field = Self::net_field_export_bits(ar)?;
                self.set_export(group, field);
            }
            return Ok(());
        }
        let count = ar.read_i32()?;
        if count > 2048 {
            return Ok(());
        }
        for _ in 0..count {
            self.load_object(ar, true, 0)?;
        }
        Ok(())
    }

    fn load_object(&mut self, ar: &mut BitReader<'_>, exporting: bool, depth: u32) -> R<u32> {
        if depth > 16 {
            return Ok(0);
        }
        let guid = ar.read_int_packed()?;
        if guid == 0 {
            return Ok(guid);
        }
        if guid == 1 || exporting {
            let flags = ar.read_byte()?;
            if flags & 1 != 0 {
                self.load_object(ar, true, depth + 1)?;
                let path = ar.read_fstring()?;
                if flags & 4 != 0 {
                    ar.read_u32()?;
                }
                if exporting {
                    self.guid_paths
                        .insert(guid, remove_all_path_prefixes(&path).to_owned());
                }
            }
        }
        Ok(guid)
    }

    fn next_partial(&mut self, b: Bunch, mut ar: BitReader<'static>) -> R<()> {
        if b.reliable {
            self.in_reliable = b.seq;
        }
        if b.initial {
            if let Some((p, _)) = &self.partial
                && !p.last
                && p.reliable
            {
                return Ok(());
            }
            self.partial = Some((b, ar));
            return Ok(());
        }
        let Some((p, archive)) = self.partial.as_mut() else {
            return Ok(());
        };
        let reliable_next = b.seq == p.seq + 1;
        let matches = if p.reliable {
            reliable_next
        } else {
            reliable_next || b.seq == p.seq
        };
        if p.last || !matches || p.reliable != b.reliable {
            return Ok(());
        }
        let left = ar.bits_left();
        if !b.exports && left > 0 {
            let data = ar.read_bits(left)?;
            archive.append(&data, left);
        }
        if !b.exports && !b.last && left % 8 != 0 {
            return Ok(());
        }
        p.seq = b.seq;
        if !b.last {
            return Ok(());
        }
        if b.exports {
            return Ok(());
        }
        p.last = true;
        p.close = b.close;
        p.must_map = b.must_map;
        let (bunch, mut archive) = self.partial.take().expect("partial bunch");
        let result = self.sequenced(bunch, &mut archive);
        self.partial = Some((bunch, archive));
        result
    }

    fn sequenced(&mut self, b: Bunch, ar: &mut BitReader<'_>) -> R<()> {
        if b.must_map {
            let count = ar.read_u16()?;
            for _ in 0..count {
                ar.read_int_packed()?;
            }
        }
        self.process_bunch(b, ar)?;
        if b.close {
            self.channels[b.ch as usize] = None;
        }
        Ok(())
    }

    fn quantized_vector(&self, ar: &mut BitReader<'_>) -> R<()> {
        if ar.read_bit() {
            let quantize = self.ver.engine < 13 || ar.read_bit();
            if quantize {
                ar.read_packed_vector(10, 24)
            } else {
                ar.read_fvector()
            }?;
        }
        Ok(())
    }

    fn process_bunch(&mut self, b: Bunch, ar: &mut BitReader<'_>) -> R<()> {
        let ch = b.ch as usize;
        if self.channels[ch]
            .as_ref()
            .is_some_and(|c| c.actor.is_none())
        {
            if !b.open {
                return Ok(());
            }
            let guid = self.load_object(ar, false, 0)?;
            let dynamic = guid > 0 && guid & 1 != 1;
            if ar.at_end() && dynamic {
                return Ok(());
            }
            let mut archetype = None;
            if dynamic {
                archetype = Some(self.load_object(ar, false, 0)?);
                if self.ver.engine >= 5 {
                    self.load_object(ar, false, 0)?;
                }
                self.quantized_vector(ar)?;
                if ar.read_bit() {
                    ar.read_rotation_short()?;
                }
                self.quantized_vector(ar)?;
                self.quantized_vector(ar)?;
            }
            if let Some(channel) = self.channels[ch].as_mut() {
                channel.actor = Some((guid, archetype));
            }
            self.builder.actor_to_channel.insert(guid, b.ch);
            self.builder.channel_to_actor.insert(b.ch, guid);
            if self
                .guid_paths
                .get(&archetype.unwrap_or(0))
                .is_some_and(|p| p == "BP_ReplayPC_Athena_C")
            {
                ar.read_byte()?; // netPlayerIndex
            }
        }
        while !ar.at_end() {
            let (rep, deleted, has_rep) = self.content_block_header(b, ar)?;
            let payload = if deleted {
                None
            } else {
                Some(ar.read_int_packed()?)
            };
            if ar.error {
                break;
            }
            let Some(payload) = payload else { continue };
            ar.set_temp_end(payload as i64, END_CONTENT);
            let stop = self.content_block(b, ar, rep, has_rep);
            // A C# finally: restored even when the block throws.
            ar.restore_temp_end(END_CONTENT);
            if stop? {
                break;
            }
        }
        Ok(())
    }

    fn content_block(
        &mut self,
        b: Bunch,
        ar: &mut BitReader<'_>,
        rep: Option<u32>,
        has_rep: bool,
    ) -> R<bool> {
        if ar.error {
            return Ok(true);
        }
        let Some(rep) = rep else { return Ok(false) };
        if ar.at_end() {
            return Ok(false);
        }
        self.replicator_bunch(b, ar, rep, has_rep)?;
        Ok(false)
    }

    fn content_block_header(
        &mut self,
        b: Bunch,
        ar: &mut BitReader<'_>,
    ) -> R<(Option<u32>, bool, bool)> {
        let has_rep = ar.read_bit();
        if ar.read_bit() {
            let actor = self.channels[b.ch as usize].as_ref().and_then(|c| c.actor);
            return Ok((
                actor.map(|(guid, archetype)| archetype.unwrap_or(guid)),
                false,
                has_rep,
            ));
        }
        let guid = self.load_object(ar, false, 0)?;
        if ar.read_bit() {
            return Ok((Some(guid), false, has_rep)); // stably named
        }
        let mut delete = false;
        let mut serialize_class = true;
        if self.ver.engine >= 30 && ar.read_bit() {
            delete = true;
            serialize_class = false;
            ar.read_byte()?;
        }
        let mut class = 0;
        if serialize_class {
            class = self.load_object(ar, false, 0)?;
            delete = class == 0;
        }
        if delete {
            return Ok((None, true, has_rep));
        }
        if self.ver.engine >= 18 && !(ar.at_end() || ar.read_bit()) {
            self.load_object(ar, false, 0)?;
        }
        Ok((Some(class), false, has_rep))
    }

    /// NetGuidCache.GetNetFieldExportGroup(netguid), including its substring matching and caches.
    fn group_for_guid(&mut self, guid: u32) -> Option<usize> {
        if let Some(&g) = self.guid_group.get(&guid) {
            return Some(g);
        }
        let path = self.guid_paths.get(&guid)?.clone();
        if self.failed.contains(&path) {
            return None;
        }
        for (at, group) in self.groups.iter().enumerate() {
            let fixed = self
                .cleaned
                .entry(group.path_index)
                .or_insert_with(|| remove_all_path_prefixes(&group.key).to_owned());
            if path.contains(fixed.as_str()) {
                self.guid_group.insert(guid, at);
                return Some(at);
            }
        }
        let cleaned = clean_path_suffix(&path);
        for (at, group) in self.groups.iter().enumerate() {
            if self
                .cleaned
                .get(&group.path_index)
                .is_some_and(|fixed| fixed.contains(cleaned))
            {
                self.guid_group.insert(guid, at);
                return Some(at);
            }
        }
        self.failed.insert(path);
        None
    }

    fn resolve(&mut self, path: &str) -> Option<Class> {
        if let Some(class) = registered(path) {
            return Some(class);
        }
        *self
            .resolved
            .entry(path.to_owned())
            .or_insert_with(|| fallback(path))
    }

    fn replicator_bunch(
        &mut self,
        b: Bunch,
        ar: &mut BitReader<'_>,
        rep: u32,
        has_rep: bool,
    ) -> R<bool> {
        let Some(g) = self.group_for_guid(rep) else {
            return Ok(true);
        };
        if has_rep {
            if !self.receive_properties(ar, g, b.ch)? {
                return Ok(false);
            }
            self.external_data(g, b.ch)?;
        }
        if ar.at_end() {
            return Ok(true);
        }
        let path = &self.groups[g].path;
        let key = if self.ver.engine >= 15 {
            format!("{path}_ClassNetCache")
        } else {
            format!("{}_ClassNetCache", remove_all_path_prefixes(path))
        };
        let Some(&cache) = self.by_path.get(&key) else {
            return Ok(false);
        };
        loop {
            if ar.at_end() {
                break;
            }
            let len = self.groups[cache].len;
            let handle = ar.read_serialized_int(len.max(2));
            if ar.error {
                break;
            }
            if handle >= len {
                return exc("IndexOutOfRangeException: Index was outside the bounds of the array.");
            }
            let field = self.groups[cache]
                .exports
                .get(&handle)
                .map(|e| (e.name.clone(), e.incompatible));
            let payload = ar.read_int_packed()? as i64;
            if ar.error || !ar.can_read(payload) {
                break;
            }
            ar.set_temp_end(payload, END_FIELD);
            let result = self.class_net_cache_field(ar, cache, field, b.ch);
            ar.restore_temp_end(END_FIELD);
            result?;
        }
        Ok(true)
    }

    /// Only GameState's CurrentPlaylistInfo custom struct affects the result; the other registered
    /// ClassNetCache properties are fast arrays whose reads are bounded by the field payload.
    fn class_net_cache_field(
        &mut self,
        ar: &mut BitReader<'_>,
        cache: usize,
        field: Option<(String, bool)>,
        ch: u32,
    ) -> R<()> {
        let Some((name, incompatible)) = field else {
            return Ok(());
        };
        if incompatible || ar.error || ar.at_end() {
            return Ok(());
        }
        if self.groups[cache].path != "Athena_GameState_C_ClassNetCache"
            || name != "CurrentPlaylistInfo"
        {
            return Ok(());
        }
        let bits = ar.bits_left();
        self.cmd.fill_bits_from(ar, bits)?;
        if self.ver.engine >= 11 {
            self.cmd.read_bit();
        }
        self.cmd.read_bit();
        let id = self.cmd.read_int_packed()?;
        self.cmd.skip_bits(31);
        let playlist = self.guid_paths.get(&id).cloned();
        if self.builder.playlist.is_none() {
            self.builder.playlist = playlist.clone();
        }
        if self.actor_of(ch).is_some() && self.chest.playlist.is_none() {
            self.chest.playlist = playlist;
        }
        Ok(())
    }

    fn actor_of(&self, ch: u32) -> Option<u32> {
        self.channels[ch as usize]
            .as_ref()
            .and_then(|c| c.actor)
            .map(|(guid, _)| guid)
    }

    fn receive_properties(&mut self, ar: &mut BitReader<'_>, g: usize, ch: u32) -> R<bool> {
        let path = self.groups[g].path.clone();
        match &self.channels[ch as usize] {
            None => return Ok(false),
            Some(c) if c.ignore.contains(&path) => return Ok(false),
            _ => {}
        }
        let class = match self.group_class.get(&g) {
            Some(&class) => class,
            None => {
                let class = self.resolve(&path);
                self.group_class.insert(g, class);
                class
            }
        };
        let Some(class) = class else {
            if let Some(c) = self.channels[ch as usize].as_mut() {
                c.ignore.insert(path);
            }
            return Ok(false);
        };
        ar.read_bit(); // property checksum
        let mut values = Values(Vec::new());
        let mut has_data = false;
        loop {
            let handle = ar.read_int_packed()?;
            if handle == 0 {
                break;
            }
            let handle = handle - 1;
            if handle >= self.groups[g].len {
                return Ok(false);
            }
            let bits = ar.read_int_packed()? as i64;
            if bits == 0 {
                continue;
            }
            match self.groups[g].exports.get(&handle) {
                None => {
                    ar.skip_bits(bits);
                    continue;
                }
                Some(e) if e.incompatible => {
                    ar.skip_bits(bits);
                    continue;
                }
                _ => {}
            }
            has_data = true;
            // ReceiveProperties catches exceptions per field and moves on.
            if let Ok(found) = self.read_field(ar, g, handle, bits, class, &mut values)
                && (!found || self.cmd.error || !self.cmd.at_end())
                && let Some(e) = self.groups[g].exports.get_mut(&handle)
            {
                e.incompatible = true;
            }
        }
        if has_data {
            self.on_export(ch, class, &path, &values)?;
        }
        Ok(true)
    }

    fn read_field(
        &mut self,
        ar: &mut BitReader<'_>,
        g: usize,
        handle: u32,
        bits: i64,
        class: Class,
        values: &mut Values,
    ) -> R<bool> {
        self.cmd.fill_bits_from(ar, bits)?;
        let Some(fields) = class.fields() else {
            self.cmd.pos = self.cmd.last; // a registered class LootLedger does not use
            return Ok(true);
        };
        let group = &mut self.groups[g];
        let export = group.exports.get_mut(&handle).expect("checked export");
        let prop = *export
            .prop
            .get_or_insert_with(|| fields.iter().position(|(n, _)| *n == export.name));
        let Some(prop) = prop else { return Ok(false) };
        let (name, kind) = fields[prop];
        let value = read_kind(&mut self.cmd, group, &kind)?;
        if let Some(value) = value
            && !self.cmd.error
        {
            values.0.push((name, value));
        }
        Ok(true)
    }

    fn external_data(&mut self, g: usize, ch: u32) -> R<()> {
        let Some(channel) = &self.channels[ch as usize] else {
            return Ok(());
        };
        if channel.ignore.contains(&self.groups[g].path) {
            return Ok(());
        }
        let Some(data) = self
            .actor_of(ch)
            .and_then(|actor| self.external.remove(&actor))
        else {
            return Ok(());
        };
        let mut r = ByteReader::new(&data, self.ver);
        r.u8()?;
        r.u8()?;
        let is_player = r.bool()?;
        let units = r.fstring_units()?;
        let name = if is_player {
            let len = units.len();
            let decoded: Vec<u16> = units
                .iter()
                .enumerate()
                .map(|(i, &u)| u.wrapping_add((((len % 4 * 3 % 8) + 1 + i) * 3 % 8) as u16))
                .collect();
            String::from_utf16_lossy(&decoded)
        } else {
            String::from_utf16_lossy(&units)
        };
        if let Some(&at) = self.builder.player_of_channel.get(&ch) {
            self.builder.players[at].name = Some(name);
        }
        Ok(())
    }

    fn on_export(&mut self, ch: u32, class: Class, path: &str, v: &Values) -> R<()> {
        let actor = self.actor_of(ch);
        match class {
            Class::GameState => {
                let b = &mut self.builder;
                if b.session.is_none() {
                    b.session = v.str("GameSessionId");
                }
                if b.team_size.is_none() {
                    b.team_size = v.int("TeamSize");
                }
                if b.team_size.is_none() {
                    b.team_size = v.len("ActiveTeamNums");
                }
                let recorder = v.int("RecorderPlayerState").map(|r| r as u32);
                if b.recorder.is_none() {
                    b.recorder = recorder;
                }
                if actor.is_some() {
                    if let Some(r) = recorder.filter(|&r| r != 0) {
                        self.chest.recorder = Some(r);
                    }
                    if self.chest.session.is_none() {
                        self.chest.session = v.str("GameSessionId");
                    }
                    if self.chest.team_size.is_none() {
                        self.chest.team_size = v.int("TeamSize");
                    }
                }
            }
            Class::PlayerState => {
                self.update_player_state(ch, v)?;
                if let Some(actor) = actor {
                    let at = *self.chest.state_of.entry(actor).or_insert_with(|| {
                        self.chest.states.push((actor, StateInfo::default()));
                        self.chest.states.len() - 1
                    });
                    let old = &mut self.chest.states[at].1;
                    old.epic = v
                        .str("UniqueId")
                        .or_else(|| v.str("UniqueID"))
                        .or(old.epic.take());
                    old.team = v.int("TeamIndex").or(old.team);
                    old.bot = v.bool("bIsABot").or(old.bot);
                }
            }
            Class::PlayerPawn | Class::AnyPawn => {
                let state = v.int("PlayerState").map(|s| s as u32);
                if class == Class::PlayerPawn {
                    self.update_player_pawn(ch, state)?;
                }
                if let (Some(actor), Some(state)) = (actor, state.filter(|&s| s != 0)) {
                    self.chest.pawn_to_state.insert(actor, state);
                }
            }
            Class::Container => {
                if let Some(actor) = actor {
                    self.on_container(actor, path, v);
                }
            }
            Class::Other => {}
        }
        Ok(())
    }

    fn update_player_state(&mut self, ch: u32, v: &Values) -> R<()> {
        let b = &mut self.builder;
        if v.bool("bOnlySpectator") == Some(true) {
            b.spectators.insert(ch);
            return Ok(());
        }
        if b.spectators.contains(&ch) {
            return Ok(());
        }
        let team = v.int("TeamIndex");
        let new = !b.player_of_channel.contains_key(&ch);
        if new {
            let owner = b.recorder.is_some() && b.channel_to_actor.get(&ch).copied() == b.recorder;
            b.players.push(PlayerData {
                epic: v.str("UniqueId").or_else(|| v.str("UniqueID")),
                bot_id: v.str("BotUniqueId"),
                name: None,
                team,
                owner,
            });
            b.player_of_channel.insert(ch, b.players.len() - 1);
        }
        if let Some(team) = team.filter(|&t| t > 0) {
            let at = b.player_of_channel[&ch];
            b.players[at].team = Some(team);
        }
        if new
            && let Some(actor) = b.channel_to_actor.get(&ch).copied()
            && let Some(pawns) = b.queued.remove(&actor)
        {
            for (pawn_channel, state) in pawns {
                self.update_player_pawn(pawn_channel, Some(state))?;
            }
        }
        Ok(())
    }

    fn update_player_pawn(&mut self, ch: u32, state: Option<u32>) -> R<()> {
        let Some(state) = state else { return Ok(()) };
        let b = &mut self.builder;
        let Some(&state_channel) = b.actor_to_channel.get(&state) else {
            b.queued.entry(state).or_default().push((ch, state));
            return Ok(());
        };
        if !b.player_of_channel.contains_key(&state_channel) {
            return exc("KeyNotFoundException: The given key was not present in the dictionary.");
        }
        Ok(())
    }

    fn on_container(&mut self, actor: u32, path: &str, v: &Values) {
        let searched = v.bool("bAlreadySearched");
        let destroyed = v.bool("bDestroyed");
        let pawn = v.int("SearchingPawn").map(|p| p as u32);
        let animations = v.int("SearchAnimationCount").map(|a| a as u32);
        if searched.is_none() && destroyed.is_none() && pawn.is_none() && animations.is_none() {
            return;
        }
        let at = *self.chest.container_of.entry(actor).or_insert_with(|| {
            let cls = path.rsplit(['.', '/']).next().unwrap_or("").to_owned();
            let container = Container {
                cls,
                pawn: None,
                animations: 0,
                current: None,
                searched: false,
                destroyed: false,
                episodes: Vec::new(),
            };
            self.chest.containers.push((actor, container));
            self.chest.containers.len() - 1
        });
        let t = self.frame_time;
        let c = &mut self.chest.containers[at].1;
        if searched == Some(false) {
            // The container was reset (some modes respawn chests): a later search is a new opening.
            c.current = None;
            c.searched = false;
            c.pawn = None;
        }
        if let Some(animations) = animations {
            c.animations = animations;
        }
        if let Some(pawn) = pawn.filter(|&p| p != 0) {
            c.pawn = Some(pawn);
            if let Some(current) = c.current
                && c.episodes[current].pawn.is_none()
            {
                c.episodes[current].pawn = Some(pawn);
            }
        }
        if searched == Some(true) && !c.searched {
            c.searched = true;
            c.episodes.push(Episode {
                t,
                kind: "opened",
                pawn: c.pawn,
            });
            c.current = Some(c.episodes.len() - 1);
        }
        if destroyed == Some(true) && !c.destroyed {
            c.destroyed = true;
            // A pawn without a completed search animation is only a cancelled interaction.
            if !c.searched && c.pawn.is_some() && c.animations > 0 {
                c.episodes.push(Episode {
                    t,
                    kind: "broken",
                    pawn: c.pawn,
                });
                c.current = Some(c.episodes.len() - 1);
            }
        }
    }

    fn fill(self, file: &str, outcome: R<()>) -> Replay {
        let ok = outcome.is_ok();
        let info = &self.info;
        let b = &self.builder;
        let c = &self.chest;
        // The builder's data only exists when the whole file was read.
        let players: &[PlayerData] = if ok { &b.players } else { &[] };
        let name_of = |epic: Option<&str>| -> Option<String> {
            let epic = epic?;
            players
                .iter()
                .find(|p| p.epic.as_deref() == Some(epic) || p.bot_id.as_deref() == Some(epic))
                .and_then(|p| p.name.clone())
        };
        let state = |actor: u32| {
            c.state_of
                .get(&actor)
                .map(|&at| c.states[at].1.clone())
                .unwrap_or_default()
        };
        let recorder = c.recorder.or(if ok { b.recorder } else { None });
        let owner = recorder.map(|r| {
            let me = state(r);
            let data = players.iter().find(|p| p.owner);
            Player {
                epic_id: me
                    .epic
                    .clone()
                    .or_else(|| data.and_then(|d| d.epic.clone())),
                name: data
                    .and_then(|d| d.name.clone())
                    .or_else(|| name_of(me.epic.as_deref())),
                team: me.team.or_else(|| data.and_then(|d| d.team)),
                bot: None,
            }
        });
        let my_team = owner.as_ref().and_then(|o| o.team);
        let teammates = match my_team {
            Some(team) => c
                .states
                .iter()
                .filter(|(actor, s)| Some(*actor) != recorder && s.team == Some(team))
                .map(|(_, s)| Player {
                    epic_id: s.epic.clone(),
                    name: name_of(s.epic.as_deref()),
                    team: s.team,
                    bot: s.bot,
                })
                .collect(),
            None => Vec::new(),
        };
        let mut events = Vec::new();
        for (actor, container) in &c.containers {
            for (i, episode) in container.episodes.iter().enumerate() {
                let (by, epic) = match episode.pawn.and_then(|p| c.pawn_to_state.get(&p)) {
                    None => ("unknown", None),
                    Some(&s) if Some(s) == recorder => ("me", None),
                    Some(&s) => {
                        let info = state(s);
                        (
                            if my_team.is_some() && info.team == my_team {
                                "team"
                            } else {
                                "other"
                            },
                            info.epic,
                        )
                    }
                };
                events.push(Opening {
                    t: (episode.t as f64 * 100.0).round_ties_even() / 100.0,
                    cls: container.cls.clone(),
                    kind: episode.kind.to_owned(),
                    by: by.to_owned(),
                    player: if by == "team" {
                        name_of(epic.as_deref())
                    } else {
                        None
                    },
                    player_id: match by {
                        "me" => owner.as_ref().and_then(|o| o.epic_id.clone()),
                        "team" => epic,
                        _ => None,
                    },
                    pawn: episode.pawn,
                    actor: *actor,
                    episode: i as u32,
                });
            }
        }
        // The old reader's List.Sort is unstable, so the order of openings with equal times is arbitrary.
        events.sort_by(|a, b| a.t.total_cmp(&b.t));
        let positive = |v: Option<u32>| v.filter(|&v| v > 0).map(i64::from);
        Replay {
            file: file.to_owned(),
            ok,
            live: info.live,
            timestamp: ticks_to_iso(info.timestamp),
            length_seconds: info.length_ms as f64 / 1000.0,
            session_id: if ok { b.session.clone() } else { None }.or_else(|| c.session.clone()),
            playlist: if ok { b.playlist.clone() } else { None }.or_else(|| c.playlist.clone()),
            branch: self.branch.clone(),
            team_size: if ok { b.team_size } else { None }.or(c.team_size),
            placement: if ok { positive(b.placement) } else { None },
            total_players: if ok { positive(b.total_players) } else { None },
            eliminations: if ok {
                b.eliminations.map(|e| e as i32 as i64)
            } else {
                None
            },
            owner,
            teammates,
            events,
            error: outcome.err().map(|e| e.0),
        }
    }
}

fn read_kind(cmd: &mut BitReader<'_>, group: &Group, kind: &Kind) -> R<Option<Val>> {
    Ok(Some(match kind {
        Kind::Bool => Val::Bool(cmd.read_bit()),
        Kind::U32 => Val::Int(cmd.read_u32()? as i64),
        Kind::I32 => Val::Int(cmd.read_i32()? as i64),
        Kind::I16 => Val::Int(cmd.read_i16()? as i64),
        Kind::U16 => Val::Int(cmd.read_u16()? as i64),
        Kind::U64 => Val::Int(cmd.read_u64()? as i64),
        Kind::Byte => Val::Int(cmd.read_byte()? as i64),
        Kind::F32 => {
            cmd.read_f32()?;
            Val::Other
        }
        Kind::F64 => {
            cmd.read_f64()?;
            Val::Other
        }
        Kind::Str => Val::Str(cmd.read_fstring()?),
        Kind::Name => Val::Str(cmd.read_fname()?),
        Kind::NetId => Val::Str(net_id(cmd)?),
        Kind::Guid => Val::Int(cmd.read_int_packed()? as i64),
        Kind::Enum => Val::Int(cmd.read_bits_to_int(cmd.bits_left()) as i64),
        Kind::Skip => {
            cmd.skip_bits(cmd.bits_left());
            return Ok(None);
        }
        Kind::Opaque => {
            cmd.pos = cmd.last;
            Val::Other
        }
        Kind::Vector => {
            cmd.read_fvector()?;
            Val::Other
        }
        Kind::Vector2D => {
            cmd.read_f32()?;
            cmd.read_f32()?;
            Val::Other
        }
        Kind::Packed(scale, bits) => {
            cmd.read_packed_vector(*scale, *bits)?;
            Val::Other
        }
        Kind::Rotator => {
            cmd.read_rotation_short()?;
            Val::Other
        }
        Kind::Array(element) => return read_array(cmd, group, *element),
    }))
}

/// NetFieldParser.ReadArrayField for arrays of primitive elements; the value kept is the length.
fn read_array(cmd: &mut BitReader<'_>, group: &Group, element: Option<&Kind>) -> R<Option<Val>> {
    let count = cmd.read_int_packed()?;
    let Some(element) = element else {
        return Ok(None);
    };
    let len = Some(Val::Int(count as i64));
    loop {
        let index = cmd.read_int_packed()?;
        if index == 0 {
            if cmd.bits_left() == 8 {
                cmd.read_int_packed()?;
            }
            return Ok(len);
        }
        if index > count {
            return Ok(len);
        }
        loop {
            let handle = cmd.read_int_packed()?;
            if handle == 0 {
                break;
            }
            let handle = handle - 1;
            if group.len < handle {
                return Ok(len);
            }
            if handle == group.len {
                return exc("IndexOutOfRangeException: Index was outside the bounds of the array.");
            }
            let bits = cmd.read_int_packed()? as i64;
            if bits == 0 {
                continue;
            }
            if !group.exports.contains_key(&handle) {
                cmd.skip_bits(bits);
                continue;
            }
            cmd.set_temp_end(bits, END_ARRAY);
            let result = read_kind(cmd, group, element);
            cmd.restore_temp_end(END_ARRAY);
            result?;
        }
    }
}

/// NetBitReader.SerializePropertyNetId.
fn net_id(cmd: &mut BitReader<'_>) -> R<String> {
    let flags = cmd.read_byte()?;
    let encoded = flags & 1 != 0;
    if encoded && flags & 2 != 0 {
        return Ok(String::new());
    }
    let type_hash = (flags & 0xF8) >> 3;
    if type_hash == 0 {
        return Ok("NULL".into());
    }
    if type_hash == 31 && cmd.read_fstring()? == "None" {
        return Ok(String::new());
    }
    if encoded {
        let size = cmd.read_byte()?;
        return Ok(hex(&cmd.read_bytes(size as i64)?));
    }
    cmd.read_fstring()
}

/// .NET ticks (local, unspecified kind) as System.Text.Json writes a DateTime: trailing zero digits trimmed.
fn ticks_to_iso(ticks: i64) -> Option<String> {
    let ticks = ticks & 0x3FFF_FFFF_FFFF_FFFF;
    if ticks == 0 {
        return None;
    }
    let base = chrono::NaiveDate::from_ymd_opt(1, 1, 1)?.and_hms_opt(0, 0, 0)?;
    let time = base.checked_add_signed(chrono::Duration::microseconds(ticks / 10))?;
    let mut text = time.format("%Y-%m-%dT%H:%M:%S").to_string();
    let fraction = format!("{:07}", ticks % 10_000_000);
    let fraction = fraction.trim_end_matches('0');
    if !fraction.is_empty() {
        text.push('.');
        text.push_str(fraction);
    }
    Some(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn group_fallbacks_match_the_old_regexes() {
        assert_eq!(
            fallback(
                "/Game/Building/ActorBlueprints/Containers/Tiered_Chest_Athena.Tiered_Chest_Athena_C"
            ),
            Some(Class::Container)
        );
        assert_eq!(
            fallback("/Game/Athena/AI/X/BP_NPCPawn_Base.BP_NPCPawn_Base_C"),
            Some(Class::AnyPawn)
        );
        assert_eq!(fallback("/Game/Pawns/Folder/Thing.Thing_C"), None); // "pawn" before the last '/'
        assert_eq!(fallback("/Script/FortniteGame.Chest:Fn_C"), None);
        assert_eq!(fallback("Tiered_Chest_c"), None);
        assert_eq!(remove_all_path_prefixes("/Game/A.B_C"), "B_C");
        assert_eq!(remove_all_path_prefixes("Default__Foo"), "Foo");
        assert_eq!(clean_path_suffix("Chest_C_12"), "Chest_C");
    }

    #[test]
    fn timestamps_match_dotnet_json() {
        // 2026-11-04T02:28:12.632 as .NET ticks
        let base = chrono::NaiveDate::from_ymd_opt(2026, 11, 4)
            .unwrap()
            .and_hms_milli_opt(2, 28, 12, 632)
            .unwrap();
        let start = chrono::NaiveDate::from_ymd_opt(1, 1, 1)
            .unwrap()
            .and_hms_opt(0, 0, 0)
            .unwrap();
        let ticks = (base - start).num_microseconds().unwrap() * 10;
        assert_eq!(
            ticks_to_iso(ticks).as_deref(),
            Some("2026-11-04T02:28:12.632")
        );
        assert_eq!(ticks_to_iso(0), None);
    }

    #[test]
    fn a_live_encrypted_replay_is_refused_like_the_old_reader() {
        let mut data = Vec::new();
        for v in [container::MAGIC, 7, 0, 1000, 1, 1] {
            data.extend(v.to_le_bytes());
        }
        data.extend(2i32.to_le_bytes());
        data.extend(b"x\0");
        data.extend(1u32.to_le_bytes()); // live
        data.extend(0i64.to_le_bytes());
        data.extend(1u32.to_le_bytes());
        data.extend(1u32.to_le_bytes()); // encrypted
        data.extend(0u32.to_le_bytes());
        let result = decode("x.replay", &data);
        assert!(!result.ok && !result.live); // the old reader threw before keeping the header
        assert_eq!(
            result.error.as_deref(),
            Some(
                "InvalidReplayException: Replay is marked encrypted but not yet marked as completed!"
            )
        );
    }
}
