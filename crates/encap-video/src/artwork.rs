//! Conservative static-artwork detection; unknown containers retain PerFrame.
//! Dimensions, decoding, corruption, and resource limits remain Core's job.
use crate::{lifecycle, CancellationToken};
use encap_core::{EncapError, Result};
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
    path::Path,
};

pub(crate) fn is_static(path: &Path, token: &CancellationToken) -> Result<bool> {
    lifecycle::check(token)?;
    let mut file = File::open(path).map_err(|source| EncapError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    let mut magic = [0; 8];
    if file.read_exact(&mut magic).is_err() {
        return Ok(false);
    }
    let result = if magic == *b"\x89PNG\r\n\x1a\n" {
        static_png(&mut file, token)
    } else if magic[..2] == [0xff, 0xd8] {
        file.rewind().and_then(|_| static_jpeg(&mut file, token))
    } else {
        // GIF, animated WebP, APNG, and all unrecognized formats retain the
        // original decoder behavior. Extensions never establish staticness.
        Ok(false)
    };
    lifecycle::check(token)?;
    // A malformed container is handed to Core for the normal media diagnostic.
    Ok(result.unwrap_or(false))
}

fn static_png(file: &mut File, token: &CancellationToken) -> std::io::Result<bool> {
    let length = file.metadata()?.len();
    let mut image_data = false;
    for index in 0..4096 {
        if token.is_cancelled() {
            return Ok(false);
        }
        let mut chunk = [0; 8];
        file.read_exact(&mut chunk)?;
        let count = u32::from_be_bytes(chunk[..4].try_into().unwrap()) as u64;
        let kind = &chunk[4..];
        if index == 0 && (kind != b"IHDR" || count != 13) {
            return Ok(false);
        }
        if [b"acTL", b"fcTL", b"fdAT"].contains(&kind.try_into().unwrap()) {
            return Ok(false);
        }
        let next = file.stream_position()?.checked_add(count + 4);
        let Some(next) = next.filter(|offset| *offset <= length) else {
            return Ok(false);
        };
        file.seek(SeekFrom::Start(next))?;
        image_data |= kind == b"IDAT";
        if kind == b"IEND" {
            return Ok(count == 0 && image_data && next == length);
        }
    }
    Ok(false)
}

fn static_jpeg(file: &mut File, token: &CancellationToken) -> std::io::Result<bool> {
    // Scan at most 64 MiB. More complex JPEG/MJPEG and embedded thumbnail
    // streams are conservatively PerFrame instead of risking frozen animation.
    if file.metadata()?.len() > 64 * 1024 * 1024 {
        return Ok(false);
    }
    let mut buffer = [0; 16 * 1024];
    let mut previous = 0;
    let mut last = [0; 2];
    let mut starts = 0;
    loop {
        if token.is_cancelled() {
            return Ok(false);
        }
        let count = file.read(&mut buffer)?;
        if count == 0 {
            return Ok(starts == 1 && last == [0xff, 0xd9]);
        }
        for &byte in &buffer[..count] {
            starts += usize::from(previous == 0xff && byte == 0xd8);
            if starts > 1 {
                return Ok(false);
            }
            last = [previous, byte];
            previous = byte;
        }
    }
}
