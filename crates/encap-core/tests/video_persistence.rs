use encap_core::{load_project, save_project, ProjectDocument};
use serde_json::{json, Value};
use std::{
    fs,
    io::{Read, Write},
};
use zip::write::SimpleFileOptions;

#[test]
fn schema_one_two_video_roundtrips_preserve_opaque_state_and_audio_order() {
    for schema in [1, 2] {
        for initialized in [false, true] {
            let root = tempfile::tempdir().unwrap();
            let archive = root.path().join("fixture.encap");
            let file = fs::File::create(&archive).unwrap();
            let mut zip = zip::ZipWriter::new(file);
            let options = SimpleFileOptions::default();
            for name in [
                "audio/one.wav",
                "audio/two.wav",
                "artwork/cover.png",
                "chapters/two.png",
            ] {
                zip.start_file(name, options).unwrap();
                zip.write_all(name.as_bytes()).unwrap();
            }
            let manifest = json!({
                "schema_version":schema, "future_project":{"keep":true},
                "metadata":{"artwork_stored_path":"artwork/cover.png", "future_metadata":[1,2]},
                "audio_sources":[{"stored_path":"audio/one.wav", "duration_seconds":1.0, "future_audio":1}, {"stored_path":"audio/two.wav", "duration_seconds":2.0}],
                "chapters":[{"id":"one","chapter_number":1,"start_time_seconds":0.0,"duration_seconds":1.0,"future_chapter":1}, {"id":"two","chapter_number":2,"start_time_seconds":1.0,"duration_seconds":2.0,"image_stored_path":"chapters/two.png"}],
                "transcript_segments":[{"id":"s","start_time_seconds":0.0,"end_time_seconds":1.0,"text":"hello","future_segment":42,"words":[{"id":"w","start_time_seconds":0.0,"end_time_seconds":0.5,"text":"hello","future_word":true}]}],
                "transcript_settings":{"future_transcript":true}, "export_settings":{"future_export":"keep"},
                "video":{"schema_version":1,"future_video":{"a":1},"compositions":[{"future_layer":[1,2,3]}],"export_settings":{"codec":"future-codec","preview_quality":"future-quality","future_setting":{"opaque":true},"selected_chapter_ids":["two","stale","one"],"selection_initialized":initialized}}
            });
            zip.start_file("manifest.json", options).unwrap();
            zip.write_all(&serde_json::to_vec(&manifest).unwrap())
                .unwrap();
            zip.finish().unwrap();
            let mut loaded = load_project(&archive, Some(root.path())).unwrap();
            assert_eq!(loaded.schema_version, 2);
            assert_eq!(
                loaded.video.export_settings.selected_chapter_ids,
                vec!["two", "one"]
            );
            assert!(loaded.video.export_settings.render_settings().is_err());
            loaded.project_title = "Edited".into();
            loaded.video.export_settings.selected_chapter_ids = vec!["two".into(), "one".into()];
            // Simulate a native client that only returns known fields plus compatibility_payload.
            loaded.extensions.clear();
            loaded.metadata.extensions.clear();
            loaded.audio_sources[0].extensions.clear();
            loaded.chapters[0].extensions.clear();
            loaded.transcript_segments[0].extensions.clear();
            loaded.transcript_segments[0].words[0].extensions.clear();
            loaded.transcript_settings.extensions.clear();
            loaded.export_settings.extensions.clear();
            loaded.video.extensions.clear();
            loaded.video.export_settings.extensions.clear();
            let saved = save_project(&loaded, &root.path().join("edited.encap")).unwrap();
            let reopened = load_project(&saved, Some(root.path())).unwrap();
            assert_eq!(
                reopened.video.export_settings.selected_chapter_ids,
                ["two", "one"]
            );
            assert_eq!(
                reopened
                    .chapters
                    .iter()
                    .map(|c| c.id.as_str())
                    .collect::<Vec<_>>(),
                ["one", "two"]
            );
            assert_eq!(reopened.chapters[1].start_time_seconds, 1.0);
            assert_eq!(reopened.video.export_settings.codec, "future-codec");
            assert_eq!(
                reopened.video.export_settings.preview_quality,
                "future-quality"
            );
            let mut zip = zip::ZipArchive::new(fs::File::open(saved).unwrap()).unwrap();
            let mut bytes = Vec::new();
            zip.by_name("manifest.json")
                .unwrap()
                .read_to_end(&mut bytes)
                .unwrap();
            let restored: Value = serde_json::from_slice(&bytes).unwrap();
            for pointer in [
                "/future_project",
                "/metadata/future_metadata",
                "/audio_sources/0/future_audio",
                "/chapters/0/future_chapter",
                "/transcript_segments/0/future_segment",
                "/transcript_segments/0/words/0/future_word",
                "/transcript_settings/future_transcript",
                "/export_settings/future_export",
                "/video/future_video",
                "/video/compositions",
                "/video/export_settings/future_setting",
            ] {
                assert_eq!(
                    restored.pointer(pointer),
                    manifest.pointer(pointer),
                    "{pointer}"
                );
            }
            let mut empty = reopened;
            empty.video.export_settings.selected_chapter_ids.clear();
            empty.video.export_settings.selection_initialized = true;
            let path = save_project(&empty, &root.path().join("empty.encap")).unwrap();
            assert!(load_project(&path, Some(root.path()))
                .unwrap()
                .video
                .export_settings
                .selected_chapter_ids
                .is_empty());
        }
    }
    let mut future = ProjectDocument::default();
    future.video.schema_version = 99;
    let copy: ProjectDocument =
        serde_json::from_value(serde_json::to_value(&future).unwrap()).unwrap();
    assert_eq!(copy.video.schema_version, 99);
    assert!(copy.validate().is_err());
}
