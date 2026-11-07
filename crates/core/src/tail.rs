//! Incremental replay-header/chunk indexing. Locked payloads are skipped, never guessed at.
use crate::container::{self, Info};
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
    path::Path,
};

#[derive(Debug, Clone, Copy, Default)]
pub struct Snapshot {
    pub live: bool,
    pub locked: bool,
    pub recorded_ms: u32,
    pub chunks: u64,
    pub offset: u64,
    pub bytes_read: u64,
}

#[derive(Default)]
pub struct Tail {
    header: Option<Info>,
    identity: Option<u128>,
    snapshot: Snapshot,
}

impl Tail {
    pub fn refresh(
        &mut self,
        path: &Path,
    ) -> Result<Snapshot, Box<dyn std::error::Error + Send + Sync>> {
        let mut file = File::open(path)?;
        let meta = file.metadata()?;
        let identity = identity(&meta);
        let size = meta.len();
        let mut head = vec![0u8; (size.min(4096)) as usize];
        file.read_exact(&mut head)?;
        let info = container::read_info(&head)?;
        let mut bytes_read = head.len() as u64;
        let reset = self.identity != Some(identity)
            || self.snapshot.offset > size
            || self.header.as_ref().is_none_or(|old| {
                old.chunks_start != info.chunks_start
                    || old.key != info.key
                    || old.timestamp != info.timestamp
                    || old.version != info.version
            });
        if reset {
            self.snapshot = Snapshot {
                offset: info.chunks_start as u64,
                ..Default::default()
            };
        }
        while self
            .snapshot
            .offset
            .checked_add(8)
            .is_some_and(|end| end <= size)
        {
            file.seek(SeekFrom::Start(self.snapshot.offset))?;
            let mut header = [0u8; 8];
            file.read_exact(&mut header)?;
            bytes_read += 8;
            let kind = u32::from_le_bytes(header[..4].try_into().unwrap());
            let length = i32::from_le_bytes(header[4..].try_into().unwrap());
            if length <= 0 {
                break;
            }
            let end = self
                .snapshot
                .offset
                .checked_add(8 + length as u64)
                .ok_or("Replay chunk offset overflow")?;
            if end > size {
                break;
            }
            if kind == 1 && info.version >= 4 && length >= 8 {
                let mut range = [0u8; 8];
                file.read_exact(&mut range)?;
                bytes_read += 8;
                self.snapshot.recorded_ms = self
                    .snapshot
                    .recorded_ms
                    .max(u32::from_le_bytes(range[4..].try_into().unwrap()));
            }
            self.snapshot.chunks += 1;
            self.snapshot.offset = end;
        }
        self.identity = Some(identity);
        self.snapshot.live = info.live;
        self.snapshot.locked = info.locked();
        self.snapshot.bytes_read = bytes_read;
        self.header = Some(info);
        Ok(self.snapshot)
    }
}

#[cfg(windows)]
fn identity(meta: &std::fs::Metadata) -> u128 {
    use std::os::windows::fs::MetadataExt;
    meta.creation_time() as u128
}
#[cfg(unix)]
fn identity(meta: &std::fs::Metadata) -> u128 {
    use std::os::unix::fs::MetadataExt;
    ((meta.dev() as u128) << 64) | meta.ino() as u128
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn header(key: &[u8]) -> Vec<u8> {
        let mut v = Vec::new();
        for n in [
            container::MAGIC,
            7,
            0,
            40000,
            1,
            1,
            0,
            u32::from(key.is_empty()),
        ] {
            v.extend(n.to_le_bytes());
        }
        v.extend(123i64.to_le_bytes());
        for n in [1, 1, key.len() as u32] {
            v.extend(n.to_le_bytes());
        }
        v.extend(key);
        v
    }
    fn chunk(end: u32) -> Vec<u8> {
        let mut v = Vec::new();
        for n in [1, 8192, end.saturating_sub(20000), end] {
            v.extend(n.to_le_bytes());
        }
        v.resize(8200, 0);
        v
    }
    #[test]
    fn growth_partial_chunk_and_unlock_reset_without_revisiting_old_chunks() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("growing.replay");
        let mut content = header(&[]);
        content.extend(chunk(20000));
        std::fs::write(&path, &content).unwrap();
        let mut tail = Tail::default();
        let first = tail.refresh(&path).unwrap();
        assert!(first.live && first.locked);
        assert_eq!((first.chunks, first.recorded_ms), (1, 20000));
        let next = tail.refresh(&path).unwrap();
        assert_eq!(next.chunks, 1);
        assert_eq!(next.bytes_read, 4096); // only the fixed header probe
        let next_chunk = chunk(40000);
        File::options()
            .append(true)
            .open(&path)
            .unwrap()
            .write_all(&next_chunk[..40])
            .unwrap();
        assert_eq!(tail.refresh(&path).unwrap().chunks, 1);
        File::options()
            .append(true)
            .open(&path)
            .unwrap()
            .write_all(&next_chunk[40..])
            .unwrap();
        let grown = tail.refresh(&path).unwrap();
        assert_eq!((grown.chunks, grown.recorded_ms), (2, 40000));
        assert_eq!(grown.bytes_read, 4112);
        let mut final_file = header(&[7; 32]);
        final_file.extend(chunk(20000));
        final_file.extend(chunk(40000));
        std::fs::write(&path, final_file).unwrap();
        let finished = tail.refresh(&path).unwrap();
        assert!(!finished.live && !finished.locked);
        assert_eq!((finished.chunks, finished.recorded_ms), (2, 40000));
    }
}
