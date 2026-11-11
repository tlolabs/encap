//! Real in-process image optimization and project-source protection through JSON.
use serde_json::{json, Value};
use std::{fs, path::Path, process::Command};

const OPAQUE_PNG: &[u8] = &[
    137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 1, 0, 0, 0, 1, 8, 2, 0,
    0, 0, 144, 119, 83, 222, 0, 0, 0, 32, 116, 69, 88, 116, 67, 111, 109, 109, 101, 110, 116, 0,
    112, 114, 105, 118, 97, 116, 101, 45, 97, 114, 116, 119, 111, 114, 107, 45, 109, 101, 116, 97,
    100, 97, 116, 97, 252, 71, 246, 62, 0, 0, 0, 12, 73, 68, 65, 84, 120, 156, 99, 248, 207, 192,
    0, 0, 3, 1, 1, 0, 201, 254, 146, 239, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
];
const TRANSPARENT_PNG: &[u8] = &[
    137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0,
    0, 0, 31, 21, 196, 137, 0, 0, 0, 32, 116, 69, 88, 116, 67, 111, 109, 109, 101, 110, 116, 0,
    112, 114, 105, 118, 97, 116, 101, 45, 97, 114, 116, 119, 111, 114, 107, 45, 109, 101, 116, 97,
    100, 97, 116, 97, 252, 71, 246, 62, 0, 0, 0, 13, 73, 68, 65, 84, 120, 156, 99, 248, 207, 192,
    192, 0, 0, 4, 1, 1, 0, 71, 6, 202, 222, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
];

fn invoke(payload: &Path, image: &Path, output: &Path, succeeds: bool) -> Value {
    let response = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("optimize-artwork")
        .arg(payload)
        .arg(image)
        .arg(output)
        .env("PATH", "")
        .env("ENCAP_FFMPEG", "/missing/ffmpeg")
        .env("ENCAP_FFPROBE", "/missing/ffprobe")
        .output()
        .unwrap();
    assert_eq!(
        response.status.success(),
        succeeds,
        "{}",
        String::from_utf8_lossy(&response.stdout)
    );
    let value: Value = serde_json::from_slice(&response.stdout).expect("one JSON response");
    assert_eq!(value.get("error").is_none(), succeeds);
    value
}

#[test]
fn opaque_artwork_uses_core_without_media_tools_and_protects_all_project_inputs() {
    let root = tempfile::tempdir().unwrap();
    let image = root.path().join("cover.png");
    let audio = root.path().join("original.wav");
    let chapter = root.path().join("chapter.png");
    let archive = root.path().join("saved.encap");
    let payload = root.path().join("payload.json");
    let output = root.path().join("optimized.png");
    fs::write(&image, OPAQUE_PNG).unwrap();
    fs::write(&chapter, OPAQUE_PNG).unwrap();
    fs::write(&audio, b"original audio").unwrap();
    fs::write(&archive, b"original archive").unwrap();
    let project = serde_json::to_vec(&json!({
        "metadata":{"artwork_path":image}, "project_path":archive,
        "audio_sources":[{"source_path":audio,"duration_seconds":1.0}],
        "chapters":[{"id":"one","chapter_number":1,"start_time_seconds":0.0,"duration_seconds":1.0,"image_path":chapter}]
    })).unwrap();
    fs::write(&payload, &project).unwrap();
    let result = invoke(&payload, &image, &output, true);
    let optimized = fs::read(&output).unwrap();
    assert_eq!(result["path"], output.to_string_lossy().as_ref());
    assert_eq!(result["format"], "png");
    assert_eq!(result["input_bytes"], OPAQUE_PNG.len());
    assert_eq!(result["output_bytes"], optimized.len());
    assert_eq!(result["bytes_saved"], OPAQUE_PNG.len() - optimized.len());
    assert!(optimized.len() <= OPAQUE_PNG.len());
    assert!(optimized.starts_with(b"\x89PNG\r\n\x1a\n"));
    assert!(!optimized
        .windows(b"private-artwork-metadata".len())
        .any(|s| s == b"private-artwork-metadata"));
    for protected in [&image, &audio, &chapter, &archive, &payload] {
        let original = fs::read(protected).unwrap();
        invoke(&payload, &image, protected, false);
        assert_eq!(fs::read(protected).unwrap(), original);
        let alias = root.path().join("protected-alias.png");
        fs::hard_link(protected, &alias).unwrap();
        invoke(&payload, &image, &alias, false);
        assert_eq!(fs::read(protected).unwrap(), original);
        fs::remove_file(alias).unwrap();
    }
    assert_eq!(fs::read(&payload).unwrap(), project);
    assert_eq!(fs::read(&image).unwrap(), OPAQUE_PNG);
    assert_eq!(fs::read(&chapter).unwrap(), OPAQUE_PNG);
    assert_eq!(fs::read(&audio).unwrap(), b"original audio");
    assert_eq!(fs::read(&archive).unwrap(), b"original archive");
}

#[test]
fn invalid_or_transparent_artwork_preserves_existing_output_and_has_artwork_errors() {
    let root = tempfile::tempdir().unwrap();
    let payload = root.path().join("payload.json");
    let image = root.path().join("input.png");
    let output = root.path().join("existing.png");
    fs::write(&payload, b"{}").unwrap();
    fs::write(&output, b"existing output").unwrap();
    for bytes in [b"corrupt image".as_slice(), TRANSPARENT_PNG] {
        fs::write(&image, bytes).unwrap();
        let result = invoke(&payload, &image, &output, false);
        let error = result["error"].as_str().unwrap();
        assert!(error.contains("Artwork optimization"));
        assert!(!error.contains("Video"));
        assert_eq!(fs::read(&image).unwrap(), bytes);
        assert_eq!(fs::read(&output).unwrap(), b"existing output");
    }
    assert!(!fs::read_dir(root.path()).unwrap().any(|entry| entry
        .unwrap()
        .file_name()
        .to_string_lossy()
        .starts_with(".avid-")));
}
