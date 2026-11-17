#![allow(dead_code)]
use std::path::Path;
pub const OPAQUE_PNG: &[u8] = &[
    137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 1, 0, 0, 0, 1, 8, 2, 0,
    0, 0, 144, 119, 83, 222, 0, 0, 0, 32, 116, 69, 88, 116, 67, 111, 109, 109, 101, 110, 116, 0,
    112, 114, 105, 118, 97, 116, 101, 45, 97, 114, 116, 119, 111, 114, 107, 45, 109, 101, 116, 97,
    100, 97, 116, 97, 252, 71, 246, 62, 0, 0, 0, 12, 73, 68, 65, 84, 120, 156, 99, 248, 207, 192,
    0, 0, 3, 1, 1, 0, 201, 254, 146, 239, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
];

pub fn write_wav(path: &Path, seconds: u32) {
    let bytes = seconds * 48_000 * 2 * 2;
    let mut wav = Vec::with_capacity(bytes as usize + 44);
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&(36 + bytes).to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    wav.extend_from_slice(&16u32.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes());
    wav.extend_from_slice(&2u16.to_le_bytes());
    wav.extend_from_slice(&48_000u32.to_le_bytes());
    wav.extend_from_slice(&192_000u32.to_le_bytes());
    wav.extend_from_slice(&4u16.to_le_bytes());
    wav.extend_from_slice(&16u16.to_le_bytes());
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&bytes.to_le_bytes());
    wav.resize(bytes as usize + 44, 0);
    std::fs::write(path, wav).unwrap();
}
