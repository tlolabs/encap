use crate::model::{new_id, AudioSource, Chapter, ProjectDocument};
use crate::{EncapError, Result};
use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

const MAX_METADATA_CHUNK: u64 = 64 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct AudioFormat {
    channels: u16,
    sample_rate: u32,
    bits_per_sample: u16,
    block_align: u16,
    data_bytes: u64,
}

pub fn discover_audio_files(folder: &Path) -> Result<Vec<PathBuf>> {
    let entries = std::fs::read_dir(folder).map_err(|source| EncapError::Read {
        path: folder.to_path_buf(),
        source,
    })?;
    let mut paths = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|source| EncapError::Read {
            path: folder.to_path_buf(),
            source,
        })?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        if matches!(
            extension.to_ascii_lowercase().as_str(),
            "wav" | "wave" | "aif" | "aiff" | "aifc"
        ) {
            paths.push(path);
        }
    }
    paths.sort_by(|left, right| {
        natural_cmp(
            left.file_name()
                .and_then(|value| value.to_str())
                .unwrap_or_default(),
            right
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or_default(),
        )
    });
    if paths.is_empty() {
        return Err(EncapError::Message(format!(
            "No WAV or AIFF files were found in {}.",
            folder.display()
        )));
    }
    Ok(paths)
}

pub fn inspect_source(path: &Path) -> Result<f64> {
    let mut file = File::open(path).map_err(|source| EncapError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    let mut header = [0_u8; 12];
    file.read_exact(&mut header)
        .map_err(|source| EncapError::Read {
            path: path.to_path_buf(),
            source,
        })?;
    let format = if &header[0..4] == b"RIFF" && &header[8..12] == b"WAVE" {
        inspect_wave(&mut file, path)?
    } else if &header[0..4] == b"FORM" && matches!(&header[8..12], b"AIFF" | b"AIFC") {
        inspect_aiff(&mut file, path)?
    } else {
        return Err(EncapError::UnsupportedAudio(format!(
            "{} is not a WAV or AIFF file.",
            path.display()
        )));
    };
    if format.channels == 0
        || format.sample_rate == 0
        || format.block_align == 0
        || format.bits_per_sample == 0
    {
        return Err(EncapError::UnsupportedAudio(format!(
            "{} has an invalid audio format.",
            path.display()
        )));
    }
    let frames = format.data_bytes / u64::from(format.block_align);
    Ok(frames as f64 / f64::from(format.sample_rate))
}

pub fn inspect_folder(folder: &Path) -> Result<ProjectDocument> {
    let paths = discover_audio_files(folder)?;
    let mut sources = Vec::with_capacity(paths.len());
    let mut chapters = Vec::with_capacity(paths.len());
    let mut position = 0.0;
    for (index, path) in paths.into_iter().enumerate() {
        let duration = inspect_source(&path)?;
        let name = path
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or("Audio")
            .to_string();
        sources.push(AudioSource {
            source_path: path,
            display_name: name.clone(),
            duration_seconds: duration,
            stored_path: None,
            extensions: BTreeMap::new(),
        });
        chapters.push(Chapter {
            id: new_id(),
            start_time_seconds: position,
            duration_seconds: duration,
            chapter_number: (index + 1) as u32,
            title: name,
            link_url: String::new(),
            image_path: None,
            image_stored_path: None,
            extensions: BTreeMap::new(),
        });
        position += duration;
    }
    let project_title = folder
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("Untitled")
        .to_string();
    let mut project = ProjectDocument {
        project_title: project_title.clone(),
        source_folder: Some(folder.to_path_buf()),
        audio_sources: sources,
        chapters,
        ..ProjectDocument::default()
    };
    project.metadata.episode_title = project.project_title.clone();
    Ok(project)
}

fn inspect_wave(file: &mut File, path: &Path) -> Result<AudioFormat> {
    let length = file
        .metadata()
        .map_err(|source| EncapError::Read {
            path: path.to_path_buf(),
            source,
        })?
        .len();
    let mut fmt: Option<(u16, u32, u16, u16)> = None;
    let mut data_bytes = None;
    while file.stream_position().unwrap_or(length) + 8 <= length {
        let mut chunk = [0_u8; 8];
        file.read_exact(&mut chunk)
            .map_err(|source| EncapError::Read {
                path: path.to_path_buf(),
                source,
            })?;
        let size = u32::from_le_bytes(chunk[4..8].try_into().unwrap()) as u64;
        let start = file.stream_position().unwrap_or(length);
        if start.checked_add(size).is_none() || start + size > length {
            return Err(EncapError::UnsupportedAudio(format!(
                "{} contains a truncated WAV chunk.",
                path.display()
            )));
        }
        match &chunk[0..4] {
            b"fmt " => {
                if !(16..=MAX_METADATA_CHUNK).contains(&size) {
                    return Err(EncapError::UnsupportedAudio(
                        "The WAV format block is invalid.".into(),
                    ));
                }
                let mut raw = vec![0; size as usize];
                file.read_exact(&mut raw)
                    .map_err(|source| EncapError::Read {
                        path: path.to_path_buf(),
                        source,
                    })?;
                let encoding = u16::from_le_bytes(raw[0..2].try_into().unwrap());
                if !matches!(encoding, 1 | 3 | 0xfffe) {
                    return Err(EncapError::UnsupportedAudio(
                        "Only PCM and IEEE-float WAV files are supported.".into(),
                    ));
                }
                fmt = Some((
                    u16::from_le_bytes(raw[2..4].try_into().unwrap()),
                    u32::from_le_bytes(raw[4..8].try_into().unwrap()),
                    u16::from_le_bytes(raw[14..16].try_into().unwrap()),
                    u16::from_le_bytes(raw[12..14].try_into().unwrap()),
                ));
            }
            b"data" => {
                data_bytes = Some(size);
                file.seek(SeekFrom::Start(start + size))
                    .map_err(|source| EncapError::Read {
                        path: path.to_path_buf(),
                        source,
                    })?;
            }
            _ => {
                file.seek(SeekFrom::Start(start + size))
                    .map_err(|source| EncapError::Read {
                        path: path.to_path_buf(),
                        source,
                    })?;
            }
        }
        if size % 2 == 1 {
            file.seek(SeekFrom::Current(1))
                .map_err(|source| EncapError::Read {
                    path: path.to_path_buf(),
                    source,
                })?;
        }
    }
    let (channels, sample_rate, bits_per_sample, block_align) =
        fmt.ok_or_else(|| EncapError::UnsupportedAudio("The WAV format block is missing.".into()))?;
    Ok(AudioFormat {
        channels,
        sample_rate,
        bits_per_sample,
        block_align,
        data_bytes: data_bytes.ok_or_else(|| {
            EncapError::UnsupportedAudio("The WAV sample block is missing.".into())
        })?,
    })
}

fn inspect_aiff(file: &mut File, path: &Path) -> Result<AudioFormat> {
    let length = file
        .metadata()
        .map_err(|source| EncapError::Read {
            path: path.to_path_buf(),
            source,
        })?
        .len();
    let mut comm: Option<(u16, u32, u16, u32)> = None;
    let mut data_bytes = None;
    while file.stream_position().unwrap_or(length) + 8 <= length {
        let mut chunk = [0_u8; 8];
        file.read_exact(&mut chunk)
            .map_err(|source| EncapError::Read {
                path: path.to_path_buf(),
                source,
            })?;
        let size = u32::from_be_bytes(chunk[4..8].try_into().unwrap()) as u64;
        let start = file.stream_position().unwrap_or(length);
        if start.checked_add(size).is_none() || start + size > length {
            return Err(EncapError::UnsupportedAudio(format!(
                "{} contains a truncated AIFF chunk.",
                path.display()
            )));
        }
        if &chunk[0..4] == b"COMM" {
            if !(18..=MAX_METADATA_CHUNK).contains(&size) {
                return Err(EncapError::UnsupportedAudio(
                    "The AIFF format block is invalid.".into(),
                ));
            }
            let mut raw = vec![0; size as usize];
            file.read_exact(&mut raw)
                .map_err(|source| EncapError::Read {
                    path: path.to_path_buf(),
                    source,
                })?;
            let channels = u16::from_be_bytes(raw[0..2].try_into().unwrap());
            let frames = u32::from_be_bytes(raw[2..6].try_into().unwrap());
            let bits = u16::from_be_bytes(raw[6..8].try_into().unwrap());
            let rate = decode_extended(&raw[8..18])?;
            comm = Some((channels, rate, bits, frames));
        } else if &chunk[0..4] == b"SSND" {
            if size < 8 {
                return Err(EncapError::UnsupportedAudio(
                    "The AIFF sound block is invalid.".into(),
                ));
            }
            data_bytes = Some(size - 8);
            file.seek(SeekFrom::Start(start + size))
                .map_err(|source| EncapError::Read {
                    path: path.to_path_buf(),
                    source,
                })?;
        } else {
            file.seek(SeekFrom::Start(start + size))
                .map_err(|source| EncapError::Read {
                    path: path.to_path_buf(),
                    source,
                })?;
        }
        if size % 2 == 1 {
            file.seek(SeekFrom::Current(1))
                .map_err(|source| EncapError::Read {
                    path: path.to_path_buf(),
                    source,
                })?;
        }
    }
    let (channels, sample_rate, bits_per_sample, frames) = comm
        .ok_or_else(|| EncapError::UnsupportedAudio("The AIFF format block is missing.".into()))?;
    let bytes_per_sample = u64::from(bits_per_sample).div_ceil(8);
    let expected = u64::from(frames) * u64::from(channels) * bytes_per_sample;
    let data_bytes = data_bytes
        .ok_or_else(|| EncapError::UnsupportedAudio("The AIFF sound block is missing.".into()))?;
    if data_bytes < expected {
        return Err(EncapError::UnsupportedAudio(
            "The AIFF sample data is truncated.".into(),
        ));
    }
    Ok(AudioFormat {
        channels,
        sample_rate,
        bits_per_sample,
        block_align: channels.saturating_mul(bytes_per_sample as u16),
        data_bytes: expected,
    })
}

fn decode_extended(raw: &[u8]) -> Result<u32> {
    let exponent = u16::from_be_bytes(raw[0..2].try_into().unwrap());
    if exponent & 0x8000 != 0 {
        return Err(EncapError::UnsupportedAudio(
            "The AIFF sample rate is negative.".into(),
        ));
    }
    let exp = i32::from(exponent & 0x7fff);
    let mantissa = u64::from_be_bytes(raw[2..10].try_into().unwrap());
    if exp == 0 || mantissa == 0 {
        return Err(EncapError::UnsupportedAudio(
            "The AIFF sample rate is zero.".into(),
        ));
    }
    let value = (mantissa as f64) * 2_f64.powi(exp - 16383 - 63);
    if !value.is_finite() || !(1.0..=768_000.0).contains(&value) {
        return Err(EncapError::UnsupportedAudio(
            "The AIFF sample rate is unsupported.".into(),
        ));
    }
    Ok(value.round() as u32)
}

fn natural_cmp(left: &str, right: &str) -> Ordering {
    let mut a = left.chars().peekable();
    let mut b = right.chars().peekable();
    loop {
        match (a.peek(), b.peek()) {
            (None, None) => return Ordering::Equal,
            (None, _) => return Ordering::Less,
            (_, None) => return Ordering::Greater,
            (Some(x), Some(y)) if x.is_ascii_digit() && y.is_ascii_digit() => {
                let an: String = std::iter::from_fn(|| a.next_if(|c| c.is_ascii_digit())).collect();
                let bn: String = std::iter::from_fn(|| b.next_if(|c| c.is_ascii_digit())).collect();
                match an
                    .trim_start_matches('0')
                    .len()
                    .cmp(&bn.trim_start_matches('0').len())
                    .then_with(|| an.cmp(&bn))
                {
                    Ordering::Equal => {}
                    order => return order,
                }
            }
            _ => {
                let ac = a.next().unwrap().to_ascii_lowercase();
                let bc = b.next().unwrap().to_ascii_lowercase();
                match ac.cmp(&bc) {
                    Ordering::Equal => {}
                    order => return order,
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::natural_cmp;
    #[test]
    fn natural_sort_orders_recording_numbers() {
        let mut names = vec!["part10.wav", "part2.wav", "part1.wav"];
        names.sort_by(|a, b| natural_cmp(a, b));
        assert_eq!(names, ["part1.wav", "part2.wav", "part10.wav"]);
    }
}
