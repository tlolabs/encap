use encap_core::{load_project, ProjectDocument};
use serde_json::json;
use std::{fs, path::Path, process::Command};

fn engine(args: &[&Path], command: &str) -> std::process::Output {
    Command::new(
        std::env::var_os("ENCAP_TEST_ENGINE")
            .unwrap_or_else(|| env!("CARGO_BIN_EXE_encap-engine").into()),
    )
    .arg(command)
    .args(args)
    .output()
    .unwrap()
}

fn wave(path: &Path, seconds: u32) {
    let length = seconds * 2;
    let mut bytes = b"RIFF".to_vec();
    bytes.extend((36 + length).to_le_bytes());
    bytes.extend(b"WAVEfmt ");
    bytes.extend(16u32.to_le_bytes());
    bytes.extend(1u16.to_le_bytes());
    bytes.extend(1u16.to_le_bytes());
    bytes.extend(1u32.to_le_bytes());
    bytes.extend(2u32.to_le_bytes());
    bytes.extend(2u16.to_le_bytes());
    bytes.extend(16u16.to_le_bytes());
    bytes.extend(b"data");
    bytes.extend(length.to_le_bytes());
    bytes.resize(bytes.len() + length as usize, 0);
    fs::write(path, bytes).unwrap();
}

#[test]
fn add_remove_and_save_reopen_keep_sources_and_chapters_in_sync() {
    let temp = tempfile::tempdir().unwrap();
    let first = temp.path().join("first.wav");
    let second = temp.path().join("second.wav");
    let third = temp.path().join("third.wav");
    wave(&first, 10);
    wave(&second, 20);
    wave(&third, 30);
    let inspected = engine(&[&first, &second], "inspect-files");
    assert!(inspected.status.success());
    let mut project: ProjectDocument = serde_json::from_slice(&inspected.stdout).unwrap();
    project.chapters[0].title = "Chapter 1".into();
    project.chapters[1].title = "Chapter 2".into();
    let payload = temp.path().join("project.json");
    let edits = temp.path().join("edits.json");
    fs::write(&payload, serde_json::to_vec(&project).unwrap()).unwrap();
    fs::write(
        &edits,
        serde_json::to_vec(&json!({"remove_files":[first],"add_files":[third,third,second]}))
            .unwrap(),
    )
    .unwrap();
    let changed = engine(&[&payload, &edits], "edit-audio");
    assert!(
        changed.status.success(),
        "{}",
        String::from_utf8_lossy(&changed.stdout)
    );
    let result: ProjectDocument = serde_json::from_slice(&changed.stdout).unwrap();
    assert_eq!(result.audio_sources.len(), 2);
    assert_eq!(result.audio_sources[0].source_path, second);
    assert_eq!(result.audio_sources[1].source_path, third);
    assert_eq!(result.chapters[0].title, "Chapter 1");
    assert_eq!(result.chapters[1].chapter_number, 2);
    assert_eq!(result.chapters[1].start_time_seconds, 20.0);
    assert!(first.exists());
    assert_eq!(
        fs::read(&payload).unwrap(),
        serde_json::to_vec(&project).unwrap()
    );
    fs::write(&payload, &changed.stdout).unwrap();
    let saved = temp.path().join("triaged.encap");
    assert!(engine(&[&payload, &saved], "save").status.success());
    let reopened = load_project(&saved, Some(temp.path())).unwrap();
    assert_eq!(
        reopened
            .audio_sources
            .iter()
            .map(|s| s.display_name.as_str())
            .collect::<Vec<_>>(),
        ["second", "third"]
    );
    assert_eq!(reopened.chapters, result.chapters);
    assert!(first.exists() && second.exists() && third.exists());

    fs::write(
        &edits,
        serde_json::to_vec(&json!({"add_files":[temp.path().join("missing.wav")]})).unwrap(),
    )
    .unwrap();
    let rejected = engine(&[&payload, &edits], "edit-audio");
    assert!(!rejected.status.success());
    assert_eq!(fs::read(&payload).unwrap(), changed.stdout);
}
