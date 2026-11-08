//! Thin, process-isolated adapter to the reviewed AVID Core transcription libraries.
//!
//! Catalogs, model ownership, downloading, verification and inference live in the
//! packaged Swift sidecar. Legacy EnCAP/third-party model folders are never touched.

use encap_core::{AudioSource, EncapError, Result, TranscriptSegment, TranscriptWord};
use encap_ffmpeg::CancellationToken;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::ffi::OsString;
use std::fs;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

pub const DEFAULT_MODEL: &str = "whisper-large-v3";
const MAX_RESPONSE_BYTES: u64 = 512 * 1024 * 1024;
const MAX_FAILURE_DIAGNOSTIC_BYTES: usize = 8192;
const CANCEL_GRACE: Duration = Duration::from_secs(15);
const PLATFORM_REASON: &str = "AVID Core transcription currently requires Apple silicon and macOS 14 or later. Shared transcription support for Intel Mac, macOS 13, Windows and Linux is unresolved; existing projects, transcript editing and exports remain available.";

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Provider {
    pub id: String,
    pub name: String,
    pub detail: String,
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ModelInfo {
    pub id: String,
    pub name: String,
    pub download_size: String,
    pub languages: String,
    pub description: String,
    pub installed: bool,
    pub download_allowed: bool,
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, Serialize)]
pub struct TranscriptionStatus {
    pub available: bool,
    pub reason: String,
    pub default_model: &'static str,
}

pub fn status() -> TranscriptionStatus {
    match helper_path() {
        Ok(_) => TranscriptionStatus {
            available: true,
            reason: "Local AVID Core transcription. Model installation is required before inference; source audio stays on this computer.".into(),
            default_model: DEFAULT_MODEL,
        },
        Err(error) => TranscriptionStatus {
            available: false,
            reason: error.to_string(),
            default_model: DEFAULT_MODEL,
        },
    }
}

pub fn models(cancellation: &CancellationToken) -> Result<Vec<ModelInfo>> {
    Bridge::discover()?.invoke(&["models".into()], cancellation)
}

pub fn providers(cancellation: &CancellationToken) -> Result<Vec<Provider>> {
    Bridge::discover()?.invoke(&["providers".into()], cancellation)
}

pub fn install_model(id: &str, cancellation: &CancellationToken) -> Result<ModelInfo> {
    Bridge::discover()?.invoke(&model_arguments("install-model", id), cancellation)
}

pub fn remove_model(id: &str, cancellation: &CancellationToken) -> Result<ModelInfo> {
    Bridge::discover()?.invoke(&model_arguments("remove-model", id), cancellation)
}

pub fn import_model(
    id: &str,
    source: &Path,
    cancellation: &CancellationToken,
) -> Result<ModelInfo> {
    let mut arguments = model_arguments("import-model", id);
    arguments.extend(["--source".into(), source.as_os_str().to_owned()]);
    Bridge::discover()?.invoke(&arguments, cancellation)
}

fn model_arguments(command: &str, id: &str) -> Vec<OsString> {
    vec![command.into(), "--model".into(), id.into()]
}

#[derive(Clone, Debug, Default)]
pub struct TranscribeOptions<'a> {
    pub word_timestamps: bool,
    pub language: Option<&'a str>,
    pub alignment_model: Option<&'a str>,
}

pub fn transcribe(
    sources: &[AudioSource],
    model: &str,
    options: &TranscribeOptions<'_>,
    previous: &[TranscriptSegment],
    cancellation: &CancellationToken,
) -> Result<Vec<TranscriptSegment>> {
    transcribe_with_bridge(
        &Bridge::discover()?,
        sources,
        model,
        options,
        previous,
        cancellation,
    )
}

fn transcribe_with_bridge(
    bridge: &Bridge,
    sources: &[AudioSource],
    model: &str,
    options: &TranscribeOptions<'_>,
    previous: &[TranscriptSegment],
    cancellation: &CancellationToken,
) -> Result<Vec<TranscriptSegment>> {
    if sources.is_empty() {
        return Err(message("Import audio before transcribing."));
    }
    let mut result = Vec::new();
    let reconciler = Reconciler::new(previous);
    let mut reused_ids = BTreeSet::new();
    let mut episode_offset = 0.0;
    for source in sources {
        let mut arguments = model_arguments("transcribe", model);
        arguments.extend(["--input".into(), source.source_path.as_os_str().to_owned()]);
        add_language(&mut arguments, options.language);
        if let Some(model) = options.alignment_model.filter(|value| !value.is_empty()) {
            arguments.extend(["--alignment-model".into(), model.into()]);
        }
        // The sidecar decodes the original file (including initial silence). It
        // returns source-clock times. Only this boundary adds the episode offset.
        let raw: Value = bridge.invoke(&arguments, cancellation)?;
        let projected = project_transcript(&raw, source, episode_offset, options.word_timestamps)?;
        for mut segment in projected {
            let candidates = reconciler.identity_candidates(&segment);
            let exact = match candidates.as_slice() {
                [old] if reused_ids.insert(old.id.clone()) => Some(*old),
                _ => None,
            };
            if let Some(old) = exact {
                segment.id.clone_from(&old.id);
                segment.speaker.clone_from(&old.speaker);
                preserve_word_ids(&mut segment, old);
                for (key, value) in &old.extensions {
                    if key != "avid_core" {
                        segment.extensions.insert(key.clone(), value.clone());
                    }
                }
            } else if let Some(speaker) = reconciler.unambiguous_speaker(&segment) {
                segment.speaker = speaker;
            }
            result.push(segment);
        }
        episode_offset += source.duration_seconds;
    }
    preserve_replaced_metadata(&mut result, previous)?;
    Ok(result)
}

struct Reconciler<'a> {
    previous: &'a [TranscriptSegment],
    origins: Vec<Option<encap_core::TranscriptOrigin>>,
    by_text: BTreeMap<(String, String), Vec<usize>>,
}
impl<'a> Reconciler<'a> {
    fn new(previous: &'a [TranscriptSegment]) -> Self {
        let origins: Vec<_> = previous
            .iter()
            .map(TranscriptSegment::transcription_origin)
            .collect();
        let mut by_text: BTreeMap<(String, String), Vec<usize>> = BTreeMap::new();
        for (index, (old, origin)) in previous.iter().zip(&origins).enumerate() {
            let key = match origin {
                Some(origin) => (
                    origin.source_id.clone(),
                    origin.transcript["segments"][0]["text"]
                        .as_str()
                        .unwrap_or(&old.text)
                        .to_owned(),
                ),
                None => (String::new(), old.text.clone()),
            };
            by_text.entry(key).or_default().push(index);
        }
        Self {
            previous,
            origins,
            by_text,
        }
    }

    fn identity_candidates(&self, new: &TranscriptSegment) -> Vec<&'a TranscriptSegment> {
        let Some(origin) = new.transcription_origin() else {
            return Vec::new();
        };
        let text = origin.transcript["segments"][0]["text"]
            .as_str()
            .unwrap_or(&new.text)
            .to_owned();
        let keys = [
            (origin.source_id.clone(), text),
            (String::new(), new.text.clone()),
        ];
        keys.into_iter()
            .filter_map(|key| self.by_text.get(&key))
            .flatten()
            .filter_map(|&index| {
                let old = &self.previous[index];
                let close = |a: f64, b: f64| (a - b).abs() <= 0.25;
                let same_bounds = if let Some(old_origin) = &self.origins[index] {
                    ["start_seconds", "end_seconds"].iter().all(|key| {
                        match (
                            origin.transcript["segments"][0]
                                .get(key)
                                .and_then(Value::as_f64),
                            old_origin.transcript["segments"][0]
                                .get(key)
                                .and_then(Value::as_f64),
                        ) {
                            (Some(a), Some(b)) => close(a, b),
                            (None, None) => true,
                            _ => false,
                        }
                    })
                } else {
                    close(new.start_time_seconds, old.start_time_seconds)
                        && close(new.end_time_seconds, old.end_time_seconds)
                };
                same_bounds.then_some(old)
            })
            .collect()
    }

    fn unambiguous_speaker(&self, new: &TranscriptSegment) -> Option<String> {
        if new.end_time_seconds <= new.start_time_seconds {
            return None;
        }
        let origin = new.transcription_origin()?;
        let overlaps: Vec<_> = self
            .previous
            .iter()
            .zip(&self.origins)
            .filter_map(|(old, old_origin)| {
                let same_source = old_origin
                    .as_ref()
                    .is_none_or(|old_origin| old_origin.source_id == origin.source_id);
                (same_source
                    && old.start_time_seconds < new.end_time_seconds
                    && old.end_time_seconds > new.start_time_seconds)
                    .then_some(old)
            })
            .collect();
        let speaker = overlaps.first()?.speaker.trim();
        if speaker.is_empty() || overlaps.iter().any(|old| old.speaker.trim() != speaker) {
            return None;
        }
        let first = overlaps
            .iter()
            .map(|old| old.start_time_seconds)
            .fold(f64::INFINITY, f64::min);
        let last = overlaps
            .iter()
            .map(|old| old.end_time_seconds)
            .fold(0.0, f64::max);
        if new.start_time_seconds + 0.25 < first || new.end_time_seconds > last + 0.25 {
            return None;
        }
        Some(overlaps[0].speaker.clone())
    }
}

fn preserve_replaced_metadata(
    result: &mut [TranscriptSegment],
    previous: &[TranscriptSegment],
) -> Result<()> {
    if previous.is_empty() {
        return Ok(());
    }
    if result.is_empty() {
        return Err(message(
            "Recognition returned no text. The current transcript was preserved.",
        ));
    }
    let by_id: BTreeMap<_, _> = result
        .iter()
        .map(|segment| (segment.id.as_str(), segment))
        .collect();
    let replaced: Vec<_> = previous
        .iter()
        .filter(|old| by_id.get(old.id.as_str()).is_none_or(|new| **new != **old))
        .collect();
    if replaced.is_empty() {
        return Ok(());
    }
    let manual_labels_unmapped = previous.iter().any(|old| {
        !old.speaker.trim().is_empty()
            && !result.iter().any(|new| {
                new.speaker == old.speaker
                    && new.start_time_seconds < old.end_time_seconds
                    && new.end_time_seconds > old.start_time_seconds
            })
    });
    let mut origin = result[0]
        .transcription_origin()
        .ok_or_else(|| message("The source recognition record is missing."))?;
    // One history envelope per operation (never per segment) retains replaced
    // editable text, stable IDs, speaker names, opaque extensions and any older
    // history. Native clients preserve the entire avid_core origin JSON.
    origin.extensions.insert(
        "previous_transcript".into(),
        serde_json::to_value(replaced)?,
    );
    if manual_labels_unmapped {
        let warning = "Some existing speaker labels could not be mapped safely to the new segmentation. Review speaker assignments; the previous edited transcript and its labels are preserved in the transcription history.";
        origin.extensions.insert(
            "reconciliation_warning".into(),
            Value::String(warning.into()),
        );
        let event = serde_json::json!({"event":"progress","stage":"speaker-review-needed","message":warning});
        let _ = writeln!(std::io::stderr(), "{event}");
    }
    result[0].set_transcription_origin(origin);
    Ok(())
}

pub fn realign(
    sources: &[AudioSource],
    previous: &[TranscriptSegment],
    alignment_model: &str,
    language: Option<&str>,
    cancellation: &CancellationToken,
) -> Result<Vec<TranscriptSegment>> {
    realign_with_bridge(
        &Bridge::discover()?,
        sources,
        previous,
        alignment_model,
        language,
        cancellation,
    )
}

fn realign_with_bridge(
    bridge: &Bridge,
    sources: &[AudioSource],
    previous: &[TranscriptSegment],
    alignment_model: &str,
    language: Option<&str>,
    cancellation: &CancellationToken,
) -> Result<Vec<TranscriptSegment>> {
    if previous.is_empty() {
        return Err(message("There is no transcript to realign."));
    }
    // Fail before processing any source if the saved transcript cannot be mapped
    // reversibly to its source. Never apply timing to a guessed source or text.
    for segment in previous {
        let origin = segment.transcription_origin().ok_or_else(|| {
            message("This legacy transcript has no source provenance. Transcribe it with AVID Core before realigning; the current transcript was preserved.")
        })?;
        if !sources
            .iter()
            .any(|source| source.transcription_source_id() == origin.source_id)
        {
            return Err(message(
                "A transcript source is missing. The current transcript was preserved.",
            ));
        }
    }
    let operation = tempfile::tempdir().map_err(|error| {
        message(format!(
            "Could not create a private alignment operation: {error}"
        ))
    })?;
    let mut result = Vec::new();
    let mut episode_offset = 0.0;
    for source in sources {
        let retained: Vec<_> = previous
            .iter()
            .filter(|segment| {
                segment
                    .transcription_origin()
                    .is_some_and(|origin| origin.source_id == source.transcription_source_id())
            })
            .collect();
        if retained.is_empty() {
            episode_offset += source.duration_seconds;
            continue;
        }
        let mut raw = retained[0].transcription_origin().unwrap().transcript;
        let mut segments = Vec::with_capacity(retained.len());
        for segment in &retained {
            let origin = segment.transcription_origin().unwrap();
            let mut raw_segment = origin
                .transcript
                .get("segments")
                .and_then(Value::as_array)
                .and_then(|items| items.first())
                .cloned()
                .ok_or_else(|| message("The saved source transcription record is invalid."))?;
            raw_segment["text"] = Value::String(segment.text.clone());
            // Always align the edited text; stale word boundaries are not inputs.
            raw_segment["words"] = Value::Array(Vec::new());
            segments.push(raw_segment);
        }
        raw["segments"] = Value::Array(segments);
        let transcript_file = operation
            .path()
            .join(format!("{}.json", uuid::Uuid::new_v4()));
        fs::write(&transcript_file, serde_json::to_vec(&raw)?)
            .map_err(|error| message(format!("Could not stage alignment text: {error}")))?;
        let mut arguments = model_arguments("realign", alignment_model);
        arguments.extend([
            "--input".into(),
            source.source_path.as_os_str().to_owned(),
            "--transcript".into(),
            transcript_file.as_os_str().to_owned(),
        ]);
        add_language(&mut arguments, language);
        let aligned: Value = bridge.invoke(&arguments, cancellation)?;
        let projected = project_transcript(&aligned, source, episode_offset, true)?;
        if projected.len() != retained.len()
            || projected
                .iter()
                .zip(&retained)
                .any(|(new, old)| new.text != old.text)
        {
            return Err(message("Alignment changed the transcript text or segment count. The current transcript was preserved."));
        }
        for (mut new, old) in projected.into_iter().zip(retained) {
            new.id.clone_from(&old.id);
            new.speaker.clone_from(&old.speaker);
            preserve_word_ids(&mut new, old);
            let old_origin = old.transcription_origin().unwrap();
            let mut new_origin = new.transcription_origin().unwrap();
            let alignment_record = new_origin.transcript;
            new_origin.transcript = old_origin.transcript;
            new_origin.extensions.extend(old_origin.extensions);
            new_origin
                .extensions
                .insert("alignment_record".into(), alignment_record);
            new.set_transcription_origin(new_origin);
            for (key, value) in &old.extensions {
                if key != "avid_core" {
                    new.extensions.insert(key.clone(), value.clone());
                }
            }
            result.push(new);
        }
        episode_offset += source.duration_seconds;
    }
    Ok(result)
}

/// Group current episode-clock words using AVID Core's caption behavior. This
/// projection is temporary: no recognition or alignment provenance is rewritten.
pub fn render_captions(
    segments: &[TranscriptSegment],
    format: &str,
    cancellation: &CancellationToken,
) -> Result<String> {
    if !matches!(format, "srt" | "vtt") {
        return Err(message("Caption format must be srt or vtt."));
    }
    let raw = caption_projection(segments)?;
    let operation = tempfile::tempdir().map_err(|error| {
        message(format!(
            "Could not create a private caption operation: {error}"
        ))
    })?;
    let transcript_file = operation.path().join("episode-transcript.json");
    fs::write(&transcript_file, serde_json::to_vec(&raw)?)
        .map_err(|error| message(format!("Could not stage caption words: {error}")))?;
    Bridge::discover()?.invoke(
        &[
            "captions".into(),
            "--transcript".into(),
            transcript_file.as_os_str().to_owned(),
            "--format".into(),
            format.into(),
        ],
        cancellation,
    )
}

fn caption_projection(segments: &[TranscriptSegment]) -> Result<Value> {
    if segments.is_empty() {
        return Err(message("There is no transcript available for captions."));
    }
    let mut projected = Vec::new();
    for segment in segments {
        if segment.text.trim().is_empty() {
            continue;
        }
        if segment.words.is_empty()
            || segment.transcription_origin().is_some_and(|origin| {
                origin.timing_status != encap_core::TranscriptTimingStatus::Timed
            })
        {
            return Err(message("Word timing is unavailable or invalidated by an edit. Realign the transcript before exporting word captions."));
        }
        projected.push(serde_json::json!({
            "text": segment.text,
            "start_seconds": segment.start_time_seconds,
            "end_seconds": segment.end_time_seconds,
            "words": segment.words.iter().map(|word| serde_json::json!({
                "text": word.text,
                "start_seconds": word.start_time_seconds,
                "end_seconds": word.end_time_seconds,
            })).collect::<Vec<_>>(),
        }));
    }
    if projected.is_empty() {
        return Err(message("There are no timed words available for captions."));
    }
    Ok(serde_json::json!({
        "segments": projected,
        "provenance": {"engine_id":"encap-episode-projection", "model_id":"current-edited-transcript"},
    }))
}

fn preserve_word_ids(new: &mut TranscriptSegment, old: &TranscriptSegment) {
    for (word, previous) in new.words.iter_mut().zip(&old.words) {
        if word.text == previous.text {
            word.id.clone_from(&previous.id);
            word.extensions.extend(previous.extensions.clone());
        }
    }
}

fn add_language(arguments: &mut Vec<OsString>, language: Option<&str>) {
    if let Some(language) = language.filter(|value| !value.trim().is_empty()) {
        arguments.extend(["--language".into(), language.into()]);
    }
}

#[derive(Deserialize)]
struct SourceTranscript {
    segments: Vec<SourceSegment>,
    provenance: Provenance,
}

#[derive(Deserialize)]
struct Provenance {
    engine_id: String,
    model_id: String,
}

#[derive(Deserialize)]
struct SourceSegment {
    text: String,
    #[serde(default)]
    words: Vec<SourceWord>,
    start_seconds: Option<f64>,
    end_seconds: Option<f64>,
}

#[derive(Deserialize)]
struct SourceWord {
    text: String,
    start_seconds: Option<f64>,
    end_seconds: Option<f64>,
    confidence: Option<f64>,
}

fn timestamp_pair(
    start: Option<f64>,
    end: Option<f64>,
    duration: f64,
) -> Result<Option<(f64, f64)>> {
    match (start, end) {
        (None, None) => Ok(None),
        (Some(start), Some(end)) if start.is_finite() && end.is_finite() && start >= 0.0 && end >= start && end <= duration + 0.5 => Ok(Some((start, end))),
        _ => Err(message("AVID Core returned an invalid source timestamp. The existing transcript was preserved.")),
    }
}

fn project_transcript(
    raw: &Value,
    source: &AudioSource,
    episode_offset: f64,
    include_words: bool,
) -> Result<Vec<TranscriptSegment>> {
    let record: SourceTranscript = serde_json::from_value(raw.clone()).map_err(|error| {
        message(format!(
            "AVID Core returned an invalid transcription record: {error}"
        ))
    })?;
    if record.provenance.engine_id.is_empty() || record.provenance.model_id.is_empty() {
        return Err(message(
            "AVID Core returned an incomplete model provenance record.",
        ));
    }
    if !source.duration_seconds.is_finite()
        || source.duration_seconds < 0.0
        || !episode_offset.is_finite()
    {
        return Err(message("The source timeline is invalid."));
    }
    let raw_segments = raw["segments"].as_array().unwrap();
    let recognition_segments = raw.get("recognition_segments").and_then(Value::as_array);
    // Preserve shared and unknown metadata without cloning every transcript segment
    // for each output record. Per-segment arrays are attached below.
    let record_template = Value::Object(
        raw.as_object()
            .unwrap()
            .iter()
            .filter(|(key, _)| {
                key.as_str() != "segments"
                    && (key.as_str() != "recognition_segments" || recognition_segments.is_none())
            })
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect(),
    );
    let mut output = Vec::with_capacity(record.segments.len());
    for (index, item) in record.segments.into_iter().enumerate() {
        let segment_time = timestamp_pair(
            item.start_seconds,
            item.end_seconds,
            source.duration_seconds,
        )?;
        let mut words = Vec::new();
        let mut first_word_time = None;
        let mut last_word_time = None;
        let mut previous_start = 0.0;
        let mut complete_word_timing = true;
        for word in item.words {
            if word.confidence.is_some_and(|confidence| {
                !confidence.is_finite() || !(0.0..=1.0).contains(&confidence)
            }) {
                return Err(message("AVID Core returned an invalid word confidence."));
            }
            if let Some((start, end)) = timestamp_pair(
                word.start_seconds,
                word.end_seconds,
                source.duration_seconds,
            )? {
                if start < previous_start {
                    return Err(message("AVID Core returned unordered source word times."));
                }
                previous_start = start;
                first_word_time.get_or_insert(start);
                last_word_time = Some(end);
                if include_words {
                    words.push(TranscriptWord {
                        id: uuid::Uuid::new_v4().simple().to_string(),
                        start_time_seconds: episode_offset + start,
                        end_time_seconds: episode_offset + end,
                        text: word.text,
                        extensions: BTreeMap::new(),
                    });
                }
            } else {
                complete_word_timing = false;
            }
        }
        if !complete_word_timing {
            words.clear();
        }
        let bounds = segment_time.or(first_word_time.zip(last_word_time));
        let (start, end) = bounds.unwrap_or((0.0, 0.0));
        let mut original_record = record_template.clone();
        original_record["segments"] = Value::Array(vec![raw_segments[index].clone()]);
        let mut origin_extensions = BTreeMap::new();
        if let Some(recognition) = recognition_segments {
            let recognition_segment = recognition.get(index).ok_or_else(|| {
                message("AVID Core returned mismatched recognition and alignment segment counts.")
            })?;
            if recognition.len() != raw_segments.len() {
                return Err(message(
                    "AVID Core returned mismatched recognition and alignment segment counts.",
                ));
            }
            origin_extensions.insert("alignment_record".into(), original_record.clone());
            original_record["segments"] = Value::Array(vec![recognition_segment.clone()]);
            original_record
                .as_object_mut()
                .unwrap()
                .remove("alignment_provenance");
        }
        let mut segment = TranscriptSegment {
            id: uuid::Uuid::new_v4().simple().to_string(),
            start_time_seconds: episode_offset + start,
            end_time_seconds: episode_offset + end,
            speaker: String::new(),
            text: item.text,
            words,
            extensions: BTreeMap::new(),
        };
        // Reject helper output that the project model cannot save. A successful
        // process response must not replace the user's transcript with times
        // that only fail validation on the next save/export operation.
        if !encap_core::is_valid_duration(segment.start_time_seconds)
            || !encap_core::is_valid_duration(segment.end_time_seconds)
            || segment.end_time_seconds < segment.start_time_seconds
            || segment.words.iter().any(|word| {
                word.start_time_seconds < segment.start_time_seconds
                    || word.end_time_seconds > segment.end_time_seconds
            })
        {
            return Err(message("AVID Core returned timing outside the project or segment bounds. The existing transcript was preserved."));
        }
        segment.set_transcription_origin(encap_core::TranscriptOrigin {
            version: 1,
            source_id: source.transcription_source_id(),
            source_duration_seconds: source.duration_seconds,
            source_timeline_offset_seconds: episode_offset,
            source_offset_seconds: 0.0,
            segment_index: index,
            timing_status: if bounds.is_some() {
                encap_core::TranscriptTimingStatus::Timed
            } else {
                encap_core::TranscriptTimingStatus::Untimed
            },
            transcript: original_record,
            extensions: origin_extensions,
        });
        output.push(segment);
    }
    Ok(output)
}

fn helper_path() -> Result<PathBuf> {
    // A deliberate developer override is never a discovery scan of third-party
    // applications, model caches or PATH. Release packages use their own helper.
    #[cfg(debug_assertions)]
    if let Some(path) = std::env::var_os("ENCAP_AVID_TRANSCRIBER") {
        let path = PathBuf::from(path);
        return if path.is_absolute() && path.is_file() {
            Ok(path)
        } else {
            Err(message(
                "ENCAP_AVID_TRANSCRIBER must name an existing absolute helper path.",
            ))
        };
    }
    if !cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        return Err(message(PLATFORM_REASON));
    }
    #[cfg(target_os = "macos")]
    {
        let version = Command::new("/usr/bin/sw_vers")
            .arg("-productVersion")
            .output()
            .map_err(|error| {
                message(format!("Could not determine macOS compatibility: {error}"))
            })?;
        let major = String::from_utf8_lossy(&version.stdout)
            .trim()
            .split('.')
            .next()
            .and_then(|part| part.parse::<u32>().ok());
        if !version.status.success() || major.is_none_or(|major| major < 14) {
            return Err(message(PLATFORM_REASON));
        }
    }
    let executable = std::env::current_exe()
        .map_err(|error| message(format!("Could not locate the application runtime: {error}")))?;
    let directory = executable
        .parent()
        .ok_or_else(|| message("The application runtime path is invalid."))?;
    [directory.join("avid-transcriber"), directory.join("../Resources/avid-transcriber")]
        .into_iter().find(|path| path.is_file()).ok_or_else(|| message("The packaged AVID Core transcription helper is missing. Rebuild or reinstall EnCAP; legacy transcription engines are no longer used."))
}

struct Bridge {
    helper: PathBuf,
}
impl Bridge {
    fn discover() -> Result<Self> {
        Ok(Self {
            helper: helper_path()?,
        })
    }
    fn invoke<T: serde::de::DeserializeOwned>(
        &self,
        arguments: &[OsString],
        cancellation: &CancellationToken,
    ) -> Result<T> {
        let bytes = run_helper(&self.helper, arguments, cancellation)?;
        serde_json::from_slice(&bytes).map_err(|error| {
            message(format!(
                "AVID Core returned an invalid JSON response: {error}"
            ))
        })
    }
}

struct OwnedChild(Child);
impl Drop for OwnedChild {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

fn run_helper(
    helper: &Path,
    arguments: &[OsString],
    cancellation: &CancellationToken,
) -> Result<Vec<u8>> {
    if cancellation.is_cancelled() {
        return Err(message("AVID Core operation was cancelled safely."));
    }
    let operation = tempfile::tempdir().map_err(|error| {
        message(format!(
            "Could not create a private transcription operation: {error}"
        ))
    })?;
    let stdout_path = operation.path().join("stdout.json");
    let stderr_path = operation.path().join("stderr.log");
    let stdout = fs::File::create(&stdout_path)
        .map_err(|error| message(format!("Could not stage transcription output: {error}")))?;
    let stderr = fs::File::create(&stderr_path).map_err(|error| {
        message(format!(
            "Could not stage transcription diagnostics: {error}"
        ))
    })?;
    let mut diagnostics = fs::File::open(&stderr_path)
        .map_err(|error| message(format!("Could not monitor transcription progress: {error}")))?;
    let mut child = OwnedChild(
        Command::new(helper)
            .args(arguments)
            .stdin(Stdio::null())
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr))
            .spawn()
            .map_err(|error| {
                message(format!(
                    "AVID Core transcription helper could not start: {error}"
                ))
            })?,
    );
    let mut cancel_started = None;
    let mut pending = Vec::new();
    let status = loop {
        forward_progress(&mut diagnostics, &mut pending)?;
        if cancellation.is_cancelled() && cancel_started.is_none() {
            request_cancel(&mut child.0);
            cancel_started = Some(Instant::now());
        }
        if cancel_started.is_some_and(|start| start.elapsed() >= CANCEL_GRACE) {
            let _ = child.0.kill();
        }
        if let Some(status) = child.0.try_wait().map_err(|error| {
            message(format!(
                "Could not monitor the owned AVID Core operation: {error}"
            ))
        })? {
            break status;
        }
        if fs::metadata(&stdout_path).is_ok_and(|metadata| metadata.len() > MAX_RESPONSE_BYTES) {
            return Err(message(
                "AVID Core transcription exceeded the supported response size.",
            ));
        }
        std::thread::sleep(Duration::from_millis(30));
    };
    forward_progress(&mut diagnostics, &mut pending)?;
    if cancellation.is_cancelled() {
        return Err(message("AVID Core operation was cancelled safely. Cleanup was awaited; an unresponsive helper is terminated after 15 seconds."));
    }
    let length = fs::metadata(&stdout_path)
        .map_err(|error| message(format!("Could not read AVID Core output: {error}")))?
        .len();
    if length > MAX_RESPONSE_BYTES {
        return Err(message(
            "AVID Core transcription exceeded the supported response size.",
        ));
    }
    let bytes = fs::read(&stdout_path)
        .map_err(|error| message(format!("Could not read AVID Core output: {error}")))?;
    if !status.success() {
        emit_failure_diagnostics(&stderr_path);
        let detail = serde_json::from_slice::<Value>(&bytes).ok().and_then(|value| value.get("error").and_then(Value::as_str).map(str::to_owned)).unwrap_or_else(|| "The helper failed without a valid error response. Reinstall or rebuild the AVID Core helper and its resources.".into());
        return Err(message(detail));
    }
    Ok(bytes)
}

fn emit_failure_diagnostics(path: &Path) {
    // Native loaders and SDKs may abort before a machine-readable error exists.
    // Retain only a bounded tail on stderr, then discard the owned operation
    // directory. Raw diagnostics never enter the one-value stdout contract.
    let Ok(mut file) = fs::File::open(path) else {
        return;
    };
    let Ok(length) = file.metadata().map(|metadata| metadata.len()) else {
        return;
    };
    let start = length.saturating_sub(MAX_FAILURE_DIAGNOSTIC_BYTES as u64);
    if file.seek(SeekFrom::Start(start)).is_err() {
        return;
    }
    let mut tail = Vec::with_capacity(MAX_FAILURE_DIAGNOSTIC_BYTES);
    if file
        .take(MAX_FAILURE_DIAGNOSTIC_BYTES as u64)
        .read_to_end(&mut tail)
        .is_err()
    {
        return;
    }
    let lossy = String::from_utf8_lossy(&tail);
    let mut diagnostics = lossy
        .lines()
        .filter(|line| {
            // Structured progress already crossed this boundary while the process
            // ran; avoid repeating it as a native runtime failure diagnostic.
            !serde_json::from_str::<Value>(line)
                .ok()
                .is_some_and(|event| event.get("event").and_then(Value::as_str) == Some("progress"))
        })
        .collect::<Vec<_>>()
        .join("\n");
    if diagnostics.trim().is_empty() {
        return;
    }
    // Lossy UTF-8 conversion can expand invalid bytes; cap the emitted text too.
    if diagnostics.len() > MAX_FAILURE_DIAGNOSTIC_BYTES {
        let mut boundary = diagnostics.len() - MAX_FAILURE_DIAGNOSTIC_BYTES;
        while !diagnostics.is_char_boundary(boundary) {
            boundary += 1;
        }
        diagnostics = diagnostics.split_off(boundary);
    }
    let _ = writeln!(
        std::io::stderr(),
        "[AVID Core helper failure diagnostics; bounded tail]\n{diagnostics}"
    );
}

fn forward_progress(file: &mut fs::File, pending: &mut Vec<u8>) -> Result<()> {
    let mut buffer = [0_u8; 8192];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|error| message(format!("Could not read AVID Core progress: {error}")))?;
        if count == 0 {
            break;
        }
        pending.extend_from_slice(&buffer[..count]);
        while let Some(newline) = pending.iter().position(|byte| *byte == b'\n') {
            let line: Vec<u8> = pending.drain(..=newline).collect();
            // Structured progress alone crosses the engine event boundary. SDK
            // diagnostics remain in the private operation log, never on stdout.
            if serde_json::from_slice::<Value>(&line)
                .ok()
                .is_some_and(|event| event.get("event").and_then(Value::as_str) == Some("progress"))
            {
                let _ = std::io::stderr().lock().write_all(&line);
            }
        }
        if pending.len() > 1024 * 1024 {
            pending.clear();
        }
    }
    // Reads from a regular file keep the cursor at the current end and observe
    // subsequent appends; no pipe fills while large inference results are written.
    Ok(())
}

#[cfg(unix)]
fn request_cancel(child: &mut Child) {
    unsafe extern "C" {
        fn kill(pid: i32, signal: i32) -> i32;
    }
    // Only this owned child's PID receives SIGTERM. Swift handles it by cancelling
    // and awaiting the operation task (including model unload and lease release).
    unsafe {
        kill(child.id() as i32, 15);
    }
}
#[cfg(not(unix))]
fn request_cancel(child: &mut Child) {
    let _ = child.kill();
}
fn message(value: impl Into<String>) -> EncapError {
    EncapError::Message(value.into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn source(path: &str, duration: f64) -> AudioSource {
        AudioSource {
            source_path: PathBuf::from(path),
            display_name: "source".into(),
            duration_seconds: duration,
            stored_path: None,
            extensions: BTreeMap::new(),
        }
    }

    fn record() -> Value {
        json!({
            "language": "en", "provenance": {"engine_id":"whisperkit", "model_id":"whisper-large-v3"},
            "segments": [{"text":"Hello world.","start_seconds":2.5,"end_seconds":4.0,
                "words":[{"text":"Hello", "start_seconds":2.5,"end_seconds":3.0,"confidence":0.9,"timing_method":"recognizer"},
                    {"text":"world.", "start_seconds":3.2,"end_seconds":4.0,"timing_method":"recognizer"}]}]
        })
    }

    #[test]
    fn helper_words_outside_segment_bounds_are_rejected() {
        let mut raw = record();
        raw["segments"][0]["words"][0]["start_seconds"] = json!(1.0);
        assert!(project_transcript(&raw, &source("clip", 10.0), 0.0, true).is_err());
    }

    #[test]
    fn projected_timeline_cannot_exceed_project_duration_limit() {
        assert!(project_transcript(
            &record(), &source("clip", 10.0), encap_core::MAX_DURATION_SECONDS, true,
        ).is_err());
    }

    #[test]
    fn source_clock_projects_exactly_once_and_preserves_immutable_record() {
        let raw = record();
        let segments = project_transcript(&raw, &source("delayed.wav", 10.0), 15.0, true).unwrap();
        assert_eq!(segments[0].start_time_seconds, 17.5);
        assert_eq!(segments[0].words[1].end_time_seconds, 19.0);
        let origin = segments[0].transcription_origin().unwrap();
        assert_eq!(origin.source_timeline_offset_seconds, 15.0);
        assert_eq!(origin.source_offset_seconds, 0.0);
        assert_eq!(origin.transcript, raw);
        assert_eq!(origin.source_id, "path:delayed.wav");
    }

    #[test]
    fn unknown_shared_metadata_and_per_segment_history_scale_linearly() {
        let mut raw = record();
        raw["future"] = json!({"opaque": [1,2,3]});
        let one = raw["segments"][0].clone();
        raw["segments"] = Value::Array(vec![one; 100]);
        let segments = project_transcript(&raw, &source("clip", 10.0), 0.0, true).unwrap();
        assert_eq!(segments.len(), 100);
        for (index, segment) in segments.iter().enumerate() {
            let origin = segment.transcription_origin().unwrap();
            assert_eq!(origin.segment_index, index);
            assert_eq!(origin.transcript["segments"].as_array().unwrap().len(), 1);
            assert_eq!(origin.transcript["future"], raw["future"]);
        }
        assert!(serde_json::to_vec(&segments).unwrap().len() < 200_000);
    }

    #[test]
    fn many_aligned_origins_preserve_shared_and_per_segment_metadata() {
        let mut raw = record();
        raw["future"] = json!({"opaque": [1, 2, 3], "nested": {"preserve": true}});
        let original = raw["segments"][0].clone();
        let mut recognition = Vec::new();
        let mut alignment = Vec::new();
        for index in 0..300 {
            let mut before = original.clone();
            before["text"] = json!(format!("recognition {index}"));
            before["future_segment"] = json!({"index": index});
            let mut after = before.clone();
            after["text"] = json!(format!("aligned {index}"));
            recognition.push(before);
            alignment.push(after);
        }
        raw["segments"] = Value::Array(alignment);
        raw["recognition_segments"] = Value::Array(recognition);
        raw["alignment_provenance"] = json!({"engine_id": "qwen", "future": "preserved"});
        let outputs = project_transcript(&raw, &source("clip", 10.0), 0.0, true).unwrap();
        assert_eq!(outputs.len(), 300);
        for (index, output) in outputs.iter().enumerate() {
            let origin = output.transcription_origin().unwrap();
            assert_eq!(origin.segment_index, index);
            assert_eq!(origin.transcript["future"], raw["future"]);
            assert_eq!(origin.transcript["provenance"], raw["provenance"]);
            assert_eq!(origin.transcript["segments"], json!([raw["recognition_segments"][index]]));
            assert!(origin.transcript.get("alignment_provenance").is_none());
            assert!(origin.transcript.get("recognition_segments").is_none());
            let aligned = &origin.extensions["alignment_record"];
            assert_eq!(aligned["future"], raw["future"]);
            assert_eq!(aligned["segments"], json!([raw["segments"][index]]));
            assert_eq!(aligned["alignment_provenance"], raw["alignment_provenance"]);
            assert!(aligned.get("recognition_segments").is_none());
        }
    }

    #[test]
    fn non_array_recognition_metadata_is_not_discarded() {
        let mut raw = record();
        raw["recognition_segments"] = json!({"future_encoding": true});
        let outputs = project_transcript(&raw, &source("clip", 10.0), 0.0, true).unwrap();
        let origin = outputs[0].transcription_origin().unwrap();
        assert_eq!(origin.transcript["recognition_segments"], raw["recognition_segments"]);
    }

    #[test]
    fn untimed_text_is_retained_without_manufactured_word_boundaries() {
        let raw = json!({"provenance":{"engine_id":"qwen","model_id":"qwen3-asr-1.7b-4bit"},
            "segments":[{"text":"Untimed é😀","words":[{"text":"Untimed"},{"text":"é😀"}]}]});
        let segments = project_transcript(&raw, &source("clip", 10.0), 20.0, true).unwrap();
        assert_eq!(segments[0].text, "Untimed é😀");
        assert!(segments[0].words.is_empty());
        assert_eq!(segments[0].start_time_seconds, 20.0);
        assert_eq!(segments[0].end_time_seconds, 20.0);
        assert_eq!(
            segments[0].transcription_origin().unwrap().timing_status,
            encap_core::TranscriptTimingStatus::Untimed
        );
        assert!(encap_core::validate_timed_transcript(&segments).is_err());
    }

    #[test]
    fn partial_word_timing_cannot_silently_omit_untimed_caption_words() {
        let mut raw = record();
        raw["segments"][0]["words"][1] = json!({"text":"world."});
        let segments = project_transcript(&raw, &source("clip", 10.0), 0.0, true).unwrap();
        assert!(segments[0].words.is_empty());
        assert_eq!(segments[0].transcription_origin().unwrap().transcript, raw);
    }

    #[test]
    fn rejects_malformed_timestamps_confidence_and_missing_provenance() {
        let source = source("clip", 10.0);
        for invalid in [json!(-1), json!(99), Value::Null] {
            let mut raw = record();
            raw["segments"][0]["words"][0]["start_seconds"] = invalid;
            assert!(project_transcript(&raw, &source, 0.0, true).is_err());
        }
        let mut raw = record();
        raw["segments"][0]["words"][0]["confidence"] = json!(1.1);
        assert!(project_transcript(&raw, &source, 0.0, true).is_err());
        raw = record();
        raw.as_object_mut().unwrap().remove("provenance");
        assert!(project_transcript(&raw, &source, 0.0, true).is_err());
    }

    #[test]
    fn caption_projection_uses_current_episode_times_once_and_rejects_text_edits() {
        let mut segments =
            project_transcript(&record(), &source("delayed", 10.0), 30.0, true).unwrap();
        let raw_before = segments[0].transcription_origin().unwrap().transcript;
        let projected = caption_projection(&segments).unwrap();
        assert_eq!(projected["segments"][0]["words"][0]["start_seconds"], 32.5);
        assert_eq!(projected["segments"][0]["words"][1]["end_seconds"], 34.0);
        assert_eq!(
            segments[0].transcription_origin().unwrap().transcript,
            raw_before
        );
        segments[0].text = "Edited".into();
        segments[0].invalidate_word_alignment();
        assert!(caption_projection(&segments)
            .unwrap_err()
            .to_string()
            .contains("Realign"));
    }

    #[cfg(unix)]
    fn fake_helper(script: &str) -> (tempfile::TempDir, Bridge) {
        use std::os::unix::fs::PermissionsExt;
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("fake helper; safe");
        fs::write(&path, format!("#!/bin/sh\n{script}\n")).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
        (directory, Bridge { helper: path })
    }

    #[cfg(unix)]
    #[test]
    fn helper_success_error_malformed_and_missing_runtime_are_typed() {
        let (_directory, bridge) =
            fake_helper("printf '[{\"id\":\"m\",\"name\":\"Model\",\"detail\":\"Local\"}]'");
        let providers: Vec<Provider> = bridge.invoke(&[], &CancellationToken::default()).unwrap();
        assert_eq!(providers[0].id, "m");
        let (_directory, bridge) =
            fake_helper("printf '{\"error\":\"Pinned hash mismatch\"}'; exit 1");
        let result: Result<Value> = bridge.invoke(&[], &CancellationToken::default());
        assert_eq!(result.unwrap_err().to_string(), "Pinned hash mismatch");
        let (_directory, bridge) = fake_helper("printf 'human readable output'");
        let result: Result<Value> = bridge.invoke(&[], &CancellationToken::default());
        assert!(result.unwrap_err().to_string().contains("invalid JSON"));
        let bridge = Bridge {
            helper: PathBuf::from("/missing/avid-transcriber"),
        };
        let result: Result<Value> = bridge.invoke(&[], &CancellationToken::default());
        assert!(result.unwrap_err().to_string().contains("could not start"));
    }

    #[cfg(unix)]
    #[test]
    fn paths_are_arguments_and_large_json_does_not_fill_a_pipe() {
        let (_directory, bridge) = fake_helper("printf '\"'; printf '%s' \"$1\"; printf '\"'");
        let path = "clip ; $(touch NOT_EXECUTED) `printf injected` \"name\"";
        // A fake JSON encoder strips quotes only for this test; arbitrary shell
        // metacharacters remain a single argument, never executable shell text.
        let path = path.replace('"', "'");
        let result: String = bridge
            .invoke(&[path.clone().into()], &CancellationToken::default())
            .unwrap();
        assert_eq!(result, path);
        let (_directory, bridge) = fake_helper(
            "printf '\"'; /usr/bin/head -c 2097152 /dev/zero | /usr/bin/tr '\\000' x; printf '\"'",
        );
        let large: String = bridge.invoke(&[], &CancellationToken::default()).unwrap();
        assert_eq!(large.len(), 2_097_152);
    }

    #[cfg(unix)]
    #[test]
    fn multi_source_transcription_maps_offsets_and_preserves_existing_ids_speaker() {
        let raw = record();
        let script = format!("cat <<'JSON'\n{raw}\nJSON");
        let (_directory, bridge) = fake_helper(&script);
        let sources = [
            source("first; $(echo nope).wav", 10.0),
            source("second.wav", 8.0),
        ];
        let mut existing = project_transcript(&raw, &sources[1], 10.0, true).unwrap();
        existing[0].id = "stable-segment".into();
        existing[0].speaker = "Manually named host".into();
        existing[0].words[0].id = "stable-word".into();
        let segments = transcribe_with_bridge(
            &bridge,
            &sources,
            DEFAULT_MODEL,
            &TranscribeOptions {
                word_timestamps: true,
                ..Default::default()
            },
            &existing,
            &CancellationToken::default(),
        )
        .unwrap();
        assert_eq!(segments.len(), 2);
        assert_eq!(segments[0].start_time_seconds, 2.5);
        assert_eq!(segments[1].start_time_seconds, 12.5);
        assert_eq!(segments[1].id, "stable-segment");
        assert_eq!(segments[1].words[0].id, "stable-word");
        assert_eq!(segments[1].speaker, "Manually named host");
    }

    #[cfg(unix)]
    #[test]
    fn shifted_segment_indices_never_cross_assign_ids_or_speakers() {
        let audio = source("clip", 10.0);
        let mut old = project_transcript(&record(), &audio, 0.0, true).unwrap();
        old[0].id = "retained-id".into();
        old[0].speaker = "Alice".into();
        let mut raw = record();
        let added = json!({"text":"New phrase.","start_seconds":0.0,"end_seconds":1.0,
            "words":[{"text":"New phrase.","start_seconds":0.0,"end_seconds":1.0}]});
        raw["segments"].as_array_mut().unwrap().insert(0, added);
        let (_directory, bridge) = fake_helper(&format!("cat <<'JSON'\n{raw}\nJSON"));
        let result = transcribe_with_bridge(
            &bridge,
            &[audio],
            DEFAULT_MODEL,
            &TranscribeOptions {
                word_timestamps: true,
                ..Default::default()
            },
            &old,
            &CancellationToken::default(),
        )
        .unwrap();
        assert_ne!(result[0].id, "retained-id");
        assert!(result[0].speaker.is_empty());
        assert_eq!(result[1].id, "retained-id");
        assert_eq!(result[1].speaker, "Alice");
        assert_eq!(result[1].transcription_origin().unwrap().segment_index, 1);
    }

    #[cfg(unix)]
    #[test]
    fn ambiguous_speaker_merge_preserves_history_and_requests_manual_review() {
        let audio = source("clip", 10.0);
        let mut raw_old = record();
        let mut second = raw_old["segments"][0].clone();
        second["text"] = json!("Second voice.");
        second["start_seconds"] = json!(4.0);
        second["end_seconds"] = json!(6.0);
        second["words"] = json!([]);
        raw_old["segments"].as_array_mut().unwrap().push(second);
        let mut previous = project_transcript(&raw_old, &audio, 0.0, true).unwrap();
        previous[0].speaker = "Alice".into();
        previous[1].speaker = "Bob".into();
        let mut merged = record();
        merged["segments"][0]["text"] = json!("Hello world. Second voice.");
        merged["segments"][0]["end_seconds"] = json!(6.0);
        let (_directory, bridge) = fake_helper(&format!("cat <<'JSON'\n{merged}\nJSON"));
        let result = transcribe_with_bridge(
            &bridge,
            &[audio],
            DEFAULT_MODEL,
            &TranscribeOptions::default(),
            &previous,
            &CancellationToken::default(),
        )
        .unwrap();
        assert!(result[0].speaker.is_empty());
        let origin = result[0].transcription_origin().unwrap();
        assert!(origin.extensions["reconciliation_warning"]
            .as_str()
            .unwrap()
            .contains("Review speaker"));
        assert_eq!(
            origin.extensions["previous_transcript"],
            serde_json::to_value(&previous).unwrap()
        );
    }

    #[cfg(unix)]
    #[test]
    fn edited_legacy_transcript_and_existing_history_are_preserved_once() {
        let audio = source("clip", 10.0);
        let prior: TranscriptSegment = serde_json::from_value(json!({"id":"legacy-edit","text":"My corrected wording.",
            "speaker":"Host","start_time_seconds":2.5,"end_time_seconds":4.0,"future":{"opaque":true}})).unwrap();
        let raw = record();
        let (_directory, bridge) = fake_helper(&format!("cat <<'JSON'\n{raw}\nJSON"));
        let first = transcribe_with_bridge(
            &bridge,
            std::slice::from_ref(&audio),
            DEFAULT_MODEL,
            &TranscribeOptions::default(),
            std::slice::from_ref(&prior),
            &CancellationToken::default(),
        )
        .unwrap();
        assert_eq!(first[0].speaker, "Host");
        let history =
            first[0].transcription_origin().unwrap().extensions["previous_transcript"].clone();
        assert_eq!(history, serde_json::to_value(vec![prior]).unwrap());
        let second = transcribe_with_bridge(
            &bridge,
            &[audio],
            DEFAULT_MODEL,
            &TranscribeOptions::default(),
            &first,
            &CancellationToken::default(),
        )
        .unwrap();
        let origin = second[0].transcription_origin().unwrap();
        assert_eq!(
            origin.extensions["previous_transcript"][0]["avid_core"]["previous_transcript"],
            history
        );
        assert_eq!(
            second
                .iter()
                .filter(|segment| segment
                    .transcription_origin()
                    .unwrap()
                    .extensions
                    .contains_key("previous_transcript"))
                .count(),
            1
        );
    }

    #[test]
    fn combined_alignment_keeps_initial_recognition_and_separate_aligned_record() {
        let mut raw = record();
        raw["recognition_segments"] = raw["segments"].clone();
        raw["segments"][0]["words"][0]["start_seconds"] = json!(2.6);
        raw["alignment_provenance"] = json!({"engine_id":"aligner","model_id":"qwen", "model_installation_id":"exact-manifest-id"});
        let result = project_transcript(&raw, &source("clip", 10.0), 20.0, true).unwrap();
        let origin = result[0].transcription_origin().unwrap();
        assert_eq!(origin.transcript, record());
        assert_eq!(
            origin.extensions["alignment_record"]["segments"][0]["words"][0]["start_seconds"],
            2.6
        );
        assert!(origin.transcript.get("recognition_segments").is_none());
        assert!(origin.extensions["alignment_record"]
            .get("recognition_segments")
            .is_none());
        assert_eq!(
            origin.extensions["alignment_record"]["alignment_provenance"]["model_installation_id"],
            "exact-manifest-id"
        );
    }

    #[cfg(unix)]
    #[test]
    fn cancellation_is_forwarded_to_owned_helper_and_waits_for_cleanup() {
        let directory = tempfile::tempdir().unwrap();
        let cleanup = directory.path().join("cleanup");
        let script = format!(
            "trap 'printf cleaned > {} ; exit 0' TERM\nwhile :; do /bin/sleep 0.05; done",
            cleanup.display()
        );
        let (_helper_directory, bridge) = fake_helper(&script);
        let token = CancellationToken::default();
        let worker_token = token.clone();
        let start = Instant::now();
        let worker = std::thread::spawn(move || bridge.invoke::<Value>(&[], &worker_token));
        std::thread::sleep(Duration::from_millis(100));
        token.cancel();
        assert!(worker
            .join()
            .unwrap()
            .unwrap_err()
            .to_string()
            .contains("cancelled safely"));
        assert_eq!(fs::read_to_string(cleanup).unwrap(), "cleaned");
        assert!(start.elapsed() < Duration::from_secs(3));
    }

    #[cfg(unix)]
    #[test]
    fn cancelled_or_failed_source_never_replaces_prior_transcript() {
        let raw = record();
        let prior = project_transcript(&raw, &source("clip", 10.0), 0.0, true).unwrap();
        let (_directory, bridge) =
            fake_helper("printf '{\"error\":\"Local model missing\"}'; exit 1");
        assert!(transcribe_with_bridge(
            &bridge,
            &[source("clip", 10.0)],
            DEFAULT_MODEL,
            &TranscribeOptions::default(),
            &prior,
            &CancellationToken::default()
        )
        .is_err());
        assert_eq!(prior[0].text, "Hello world.");
        assert_eq!(prior[0].transcription_origin().unwrap().transcript, raw);
        let token = CancellationToken::default();
        token.cancel();
        assert!(transcribe_with_bridge(
            &bridge,
            &[source("clip", 10.0)],
            DEFAULT_MODEL,
            &TranscribeOptions::default(),
            &prior,
            &token
        )
        .is_err());
    }

    #[cfg(unix)]
    #[test]
    fn realignment_preserves_edited_text_id_speaker_and_recognition_provenance() {
        let source = source("clip", 10.0);
        let mut edited = project_transcript(&record(), &source, 0.0, true).unwrap();
        edited[0].text = "Edited words.".into();
        edited[0].speaker = "Host".into();
        edited[0].invalidate_word_alignment();
        let mut aligned = record();
        aligned["segments"][0]["text"] = json!("Edited words.");
        aligned["segments"][0]["words"][0]["text"] = json!("Edited");
        aligned["segments"][0]["words"][1]["text"] = json!("words.");
        aligned["alignment_provenance"] =
            json!({"engine_id":"qwen-aligner","model_id":"qwen3-forced-aligner-0.6b-4bit"});
        let script = format!("cat <<'JSON'\n{aligned}\nJSON");
        let (_directory, bridge) = fake_helper(&script);
        let result = realign_with_bridge(
            &bridge,
            &[source],
            &edited,
            "qwen3-forced-aligner-0.6b-4bit",
            Some("en"),
            &CancellationToken::default(),
        )
        .unwrap();
        assert_eq!(result[0].id, edited[0].id);
        assert_eq!(result[0].speaker, "Host");
        assert_eq!(result[0].text, "Edited words.");
        assert_eq!(result[0].words.len(), 2);
        let origin = result[0].transcription_origin().unwrap();
        assert_eq!(origin.transcript["provenance"], record()["provenance"]);
        assert_eq!(origin.transcript, record());
        assert_eq!(
            origin.extensions["alignment_record"]["alignment_provenance"],
            aligned["alignment_provenance"]
        );
        assert_eq!(
            origin.extensions["alignment_record"]["segments"][0]["text"],
            "Edited words."
        );
    }
}
