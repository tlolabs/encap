use serde_json::Value;
use std::process::Command;

#[test]
fn normal_engine_reports_the_resolved_core_pin_without_media_tools() {
    let output = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("build-info")
        .env("PATH", "")
        .env("ENCAP_FFMPEG", "/missing")
        .env("ENCAP_FFPROBE", "/missing")
        .output()
        .unwrap();
    assert!(output.status.success());
    let identity: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(identity["encap_version"], env!("CARGO_PKG_VERSION"));
    assert_eq!(identity["avid_core"]["version"], encap_core::CORE_VERSION);
    assert_eq!(identity["avid_core"]["revision"], encap_core::CORE_REVISION);
    assert_eq!(identity["avid_core"]["source"], encap_core::CORE_SOURCE);
    assert_eq!(encap_core::CORE_REVISION.len(), 40);
}

#[test]
fn engine_startup_probe_returns_providers_presets_and_recovery() {
    let temp = tempfile::tempdir().unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("startup")
        .env("ENCAP_RECOVERY_PATH", temp.path().join("recovery.json"))
        .output()
        .unwrap();
    assert!(output.status.success());
    let init: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(init["providers"].is_array());
    assert!(init["presets"].is_array());
    assert!(!init["presets"].as_array().unwrap().is_empty());
    assert!(init["recovery"].is_object());
}

#[test]
fn startup_matches_legacy_commands_and_preserves_recovery_errors() {
    let root = tempfile::tempdir().unwrap();
    let recovery = root.path().join("recovery.json");
    let run = |command: &str| {
        Command::new(env!("CARGO_BIN_EXE_encap-engine"))
            .arg(command)
            .env("ENCAP_RECOVERY_PATH", &recovery)
            .output()
            .unwrap()
    };
    let startup: Value = serde_json::from_slice(&run("startup").stdout).unwrap();
    for (field, command) in [
        ("providers", "providers"),
        ("presets", "video-presets"),
        ("recovery", "load-recovery"),
    ] {
        let output = run(command);
        assert!(output.status.success());
        assert_eq!(
            startup[field],
            serde_json::from_slice::<Value>(&output.stdout).unwrap()
        );
    }
    let media = root.path().join("audio.wav");
    std::fs::write(&media, b"referenced media").unwrap();
    let mut project = encap_core::ProjectDocument::default();
    project.audio_sources.push(encap_core::AudioSource {
        source_path: media,
        display_name: "音声".into(),
        duration_seconds: 1.0,
        stored_path: None,
        extensions: Default::default(),
    });
    let payload = root.path().join("payload.json");
    std::fs::write(&payload, serde_json::to_vec(&project).unwrap()).unwrap();
    assert!(Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("save-recovery")
        .arg(&payload)
        .env("ENCAP_RECOVERY_PATH", &recovery)
        .output()
        .unwrap()
        .status
        .success());
    let recovered: Value = serde_json::from_slice(&run("startup").stdout).unwrap();
    let legacy: Value = serde_json::from_slice(&run("load-recovery").stdout).unwrap();
    assert_eq!(recovered["recovery"], legacy);
    assert!(legacy["project"].is_object());
    std::fs::write(&recovery, b"invalid recovery").unwrap();
    let unified = run("startup");
    let legacy = run("load-recovery");
    assert!(!unified.status.success());
    assert!(!legacy.status.success());
    assert_eq!(
        serde_json::from_slice::<Value>(&unified.stdout).unwrap(),
        serde_json::from_slice::<Value>(&legacy.stdout).unwrap()
    );
    assert_eq!(std::fs::read(&recovery).unwrap(), b"invalid recovery");
}
