//! The saved-segment export uses Core's helper without word-caption regrouping.
#![cfg(unix)]
use serde_json::{json, Value};
use std::{fs, os::unix::fs::PermissionsExt, path::Path, process::Command};

fn invoke(payload: &Path, output: &Path, helper: &Path, format: &str, ok: bool) {
    let response = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("export-transcript")
        .arg(payload)
        .arg(output)
        .arg(format)
        .env("ENCAP_AVID_TRANSCRIBER", helper)
        .output()
        .unwrap();
    assert_eq!(
        response.status.success(),
        ok,
        "{}",
        String::from_utf8_lossy(&response.stdout)
    );
    let value: Value = serde_json::from_slice(&response.stdout).expect("one JSON response");
    assert_eq!(value.get("error").is_none(), ok);
}

#[test]
fn segment_subtitle_exports_route_formats_and_preserve_output_on_core_failure() {
    let root = tempfile::tempdir().unwrap();
    let payload = root.path().join("episode.json");
    let helper = root.path().join("avid-transcriber");
    let source = serde_json::to_vec(&json!({"transcript_segments": [{
        "id":"one", "start_time_seconds":0.0, "end_time_seconds":1.0,
        "speaker":"Host", "text":"Original segment", "words":[]
    }]}))
    .unwrap();
    fs::write(&payload, &source).unwrap();
    fs::write(
        &helper,
        r#"#!/bin/sh
[ "$1" = subtitles ] && [ "$2" = --transcript ] && [ -f "$3" ] && [ "$4" = --format ] || exit 2
printf '"Core %s segment cues\\n"\n' "$5"
"#,
    )
    .unwrap();
    fs::set_permissions(&helper, fs::Permissions::from_mode(0o755)).unwrap();
    for format in ["srt", "vtt"] {
        let output = root.path().join(format!("episode.{format}"));
        invoke(&payload, &output, &helper, format, true);
        assert_eq!(
            fs::read_to_string(&output).unwrap(),
            format!("Core {format} segment cues\n")
        );
        // Core errors must preserve the existing output, without selecting the
        // retained writer used on platforms where Core has no exporter.
        let failing = root.path().join("failed-helper");
        fs::write(
            &failing,
            "#!/bin/sh\nprintf '%s\\n' '{\"error\":\"invalid Core cues\"}'\nexit 1\n",
        )
        .unwrap();
        fs::set_permissions(&failing, fs::Permissions::from_mode(0o755)).unwrap();
        invoke(&payload, &output, &failing, format, false);
        assert_eq!(
            fs::read_to_string(&output).unwrap(),
            format!("Core {format} segment cues\n")
        );
        invoke(&payload, &payload, &helper, format, false);
        assert_eq!(fs::read(&payload).unwrap(), source);
    }
}
