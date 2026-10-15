use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::PathBuf;
use uuid::Uuid;

fn default_schema() -> u64 {
    2
}

/// Maximum permitted duration for any audio source, chapter, segment, or aggregate project timeline.
/// Bounded to 1 year (31,536,000 seconds), which protects 32-bit integer conversions (max ~2.14B seconds),
/// microsecond scaling (Linux MPRIS), and 100ns scaling (Windows SMTC) while accommodating legitimate
/// recordings and multi-day projects without arbitrary truncation.
pub const MAX_DURATION_SECONDS: f64 = 86_400.0 * 365.0;

#[inline]
pub fn is_valid_duration(seconds: f64) -> bool {
    seconds.is_finite() && seconds >= 0.0 && seconds <= MAX_DURATION_SECONDS
}

#[inline]
pub fn is_valid_chapter_duration(seconds: f64) -> bool {
    seconds.is_finite() && seconds > 0.0 && seconds <= MAX_DURATION_SECONDS
}

pub use avid_core::{VideoProjectState, VideoSettings};

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkspaceMode {
    #[default]
    #[serde(alias = "assemble", alias = "process", alias = "process_audio")]
    Audio,
    #[serde(alias = "transcribe")]
    Transcript,
    Video,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct TranscriptWord {
    #[serde(default = "new_id")]
    pub id: String,
    pub start_time_seconds: f64,
    pub end_time_seconds: f64,
    #[serde(default)]
    pub text: String,
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct TranscriptSettings {
    #[serde(default)]
    pub include_word_timestamps: bool,
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

fn default_project_title() -> String {
    "Untitled".into()
}
fn default_output_format() -> String {
    "mp3".into()
}
fn default_quality() -> String {
    "320k".into()
}
fn default_encoder() -> String {
    "lame".into()
}
fn default_channels() -> u8 {
    2
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct EpisodeMetadata {
    #[serde(default)]
    pub podcast_title: String,
    #[serde(default)]
    pub episode_title: String,
    #[serde(default)]
    pub summary: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub artwork_path: Option<PathBuf>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub artwork_stored_path: Option<String>,
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AudioSource {
    pub source_path: PathBuf,
    #[serde(default)]
    pub display_name: String,
    pub duration_seconds: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stored_path: Option<String>,
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Chapter {
    #[serde(default = "new_id")]
    pub id: String,
    pub start_time_seconds: f64,
    pub duration_seconds: f64,
    pub chapter_number: u32,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub link_url: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub image_path: Option<PathBuf>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub image_stored_path: Option<String>,
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TranscriptSegment {
    #[serde(default = "new_id")]
    pub id: String,
    pub start_time_seconds: f64,
    pub end_time_seconds: f64,
    #[serde(default)]
    pub speaker: String,
    #[serde(default)]
    pub text: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub words: Vec<TranscriptWord>,
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ExportSettings {
    #[serde(default = "default_output_format")]
    pub output_format: String,
    #[serde(default = "default_quality")]
    pub quality_preset: String,
    #[serde(default = "default_encoder")]
    pub encoder: String,
    #[serde(default = "default_channels")]
    pub channels: u8,
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

impl Default for ExportSettings {
    fn default() -> Self {
        Self {
            output_format: default_output_format(),
            quality_preset: default_quality(),
            encoder: default_encoder(),
            channels: default_channels(),
            extensions: BTreeMap::new(),
        }
    }
}

impl ExportSettings {
    pub fn extension(&self) -> &'static str {
        match self.output_format.to_ascii_lowercase().as_str() {
            "aac" | "m4a" => "m4a",
            _ => "mp3",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ProjectDocument {
    #[serde(default = "default_schema")]
    pub schema_version: u64,
    #[serde(default = "default_project_title")]
    pub project_title: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_folder: Option<PathBuf>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub project_path: Option<PathBuf>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub working_dir: Option<PathBuf>,
    #[serde(default)]
    pub metadata: EpisodeMetadata,
    #[serde(default)]
    pub audio_sources: Vec<AudioSource>,
    #[serde(default)]
    pub chapters: Vec<Chapter>,
    #[serde(default)]
    pub transcript_segments: Vec<TranscriptSegment>,
    #[serde(default)]
    pub transcript_settings: TranscriptSettings,
    #[serde(default)]
    pub export_settings: ExportSettings,
    #[serde(default, alias = "workspace")]
    pub active_mode: WorkspaceMode,
    #[serde(default)]
    pub video: VideoProjectState,
    /// Opaque engine-boundary state used to preserve unknown manifest fields
    /// through native clients that intentionally expose only known fields.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub compatibility_payload: Option<String>,
    /// Unknown top-level manifest fields are retained across open/save cycles.
    #[serde(flatten)]
    pub extensions: BTreeMap<String, Value>,
}

impl Default for ProjectDocument {
    fn default() -> Self {
        Self {
            schema_version: default_schema(),
            project_title: default_project_title(),
            source_folder: None,
            project_path: None,
            working_dir: None,
            metadata: EpisodeMetadata::default(),
            audio_sources: Vec::new(),
            chapters: Vec::new(),
            transcript_segments: Vec::new(),
            transcript_settings: TranscriptSettings::default(),
            export_settings: ExportSettings::default(),
            active_mode: WorkspaceMode::Audio,
            video: VideoProjectState::default(),
            compatibility_payload: None,
            extensions: BTreeMap::new(),
        }
    }
}

impl ProjectDocument {
    pub fn output_basename(&self) -> String {
        let candidate = [
            self.metadata.episode_title.trim(),
            self.project_title.trim(),
        ]
        .into_iter()
        .find(|value| !value.is_empty())
        .unwrap_or("encap-output");
        let mapped: String = candidate
            .chars()
            .map(|c| {
                if c.is_alphanumeric() || matches!(c, '-' | '_' | ' ') {
                    c
                } else {
                    '-'
                }
            })
            .collect();
        let result = mapped.split_whitespace().collect::<Vec<_>>().join("-");
        if result.is_empty() {
            "encap-output".into()
        } else {
            result
        }
    }

    pub fn validate(&self) -> crate::Result<()> {
        if self.schema_version != 2 {
            return Err(crate::EncapError::UnsupportedSchema {
                found: self.schema_version,
                supported: 2,
            });
        }
        if !matches!(self.export_settings.channels, 1 | 2) {
            return Err(crate::EncapError::Message(
                "Audio channels must be mono or stereo.".into(),
            ));
        }
        let format = self.export_settings.output_format.to_ascii_lowercase();
        if !matches!(format.as_str(), "mp3" | "aac" | "m4a") {
            return Err(crate::EncapError::Message(
                "The selected audio format is unsupported.".into(),
            ));
        }
        let encoder = self.export_settings.encoder.as_str();
        if (format == "mp3" && !matches!(encoder, "lame" | "ffmpeg"))
            || (format != "mp3" && !matches!(encoder, "ffmpeg" | "audio_toolbox"))
        {
            return Err(crate::EncapError::Message(
                "The selected encoder does not support this audio format.".into(),
            ));
        }
        let allowed_quality = match (format.as_str(), self.export_settings.channels) {
            ("mp3", 1) => &["64k", "80k", "96k", "112k", "128k", "160k"][..],
            ("mp3", 2) => &["96k", "128k", "160k", "192k", "224k", "256k", "320k"][..],
            (_, 1) => &["48k", "64k", "80k", "96k", "128k", "160k"][..],
            (_, 2) => &["64k", "96k", "128k", "160k", "192k", "256k", "320k"][..],
            _ => unreachable!(),
        };
        if !allowed_quality.contains(&self.export_settings.quality_preset.as_str()) {
            return Err(crate::EncapError::Message(
                "The selected bitrate is unsupported for this format and channel layout.".into(),
            ));
        }
        for source in &self.audio_sources {
            if !is_valid_duration(source.duration_seconds) {
                return Err(crate::EncapError::Message(
                    "Audio source duration is invalid or exceeds maximum permitted duration.".into(),
                ));
            }
        }
        let mut previous = 0.0;
        let mut total_duration = 0.0;
        for chapter in &self.chapters {
            if !is_valid_duration(chapter.start_time_seconds)
                || !is_valid_chapter_duration(chapter.duration_seconds)
                || chapter.start_time_seconds < previous
            {
                return Err(crate::EncapError::Message(
                    "Chapter times must be finite, within permitted bounds, ordered, and have positive durations.".into(),
                ));
            }
            let end_time = chapter.start_time_seconds + chapter.duration_seconds;
            if !end_time.is_finite() || end_time > MAX_DURATION_SECONDS {
                return Err(crate::EncapError::Message(
                    "Chapter timing or total project duration exceeds maximum permitted bounds.".into(),
                ));
            }
            previous = chapter.start_time_seconds;
            total_duration += chapter.duration_seconds;
        }
        if !total_duration.is_finite() || total_duration > MAX_DURATION_SECONDS {
            return Err(crate::EncapError::Message(
                "Aggregate chapter duration exceeds maximum permitted bounds.".into(),
            ));
        }
        for segment in &self.transcript_segments {
            if !is_valid_duration(segment.start_time_seconds)
                || !is_valid_duration(segment.end_time_seconds)
                || segment.end_time_seconds < segment.start_time_seconds
            {
                return Err(crate::EncapError::Message(
                    "Transcript timing is invalid or exceeds permitted bounds.".into(),
                ));
            }
            for word in &segment.words {
                if !is_valid_duration(word.start_time_seconds)
                    || !is_valid_duration(word.end_time_seconds)
                    || word.start_time_seconds < segment.start_time_seconds
                    || word.end_time_seconds < word.start_time_seconds
                    || word.end_time_seconds > segment.end_time_seconds
                {
                    return Err(crate::EncapError::Message(
                        "Word-level transcript timing is invalid or exceeds permitted bounds.".into(),
                    ));
                }
            }
        }
        self.video
            .validate_schema()
            .map_err(crate::EncapError::from)?;
        Ok(())
    }
}

pub(crate) fn new_id() -> String {
    Uuid::new_v4().simple().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn sample_project() -> ProjectDocument {
        let mut project = ProjectDocument::default();
        project.metadata.podcast_title = "Show".into();
        project.metadata.episode_title = "Ep".into();
        project.audio_sources.push(AudioSource {
            source_path: PathBuf::from("test.wav"),
            display_name: "Source 1".into(),
            duration_seconds: 60.0,
            stored_path: None,
            extensions: BTreeMap::new(),
        });
        project.chapters.push(Chapter {
            id: "ch1".into(),
            chapter_number: 1,
            title: "Intro".into(),
            start_time_seconds: 0.0,
            duration_seconds: 60.0,
            image_path: None,
            image_stored_path: None,
            link_url: String::new(),
            extensions: BTreeMap::new(),
        });
        project
    }

    #[test]
    fn test_valid_project_duration() {
        let project = sample_project();
        assert!(project.validate().is_ok());
    }

    #[test]
    fn test_huge_duration_rejected() {
        let mut project = sample_project();
        project.audio_sources[0].duration_seconds = 1e300;
        assert!(project.validate().is_err());

        let mut project2 = sample_project();
        project2.chapters[0].duration_seconds = 1e300;
        assert!(project2.validate().is_err());
    }

    #[test]
    fn test_negative_or_nan_duration_rejected() {
        let mut project = sample_project();
        project.audio_sources[0].duration_seconds = -1.0;
        assert!(project.validate().is_err());

        let mut project2 = sample_project();
        project2.chapters[0].duration_seconds = f64::NAN;
        assert!(project2.validate().is_err());

        let mut project3 = sample_project();
        project3.chapters[0].start_time_seconds = f64::INFINITY;
        assert!(project3.validate().is_err());
    }

    #[test]
    fn test_exceeding_max_duration_rejected() {
        let mut project = sample_project();
        project.chapters[0].start_time_seconds = MAX_DURATION_SECONDS - 10.0;
        project.chapters[0].duration_seconds = 20.0; // sum exceeds MAX_DURATION_SECONDS
        assert!(project.validate().is_err());
    }

    #[test]
    fn test_max_duration_boundary() {
        let mut project = sample_project();
        project.audio_sources[0].duration_seconds = MAX_DURATION_SECONDS;
        project.chapters[0].start_time_seconds = 0.0;
        project.chapters[0].duration_seconds = MAX_DURATION_SECONDS;
        assert!(project.validate().is_ok());
    }
}
