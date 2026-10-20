//! Native EnCAP adapter checks. Supply the complete, authenticated pinned runtime
//! with ENCAP_CORE_RUNTIME_DIR; this suite never searches PATH for media tools.
//! Run with --ignored --test-threads=1 to keep comparison measurements isolated.
use avid_core::{CancellationToken, EventSink, MediaTools, Renderer, Stage};
use encap_core::{AudioSource, Chapter, EpisodeMetadata, ProjectDocument};
use encap_video::{RenderMode, VideoRenderer};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    process::Command,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

struct Harness {
    root: tempfile::TempDir,
    runtime: PathBuf,
    video: VideoRenderer,
}
#[derive(Default)]
struct Events {
    diagnostics: Mutex<Vec<String>>,
    stages: Mutex<Vec<String>>,
}
impl EventSink for Events {
    fn diagnostic(&self, line: &str) {
        self.diagnostics.lock().unwrap().push(line.to_owned());
    }
    fn stage(&self, stage: Stage) {
        self.stages.lock().unwrap().push(stage.as_str().to_owned());
    }
}
impl Harness {
    fn new() -> Self {
        let runtime = PathBuf::from(std::env::var_os("ENCAP_CORE_RUNTIME_DIR").expect(
            "set ENCAP_CORE_RUNTIME_DIR to the authenticated complete pinned Core runtime",
        ));
        let tools =
            MediaTools::from_core_directory(&runtime, &CancellationToken::default()).unwrap();
        Self {
            root: tempfile::tempdir().unwrap(),
            runtime,
            video: VideoRenderer::new(Renderer::new(tools)),
        }
    }
    fn ff(&self, args: &[OsString]) -> Vec<u8> {
        let out = Command::new(self.runtime.join(if cfg!(windows) {
            "ffmpeg.exe"
        } else {
            "ffmpeg"
        }))
        .args(args)
        .output()
        .unwrap();
        assert!(
            out.status.success(),
            "ffmpeg: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        out.stdout
    }
    fn probe(&self, path: &Path, frames: bool) -> Value {
        let mut command = Command::new(self.runtime.join(if cfg!(windows) {
            "ffprobe.exe"
        } else {
            "ffprobe"
        }));
        command.args([
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
        ]);
        if frames {
            command.args(["-select_streams", "v:0", "-show_frames"]);
        }
        let out = command.arg(path).output().unwrap();
        assert!(
            out.status.success(),
            "ffprobe: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        serde_json::from_slice(&out.stdout).unwrap()
    }
    fn decode(&self, path: &Path, audio: bool) -> Vec<u8> {
        let mut args = strings(&["-v", "error", "-i"]);
        args.push(path.into());
        args.extend(strings(if audio {
            &["-map", "0:a:0", "-f", "s16le", "-"]
        } else {
            &["-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        }));
        self.ff(&args)
    }
    fn fixture(&self) -> ProjectDocument {
        let root = self.root.path();
        let main = root.join("主 artwork portrait.png");
        let landscape = root.join("chapter landscape ü.png");
        for (path, size) in [(&main, "64x96"), (&landscape, "128x64")] {
            let mut args = strings(&[
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                &format!("testsrc2=s={size}:rate=1"),
                "-frames:v",
                "1",
            ]);
            args.push(path.into());
            self.ff(&args);
        }
        let mut project = ProjectDocument {
            metadata: EpisodeMetadata {
                artwork_path: Some(main),
                ..Default::default()
            },
            project_path: Some(root.join("project 保存.encap")),
            ..Default::default()
        };
        fs::write(project.project_path.as_ref().unwrap(), b"protected project").unwrap();
        let mut start = 0.0;
        for (index, duration) in [0.375, 0.625, 0.5].into_iter().enumerate() {
            let audio = root.join(format!("音源 {index}.wav"));
            let mut args = strings(&[
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                &format!(
                    "sine=frequency={}:duration=2:sample_rate={}",
                    330 * (index + 1),
                    if index == 1 { 48000 } else { 44100 }
                ),
                "-c:a",
                "pcm_s24le",
            ]);
            args.push(audio.clone().into());
            self.ff(&args);
            project.audio_sources.push(AudioSource {
                source_path: audio,
                display_name: index.to_string(),
                duration_seconds: 2.0,
                stored_path: None,
                extensions: Default::default(),
            });
            project.chapters.push(Chapter {
                id: index.to_string(),
                start_time_seconds: start,
                duration_seconds: duration,
                chapter_number: index as u32 + 1,
                title: format!("章 {index}"),
                link_url: String::new(),
                image_path: (index == 1).then(|| landscape.clone()),
                image_stored_path: None,
                extensions: Default::default(),
            });
            start += duration;
        }
        project.video.export_settings.width = 320;
        project.video.export_settings.height = 180;
        project.video.export_settings.fps = 24;
        project.video.export_settings.encoding = "software".into();
        // The chosen order repeats the fallback image on both sides of an override.
        project.video.export_settings.selected_chapter_ids =
            vec!["2".into(), "1".into(), "0".into()];
        project.video.export_settings.selection_initialized = true;
        project
    }
    fn evidence(&self, name: &str, value: &Value) {
        let directory = std::env::var_os("ENCAP_CORE031_EVIDENCE_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../target/core031")
            });
        fs::create_dir_all(&directory).unwrap();
        fs::write(
            directory.join(name),
            serde_json::to_vec_pretty(value).unwrap(),
        )
        .unwrap();
    }
}
fn strings(values: &[&str]) -> Vec<OsString> {
    values.iter().map(OsString::from).collect()
}

/// Sample aggregate child RSS using OS process information, excluding the sampler
/// itself. This is an observed peak with 25 ms sampling, not an allocation bound.
fn measure<T>(work: impl FnOnce() -> T) -> (T, Value) {
    let done = Arc::new(AtomicBool::new(false));
    let sampler_done = done.clone();
    let sampler = thread::spawn(move || {
        let mut peak = 0u64;
        let mut samples = 0u64;
        while !sampler_done.load(Ordering::Relaxed) {
            if cfg!(unix) {
                if let Ok(out) = Command::new("ps")
                    .args(["-axo", "pid=,ppid=,rss=,comm="])
                    .output()
                {
                    if !out.status.success() {
                        thread::sleep(Duration::from_millis(25));
                        continue;
                    }
                    samples += 1;
                    let text = String::from_utf8_lossy(&out.stdout);
                    let rows = text
                        .lines()
                        .filter_map(|line| {
                            let mut fields = line.split_whitespace();
                            Some((
                                fields.next()?.parse::<u32>().ok()?,
                                fields.next()?.parse::<u32>().ok()?,
                                fields.next()?.parse::<u64>().ok()?,
                                fields.next()?.to_owned(),
                            ))
                        })
                        .collect::<Vec<_>>();
                    let mut descendants = vec![std::process::id()];
                    loop {
                        let before = descendants.len();
                        for (pid, parent, _, _) in &rows {
                            if descendants.contains(parent) && !descendants.contains(pid) {
                                descendants.push(*pid);
                            }
                        }
                        if descendants.len() == before {
                            break;
                        }
                    }
                    let rss = rows
                        .iter()
                        .filter(|(pid, _, _, name)| {
                            *pid != std::process::id()
                                && descendants.contains(pid)
                                && !name.ends_with("/ps")
                                && name != "ps"
                        })
                        .map(|(_, _, rss, _)| *rss)
                        .sum();
                    peak = peak.max(rss);
                }
            }
            thread::sleep(Duration::from_millis(25));
        }
        (peak, samples)
    });
    let start = Instant::now();
    let value = work();
    let seconds = start.elapsed().as_secs_f64();
    done.store(true, Ordering::Relaxed);
    let (peak, samples) = sampler.join().unwrap();
    (
        value,
        json!({"wall_seconds":seconds,"sampled_peak_child_rss_kib":(samples > 0).then_some(peak),"rss_sample_count":samples,"rss_sample_interval_ms":25}),
    )
}

#[test]
#[ignore = "native media; requires the exact authenticated complete Core runtime"]
fn static_modes_match_appearance_audio_cadence_duration_and_record_cost() {
    let h = Harness::new();
    let mut project = h.fixture();
    let source_snapshots = project
        .audio_sources
        .iter()
        .map(|source| {
            (
                source.source_path.clone(),
                fs::read(&source.source_path).unwrap(),
            )
        })
        .collect::<Vec<_>>();
    let mut results = vec![];
    let mut failures = vec![];
    for (codec, width, height, horizontal, vertical) in [
        ("h264", 320, 180, false, false),
        ("h264", 180, 360, true, false),
        ("h264", 320, 180, false, true),
        ("h264", 180, 360, true, true),
        ("hevc", 320, 180, false, false),
        ("h264", 180, 320, false, false),
    ] {
        project.video.export_settings.codec = codec.into();
        project.video.export_settings.width = width;
        project.video.export_settings.height = height;
        project.video.export_settings.flip_horizontal = horizontal;
        project.video.export_settings.flip_vertical = vertical;
        let mut outputs = vec![];
        let mut measurements = vec![];
        for mode in [RenderMode::PerFrame, RenderMode::Simple] {
            let output = h.root.path().join(format!(
                "{codec}-{width}-{horizontal}-{vertical}-{mode:?}.mp4"
            ));
            fs::write(&output, b"previous destination").unwrap();
            let events = Events::default();
            let (result, cost) = measure(|| {
                h.video.export_with_events(
                    &project,
                    &output,
                    Some(mode),
                    &CancellationToken::default(),
                    &events,
                )
            });
            if let Err(error) = result {
                assert_eq!(fs::read(&output).unwrap(), b"previous destination");
                let diagnostics = events.diagnostics.lock().unwrap();
                let failure = json!({"codec":codec,"width":width,"height":height,"mode":format!("{mode:?}"),"error":error.to_string(),"diagnostics":*diagnostics,"stages":*events.stages.lock().unwrap(),"existing_destination_preserved":true});
                eprintln!("native case failed: {failure}");
                failures.push(failure);
                h.evidence(
                    "native-render-failures.json",
                    &json!({"coverage":"native pinned runtime", "failures":failures}),
                );
                continue;
            }
            assert_eq!(events.stages.lock().unwrap().last().unwrap(), "complete");
            let probe = h.probe(&output, true);
            let stream = &probe["streams"][0];
            assert_eq!(stream["codec_name"], codec);
            assert_eq!(
                stream["codec_tag_string"],
                if codec == "hevc" { "hvc1" } else { "avc1" }
            );
            assert_eq!(stream["width"], width);
            assert_eq!(stream["height"], height);
            assert_eq!(stream["r_frame_rate"], "24/1");
            let duration = probe["format"]["duration"]
                .as_str()
                .unwrap()
                .parse::<f64>()
                .unwrap();
            assert!((duration - 1.5).abs() < 0.1, "duration {duration}");
            let audio_probe = h.probe(&output, false);
            let audio = audio_probe["streams"]
                .as_array()
                .unwrap()
                .iter()
                .find(|stream| stream["codec_type"] == "audio")
                .unwrap();
            assert_eq!(audio["sample_rate"], "48000");
            assert_eq!(audio["channels"], 2);
            let timestamps = probe["frames"]
                .as_array()
                .unwrap()
                .iter()
                .map(|frame| frame["best_effort_timestamp_time"].clone())
                .collect::<Vec<_>>();
            assert!(timestamps.len() >= 35);
            measurements.push(json!({"mode":format!("{mode:?}"),"cost":cost,"duration_seconds":duration,"frame_count":timestamps.len(),"timestamps":timestamps}));
            outputs.push(output);
        }
        if outputs.len() != 2 {
            continue;
        }
        let per_frame = h.decode(&outputs[0], false);
        let simple = h.decode(&outputs[1], false);
        assert_eq!(per_frame.len(), simple.len(), "frame counts differ");
        let total_delta = per_frame
            .iter()
            .zip(&simple)
            .map(|(a, b)| a.abs_diff(*b) as u64)
            .sum::<u64>();
        let mean_delta = total_delta as f64 / per_frame.len() as f64;
        assert!(mean_delta <= 0.1, "decoded RGB mean delta {mean_delta}");
        let audio_equal = h.decode(&outputs[0], true) == h.decode(&outputs[1], true);
        assert!(audio_equal, "decoded PCM differs between modes");
        assert_eq!(measurements[0]["timestamps"], measurements[1]["timestamps"]);
        results.push(json!({"codec":codec,"width":width,"height":height,"flip_horizontal":horizontal,"flip_vertical":vertical,"decoded_rgb_mean_absolute_delta":mean_delta,"decoded_pcm_identical":audio_equal,"measurements":measurements}));
        h.evidence("native-mode-comparison.json", &json!({"coverage":"native EnCAP VideoRenderer with authenticated pinned macOS arm64 runtime", "core_revision":encap_core::CORE_REVISION,"runtime_directory":h.runtime,"cases":results}));
    }
    for (path, contents) in source_snapshots {
        assert_eq!(fs::read(path).unwrap(), contents);
    }
    assert!(
        failures.is_empty(),
        "{} native mode cases failed; see native-render-failures.json",
        failures.len()
    );
}

#[test]
#[ignore = "native media; requires the exact authenticated complete Core runtime"]
fn previews_cache_changes_failures_and_independent_cancellation_preserve_destinations() {
    let h = Harness::new();
    let project = h.fixture();
    let token = CancellationToken::default();
    let image = project.metadata.artwork_path.as_ref().unwrap();
    assert_eq!(h.video.inspect_image(image, &token).unwrap(), (64, 96));
    assert_eq!(h.video.inspect_image(image, &token).unwrap(), (64, 96));
    let preview = h.root.path().join("preview.png");
    h.video.preview(&project, &preview, None, &token).unwrap();
    let before = fs::read(&preview).unwrap();
    let mut args = strings(&[
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=purple:s=48x72",
        "-frames:v",
        "1",
    ]);
    args.push(image.into());
    h.ff(&args);
    assert_eq!(h.video.inspect_image(image, &token).unwrap(), (48, 72));
    h.video.preview(&project, &preview, None, &token).unwrap();
    assert_ne!(fs::read(&preview).unwrap(), before);
    let cancelled = CancellationToken::default();
    cancelled.cancel();
    let existing = fs::read(&preview).unwrap();
    assert!(h
        .video
        .preview(&project, &preview, None, &cancelled)
        .is_err());
    assert_eq!(fs::read(&preview).unwrap(), existing);
    let corrupt = h.root.path().join("corrupt.png");
    fs::write(&corrupt, b"invalid image").unwrap();
    assert!(h.video.inspect_image(&corrupt, &token).is_err());
    let mut bad = project.clone();
    bad.metadata.artwork_path = Some(corrupt);
    assert!(h.video.preview(&bad, &preview, None, &token).is_err());
    assert_eq!(fs::read(&preview).unwrap(), existing);
    let oversized = h.root.path().join("oversized.ppm");
    let mut ppm = b"P6\n40000 1\n255\n".to_vec();
    ppm.extend(vec![0; 40_000 * 3]);
    fs::write(&oversized, ppm).unwrap();
    assert!(h.video.inspect_image(&oversized, &token).is_err());
    let mut large_preview = project.clone();
    large_preview.video.export_settings.width = 4096;
    large_preview.video.export_settings.height = 4096;
    let preview_cancel = CancellationToken::default();
    let preview_worker_token = preview_cancel.clone();
    let preview_worker_video = h.video.clone();
    let preview_worker_path = preview.clone();
    let preview_worker = thread::spawn(move || {
        preview_worker_video.preview(
            &large_preview,
            &preview_worker_path,
            None,
            &preview_worker_token,
        )
    });
    thread::sleep(Duration::from_millis(75));
    preview_cancel.cancel();
    assert!(preview_worker.join().unwrap().is_err());
    assert_eq!(fs::read(&preview).unwrap(), existing);
    let output = h.root.path().join("cancel-preserved.mp4");
    fs::write(&output, b"existing export").unwrap();
    let mut slow = project.clone();
    slow.video.export_settings.width = 1920;
    slow.video.export_settings.height = 1080;
    slow.video.export_settings.fps = 60;
    for chapter in &mut slow.chapters {
        chapter.duration_seconds = 30.0;
    }
    let active = CancellationToken::default();
    let worker_token = active.clone();
    let worker_video = h.video.clone();
    let worker_output = output.clone();
    let worker = thread::spawn(move || {
        worker_video.export_with_mode(&slow, &worker_output, RenderMode::PerFrame, &worker_token)
    });
    thread::sleep(Duration::from_millis(150));
    active.cancel();
    // A separate operation token remains usable while the first worker exits.
    let independent = h.root.path().join("independent-preview.png");
    h.video
        .preview(&project, &independent, None, &CancellationToken::default())
        .unwrap();
    assert!(worker.join().unwrap().is_err());
    assert_eq!(fs::read(&output).unwrap(), b"existing export");
    assert!(independent.is_file());
    for protected in project
        .audio_sources
        .iter()
        .map(|source| &source.source_path)
        .chain(project.project_path.iter())
        .chain(project.metadata.artwork_path.iter())
    {
        assert!(h.video.export(&project, protected, &token).is_err());
    }
    h.evidence("native-lifecycle.json", &json!({"coverage":"native EnCAP VideoRenderer", "repeated_inspection":true,"changed_image_dimensions_and_preview":true,"corrupt_input_preserves_preview":true,"oversized_40000px_source_rejected":true,"preview_precancel_preserves_destination":true,"preview_worker_cancel_after_75ms_preserves_destination":true,"active_render_cancel_preserves_destination":true,"independent_preview_succeeds":true,"protected_project_audio_artwork_rejected":true}));
}

#[test]
#[ignore = "native media comparison; requires the exact authenticated complete Core runtime"]
fn longer_repeated_artwork_records_simple_and_per_frame_time_and_memory() {
    let h = Harness::new();
    let mut project = h.fixture();
    project.video.export_settings.width = 1280;
    project.video.export_settings.height = 720;
    project.video.export_settings.fps = 30;
    project.chapters = (0..6)
        .map(|index| {
            let mut chapter = project.chapters[index % 3].clone();
            chapter.id = format!("repeat-{index}");
            chapter.start_time_seconds = index as f64 * 2.0;
            chapter.duration_seconds = 2.0;
            chapter
        })
        .collect();
    project.video.export_settings.selected_chapter_ids.clear();
    project.video.export_settings.selection_initialized = false;
    let mut measurements = vec![];
    for mode in [RenderMode::PerFrame, RenderMode::Simple] {
        let output = h.root.path().join(format!("long-{mode:?}.mp4"));
        let (result, cost) = measure(|| {
            h.video
                .export_with_mode(&project, &output, mode, &CancellationToken::default())
        });
        result.unwrap();
        let probe = h.probe(&output, true);
        assert_eq!(probe["frames"].as_array().unwrap().len(), 360);
        measurements.push(json!({"mode":format!("{mode:?}"),"cost":cost,"duration_seconds":probe["format"]["duration"],"frame_count":360}));
    }
    h.evidence("native-performance.json", &json!({"coverage":"native EnCAP VideoRenderer; single run per mode; diagnostic measurements only", "settings":{"width":1280,"height":720,"fps":30,"codec":"h264","encoding":"software","chapter_count":6,"seconds":12},"measurements":measurements}));
}

#[test]
#[ignore = "native animated media; requires the exact authenticated complete Core runtime"]
fn mixed_animated_artwork_automatic_matches_per_frame_semantics() {
    let h = Harness::new();
    let mut project = h.fixture();
    let gif = h.root.path().join("animated 二色.gif");
    // GIF89a with a red and a blue frame, 200 ms each and infinite looping.
    let mut bytes = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\x00\x00\x00\x00\xff".to_vec();
    bytes.extend(b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00");
    for encoded_pixel in [0x44, 0x4c] {
        bytes.extend(
            b"\x21\xf9\x04\x00\x14\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02",
        );
        bytes.extend([encoded_pixel, 0x01, 0x00]);
    }
    bytes.push(0x3b);
    fs::write(&gif, bytes).unwrap();
    assert_eq!(h.probe(&gif, true)["frames"].as_array().unwrap().len(), 2);
    project.chapters[1].image_path = Some(gif);
    let mut outputs = vec![];
    let mut observations = vec![];
    for mode in [None, Some(RenderMode::PerFrame)] {
        let events = Events::default();
        let output = h.root.path().join(format!("animated-{mode:?}.mp4"));
        fs::write(&output, b"previous animated destination").unwrap();
        let result = h.video.export_with_events(
            &project,
            &output,
            mode,
            &CancellationToken::default(),
            &events,
        );
        if result.is_err() {
            assert_eq!(fs::read(&output).unwrap(), b"previous animated destination");
        }
        observations.push(json!({"mode":format!("{mode:?}"),"success":result.is_ok(),"error":result.as_ref().err().map(ToString::to_string),"diagnostics":*events.diagnostics.lock().unwrap(),"stages":*events.stages.lock().unwrap(),"existing_destination_preserved_on_failure":true}));
        if result.is_ok() {
            outputs.push(output);
        }
    }
    h.evidence(
        "native-animation.json",
        &json!({"coverage":"native mixed GIF and PNG EnCAP timeline", "observations":observations}),
    );
    assert_eq!(
        outputs.len(),
        2,
        "native animated exports failed; see native-animation.json"
    );
    let automatic = h.decode(&outputs[0], false);
    assert_eq!(automatic, h.decode(&outputs[1], false));
    let frame_size = 320 * 180 * 3;
    let frames = automatic.chunks_exact(frame_size).collect::<Vec<_>>();
    // Selected clip 2 runs from 0.5 to 1.125 seconds. It must show both GIF colors.
    assert!(
        frames[14..26].windows(2).any(|pair| pair[0] != pair[1]),
        "animated chapter froze"
    );
}
