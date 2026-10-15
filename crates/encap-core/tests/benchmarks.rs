use encap_core::{
    discover_audio_files, edit_audio, inspect_source, load_project, render_srt,
    render_transcript_text, save_project, waveform_preview, AudioEdits, AudioSource, Chapter,
    ProjectDocument, TranscriptSegment, TranscriptWord, WorkspaceMode,
};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::Path;
use std::time::Instant;

fn create_wav(
    path: &Path,
    channels: u16,
    bits_per_sample: u16,
    sample_rate: u32,
    duration_secs: f32,
) {
    let bytes_per_sample = bits_per_sample / 8;
    let block_align = channels * bytes_per_sample;
    let total_samples = (sample_rate as f32 * duration_secs) as u32;
    let data_len = total_samples * block_align as u32;

    let mut file = File::create(path).unwrap();
    // RIFF header
    file.write_all(b"RIFF").unwrap();
    file.write_all(&(36 + data_len).to_le_bytes()).unwrap();
    file.write_all(b"WAVE").unwrap();

    // fmt chunk
    file.write_all(b"fmt ").unwrap();
    file.write_all(&16_u32.to_le_bytes()).unwrap(); // 16 bytes for PCM
    file.write_all(&(if bits_per_sample == 32 { 3_u16 } else { 1_u16 }).to_le_bytes())
        .unwrap(); // IEEE float or PCM
    file.write_all(&channels.to_le_bytes()).unwrap();
    file.write_all(&sample_rate.to_le_bytes()).unwrap();
    let byte_rate = sample_rate * block_align as u32;
    file.write_all(&byte_rate.to_le_bytes()).unwrap();
    file.write_all(&block_align.to_le_bytes()).unwrap();
    file.write_all(&bits_per_sample.to_le_bytes()).unwrap();

    // data chunk
    file.write_all(b"data").unwrap();
    file.write_all(&data_len.to_le_bytes()).unwrap();

    // Write samples in chunks
    let chunk_samples = 4096;
    let mut chunk = vec![0_u8; chunk_samples * block_align as usize];
    let mut remaining = data_len as usize;
    let mut val: i16 = 1000;
    while remaining > 0 {
        let to_write = remaining.min(chunk.len());
        // generate simple audio pattern
        for frame in chunk[..to_write].chunks_exact_mut(block_align as usize) {
            val = val.wrapping_add(31);
            if bits_per_sample == 32 {
                frame[..4].copy_from_slice(&(val as f32 / 32768.0).to_le_bytes());
            } else {
                let b = val.to_le_bytes();
                frame[0] = b[0];
                frame[1] = b[1];
            }
        }
        file.write_all(&chunk[..to_write]).unwrap();
        remaining -= to_write;
    }
}

fn create_aiff(
    path: &Path,
    channels: u16,
    bits_per_sample: u16,
    sample_rate: u32,
    duration_secs: f32,
) {
    let bytes_per_sample = bits_per_sample / 8;
    let block_align = channels * bytes_per_sample;
    let total_samples = (sample_rate as f32 * duration_secs) as u32;
    let data_len = total_samples * block_align as u32;

    let mut file = File::create(path).unwrap();
    // FORM header
    file.write_all(b"FORM").unwrap();
    file.write_all(&(46 + data_len).to_be_bytes()).unwrap();
    file.write_all(b"AIFF").unwrap();

    // COMM chunk (18 bytes payload)
    file.write_all(b"COMM").unwrap();
    file.write_all(&18_u32.to_be_bytes()).unwrap();
    file.write_all(&channels.to_be_bytes()).unwrap();
    file.write_all(&total_samples.to_be_bytes()).unwrap();
    file.write_all(&bits_per_sample.to_be_bytes()).unwrap();
    // 80-bit IEEE 754 extended float for 44100 / 48000
    let rate_bytes: [u8; 10] = if sample_rate == 48000 {
        [0x40, 0x0E, 0xBB, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    } else {
        // 44100
        [0x40, 0x0E, 0xAC, 0x44, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    };
    file.write_all(&rate_bytes).unwrap();

    // SSND chunk
    file.write_all(b"SSND").unwrap();
    file.write_all(&(data_len + 8).to_be_bytes()).unwrap();
    file.write_all(&0_u32.to_be_bytes()).unwrap(); // offset
    file.write_all(&0_u32.to_be_bytes()).unwrap(); // block size

    let chunk_samples = 4096;
    let mut chunk = vec![0_u8; chunk_samples * block_align as usize];
    let mut remaining = data_len as usize;
    let mut val: i16 = 1000;
    while remaining > 0 {
        let to_write = remaining.min(chunk.len());
        for frame in chunk[..to_write].chunks_exact_mut(block_align as usize) {
            val = val.wrapping_add(31);
            let b = val.to_be_bytes();
            frame[0] = b[0];
            frame[1] = b[1];
        }
        file.write_all(&chunk[..to_write]).unwrap();
        remaining -= to_write;
    }
}

// Independent full-buffer reference, computed outside timed preview calls.
// Fixtures here are canonical stereo WAVs with a 44-byte header.
fn reference_waveform(path: &Path, bits: u16) -> Vec<f32> {
    let bytes = fs::read(path).unwrap();
    let audio = &bytes[44..];
    let stride = bits as usize / 8 * 2;
    let frames = audio.len() / stride;
    let mut peaks = Vec::with_capacity(64);
    for bin in 0..64 {
        let first = frames * bin / 64;
        let end = frames * (bin + 1) / 64;
        let count = (end - first).min(256);
        let start = first + (end - first - count) / 2;
        let mut peak = 0_f32;
        for frame in start..start + count {
            let raw = &audio[frame * stride..];
            let value = match bits {
                16 => i16::from_le_bytes(raw[..2].try_into().unwrap()) as f64 / 32768.0,
                24 => {
                    ((i32::from_le_bytes([raw[0], raw[1], raw[2], 0]) << 8) >> 8) as f64 / 8388608.0
                }
                32 => f32::from_le_bytes(raw[..4].try_into().unwrap()) as f64,
                _ => unreachable!(),
            };
            peak = peak.max(if value.is_finite() {
                value.abs().min(1.0) as f32
            } else {
                0.0
            });
        }
        peaks.push(peak);
    }
    let maximum = peaks.iter().copied().fold(0_f32, f32::max);
    if maximum > 0.0 {
        for peak in &mut peaks {
            *peak = (*peak / maximum).sqrt();
        }
    }
    peaks
}

fn measure<F>(name: &str, iterations: usize, mut op: F)
where
    F: FnMut(),
{
    // Warmup
    for _ in 0..iterations.min(5) {
        op();
    }

    let mut timings = Vec::with_capacity(iterations);
    for _ in 0..iterations {
        let start = Instant::now();
        op();
        timings.push(start.elapsed());
    }
    timings.sort();

    let median = timings[timings.len() / 2];
    let p95_idx = ((timings.len() as f64 * 0.95) as usize).min(timings.len() - 1);
    let p95 = timings[p95_idx];
    let min = timings[0];
    let max = timings[timings.len() - 1];
    let total_secs: f64 = timings.iter().map(|d| d.as_secs_f64()).sum();
    let ops_per_sec = timings.len() as f64 / total_secs;

    println!(
        "BENCH: {:<35} | Median: {:>8.3?} | P95: {:>8.3?} | Min: {:>8.3?} | Max: {:>8.3?} | Ops/sec: {:>10.1}",
        name, median, p95, min, max, ops_per_sec
    );
}

#[test]
#[ignore = "diagnostic timings; run explicitly in release mode"]
fn run_comprehensive_benchmarks() {
    println!("\n=======================================================");
    println!("      EnCAP Core Comprehensive Performance Benchmark    ");
    println!("=======================================================\n");

    let temp_dir = tempfile::tempdir().unwrap();
    let root = temp_dir.path();

    // 1. Natural Sort Benchmark
    let sort_dir = root.join("sort_files");
    fs::create_dir_all(&sort_dir).unwrap();
    for i in 0..200 {
        let filename = format!("track_{:04}_take_{}.wav", i, i % 7);
        File::create(sort_dir.join(filename)).unwrap();
    }
    measure("natural_sort_200_files", 30, || {
        let paths = discover_audio_files(&sort_dir).unwrap();
        assert_eq!(paths.len(), 200);
        assert_eq!(paths[0].file_name().unwrap(), "track_0000_take_0.wav");
        assert_eq!(paths[199].file_name().unwrap(), "track_0199_take_3.wav");
        std::hint::black_box(paths);
    });

    let mixed_dir = root.join("mixed_sort");
    fs::create_dir_all(&mixed_dir).unwrap();
    for i in 0..200 {
        let name = format!(
            "{}take{}_{}_{}.WAV",
            ["音", "é", "A", "a"][i % 4],
            i,
            "0".repeat(i % 12),
            "9".repeat(i % 90 + 1)
        );
        File::create(mixed_dir.join(name)).unwrap();
    }
    let expected = discover_audio_files(&mixed_dir).unwrap();
    measure("natural_sort_200_mixed_unicode", 30, || {
        let paths = discover_audio_files(&mixed_dir).unwrap();
        assert_eq!(paths, expected);
        std::hint::black_box(paths);
    });

    // 2. Audio File Inspection (WAV & AIFF)
    let sample_wav = root.join("sample.wav");
    create_wav(&sample_wav, 2, 16, 48000, 10.0); // 10s audio = ~1.9 MB
    measure("inspect_wav_10s_audio", 100, || {
        let duration = inspect_source(&sample_wav).unwrap();
        assert!((duration - 10.0).abs() < 0.01);
    });

    let sample_aiff = root.join("sample.aiff");
    create_aiff(&sample_aiff, 2, 16, 48000, 10.0);
    measure("inspect_aiff_10s_audio", 100, || {
        let duration = inspect_source(&sample_aiff).unwrap();
        assert!((duration - 10.0).abs() < 0.01);
    });

    let metadata_wav = root.join("metadata.wav");
    let bytes = fs::read(&sample_wav).unwrap();
    let mut padded = bytes[..12].to_vec();
    padded.extend_from_slice(b"JUNK");
    padded.extend_from_slice(&65537_u32.to_le_bytes());
    padded.resize(padded.len() + 65538, 0);
    padded.extend_from_slice(&bytes[12..]);
    let riff_size = (padded.len() - 8) as u32;
    padded[4..8].copy_from_slice(&riff_size.to_le_bytes());
    fs::write(&metadata_wav, padded).unwrap();
    measure("inspect_wav_odd_metadata", 100, || {
        assert_eq!(inspect_source(&metadata_wav).unwrap(), 10.0);
    });

    // 3. Waveform Generation Benchmark
    let large_wav = root.join("large_track.wav");
    create_wav(&large_wav, 2, 16, 48000, 120.0); // 2 minutes audio = ~23 MB
    let expected_waveform = reference_waveform(&large_wav, 16);
    measure("waveform_preview_2min_wav", 50, || {
        let preview = waveform_preview(&large_wav).unwrap();
        assert_eq!(preview.channel, 1);
        assert_eq!(preview.peaks.len(), 64);
        assert_eq!(preview.peaks, expected_waveform);
        std::hint::black_box(preview);
    });

    for (bits, name) in [
        (24, "waveform_preview_pcm24_stereo"),
        (32, "waveform_preview_float32_stereo"),
    ] {
        let path = root.join(format!("waveform_{bits}.wav"));
        create_wav(&path, 2, bits, 48000, 120.0);
        let expected = reference_waveform(&path, bits);
        measure(name, 50, || {
            let preview = waveform_preview(&path).unwrap();
            assert_eq!(preview.peaks.len(), 64);
            assert_eq!(preview.peaks, expected);
            std::hint::black_box(preview);
        });
    }

    // 4. Project Full Save & Re-save (Persistence)
    let project_dir = root.join("persistence");
    fs::create_dir_all(&project_dir).unwrap();
    let mut project = ProjectDocument {
        project_title: "Benchmark Podcast".into(),
        ..ProjectDocument::default()
    };
    let project_seconds: f32 = std::env::var("ENCAP_BENCH_PROJECT_SECONDS")
        .unwrap_or_else(|_| "15".into())
        .parse()
        .unwrap();
    assert!(project_seconds.is_finite() && project_seconds > 0.0 && project_seconds <= 600.0);
    for i in 1..=4 {
        let src = project_dir.join(format!("chapter_{i}.wav"));
        create_wav(&src, 2, 16, 48000, project_seconds); // 15s each = ~2.8 MB each, ~11.5 MB total
        project.audio_sources.push(AudioSource {
            source_path: src,
            display_name: format!("Chapter {i}"),
            duration_seconds: project_seconds as f64,
            stored_path: None,
            extensions: BTreeMap::new(),
        });
        project.chapters.push(Chapter {
            id: format!("ch_{i}"),
            start_time_seconds: (i - 1) as f64 * project_seconds as f64,
            duration_seconds: project_seconds as f64,
            chapter_number: i as u32,
            title: format!("Chapter {i}"),
            link_url: String::new(),
            image_path: None,
            image_stored_path: None,
            extensions: BTreeMap::new(),
        });
    }

    let encap_file = project_dir.join("benchmark.encap");
    measure("project_first_save_11mb", 10, || {
        let dest = project_dir.join(format!("test_save_{}.encap", uuid::Uuid::new_v4()));
        save_project(&project, &dest).unwrap();
        assert!(fs::metadata(&dest).unwrap().len() > 0);
        fs::remove_file(dest).unwrap();
    });

    // Save initial destination for incremental testing
    save_project(&project, &encap_file).unwrap();
    project.project_path = Some(encap_file.clone());

    measure("project_incremental_metadata_save", 30, || {
        project.metadata.summary = format!("Updated summary {}", uuid::Uuid::new_v4());
        project.active_mode = WorkspaceMode::Video;
        save_project(&project, &encap_file).unwrap();
    });

    // 5. Project Load & Extraction
    let extract_dir = root.join("extract_scratch");
    measure("project_load_and_extract", 20, || {
        let loaded = load_project(&encap_file, Some(&extract_dir)).unwrap();
        assert_eq!(loaded.audio_sources.len(), 4);
        for (actual, original) in loaded.audio_sources.iter().zip(&project.audio_sources) {
            assert_eq!(
                fs::read(&actual.source_path).unwrap(),
                fs::read(&original.source_path).unwrap()
            );
        }
        fs::remove_dir_all(&extract_dir).unwrap();
    });

    // 6. Audio Editing & Chapter Triage
    let edit_project = project.clone();
    let to_remove = edit_project.audio_sources[1].source_path.clone();
    measure("audio_edit_triage_cut", 50, || {
        let edits = AudioEdits {
            add_files: Vec::new(),
            remove_files: vec![to_remove.clone()],
        };
        let result = edit_audio(&edit_project, edits).unwrap();
        assert_eq!(result.audio_sources.len(), 3);
        assert!(!result
            .audio_sources
            .iter()
            .any(|s| s.source_path == to_remove));
        std::hint::black_box(result);
    });

    // 7. Transcript Rendering
    let mut segments = Vec::new();
    for i in 0..1000 {
        segments.push(TranscriptSegment {
            id: format!("seg_{i}"),
            start_time_seconds: i as f64 * 2.5,
            end_time_seconds: (i as f64 + 1.0) * 2.5,
            speaker: format!("Speaker {}", i % 3),
            text:
                "This is a detailed segment of the podcast conversation with valuable information."
                    .into(),
            words: (0..12)
                .map(|w| TranscriptWord {
                    id: format!("w_{i}_{w}"),
                    start_time_seconds: i as f64 * 2.5 + w as f64 * 0.2,
                    end_time_seconds: i as f64 * 2.5 + (w + 1) as f64 * 0.2,
                    text: "word".into(),
                    extensions: BTreeMap::new(),
                })
                .collect(),
            extensions: BTreeMap::new(),
        });
    }

    measure("render_transcript_text_1000_segments", 50, || {
        let text = render_transcript_text(&segments);
        assert_eq!(text.lines().count(), 1000);
        std::hint::black_box(text);
    });

    measure("render_srt_1000_segments", 50, || {
        let srt = render_srt(&segments);
        assert_eq!(srt.matches(" --> ").count(), 1000);
        std::hint::black_box(srt);
    });

    for (index, segment) in segments.iter_mut().enumerate() {
        segment.speaker = if index % 3 == 0 {
            "  音声 😀  ".into()
        } else {
            String::new()
        };
        segment.text =
            ["", " Unicode é😀\nsecond line ", " long transcript "][index % 3].repeat(index % 31);
    }
    let expected_text = render_transcript_text(&segments);
    let expected_srt = render_srt(&segments);
    measure("render_transcript_unicode_variable", 50, || {
        let text = render_transcript_text(&segments);
        assert_eq!(text, expected_text);
        std::hint::black_box(text);
    });
    measure("render_srt_unicode_variable", 50, || {
        let srt = render_srt(&segments);
        assert_eq!(srt, expected_srt);
        std::hint::black_box(srt);
    });

    println!("\n=======================================================");
    println!("                Benchmark Suite Complete               ");
    println!("=======================================================\n");
}
