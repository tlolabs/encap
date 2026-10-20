//! Injected-process protocol coverage; native media lives in core031_native.
#![cfg(unix)]
use serde_json::{json, Value};
use std::{fs, os::unix::fs::PermissionsExt, path::Path, process::Command};

fn executable(path: &Path, body: &str) {
    fs::write(path, format!("#!/bin/sh\n{body}\n")).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
}

#[test]
fn inspection_preview_and_comparison_preserve_the_json_protocol_and_sources() {
    let root = tempfile::tempdir().unwrap();
    let ffmpeg = root.path().join("ffmpeg");
    let ffprobe = root.path().join("ffprobe");
    executable(&ffmpeg, "if [ \"$1\" = -version ]; then echo 'ffmpeg version 9.0.1'; exit; fi\nif [ \"$2\" = -encoders ]; then echo ' V..... libx264 software'; exit; fi\nfor last do :; done\nprintf composed > \"$last\"");
    executable(
        &ffprobe,
        "if [ \"$1\" = -version ]; then echo 'ffprobe version 9.0.1'; else echo 100x200; fi",
    );
    let image = root.path().join("封面.png");
    let audio = root.path().join("audio.wav");
    let archive = root.path().join("saved.encap");
    fs::write(&image, b"fake image").unwrap();
    fs::write(&audio, b"fake audio").unwrap();
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
            .env("ENCAP_FFMPEG", &ffmpeg)
            .env("ENCAP_FFPROBE", &ffprobe)
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
        json!({"width":100,"height":200})
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
    assert_eq!(fs::read(&preview).unwrap(), b"composed");
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
    assert_eq!(fs::read(&preview).unwrap(), b"composed");
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
    assert_eq!(fs::read(&image).unwrap(), b"fake image");
    assert_eq!(fs::read(&audio).unwrap(), b"fake audio");
}
