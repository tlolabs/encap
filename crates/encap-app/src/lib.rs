//! Shared EnCAP application operations. The CLI and native hosts use these services.
//! Project documents remain EnCAP-owned files, separate from bounded media requests.
use clap::Subcommand;
use directories::ProjectDirs;
use encap_core::{
    replace_staged_file, EncapError, ProjectDocument, Result, PROJECT_SCHEMA_VERSION,
};
use encap_ffmpeg::CancellationToken;
use serde::Serialize;
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
};
mod artwork;
mod ffi;
pub use ffi::*;

#[derive(Subcommand, serde::Deserialize)]
#[serde(tag = "operation", rename_all = "kebab-case", deny_unknown_fields)]
pub enum Operation {
    /// Report the compiled application and immutable AVID Core identity.
    BuildInfo,
    /// Fast combined startup probe returning providers, video presets, and recovery state in one process.
    Startup,
    Inspect {
        folder: PathBuf,
    },
    /// Approximate first-channel waveform using bounded sample reads.
    Waveform {
        file: PathBuf,
    },
    InspectFiles {
        #[arg(required = true)]
        files: Vec<PathBuf>,
    },
    EditAudio {
        payload: PathBuf,
        edits: PathBuf,
    },
    Open {
        project: PathBuf,
        #[arg(long)]
        extraction_parent: Option<PathBuf>,
    },
    Save {
        payload: PathBuf,
        project: PathBuf,
    },
    Export {
        payload: PathBuf,
        output: PathBuf,
    },
    ExportVideo {
        payload: PathBuf,
        output: PathBuf,
        /// Compare Core renderers without changing saved project settings.
        #[arg(long, value_enum, default_value = "automatic")]
        #[serde(default)]
        render_mode: VideoRenderMode,
    },
    /// Inspect artwork through the same Core limits used by Video export.
    InspectArtwork {
        image: PathBuf,
    },
    /// Create a lossless JPEG/PNG artwork copy with metadata removed through Core.
    OptimizeArtwork {
        payload: PathBuf,
        image: PathBuf,
        output: PathBuf,
    },
    /// Publish a PNG composition using the project's Video settings and artwork fallback.
    PreviewVideo {
        payload: PathBuf,
        output: PathBuf,
        #[arg(long)]
        chapter_id: Option<String>,
    },
    VideoPresets,
    VideoCapabilities,
    ExportTranscript {
        payload: PathBuf,
        output: PathBuf,
        #[arg(value_enum)]
        format: TranscriptFormat,
    },
    ExportCaptions {
        payload: PathBuf,
        output: PathBuf,
        #[arg(value_enum)]
        format: CaptionFormat,
    },
    Transcribe {
        payload: PathBuf,
        provider: String,
        #[arg(long)]
        #[serde(default)]
        word_timestamps: bool,
        #[arg(long)]
        language: Option<String>,
        #[arg(long)]
        alignment_model: Option<String>,
    },
    /// Restore word alignment for the current edited text without recognition.
    Realign {
        payload: PathBuf,
        model: String,
        #[arg(long)]
        language: Option<String>,
    },
    TranscriptionStatus,
    Providers,
    Models,
    InstallModel {
        model: String,
    },
    RemoveModel {
        model: String,
    },
    VerifyModel {
        model: String,
    },
    ImportModel {
        model: String,
        source: PathBuf,
    },
    SaveRecovery {
        payload: PathBuf,
    },
    LoadRecovery,
    ClearRecovery,
    ValidateTools,
    /// Validate the retained executable pair for unfinished Audio/PCM paths.
    ValidateCompatibilityTools,
    /// Validate the original matched pair through Core before platform signing.
    ValidateCoreRuntime {
        directory: PathBuf,
    },
}

#[derive(Clone, clap::ValueEnum, serde::Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum TranscriptFormat {
    Txt,
    Srt,
    Vtt,
}

#[derive(Clone, clap::ValueEnum, serde::Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum CaptionFormat {
    Srt,
    Vtt,
}

#[derive(Clone, Default, clap::ValueEnum, serde::Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum VideoRenderMode {
    #[default]
    Automatic,
    Simple,
    PerFrame,
}

#[derive(Serialize)]
struct PathResponse {
    path: PathBuf,
}

#[derive(Serialize)]
struct RecoveryResponse {
    project: Option<ProjectDocument>,
}

/// Per-application storage configuration, independent of process environment.
#[derive(Clone, Default)]
pub struct ApplicationConfig {
    pub recovery_path: Option<PathBuf>,
}

pub fn execute(
    operation: Operation,
    cancellation: &CancellationToken,
    video_cancellation: &avid_core::CancellationToken,
) -> Result<Value> {
    execute_with_config(
        operation,
        cancellation,
        video_cancellation,
        &ApplicationConfig::default(),
    )
}

/// Blocks the calling worker until the operation and its cleanup have returned.
pub fn execute_with_config(
    operation: Operation,
    cancellation: &CancellationToken,
    video_cancellation: &avid_core::CancellationToken,
    config: &ApplicationConfig,
) -> Result<Value> {
    if cancellation.is_cancelled() || video_cancellation.is_cancelled() {
        return Err(EncapError::Message(
            "The operation was cancelled safely.".into(),
        ));
    }
    let _writer = ffi::reserve_output(&operation, config)?;
    match operation {
        Operation::BuildInfo => Ok(serde_json::json!({
            "encap_version": env!("CARGO_PKG_VERSION"),
            "avid_core": { "version": encap_core::CORE_VERSION,
                "revision": encap_core::CORE_REVISION, "source": encap_core::CORE_SOURCE }
        })),
        Operation::Startup => startup_response(
            encap_transcript::providers(cancellation),
            encap_transcript::status(),
            cancellation,
            config,
        ),
        Operation::ValidateCoreRuntime { .. } => Err(EncapError::Message(
            "Executable runtime validation is obsolete for linked Core artifacts.".into(),
        )),
        Operation::Inspect { folder } => json(encap_audio::inspect(&folder)?),
        Operation::Waveform { file } => json(encap_core::waveform_preview(&file)?),
        Operation::InspectFiles { files } => json(encap_core::inspect_files(&files)?),
        Operation::EditAudio { payload, edits } => {
            let project = read_payload(&payload)?;
            let bytes = read_bounded(&edits, 8 * 1024 * 1024)?;
            let edits = serde_json::from_slice::<encap_core::AudioEdits>(&bytes)?;
            json(encap_core::edit_audio(&project, edits)?)
        }
        Operation::Open {
            project,
            extraction_parent,
        } => json(encap_core::load_project_cancellable(
            &project,
            extraction_parent.as_deref(),
            &|| cancellation.is_cancelled(),
        )?),
        Operation::Save {
            payload,
            project: destination,
        } => {
            let project = read_payload(&payload)?;
            json(PathResponse {
                path: encap_core::save_project_cancellable(&project, &destination, &|| {
                    cancellation.is_cancelled()
                })?,
            })
        }
        Operation::Export { payload, output } => {
            let project = read_payload(&payload)?;
            let path = encap_audio::export(&project, &output, cancellation)?;
            json(PathResponse { path })
        }
        Operation::ExportVideo {
            payload,
            output,
            render_mode,
        } => {
            let project = read_video_payload(&payload, &output)?;
            let path = match render_mode {
                VideoRenderMode::Automatic => {
                    encap_video::export(&project, &output, video_cancellation)?
                }
                VideoRenderMode::Simple => encap_video::export_with_mode(
                    &project,
                    &output,
                    encap_video::RenderMode::Simple,
                    video_cancellation,
                )?,
                VideoRenderMode::PerFrame => encap_video::export_with_mode(
                    &project,
                    &output,
                    encap_video::RenderMode::PerFrame,
                    video_cancellation,
                )?,
            };
            json(PathResponse { path })
        }
        Operation::InspectArtwork { image } => {
            let (width, height) = encap_video::inspect_image(&image, video_cancellation)?;
            Ok(serde_json::json!({ "width": width, "height": height }))
        }
        Operation::OptimizeArtwork {
            payload,
            image,
            output,
        } => {
            let project = read_payload(&payload)?;
            artwork::optimize(&project, &payload, &image, &output, cancellation)
        }
        Operation::PreviewVideo {
            payload,
            output,
            chapter_id,
        } => {
            let project = read_video_payload(&payload, &output)?;
            let path =
                encap_video::preview(&project, &output, chapter_id.as_deref(), video_cancellation)?;
            json(PathResponse { path })
        }
        Operation::VideoPresets => json(encap_video::PRESETS),
        Operation::VideoCapabilities => json(encap_video::capabilities(video_cancellation)?),
        Operation::ExportTranscript {
            payload,
            output,
            format,
        } => {
            if encap_core::conflicts_with_path(&output, &payload) {
                return Err(EncapError::Message(
                    "Transcript output cannot replace its project payload.".into(),
                ));
            }
            let project = read_payload(&payload)?;
            encap_core::validate_transcript_export(&project, &output)?;
            let content = match format {
                TranscriptFormat::Txt => {
                    encap_core::render_transcript_text(&project.transcript_segments)
                }
                TranscriptFormat::Srt => encap_transcript::render_segment_subtitles(
                    &project.transcript_segments,
                    "srt",
                    cancellation,
                )?,
                TranscriptFormat::Vtt => encap_transcript::render_segment_subtitles(
                    &project.transcript_segments,
                    "vtt",
                    cancellation,
                )?,
            };
            atomic_write(&output, content.as_bytes())?;
            json(PathResponse { path: output })
        }
        Operation::ExportCaptions {
            payload,
            output,
            format,
        } => {
            if encap_core::conflicts_with_path(&output, &payload) {
                return Err(EncapError::Message(
                    "Caption output cannot replace its project payload.".into(),
                ));
            }
            let project = read_payload(&payload)?;
            encap_core::validate_transcript_export(&project, &output)?;
            let format = match format {
                CaptionFormat::Srt => "srt",
                CaptionFormat::Vtt => "vtt",
            };
            let content = encap_transcript::render_captions(
                &project.transcript_segments,
                format,
                cancellation,
            )?;
            atomic_write(&output, content.as_bytes())?;
            json(PathResponse { path: output })
        }
        Operation::Transcribe {
            payload,
            provider,
            word_timestamps,
            language,
            alignment_model,
        } => {
            let project = read_payload(&payload)?;
            let segments = encap_transcript::transcribe(
                &project.audio_sources,
                &provider,
                &encap_transcript::TranscribeOptions {
                    word_timestamps,
                    language: language.as_deref(),
                    alignment_model: alignment_model.as_deref(),
                },
                &project.transcript_segments,
                cancellation,
            )?;
            json(segments)
        }
        Operation::Realign {
            payload,
            model,
            language,
        } => {
            let project = read_payload(&payload)?;
            json(encap_transcript::realign(
                &project.audio_sources,
                &project.transcript_segments,
                &model,
                language.as_deref(),
                cancellation,
            )?)
        }
        Operation::TranscriptionStatus => json(encap_transcript::status()),
        Operation::Providers => json(encap_transcript::providers(cancellation)?),
        Operation::Models => json(encap_transcript::models(cancellation)?),
        Operation::InstallModel { model } => {
            json(encap_transcript::install_model(&model, cancellation)?)
        }
        Operation::VerifyModel { model } => {
            json(encap_transcript::verify_model(&model, cancellation)?)
        }
        Operation::RemoveModel { model } => {
            json(encap_transcript::remove_model(&model, cancellation)?)
        }
        Operation::ImportModel { model, source } => json(encap_transcript::import_model(
            &model,
            &source,
            cancellation,
        )?),
        Operation::SaveRecovery { payload } => {
            let project = read_payload(&payload)?;
            save_recovery_at(&project, &configured_recovery_path(config)?)?;
            json(serde_json::json!({ "ok": true }))
        }
        Operation::LoadRecovery => json(RecoveryResponse {
            project: load_recovery_at(&configured_recovery_path(config)?)?,
        }),
        Operation::ClearRecovery => {
            clear_recovery_at(&configured_recovery_path(config)?)?;
            json(serde_json::json!({ "ok": true }))
        }
        Operation::ValidateCompatibilityTools => {
            let tools = encap_ffmpeg::MediaTools::discover_with_cancellation(cancellation)?;
            json(serde_json::json!({"ok":true,"compatibility":true,
                "ffmpeg":tools.ffmpeg_version(),"ffprobe":tools.ffprobe_version()}))
        }
        Operation::ValidateTools => json(
            serde_json::json!({ "ok": true, "capabilities": encap_video::capabilities(video_cancellation)? }),
        ),
    }
}

fn read_video_payload(payload: &Path, output: &Path) -> Result<ProjectDocument> {
    if encap_core::conflicts_with_path(output, payload) {
        return Err(EncapError::Message(
            "Video output cannot replace its project payload.".into(),
        ));
    }
    read_payload(payload)
}

fn startup_response(
    providers: Result<Vec<encap_transcript::Provider>>,
    mut status: encap_transcript::TranscriptionStatus,
    cancellation: &CancellationToken,
    config: &ApplicationConfig,
) -> Result<Value> {
    if cancellation.is_cancelled() {
        return Err(EncapError::Message(
            "The operation was cancelled safely.".into(),
        ));
    }
    let providers = match providers {
        Ok(providers) => providers,
        Err(error) => {
            // Optional inference failures must remain visible without hiding
            // project recovery or making the base application unusable.
            status.available = false;
            status.reason = format!("Could not load transcription providers: {error}");
            Vec::new()
        }
    };
    Ok(serde_json::json!({
        "providers": providers,
        "transcription_status": status,
        "presets": encap_video::PRESETS,
        "recovery": RecoveryResponse {
            project: load_recovery_at(&configured_recovery_path(config)?)?,
        },
    }))
}

pub(crate) fn configured_recovery_path(config: &ApplicationConfig) -> Result<PathBuf> {
    if let Some(path) = &config.recovery_path {
        return Ok(path.clone());
    }
    recovery_path()
}

fn recovery_path() -> Result<PathBuf> {
    if let Some(path) = std::env::var_os("ENCAP_RECOVERY_PATH") {
        return Ok(PathBuf::from(path));
    }
    ProjectDirs::from("com", "TLO Labs", "EnCap")
        .map(|directories| directories.data_local_dir().join("recovery.json"))
        .ok_or_else(|| EncapError::Message("The recovery storage location is unavailable.".into()))
}

fn save_recovery_at(project: &ProjectDocument, path: &Path) -> Result<()> {
    project.validate()?;
    atomic_write(path, &serde_json::to_vec_pretty(project)?)
}

fn load_recovery_at(path: &Path) -> Result<Option<ProjectDocument>> {
    let bytes = match read_bounded(path, 8 * 1024 * 1024) {
        Ok(bytes) => bytes,
        Err(EncapError::Read { source, .. }) if source.kind() == std::io::ErrorKind::NotFound => {
            return Ok(None)
        }
        Err(error) => return Err(error),
    };
    let mut project: ProjectDocument = serde_json::from_slice(&bytes)?;
    migrate_payload(&mut project);
    project.validate()?;
    if project
        .audio_sources
        .iter()
        .any(|source| !source.source_path.is_file())
    {
        return Err(EncapError::Message(
            "The recovery record refers to audio that is no longer available. The record was preserved for manual recovery."
                .into(),
        ));
    }
    Ok(Some(project))
}

fn clear_recovery_at(path: &Path) -> Result<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(source) => Err(EncapError::Write {
            path: path.to_path_buf(),
            source,
        }),
    }
}

fn read_payload(path: &Path) -> Result<ProjectDocument> {
    let bytes = read_bounded(path, 8 * 1024 * 1024)?;
    let mut project: ProjectDocument = serde_json::from_slice(&bytes)?;
    migrate_payload(&mut project);
    project.validate()?;
    Ok(project)
}

fn migrate_payload(project: &mut ProjectDocument) {
    if project.schema_version == 1 {
        project.schema_version = PROJECT_SCHEMA_VERSION;
        if !project.video.export_settings.selection_initialized {
            project.video.export_settings.selected_chapter_ids = project
                .chapters
                .iter()
                .map(|chapter| chapter.id.clone())
                .collect();
            project.video.export_settings.selection_initialized = true;
        }
    }
}

fn atomic_write(path: &Path, data: &[u8]) -> Result<()> {
    let parent = match path.parent() {
        Some(p) if !p.as_os_str().is_empty() => p,
        _ => Path::new("."),
    };
    fs::create_dir_all(parent).map_err(|source| EncapError::Write {
        path: parent.to_path_buf(),
        source,
    })?;
    let mut temporary =
        tempfile::NamedTempFile::new_in(parent).map_err(|source| EncapError::Write {
            path: path.to_path_buf(),
            source,
        })?;
    std::io::Write::write_all(&mut temporary, data).map_err(|source| EncapError::Write {
        path: path.to_path_buf(),
        source,
    })?;
    temporary
        .as_file()
        .sync_all()
        .map_err(|source| EncapError::Write {
            path: path.to_path_buf(),
            source,
        })?;
    let staged = temporary
        .into_temp_path()
        .keep()
        .map_err(|error| EncapError::Write {
            path: path.to_path_buf(),
            source: error.error,
        })?;
    replace_staged_file(&staged, path)?;
    Ok(())
}

fn json<T: Serialize>(value: T) -> Result<Value> {
    Ok(serde_json::to_value(value)?)
}

fn read_bounded(path: &Path, maximum: u64) -> Result<Vec<u8>> {
    use std::io::Read;
    let file = fs::File::open(path).map_err(|source| EncapError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    let mut bytes = Vec::new();
    file.take(maximum + 1)
        .read_to_end(&mut bytes)
        .map_err(|source| EncapError::Read {
            path: path.to_path_buf(),
            source,
        })?;
    if bytes.len() as u64 > maximum {
        return Err(EncapError::Message(
            "The project payload exceeds the 8 MiB manifest limit.".into(),
        ));
    }
    Ok(bytes)
}
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn startup_reports_provider_errors_without_hiding_recovery_or_cancellation() {
        let temporary = tempfile::tempdir().unwrap();
        let config = ApplicationConfig {
            recovery_path: Some(temporary.path().join("recovery.json")),
        };
        save_recovery_at(
            &ProjectDocument::default(),
            &configured_recovery_path(&config).unwrap(),
        )
        .unwrap();
        let token = CancellationToken::default();
        let status = || encap_transcript::TranscriptionStatus {
            available: true,
            reason: "Linked providers available".into(),
            default_model: encap_transcript::DEFAULT_MODEL,
        };
        let failed = || {
            Err(EncapError::Message(
                "Provider catalog could not be read".into(),
            ))
        };
        let response = startup_response(failed(), status(), &token, &config).unwrap();
        assert_eq!(response["providers"], serde_json::json!([]));
        assert_eq!(response["transcription_status"]["available"], false);
        assert!(response["transcription_status"]["reason"]
            .as_str()
            .unwrap()
            .contains("Provider catalog could not be read"));
        assert!(response["recovery"]["project"].is_object());
        assert!(!response["presets"].as_array().unwrap().is_empty());
        let healthy = startup_response(Ok(Vec::new()), status(), &token, &config).unwrap();
        assert_eq!(healthy["transcription_status"]["available"], true);
        token.cancel();
        assert!(startup_response(failed(), status(), &token, &config).is_err());
    }

    #[test]
    fn recovery_is_lightweight_atomic_and_non_destructive() {
        let temporary = tempfile::tempdir().unwrap();
        let audio = temporary.path().join("source.wav");
        fs::write(&audio, b"audio placeholder").unwrap();
        let path = temporary.path().join("recovery.json");
        let mut project = ProjectDocument::default();
        project.audio_sources.push(encap_core::AudioSource {
            source_path: audio.clone(),
            display_name: "source.wav".into(),
            duration_seconds: 1.0,
            stored_path: None,
            extensions: Default::default(),
        });
        save_recovery_at(&project, &path).unwrap();
        assert_eq!(load_recovery_at(&path).unwrap(), Some(project));
        fs::remove_file(audio).unwrap();
        assert!(load_recovery_at(&path).is_err());
        assert!(path.exists(), "invalid recovery must be preserved");
        clear_recovery_at(&path).unwrap();
        assert!(!path.exists());
    }
}
