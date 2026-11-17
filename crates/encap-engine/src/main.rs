use clap::Parser;
use directories::ProjectDirs;
use encap_app::Operation;
use encap_ffmpeg::CancellationToken;
use serde_json::Value;
use std::fs;
use tracing_subscriber::EnvFilter;
#[derive(Parser)]
#[command(
    name = "encap-engine",
    version,
    about = "EnCAP diagnostic application client"
)]
struct Cli {
    #[command(subcommand)]
    command: Operation,
}

fn main() {
    init_logging();
    let cancellation = CancellationToken::default();
    let signal_cancellation = cancellation.clone();
    // Each operation owns a token; the process stop signal reaches both mode workers.
    let video_cancellation = CancellationToken::default();
    let signal_video_cancellation = video_cancellation.clone();
    if let Err(error) = ctrlc::set_handler(move || {
        signal_cancellation.cancel();
        signal_video_cancellation.cancel();
    }) {
        tracing::warn!(%error, "could not install the cancellation signal handler");
    }
    let result = encap_core::with_progress_handler(
        std::sync::Arc::new(|event| eprintln!("{event}")),
        || encap_app::execute(Cli::parse().command, &cancellation, &video_cancellation),
    );
    let (value, failed) = match result {
        Ok(value) => (value, false),
        Err(error) => {
            tracing::error!(%error,"engine operation failed");
            (serde_json::json!({"error":error.to_string()}), true)
        }
    };
    if let Err(error) = write_response(std::io::stdout().lock(), &value) {
        eprintln!("Failed to write engine response: {error}");
        std::process::exit(1);
    }
    if failed {
        std::process::exit(1);
    }
}

fn write_response(writer: impl std::io::Write, value: &Value) -> std::io::Result<()> {
    use std::io::Write;
    let mut writer = std::io::BufWriter::new(writer);
    serde_json::to_writer(&mut writer, value).map_err(std::io::Error::other)?;
    writer.write_all(b"\n")?;
    writer.flush()
}

fn init_logging() {
    let directory = match ProjectDirs::from("com", "TLO Labs", "EnCap")
        .map(|dirs| dirs.data_local_dir().join("logs"))
    {
        Some(dir) => dir,
        None => return,
    };
    if fs::create_dir_all(&directory).is_err() {
        return;
    }
    let appender = match tracing_appender::rolling::RollingFileAppender::builder()
        .rotation(tracing_appender::rolling::Rotation::DAILY)
        .filename_prefix("engine")
        .filename_suffix("log")
        .max_log_files(14)
        .build(directory)
    {
        Ok(appender) => appender,
        Err(_) => return,
    };
    let _ = tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .with_writer(appender)
        .with_ansi(false)
        .try_init();
}

#[cfg(test)]
mod response_regressions {
    use super::*;
    #[test]
    fn buffered_response_reports_write_and_flush_failures() {
        struct Fail(bool);
        impl std::io::Write for Fail {
            fn write(&mut self, data: &[u8]) -> std::io::Result<usize> {
                if self.0 {
                    Err(std::io::ErrorKind::BrokenPipe.into())
                } else {
                    Ok(data.len())
                }
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Err(std::io::ErrorKind::BrokenPipe.into())
            }
        }
        for fail_write in [true, false] {
            assert_eq!(
                write_response(Fail(fail_write), &serde_json::json!({"ok":true}))
                    .unwrap_err()
                    .kind(),
                std::io::ErrorKind::BrokenPipe
            );
        }
        let mut bytes = Vec::new();
        write_response(&mut bytes, &serde_json::json!({"ok":true})).unwrap();
        assert_eq!(bytes, b"{\"ok\":true}\n");
    }
}
