//! Process-safe access to bundled FFmpeg-family tools.

use encap_core::{EncapError, Result};
use std::ffi::{OsStr, OsString};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::time::Duration;
mod runtime;
pub use avid_core::CancellationToken;

#[derive(Debug)]
pub struct ProcessOutput {
    pub status: ExitStatus,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

#[derive(Clone, Debug)]
pub struct MediaTools(avid_core::MediaTools);

impl MediaTools {
    pub fn discover() -> Result<Self> {
        Self::discover_with_cancellation(&CancellationToken::default())
    }

    pub fn discover_with_cancellation(token: &CancellationToken) -> Result<Self> {
        // Production release engines only use the packaged pair. Debug fixture
        // overrides require both paths; they never fall back to PATH or a bundle.
        #[cfg(debug_assertions)]
        let paths = (
            std::env::var_os("ENCAP_FFMPEG").map(PathBuf::from),
            std::env::var_os("ENCAP_FFPROBE").map(PathBuf::from),
        );
        #[cfg(not(debug_assertions))]
        let paths = (None, None);
        runtime::resolve(paths.0, paths.1, token).map(Self)
    }

    pub fn ffmpeg(&self) -> &Path {
        self.0.ffmpeg()
    }
    pub fn ffprobe(&self) -> &Path {
        self.0.ffprobe()
    }
    pub fn into_core(self) -> avid_core::MediaTools {
        self.0
    }
}

pub fn run(
    executable: &Path,
    arguments: &[OsString],
    cancellation: &CancellationToken,
    operation: &str,
) -> Result<ProcessOutput> {
    if cancellation.is_cancelled() {
        return Err(EncapError::Message(format!(
            "{operation} was cancelled safely."
        )));
    }
    let stdout_file = tempfile::NamedTempFile::new().map_err(|source| EncapError::Write {
        path: executable.to_path_buf(),
        source,
    })?;
    let stderr_file = tempfile::NamedTempFile::new().map_err(|source| EncapError::Write {
        path: executable.to_path_buf(),
        source,
    })?;
    let stdout = stdout_file.reopen().map_err(|source| EncapError::Write {
        path: executable.to_path_buf(),
        source,
    })?;
    let stderr = stderr_file.reopen().map_err(|source| EncapError::Write {
        path: executable.to_path_buf(),
        source,
    })?;
    let mut child = Command::new(executable)
        .args(arguments)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .map_err(|source| EncapError::Message(format!("{operation} could not start: {source}")))?;
    let status = loop {
        if cancellation.is_cancelled() {
            let _ = child.kill();
            let _ = child.wait();
            return Err(EncapError::Message(format!(
                "{operation} was cancelled safely."
            )));
        }
        let status = match child.try_wait() {
            Ok(status) => status,
            Err(source) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(EncapError::Message(format!(
                    "{operation} could not be monitored: {source}"
                )));
            }
        };
        if let Some(status) = status {
            break status;
        }
        std::thread::sleep(Duration::from_millis(50));
    };
    if cancellation.is_cancelled() {
        return Err(EncapError::Message(format!(
            "{operation} was cancelled safely."
        )));
    }
    let stdout = fs::read(stdout_file.path()).unwrap_or_default();
    let stderr = fs::read(stderr_file.path()).unwrap_or_default();
    if !status.success() {
        let detail = String::from_utf8_lossy(&stderr);
        tracing::error!(operation, diagnostics = %detail, "external media process failed");
        let summary = detail
            .lines()
            .rev()
            .find(|line| !line.trim().is_empty())
            .unwrap_or("The media tool did not explain the failure.");
        return Err(EncapError::Message(format!(
            "{operation} failed: {summary}"
        )));
    }
    Ok(ProcessOutput {
        status,
        stdout,
        stderr,
    })
}

pub fn locate_optional_tool(name: &str, environment: &str) -> Option<PathBuf> {
    if let Some(path) = std::env::var_os(environment)
        .map(PathBuf::from)
        .filter(|path| path.is_file())
    {
        return Some(path);
    }
    let platform_name = if cfg!(windows) {
        format!("{name}.exe")
    } else {
        name.to_string()
    };
    let executable = std::env::current_exe().ok()?;
    let directory = executable.parent()?;
    [
        directory.join(&platform_name),
        directory.join("../Resources").join(&platform_name),
    ]
    .into_iter()
    .find(|path| path.is_file())
    .or_else(|| find_on_path(&platform_name))
}

fn runtime_error() -> EncapError {
    EncapError::Message(
        "The bundled FFmpeg runtime is missing, damaged or incompatible. Reinstall EnCap.".into(),
    )
}

fn find_on_path(name: &str) -> Option<PathBuf> {
    std::env::var_os("PATH").and_then(|value| {
        std::env::split_paths(&value)
            .map(|directory| directory.join(name))
            .find(|path| path.is_file())
    })
}

pub fn os(value: impl AsRef<OsStr>) -> OsString {
    value.as_ref().to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn precancelled_operation_does_not_spawn() {
        let token = CancellationToken::default();
        token.cancel();
        let error = run(Path::new("/missing/should-not-spawn"), &[], &token, "Test").unwrap_err();
        assert!(error.to_string().contains("cancelled safely"));
    }

    #[cfg(unix)]
    #[test]
    fn cancellation_terminates_the_owned_child() {
        let cancellation = CancellationToken::default();
        let worker_token = cancellation.clone();
        let started = std::time::Instant::now();
        let worker = std::thread::spawn(move || {
            run(
                Path::new("/bin/sleep"),
                &[os("10")],
                &worker_token,
                "Test child",
            )
        });
        std::thread::sleep(Duration::from_millis(100));
        cancellation.cancel();
        let error = worker.join().unwrap().unwrap_err();
        assert!(error.to_string().contains("cancelled safely"));
        assert!(started.elapsed() < Duration::from_secs(2));
    }
}
