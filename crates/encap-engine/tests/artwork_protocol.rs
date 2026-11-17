//! Real linked protocol coverage with no media executable discovery.
#![cfg(unix)]
use serde_json::{json, Value};
use std::{fs, process::Command};
mod support;

#[test]
fn inspection_preview_and_comparison_preserve_the_json_protocol_and_sources() {
    let root = tempfile::tempdir().unwrap();
    let image = root.path().join("封面.png");
    let audio = root.path().join("audio.wav");
    let archive = root.path().join("saved.encap");
    fs::write(&image, support::OPAQUE_PNG).unwrap();
    support::write_wav(&audio, 1);
    let original_audio = fs::read(&audio).unwrap();
    fs::write(&archive, b"original project").unwrap();
    let payload = root.path().join("payload.json");
    let bytes = serde_json::to_vec(&json!({
        "metadata":{"artwork_path":image}, "project_path":archive,
        "audio_sources":[{"source_path":audio,"duration_seconds":1.0}],
        "chapters":[{"id":"one","chapter_number":1,"start_time_seconds":0.0,"duration_seconds":1.0}],
        "video":{"export_settings":{"width":160,"height":90,"encoding":"software"}}
    })).unwrap();
    fs::write(&payload, &bytes).unwrap();
    let invoke = |args: &[&std::ffi::OsStr], ok: bool| -> Value {
        let out = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
            .args(args)
            .env("PATH", "")
            .env("ENCAP_FFMPEG", "/missing/ffmpeg")
            .env("ENCAP_FFPROBE", "/missing/ffprobe")
            .output()
            .unwrap();
        assert_eq!(
            out.status.success(),
            ok,
            "{}",
            String::from_utf8_lossy(&out.stdout)
        );
        serde_json::from_slice(&out.stdout).expect("one JSON response")
    };
    let s = std::ffi::OsStr::new;
    assert_eq!(
        invoke(&[s("inspect-artwork"), image.as_os_str()], true),
        json!({"width":1,"height":1})
    );
    let preview = root.path().join("preview.png");
    let response = invoke(
        &[
            s("preview-video"),
            payload.as_os_str(),
            preview.as_os_str(),
            s("--chapter-id"),
            s("one"),
        ],
        true,
    );
    assert_eq!(response["path"], preview.to_string_lossy().as_ref());
    let preview_bytes = fs::read(&preview).unwrap();
    assert!(preview_bytes.starts_with(b"\x89PNG\r\n\x1a\n"));
    assert_eq!(
        u32::from_be_bytes(preview_bytes[16..20].try_into().unwrap()),
        160
    );
    assert_eq!(
        u32::from_be_bytes(preview_bytes[20..24].try_into().unwrap()),
        90
    );
    invoke(
        &[
            s("preview-video"),
            payload.as_os_str(),
            preview.as_os_str(),
            s("--chapter-id"),
            s("missing"),
        ],
        false,
    );
    assert_eq!(fs::read(&preview).unwrap(), preview_bytes);
    for mode in ["simple", "per-frame", "automatic"] {
        let output = root.path().join(format!("{mode}.mp4"));
        invoke(
            &[
                s("export-video"),
                payload.as_os_str(),
                output.as_os_str(),
                s("--render-mode"),
                s(mode),
            ],
            true,
        );
        let duration = avid_core::Renderer::new()
            .probe_audio_duration(&output, &avid_core::CancellationToken::default())
            .unwrap()
            .unwrap();
        assert!((duration - 1.0).abs() < 0.1);
        assert!(fs::metadata(&output).unwrap().len() > 100);
    }
    for command in ["preview-video", "export-video"] {
        for output in [&payload, &archive, &image, &audio] {
            invoke(
                &[s(command), payload.as_os_str(), output.as_os_str()],
                false,
            );
        }
    }
    assert_eq!(fs::read(&payload).unwrap(), bytes);
    assert_eq!(fs::read(&archive).unwrap(), b"original project");
    assert_eq!(fs::read(&image).unwrap(), support::OPAQUE_PNG);
    assert_eq!(fs::read(&audio).unwrap(), original_audio);
}
