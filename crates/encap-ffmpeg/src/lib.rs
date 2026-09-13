//! Process-safe access to bundled FFmpeg-family tools.

use encap_core::{EncapError, Result};
use std::ffi::{OsStr, OsString};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

#[derive(Clone, Debug, Default)]
pub struct CancellationToken(Arc<AtomicBool>);

impl CancellationToken {
    pub fn cancel(&self) {
        self.0.store(true, Ordering::Release);
    }
    pub fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
}

#[derive(Debug)]
pub struct ProcessOutput {
    pub status: ExitStatus,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

#[derive(Clone, Debug)]
pub struct MediaTools {
    ffmpeg: PathBuf,
    ffprobe: PathBuf,
}

impl MediaTools {
    pub fn discover() -> Result<Self> {
        let tools = Self {
            ffmpeg: locate_tool("ffmpeg", "ENCAP_FFMPEG")?,
            ffprobe: locate_tool("ffprobe", "ENCAP_FFPROBE")?,
        };
        tools.validate()?;
        Ok(tools)
    }

    pub fn ffmpeg(&self) -> &Path {
        &self.ffmpeg
    }
    pub fn ffprobe(&self) -> &Path {
        &self.ffprobe
    }

    pub fn validate(&self) -> Result<()> {
        validate_binary(&self.ffmpeg, "ffmpeg")?;
        validate_binary(&self.ffprobe, "ffprobe")
    }
}

pub fn run(
    executable: &Path,
    arguments: &[OsString],
    cancellation: &CancellationToken,
    operation: &str,
) -> Result<ProcessOutput> {
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
        if let Some(status) = child.try_wait().map_err(|source| {
            EncapError::Message(format!("{operation} could not be monitored: {source}"))
        })? {
            break status;
        }
        std::thread::sleep(Duration::from_millis(50));
    };
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

fn locate_tool(name: &str, environment: &str) -> Result<PathBuf> {
    locate_optional_tool(name, environment).ok_or_else(|| {
        EncapError::Message(format!(
            "The bundled {name} tool is missing or damaged. Reinstall EnCap."
        ))
    })
}

fn find_on_path(name: &str) -> Option<PathBuf> {
    std::env::var_os("PATH").and_then(|value| {
        std::env::split_paths(&value)
            .map(|directory| directory.join(name))
            .find(|path| path.is_file())
    })
}

fn validate_binary(path: &Path, name: &str) -> Result<()> {
    let output = run(
        path,
        &[OsString::from("-version")],
        &CancellationToken::default(),
        name,
    )?;
    if output.stdout.is_empty() && output.stderr.is_empty() {
        return Err(EncapError::Message(format!(
            "The bundled {name} tool is incompatible. Reinstall EnCap."
        )));
    }
    Ok(())
}

pub fn os(value: impl AsRef<OsStr>) -> OsString {
    value.as_ref().to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

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
