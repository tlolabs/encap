//! Bounded, approximate first-channel thumbnails, independent of file duration.
use crate::{EncapError, Result};
use serde::Serialize;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

const BINS: usize = 64;
const WINDOW_BYTES: usize = 32 * 1024;
const WINDOW_FRAMES: usize = 256;

#[derive(Debug, Serialize)]
pub struct WaveformPreview {
    pub channel: u8,
    pub peaks: Vec<f32>,
}

#[derive(Clone, Copy)]
struct Format {
    stride: usize,
    bytes: usize,
    float: bool,
    little: bool,
    unsigned: bool,
    frames: Option<u64>,
}

fn invalid() -> std::io::Error {
    std::io::Error::new(
        std::io::ErrorKind::InvalidData,
        "Unsupported or truncated waveform data",
    )
}

/// Reads at most 2 MiB of sample windows, plus small chunk headers. Never decodes
/// the whole recording, downmixes channels, or changes the project/source file.
pub fn waveform_preview(path: &Path) -> Result<WaveformPreview> {
    let read = || -> std::io::Result<WaveformPreview> {
        let mut file = File::open(path)?;
        let length = file.metadata()?.len();
        preview(&mut file, length)
    };
    read().map_err(|source| EncapError::Read {
        path: path.to_path_buf(),
        source,
    })
}

fn preview(reader: &mut (impl Read + Seek), length: u64) -> std::io::Result<WaveformPreview> {
    let mut header = [0; 12];
    reader.read_exact(&mut header)?;
    let wave = &header[..4] == b"RIFF" && &header[8..] == b"WAVE";
    let aiff = &header[..4] == b"FORM" && matches!(&header[8..], b"AIFF" | b"AIFC");
    if !wave && !aiff {
        return Err(invalid());
    }
    let mut format = None;
    let mut samples = None;
    // Metadata is skipped by seeking, with a cap on pathological chunk counts.
    for _ in 0..4096 {
        if reader.stream_position()?.saturating_add(8) > length {
            break;
        }
        let mut chunk = [0; 8];
        reader.read_exact(&mut chunk)?;
        let size = if wave {
            u32::from_le_bytes(chunk[4..].try_into().unwrap())
        } else {
            u32::from_be_bytes(chunk[4..].try_into().unwrap())
        } as u64;
        let start = reader.stream_position()?;
        let end = start
            .checked_add(size)
            .filter(|end| *end <= length)
            .ok_or_else(invalid)?;
        if wave && &chunk[..4] == b"fmt " {
            if size < 16 {
                return Err(invalid());
            }
            let mut raw = [0; 40];
            reader.read_exact(&mut raw[..size.min(40) as usize])?;
            let mut encoding = u16::from_le_bytes(raw[..2].try_into().unwrap());
            if encoding == 0xfffe {
                if size < 40
                    || u16::from_le_bytes(raw[16..18].try_into().unwrap()) < 22
                    || raw[26..40] != [0, 0, 0, 0, 16, 0, 128, 0, 0, 170, 0, 56, 155, 113]
                {
                    return Err(invalid());
                }
                encoding = u16::from_le_bytes(raw[24..26].try_into().unwrap());
            }
            let channels = u16::from_le_bytes(raw[2..4].try_into().unwrap()) as usize;
            let bits = u16::from_le_bytes(raw[14..16].try_into().unwrap()) as usize;
            if channels == 0
                || !matches!(encoding, 1 | 3)
                || !matches!(bits, 8 | 16 | 24 | 32 | 64)
                || (encoding == 3 && !matches!(bits, 32 | 64))
                || (encoding == 1 && bits == 64)
            {
                return Err(invalid());
            }
            let stride = u16::from_le_bytes(raw[12..14].try_into().unwrap()) as usize;
            if stride < channels * (bits / 8) {
                return Err(invalid());
            }
            format = Some(Format {
                stride,
                bytes: bits / 8,
                float: encoding == 3,
                little: true,
                unsigned: encoding == 1 && bits == 8,
                frames: None,
            });
        } else if aiff && &chunk[..4] == b"COMM" {
            if size < 18 {
                return Err(invalid());
            }
            let mut raw = [0; 22];
            reader.read_exact(&mut raw[..size.min(22) as usize])?;
            let channels = u16::from_be_bytes(raw[..2].try_into().unwrap()) as usize;
            let bits = u16::from_be_bytes(raw[6..8].try_into().unwrap()) as usize;
            let encoding = if &header[8..] == b"AIFC" {
                if size < 22 {
                    return Err(invalid());
                }
                &raw[18..22]
            } else {
                b"NONE"
            };
            let float = matches!(encoding, b"fl32" | b"FL32" | b"fl64" | b"FL64");
            if channels == 0
                || !matches!(bits, 8 | 16 | 24 | 32 | 64)
                || !matches!(
                    encoding,
                    b"NONE" | b"twos" | b"sowt" | b"fl32" | b"FL32" | b"fl64" | b"FL64"
                )
                || (float && !matches!(bits, 32 | 64))
                || (!float && bits == 64)
            {
                return Err(invalid());
            }
            format = Some(Format {
                stride: channels * (bits / 8),
                bytes: bits / 8,
                float,
                little: encoding == b"sowt",
                unsigned: false,
                frames: Some(u32::from_be_bytes(raw[2..6].try_into().unwrap()) as u64),
            });
        } else if wave && &chunk[..4] == b"data" {
            samples = Some((start, size));
        } else if aiff && &chunk[..4] == b"SSND" {
            if size < 8 {
                return Err(invalid());
            }
            let mut sound = [0; 8];
            reader.read_exact(&mut sound)?;
            let offset = u32::from_be_bytes(sound[..4].try_into().unwrap()) as u64;
            if offset > size - 8 {
                return Err(invalid());
            }
            samples = Some((start + 8 + offset, size - 8 - offset));
        }
        if format.is_some() && samples.is_some() {
            break;
        }
        reader.seek(SeekFrom::Start(end + (size & 1)))?;
    }
    let format = format.ok_or_else(invalid)?;
    let (offset, size) = samples.ok_or_else(invalid)?;
    if format.stride == 0 || format.stride > WINDOW_BYTES {
        return Err(invalid());
    }
    let available_frames = size / format.stride as u64;
    let frames = format.frames.unwrap_or(available_frames);
    if frames > available_frames {
        return Err(invalid());
    }
    let mut peaks = vec![0_f32; BINS];
    let mut buffer = vec![0; WINDOW_BYTES];
    for (bin, peak) in peaks.iter_mut().enumerate() {
        let first = frames * bin as u64 / BINS as u64;
        let end = frames * (bin + 1) as u64 / BINS as u64;
        let count = (end - first)
            .min(WINDOW_FRAMES as u64)
            .min((WINDOW_BYTES / format.stride) as u64) as usize;
        if count == 0 {
            continue;
        }
        let start = first + (end - first - count as u64) / 2;
        reader.seek(SeekFrom::Start(offset + start * format.stride as u64))?;
        let window = &mut buffer[..count * format.stride];
        reader.read_exact(window)?;
        for frame in window.chunks_exact(format.stride) {
            *peak = peak.max(sample(&frame[..format.bytes], format).abs());
        }
    }
    // Normalize the silhouette per recording. Preserve true silence and leave a
    // floor in the renderer rather than inventing signal in silent bins.
    let maximum = peaks.iter().copied().fold(0_f32, f32::max);
    if maximum > 0.0 {
        for peak in &mut peaks {
            *peak = (*peak / maximum).sqrt();
        }
    }
    Ok(WaveformPreview { channel: 1, peaks })
}

fn sample(bytes: &[u8], format: Format) -> f32 {
    let mut raw = [0_u8; 8];
    if format.little {
        raw[..bytes.len()].copy_from_slice(bytes);
    } else {
        for (index, byte) in bytes.iter().rev().enumerate() {
            raw[index] = *byte;
        }
    }
    let value = if format.float {
        if bytes.len() == 4 {
            f32::from_le_bytes(raw[..4].try_into().unwrap()) as f64
        } else {
            f64::from_le_bytes(raw)
        }
    } else if format.unsigned {
        (raw[0] as f64 - 128.0) / 128.0
    } else {
        let shift = 64 - bytes.len() * 8;
        let signed = ((u64::from_le_bytes(raw) << shift) as i64) >> shift;
        signed as f64 / (1_u64 << (bytes.len() * 8 - 1)) as f64
    };
    if value.is_finite() {
        value.abs().min(1.0) as f32
    } else {
        0.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn wave(channels: u16, first: i16, other: i16) -> Vec<u8> {
        let mut audio = Vec::new();
        for _ in 0..1024 {
            for channel in 0..channels {
                audio.extend_from_slice(&(if channel == 0 { first } else { other }).to_le_bytes());
            }
        }
        let mut result = b"RIFF".to_vec();
        result.extend_from_slice(&(36 + audio.len() as u32).to_le_bytes());
        result.extend_from_slice(b"WAVEfmt \x10\0\0\0\x01\0");
        result.extend_from_slice(&channels.to_le_bytes());
        result.extend_from_slice(&48000_u32.to_le_bytes());
        result.extend_from_slice(&(48000_u32 * channels as u32 * 2).to_le_bytes());
        result.extend_from_slice(&(channels * 2).to_le_bytes());
        result.extend_from_slice(&16_u16.to_le_bytes());
        result.extend_from_slice(b"data");
        result.extend_from_slice(&(audio.len() as u32).to_le_bytes());
        result.extend(audio);
        result
    }
    fn read(bytes: Vec<u8>) -> WaveformPreview {
        let len = bytes.len() as u64;
        preview(&mut Cursor::new(bytes), len).unwrap()
    }

    #[test]
    fn first_channel_in_mono_stereo_and_surround() {
        for channels in [1, 2, 6, 32] {
            assert!(read(wave(channels, 0, 32000))
                .peaks
                .iter()
                .all(|v| *v == 0.0));
            let result = read(wave(channels, -12000, 0));
            assert_eq!(result.channel, 1);
            assert!(result.peaks.iter().all(|v| *v == 1.0));
        }
    }
    #[test]
    fn truncated_input_is_rejected() {
        let mut bytes = wave(2, 1, 0);
        bytes.pop();
        let len = bytes.len() as u64;
        assert!(preview(&mut Cursor::new(bytes), len).is_err());
    }
    #[test]
    fn sample_encodings_and_non_finite_values() {
        let mut format = Format {
            stride: 4,
            bytes: 4,
            float: true,
            little: true,
            unsigned: false,
            frames: None,
        };
        assert_eq!(sample(&f32::NAN.to_le_bytes(), format), 0.0);
        assert_eq!(sample(&0.25_f32.to_le_bytes(), format), 0.25);
        format.float = false;
        format.little = false;
        format.bytes = 3;
        assert_eq!(sample(&[0x80, 0, 0], format), 1.0);
        format.bytes = 1;
        format.unsigned = true;
        assert_eq!(sample(&[128], format), 0.0);
    }
    #[test]
    fn aiff_big_endian_and_sound_offset() {
        let mut bytes = b"FORM\0\0\0\0AIFFCOMM\0\0\0\x12\0\x02\0\0\x01\0\0\x10".to_vec();
        bytes.extend_from_slice(&[0x40, 0x0e, 0xbb, 0x80, 0, 0, 0, 0, 0, 0]);
        bytes.extend_from_slice(b"SSND");
        bytes.extend_from_slice(&1036_u32.to_be_bytes());
        bytes.extend_from_slice(&4_u32.to_be_bytes());
        bytes.extend_from_slice(&0_u32.to_be_bytes());
        bytes.extend_from_slice(&[0xff; 4]);
        for _ in 0..256 {
            bytes.extend_from_slice(&[0, 0, 0x7f, 0xff]);
        }
        let size = bytes.len() as u32 - 8;
        bytes[4..8].copy_from_slice(&size.to_be_bytes());
        assert!(read(bytes).peaks.iter().all(|v| *v == 0.0));
    }
    #[test]
    fn sampling_io_is_bounded_for_large_recordings() {
        let mut file = tempfile::tempfile().unwrap();
        use std::io::Write;
        let mut header = wave(32, 0, 0);
        header.truncate(44);
        let size = 2_000_000_000_u32;
        header[4..8].copy_from_slice(&(size + 36).to_le_bytes());
        header[40..44].copy_from_slice(&size.to_le_bytes());
        file.write_all(&header).unwrap();
        file.set_len(size as u64 + 44).unwrap();
        file.rewind().unwrap();
        struct Count {
            file: File,
            bytes: usize,
        }
        impl Read for Count {
            fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
                let n = self.file.read(buffer)?;
                self.bytes += n;
                Ok(n)
            }
        }
        impl Seek for Count {
            fn seek(&mut self, pos: SeekFrom) -> std::io::Result<u64> {
                self.file.seek(pos)
            }
        }
        let mut counted = Count { file, bytes: 0 };
        let result = preview(&mut counted, size as u64 + 44).unwrap();
        assert_eq!(result.peaks.len(), BINS);
        assert!(counted.bytes <= BINS * WINDOW_BYTES + 100);
    }
}
