//! The local replay file: header, chunks, AES-256-ECB decryption and Oodle decompression.
//!
//! Layout (Unreal's LocalFileNetworkReplayStreaming): magic, file version, custom versions (v7+), length in
//! ms, network version, changelist, friendly name, live flag, timestamp (v3+), compressed flag (v2+),
//! encrypted flag and key (v6+), then chunks of `kind: u32, size: i32, data`. Unreal writes the key only
//! when the replay is finalized, so a live replay is "locked".

use std::fmt;

pub const MAGIC: u32 = 0x1CA2_E27F;

#[derive(Debug)]
pub enum Error {
    NotAReplay,
    Truncated(&'static str),
    Locked,
    Decrypt,
    Decompress(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::NotAReplay => write!(f, "not a Fortnite replay"),
            Error::Truncated(what) => write!(f, "replay ends inside the {what}"),
            Error::Locked => write!(
                f,
                "replay is still being recorded or its decryption key is unavailable"
            ),
            Error::Decrypt => write!(f, "replay chunk could not be decrypted"),
            Error::Decompress(why) => write!(f, "replay chunk could not be decompressed: {why}"),
        }
    }
}

impl std::error::Error for Error {}

pub type Result<T> = std::result::Result<T, Error>;

/// A little-endian reader over a byte slice.
pub struct Bytes<'a> {
    pub data: &'a [u8],
    pub pos: usize,
}

impl<'a> Bytes<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Bytes { data, pos: 0 }
    }
    pub fn take(&mut self, n: usize, what: &'static str) -> Result<&'a [u8]> {
        let end = self
            .pos
            .checked_add(n)
            .filter(|&e| e <= self.data.len())
            .ok_or(Error::Truncated(what))?;
        let out = &self.data[self.pos..end];
        self.pos = end;
        Ok(out)
    }
    pub fn u32(&mut self, what: &'static str) -> Result<u32> {
        Ok(u32::from_le_bytes(
            self.take(4, what)?.try_into().expect("4 bytes"),
        ))
    }
    pub fn i32(&mut self, what: &'static str) -> Result<i32> {
        Ok(self.u32(what)? as i32)
    }
    pub fn i64(&mut self, what: &'static str) -> Result<i64> {
        Ok(i64::from_le_bytes(
            self.take(8, what)?.try_into().expect("8 bytes"),
        ))
    }
    /// Unreal FString: length with terminator; negative means UTF-16.
    pub fn fstring(&mut self, what: &'static str) -> Result<String> {
        let len = self.i32(what)?;
        if len == 0 {
            return Ok(String::new());
        }
        if len < 0 {
            let raw = self.take(len.unsigned_abs() as usize * 2, what)?;
            let units: Vec<u16> = raw
                .as_chunks::<2>()
                .0
                .iter()
                .map(|c| u16::from_le_bytes(*c))
                .collect();
            return Ok(String::from_utf16_lossy(&units)
                .trim_end_matches('\0')
                .to_owned());
        }
        let raw = self.take(len as usize, what)?;
        Ok(String::from_utf8_lossy(raw)
            .trim_end_matches('\0')
            .to_owned())
    }
}

#[derive(Debug, Clone)]
pub struct Info {
    pub version: u32,
    pub length_ms: u32,
    pub network_version: u32,
    pub changelist: u32,
    pub friendly_name: String,
    pub live: bool,
    /// .NET ticks (100 ns since 0001-01-01), local clock time of the recording PC.
    pub timestamp: i64,
    pub compressed: bool,
    pub encrypted: bool,
    pub key: Vec<u8>,
    /// Offset of the first chunk.
    pub chunks_start: usize,
}

impl Info {
    /// Match the old decoder's live guard and recognize Fortnite's 32-byte zero placeholder.
    pub fn locked(&self) -> bool {
        self.encrypted && (self.live || self.key.is_empty() || self.key.iter().all(|&b| b == 0))
    }
}

pub fn read_info(data: &[u8]) -> Result<Info> {
    let mut r = Bytes::new(data);
    if r.u32("header")? != MAGIC {
        return Err(Error::NotAReplay);
    }
    let version = r.u32("header")?;
    if version >= 7 {
        let count = r.u32("header")? as usize;
        r.take(count * 20, "header")?;
    }
    let length_ms = r.u32("header")?;
    let network_version = r.u32("header")?;
    let changelist = r.u32("header")?;
    let friendly_name = r.fstring("header")?;
    let live = r.u32("header")? != 0;
    let timestamp = if version >= 3 { r.i64("header")? } else { 0 };
    let compressed = version >= 2 && r.u32("header")? != 0;
    let (encrypted, key) = if version >= 6 {
        let encrypted = r.u32("header")? != 0;
        let size = r.u32("header")? as usize;
        (encrypted, r.take(size, "header")?.to_vec())
    } else {
        (false, Vec::new())
    };
    Ok(Info {
        version,
        length_ms,
        network_version,
        changelist,
        friendly_name,
        live,
        timestamp,
        compressed,
        encrypted,
        key,
        chunks_start: r.pos,
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChunkKind {
    Header,
    ReplayData,
    Checkpoint,
    Event,
    Unknown(u32),
}

pub struct Chunk<'a> {
    pub kind: ChunkKind,
    pub data: &'a [u8],
}

/// Complete chunks in order; stops quietly at a chunk that is still being written.
pub fn chunks<'a>(data: &'a [u8], info: &Info) -> impl Iterator<Item = Chunk<'a>> {
    let mut pos = info.chunks_start;
    std::iter::from_fn(move || {
        let header_end = pos.checked_add(8)?;
        let head = data.get(pos..header_end)?;
        let kind = u32::from_le_bytes(head[..4].try_into().ok()?);
        let size = i32::from_le_bytes(head[4..].try_into().ok()?);
        if size <= 0 {
            return None;
        }
        let end = header_end.checked_add(size as usize)?;
        let body = data.get(header_end..end)?;
        pos = end;
        let kind = match kind {
            0 => ChunkKind::Header,
            1 => ChunkKind::ReplayData,
            2 => ChunkKind::Checkpoint,
            3 => ChunkKind::Event,
            other => ChunkKind::Unknown(other),
        };
        Some(Chunk { kind, data: body })
    })
}

/// Decrypt (AES-256-ECB, PKCS7 padding) when the replay is encrypted.
pub fn decrypt(info: &Info, data: &[u8]) -> Result<Vec<u8>> {
    use aes::cipher::{BlockDecrypt, KeyInit, generic_array::GenericArray};
    if !info.encrypted {
        return Ok(data.to_vec());
    }
    if info.locked() {
        return Err(Error::Locked);
    }
    if !data.len().is_multiple_of(16) || info.key.len() != 32 {
        return Err(Error::Decrypt);
    }
    let cipher = aes::Aes256::new(GenericArray::from_slice(&info.key));
    let mut out = data.to_vec();
    for block in out.as_chunks_mut::<16>().0 {
        cipher.decrypt_block(GenericArray::from_mut_slice(block));
    }
    let pad = *out.last().ok_or(Error::Decrypt)? as usize;
    if pad == 0
        || pad > 16
        || out.len() < pad
        || !out[out.len() - pad..].iter().all(|&b| b as usize == pad)
    {
        return Err(Error::Decrypt);
    }
    out.truncate(out.len() - pad);
    Ok(out)
}

/// Oodle-decompress a `decompressed size: i32, compressed size: i32, data` block when the replay is compressed.
pub fn decompress(info: &Info, data: Vec<u8>) -> Result<Vec<u8>> {
    if !info.compressed {
        return Ok(data);
    }
    let mut r = Bytes::new(&data);
    let size = r.i32("compressed block")?;
    let packed = r.i32("compressed block")?;
    if size < 0 || packed < 0 || size > 512 * 1024 * 1024 {
        return Err(Error::Decompress(
            "invalid size or block exceeds the 512 MiB safety limit".into(),
        ));
    }
    let input = r.take(packed as usize, "compressed block")?;
    let mut out = Vec::new();
    out.try_reserve_exact(size as usize)
        .map_err(|_| Error::Decompress("could not allocate output block".into()))?;
    out.resize(size as usize, 0);
    let written = oozextract::Extractor::new()
        .read_from_slice(input, &mut out)
        .map_err(|e| Error::Decompress(format!("{e:?}")))?;
    if written != out.len() {
        return Err(Error::Decompress(format!(
            "{written} of {} bytes",
            out.len()
        )));
    }
    Ok(out)
}

/// A ReplayData chunk: its time range and the decrypted, decompressed demo frames.
pub struct ReplayData {
    pub start_ms: u32,
    pub end_ms: u32,
    pub frames: Vec<u8>,
}

pub fn replay_data(info: &Info, chunk: &Chunk<'_>) -> Result<ReplayData> {
    let mut r = Bytes::new(chunk.data);
    let (start_ms, end_ms, length) = if info.version >= 4 {
        (
            r.u32("data chunk")?,
            r.u32("data chunk")?,
            r.u32("data chunk")? as usize,
        )
    } else {
        (0, 0, chunk.data.len())
    };
    if info.version >= 6 {
        r.u32("data chunk")?; // size in memory
    }
    let payload = r.take(length, "data chunk")?;
    let frames = decompress(info, decrypt(info, payload)?)?;
    Ok(ReplayData {
        start_ms,
        end_ms,
        frames,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn replay(live: bool, key: &[u8], chunks_len: &[(u32, usize)]) -> Vec<u8> {
        let mut out = Vec::new();
        for v in [MAGIC, 7, 0, 40_000, 1, 1] {
            out.extend(v.to_le_bytes());
        }
        out.extend(2i32.to_le_bytes());
        out.extend(b"x\0");
        out.extend((live as u32).to_le_bytes());
        out.extend(0i64.to_le_bytes());
        out.extend(1u32.to_le_bytes());
        out.extend(1u32.to_le_bytes());
        out.extend((key.len() as u32).to_le_bytes());
        out.extend(key);
        for &(kind, len) in chunks_len {
            out.extend(kind.to_le_bytes());
            out.extend((len as i32).to_le_bytes());
            out.extend(std::iter::repeat_n(0u8, len));
        }
        out
    }

    #[test]
    fn header_live_flag_and_missing_key() {
        let data = replay(true, &[], &[(1, 24)]);
        let info = read_info(&data).unwrap();
        assert!(info.live && info.locked() && info.compressed && info.friendly_name == "x");
        assert_eq!(chunks(&data, &info).count(), 1);
        let finished = replay(false, &[7; 32], &[(1, 24), (3, 8)]);
        let info = read_info(&finished).unwrap();
        assert!(!info.locked() && info.key.len() == 32);
        assert_eq!(
            chunks(&finished, &info).map(|c| c.kind).collect::<Vec<_>>(),
            [ChunkKind::ReplayData, ChunkKind::Event]
        );
    }

    #[test]
    fn a_live_zero_key_placeholder_is_locked_even_with_32_key_bytes() {
        for live in [false, true] {
            let data = replay(live, &[0; 32], &[(1, 24)]);
            let info = read_info(&data).unwrap();
            assert!(info.locked());
            assert!(matches!(decrypt(&info, &[0; 16]), Err(Error::Locked)));
        }
        let data = replay(true, &[7; 32], &[]);
        assert!(read_info(&data).unwrap().locked());
    }

    #[test]
    fn a_chunk_still_being_written_is_not_returned() {
        let mut data = replay(true, &[], &[(1, 24), (1, 24)]);
        data.truncate(data.len() - 5);
        let info = read_info(&data).unwrap();
        assert_eq!(chunks(&data, &info).count(), 1);
        assert!(matches!(read_info(b"no"), Err(Error::Truncated(_))));
        assert!(matches!(read_info(&[0u8; 64]), Err(Error::NotAReplay)));
    }
}
