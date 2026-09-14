//! Explicit release-pair checks. No downloads and no system-tool substitution.
use serde_json::{json, Value};
use std::{
    ffi::OsStr,
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
};

struct Harness {
    root: tempfile::TempDir,
    engine: PathBuf,
    ffmpeg: PathBuf,
    ffprobe: PathBuf,
}
impl Harness {
    fn new() -> Self {
        Self {
            root: tempfile::tempdir().unwrap(),
            engine: std::env::var_os("ENCAP_TEST_ENGINE")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from(env!("CARGO_BIN_EXE_encap-engine"))),
            ffmpeg: std::env::var_os("ENCAP_FFMPEG")
                .expect("set release ffmpeg")
                .into(),
            ffprobe: std::env::var_os("ENCAP_FFPROBE")
                .expect("set release ffprobe")
                .into(),
        }
    }
    fn tool(&self, tool: &Path, args: &[&OsStr]) -> Output {
        let out = Command::new(tool).args(args).output().unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        out
    }
    fn ff(&self, args: &[&OsStr]) -> Vec<u8> {
        self.tool(&self.ffmpeg, args).stdout
    }
    fn engine(&self, args: &[&OsStr], ok: bool) -> Value {
        let out = Command::new(&self.engine)
            .args(args)
            .env("ENCAP_FFMPEG", &self.ffmpeg)
            .env("ENCAP_FFPROBE", &self.ffprobe)
            .env(
                "ENCAP_RECOVERY_PATH",
                self.root.path().join("recovery.json"),
            )
            .output()
            .unwrap();
        assert_eq!(
            out.status.success(),
            ok,
            "{}",
            String::from_utf8_lossy(&out.stdout)
        );
        let value: Value = serde_json::from_slice(&out.stdout).expect("exactly one JSON value");
        assert_eq!(value.get("error").is_none(), ok);
        value
    }
    fn probe(&self, path: &Path) -> Value {
        serde_json::from_slice(
            &self
                .tool(
                    &self.ffprobe,
                    &[
                        s("-v"),
                        s("error"),
                        s("-show_streams"),
                        s("-show_format"),
                        s("-of"),
                        s("json"),
                        path.as_os_str(),
                    ],
                )
                .stdout,
        )
        .unwrap()
    }
    fn write(&self, project: &Value) -> PathBuf {
        let path = self.root.path().join("payload.json");
        fs::write(&path, serde_json::to_vec(project).unwrap()).unwrap();
        path
    }
}
fn s(value: &str) -> &OsStr {
    OsStr::new(value)
}

#[test]
#[ignore = "requires the explicit approved FFmpeg/ffprobe release pair"]
fn release_pair_has_complete_audio_transcript_video_capabilities() {
    let h = Harness::new();
    h.engine(&[s("validate-tools")], true);
    h.engine(&[s("video-capabilities")], true);
    let version = String::from_utf8(h.ff(&[s("-version")])).unwrap();
    let identifier = version.split_whitespace().nth(2).unwrap();
    assert!(
        identifier == "9.0.1"
            || identifier.starts_with("9.0.1-")
            || identifier.starts_with("n9.0.1-")
    );
    for (option, required) in [
        (
            "-encoders",
            vec![
                "libx264",
                "libx265",
                "aac",
                "libmp3lame",
                "png",
                "pcm_s16le",
            ],
        ),
        (
            "-decoders",
            vec![
                "pcm_s16le",
                "pcm_s24le",
                "pcm_s16be",
                "pcm_s24be",
                "png",
                "mjpeg",
            ],
        ),
        (
            "-filters",
            vec![
                "scale",
                "crop",
                "split",
                "gblur",
                "overlay",
                "format",
                "hflip",
                "vflip",
                "pad",
                "trim",
                "setpts",
                "atrim",
                "aformat",
                "asetpts",
                "concat",
                "aresample",
            ],
        ),
    ] {
        let listing = String::from_utf8(h.ff(&[s("-hide_banner"), s(option)])).unwrap();
        let names: Vec<_> = listing
            .lines()
            .filter_map(|line| line.split_whitespace().nth(1))
            .collect();
        for name in required {
            assert!(names.contains(&name), "missing {name}");
        }
        if cfg!(target_os = "macos") && option == "-encoders" {
            assert!(names.contains(&"aac_at"));
        }
    }
}

#[test]
#[ignore = "requires the explicit approved FFmpeg/ffprobe release pair"]
fn whole_engine_media_persistence_recovery_and_reference_contract() {
    let h = Harness::new();
    let audio = h.root.path().join("audio ü");
    fs::create_dir(&audio).unwrap();
    for (name, freq) in [("source 1.wav", "440"), ("source 2.wav", "880")] {
        h.ff(&[
            s("-v"),
            s("error"),
            s("-f"),
            s("lavfi"),
            s("-i"),
            s(&format!(
                "sine=frequency={freq}:duration=1:sample_rate=44100"
            )),
            s("-c:a"),
            s("pcm_s16le"),
            audio.join(name).as_os_str(),
        ]);
    }
    let main = h.root.path().join("main.png");
    let art = h.root.path().join("chapter.png");
    for (path, color) in [(&main, "red"), (&art, "blue")] {
        h.ff(&[
            s("-v"),
            s("error"),
            s("-f"),
            s("lavfi"),
            s("-i"),
            s(&format!("color=c={color}:s=100x100")),
            s("-frames:v"),
            s("1"),
            path.as_os_str(),
        ]);
    }
    let mut project = h.engine(&[s("inspect"), audio.as_os_str()], true);
    project["metadata"]["artwork_path"] = json!(main);
    project["metadata"]["episode_title"] = json!("Contract");
    project["chapters"][1]["image_path"] = json!(art);
    project["transcript_segments"] = json!([{"id":"s", "start_time_seconds":0.0,"end_time_seconds":0.5,"text":"Hello world","speaker":"Host"}]);
    let ids = vec![
        project["chapters"][1]["id"].clone(),
        project["chapters"][0]["id"].clone(),
    ];
    project["video"]["export_settings"] = json!({"width":160,"height":90,"fps":30,"codec":"h264","encoding":"software","selected_chapter_ids":ids,"selection_initialized":true});
    project = serde_json::to_value(
        serde_json::from_value::<encap_core::ProjectDocument>(project).unwrap(),
    )
    .unwrap();
    let original = project.clone();
    let payload = h.write(&project);
    let mut hashes = Vec::new();
    project["chapters"][1]
        .as_object_mut()
        .unwrap()
        .remove("image_path");
    for entry in project["audio_sources"].as_array().unwrap() {
        let path = PathBuf::from(entry["source_path"].as_str().unwrap());
        hashes.push((path.clone(), fs::read(path).unwrap()));
    }
    for (format, encoder, ext) in [("mp3", "lame", "mp3"), ("aac", "ffmpeg", "m4a")] {
        project["export_settings"] =
            json!({"output_format":format,"encoder":encoder,"quality_preset":"192k","channels":2});
        let payload = h.write(&project);
        let output = h.root.path().join(format!("audio.{ext}"));
        h.engine(
            &[s("export"), payload.as_os_str(), output.as_os_str()],
            true,
        );
        assert!(h.probe(&output)["streams"]
            .as_array()
            .unwrap()
            .iter()
            .any(|v| v["codec_name"] == format));
    }
    if cfg!(target_os = "macos") {
        project["export_settings"] = json!({"output_format":"aac","encoder":"audio_toolbox","quality_preset":"192k","channels":2});
        let payload = h.write(&project);
        h.engine(
            &[
                s("export"),
                payload.as_os_str(),
                h.root.path().join("toolbox.m4a").as_os_str(),
            ],
            true,
        );
    }
    project = original.clone();
    h.write(&project);
    for format in ["txt", "srt"] {
        let output = h.root.path().join(format!("transcript.{format}"));
        h.engine(
            &[
                s("export-transcript"),
                payload.as_os_str(),
                output.as_os_str(),
                s(format),
            ],
            true,
        );
        assert!(fs::read_to_string(output).unwrap().contains("Hello world"));
    }
    h.engine(&[s("providers")], true);
    h.engine(
        &[s("transcribe"), payload.as_os_str(), s("invalid-provider")],
        false,
    );
    // Same release pair also supplies Transcript's mono/16 kHz PCM conversion.
    let pcm = h.root.path().join("transcript-input.wav");
    h.ff(&[
        s("-v"),
        s("error"),
        s("-i"),
        s(project["audio_sources"][0]["source_path"].as_str().unwrap()),
        s("-vn"),
        s("-ar"),
        s("16000"),
        s("-ac"),
        s("1"),
        s("-c:a"),
        s("pcm_s16le"),
        pcm.as_os_str(),
    ]);
    let p = h.probe(&pcm);
    assert_eq!(p["streams"][0]["sample_rate"], "16000");
    assert_eq!(p["streams"][0]["channels"], 1);
    for codec in ["h264", "hevc"] {
        project["video"]["export_settings"]["codec"] = json!(codec);
        h.write(&project);
        let output = h.root.path().join(format!("{codec}.mp4"));
        fs::write(&output, b"previous output").unwrap();
        let response = h.engine(
            &[s("export-video"), payload.as_os_str(), output.as_os_str()],
            true,
        );
        assert_eq!(response, json!({"path":output}));
        let p = h.probe(&output);
        let streams = p["streams"].as_array().unwrap();
        let video = streams.iter().find(|v| v["codec_type"] == "video").unwrap();
        let audio = streams.iter().find(|v| v["codec_type"] == "audio").unwrap();
        assert_eq!(video["codec_name"], codec);
        assert_eq!(
            video["codec_tag_string"],
            if codec == "hevc" { "hvc1" } else { "avc1" }
        );
        assert_eq!(audio["codec_name"], "aac");
        assert_eq!(audio["sample_rate"], "48000");
        assert_eq!(audio["channels"], 2);
        let duration = p["format"]["duration"]
            .as_str()
            .unwrap()
            .parse::<f64>()
            .unwrap();
        assert!((duration - 2.0).abs() < 0.12);
        for (second, channel) in [("0.5", 2), ("1.5", 0)] {
            let pixel = h.ff(&[
                s("-v"),
                s("error"),
                s("-ss"),
                s(second),
                s("-i"),
                output.as_os_str(),
                s("-frames:v"),
                s("1"),
                s("-vf"),
                s("scale=1:1"),
                s("-f"),
                s("rawvideo"),
                s("-pix_fmt"),
                s("rgb24"),
                s("-"),
            ]);
            assert!(pixel[channel] > 150 && pixel[(channel + 1) % 3] < 80);
        }
        if codec == "h264" {
            if let Some(reference) = std::env::var_os("ENCAP_REFERENCE_ENGINE") {
                let baseline = h.root.path().join("baseline.mp4");
                let status = Command::new(reference)
                    .args([s("export-video"), payload.as_os_str(), baseline.as_os_str()])
                    .env("ENCAP_FFMPEG", &h.ffmpeg)
                    .env("ENCAP_FFPROBE", &h.ffprobe)
                    .output()
                    .unwrap();
                assert!(
                    status.status.success(),
                    "{}",
                    String::from_utf8_lossy(&status.stdout)
                );
                for (map, format, extra) in [("0:v:0", "rawvideo", "rgb24"), ("0:a:0", "s16le", "")]
                {
                    let decoded = |path: &Path| {
                        let mut args = vec![
                            s("-v"),
                            s("error"),
                            s("-i"),
                            path.as_os_str(),
                            s("-map"),
                            s(map),
                            s("-f"),
                            s(format),
                        ];
                        if !extra.is_empty() {
                            args.extend([s("-pix_fmt"), s(extra)]);
                        }
                        args.push(s("-"));
                        h.ff(&args)
                    };
                    assert_eq!(decoded(&output), decoded(&baseline));
                }
                let presets = Command::new(std::env::var_os("ENCAP_REFERENCE_ENGINE").unwrap())
                    .arg("video-presets")
                    .output()
                    .unwrap();
                assert_eq!(
                    serde_json::from_slice::<Value>(&presets.stdout).unwrap(),
                    h.engine(&[s("video-presets")], true)
                );
            }
        }
    }
    let saved = h.root.path().join("project.encap");
    h.engine(&[s("save"), payload.as_os_str(), saved.as_os_str()], true);
    let reopened = h.engine(
        &[
            s("open"),
            saved.as_os_str(),
            s("--extraction-parent"),
            h.root.path().as_os_str(),
        ],
        true,
    );
    assert_eq!(reopened["video"], project["video"]);
    assert_eq!(reopened["chapters"][0]["id"], original["chapters"][0]["id"]);
    h.engine(&[s("save-recovery"), payload.as_os_str()], true);
    assert_eq!(
        h.engine(&[s("load-recovery")], true)["project"]["video"],
        project["video"]
    );
    h.engine(&[s("clear-recovery")], true);
    let output = h.root.path().join("preserved.mp4");
    fs::write(&output, b"old").unwrap();
    project["video"]["export_settings"]["selected_chapter_ids"] = json!([]);
    h.write(&project);
    h.engine(
        &[s("export-video"), payload.as_os_str(), output.as_os_str()],
        false,
    );
    assert_eq!(fs::read(&output).unwrap(), b"old");
    for (path, bytes) in hashes {
        assert_eq!(fs::read(path).unwrap(), bytes);
    }
    assert!(!fs::read_dir(h.root.path()).unwrap().any(|e| e
        .unwrap()
        .file_name()
        .to_string_lossy()
        .starts_with(".avid-")));
}

#[test]
#[ignore = "requires the explicit approved FFmpeg/ffprobe release pair"]
fn artwork_flips_and_real_media_failures_preserve_sources() {
    let h = Harness::new();
    let audio = h.root.path().join("audio");
    fs::create_dir(&audio).unwrap();
    let source = audio.join("one.wav");
    h.ff(&[
        s("-v"),
        s("error"),
        s("-f"),
        s("lavfi"),
        s("-i"),
        s("sine=duration=1"),
        source.as_os_str(),
    ]);
    let image = h.root.path().join("quadrants.ppm");
    let colors = [[255u8, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0]];
    let mut ppm = b"P6\n160 160\n255\n".to_vec();
    for y in 0..160 {
        for x in 0..160 {
            ppm.extend(colors[usize::from(x >= 80) + 2 * usize::from(y >= 80)]);
        }
    }
    fs::write(&image, &ppm).unwrap();
    let mut project = h.engine(&[s("inspect"), audio.as_os_str()], true);
    project["metadata"]["artwork_path"] = json!(image);
    project["video"]["export_settings"]["width"] = json!(160);
    project["video"]["export_settings"]["height"] = json!(160);
    project["video"]["export_settings"]["encoding"] = json!("software");
    for horizontal in [false, true] {
        for vertical in [false, true] {
            project["video"]["export_settings"]["flip_horizontal"] = json!(horizontal);
            project["video"]["export_settings"]["flip_vertical"] = json!(vertical);
            let payload = h.write(&project);
            let output = h.root.path().join("flip.mp4");
            h.engine(
                &[s("export-video"), payload.as_os_str(), output.as_os_str()],
                true,
            );
            let pixels = h.ff(&[
                s("-v"),
                s("error"),
                s("-ss"),
                s("0.3"),
                s("-i"),
                output.as_os_str(),
                s("-frames:v"),
                s("1"),
                s("-f"),
                s("rawvideo"),
                s("-pix_fmt"),
                s("rgb24"),
                s("-"),
            ]);
            for (x, y) in [(20, 20), (140, 20), (20, 140), (140, 140)] {
                let expected = colors
                    [usize::from((x >= 80) ^ horizontal) + 2 * usize::from((y >= 80) ^ vertical)];
                for channel in 0..3 {
                    let actual = pixels[(y * 160 + x) * 3 + channel];
                    assert!(
                        (i16::from(actual) - i16::from(expected[channel])).abs() < 20,
                        "flip {horizontal}/{vertical} at {x},{y}"
                    );
                }
            }
        }
    }
    let output = h.root.path().join("old.mp4");
    fs::write(&output, b"old").unwrap();
    let source_bytes = fs::read(&source).unwrap();
    for (field, value) in [
        ("fps", json!(121)),
        ("width", json!(3)),
        ("audio_bitrate", json!("bad")),
    ] {
        let mut bad = project.clone();
        bad["video"]["export_settings"][field] = value;
        h.engine(
            &[
                s("export-video"),
                h.write(&bad).as_os_str(),
                output.as_os_str(),
            ],
            false,
        );
        assert_eq!(fs::read(&output).unwrap(), b"old");
    }
    for missing in [false, true] {
        let invalid = h.root.path().join("invalid.png");
        if !missing {
            fs::write(&invalid, b"corrupt").unwrap();
        } else {
            fs::remove_file(&invalid).unwrap();
        }
        let mut bad = project.clone();
        bad["metadata"]["artwork_path"] = json!(invalid);
        // A selected valid chapter override must not bypass the corrupt main image.
        bad["chapters"][0]["image_path"] = json!(image);
        h.engine(
            &[
                s("export-video"),
                h.write(&bad).as_os_str(),
                output.as_os_str(),
            ],
            false,
        );
        assert_eq!(fs::read(&output).unwrap(), b"old");
    }
    let corrupt = h.root.path().join("corrupt.wav");
    fs::write(&corrupt, b"corrupt").unwrap();
    for path in [&corrupt, &h.root.path().join("missing.wav")] {
        let mut bad = project.clone();
        bad["audio_sources"][0]["source_path"] = json!(path);
        h.engine(
            &[
                s("export-video"),
                h.write(&bad).as_os_str(),
                output.as_os_str(),
            ],
            false,
        );
        assert_eq!(fs::read(&output).unwrap(), b"old");
    }
    assert_eq!(fs::read(&source).unwrap(), source_bytes);
    assert_eq!(fs::read(&image).unwrap(), ppm);
    assert!(!fs::read_dir(h.root.path()).unwrap().any(|e| e
        .unwrap()
        .file_name()
        .to_string_lossy()
        .starts_with(".avid-")));
}
