//! Linked media lifecycle and the explicitly unfinished executable-pair boundary.
#![cfg(unix)]
use serde_json::{json, Value};
use std::{
    fs,
    io::BufRead,
    os::unix::fs::PermissionsExt,
    path::Path,
    process::{Command, Stdio},
    time::{Duration, Instant},
};
mod support;
fn shell(path: &Path, body: &str) {
    fs::write(path, format!("#!/bin/sh\n{body}\n")).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
}

#[test]
fn shared_validation_rejects_partial_mismatched_and_unidentified_pairs() {
    let root = tempfile::tempdir().unwrap();
    let ffmpeg = root.path().join("ffmpeg");
    let ffprobe = root.path().join("ffprobe");
    shell(&ffmpeg, "echo 'ffmpeg version 9.0.2'");
    for identity in ["ffprobe version 9.0.1", "some unrelated executable"] {
        shell(&ffprobe, &format!("echo '{identity}'"));
        {
            let command = "validate-compatibility-tools";
            let out = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
                .arg(command)
                .env("ENCAP_FFMPEG", &ffmpeg)
                .env("ENCAP_FFPROBE", &ffprobe)
                .env("PATH", root.path())
                .output()
                .unwrap();
            assert!(!out.status.success(), "accepted {identity}");
        }
    }
    shell(&ffprobe, "echo 'ffprobe version 9.0.2'");
    for missing in ["ENCAP_FFMPEG", "ENCAP_FFPROBE"] {
        let out = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
            .arg("validate-compatibility-tools")
            .env("ENCAP_FFMPEG", &ffmpeg)
            .env("ENCAP_FFPROBE", &ffprobe)
            .env_remove(missing)
            .env("PATH", root.path())
            .output()
            .unwrap();
        assert!(!out.status.success(), "partial override fell back to PATH");
    }
}

#[test]
fn audio_and_validation_signals_cancel_shared_pair_validation() {
    for mode in ["audio", "validation"] {
        let root = tempfile::tempdir().unwrap();
        let ready = root.path().join("ready");
        let ffmpeg = root.path().join("ffmpeg");
        let ffprobe = root.path().join("ffprobe");
        shell(
            &ffmpeg,
            &format!("echo ready > '{}'; exec /bin/sleep 20", ready.display()),
        );
        shell(&ffprobe, "echo 'ffprobe version 9.0.2'");
        let source = root.path().join("source.wav");
        fs::write(&source, b"source audio").unwrap();
        let payload = root.path().join("payload.json");
        fs::write(&payload, serde_json::to_vec(&json!({
            "metadata": {"podcast_title": "Show", "episode_title": "Episode"},
            "audio_sources": [{"source_path": source, "duration_seconds": 1.0}],
            "chapters": [{"id":"one", "chapter_number":1, "title":"Intro", "start_time_seconds":0.0, "duration_seconds":1.0}]
        })).unwrap()).unwrap();
        let output = root.path().join("out.mp3");
        fs::write(&output, b"old output").unwrap();
        let mut command = Command::new(env!("CARGO_BIN_EXE_encap-engine"));
        if mode == "audio" {
            command.arg("export").arg(&payload).arg(&output);
        } else {
            command.arg("validate-compatibility-tools");
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
        assert!(ready.exists(), "{mode} never validated the pair");
        assert!(Command::new("/bin/kill")
            .args(["-TERM", &child.id().to_string()])
            .status()
            .unwrap()
            .success());
        let result = child.wait_with_output().unwrap();
        assert!(!result.status.success());
        assert!(String::from_utf8_lossy(&result.stdout).contains("cancelled"));
        assert!(start.elapsed() < Duration::from_secs(5));
        assert_eq!(fs::read(&output).unwrap(), b"old output");
        assert_eq!(fs::read(&source).unwrap(), b"source audio");
    }
}

#[test]
fn linked_capabilities_ignore_executable_overrides_while_compatibility_checks_fail() {
    let root = tempfile::tempdir().unwrap();
    let ffmpeg = root.path().join("ffmpeg");
    let ffprobe = root.path().join("ffprobe");
    let marker = root.path().join("executed");
    shell(
        &ffmpeg,
        &format!("echo executed > '{}'; exit 1", marker.display()),
    );
    shell(
        &ffprobe,
        &format!("echo executed > '{}'; exit 1", marker.display()),
    );
    for command in ["validate-tools", "video-capabilities"] {
        let output = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
            .arg(command)
            .env("PATH", root.path())
            .env("ENCAP_FFMPEG", &ffmpeg)
            .env("ENCAP_FFPROBE", &ffprobe)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stdout)
        );
        let result: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert!(result.get("error").is_none());
        assert!(
            !marker.exists(),
            "linked capabilities launched a media executable"
        );
    }
    let output = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("validate-compatibility-tools")
        .env("PATH", root.path())
        .env("ENCAP_FFMPEG", root.path().join("invalid"))
        .env("ENCAP_FFPROBE", root.path().join("invalid"))
        .output()
        .unwrap();
    assert!(!output.status.success());
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(result["error"].as_str().unwrap().contains("bundled"));
}

#[test]
fn signal_cancels_linked_video_and_waits_for_cleanup_preserving_destination() {
    let root = tempfile::tempdir().unwrap();
    let image = root.path().join("image.png");
    let audio = root.path().join("audio.wav");
    let output = root.path().join("movie.mp4");
    let payload = root.path().join("project.json");
    fs::write(&image, support::OPAQUE_PNG).unwrap();
    support::write_wav(&audio, 10);
    fs::write(&output, b"existing movie").unwrap();
    let original_audio = fs::read(&audio).unwrap();
    let project=serde_json::to_vec(&json!({"metadata":{"artwork_path":image},"audio_sources":[{"source_path":audio,"duration_seconds":10.0}],"chapters":[{"id":"one","chapter_number":1,"start_time_seconds":0.0,"duration_seconds":10.0}],"video":{"export_settings":{"width":1920,"height":1080,"fps":60,"encoding":"software"}}})).unwrap();
    fs::write(&payload, &project).unwrap();
    let mut child = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("export-video")
        .arg(&payload)
        .arg(&output)
        .args(["--render-mode", "per-frame"])
        .env("PATH", "")
        .env("ENCAP_FFMPEG", "/must-not-be-used")
        .env("ENCAP_FFPROBE", "/must-not-be-used")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let stderr = child.stderr.take().unwrap();
    let (started, wait) = std::sync::mpsc::channel();
    let reader = std::thread::spawn(move || {
        let mut captured = Vec::new();
        for line in std::io::BufReader::new(stderr).lines() {
            let line = line.unwrap();
            if serde_json::from_str::<Value>(&line)
                .ok()
                .is_some_and(|v| v["event"] == "stage")
            {
                let _ = started.send(());
            }
            captured.push(line);
        }
        captured
    });
    wait.recv_timeout(Duration::from_secs(10))
        .expect("linked render did not emit its first stage");
    assert!(Command::new("/bin/kill")
        .args(["-TERM", &child.id().to_string()])
        .status()
        .unwrap()
        .success());
    let result = child.wait_with_output().unwrap();
    let diagnostics = reader.join().unwrap();
    assert!(
        !result.status.success(),
        "render unexpectedly completed: {diagnostics:?}"
    );
    let result: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert!(result["error"].as_str().unwrap().contains("cancelled"));
    assert_eq!(fs::read(&output).unwrap(), b"existing movie");
    assert_eq!(fs::read(&audio).unwrap(), original_audio);
    assert_eq!(fs::read(&image).unwrap(), support::OPAQUE_PNG);
    assert_eq!(fs::read(&payload).unwrap(), project);
    assert!(!fs::read_dir(root.path()).unwrap().any(|entry| entry
        .unwrap()
        .file_name()
        .to_string_lossy()
        .starts_with(".avid-")));
}

#[test]
fn removed_helper_override_is_never_executed_and_failure_preserves_transcript() {
    let root = tempfile::tempdir().unwrap();
    let marker = root.path().join("executed");
    let helper = root.path().join("avid-transcriber");
    shell(
        &helper,
        &format!("echo helper > '{}'; exit 1", marker.display()),
    );
    let source = root.path().join("audio.wav");
    support::write_wav(&source, 1);
    let payload = root.path().join("project.json");
    let project=serde_json::to_vec(&json!({"audio_sources":[{"source_path":source,"duration_seconds":1.0}],"transcript_segments":[{"id":"edited","text":"Edited transcript","speaker":"Host","start_time_seconds":0.0,"end_time_seconds":1.0}]})).unwrap();
    fs::write(&payload, &project).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("transcribe")
        .arg(&payload)
        .arg("whisper-large-v3")
        .env("ENCAP_AVID_TRANSCRIBER", &helper)
        .env(
            "ENCAP_AVID_TRANSCRIPTION_LIBRARY",
            root.path().join("missing-library"),
        )
        .env("ENCAP_FFMPEG", "/must-not-be-used")
        .env("ENCAP_FFPROBE", "/must-not-be-used")
        .env("PATH", "")
        .output()
        .unwrap();
    assert!(!output.status.success());
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(result["error"].as_str().is_some());
    assert!(!marker.exists());
    assert_eq!(fs::read(&payload).unwrap(), project);
    let output = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("models")
        .env("ENCAP_AVID_TRANSCRIBER", &helper)
        .env(
            "ENCAP_AVID_TRANSCRIPTION_LIBRARY",
            root.path().join("missing-library"),
        )
        .env("PATH", "")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(serde_json::from_slice::<Value>(&output.stdout)
        .unwrap()
        .is_array());
    assert!(!marker.exists());
}
