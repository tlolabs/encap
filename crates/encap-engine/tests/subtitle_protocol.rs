//! Saved-segment export calls linked Core independently of inference or executables.
#![cfg(unix)]
use serde_json::{json, Value};
use std::{fs, path::Path, process::Command};

fn invoke(payload: &Path, output: &Path, helper: &Path, format: &str, ok: bool) {
    let response = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("export-transcript")
        .arg(payload)
        .arg(output)
        .arg(format)
        .env("ENCAP_AVID_TRANSCRIBER", helper)
        .env("ENCAP_AVID_TRANSCRIPTION_LIBRARY", "/missing/library")
        .env("PATH", "")
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
    for format in ["srt", "vtt"] {
        let output = root.path().join(format!("episode.{format}"));
        invoke(&payload, &output, &helper, format, true);
        let expected = if format == "srt" {
            "1\n00:00:00,000 --> 00:00:01,000\nHost: Original segment\n\n"
        } else {
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHost: Original segment\n\n"
        };
        assert_eq!(fs::read_to_string(&output).unwrap(), expected);
        // Invalid segment bounds fail before publication, independent of model
        // availability and without substituting the old writer/helper.
        let invalid = root.path().join("invalid.json");
        fs::write(
            &invalid,
            serde_json::to_vec(&json!({"transcript_segments":[{
                "id":"one","start_time_seconds":1.0,"end_time_seconds":0.0,"text":"Original segment"
            }]}))
            .unwrap(),
        )
        .unwrap();
        invoke(&invalid, &output, &helper, format, false);
        assert_eq!(fs::read_to_string(&output).unwrap(), expected);
        invoke(&payload, &payload, &helper, format, false);
        assert_eq!(fs::read(&payload).unwrap(), source);
    }
}
