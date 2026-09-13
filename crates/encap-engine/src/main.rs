use clap::{Parser, Subcommand};
use directories::ProjectDirs;
use encap_core::{
    load_project, replace_staged_file, save_project, EncapError, ProjectDocument, Result,
};
use encap_ffmpeg::{CancellationToken, MediaTools};
use serde::Serialize;
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use tracing_subscriber::EnvFilter;

#[derive(Parser)]
#[command(
    name = "encap-engine",
    version,
    about = "EnCap shared application engine"
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    Inspect {
        folder: PathBuf,
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
    ExportTranscript {
        payload: PathBuf,
        output: PathBuf,
        #[arg(value_enum)]
        format: TranscriptFormat,
    },
    Transcribe {
        payload: PathBuf,
        provider: String,
    },
    Providers,
    ValidateTools,
}

#[derive(Clone, clap::ValueEnum)]
enum TranscriptFormat {
    Txt,
    Srt,
}

#[derive(Serialize)]
struct PathResponse {
    path: PathBuf,
}

fn main() {
    let _log_guard = init_logging();
    match run(Cli::parse()) {
        Ok(value) => match serde_json::to_writer(std::io::stdout(), &value) {
            Ok(()) => println!(),
            Err(error) => {
                eprintln!("Failed to serialize engine response: {error}");
                std::process::exit(1);
            }
        },
        Err(error) => {
            tracing::error!(error = %error, "engine operation failed");
            let _ = serde_json::to_writer(
                std::io::stdout(),
                &serde_json::json!({ "error": error.to_string() }),
            );
            println!();
            std::process::exit(1);
        }
    }
}

fn run(cli: Cli) -> Result<Value> {
    match cli.command {
        Commands::Inspect { folder } => json(encap_assemble::inspect(&folder)?),
        Commands::Open {
            project,
            extraction_parent,
        } => json(load_project(&project, extraction_parent.as_deref())?),
        Commands::Save {
            payload,
            project: destination,
        } => {
            let project = read_payload(&payload)?;
            json(PathResponse {
                path: save_project(&project, &destination)?,
            })
        }
        Commands::Export { payload, output } => {
            let project = read_payload(&payload)?;
            let path = encap_assemble::export(&project, &output, &CancellationToken::default())?;
            json(PathResponse { path })
        }
        Commands::ExportTranscript {
            payload,
            output,
            format,
        } => {
            let project = read_payload(&payload)?;
            let content = match format {
                TranscriptFormat::Txt => {
                    encap_core::render_transcript_text(&project.transcript_segments)
                }
                TranscriptFormat::Srt => encap_core::render_srt(&project.transcript_segments),
            };
            atomic_write(&output, content.as_bytes())?;
            json(PathResponse { path: output })
        }
        Commands::Transcribe { payload, provider } => {
            let project = read_payload(&payload)?;
            json(encap_transcribe::transcribe(
                &project.audio_sources,
                &provider,
                &CancellationToken::default(),
            )?)
        }
        Commands::Providers => json(encap_transcribe::providers()),
        Commands::ValidateTools => {
            MediaTools::discover()?;
            json(serde_json::json!({ "ok": true }))
        }
    }
}

fn read_payload(path: &Path) -> Result<ProjectDocument> {
    let bytes = fs::read(path).map_err(|source| EncapError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    let project: ProjectDocument = serde_json::from_slice(&bytes)?;
    project.validate()?;
    Ok(project)
}

fn atomic_write(path: &Path, data: &[u8]) -> Result<()> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
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

fn init_logging() -> Option<tracing_appender::non_blocking::WorkerGuard> {
    let directory = ProjectDirs::from("com", "TLO Labs", "EnCap")
        .map(|dirs| dirs.data_local_dir().join("logs"))?;
    fs::create_dir_all(&directory).ok()?;
    let appender = tracing_appender::rolling::RollingFileAppender::builder()
        .rotation(tracing_appender::rolling::Rotation::DAILY)
        .filename_prefix("engine")
        .filename_suffix("log")
        .max_log_files(14)
        .build(directory)
        .ok()?;
    let (writer, guard) = tracing_appender::non_blocking(appender);
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .with_writer(writer)
        .with_ansi(false)
        .try_init()
        .ok()?;
    Some(guard)
}
