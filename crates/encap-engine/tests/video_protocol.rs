#![cfg(unix)]
use serde_json::{json, Value};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::Path,
    process::{Command, Stdio},
    time::{Duration, Instant},
};
fn shell(path: &Path, body: &str) {
    fs::write(path, format!("#!/bin/sh\n{body}\n")).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
}

#[test]
fn host_resolution_invalid_override_fallback_and_pair_identity() {
    let root = tempfile::tempdir().unwrap();
    shell(&root.path().join("ffmpeg"),"if [ \"$1\" = -version ]; then echo 'ffmpeg version 9.0.1'; else echo ' V..... libx264 software'; fi");
    shell(&root.path().join("ffprobe"), "echo 'ffprobe version 9.0.1'");
    let invoke = |command: &str| {
        Command::new(env!("CARGO_BIN_EXE_encap-engine"))
            .arg(command)
            .env("PATH", root.path())
            .env("ENCAP_FFMPEG", root.path().join("invalid"))
            .env("ENCAP_FFPROBE", root.path().join("invalid"))
            .output()
            .unwrap()
    };
    for command in ["validate-tools", "video-capabilities"] {
        let out = invoke(command);
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stdout)
        );
        let _: Value = serde_json::from_slice(&out.stdout).unwrap();
    }
    shell(&root.path().join("ffprobe"), "echo 'ffprobe version 8.0'");
    let out = invoke("video-capabilities");
    assert!(!out.status.success());
    let error: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert!(error["error"].as_str().unwrap().contains("matching"));
    assert!(!error["error"]
        .as_str()
        .unwrap()
        .contains(root.path().to_str().unwrap()));
}

#[test]
fn one_signal_handler_cancels_video_validation_capabilities_probes_and_encoding() {
    for stage in ["validation", "capabilities", "probe", "encoding"] {
        let root = tempfile::tempdir().unwrap();
        let ready = root.path().join("ready");
        let sleep = format!("echo ready > '{}'; exec /bin/sleep 20", ready.display());
        let ffmpeg = root.path().join("ffmpeg");
        let ffprobe = root.path().join("ffprobe");
        shell(&ffmpeg,&format!("if [ \"$1\" = -version ]; then {}; echo 'ffmpeg version 9.0.1'; exit; fi\nif [ \"$2\" = -encoders ]; then {}; echo ' V..... libx264 software'; exit; fi\nfor last do :; done\nprintf partial > \"$last\"\n{}",if stage=="validation" {&sleep} else {":"},if stage=="capabilities" {&sleep} else {":"},if stage=="encoding" {&sleep} else {":"}));
        shell(&ffprobe,&format!("if [ \"$1\" = -version ]; then echo 'ffprobe version 9.0.1'; exit; fi\n{}\necho 100x100",if stage=="probe" {&sleep} else {":"}));
        let image = root.path().join("cover.png");
        let audio = root.path().join("source.wav");
        let output = root.path().join("out.mp4");
        fs::write(&image, b"image").unwrap();
        fs::write(&audio, b"audio").unwrap();
        fs::write(&output, b"old").unwrap();
        let payload = root.path().join("payload.json");
        fs::write(&payload,serde_json::to_vec(&json!({"metadata":{"artwork_path":image},"audio_sources":[{"source_path":audio,"duration_seconds":1.0}],"chapters":[{"id":"one","chapter_number":1,"start_time_seconds":0.0,"duration_seconds":1.0}],"video":{"export_settings":{"width":160,"height":90,"encoding":"software"}}})).unwrap()).unwrap();
        let mut command = Command::new(env!("CARGO_BIN_EXE_encap-engine"));
        if stage == "validation" || stage == "capabilities" {
            command.arg("video-capabilities");
        } else {
            command.arg("export-video").arg(&payload).arg(&output);
        }
        let child = command
            .env("ENCAP_FFMPEG", &ffmpeg)
            .env("ENCAP_FFPROBE", &ffprobe)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let start = Instant::now();
        while !ready.exists() && start.elapsed() < Duration::from_secs(5) {
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(ready.exists(), "{stage} never started");
        assert!(Command::new("/bin/kill")
            .args(["-TERM", &child.id().to_string()])
            .status()
            .unwrap()
            .success());
        let out = child.wait_with_output().unwrap();
        assert!(!out.status.success());
        assert!(start.elapsed() < Duration::from_secs(5));
        let error: Value = serde_json::from_slice(&out.stdout).unwrap();
        assert!(error["error"].as_str().unwrap().contains("cancelled"));
        assert_eq!(fs::read(&output).unwrap(), b"old");
        assert_eq!(fs::read(&audio).unwrap(), b"audio");
        assert_eq!(fs::read(&image).unwrap(), b"image");
        assert!(!fs::read_dir(root.path()).unwrap().any(|e| e
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".avid-")));
    }
}
