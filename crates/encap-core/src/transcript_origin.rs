//! Backward-compatible recognition records and their episode-clock projection.
//!
//! The `avid_core` extension is optional: projects made before AVID integration
//! retain their established segment/word times. Raw recognition records keep
//! their original source clock; only episode times and the projection offset
//! change when source audio is removed.

use crate::{AudioSource, EncapError, ProjectDocument, Result, TranscriptSegment};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TranscriptTimingStatus {
    #[default]
    Timed,
    Untimed,
    /// Text changed after recognition/alignment. Word timing was discarded;
    /// existing coarse segment bounds are retained for ordinary subtitles.
    Invalidated,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct TranscriptOrigin {
    pub version: u32,
    pub source_id: String,
    pub source_duration_seconds: f64,
    pub source_timeline_offset_seconds: f64,
    #[serde(default)]
    pub source_offset_seconds: f64,
    pub segment_index: usize,
    #[serde(default)]
    pub timing_status: TranscriptTimingStatus,
    /// Original shared Transcript envelope containing this source segment and
    /// its recognition/alignment provenance. Never rewritten by text edits.
    /// One segment per envelope keeps storage linear in transcript length.
    pub transcript: Value,
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

impl TranscriptOrigin {
    /// Raw Core time includes the requested source extraction offset. Remove
    /// that offset once, then place the result on the assembled episode clock.
    pub fn source_time_to_episode(&self, seconds: f64) -> f64 {
        seconds - self.source_offset_seconds + self.source_timeline_offset_seconds
    }

    pub fn episode_time_to_source(&self, seconds: f64) -> f64 {
        seconds - self.source_timeline_offset_seconds + self.source_offset_seconds
    }
}

impl AudioSource {
    /// A source identity is independent of the extraction directory. Legacy
    /// sources receive a deterministic identity that is pinned on save/load.
    pub fn transcription_source_id(&self) -> String {
        self.extensions
            .get("avid_source_id")
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty())
            .map(str::to_owned)
            .unwrap_or_else(|| match &self.stored_path {
                Some(path) => format!("stored:{path}"),
                None => format!("path:{}", self.source_path.to_string_lossy()),
            })
    }

    pub fn ensure_transcription_source_id(&mut self) -> String {
        let id = self.transcription_source_id();
        self.extensions
            .insert("avid_source_id".into(), Value::String(id.clone()));
        id
    }
}

impl TranscriptSegment {
    pub fn transcription_origin(&self) -> Option<TranscriptOrigin> {
        self.extensions
            .get("avid_core")
            .and_then(|value| serde_json::from_value(value.clone()).ok())
    }

    pub fn set_transcription_origin(&mut self, origin: TranscriptOrigin) {
        // Every field is JSON-serializable; unlike an arbitrary map there are
        // no unsupported non-string keys in this record.
        self.extensions.insert(
            "avid_core".into(),
            serde_json::to_value(origin).expect("transcript origin is JSON-serializable"),
        );
    }

    pub fn invalidate_word_alignment(&mut self) {
        self.words.clear();
        if let Some(mut origin) = self.transcription_origin() {
            // Untimed recognition remains untimed after an edit.
            if origin.timing_status != TranscriptTimingStatus::Untimed {
                origin.timing_status = TranscriptTimingStatus::Invalidated;
            }
            self.set_transcription_origin(origin);
        }
    }

    pub fn replace_text(&mut self, text: String) {
        if self.text != text {
            self.invalidate_word_alignment();
            self.text = text;
        }
    }

    /// Update the reversible source-to-episode mapping while retaining the raw
    /// source record, source offsets, IDs, speakers, and unknown extensions.
    pub fn shift_transcription_projection(&mut self, delta_seconds: f64) {
        if let Some(mut origin) = self.transcription_origin() {
            origin.source_timeline_offset_seconds += delta_seconds;
            self.set_transcription_origin(origin);
        }
    }

    pub(crate) fn reproject_to_source(&mut self, episode_start: f64, duration: f64) {
        let Some(mut origin) = self.transcription_origin() else {
            return;
        };
        let project = |time: f64| {
            (time - origin.source_timeline_offset_seconds).clamp(0.0, duration) + episode_start
        };
        self.start_time_seconds = project(self.start_time_seconds);
        self.end_time_seconds = project(self.end_time_seconds);
        for word in &mut self.words {
            word.start_time_seconds = project(word.start_time_seconds);
            word.end_time_seconds = project(word.end_time_seconds);
        }
        if self.end_time_seconds <= self.start_time_seconds {
            self.words.clear();
            origin.timing_status = TranscriptTimingStatus::Untimed;
        } else if self
            .words
            .iter()
            .any(|word| word.end_time_seconds <= word.start_time_seconds)
        {
            self.words.clear();
            if origin.timing_status != TranscriptTimingStatus::Untimed {
                origin.timing_status = TranscriptTimingStatus::Invalidated;
            }
        }
        origin.source_timeline_offset_seconds = episode_start;
        self.set_transcription_origin(origin);
    }
}

/// Rerecognition stores one operation history on a carrier segment. Removing
/// its source must not discard the previous edits of surviving sources.
pub(crate) fn transfer_removed_history(
    previous: &[TranscriptSegment],
    project: &mut ProjectDocument,
) {
    if project.audio_sources.is_empty() {
        // Explicit tombstones also override opaque compatibility payloads on
        // save, so deleting all sources cannot resurrect old transcript data.
        project
            .extensions
            .insert("avid_transcript_history".into(), Value::Null);
        project
            .extensions
            .insert("avid_reconciliation_warning".into(), Value::Null);
        return;
    }
    let retained_ids: std::collections::BTreeSet<_> = project
        .transcript_segments
        .iter()
        .map(|segment| &segment.id)
        .collect();
    let mut histories = Vec::new();
    let mut warnings = Vec::new();
    for removed in previous
        .iter()
        .filter(|segment| !retained_ids.contains(&segment.id))
    {
        let Some(origin) = removed.transcription_origin() else {
            continue;
        };
        if let Some(Value::Array(items)) = origin.extensions.get("previous_transcript") {
            histories.extend(items.iter().cloned());
        }
        if let Some(Value::String(warning)) = origin.extensions.get("reconciliation_warning") {
            warnings.push(warning.clone());
        }
    }
    if histories.is_empty() && warnings.is_empty() {
        return;
    }
    let carrier = project
        .transcript_segments
        .iter()
        .position(|segment| segment.transcription_origin().is_some());
    let mut origin =
        carrier.and_then(|index| project.transcript_segments[index].transcription_origin());
    let (extensions, history_key, warning_key) = match &mut origin {
        Some(origin) => (
            &mut origin.extensions,
            "previous_transcript",
            "reconciliation_warning",
        ),
        None => (
            &mut project.extensions,
            "avid_transcript_history",
            "avid_reconciliation_warning",
        ),
    };
    let mut merged = extensions
        .get(history_key)
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    for item in histories {
        if !merged.contains(&item) {
            merged.push(item);
        }
    }
    if !merged.is_empty() {
        extensions.insert(history_key.into(), Value::Array(merged));
    }
    let mut merged_warnings = extensions
        .get(warning_key)
        .and_then(Value::as_str)
        .map(|warning| vec![warning.to_owned()])
        .unwrap_or_default();
    for warning in warnings {
        if !merged_warnings.contains(&warning) {
            merged_warnings.push(warning);
        }
    }
    if !merged_warnings.is_empty() {
        extensions.insert(
            warning_key.into(),
            Value::String(merged_warnings.join("\n")),
        );
    }
    if let (Some(index), Some(origin)) = (carrier, origin) {
        project.transcript_segments[index].set_transcription_origin(origin);
    }
}

/// Untimed recognition is valid text, but must not produce fabricated SRT/VTT
/// timestamps. Legacy segments retain their established export behavior.
pub fn validate_timed_transcript(segments: &[TranscriptSegment]) -> Result<()> {
    for segment in segments {
        if let Some(raw) = segment.extensions.get("avid_core") {
            let origin: TranscriptOrigin = serde_json::from_value(raw.clone()).map_err(|_| {
                EncapError::Message("The transcript's timing metadata is invalid.".into())
            })?;
            if origin.version != 1
                || origin.timing_status == TranscriptTimingStatus::Untimed
                || segment.end_time_seconds <= segment.start_time_seconds
            {
                return Err(EncapError::Message(
                    "This transcript has no usable segment timing. Align the text before exporting subtitles."
                        .into(),
                ));
            }
        }
    }
    Ok(())
}

pub(crate) fn validate_origin(segment: &TranscriptSegment) -> Result<()> {
    let Some(raw) = segment.extensions.get("avid_core") else {
        return Ok(());
    };
    let origin: TranscriptOrigin = serde_json::from_value(raw.clone()).map_err(|_| {
        EncapError::Message("The transcript's recognition metadata is invalid.".into())
    })?;
    if origin.source_id.is_empty()
        || !crate::is_valid_duration(origin.source_duration_seconds)
        || !crate::is_valid_duration(origin.source_timeline_offset_seconds)
        || !crate::is_valid_duration(origin.source_offset_seconds)
        || !origin.transcript.is_object()
        || (origin.timing_status != TranscriptTimingStatus::Timed && !segment.words.is_empty())
    {
        return Err(EncapError::Message(
            "The transcript's source mapping or alignment state is invalid.".into(),
        ));
    }
    Ok(())
}
