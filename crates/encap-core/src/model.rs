use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::PathBuf;
use uuid::Uuid;

fn default_schema() -> u64 {
    1
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
    pub export_settings: ExportSettings,
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
            export_settings: ExportSettings::default(),
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
        if self.schema_version != 1 {
            return Err(crate::EncapError::UnsupportedSchema {
                found: self.schema_version,
                supported: 1,
            });
        }
        if !matches!(self.export_settings.channels, 1 | 2) {
            return Err(crate::EncapError::Message(
                "Audio channels must be mono or stereo.".into(),
            ));
        }
        let mut previous = 0.0;
        for chapter in &self.chapters {
            if !chapter.start_time_seconds.is_finite()
                || !chapter.duration_seconds.is_finite()
                || chapter.start_time_seconds < previous
                || chapter.duration_seconds <= 0.0
            {
                return Err(crate::EncapError::Message(
                    "Chapter times must be finite, ordered, and have positive durations.".into(),
                ));
            }
            previous = chapter.start_time_seconds;
        }
        for segment in &self.transcript_segments {
            if !segment.start_time_seconds.is_finite()
                || !segment.end_time_seconds.is_finite()
                || segment.start_time_seconds < 0.0
                || segment.end_time_seconds < segment.start_time_seconds
            {
                return Err(crate::EncapError::Message(
                    "Transcript timing is invalid.".into(),
                ));
            }
        }
        Ok(())
    }
}

pub(crate) fn new_id() -> String {
    Uuid::new_v4().simple().to_string()
}
