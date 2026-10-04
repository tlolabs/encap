use encap_core::{load_project, AudioSource, ProjectDocument, WorkspaceMode};
use std::{collections::BTreeMap, fs, path::Path, process::Command};

fn save(payload: &Path, destination: &Path) {
    let engine = std::env::var_os("ENCAP_TEST_ENGINE")
        .unwrap_or_else(|| env!("CARGO_BIN_EXE_encap-engine").into());
    let output = Command::new(engine)
        .arg("save")
        .arg(payload)
        .arg(destination)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stdout)
    );
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(response["path"], destination.to_str().unwrap());
}

// Run on every platform. Reports mode-switch save latency with and without
// existing media so regressions are visible in logs. Shared CI hardware
// (especially virtualized/shared Intel macOS runners) has too much timing
// variance for a hard millisecond budget to be a reliable pass/fail gate, so
// no latency assertion is enforced here; see docs/development.md.
#[test]
fn mode_switch_save_latency_does_not_scale_with_existing_media() {
    use std::io::Write;
    use std::time::{Duration, Instant};

    fn add_media(project: &mut ProjectDocument, root: &Path, mib: usize) {
        let source = root.join(format!("source-{mib}.wav"));
        let mut output = fs::File::create(&source).unwrap();
        let mut state = mib as u64;
        let chunk: Vec<u8> = (0..1024 * 1024)
            .map(|_| {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                state as u8
            })
            .collect();
        for _ in 0..mib {
            output.write_all(&chunk).unwrap();
        }
        output.sync_all().unwrap();
        project.audio_sources.push(AudioSource {
            source_path: source,
            display_name: format!("{mib} MiB source"),
            duration_seconds: 1.0,
            stored_path: None,
            extensions: BTreeMap::new(),
        });
    }

    fn switches(
        project: &mut ProjectDocument,
        payload: &Path,
        destination: &Path,
        label: &str,
    ) -> Duration {
        let mut timings = Vec::new();
        for iteration in 0..2 {
            for mode in [
                WorkspaceMode::Transcript,
                WorkspaceMode::Video,
                WorkspaceMode::Audio,
            ] {
                project.active_mode = mode;
                project.metadata.summary = format!("{label}: {mode:?} {iteration}");
                project.transcript_settings.include_word_timestamps = iteration == 0;
                // Editing order also must not turn existing media into new media.
                project.audio_sources.reverse();
                let start = Instant::now();
                fs::write(payload, serde_json::to_vec(project).unwrap()).unwrap();
                save(payload, destination);
                let elapsed = start.elapsed();
                eprintln!("{label}, {mode:?}: {elapsed:?}");
                timings.push(elapsed);
            }
        }
        timings.sort();
        timings[timings.len() / 2]
    }

    let root = tempfile::tempdir().unwrap();
    let payload = root.path().join("payload.json");
    let destination = root.path().join("project.encap");
    let mut project = ProjectDocument::default();
    add_media(&mut project, root.path(), 1);
    let probe = root.path().join("clone-probe");
    let method =
        encap_core::stage_archive_copy(&project.audio_sources[0].source_path, &probe).unwrap();
    fs::remove_file(probe).unwrap();
    let supports_clone = method == encap_core::ArchiveCopyMethod::Clone;
    eprintln!("Project filesystem staging: {method:?}; clone supported: {supports_clone}");
    if std::env::var_os("ENCAP_REQUIRE_CLONING").is_some() {
        assert!(supports_clone, "This test job requires filesystem cloning; refusing to silently test the copy fallback");
    }
    fs::write(&payload, serde_json::to_vec(&project).unwrap()).unwrap();
    save(&payload, &destination); // Initial media ingestion is unmeasured.
    project.project_path = Some(destination.clone());
    let small = switches(&mut project, &payload, &destination, "1 MiB");

    add_media(&mut project, root.path(), 256);
    fs::write(&payload, serde_json::to_vec(&project).unwrap()).unwrap();
    let start = Instant::now();
    save(&payload, &destination); // Exactly this save may do additional media work.
    eprintln!(
        "Save incorporating 256 MiB of new media: {:?}",
        start.elapsed()
    );
    let large = switches(
        &mut project,
        &payload,
        &destination,
        "257 MiB after media addition",
    );

    let mut reopened = load_project(&destination, Some(root.path())).unwrap();
    assert_eq!(reopened.audio_sources.len(), 2);
    for (audio, expected_mib) in reopened.audio_sources.iter_mut().zip([1, 256]) {
        assert_eq!(
            fs::metadata(&audio.source_path).unwrap().len(),
            expected_mib * 1024 * 1024
        );
        audio.stored_path = None; // Match the Swift client's payload.
    }
    let reopened_time = switches(
        &mut reopened,
        &payload,
        &destination,
        "257 MiB after reopen",
    );
    for (label, median) in [
        ("after adding media", large),
        ("after reopening", reopened_time),
    ] {
        eprintln!(
            "Mode switch latency {label}: small-project median {small:?}, this median {median:?}"
        );
    }
    let restored = load_project(&destination, Some(root.path())).unwrap();
    assert_eq!(restored.active_mode, WorkspaceMode::Audio);
    assert_eq!(restored.metadata.summary, reopened.metadata.summary);
}

#[test]
fn mode_saves_across_engine_processes_keep_one_portable_document() {
    let root = tempfile::tempdir().unwrap();
    let source = root.path().join("source.wav");
    fs::write(&source, b"original audio").unwrap();
    let mut project = ProjectDocument::default();
    project.audio_sources.push(AudioSource {
        source_path: source,
        display_name: "Source".into(),
        duration_seconds: 1.0,
        stored_path: None,
        extensions: BTreeMap::new(),
    });
    let payload = root.path().join("payload.json");
    let destination = root.path().join("project.encap");
    for mode in [
        WorkspaceMode::Audio,
        WorkspaceMode::Video,
        WorkspaceMode::Transcript,
    ] {
        project.active_mode = mode;
        fs::write(&payload, serde_json::to_vec(&project).unwrap()).unwrap();
        save(&payload, &destination);
        project.project_path = Some(destination.clone());
    }
    let mut loaded = load_project(&destination, Some(root.path())).unwrap();
    assert_eq!(loaded.active_mode, WorkspaceMode::Transcript);
    loaded.active_mode = WorkspaceMode::Video;
    loaded.metadata.summary = "Edited after reopening".into();
    loaded.audio_sources[0].stored_path = None; // Swift omits runtime archive names.
    fs::write(&payload, serde_json::to_vec(&loaded).unwrap()).unwrap();
    save(&payload, &destination);
    let copy = root.path().join("portable-copy.encap");
    save(&payload, &copy);
    // The copied document is sufficient on its own, even after original input
    // and extraction directories disappear.
    fs::remove_file(&project.audio_sources[0].source_path).unwrap();
    fs::remove_dir_all(loaded.working_dir.unwrap()).unwrap();
    fs::remove_file(destination).unwrap();
    let restored = load_project(&copy, Some(root.path())).unwrap();
    assert_eq!(restored.active_mode, WorkspaceMode::Video);
    assert_eq!(restored.metadata.summary, "Edited after reopening");
    assert_eq!(
        fs::read(&restored.audio_sources[0].source_path).unwrap(),
        b"original audio"
    );
}
