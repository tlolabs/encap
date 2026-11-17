//! Explicit real-model diagnostic; never downloads or adopts an existing cache.
#![cfg(feature = "portable-whisper")]
use encap_core::AudioSource;
use encap_ffmpeg::CancellationToken;
use encap_transcript::*;
use std::{collections::BTreeMap, path::PathBuf};

#[test]
#[ignore = "requires explicitly supplied verified Tiny English model and local speech fixture"]
fn actual_portable_recognition_preserves_identity_clock_and_cleanup() {
    let model =
        PathBuf::from(std::env::var_os("AVID_TEST_WHISPER_MODEL").expect("explicit model fixture"));
    let audio =
        PathBuf::from(std::env::var_os("AVID_TEST_SPEECH").expect("explicit speech fixture"));
    let cache = tempfile::tempdir().unwrap();
    std::env::set_var("ENCAP_AVID_PORTABLE_CACHE", cache.path());
    let token = CancellationToken::default();
    let imported = import_model("whisper-cpp-tiny-en", &model, &token).unwrap();
    assert!(imported.installed);
    assert_eq!(imported.extensions["installation_state"], "verified");
    assert!(!imported.download_allowed);
    assert!(
        verify_model("whisper-cpp-tiny-en", &token)
            .unwrap()
            .installed
    );
    let source = AudioSource {
        source_path: audio,
        display_name: "speech".into(),
        duration_seconds: 6.,
        stored_path: None,
        extensions: BTreeMap::new(),
    };
    let options = TranscribeOptions {
        word_timestamps: true,
        language: Some("en"),
        alignment_model: None,
    };
    let first = transcribe(
        &[source.clone()],
        "whisper-cpp-tiny-en",
        &options,
        &[],
        &token,
    )
    .unwrap();
    assert!(!first.is_empty());
    assert!(first.iter().map(|s| s.words.len()).sum::<usize>() >= 10);
    let original = first[0].transcription_origin().unwrap();
    let provenance = &original.transcript["provenance"];
    assert_eq!(provenance["model_id"], "whisper-cpp-tiny-en");
    assert_eq!(
        provenance["model_identity"]["artifacts"][0]["sha256"],
        "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f"
    );
    assert_eq!(
        provenance["runtime_revisions"]["whisper.cpp"],
        "4979e04f5dcaccb36057e059bbaed8a2f5288315"
    );
    assert_eq!(
        provenance["runtime_build_sha256"].as_str().unwrap().len(),
        64
    );
    assert!(render_captions(&first, "vtt", &token)
        .unwrap()
        .starts_with("WEBVTT"));
    let repeat = transcribe(
        &[source.clone()],
        "whisper-cpp-tiny-en",
        &options,
        &first,
        &token,
    )
    .unwrap();
    assert_eq!(repeat[0].id, first[0].id);
    let cancelled = CancellationToken::default();
    cancelled.cancel();
    assert!(transcribe(
        &[source],
        "whisper-cpp-tiny-en",
        &options,
        &repeat,
        &cancelled
    )
    .is_err());
    assert!(
        !remove_model("whisper-cpp-tiny-en", &token)
            .unwrap()
            .installed
    );
    assert!(model.is_file(), "explicit import source remains intact");
    std::env::remove_var("ENCAP_AVID_PORTABLE_CACHE");
}
