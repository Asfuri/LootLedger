//! Readers with the exact semantics of the vendored C# reader (Unreal.Core BitReader and BinaryReader).
//!
//! Parity matters more than tidiness here: a bit reader that runs out sets `error` and returns zero, some
//! reads (ReadByte) are unchecked and may read past the logical end into the bytes that follow, and reads
//! past the backing array raise an exception (`Exc`) that the parser catches at the same places the C# code
//! catches it. `buf` is the backing array from the reader's start (it may extend past `len`, like a C#
//! array-backed Memory slice); `len` is the logical Buffer.Length.

// The index loops mirror the C# reader line by line, including the reads that raise.
#![allow(clippy::needless_range_loop, clippy::explicit_counter_loop)]

use std::borrow::Cow;

/// A C# exception: unwinds to the nearest catch, exactly where the old reader would.
#[derive(Debug, Clone, PartialEq)]
pub struct Exc(pub String);
pub type R<T> = Result<T, Exc>;

pub fn exc<T>(what: &str) -> R<T> {
    Err(Exc(what.to_owned()))
}

fn out_of_range<T>() -> R<T> {
    exc("IndexOutOfRangeException: Index was outside the bounds of the array.")
}

/// Engine, network and header-flag versions every reader carries.
#[derive(Debug, Clone, Copy, Default)]
pub struct Ver {
    pub engine: u32,
    pub network: u32,
    pub flags: u32,
}

impl Ver {
    pub fn streaming_fixes(&self) -> bool {
        self.flags & 2 != 0
    }
    pub fn game_specific_frame_data(&self) -> bool {
        self.flags & 8 != 0
    }
}

/// Hardcoded FName lookup (UnrealNames enum, or the number when it has no name).
pub fn unreal_name(index: u32) -> String {
    match crate::tables::UNREAL_NAMES.binary_search_by_key(&index, |(i, _)| *i) {
        Ok(at) => crate::tables::UNREAL_NAMES[at].1.to_owned(),
        Err(_) => index.to_string(),
    }
}

/// Unreal FString bytes to text: UTF-8 or UTF-16LE without the terminator, spaces trimmed (C# Trim(' ')).
fn decode_fstring(bytes: &[u8], unicode: bool) -> String {
    let text = if unicode {
        let bytes =
            if bytes.len() >= 2 && bytes[bytes.len() - 1] == 0 && bytes[bytes.len() - 2] == 0 {
                &bytes[..bytes.len() - 2]
            } else {
                bytes
            };
        let units: Vec<u16> = bytes
            .chunks_exact(2)
            .map(|c| u16::from_le_bytes([c[0], c[1]]))
            .collect();
        String::from_utf16_lossy(&units)
    } else {
        let bytes = if bytes.last() == Some(&0) {
            &bytes[..bytes.len() - 1]
        } else {
            bytes
        };
        String::from_utf8_lossy(bytes).into_owned()
    };
    text.trim_matches(' ').to_owned()
}

pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02X}")).collect()
}

pub struct BitReader<'a> {
    buf: Cow<'a, [u8]>,
    len: usize,
    pub pos: usize,
    pub last: usize,
    pub error: bool,
    pub temp: [usize; 4],
    pub ver: Ver,
}

pub const END_BUNCH: usize = 0;
pub const END_CONTENT: usize = 1;
pub const END_FIELD: usize = 2;
pub const END_ARRAY: usize = 3;

impl<'a> BitReader<'a> {
    /// A reader over `len` bytes at the start of `buf`, of which `bits` are readable.
    pub fn borrowed(buf: &'a [u8], len: usize, bits: usize, ver: Ver) -> Self {
        BitReader {
            buf: Cow::Borrowed(buf),
            len,
            pos: 0,
            last: bits,
            error: false,
            temp: [0; 4],
            ver,
        }
    }
    pub fn owned(bytes: Vec<u8>, bits: usize, ver: Ver) -> BitReader<'static> {
        let len = bytes.len();
        BitReader {
            buf: Cow::Owned(bytes),
            len,
            pos: 0,
            last: bits,
            error: false,
            temp: [0; 4],
            ver,
        }
    }

    pub fn at_end(&self) -> bool {
        self.pos >= self.last
    }
    pub fn can_read(&self, bits: i64) -> bool {
        self.pos as i64 + bits <= self.last as i64
    }
    pub fn bits_left(&self) -> i64 {
        self.last as i64 - self.pos as i64
    }
    /// Span access (Buffer.Span[i]): bounded by the logical length.
    fn span(&self, i: usize) -> R<u8> {
        if i < self.len {
            Ok(self.buf[i])
        } else {
            out_of_range()
        }
    }
    /// Array access (_byteArray[offset + i]): bounded only by the backing array.
    fn arr(&self, i: usize) -> R<u8> {
        self.buf.get(i).copied().map_or_else(out_of_range, Ok)
    }

    pub fn read_bit(&mut self) -> bool {
        if self.pos >= self.last || self.error {
            self.error = true;
            return false;
        }
        let bit = self
            .buf
            .get(self.pos >> 3)
            .is_some_and(|b| b & (1 << (self.pos & 7)) != 0);
        self.pos += 1;
        bit
    }

    pub fn read_bits_to_int(&mut self, count: i64) -> i32 {
        if !self.can_read(count) || count < 0 {
            self.error = true;
            return 0;
        }
        if count == 0 {
            return 0;
        }
        let cur = self.pos >> 3;
        if cur + 8 <= self.len {
            let val = u64::from_le_bytes(self.buf[cur..cur + 8].try_into().expect("8 bytes"));
            let mask = if count >= 64 {
                !0u64
            } else {
                (1u64 << count) - 1
            };
            let res = ((val >> (self.pos & 7)) & mask) as i32;
            self.pos += count as usize;
            return res;
        }
        let mut result = 0i32;
        for i in 0..count as u32 {
            if self.error {
                return 0;
            }
            if self.read_bit() {
                result |= 1i32.wrapping_shl(i);
            }
        }
        result
    }

    pub fn read_bits_to_long(&mut self, count: i64) -> u64 {
        if !self.can_read(count) || count < 0 {
            self.error = true;
            return 0;
        }
        if count == 0 {
            return 0;
        }
        let cur = self.pos >> 3;
        if cur + 8 <= self.len {
            let val = u64::from_le_bytes(self.buf[cur..cur + 8].try_into().expect("8 bytes"));
            let mask = if count >= 64 {
                !0u64
            } else {
                (1u64 << count) - 1
            };
            let res = (val >> (self.pos & 7)) & mask;
            self.pos += count as usize;
            return res;
        }
        let mut result = 0u64;
        for i in 0..count as u32 {
            if self.read_bit() {
                result |= 1u64.wrapping_shl(i);
            }
        }
        result
    }

    /// ReadBits(Span destination, bitCount).
    pub fn read_bits_into(&mut self, dest: &mut [u8], count: i64) -> R<()> {
        if !self.can_read(count) || count < 0 {
            self.error = true;
            return Ok(());
        }
        let count = count as usize;
        let used = self.pos & 7;
        let byte_count = count / 8;
        let extra = count % 8;
        let cur = self.pos >> 3;
        if used == 0 {
            for i in 0..byte_count {
                dest[i] = self.span(cur + i)?;
            }
            self.pos += byte_count * 8;
            if extra > 0 {
                dest[byte_count] = self.span(self.pos >> 3)? & ((1u8 << extra) - 1);
                self.pos += extra;
            }
            return Ok(());
        }
        let needed = count.div_ceil(8);
        dest[..needed].fill(0);
        let left = 8 - used;
        let shift_mask = (1u8 << used) - 1;
        for i in 0..byte_count {
            dest[i] =
                (self.span(cur + i)? >> used) | ((self.span(cur + i + 1)? & shift_mask) << left);
        }
        self.pos += byte_count * 8;
        for i in 0..extra {
            let bit = self.span(self.pos >> 3)? & (1 << (self.pos & 7)) != 0;
            self.pos += 1;
            if bit {
                dest[needed - 1] |= 1 << i;
            }
        }
        Ok(())
    }

    pub fn read_bits(&mut self, count: i64) -> R<Vec<u8>> {
        if !self.can_read(count) || count < 0 {
            self.error = true;
            return Ok(Vec::new());
        }
        let mut out = vec![0u8; (count as usize).div_ceil(8)];
        self.read_bits_into(&mut out, count)?;
        Ok(out)
    }

    /// Unchecked, like the C# ReadByte: it never sets `error` and may read past the logical end.
    pub fn read_byte(&mut self) -> R<u8> {
        let used = self.pos & 7;
        let cur = self.pos >> 3;
        self.pos += 8;
        if used == 0 {
            return self.arr(cur);
        }
        Ok((self.arr(cur)? >> used) | ((self.arr(cur + 1)? & ((1u8 << used) - 1)) << (8 - used)))
    }

    fn read_bytes_into(&mut self, dest: &mut [u8]) -> R<()> {
        let n = dest.len();
        if !self.can_read(n as i64 * 8) {
            self.error = true;
            dest.fill(0);
            return Ok(());
        }
        let used = self.pos & 7;
        let cur = self.pos >> 3;
        if used == 0 {
            for (i, d) in dest.iter_mut().enumerate() {
                *d = self.span(cur + i)?;
            }
        } else {
            let mask = (1u8 << used) - 1;
            for (i, d) in dest.iter_mut().enumerate() {
                *d = (self.span(cur + i)? >> used)
                    | ((self.span(cur + 1 + i)? & mask) << (8 - used));
            }
        }
        self.pos += n * 8;
        Ok(())
    }

    pub fn read_bytes(&mut self, n: i64) -> R<Vec<u8>> {
        if n < 0 || !self.can_read(n * 8) {
            self.error = true;
            return Ok(Vec::new());
        }
        let mut out = vec![0u8; n as usize];
        self.read_bytes_into(&mut out)?;
        Ok(out)
    }

    fn fixed<const N: usize>(&mut self) -> R<[u8; N]> {
        let mut out = [0u8; N];
        if !self.can_read(N as i64 * 8) {
            self.error = true;
            return Ok(out);
        }
        self.read_bytes_into(&mut out)?;
        Ok(out)
    }
    pub fn read_u16(&mut self) -> R<u16> {
        Ok(u16::from_le_bytes(self.fixed()?))
    }
    pub fn read_i16(&mut self) -> R<i16> {
        Ok(i16::from_le_bytes(self.fixed()?))
    }
    pub fn read_u32(&mut self) -> R<u32> {
        Ok(u32::from_le_bytes(self.fixed()?))
    }
    pub fn read_i32(&mut self) -> R<i32> {
        Ok(i32::from_le_bytes(self.fixed()?))
    }
    pub fn read_u64(&mut self) -> R<u64> {
        Ok(u64::from_le_bytes(self.fixed()?))
    }
    pub fn read_f32(&mut self) -> R<f32> {
        Ok(f32::from_le_bytes(self.fixed()?))
    }
    pub fn read_f64(&mut self) -> R<f64> {
        Ok(f64::from_le_bytes(self.fixed()?))
    }

    pub fn read_int_packed(&mut self) -> R<u32> {
        let mut value = 0u32;
        if self.pos & 7 == 0 {
            let mut src = self.pos >> 3;
            for it in 0..5 {
                if !self.can_read(8) {
                    self.error = true;
                    break;
                }
                self.pos += 8;
                let b = self.span(src)?;
                src += 1;
                value |= ((b >> 1) as u32).wrapping_shl(7 * it);
                if b & 1 == 0 {
                    break;
                }
            }
            return Ok(value);
        }
        let used = (self.pos & 7) as u32;
        let left = 8 - used;
        let mask0 = ((1u32 << left) - 1) as u8;
        let mask1 = ((1u32 << used) - 1) as u8;
        let mut cur = self.pos >> 3;
        let mut next = cur + 1;
        for it in 0..5 {
            if !self.can_read(8) {
                self.error = true;
                break;
            }
            if next >= self.len {
                next = cur;
            }
            self.pos += 8;
            let b =
                ((self.span(cur)? >> used) & mask0) | ((self.span(next)? & mask1) << (left & 7));
            value |= ((b >> 1) as u32).wrapping_shl(7 * it);
            cur += 1;
            next += 1;
            if b & 1 == 0 {
                break;
            }
        }
        Ok(value)
    }

    pub fn read_serialized_int(&mut self, max: u32) -> u32 {
        let mut value = 0u64;
        let mut mask = 1u64;
        while value + mask < max as u64 {
            if self.read_bit() {
                value |= mask;
            }
            mask *= 2;
        }
        value as u32
    }

    pub fn read_fstring(&mut self) -> R<String> {
        let length = self.read_i32()?;
        if length == 0 {
            return Ok(String::new());
        }
        let unicode = length < 0;
        let n = if unicode {
            length.wrapping_mul(-2)
        } else {
            length
        };
        let bytes = self.read_bytes(n as i64)?;
        Ok(decode_fstring(&bytes, unicode))
    }

    pub fn read_fname(&mut self) -> R<String> {
        if self.read_bit() {
            let index = if self.ver.engine < 6 {
                self.read_u32()?
            } else {
                self.read_int_packed()?
            };
            return Ok(unreal_name(index));
        }
        let text = self.read_fstring()?;
        self.read_i32()?;
        Ok(text)
    }

    pub fn read_fvector(&mut self) -> R<()> {
        if self.ver.engine >= 23 {
            for _ in 0..3 {
                self.read_f64()?;
            }
        } else {
            for _ in 0..3 {
                self.read_f32()?;
            }
        }
        Ok(())
    }

    pub fn read_packed_vector(&mut self, scale: i32, max_bits: u32) -> R<()> {
        let _ = scale;
        if self.ver.engine >= 23 && self.ver.engine != 26 {
            let info = self.read_serialized_int(1 << 7);
            let bits = (info & 63) as i64;
            if bits > 0 {
                for _ in 0..3 {
                    self.read_bits_to_long(bits);
                }
            } else if info >> 6 == 0 {
                for _ in 0..3 {
                    self.read_f32()?;
                }
            } else {
                for _ in 0..3 {
                    self.read_f64()?;
                }
            }
            return Ok(());
        }
        let bits = self.read_serialized_int(max_bits);
        if self.error {
            return Ok(());
        }
        let max = 1u32.wrapping_shl(bits + 2);
        for _ in 0..3 {
            self.read_serialized_int(max);
        }
        Ok(())
    }

    pub fn read_rotation_short(&mut self) -> R<()> {
        for _ in 0..3 {
            if self.read_bit() {
                self.read_u16()?;
            }
        }
        Ok(())
    }

    /// Seek(offset, Current), with the C# bounds check against the buffer (not the logical end).
    pub fn skip_bits(&mut self, offset: i64) {
        let len = self.len as i64;
        if offset < 0
            || offset >> 3 > len
            || (offset >> 3 == len && offset & 7 > 0)
            || offset + self.pos as i64 > len * 8
        {
            self.error = true;
            return;
        }
        self.pos += offset as usize;
    }

    pub fn set_temp_end(&mut self, size: i64, index: usize) {
        let end = self.pos as i64 + size;
        if end > self.last as i64 {
            self.error = true;
            return;
        }
        self.temp[index] = self.last;
        self.last = end as usize;
    }

    pub fn restore_temp_end(&mut self, index: usize) {
        self.pos = self.last;
        self.last = self.temp[index];
        self.error = false;
    }

    /// AppendDataFromChecked: whole bytes are appended after the buffer, the readable end grows by `bits`.
    pub fn append(&mut self, data: &[u8], bits: i64) {
        self.last = (self.last as i64 + bits) as usize;
        let mut combined = self.buf[..self.len].to_vec();
        combined.extend_from_slice(data);
        self.len = combined.len();
        self.buf = Cow::Owned(combined);
    }

    /// FillBitsFrom: copy `count` bits of `src` into this reader's reusable buffer (which keeps stale bytes
    /// past the copied ones, as the C# buffer does).
    pub fn fill_bits_from(&mut self, src: &mut BitReader<'_>, count: i64) -> R<()> {
        self.pos = 0;
        if count <= 0 || !src.can_read(count) {
            self.error = count < 0 || src.error;
            self.len = 0;
            self.last = 0;
            self.buf = Cow::Owned(Vec::new());
            return Ok(());
        }
        let required = (count as usize).div_ceil(8);
        let mut scratch = std::mem::take(&mut self.buf).into_owned();
        if scratch.len() < required {
            scratch = vec![0u8; (required * 2).max(2048)];
        }
        let result = src.read_bits_into(&mut scratch[..required], count);
        self.buf = Cow::Owned(scratch);
        self.len = required;
        self.last = count as usize;
        self.error = src.error;
        result
    }
}

/// The byte-level reader (C# BinaryReader): every read past the end is an exception.
pub struct ByteReader<'a> {
    pub data: &'a [u8],
    pub pos: usize,
    pub ver: Ver,
}

impl<'a> ByteReader<'a> {
    pub fn new(data: &'a [u8], ver: Ver) -> Self {
        ByteReader { data, pos: 0, ver }
    }
    pub fn at_end(&self) -> bool {
        self.pos >= self.data.len()
    }
    pub fn take(&mut self, n: i64) -> R<&'a [u8]> {
        if n < 0 {
            return exc(
                "ArgumentOutOfRangeException: Specified argument was out of the range of valid values.",
            );
        }
        let end = self
            .pos
            .checked_add(n as usize)
            .filter(|&e| e <= self.data.len());
        let Some(end) = end else {
            return exc(
                "ArgumentOutOfRangeException: Specified argument was out of the range of valid values.",
            );
        };
        let out = &self.data[self.pos..end];
        self.pos = end;
        Ok(out)
    }
    /// The position of the next byte in the underlying data (for readers that view the bytes that follow).
    pub fn skip(&mut self, n: i64) {
        self.pos = (self.pos as i64 + n).max(0) as usize;
    }
    pub fn u8(&mut self) -> R<u8> {
        match self.data.get(self.pos) {
            Some(&b) => {
                self.pos += 1;
                Ok(b)
            }
            None => out_of_range(),
        }
    }
    pub fn bool(&mut self) -> R<bool> {
        Ok(self.u8()? != 0)
    }
    pub fn u16(&mut self) -> R<u16> {
        Ok(u16::from_le_bytes(
            self.take(2)?.try_into().expect("2 bytes"),
        ))
    }
    pub fn u32(&mut self) -> R<u32> {
        Ok(u32::from_le_bytes(
            self.take(4)?.try_into().expect("4 bytes"),
        ))
    }
    pub fn i32(&mut self) -> R<i32> {
        Ok(self.u32()? as i32)
    }
    pub fn u64(&mut self) -> R<u64> {
        Ok(u64::from_le_bytes(
            self.take(8)?.try_into().expect("8 bytes"),
        ))
    }
    pub fn i64(&mut self) -> R<i64> {
        Ok(self.u64()? as i64)
    }
    pub fn f32(&mut self) -> R<f32> {
        Ok(f32::from_le_bytes(
            self.take(4)?.try_into().expect("4 bytes"),
        ))
    }
    pub fn int_packed(&mut self) -> R<u32> {
        let mut value = 0u32;
        let mut count = 0u32;
        loop {
            let b = self.u8()?;
            value = value.wrapping_add(((b >> 1) as u32).wrapping_shl(7 * count));
            count += 1;
            if b & 1 == 0 {
                return Ok(value);
            }
        }
    }
    pub fn fstring(&mut self) -> R<String> {
        let length = self.i32()?;
        if length == 0 {
            return Ok(String::new());
        }
        let unicode = length < 0;
        let n = if unicode {
            length.wrapping_mul(-2)
        } else {
            length
        };
        let bytes = self.take(n as i64)?;
        Ok(decode_fstring(bytes, unicode))
    }
    /// The UTF-16 code units of an FString (C# string indexing works on these).
    pub fn fstring_units(&mut self) -> R<Vec<u16>> {
        Ok(self.fstring()?.encode_utf16().collect())
    }
    pub fn fname(&mut self) -> R<String> {
        if self.bool()? {
            let index = if self.ver.engine < 6 {
                self.u32()?
            } else {
                self.int_packed()?
            };
            return Ok(unreal_name(index));
        }
        let text = self.fstring()?;
        self.i32()?;
        Ok(text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn int_packed_matches_unreal_varint_aligned_and_unaligned() {
        // 300 = 0b1_0010_1100 -> bytes (44<<1)|1, (2<<1)
        let data = [0x59u8, 0x04];
        let mut r = BitReader::borrowed(&data, 2, 16, Ver::default());
        assert_eq!(r.read_int_packed().unwrap(), 300);
        // Shift the same bytes by one bit.
        let shifted = [0xB2u8, 0x08, 0x00];
        let mut r = BitReader::borrowed(&shifted, 3, 24, Ver::default());
        assert!(!r.read_bit());
        assert_eq!(r.read_int_packed().unwrap(), 300);
    }

    #[test]
    fn running_out_sets_error_and_temp_end_restores() {
        let data = [0xFFu8; 4];
        let mut r = BitReader::borrowed(&data, 4, 32, Ver::default());
        r.set_temp_end(4, END_BUNCH);
        assert_eq!(r.read_bits_to_int(4), 15);
        assert!(!r.read_bit() && r.error);
        r.restore_temp_end(END_BUNCH);
        assert!(!r.error && r.pos == 4 && r.last == 32);
        assert_eq!(r.read_serialized_int(16), 15);
    }

    #[test]
    fn read_byte_is_unchecked_but_the_array_end_raises() {
        let data = [0xAAu8, 0x55];
        let mut r = BitReader::borrowed(&data, 1, 3, Ver::default());
        assert_eq!(r.read_byte().unwrap(), 0xAA); // past the 3 readable bits, no error
        assert!(!r.error && r.at_end());
        assert_eq!(r.read_byte().unwrap(), 0x55); // the next byte of the backing array
        assert!(r.read_byte().is_err());
    }

    #[test]
    fn fstrings_trim_and_decode_utf16() {
        let mut data = Vec::new();
        data.extend((-3i32).to_le_bytes());
        data.extend([b'h', 0, b'i', 0, 0, 0]);
        data.extend(4i32.to_le_bytes());
        data.extend(b" a \0");
        let mut r = ByteReader::new(&data, Ver::default());
        assert_eq!(r.fstring().unwrap(), "hi");
        assert_eq!(r.fstring().unwrap(), "a");
        assert!(r.u8().is_err());
    }
}
