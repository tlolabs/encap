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
        inspect_aiff(&mut file, path, &header[8..12] == b"AIFC")?
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
    let mut project = inspect_files(&paths)?;
    project.project_title = folder
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("Untitled")
        .to_string();
    project.source_folder = Some(folder.to_path_buf());
    project.metadata.episode_title = project.project_title.clone();
    Ok(project)
}

/// Inspect only the selected files, retaining their supplied order.
pub fn inspect_files(paths: &[PathBuf]) -> Result<ProjectDocument> {
    let mut sources = Vec::with_capacity(paths.len());
    let mut chapters = Vec::with_capacity(paths.len());
    let mut position = 0.0;
    for (index, path) in paths.iter().enumerate() {
        let duration = inspect_source(path)?;
        let name = path
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or("Audio")
            .to_string();
        sources.push(AudioSource {
            source_path: path.clone(),
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
    Ok(ProjectDocument {
        audio_sources: sources,
        chapters,
        ..ProjectDocument::default()
    })
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
    let mut pos = 12_u64;
    while pos + 8 <= length {
        let mut chunk = [0_u8; 8];
        file.read_exact(&mut chunk)
            .map_err(|source| EncapError::Read {
                path: path.to_path_buf(),
                source,
            })?;
        pos += 8;
        let size = u32::from_le_bytes(chunk[4..8].try_into().unwrap()) as u64;
        let start = pos;
        if start.checked_add(size + (size & 1)).is_none() || start + size + (size & 1) > length {
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
                let read_len = (size as usize).min(40);
                let mut raw = [0_u8; 40];
                file.read_exact(&mut raw[..read_len])
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
                if encoding == 0xfffe
                    && (size < 40
                        || u16::from_le_bytes(raw[16..18].try_into().unwrap()) < 22
                        || !matches!(u16::from_le_bytes(raw[24..26].try_into().unwrap()), 1 | 3)
                        || raw[26..40] != [0, 0, 0, 0, 16, 0, 128, 0, 0, 170, 0, 56, 155, 113])
                {
                    return Err(EncapError::UnsupportedAudio(
                        "The extensible WAV format is invalid.".into(),
                    ));
                }
                fmt = Some((
                    u16::from_le_bytes(raw[2..4].try_into().unwrap()),
                    u32::from_le_bytes(raw[4..8].try_into().unwrap()),
                    u16::from_le_bytes(raw[14..16].try_into().unwrap()),
                    u16::from_le_bytes(raw[12..14].try_into().unwrap()),
                ));
                file.seek(SeekFrom::Start(start + size))
                    .map_err(|source| EncapError::Read {
                        path: path.to_path_buf(),
                        source,
                    })?;
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
        pos = start + size;
        if size % 2 == 1 {
            file.seek(SeekFrom::Current(1))
                .map_err(|source| EncapError::Read {
                    path: path.to_path_buf(),
                    source,
                })?;
            pos += 1;
        }
    }
    if pos != length {
        return Err(EncapError::UnsupportedAudio(
            "The WAV chunk header is truncated.".into(),
        ));
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

fn inspect_aiff(file: &mut File, path: &Path, compressed_container: bool) -> Result<AudioFormat> {
    let length = file
        .metadata()
        .map_err(|source| EncapError::Read {
            path: path.to_path_buf(),
            source,
        })?
        .len();
    let mut comm: Option<(u16, u32, u16, u32)> = None;
    let mut data_bytes = None;
    let mut pos = 12_u64;
    while pos + 8 <= length {
        let mut chunk = [0_u8; 8];
        file.read_exact(&mut chunk)
            .map_err(|source| EncapError::Read {
                path: path.to_path_buf(),
                source,
            })?;
        pos += 8;
        let size = u32::from_be_bytes(chunk[4..8].try_into().unwrap()) as u64;
        let start = pos;
        if start.checked_add(size + (size & 1)).is_none() || start + size + (size & 1) > length {
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
            let mut raw = [0_u8; 22];
            if compressed_container && size < 22 {
                return Err(EncapError::UnsupportedAudio(
                    "The AIFC compression type is missing.".into(),
                ));
            }
            let read_len = if compressed_container { 22 } else { 18 };
            file.read_exact(&mut raw[..read_len])
                .map_err(|source| EncapError::Read {
                    path: path.to_path_buf(),
                    source,
                })?;
            let channels = u16::from_be_bytes(raw[0..2].try_into().unwrap());
            let frames = u32::from_be_bytes(raw[2..6].try_into().unwrap());
            let bits = u16::from_be_bytes(raw[6..8].try_into().unwrap());
            let rate = decode_extended(&raw[8..18])?;
            if compressed_container
                && !matches!(
                    &raw[18..22],
                    b"NONE" | b"twos" | b"sowt" | b"fl32" | b"FL32" | b"fl64" | b"FL64"
                )
            {
                return Err(EncapError::UnsupportedAudio(
                    "Compressed AIFC samples are unsupported.".into(),
                ));
            }
            comm = Some((channels, rate, bits, frames));
            file.seek(SeekFrom::Start(start + size))
                .map_err(|source| EncapError::Read {
                    path: path.to_path_buf(),
                    source,
                })?;
        } else if &chunk[0..4] == b"SSND" {
            if size < 8 {
                return Err(EncapError::UnsupportedAudio(
                    "The AIFF sound block is invalid.".into(),
                ));
            }
            let mut sound = [0_u8; 8];
            file.read_exact(&mut sound)
                .map_err(|source| EncapError::Read {
                    path: path.to_path_buf(),
                    source,
                })?;
            let offset = u32::from_be_bytes(sound[..4].try_into().unwrap()) as u64;
            if offset > size - 8 {
                return Err(EncapError::UnsupportedAudio(
                    "The AIFF sound offset is invalid.".into(),
                ));
            }
            data_bytes = Some(size - 8 - offset);
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
        pos = start + size;
        if size % 2 == 1 {
            file.seek(SeekFrom::Current(1))
                .map_err(|source| EncapError::Read {
                    path: path.to_path_buf(),
                    source,
                })?;
            pos += 1;
        }
    }
    if pos != length {
        return Err(EncapError::UnsupportedAudio(
            "The AIFF chunk header is truncated.".into(),
        ));
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
    let mut a_chars = left.char_indices().peekable();
    let mut b_chars = right.char_indices().peekable();
    loop {
        match (a_chars.peek(), b_chars.peek()) {
            (None, None) => return Ordering::Equal,
            (None, _) => return Ordering::Less,
            (_, None) => return Ordering::Greater,
            (Some(&(ai, x)), Some(&(bi, y))) if x.is_ascii_digit() && y.is_ascii_digit() => {
                let a_start = ai;
                while let Some(&(_, c)) = a_chars.peek() {
                    if c.is_ascii_digit() {
                        a_chars.next();
                    } else {
                        break;
                    }
                }
                let a_end = a_chars.peek().map(|&(i, _)| i).unwrap_or(left.len());
                let an = &left[a_start..a_end];

                let b_start = bi;
                while let Some(&(_, c)) = b_chars.peek() {
                    if c.is_ascii_digit() {
                        b_chars.next();
                    } else {
                        break;
                    }
                }
                let b_end = b_chars.peek().map(|&(i, _)| i).unwrap_or(right.len());
                let bn = &right[b_start..b_end];

                let atrim = an.trim_start_matches('0');
                let btrim = bn.trim_start_matches('0');
                match atrim
                    .len()
                    .cmp(&btrim.len())
                    .then_with(|| atrim.cmp(btrim))
                    .then_with(|| an.cmp(bn))
                {
                    Ordering::Equal => {}
                    order => return order,
                }
            }
            _ => {
                let (_, ac) = a_chars.next().unwrap();
                let (_, bc) = b_chars.next().unwrap();
                let ac = ac.to_ascii_lowercase();
                let bc = bc.to_ascii_lowercase();
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
    use super::{inspect_files, natural_cmp};

    #[test]
    fn selected_files_preserve_order_and_ignore_unselected_invalid_audio() {
        let temp = tempfile::tempdir().unwrap();
        let first = temp.path().join("first.wav");
        let second = temp.path().join("second.wav");
        let invalid = temp.path().join("invalid.wav");
        let mut wave = Vec::new();
        wave.extend_from_slice(b"RIFF");
        wave.extend_from_slice(&38_u32.to_le_bytes());
        wave.extend_from_slice(b"WAVEfmt ");
        wave.extend_from_slice(&16_u32.to_le_bytes());
        wave.extend_from_slice(&1_u16.to_le_bytes());
        wave.extend_from_slice(&1_u16.to_le_bytes());
        wave.extend_from_slice(&1_u32.to_le_bytes());
        wave.extend_from_slice(&2_u32.to_le_bytes());
        wave.extend_from_slice(&2_u16.to_le_bytes());
        wave.extend_from_slice(&16_u16.to_le_bytes());
        wave.extend_from_slice(b"data");
        wave.extend_from_slice(&2_u32.to_le_bytes());
        wave.extend_from_slice(&0_i16.to_le_bytes());
        std::fs::write(&first, &wave).unwrap();
        std::fs::write(&second, &wave).unwrap();
        std::fs::write(&invalid, b"invalid").unwrap();
        let project = inspect_files(&[second.clone(), first.clone()]).unwrap();
        assert_eq!(project.audio_sources.len(), 2);
        assert_eq!(project.audio_sources[0].source_path, second);
        assert_eq!(project.chapters[0].title, "second");
        assert_eq!(project.chapters[1].start_time_seconds, 1.0);
        assert_eq!(project.chapters[1].chapter_number, 2);
        assert!(inspect_files(&[first, invalid]).is_err());
    }

    #[test]
    fn natural_sort_orders_recording_numbers() {
        let mut names = vec![
            "part10.wav",
            "part2.wav",
            "part03.wav",
            "part002.wav",
            "part1.wav",
        ];
        names.sort_by(|a, b| natural_cmp(a, b));
        assert_eq!(
            names,
            [
                "part1.wav",
                "part002.wav",
                "part2.wav",
                "part03.wav",
                "part10.wav"
            ]
        );
    }
}

#[cfg(test)]
mod performance_regressions {
    use super::*;

    #[test]
    fn natural_order_is_consistent_for_unicode_long_numbers_and_leading_zeros() {
        let names = [
            "",
            "a",
            "A",
            "a0",
            "a00",
            "a01",
            "a1",
            "a2",
            "a10",
            "a1x2",
            "a1x10",
            "é2",
            "é10",
            "音02",
            "音2",
            "音10",
            "a18446744073709551616",
            "a999999999999999999999",
            "a00000000000000000000000000000000000000000001",
            "a/",
            "a:",
        ];
        for a in names {
            for b in names {
                assert_eq!(natural_cmp(a, b), natural_cmp(b, a).reverse());
                for c in names {
                    if natural_cmp(a, b).is_le() && natural_cmp(b, c).is_le() {
                        assert!(natural_cmp(a, c).is_le(), "{a:?} {b:?} {c:?}");
                    }
                }
            }
        }
        assert!(natural_cmp("音02", "音2").is_lt());
        assert!(natural_cmp("a18446744073709551616", "a999999999999999999999").is_lt());
        assert!(natural_cmp("a00000000000000000000000000000000000000000001", "a2").is_lt());
    }

    fn chunk(out: &mut Vec<u8>, id: &[u8; 4], data: &[u8], little: bool) {
        out.extend_from_slice(id);
        out.extend_from_slice(&if little {
            (data.len() as u32).to_le_bytes()
        } else {
            (data.len() as u32).to_be_bytes()
        });
        out.extend_from_slice(data);
        if data.len() % 2 == 1 {
            out.push(0);
        }
    }
    fn inspect(bytes: &[u8]) -> Result<f64> {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("fixture");
        std::fs::write(&path, bytes).unwrap();
        inspect_source(&path)
    }
    fn aiff(offset: u32, padding: usize, frames: u32) -> Vec<u8> {
        let mut out = b"FORM\0\0\0\0AIFF".to_vec();
        chunk(&mut out, b"JUNK", &[1, 2, 3], false);
        let mut comm = Vec::new();
        comm.extend_from_slice(&1_u16.to_be_bytes());
        comm.extend_from_slice(&frames.to_be_bytes());
        comm.extend_from_slice(&16_u16.to_be_bytes());
        comm.extend_from_slice(&[0x40, 0x0e, 0xbb, 0x80, 0, 0, 0, 0, 0, 0]);
        comm.extend_from_slice(&[0; 15]); // unread COMM tail and odd padding
        chunk(&mut out, b"COMM", &comm, false);
        let mut sound = Vec::new();
        sound.extend_from_slice(&offset.to_be_bytes());
        sound.extend_from_slice(&0_u32.to_be_bytes());
        sound.resize(8 + padding + 2, 0);
        chunk(&mut out, b"SSND", &sound, false);
        out
    }
    #[test]
    fn aiff_skips_comm_tail_and_accounts_for_sound_offset() {
        assert_eq!(inspect(&aiff(5, 5, 1)).unwrap(), 1.0 / 48000.0);
        assert!(inspect(&aiff(5, 5, 3)).is_err()); // offset bytes are not sample frames
        assert!(inspect(&aiff(u32::MAX, 0, 1)).is_err());
        let mut bytes = aiff(0, 0, 1);
        bytes.extend_from_slice(b"BAD");
        assert!(inspect(&bytes).is_err());
        let mut bytes = aiff(0, 0, 1);
        bytes.truncate(bytes.len() - 1);
        assert!(inspect(&bytes).is_err());
    }
    #[test]
    fn wav_bounded_fmt_reads_preserve_alignment_and_reject_bad_lengths() {
        let mut out = b"RIFF\0\0\0\0WAVE".to_vec();
        chunk(&mut out, b"JUNK", &[1, 2, 3], true);
        let mut fmt = vec![0; 81];
        fmt[..2].copy_from_slice(&1_u16.to_le_bytes());
        fmt[2..4].copy_from_slice(&1_u16.to_le_bytes());
        fmt[4..8].copy_from_slice(&48000_u32.to_le_bytes());
        fmt[12..14].copy_from_slice(&2_u16.to_le_bytes());
        fmt[14..16].copy_from_slice(&16_u16.to_le_bytes());
        chunk(&mut out, b"fmt ", &fmt, true);
        chunk(&mut out, b"data", &[0, 0], true);
        assert_eq!(inspect(&out).unwrap(), 1.0 / 48000.0);
        out.extend_from_slice(b"JUNK");
        out.extend_from_slice(&u32::MAX.to_le_bytes());
        assert!(inspect(&out).is_err());
        out.truncate(out.len() - 4);
        assert!(inspect(&out).is_err());
        let mut out = b"RIFF\0\0\0\0WAVE".to_vec();
        chunk(&mut out, b"fmt ", &fmt, true);
        chunk(&mut out, b"data", &[0], true);
        out.pop(); // missing odd-chunk pad
        assert!(inspect(&out).is_err());
    }
}
