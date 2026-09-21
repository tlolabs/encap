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
        Self::discover_with_validator(|tools| {
            tools.validate()?;
            Ok(tools.clone())
        })
    }

    /// The same host resolution policy with caller-owned validation. Video uses
    /// the shared cancellable validator; unrelated modes retain `discover()`.
    pub fn discover_with_validator<T>(validate: impl FnOnce(&Self) -> Result<T>) -> Result<T> {
        let executable = std::env::current_exe()
            .map_err(|e| EncapError::Message(format!("Cannot locate application: {e}")))?;
        let directory = executable.parent().ok_or_else(runtime_error)?;
        // Explicit fixtures are allowed only in debug builds. Packaged release
        // engines always use their own pair, regardless of environment or PATH.
        #[cfg(debug_assertions)]
        if std::env::var_os("ENCAP_FFMPEG").is_some() || std::env::var_os("ENCAP_FFPROBE").is_some()
        {
            let tools = Self {
                ffmpeg: explicit_tool("ENCAP_FFMPEG")?,
                ffprobe: explicit_tool("ENCAP_FFPROBE")?,
            };
            return validate(&tools);
        }
        let tools = packaged_tools(directory)?;
        validate(&tools)
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

fn runtime_error() -> EncapError {
    EncapError::Message(
        "The bundled FFmpeg runtime is missing, damaged or incompatible. Reinstall EnCap.".into(),
    )
}

#[cfg(debug_assertions)]
fn explicit_tool(environment: &str) -> Result<PathBuf> {
    std::env::var_os(environment)
        .map(PathBuf::from)
        .filter(|p| p.is_absolute() && p.is_file())
        .ok_or_else(runtime_error)
}

#[derive(serde::Deserialize)]
struct RuntimeManifest {
    schema: u32,
    version: String,
    target: String,
    binaries: BinaryHashes,
}
#[derive(serde::Deserialize)]
struct BinaryHashes {
    ffmpeg: String,
    ffprobe: String,
}

fn packaged_tools(directory: &Path) -> Result<MediaTools> {
    let metadata = if cfg!(target_os = "macos")
        && directory.file_name().is_some_and(|n| n == "MacOS")
        && directory
            .parent()
            .and_then(|p| p.file_name())
            .is_some_and(|n| n == "Contents")
    {
        directory.join("../Resources/FFmpeg")
    } else {
        directory.join("FFmpeg")
    };
    let manifest: RuntimeManifest = serde_json::from_slice(
        &fs::read(metadata.join("runtime.json")).map_err(|_| runtime_error())?,
    )
    .map_err(|_| runtime_error())?;
    let dependencies: serde_json::Value =
        serde_json::from_str(include_str!("../../../runtime/ffmpeg/dependencies.json"))
            .expect("checked-in FFmpeg dependency record");
    let platform = if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(windows) {
        "windows"
    } else {
        "linux"
    };
    let arch = if cfg!(target_arch = "aarch64") {
        "arm64"
    } else {
        "x86_64"
    };
    if manifest.schema != 1
        || manifest.version != dependencies["ffmpeg"]["version"]
        || manifest.target != format!("{platform}-{arch}")
    {
        return Err(runtime_error());
    }
    let suffix = if cfg!(windows) { ".exe" } else { "" };
    let tools = MediaTools {
        ffmpeg: directory.join(format!("ffmpeg{suffix}")),
        ffprobe: directory.join(format!("ffprobe{suffix}")),
    };
    verify_hash(&tools.ffmpeg, &manifest.binaries.ffmpeg)?;
    verify_hash(&tools.ffprobe, &manifest.binaries.ffprobe)?;
    Ok(tools)
}

fn verify_hash(path: &Path, expected: &str) -> Result<()> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let mut file = fs::File::open(path).map_err(|_| runtime_error())?;
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let length = file.read(&mut buffer).map_err(|_| runtime_error())?;
        if length == 0 {
            break;
        }
        hash.update(&buffer[..length]);
    }
    if format!("{:x}", hash.finalize()) != expected {
        return Err(runtime_error());
    }
    Ok(())
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
