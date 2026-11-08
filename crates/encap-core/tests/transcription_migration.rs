use encap_core::{
    edit_audio, inspect_files, load_project, render_transcript_text, save_project,
    validate_timed_transcript, AudioEdits, ProjectDocument, TranscriptOrigin, TranscriptSegment,
    TranscriptTimingStatus,
};
use serde_json::{json, Value};
use std::{fs, io::Write};
use zip::write::SimpleFileOptions;

fn origin(source: &str, episode_offset: f64) -> Value {
    json!({
        "version": 1, "source_id": source, "source_duration_seconds": 30.0,
        "source_timeline_offset_seconds": episode_offset, "source_offset_seconds": 12.5,
        "segment_index": 0, "timing_status": "timed",
        "future_origin": {"preserve": [true, null, "é"]},
        "transcript": {
            "language":"en", "recognition":{"model_id":"whisper-large-v3", "revision":"pinned"},
            "alignment":{"model_id":"aligner", "language":"en"},
            "segments":[{"text":"Original", "start":13.0, "end":14.0,
                "words":[{"text":"Original", "start":13.0, "end":14.0,"confidence":0.8}]}],
            "future_raw":{"key_with_underscores":[1, 2]}
        }
    })
}

fn segment() -> TranscriptSegment {
    serde_json::from_value(json!({
        "id":"segment", "start_time_seconds":30.5,"end_time_seconds":31.5,
        "text":"Edited by user", "speaker":"Manually named speaker", "future_segment":42,
        "words":[{"id":"word","start_time_seconds":30.5,"end_time_seconds":31.5,
            "text":"Original","future_word":true}],
        "avid_core":origin("stored:audio/c.wav",30.0)
    }))
    .unwrap()
}

#[test]
fn legacy_schema_one_and_two_keep_edits_ids_speakers_and_opaque_fields() {
    for schema in [1, 2] {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("legacy.encap");
        let mut zip = zip::ZipWriter::new(fs::File::create(&path).unwrap());
        zip.start_file("audio/c.wav", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"source media bytes").unwrap();
        zip.start_file("manifest.json", SimpleFileOptions::default())
            .unwrap();
        let value = json!({
            "schema_version":schema,
            "future_project":{"opaque":[true,null,"keep"]},
            "audio_sources":[{"stored_path":"audio/c.wav","duration_seconds":60.0,"future_source":"keep"}],
            "transcript_segments":[
                segment(),
                {"id":"without-words","start_time_seconds":1.0,"end_time_seconds":2.0,"text":"Legacy edit","speaker":"Host"}
            ],
            "transcript_settings":{"recognition_model_id":"whisper-large-v3","alignment_model_id":"qwen3-forced-aligner-0.6b-4bit","language":"en","future_setting":true}
        });
        zip.write_all(&serde_json::to_vec(&value).unwrap()).unwrap();
        zip.finish().unwrap();
        let loaded = load_project(&path, Some(dir.path())).unwrap();
        assert_eq!(loaded.schema_version, 2);
        assert!(loaded.transcript_segments[1].words.is_empty());
        let saved = save_project(&loaded, &dir.path().join("saved.encap")).unwrap();
        let reopened = load_project(&saved, Some(dir.path())).unwrap();
        assert_eq!(reopened.transcript_segments, loaded.transcript_segments);
        assert_eq!(reopened.transcript_settings, loaded.transcript_settings);
        assert_eq!(reopened.extensions, loaded.extensions);
        assert_eq!(
            reopened.audio_sources[0].transcription_source_id(),
            "stored:audio/c.wav"
        );
        assert_eq!(
            fs::read(&reopened.audio_sources[0].source_path).unwrap(),
            b"source media bytes"
        );
        // Recovery uses the engine's JSON representation, including its opaque
        // compatibility payload. It must retain the entire original record.
        let recovery: ProjectDocument =
            serde_json::from_slice(&serde_json::to_vec(&reopened).unwrap()).unwrap();
        assert_eq!(recovery, reopened);
        assert_eq!(
            recovery.transcript_segments[0].extensions["avid_core"],
            origin("stored:audio/c.wav", 30.0)
        );
    }
}

#[test]
fn source_identity_is_pinned_before_first_save_and_survives_relocation() {
    let dir = tempfile::tempdir().unwrap();
    let media = dir.path().join("original.wav");
    fs::write(&media, b"media").unwrap();
    let project: ProjectDocument = serde_json::from_value(json!({
        "audio_sources":[{"source_path":media,"duration_seconds":1.0,"display_name":"Recording"}]
    }))
    .unwrap();
    let original_id = project.audio_sources[0].transcription_source_id();
    let saved = save_project(&project, &dir.path().join("portable.encap")).unwrap();
    let loaded = load_project(&saved, Some(dir.path())).unwrap();
    assert_ne!(
        loaded.audio_sources[0].source_path,
        project.audio_sources[0].source_path
    );
    assert_eq!(
        loaded.audio_sources[0].transcription_source_id(),
        original_id
    );
}

#[test]
fn editing_invalidates_words_without_mutating_source_record_or_user_identity() {
    let mut segment = segment();
    let raw = segment.transcription_origin().unwrap().transcript;
    let words = segment.words.clone();
    segment.replace_text(segment.text.clone());
    assert_eq!(segment.words, words);
    segment.replace_text("A different edit".into());
    assert!(segment.words.is_empty());
    let updated = segment.transcription_origin().unwrap();
    assert_eq!(updated.timing_status, TranscriptTimingStatus::Invalidated);
    assert_eq!(updated.transcript, raw);
    assert_eq!(
        updated.extensions["future_origin"],
        json!({"preserve":[true,null,"é"]})
    );
    assert_eq!(segment.id, "segment");
    assert_eq!(segment.speaker, "Manually named speaker");
    assert_eq!(segment.start_time_seconds, 30.5);
    // Ordinary coarse subtitles remain available; word caption generation
    // separately requires actual verified word timing.
    assert!(validate_timed_transcript(&[segment]).is_ok());
}

#[test]
fn removing_sources_shifts_projection_once_and_removes_untimed_text_by_identity() {
    let mut project: ProjectDocument = serde_json::from_value(json!({
        "audio_sources":[
            {"source_path":"a.wav","duration_seconds":10.0,"avid_source_id":"a"},
            {"source_path":"b.wav","duration_seconds":20.0,"avid_source_id":"b"},
            {"source_path":"c.wav","duration_seconds":30.0,"avid_source_id":"stored:audio/c.wav"}
        ],
        "transcript_segments":[segment()]
    }))
    .unwrap();
    let mut untimed: TranscriptSegment = serde_json::from_value(json!({
        "id":"untimed", "start_time_seconds":10.0, "end_time_seconds":10.0,"text":"Untimed text"
    }))
    .unwrap();
    let mut untimed_origin: TranscriptOrigin = serde_json::from_value(origin("b", 10.0)).unwrap();
    untimed_origin.timing_status = TranscriptTimingStatus::Untimed;
    untimed.set_transcription_origin(untimed_origin);
    project.transcript_segments.push(untimed);
    let result = edit_audio(
        &project,
        AudioEdits {
            remove_files: vec!["b.wav".into()],
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(result.transcript_segments.len(), 1);
    let retained = &result.transcript_segments[0];
    assert_eq!(retained.start_time_seconds, 10.5);
    assert_eq!(retained.words[0].start_time_seconds, 10.5);
    let mapped = retained.transcription_origin().unwrap();
    assert_eq!(mapped.source_timeline_offset_seconds, 10.0);
    assert_eq!(
        mapped.transcript,
        project.transcript_segments[0]
            .transcription_origin()
            .unwrap()
            .transcript
    );
    assert_eq!(mapped.source_time_to_episode(13.0), 10.5);
    assert_eq!(mapped.episode_time_to_source(10.5), 13.0);
    assert_eq!(project.transcript_segments.len(), 2);
}

#[test]
fn untimed_text_exports_as_text_but_never_fabricated_subtitles() {
    let mut segment = segment();
    segment.words.clear();
    let mut origin = segment.transcription_origin().unwrap();
    origin.timing_status = TranscriptTimingStatus::Untimed;
    segment.set_transcription_origin(origin);
    assert!(validate_timed_transcript(&[segment.clone()]).is_err());
    assert!(render_transcript_text(&[segment.clone()]).contains("Edited by user"));
    segment.replace_text("Still untimed".into());
    assert_eq!(
        segment.transcription_origin().unwrap().timing_status,
        TranscriptTimingStatus::Untimed
    );
    assert!(validate_timed_transcript(&[segment]).is_err());
}

fn instance_segment(
    source_id: &str,
    start: f64,
    end: f64,
    episode_offset: f64,
) -> TranscriptSegment {
    serde_json::from_value(json!({
        "id":format!("{source_id}-segment"),
        "start_time_seconds":episode_offset+start,"end_time_seconds":episode_offset+end,
        "speaker":"Manually named speaker","text":"Keep this source",
        "words":[{"id":format!("{source_id}-word"),"text":"Keep this source",
            "start_time_seconds":episode_offset+start,"end_time_seconds":episode_offset+end}],
        "avid_core":{
            "version":1,"source_id":source_id,"source_duration_seconds":10.0,
            "source_timeline_offset_seconds":episode_offset,"source_offset_seconds":0.0,"segment_index":0,"timing_status":"timed",
            "transcript":{"segments":[{"text":"Keep this source","start_seconds":start,"end_seconds":end,
                "words":[{"text":"Keep this source","start_seconds":start,"end_seconds":end}]}],
                "provenance":{"engine_id":"whisperkit","model_id":"whisper-large-v3"}}
        }
    })).unwrap()
}

#[test]
fn retained_source_native_overshoot_is_clipped_without_deleting_its_text_or_record() {
    let original = instance_segment("a", 9.5, 10.2, 0.0);
    let legacy: TranscriptSegment = serde_json::from_value(json!({
        "id":"legacy-crossing","start_time_seconds":9.5,"end_time_seconds":10.2,"text":"Legacy crossing"
    })).unwrap();
    let project: ProjectDocument = serde_json::from_value(json!({
        "audio_sources":[{"source_path":"a.wav","duration_seconds":10,"avid_source_id":"a"},
            {"source_path":"b.wav","duration_seconds":20,"avid_source_id":"b"}],
        "transcript_segments":[original,legacy]
    }))
    .unwrap();
    let result = edit_audio(
        &project,
        AudioEdits {
            remove_files: vec!["b.wav".into()],
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(result.transcript_segments.len(), 1);
    let retained = &result.transcript_segments[0];
    assert_eq!(retained.id, original.id);
    assert_eq!(retained.speaker, original.speaker);
    assert_eq!(retained.text, original.text);
    assert_eq!(
        (retained.start_time_seconds, retained.end_time_seconds),
        (9.5, 10.0)
    );
    assert_eq!(retained.words[0].end_time_seconds, 10.0);
    assert_eq!(
        retained.transcription_origin().unwrap().transcript,
        original.transcription_origin().unwrap().transcript
    );
    assert!(edit_audio(
        &project,
        AudioEdits {
            remove_files: vec!["a.wav".into()],
            ..Default::default()
        }
    )
    .unwrap()
    .transcript_segments
    .is_empty());
}

#[test]
fn removing_history_carrier_preserves_surviving_edit_history_once() {
    let historical = json!({"id":"old-b","text":"User edited B","speaker":"Custom speaker B",
        "future_history":{"opaque":[1,true,null]}});
    let mut a = instance_segment("a", 0.0, 1.0, 0.0);
    let b = instance_segment("b", 1.0, 2.0, 10.0);
    let mut carrier_origin = a.transcription_origin().unwrap();
    carrier_origin
        .extensions
        .insert("previous_transcript".into(), json!([historical]));
    carrier_origin.extensions.insert(
        "reconciliation_warning".into(),
        "Review preserved speaker assignments".into(),
    );
    a.set_transcription_origin(carrier_origin);
    let project: ProjectDocument = serde_json::from_value(json!({
        "audio_sources":[{"source_path":"a.wav","duration_seconds":10,"avid_source_id":"a"},
            {"source_path":"b.wav","duration_seconds":20,"avid_source_id":"b"}],
        "transcript_segments":[a,b]
    }))
    .unwrap();
    let result = edit_audio(
        &project,
        AudioEdits {
            remove_files: vec!["a.wav".into()],
            ..Default::default()
        },
    )
    .unwrap();
    let retained = result.transcript_segments[0]
        .transcription_origin()
        .unwrap();
    assert_eq!(
        retained.extensions["previous_transcript"],
        json!([historical])
    );
    assert_eq!(
        retained.extensions["reconciliation_warning"],
        "Review preserved speaker assignments"
    );
    assert_eq!(
        retained.transcript,
        b.transcription_origin().unwrap().transcript
    );
    let mut duplicated_history = project.clone();
    let mut target = duplicated_history.transcript_segments[1]
        .transcription_origin()
        .unwrap();
    target
        .extensions
        .insert("previous_transcript".into(), json!([historical]));
    duplicated_history.transcript_segments[1].set_transcription_origin(target);
    let deduplicated = edit_audio(
        &duplicated_history,
        AudioEdits {
            remove_files: vec!["a.wav".into()],
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(
        deduplicated.transcript_segments[0]
            .transcription_origin()
            .unwrap()
            .extensions["previous_transcript"],
        json!([historical])
    );
    let carrier_retained = edit_audio(
        &project,
        AudioEdits {
            remove_files: vec!["b.wav".into()],
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(
        carrier_retained.transcript_segments[0]
            .transcription_origin()
            .unwrap()
            .extensions["previous_transcript"],
        json!([historical])
    );
    let empty = edit_audio(
        &project,
        AudioEdits {
            remove_files: vec!["a.wav".into(), "b.wav".into()],
            ..Default::default()
        },
    )
    .unwrap();
    assert!(empty.transcript_segments.is_empty());
}

#[test]
fn save_reopen_reimport_keeps_distinct_source_instances_and_removing_one_keeps_the_other() {
    let dir = tempfile::tempdir().unwrap();
    let media = dir.path().join("original.wav");
    let samples = [0_u8; 32_000];
    let mut wav = Vec::new();
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&(36_u32 + samples.len() as u32).to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    wav.extend_from_slice(&16_u32.to_le_bytes());
    wav.extend_from_slice(&1_u16.to_le_bytes());
    wav.extend_from_slice(&1_u16.to_le_bytes());
    wav.extend_from_slice(&16_000_u32.to_le_bytes());
    wav.extend_from_slice(&32_000_u32.to_le_bytes());
    wav.extend_from_slice(&2_u16.to_le_bytes());
    wav.extend_from_slice(&16_u16.to_le_bytes());
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&(samples.len() as u32).to_le_bytes());
    wav.extend_from_slice(&samples);
    fs::write(&media, wav).unwrap();
    let imported = inspect_files(std::slice::from_ref(&media)).unwrap();
    let original_id = imported.audio_sources[0].transcription_source_id();
    let archive = save_project(&imported, &dir.path().join("project.encap")).unwrap();
    let loaded = load_project(&archive, Some(dir.path())).unwrap();
    assert_eq!(
        loaded.audio_sources[0].transcription_source_id(),
        original_id
    );
    let mut added = edit_audio(
        &loaded,
        AudioEdits {
            add_files: vec![media.clone()],
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(added.audio_sources.len(), 2);
    let second_id = added.audio_sources[1].transcription_source_id();
    assert_ne!(second_id, original_id);
    added.transcript_segments = vec![
        instance_segment(&original_id, 0.0, 0.8, 0.0),
        instance_segment(&second_id, 0.0, 0.8, 1.0),
    ];
    let result = edit_audio(
        &added,
        AudioEdits {
            remove_files: vec![media],
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(result.audio_sources.len(), 1);
    assert_eq!(
        result.audio_sources[0].transcription_source_id(),
        original_id
    );
    assert_eq!(result.transcript_segments.len(), 1);
    assert_eq!(result.transcript_segments[0], added.transcript_segments[0]);
}

#[test]
fn silent_surviving_source_keeps_history_at_project_level_through_save_and_recovery() {
    let dir = tempfile::tempdir().unwrap();
    let a_path = dir.path().join("a.wav");
    let b_path = dir.path().join("b.wav");
    fs::write(&a_path, b"A media").unwrap();
    fs::write(&b_path, b"Silent B media").unwrap();
    let historical = json!({"id":"old-b","text":"Previously edited B","speaker":"Custom B",
        "future_history":{"opaque":[true,null,"é"]}});
    let mut a = instance_segment("a", 0.0, 1.0, 0.0);
    let mut origin = a.transcription_origin().unwrap();
    origin
        .extensions
        .insert("previous_transcript".into(), json!([historical]));
    origin.extensions.insert(
        "reconciliation_warning".into(),
        "Review history for B".into(),
    );
    a.set_transcription_origin(origin);
    let project: ProjectDocument = serde_json::from_value(json!({
        "audio_sources":[{"source_path":a_path,"duration_seconds":10,"avid_source_id":"a"},
            {"source_path":b_path,"duration_seconds":20,"avid_source_id":"b"}],
        "transcript_segments":[a]
    }))
    .unwrap();
    let result = edit_audio(
        &project,
        AudioEdits {
            remove_files: vec![a_path],
            ..Default::default()
        },
    )
    .unwrap();
    assert!(result.transcript_segments.is_empty());
    assert_eq!(result.audio_sources.len(), 1);
    assert_eq!(
        result.extensions["avid_transcript_history"],
        json!([historical])
    );
    assert_eq!(
        result.extensions["avid_reconciliation_warning"],
        "Review history for B"
    );
    let saved = save_project(&result, &dir.path().join("history.encap")).unwrap();
    let reopened = load_project(&saved, Some(dir.path())).unwrap();
    assert_eq!(
        reopened.extensions["avid_transcript_history"],
        json!([historical])
    );
    let recovery: ProjectDocument =
        serde_json::from_slice(&serde_json::to_vec(&reopened).unwrap()).unwrap();
    assert_eq!(
        recovery.extensions["avid_transcript_history"],
        json!([historical])
    );
    let emptied = edit_audio(
        &reopened,
        AudioEdits {
            remove_files: vec![reopened.audio_sources[0].source_path.clone()],
            ..Default::default()
        },
    )
    .unwrap();
    assert!(emptied.extensions["avid_transcript_history"].is_null());
    let empty_saved = save_project(&emptied, &dir.path().join("cleared.encap")).unwrap();
    let empty_reopened = load_project(&empty_saved, Some(dir.path())).unwrap();
    assert!(empty_reopened.extensions["avid_transcript_history"].is_null());
    assert!(empty_reopened.extensions["avid_reconciliation_warning"].is_null());
}
