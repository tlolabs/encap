use crate::{
    replace_staged_file, AudioSource, Chapter, EncapError, EpisodeMetadata, ExportSettings,
    ProjectDocument, Result, TranscriptSegment, TranscriptSettings, VideoProjectState,
    VideoSettings, WorkspaceMode,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, HashSet};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use tempfile::{Builder, NamedTempFile};
use zip::write::SimpleFileOptions;

pub const PROJECT_SCHEMA_VERSION: u64 = 2;
const MAX_ENTRIES: usize = 4096;
const MAX_MANIFEST: u64 = 8 * 1024 * 1024;
const MAX_MEMBER: u64 = 32 * 1024 * 1024 * 1024;
const MAX_TOTAL: u64 = 64 * 1024 * 1024 * 1024;
const MAX_COMPRESSION_RATIO: u64 = 1000;

#[derive(Debug, Serialize, Deserialize)]
struct Manifest {
    #[serde(default = "schema_one")]
    schema_version: u64,
    #[serde(default = "untitled")]
    project_title: String,
    #[serde(default)]
    metadata: ManifestMetadata,
    #[serde(default)]
    audio_sources: Vec<ManifestAudio>,
    #[serde(default)]
    chapters: Vec<ManifestChapter>,
    #[serde(default)]
    transcript_segments: Vec<TranscriptSegment>,
    #[serde(default)]
    transcript_settings: TranscriptSettings,
    #[serde(default)]
    export_settings: ExportSettings,
    #[serde(default, alias = "workspace")]
    active_mode: WorkspaceMode,
    #[serde(default)]
    video: VideoProjectState,
    #[serde(flatten)]
    extensions: BTreeMap<String, Value>,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct ManifestMetadata {
    #[serde(default)]
    podcast_title: String,
    #[serde(default)]
    episode_title: String,
    #[serde(default)]
    summary: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    artwork_stored_path: Option<String>,
    #[serde(flatten)]
    extensions: BTreeMap<String, Value>,
}

#[derive(Debug, Serialize, Deserialize)]
struct ManifestAudio {
    #[serde(default)]
    display_name: String,
    duration_seconds: f64,
    stored_path: String,
    #[serde(flatten)]
    extensions: BTreeMap<String, Value>,
}

#[derive(Debug, Serialize, Deserialize)]
struct ManifestChapter {
    #[serde(default = "crate::model::new_id")]
    id: String,
    start_time_seconds: f64,
    duration_seconds: f64,
    chapter_number: u32,
    #[serde(default)]
    title: String,
    #[serde(default)]
    link_url: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    image_stored_path: Option<String>,
    #[serde(flatten)]
    extensions: BTreeMap<String, Value>,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct CompatibilityPayload {
    top_level: BTreeMap<String, Value>,
    metadata: BTreeMap<String, Value>,
    audio_sources: Vec<BTreeMap<String, Value>>,
    chapters: Vec<BTreeMap<String, Value>>,
    transcript_segments: Vec<BTreeMap<String, Value>>,
    export_settings: BTreeMap<String, Value>,
    transcript_settings: BTreeMap<String, Value>,
    video: BTreeMap<String, Value>,
    video_export_settings: BTreeMap<String, Value>,
}

fn schema_one() -> u64 {
    1
}
fn untitled() -> String {
    "Untitled".into()
}

pub fn save_project(project: &ProjectDocument, requested_path: &Path) -> Result<PathBuf> {
    project.validate()?;
    let preserved = project
        .compatibility_payload
        .as_deref()
        .and_then(|value| serde_json::from_str::<CompatibilityPayload>(value).ok())
        .unwrap_or_default();
    let target = if requested_path.extension().and_then(|value| value.to_str()) == Some("encap") {
        requested_path.to_path_buf()
    } else {
        requested_path.with_extension("encap")
    };
    let parent = target.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).map_err(|source| EncapError::Write {
        path: parent.to_path_buf(),
        source,
    })?;
    let mut temporary = NamedTempFile::new_in(parent).map_err(|source| EncapError::Write {
        path: target.clone(),
        source,
    })?;
    {
        let mut archive = zip::ZipWriter::new(temporary.as_file_mut());
        let options =
            SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);
        let mut audio_records = Vec::with_capacity(project.audio_sources.len());
        for (index, source) in project.audio_sources.iter().enumerate() {
            ensure_regular_file(&source.source_path, "Audio source")?;
            let stored = format!("audio/{:03}-{}", index + 1, safe_name(&source.source_path));
            add_file(&mut archive, &source.source_path, &stored, options)?;
            audio_records.push(ManifestAudio {
                display_name: source.display_name.clone(),
                duration_seconds: source.duration_seconds,
                stored_path: stored,
                extensions: merged_extensions(
                    preserved.audio_sources.get(index),
                    &source.extensions,
                ),
            });
        }
        let artwork_stored_path = if let Some(path) = &project.metadata.artwork_path {
            ensure_regular_file(path, "Artwork")?;
            let stored = format!("artwork/{}", safe_name(path));
            add_file(&mut archive, path, &stored, options)?;
            Some(stored)
        } else {
            None
        };
        let mut chapter_records = Vec::with_capacity(project.chapters.len());
        for (index, chapter) in project.chapters.iter().enumerate() {
            let image_stored_path = if let Some(path) = &chapter.image_path {
                ensure_regular_file(path, "Chapter image")?;
                let stored = format!("chapters/{:03}-{}", index + 1, safe_name(path));
                add_file(&mut archive, path, &stored, options)?;
                Some(stored)
            } else {
                None
            };
            chapter_records.push(ManifestChapter {
                id: chapter.id.clone(),
                start_time_seconds: chapter.start_time_seconds,
                duration_seconds: chapter.duration_seconds,
                chapter_number: chapter.chapter_number,
                title: chapter.title.clone(),
                link_url: chapter.link_url.clone(),
                image_stored_path,
                extensions: merged_extensions(preserved.chapters.get(index), &chapter.extensions),
            });
        }
        let transcript_segments = project
            .transcript_segments
            .iter()
            .enumerate()
            .map(|(index, segment)| {
                let mut segment = segment.clone();
                segment.extensions = merged_extensions(
                    preserved.transcript_segments.get(index),
                    &segment.extensions,
                );
                segment
            })
            .collect();
        let manifest = Manifest {
            schema_version: PROJECT_SCHEMA_VERSION,
            project_title: project.project_title.clone(),
            metadata: ManifestMetadata {
                podcast_title: project.metadata.podcast_title.clone(),
                episode_title: project.metadata.episode_title.clone(),
                summary: project.metadata.summary.clone(),
                artwork_stored_path,
                extensions: merged_extensions(
                    Some(&preserved.metadata),
                    &project.metadata.extensions,
                ),
            },
            audio_sources: audio_records,
            chapters: chapter_records,
            transcript_segments,
            transcript_settings: TranscriptSettings {
                extensions: merged_extensions(
                    Some(&preserved.transcript_settings),
                    &project.transcript_settings.extensions,
                ),
                ..project.transcript_settings.clone()
            },
            export_settings: ExportSettings {
                extensions: merged_extensions(
                    Some(&preserved.export_settings),
                    &project.export_settings.extensions,
                ),
                ..project.export_settings.clone()
            },
            active_mode: project.active_mode,
            video: VideoProjectState {
                export_settings: VideoSettings {
                    extensions: merged_extensions(
                        Some(&preserved.video_export_settings),
                        &project.video.export_settings.extensions,
                    ),
                    ..project.video.export_settings.clone()
                },
                extensions: merged_extensions(Some(&preserved.video), &project.video.extensions),
                ..project.video.clone()
            },
            extensions: merged_extensions(Some(&preserved.top_level), &project.extensions),
        };
        let json = serde_json::to_vec_pretty(&manifest)?;
        archive.start_file("manifest.json", options)?;
        archive
            .write_all(&json)
            .map_err(|source| EncapError::Write {
                path: target.clone(),
                source,
            })?;
        archive.finish()?;
    }
    temporary
        .as_file()
        .sync_all()
        .map_err(|source| EncapError::Write {
            path: target.clone(),
            source,
        })?;
    let staged = temporary
        .into_temp_path()
        .keep()
        .map_err(|error| EncapError::Write {
            path: target.clone(),
            source: error.error,
        })?;
    replace_staged_file(&staged, &target)?;
    Ok(target)
}

pub fn load_project(
    project_path: &Path,
    extraction_parent: Option<&Path>,
) -> Result<ProjectDocument> {
    let file = File::open(project_path).map_err(|source| EncapError::Read {
        path: project_path.to_path_buf(),
        source,
    })?;
    let mut archive = zip::ZipArchive::new(file)?;
    preflight(&mut archive)?;
    let temporary = match extraction_parent {
        Some(parent) => {
            fs::create_dir_all(parent).map_err(|source| EncapError::Write {
                path: parent.to_path_buf(),
                source,
            })?;
            Builder::new().prefix("encap-project-").tempdir_in(parent)
        }
        None => Builder::new().prefix("encap-project-").tempdir(),
    }
    .map_err(|source| EncapError::Write {
        path: extraction_parent
            .unwrap_or_else(|| Path::new("."))
            .to_path_buf(),
        source,
    })?;
    extract(&mut archive, temporary.path())?;
    let root = temporary.keep();
    let result = load_manifest(&root, project_path);
    if result.is_err() {
        let _ = fs::remove_dir_all(&root);
    }
    result
}

fn preflight(archive: &mut zip::ZipArchive<File>) -> Result<()> {
    if archive.len() > MAX_ENTRIES {
        return Err(EncapError::Message(
            "The project archive contains too many files.".into(),
        ));
    }
    let mut seen = HashSet::new();
    let mut total = 0_u64;
    let mut manifest = false;
    for index in 0..archive.len() {
        let file = archive.by_index(index)?;
        let name = file.name().to_string();
        let path = safe_stored_path(&name)?;
        if !seen.insert(path.clone()) {
            return Err(EncapError::Message(
                "The project archive contains duplicate paths.".into(),
            ));
        }
        if let Some(mode) = file.unix_mode() {
            let kind = mode & 0o170000;
            if kind != 0 && kind != 0o100000 && kind != 0o040000 {
                return Err(EncapError::Message(
                    "The project archive contains an unsafe file type.".into(),
                ));
            }
        }
        if file.is_dir() {
            continue;
        }
        if file.size() > MAX_MEMBER {
            return Err(EncapError::Message("A project member is too large.".into()));
        }
        total = total
            .checked_add(file.size())
            .ok_or_else(|| EncapError::Message("The project archive is too large.".into()))?;
        if total > MAX_TOTAL {
            return Err(EncapError::Message(
                "The project archive is too large.".into(),
            ));
        }
        if file.size() > 0
            && file.size()
                > file
                    .compressed_size()
                    .max(1)
                    .saturating_mul(MAX_COMPRESSION_RATIO)
        {
            return Err(EncapError::Message(
                "The project archive has an unsafe compression ratio.".into(),
            ));
        }
        if path == Path::new("manifest.json") {
            manifest = true;
            if file.size() > MAX_MANIFEST {
                return Err(EncapError::Message(
                    "The project manifest is too large.".into(),
                ));
            }
        }
    }
    if !manifest {
        return Err(EncapError::Message(
            "The project does not contain manifest.json.".into(),
        ));
    }
    Ok(())
}

fn extract(archive: &mut zip::ZipArchive<File>, root: &Path) -> Result<()> {
    let mut total = 0_u64;
    for index in 0..archive.len() {
        let member = archive.by_index(index)?;
        let relative = safe_stored_path(member.name())?;
        let target = root.join(relative);
        if member.is_dir() {
            fs::create_dir_all(&target).map_err(|source| EncapError::Write {
                path: target,
                source,
            })?;
            continue;
        }
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).map_err(|source| EncapError::Write {
                path: parent.to_path_buf(),
                source,
            })?;
        }
        let mut output = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&target)
            .map_err(|source| EncapError::Write {
                path: target.clone(),
                source,
            })?;
        let copied =
            std::io::copy(&mut member.take(MAX_MEMBER + 1), &mut output).map_err(|source| {
                EncapError::Write {
                    path: target.clone(),
                    source,
                }
            })?;
        if copied > MAX_MEMBER {
            return Err(EncapError::Message(
                "A project member expanded beyond its allowed size.".into(),
            ));
        }
        total = total.saturating_add(copied);
        if total > MAX_TOTAL {
            return Err(EncapError::Message(
                "The project expanded beyond its allowed size.".into(),
            ));
        }
    }
    Ok(())
}

fn load_manifest(root: &Path, project_path: &Path) -> Result<ProjectDocument> {
    let manifest_path = root.join("manifest.json");
    let json = fs::read(&manifest_path).map_err(|source| EncapError::Read {
        path: manifest_path.clone(),
        source,
    })?;
    let manifest: Manifest = serde_json::from_slice(&json)?;
    if !matches!(manifest.schema_version, 1 | PROJECT_SCHEMA_VERSION) {
        return Err(EncapError::UnsupportedSchema {
            found: manifest.schema_version,
            supported: PROJECT_SCHEMA_VERSION,
        });
    }
    let compatibility_payload = serde_json::to_string(&CompatibilityPayload {
        top_level: manifest.extensions.clone(),
        metadata: manifest.metadata.extensions.clone(),
        audio_sources: manifest
            .audio_sources
            .iter()
            .map(|item| item.extensions.clone())
            .collect(),
        chapters: manifest
            .chapters
            .iter()
            .map(|item| item.extensions.clone())
            .collect(),
        transcript_segments: manifest
            .transcript_segments
            .iter()
            .map(|item| item.extensions.clone())
            .collect(),
        export_settings: manifest.export_settings.extensions.clone(),
        transcript_settings: manifest.transcript_settings.extensions.clone(),
        video: manifest.video.extensions.clone(),
        video_export_settings: manifest.video.export_settings.extensions.clone(),
    })?;
    let resolve = |stored: &str| -> Result<PathBuf> {
        let path = root.join(safe_stored_path(stored)?);
        if !path.is_file() {
            return Err(EncapError::Message(format!(
                "Project media is missing: {stored}"
            )));
        }
        Ok(path)
    };
    let mut audio_sources = Vec::with_capacity(manifest.audio_sources.len());
    for item in manifest.audio_sources {
        if !item.duration_seconds.is_finite() || item.duration_seconds < 0.0 {
            return Err(EncapError::Message(
                "Project audio duration is invalid.".into(),
            ));
        }
        let source_path = resolve(&item.stored_path)?;
        audio_sources.push(AudioSource {
            source_path,
            display_name: item.display_name,
            duration_seconds: item.duration_seconds,
            stored_path: Some(item.stored_path),
            extensions: item.extensions,
        });
    }
    let artwork_path = manifest
        .metadata
        .artwork_stored_path
        .as_deref()
        .map(resolve)
        .transpose()?;
    let mut chapters = Vec::with_capacity(manifest.chapters.len());
    for item in manifest.chapters {
        let image_path = item.image_stored_path.as_deref().map(resolve).transpose()?;
        chapters.push(Chapter {
            id: item.id,
            start_time_seconds: item.start_time_seconds,
            duration_seconds: item.duration_seconds,
            chapter_number: item.chapter_number,
            title: item.title,
            link_url: item.link_url,
            image_path,
            image_stored_path: item.image_stored_path,
            extensions: item.extensions,
        });
    }
    let mut video = manifest.video;
    if video.export_settings.selected_chapter_ids.is_empty()
        && !video.export_settings.selection_initialized
    {
        video.export_settings.selected_chapter_ids =
            chapters.iter().map(|chapter| chapter.id.clone()).collect();
        video.export_settings.selection_initialized = true;
    } else {
        let known: HashSet<_> = chapters.iter().map(|chapter| chapter.id.as_str()).collect();
        video
            .export_settings
            .selected_chapter_ids
            .retain(|id| known.contains(id.as_str()));
    }
    let project = ProjectDocument {
        schema_version: PROJECT_SCHEMA_VERSION,
        project_title: manifest.project_title,
        source_folder: None,
        project_path: Some(project_path.to_path_buf()),
        working_dir: Some(root.to_path_buf()),
        metadata: EpisodeMetadata {
            podcast_title: manifest.metadata.podcast_title,
            episode_title: manifest.metadata.episode_title,
            summary: manifest.metadata.summary,
            artwork_path,
            artwork_stored_path: manifest.metadata.artwork_stored_path,
            extensions: manifest.metadata.extensions,
        },
        audio_sources,
        chapters,
        transcript_segments: manifest.transcript_segments,
        transcript_settings: manifest.transcript_settings,
        export_settings: normalize_export(manifest.export_settings),
        active_mode: manifest.active_mode,
        video,
        compatibility_payload: Some(compatibility_payload),
        extensions: manifest.extensions,
    };
    project.validate()?;
    Ok(project)
}

fn merged_extensions(
    preserved: Option<&BTreeMap<String, Value>>,
    current: &BTreeMap<String, Value>,
) -> BTreeMap<String, Value> {
    let mut output = preserved.cloned().unwrap_or_default();
    output.extend(current.clone());
    output
}

fn normalize_export(mut value: ExportSettings) -> ExportSettings {
    if let Some(bitrate) = value.extensions.get("bitrate").and_then(Value::as_str) {
        value.quality_preset = bitrate.to_string();
    }
    if value.output_format.eq_ignore_ascii_case("m4a") {
        value.output_format = "aac".into();
    }
    value.encoder = match value.encoder.as_str() {
        "ffmpeg_default" => "ffmpeg",
        "lame_mp3_advanced" => "lame",
        other => other,
    }
    .to_string();
    value
}

fn add_file<W: Write + std::io::Seek>(
    archive: &mut zip::ZipWriter<W>,
    path: &Path,
    stored: &str,
    options: SimpleFileOptions,
) -> Result<()> {
    archive.start_file(stored, options)?;
    let mut input = File::open(path).map_err(|source| EncapError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    std::io::copy(&mut input, archive).map_err(|source| EncapError::Write {
        path: path.to_path_buf(),
        source,
    })?;
    Ok(())
}

fn ensure_regular_file(path: &Path, label: &str) -> Result<()> {
    if !path.is_file() {
        return Err(EncapError::Message(format!(
            "{label} is missing: {}",
            path.display()
        )));
    }
    Ok(())
}

fn safe_name(path: &Path) -> String {
    path.file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("media")
        .chars()
        .map(|c| {
            if matches!(c, '/' | '\\' | '\0') {
                '_'
            } else {
                c
            }
        })
        .collect()
}

fn safe_stored_path(value: &str) -> Result<PathBuf> {
    let path = Path::new(value);
    if value.is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(EncapError::Message(
            "The project archive contains an unsafe path.".into(),
        ));
    }
    Ok(path.to_path_buf())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn saves_and_loads_python_compatible_project() {
        let temp = tempfile::tempdir().unwrap();
        let media = temp.path().join("part.wav");
        fs::write(&media, b"audio").unwrap();
        let mut project = ProjectDocument {
            project_title: "Example".into(),
            ..ProjectDocument::default()
        };
        project.audio_sources.push(AudioSource {
            source_path: media,
            display_name: "Part".into(),
            duration_seconds: 1.5,
            stored_path: None,
            extensions: BTreeMap::new(),
        });
        project.chapters.push(Chapter {
            id: crate::model::new_id(),
            start_time_seconds: 0.0,
            duration_seconds: 1.5,
            chapter_number: 1,
            title: "Part".into(),
            link_url: String::new(),
            image_path: None,
            image_stored_path: None,
            extensions: BTreeMap::new(),
        });
        let target = save_project(&project, &temp.path().join("example")).unwrap();
        let loaded = load_project(&target, Some(temp.path())).unwrap();
        assert_eq!(loaded.project_title, "Example");
        assert_eq!(loaded.audio_sources[0].display_name, "Part");
        assert_eq!(
            fs::read(&loaded.audio_sources[0].source_path).unwrap(),
            b"audio"
        );
    }

    #[test]
    fn native_client_round_trip_preserves_unknown_manifest_fields() {
        let temporary = tempfile::tempdir().unwrap();
        let media = temporary.path().join("part.wav");
        fs::write(&media, b"audio").unwrap();
        let mut project = ProjectDocument {
            project_title: "Forward-compatible".into(),
            ..ProjectDocument::default()
        };
        project.extensions.insert(
            "future_top_level".into(),
            serde_json::json!({"enabled": true}),
        );
        project
            .metadata
            .extensions
            .insert("future_metadata".into(), serde_json::json!([1, 2, 3]));
        project.audio_sources.push(AudioSource {
            source_path: media,
            display_name: "Part".into(),
            duration_seconds: 1.0,
            stored_path: None,
            extensions: BTreeMap::from([("future_audio".into(), serde_json::json!("kept"))]),
        });
        project.chapters.push(Chapter {
            id: crate::model::new_id(),
            start_time_seconds: 0.0,
            duration_seconds: 1.0,
            chapter_number: 1,
            title: "Part".into(),
            link_url: String::new(),
            image_path: None,
            image_stored_path: None,
            extensions: BTreeMap::from([("future_chapter".into(), serde_json::json!(42))]),
        });
        project
            .export_settings
            .extensions
            .insert("future_export".into(), serde_json::json!(false));

        let first = save_project(&project, &temporary.path().join("first.encap")).unwrap();
        let mut through_native = load_project(&first, Some(temporary.path())).unwrap();
        assert!(through_native.compatibility_payload.is_some());
        through_native.extensions.clear();
        through_native.metadata.extensions.clear();
        through_native.audio_sources[0].extensions.clear();
        through_native.chapters[0].extensions.clear();
        through_native.export_settings.extensions.clear();

        let second = save_project(
            &through_native,
            &temporary.path().join("through-native.encap"),
        )
        .unwrap();
        let restored = load_project(&second, Some(temporary.path())).unwrap();
        assert_eq!(
            restored.extensions["future_top_level"],
            serde_json::json!({"enabled": true})
        );
        assert_eq!(
            restored.metadata.extensions["future_metadata"],
            serde_json::json!([1, 2, 3])
        );
        assert_eq!(
            restored.audio_sources[0].extensions["future_audio"],
            serde_json::json!("kept")
        );
        assert_eq!(
            restored.chapters[0].extensions["future_chapter"],
            serde_json::json!(42)
        );
        assert_eq!(
            restored.export_settings.extensions["future_export"],
            serde_json::json!(false)
        );
    }

    #[test]
    fn migrates_schema_one_without_losing_embedded_project_data() {
        let temporary = tempfile::tempdir().unwrap();
        let legacy = temporary.path().join("legacy.encap");
        let file = File::create(&legacy).unwrap();
        let mut zip = zip::ZipWriter::new(file);
        let options = SimpleFileOptions::default();
        zip.start_file("audio/001-source.wav", options).unwrap();
        zip.write_all(b"legacy audio").unwrap();
        zip.start_file("artwork/cover.png", options).unwrap();
        zip.write_all(b"legacy artwork").unwrap();
        zip.start_file("manifest.json", options).unwrap();
        zip.write_all(
            br#"{
              "schema_version": 1,
              "project_title": "Legacy Project",
              "metadata": {
                "podcast_title": "History",
                "episode_title": "Episode One",
                "summary": "Preserve me",
                "artwork_stored_path": "artwork/cover.png"
              },
              "audio_sources": [{
                "display_name": "source.wav",
                "duration_seconds": 2.5,
                "stored_path": "audio/001-source.wav"
              }],
              "chapters": [{
                "start_time_seconds": 0,
                "duration_seconds": 2.5,
                "chapter_number": 1,
                "title": "Opening"
              }],
              "transcript_segments": [{
                "id": "segment-1",
                "start_time_seconds": 0.1,
                "end_time_seconds": 1.2,
                "speaker": "Host",
                "text": "Welcome"
              }],
              "export_settings": {
                "output_format": "aac",
                "quality_preset": "192k",
                "encoder": "ffmpeg",
                "channels": 2
              },
              "workspace": "transcribe"
            }"#,
        )
        .unwrap();
        zip.finish().unwrap();

        let migrated = load_project(&legacy, Some(temporary.path())).unwrap();
        assert_eq!(migrated.schema_version, PROJECT_SCHEMA_VERSION);
        assert_eq!(migrated.metadata.podcast_title, "History");
        assert_eq!(migrated.metadata.summary, "Preserve me");
        assert_eq!(
            fs::read(&migrated.audio_sources[0].source_path).unwrap(),
            b"legacy audio"
        );
        assert_eq!(
            fs::read(migrated.metadata.artwork_path.as_ref().unwrap()).unwrap(),
            b"legacy artwork"
        );
        assert_eq!(migrated.transcript_segments[0].text, "Welcome");
        assert_eq!(migrated.export_settings.quality_preset, "192k");
        assert_eq!(migrated.active_mode, WorkspaceMode::Transcript);
        assert_eq!(migrated.video.export_settings.selected_chapter_ids.len(), 1);
        assert!(migrated.video.export_settings.selection_initialized);

        let upgraded = save_project(&migrated, &temporary.path().join("upgraded.encap")).unwrap();
        let reopened = load_project(&upgraded, Some(temporary.path())).unwrap();
        assert_eq!(reopened.schema_version, PROJECT_SCHEMA_VERSION);
        assert_eq!(reopened.metadata.episode_title, "Episode One");
        assert_eq!(reopened.transcript_segments[0].speaker, "Host");
        assert_eq!(reopened.export_settings.output_format, "aac");
    }

    #[test]
    fn rejects_traversal() {
        let temp = tempfile::tempdir().unwrap();
        let target = temp.path().join("bad.encap");
        let file = File::create(&target).unwrap();
        let mut zip = zip::ZipWriter::new(file);
        zip.start_file("../outside", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"bad").unwrap();
        zip.start_file("manifest.json", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"{}").unwrap();
        zip.finish().unwrap();
        assert!(load_project(&target, Some(temp.path())).is_err());
    }
}
