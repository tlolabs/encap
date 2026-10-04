//! Core owns the media pair; EnCAP binds platform-signed copies to its pinned artifact.
use avid_core::{CancellationToken, MediaTools};
use encap_core::EncapError;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    fs,
    io::Read,
    path::{Path, PathBuf},
};

const PIN: &str = include_str!("../../../runtime/core-runtime.json");

fn unavailable() -> EncapError {
    super::runtime_error()
}
fn read_json(path: &Path) -> encap_core::Result<Value> {
    serde_json::from_slice(&fs::read(path).map_err(|_| unavailable())?).map_err(|_| unavailable())
}
fn hash(path: &Path) -> encap_core::Result<String> {
    if !fs::symlink_metadata(path)
        .map_err(|_| unavailable())?
        .is_file()
    {
        return Err(unavailable());
    }
    let mut file = fs::File::open(path).map_err(|_| unavailable())?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let count = file.read(&mut buffer).map_err(|_| unavailable())?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}
fn check_tree(
    root: &Path,
    directory: &Path,
    files: &HashMap<String, String>,
) -> encap_core::Result<()> {
    for entry in fs::read_dir(directory).map_err(|_| unavailable())? {
        let path = entry.map_err(|_| unavailable())?.path();
        let metadata = fs::symlink_metadata(&path).map_err(|_| unavailable())?;
        if metadata.is_dir() {
            check_tree(root, &path, files)?;
        } else if !metadata.is_file() {
            return Err(unavailable());
        } else {
            let name = path
                .strip_prefix(root)
                .map_err(|_| unavailable())?
                .to_string_lossy()
                .replace('\\', "/");
            if !files.contains_key(&name)
                && ![
                    "SHA256SUMS",
                    "signed-payload.json",
                    "encap-runtime.json",
                    "corresponding-source.tar.gz",
                ]
                .contains(&name.as_str())
            {
                return Err(unavailable());
            }
        }
    }
    Ok(())
}
fn packaged_pair() -> encap_core::Result<(PathBuf, PathBuf, String)> {
    let executable = std::env::current_exe().map_err(|_| unavailable())?;
    let binary = executable.parent().ok_or_else(unavailable)?;
    let metadata = if cfg!(target_os = "macos") && binary.file_name().is_some_and(|n| n == "MacOS")
    {
        binary.join("../Resources/FFmpeg")
    } else {
        binary.join("ffmpeg-runtime")
    };
    let os = if cfg!(target_os = "macos") {
        "macos"
    } else {
        std::env::consts::OS
    };
    let arch = if cfg!(target_arch = "aarch64") {
        "arm64"
    } else {
        std::env::consts::ARCH
    };
    let target = format!("{os}-{arch}");
    let pin: Value = serde_json::from_str(PIN).expect("checked-in Core runtime pins");
    let record = &pin["targets"][&target];
    if hash(&metadata.join("SHA256SUMS"))?
        != record["checksums_sha256"]
            .as_str()
            .ok_or_else(unavailable)?
    {
        return Err(unavailable());
    }
    let mut files = HashMap::new();
    for line in fs::read_to_string(metadata.join("SHA256SUMS"))
        .map_err(|_| unavailable())?
        .lines()
    {
        let (digest, name) = line.split_once("  ").ok_or_else(unavailable)?;
        if digest.len() != 64
            || !digest.bytes().all(|b| b.is_ascii_hexdigit())
            || Path::new(name).is_absolute()
            || name.contains('\\')
            || name
                .split('/')
                .any(|p| p.is_empty() || p == "." || p == "..")
            || files.insert(name.to_owned(), digest.to_owned()).is_some()
        {
            return Err(unavailable());
        }
    }
    check_tree(&metadata, &metadata, &files)?;
    let ffmpeg_name = format!("ffmpeg{}", std::env::consts::EXE_SUFFIX);
    let ffprobe_name = format!("ffprobe{}", std::env::consts::EXE_SUFFIX);
    for (name, expected) in &files {
        if name != &ffmpeg_name && name != &ffprobe_name && hash(&metadata.join(name))? != *expected
        {
            return Err(unavailable());
        }
    }
    let spec = read_json(&metadata.join("spec.json"))?;
    let core_spec: Value =
        serde_json::from_str(avid_core::FFMPEG_RUNTIME_SPECIFICATION).expect("Core specification");
    let build = read_json(&metadata.join("build.json"))?;
    let provenance = read_json(&metadata.join("encap-runtime.json"))?;
    let signed = read_json(&metadata.join("signed-payload.json"))?;
    if spec != core_spec
        || build["target"] != target
        || build["core_revision"] != pin["revision"]
        || build["core_worktree_modified"] != false
        || provenance
            != serde_json::json!({"schema":1,"owner":"AVID Core","encap_version":env!("CARGO_PKG_VERSION"),"avid_core":{"version":encap_core::CORE_VERSION,"revision":encap_core::CORE_REVISION,"source":encap_core::CORE_SOURCE},"target":target})
        || signed["schema"] != 1
        || signed["target"] != target
        || hash(&metadata.join("corresponding-source.tar.gz"))?
            != record["source_sha256"].as_str().ok_or_else(unavailable)?
    {
        return Err(unavailable());
    }
    for name in [&ffmpeg_name, &ffprobe_name] {
        if signed["original_binary_sha256"][name] != *files.get(name).ok_or_else(unavailable)?
            || signed["signed_binary_sha256"][name] != hash(&binary.join(name))?
        {
            return Err(unavailable());
        }
    }
    Ok((
        binary.join(ffmpeg_name),
        binary.join(ffprobe_name),
        core_spec["source"]["version"]
            .as_str()
            .ok_or_else(unavailable)?
            .to_owned(),
    ))
}

pub fn resolve(
    ffmpeg: Option<PathBuf>,
    ffprobe: Option<PathBuf>,
    token: &CancellationToken,
) -> encap_core::Result<MediaTools> {
    if token.is_cancelled() {
        return Err(unavailable());
    }
    let (ffmpeg, ffprobe, version) =
        match (ffmpeg, ffprobe) {
            (Some(ffmpeg), Some(ffprobe)) if ffmpeg.is_absolute() && ffprobe.is_absolute() => {
                (ffmpeg, ffprobe, None)
            }
            (None, None) => {
                let (ffmpeg, ffprobe, version) = packaged_pair()?;
                (ffmpeg, ffprobe, Some(version))
            }
            _ => return Err(EncapError::Message(
                "Development overrides require both ENCAP_FFMPEG and ENCAP_FFPROBE absolute paths."
                    .into(),
            )),
        };
    let tools = MediaTools::from_paths(ffmpeg, ffprobe, token).map_err(|error| {
        tracing::error!(code=error.code(), details=?error, "Core media tool validation failed");
        match error {
            avid_core::Error::Cancelled => {
                EncapError::Message("Media tool validation was cancelled safely.".into())
            }
            avid_core::Error::Timeout(_) => {
                EncapError::Message("The bundled media tools did not respond in time.".into())
            }
            _ => unavailable(),
        }
    })?;
    if let Some(version) = version {
        if tools.ffmpeg_version().split_whitespace().nth(2) != Some(version.as_str())
            || tools.ffprobe_version().split_whitespace().nth(2) != Some(version.as_str())
        {
            return Err(unavailable());
        }
    }
    Ok(tools)
}
