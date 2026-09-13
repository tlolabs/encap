//! Local transcription mode and provider discovery.

use directories::ProjectDirs;
use encap_core::{replace_staged_file, AudioSource, EncapError, Result, TranscriptSegment};
use encap_ffmpeg::{locate_optional_tool, os, CancellationToken, MediaTools};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
#[cfg(target_os = "macos")]
use std::process::Command;
use std::time::Duration;

const SUPERWHISPER_ID: &str = "superwhisper-large-v3";
#[cfg(target_os = "macos")]
const SUPERWHISPER_FILENAME: &str = "ggml-large-v3.bin";
#[cfg(target_os = "macos")]
const SUPERWHISPER_SIZE: u64 = 3_095_033_483;
#[cfg(target_os = "macos")]
const SUPERWHISPER_SHA256: &str =
    "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2";

#[cfg(target_os = "macos")]
const MACWHISPER_MODELS: &[(&str, &str, &str, &str)] = &[
    (
        "openai_whisper-large-v3-v20240930_626MB",
        "macwhisper-large-v3-turbo-compressed",
        "Whisper Large V3 Turbo (compressed) — Whisper Transcription",
        "whisper-large-v3",
    ),
    (
        "openai_whisper-large-v3-v20240930",
        "macwhisper-large-v3-turbo",
        "Whisper Large V3 Turbo — Whisper Transcription",
        "whisper-large-v3",
    ),
    (
        "openai_whisper-large-v3",
        "macwhisper-large-v3",
        "Whisper Large V3 — Whisper Transcription",
        "whisper-large-v3",
    ),
];

#[derive(Clone, Debug, Serialize)]
pub struct Provider {
    pub id: String,
    pub name: String,
    pub detail: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct ModelInfo {
    pub id: String,
    pub name: String,
    pub download_size: String,
    pub languages: String,
    pub description: String,
    pub installed: bool,
    pub download_allowed: bool,
}

pub fn models() -> Vec<ModelInfo> {
    let download_allowed = shared_providers().is_empty();
    model_catalog()
        .into_iter()
        .map(|model| model.info(download_allowed))
        .collect()
}

pub fn install_model(id: &str, cancellation: &CancellationToken) -> Result<ModelInfo> {
    let model = model_catalog()
        .into_iter()
        .find(|model| model.id == id)
        .ok_or_else(|| {
            EncapError::Message(
                "That transcription model is not in EnCap's trusted catalog.".into(),
            )
        })?;
    if !shared_providers().is_empty() {
        return Err(EncapError::Message(
            "EnCap is already reusing a compatible local model. A duplicate download is unnecessary."
                .into(),
        ));
    }
    if model.path.is_file() && verify_model(&model).is_ok() {
        return Ok(model.info(true));
    }
    let parent = model
        .path
        .parent()
        .ok_or_else(|| EncapError::Message("The model storage location is invalid.".into()))?;
    fs::create_dir_all(parent).map_err(|source| EncapError::Write {
        path: parent.to_path_buf(),
        source,
    })?;
    let client = reqwest::blocking::Client::builder()
        .connect_timeout(Duration::from_secs(20))
        .user_agent("EnCap/0.2 model installer")
        .build()
        .map_err(|error| {
            EncapError::Message(format!("The model download could not start: {error}"))
        })?;
    let mut response = client
        .get(model.download_url)
        .send()
        .and_then(reqwest::blocking::Response::error_for_status)
        .map_err(|error| EncapError::Message(format!("The model download failed: {error}")))?;
    if response
        .content_length()
        .is_some_and(|length| length > model.max_download_bytes)
    {
        return Err(EncapError::Message(
            "The model server reported an unexpectedly large file.".into(),
        ));
    }
    let mut temporary =
        tempfile::NamedTempFile::new_in(parent).map_err(|source| EncapError::Write {
            path: model.path.clone(),
            source,
        })?;
    let mut digest = Sha256::new();
    let mut received = 0_u64;
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        if cancellation.is_cancelled() {
            return Err(EncapError::Message(
                "The model download was cancelled safely.".into(),
            ));
        }
        let count = response.read(&mut buffer).map_err(|error| {
            EncapError::Message(format!("The model download was interrupted: {error}"))
        })?;
        if count == 0 {
            break;
        }
        received = received
            .checked_add(count as u64)
            .ok_or_else(|| EncapError::Message("The model download is too large.".into()))?;
        if received > model.max_download_bytes {
            return Err(EncapError::Message(
                "The model download exceeded its expected maximum size.".into(),
            ));
        }
        digest.update(&buffer[..count]);
        temporary
            .write_all(&buffer[..count])
            .map_err(|source| EncapError::Write {
                path: model.path.clone(),
                source,
            })?;
    }
    let actual = format!("{:x}", digest.finalize());
    if actual != model.sha256 {
        return Err(EncapError::Message(
            "The downloaded model failed SHA-256 verification and was not installed.".into(),
        ));
    }
    temporary
        .as_file()
        .sync_all()
        .map_err(|source| EncapError::Write {
            path: model.path.clone(),
            source,
        })?;
    let staged = temporary
        .into_temp_path()
        .keep()
        .map_err(|error| EncapError::Write {
            path: model.path.clone(),
            source: error.error,
        })?;
    replace_staged_file(&staged, &model.path)?;
    Ok(model.info(true))
}

pub fn remove_model(id: &str) -> Result<ModelInfo> {
    let model = model_catalog()
        .into_iter()
        .find(|model| model.id == id)
        .ok_or_else(|| {
            EncapError::Message(
                "That transcription model is not in EnCap's trusted catalog.".into(),
            )
        })?;
    if model.path.exists() {
        fs::remove_file(&model.path).map_err(|source| EncapError::Write {
            path: model.path.clone(),
            source,
        })?;
    }
    Ok(model.info(shared_providers().is_empty()))
}

pub fn providers() -> Vec<Provider> {
    let mut output = Vec::new();
    let shared = shared_providers();
    output.extend(shared.iter().map(ResolvedProvider::info));
    if cfg!(target_os = "macos")
        && locate_optional_tool("apple-transcriber", "ENCAP_APPLE_TRANSCRIBER").is_some()
    {
        output.push(Provider {
            id: "apple-local".into(),
            name: "Apple On-Device".into(),
            detail: "Apple Speech · on this Mac".into(),
        });
    }
    let local_runtime = locate_optional_tool("whisper-cli", "ENCAP_WHISPER_CLI").is_some();
    if shared.is_empty() {
        for model in model_catalog() {
            if model.path.is_file() && local_runtime {
                output.push(Provider {
                    id: model.id,
                    name: model.name,
                    detail: "whisper.cpp · EnCap model".into(),
                });
            }
        }
    }
    output
}

pub fn transcribe(
    sources: &[AudioSource],
    provider: &str,
    cancellation: &CancellationToken,
) -> Result<Vec<TranscriptSegment>> {
    if sources.is_empty() {
        return Err(EncapError::Message(
            "Import audio before transcribing.".into(),
        ));
    }
    let tools = MediaTools::discover()?;
    let mut resolved = resolve_provider(provider);
    if provider != "apple-local" && resolved.is_none() {
        return Err(EncapError::Message(
            "The selected transcription engine is no longer available. Refresh the engine list and try again."
                .into(),
        ));
    }
    if let Some(candidate) = resolved.as_ref() {
        if let Backend::WhisperCpp { model, sha256 } = &candidate.backend {
            // Hash multi-gigabyte weights once per job, not once per source file.
            if let Err(error) = verify_path(model, sha256, &candidate.source_name) {
                if candidate.id != SUPERWHISPER_ID {
                    return Err(error);
                }
                resolved = fallback_after_superwhisper();
                let Some(fallback) = resolved.as_ref() else {
                    return Err(error);
                };
                if let Backend::WhisperCpp { model, sha256 } = &fallback.backend {
                    verify_path(model, sha256, &fallback.source_name)?;
                }
            }
        }
    }
    let mut output = Vec::new();
    let mut offset = 0.0;
    for source in sources {
        let mut segments = if provider == "apple-local" {
            transcribe_apple(&source.source_path, offset, cancellation)?
        } else {
            let resolved = resolved.as_ref().unwrap();
            match &resolved.backend {
                Backend::WhisperCpp { model, .. } => transcribe_whisper(
                    &tools,
                    &source.source_path,
                    model,
                    &resolved.language_code,
                    offset,
                    cancellation,
                )?,
                #[cfg(target_os = "macos")]
                Backend::WhisperKit { model, tokenizer } => transcribe_whisperkit(
                    &tools,
                    &source.source_path,
                    model,
                    tokenizer,
                    &resolved.language_code,
                    offset,
                    cancellation,
                )?,
            }
        };
        output.append(&mut segments);
        offset += source.duration_seconds;
    }
    Ok(output)
}

#[cfg(target_os = "macos")]
fn transcribe_whisperkit(
    tools: &MediaTools,
    source: &Path,
    model: &Path,
    tokenizer: &Path,
    language_code: &str,
    offset: f64,
    cancellation: &CancellationToken,
) -> Result<Vec<TranscriptSegment>> {
    let helper = locate_optional_tool("whisperkit-transcriber", "ENCAP_WHISPERKIT_TRANSCRIBER")
        .ok_or_else(|| {
            EncapError::Message(
                "Whisper Transcription model reuse is unavailable in this build.".into(),
            )
        })?;
    let temp = tempfile::tempdir().map_err(|source| EncapError::Write {
        path: std::env::temp_dir(),
        source,
    })?;
    let input = temp.path().join("input.wav");
    let private_tokenizer = temp.path().join("tokenizer");
    fs::create_dir(&private_tokenizer).map_err(|source| EncapError::Write {
        path: private_tokenizer.clone(),
        source,
    })?;
    for filename in ["tokenizer.json", "tokenizer_config.json", "config.json"] {
        let source_path = tokenizer.join(filename);
        let destination = private_tokenizer.join(filename);
        fs::copy(&source_path, &destination).map_err(|source| EncapError::Write {
            path: destination,
            source,
        })?;
    }
    encap_ffmpeg::run(
        tools.ffmpeg(),
        &[
            os("-hide_banner"),
            os("-nostdin"),
            os("-y"),
            os("-i"),
            os(source),
            os("-vn"),
            os("-ar"),
            os("16000"),
            os("-ac"),
            os("1"),
            os("-c:a"),
            os("pcm_s16le"),
            os(&input),
        ],
        cancellation,
        "Audio preparation",
    )?;
    let mut arguments = vec![
        os("--model"),
        os(model),
        os("--tokenizer"),
        os(&private_tokenizer),
        os("--input"),
        os(&input),
    ];
    if language_code != "auto" {
        arguments.push(os("--language"));
        arguments.push(os(language_code));
    }
    let result = encap_ffmpeg::run(
        &helper,
        &arguments,
        cancellation,
        "WhisperKit transcription",
    )?;
    #[derive(serde::Deserialize)]
    struct Response {
        segments: Vec<Item>,
    }
    #[derive(serde::Deserialize)]
    struct Item {
        start_seconds: f64,
        end_seconds: f64,
        text: String,
    }
    let response: Response = serde_json::from_slice(&result.stdout)
        .map_err(|_| EncapError::Message("WhisperKit returned an invalid result.".into()))?;
    response
        .segments
        .into_iter()
        .filter(|item| !item.text.trim().is_empty())
        .map(|item| {
            if !item.start_seconds.is_finite()
                || !item.end_seconds.is_finite()
                || item.start_seconds < 0.0
                || item.end_seconds < item.start_seconds
            {
                return Err(EncapError::Message(
                    "WhisperKit returned an invalid segment time.".into(),
                ));
            }
            Ok(TranscriptSegment {
                id: uuid::Uuid::new_v4().simple().to_string(),
                start_time_seconds: offset + item.start_seconds,
                end_time_seconds: offset + item.end_seconds,
                speaker: String::new(),
                text: item.text.trim().to_string(),
                extensions: BTreeMap::new(),
            })
        })
        .collect()
}

fn transcribe_apple(
    source: &Path,
    offset: f64,
    cancellation: &CancellationToken,
) -> Result<Vec<TranscriptSegment>> {
    let helper =
        locate_optional_tool("apple-transcriber", "ENCAP_APPLE_TRANSCRIBER").ok_or_else(|| {
            EncapError::Message(
                "Apple On-Device transcription is unavailable in this build.".into(),
            )
        })?;
    let result = encap_ffmpeg::run(
        &helper,
        &[os("--input"), os(source)],
        cancellation,
        "Apple On-Device transcription",
    )?;
    #[derive(serde::Deserialize)]
    struct Response {
        segments: Vec<Word>,
    }
    #[derive(serde::Deserialize)]
    struct Word {
        text: String,
        start_seconds: f64,
        duration_seconds: f64,
    }
    let response: Response = serde_json::from_slice(&result.stdout)
        .map_err(|_| EncapError::Message("Apple Speech returned an invalid result.".into()))?;
    let words = response
        .segments
        .into_iter()
        .filter(|word| !word.text.trim().is_empty())
        .map(|word| TranscriptSegment {
            id: uuid::Uuid::new_v4().simple().to_string(),
            start_time_seconds: offset + word.start_seconds,
            end_time_seconds: offset + word.start_seconds + word.duration_seconds,
            speaker: String::new(),
            text: word.text.trim().to_string(),
            extensions: BTreeMap::new(),
        })
        .collect::<Vec<_>>();
    Ok(group_words(words))
}

fn transcribe_whisper(
    tools: &MediaTools,
    source: &Path,
    model: &Path,
    language_code: &str,
    offset: f64,
    cancellation: &CancellationToken,
) -> Result<Vec<TranscriptSegment>> {
    let whisper = locate_optional_tool("whisper-cli", "ENCAP_WHISPER_CLI").ok_or_else(|| {
        EncapError::Message("The local Whisper runtime is unavailable in this build.".into())
    })?;
    let temp = tempfile::tempdir().map_err(|source| EncapError::Write {
        path: std::env::temp_dir(),
        source,
    })?;
    let input = temp.path().join("input.wav");
    let prefix = temp.path().join("transcript");
    encap_ffmpeg::run(
        tools.ffmpeg(),
        &[
            os("-hide_banner"),
            os("-nostdin"),
            os("-y"),
            os("-i"),
            os(source),
            os("-vn"),
            os("-ar"),
            os("16000"),
            os("-ac"),
            os("1"),
            os("-c:a"),
            os("pcm_s16le"),
            os(&input),
        ],
        cancellation,
        "Audio preparation",
    )?;
    encap_ffmpeg::run(
        &whisper,
        &[
            os("--model"),
            os(model),
            os("--file"),
            os(&input),
            os("--language"),
            os(language_code),
            os("--output-json"),
            os("--output-file"),
            os(&prefix),
            os("--no-prints"),
        ],
        cancellation,
        "Whisper transcription",
    )?;
    #[derive(serde::Deserialize)]
    struct Response {
        transcription: Vec<Item>,
    }
    #[derive(serde::Deserialize)]
    struct Item {
        offsets: Offsets,
        text: String,
    }
    #[derive(serde::Deserialize)]
    struct Offsets {
        from: f64,
        to: f64,
    }
    let result_path = prefix.with_extension("json");
    let bytes = fs::read(&result_path).map_err(|source| EncapError::Read {
        path: result_path,
        source,
    })?;
    let response: Response = serde_json::from_slice(&bytes)
        .map_err(|_| EncapError::Message("Whisper returned an invalid result.".into()))?;
    Ok(response
        .transcription
        .into_iter()
        .filter(|item| !item.text.trim().is_empty())
        .map(|item| TranscriptSegment {
            id: uuid::Uuid::new_v4().simple().to_string(),
            start_time_seconds: offset + item.offsets.from / 1000.0,
            end_time_seconds: offset + item.offsets.to / 1000.0,
            speaker: String::new(),
            text: item.text.trim().to_string(),
            extensions: BTreeMap::new(),
        })
        .collect())
}

#[derive(Clone)]
struct Model {
    id: String,
    path: PathBuf,
    name: String,
    download_url: &'static str,
    sha256: &'static str,
    download_size: &'static str,
    languages: &'static str,
    description: &'static str,
    language_code: &'static str,
    max_download_bytes: u64,
}

#[derive(Clone)]
enum Backend {
    WhisperCpp {
        model: PathBuf,
        sha256: String,
    },
    #[cfg(target_os = "macos")]
    WhisperKit {
        model: PathBuf,
        tokenizer: PathBuf,
    },
}

#[derive(Clone)]
struct ResolvedProvider {
    id: String,
    name: String,
    source_name: String,
    language_code: String,
    backend: Backend,
}

impl ResolvedProvider {
    fn info(&self) -> Provider {
        let engine = match self.backend {
            Backend::WhisperCpp { .. } => "whisper.cpp",
            #[cfg(target_os = "macos")]
            Backend::WhisperKit { .. } => "WhisperKit",
        };
        Provider {
            id: self.id.clone(),
            name: self.name.clone(),
            detail: format!("{engine} · shared from {}", self.source_name),
        }
    }
}

impl Model {
    fn info(&self, download_allowed: bool) -> ModelInfo {
        ModelInfo {
            id: self.id.clone(),
            name: self.name.clone(),
            download_size: self.download_size.into(),
            languages: self.languages.into(),
            description: self.description.into(),
            installed: self.path.is_file(),
            download_allowed,
        }
    }
}

fn verify_model(model: &Model) -> Result<()> {
    verify_path(&model.path, model.sha256, &model.name)
}

fn verify_path(path: &Path, expected_sha256: &str, display_name: &str) -> Result<()> {
    let metadata = fs::metadata(path).map_err(|source| EncapError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    let modified_ns = metadata
        .modified()
        .ok()
        .and_then(|value| value.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|value| value.as_nanos().min(u64::MAX as u128) as u64)
        .unwrap_or(0);
    let record = VerificationRecord {
        path: path.to_string_lossy().into_owned(),
        sha256: expected_sha256.into(),
        size: metadata.len(),
        modified_ns,
        valid: false,
    };
    let cache_key = format!("{display_name}:{expected_sha256}");
    if let Some(cached) = read_verification_cache()
        .entries
        .get(&cache_key)
        .filter(|cached| cached.same_file(&record))
    {
        return if cached.valid {
            Ok(())
        } else {
            Err(verification_error(display_name))
        };
    }
    let actual = sha256_file(path)?;
    let valid = actual == expected_sha256;
    store_verification_result(&cache_key, VerificationRecord { valid, ..record });
    if !valid {
        return Err(verification_error(display_name));
    }
    Ok(())
}

fn verification_error(display_name: &str) -> EncapError {
    EncapError::Message(format!(
        "{display_name} failed SHA-256 verification and cannot be used."
    ))
}

#[derive(Clone, Default, Deserialize, Serialize)]
struct VerificationCache {
    #[serde(default)]
    entries: BTreeMap<String, VerificationRecord>,
}

#[derive(Clone, Deserialize, Serialize)]
struct VerificationRecord {
    path: String,
    sha256: String,
    size: u64,
    modified_ns: u64,
    valid: bool,
}

impl VerificationRecord {
    fn same_file(&self, other: &Self) -> bool {
        self.path == other.path
            && self.sha256 == other.sha256
            && self.size == other.size
            && self.modified_ns == other.modified_ns
    }
}

fn verification_cache_path() -> Option<PathBuf> {
    std::env::var_os("ENCAP_MODEL_VERIFICATION_CACHE")
        .map(PathBuf::from)
        .or_else(|| {
            ProjectDirs::from("com", "TLO Labs", "EnCap")
                .map(|directories| directories.data_dir().join("model-verification.json"))
        })
}

fn read_verification_cache() -> VerificationCache {
    verification_cache_path()
        .and_then(|path| fs::read(path).ok())
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

fn store_verification_result(key: &str, record: VerificationRecord) {
    let Some(path) = verification_cache_path() else {
        return;
    };
    let Some(parent) = path.parent() else {
        return;
    };
    if fs::create_dir_all(parent).is_err() {
        return;
    }
    let mut cache = read_verification_cache();
    cache.entries.insert(key.into(), record);
    let Ok(bytes) = serde_json::to_vec_pretty(&cache) else {
        return;
    };
    let Ok(mut temporary) = tempfile::NamedTempFile::new_in(parent) else {
        return;
    };
    if temporary.write_all(&bytes).is_err() || temporary.as_file().sync_all().is_err() {
        return;
    }
    if let Ok(staged) = temporary.into_temp_path().keep() {
        let _ = replace_staged_file(&staged, &path);
    }
}

fn sha256_file(path: &Path) -> Result<String> {
    let mut input = fs::File::open(path).map_err(|source| EncapError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let count = input.read(&mut buffer).map_err(|source| EncapError::Read {
            path: path.to_path_buf(),
            source,
        })?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn resolve_provider(id: &str) -> Option<ResolvedProvider> {
    if let Some(provider) = shared_providers()
        .into_iter()
        .find(|provider| provider.id == id)
    {
        return Some(provider);
    }
    model_catalog()
        .into_iter()
        .find(|entry| entry.id == id && entry.path.is_file())
        .map(|model| ResolvedProvider {
            id: model.id,
            name: model.name.clone(),
            source_name: model.name,
            language_code: model.language_code.into(),
            backend: Backend::WhisperCpp {
                model: model.path,
                sha256: model.sha256.into(),
            },
        })
}

fn fallback_after_superwhisper() -> Option<ResolvedProvider> {
    shared_providers_without_superwhisper()
        .into_iter()
        .next()
        .or_else(|| {
            model_catalog()
                .into_iter()
                .find(|entry| entry.path.is_file())
                .map(|model| ResolvedProvider {
                    id: model.id,
                    name: model.name.clone(),
                    source_name: model.name,
                    language_code: model.language_code.into(),
                    backend: Backend::WhisperCpp {
                        model: model.path,
                        sha256: model.sha256.into(),
                    },
                })
        })
}

#[cfg(not(target_os = "macos"))]
fn shared_providers() -> Vec<ResolvedProvider> {
    Vec::new()
}

#[cfg(not(target_os = "macos"))]
fn shared_providers_without_superwhisper() -> Vec<ResolvedProvider> {
    Vec::new()
}

#[cfg(target_os = "macos")]
fn shared_providers() -> Vec<ResolvedProvider> {
    shared_providers_impl(false)
}

#[cfg(target_os = "macos")]
fn shared_providers_without_superwhisper() -> Vec<ResolvedProvider> {
    shared_providers_impl(true)
}

#[cfg(target_os = "macos")]
fn shared_providers_impl(skip_superwhisper: bool) -> Vec<ResolvedProvider> {
    let Some(home) = std::env::var_os("HOME").map(PathBuf::from) else {
        return Vec::new();
    };
    if !skip_superwhisper
        && application_is_installed(
            &home,
            &["superwhisper.app", "Superwhisper.app"],
            "com.superduper.superwhisper",
        )
    {
        let model = home
            .join("Library/Application Support/superwhisper")
            .join(SUPERWHISPER_FILENAME);
        if fs::metadata(&model)
            .is_ok_and(|metadata| metadata.is_file() && metadata.len() == SUPERWHISPER_SIZE)
            && locate_optional_tool("whisper-cli", "ENCAP_WHISPER_CLI").is_some()
        {
            return vec![ResolvedProvider {
                id: SUPERWHISPER_ID.into(),
                name: "Whisper Large V3 — Superwhisper".into(),
                source_name: "Superwhisper".into(),
                language_code: "auto".into(),
                backend: Backend::WhisperCpp {
                    model,
                    sha256: SUPERWHISPER_SHA256.into(),
                },
            }];
        }
    }

    if cfg!(not(target_arch = "aarch64"))
        || macos_major_version() < 14
        || locate_optional_tool("whisperkit-transcriber", "ENCAP_WHISPERKIT_TRANSCRIBER").is_none()
        || !application_is_installed(
            &home,
            &["Whisper Transcription.app", "MacWhisper.app"],
            "com.goodsnooze.MacWhisper",
        )
    {
        return Vec::new();
    }

    let roots = [
        home.join("Library/Containers/com.goodsnooze.MacWhisper/Data/Library/Application Support/MacWhisper/models"),
        home.join("Library/Application Support/MacWhisper/models"),
    ];
    let mut providers = Vec::new();
    for (folder, id, name, tokenizer_name) in MACWHISPER_MODELS {
        for root in &roots {
            let models = root.join("whisperkit/models");
            let model = models.join("argmaxinc/whisperkit-coreml").join(folder);
            let tokenizer_candidates = [
                models.join("openai").join(tokenizer_name),
                model.join("models/openai").join(tokenizer_name),
            ];
            let tokenizer = tokenizer_candidates
                .into_iter()
                .find(|path| valid_whisperkit_tokenizer(path));
            if valid_whisperkit_model(&model) {
                if let Some(tokenizer) = tokenizer {
                    providers.push(ResolvedProvider {
                        id: (*id).into(),
                        name: (*name).into(),
                        source_name: "Whisper Transcription".into(),
                        language_code: "auto".into(),
                        backend: Backend::WhisperKit { model, tokenizer },
                    });
                    break;
                }
            }
        }
    }
    providers
}

#[cfg(target_os = "macos")]
fn application_is_installed(home: &Path, names: &[&str], bundle_id: &str) -> bool {
    [PathBuf::from("/Applications"), home.join("Applications")]
        .into_iter()
        .flat_map(|root| names.iter().map(move |name| root.join(name)))
        .any(|candidate| {
            let info = candidate.join("Contents/Info.plist");
            fs::read(info).is_ok_and(|bytes| {
                bytes
                    .windows(bundle_id.len())
                    .any(|window| window == bundle_id.as_bytes())
            })
        })
}

#[cfg(target_os = "macos")]
fn macos_major_version() -> u32 {
    Command::new("/usr/bin/sw_vers")
        .arg("-productVersion")
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .and_then(|version| version.split('.').next()?.trim().parse().ok())
        .unwrap_or(0)
}

#[cfg(target_os = "macos")]
fn read_json_object(path: &Path) -> Option<serde_json::Map<String, serde_json::Value>> {
    let value: serde_json::Value = serde_json::from_slice(&fs::read(path).ok()?).ok()?;
    value.as_object().cloned()
}

#[cfg(target_os = "macos")]
fn positive_integer(value: Option<&serde_json::Value>) -> bool {
    value
        .and_then(serde_json::Value::as_i64)
        .is_some_and(|value| value > 0)
}

#[cfg(target_os = "macos")]
fn valid_whisperkit_model(path: &Path) -> bool {
    let Some(config) = read_json_object(&path.join("config.json")) else {
        return false;
    };
    let Some(generation) = read_json_object(&path.join("generation_config.json")) else {
        return false;
    };
    if config.get("model_type").and_then(|value| value.as_str()) != Some("whisper")
        || !positive_integer(config.get("d_model"))
        || !positive_integer(config.get("decoder_start_token_id"))
        || !generation
            .get("lang_to_id")
            .and_then(|value| value.as_object())
            .is_some_and(|value| !value.is_empty())
        || !generation
            .get("task_to_id")
            .and_then(|value| value.as_object())
            .is_some_and(|value| !value.is_empty())
        || !positive_integer(generation.get("no_timestamps_token_id"))
    {
        return false;
    }
    ["AudioEncoder", "MelSpectrogram", "TextDecoder"]
        .into_iter()
        .all(|component| {
            let root = path.join(format!("{component}.mlmodelc"));
            [
                root.join("model.mil"),
                root.join("coremldata.bin"),
                root.join("metadata.json"),
                root.join("weights/weight.bin"),
            ]
            .into_iter()
            .all(|file| {
                fs::metadata(file).is_ok_and(|metadata| metadata.is_file() && metadata.len() > 0)
            })
        })
}

#[cfg(target_os = "macos")]
fn valid_whisperkit_tokenizer(path: &Path) -> bool {
    let Some(tokenizer) = read_json_object(&path.join("tokenizer.json")) else {
        return false;
    };
    let Some(tokenizer_config) = read_json_object(&path.join("tokenizer_config.json")) else {
        return false;
    };
    let Some(config) = read_json_object(&path.join("config.json")) else {
        return false;
    };
    let model = tokenizer.get("model").and_then(|value| value.as_object());
    model
        .and_then(|value| value.get("type"))
        .and_then(|value| value.as_str())
        == Some("BPE")
        && model
            .and_then(|value| value.get("vocab"))
            .and_then(|value| value.as_object())
            .is_some_and(|value| !value.is_empty())
        && model
            .and_then(|value| value.get("merges"))
            .and_then(|value| value.as_array())
            .is_some_and(|value| !value.is_empty())
        && tokenizer_config
            .get("tokenizer_class")
            .and_then(|value| value.as_str())
            == Some("WhisperTokenizer")
        && tokenizer_config
            .get("added_tokens_decoder")
            .and_then(|value| value.as_object())
            .is_some_and(|value| !value.is_empty())
        && config.get("model_type").and_then(|value| value.as_str()) == Some("whisper")
        && positive_integer(config.get("d_model"))
        && positive_integer(config.get("decoder_start_token_id"))
}

fn model_catalog() -> Vec<Model> {
    let root = std::env::var_os("ENCAP_MODEL_DIR")
        .map(PathBuf::from)
        .or_else(|| {
            ProjectDirs::from("com", "TLO Labs", "EnCap").map(|dirs| dirs.data_dir().join("models"))
        })
        .unwrap_or_else(|| PathBuf::from("models"));
    vec![
        Model {
            id: "whisper-base-en".into(),
            path: root.join("ggml-base.en.bin"),
            name: "Whisper Base (English)".into(),
            download_url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/c521a4b02f422512d734391fdf08bb08c0862f68/ggml-base.en.bin?download=true",
            sha256: "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002",
            download_size: "148 MB",
            languages: "English",
            description: "Fast, compact, and the recommended starting point for English recordings.",
            language_code: "en",
            max_download_bytes: 200 * 1024 * 1024,
        },
        Model {
            id: "whisper-small".into(),
            path: root.join("ggml-small.bin"),
            name: "Whisper Small (Multilingual)".into(),
            download_url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/c521a4b02f422512d734391fdf08bb08c0862f68/ggml-small.bin?download=true",
            sha256: "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
            download_size: "488 MB",
            languages: "Multilingual",
            description: "A balanced multilingual model with better accuracy than Base.",
            language_code: "auto",
            max_download_bytes: 600 * 1024 * 1024,
        },
        Model {
            id: "whisper-large-v3-turbo".into(),
            path: root.join("ggml-large-v3-turbo.bin"),
            name: "Whisper Large v3 Turbo".into(),
            download_url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/6034871ec87c84e342efab769d4c5c06cd126db3/ggml-large-v3-turbo.bin?download=true",
            sha256: "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69",
            download_size: "1.62 GB",
            languages: "Multilingual",
            description: "Highest-quality catalog option; requires substantially more memory.",
            language_code: "auto",
            max_download_bytes: 2 * 1024 * 1024 * 1024,
        },
    ]
}

fn group_words(words: Vec<TranscriptSegment>) -> Vec<TranscriptSegment> {
    let mut grouped: Vec<TranscriptSegment> = Vec::new();
    for word in words {
        if let Some(current) = grouped.last_mut() {
            let gap = word.start_time_seconds - current.end_time_seconds;
            let sentence_ended = current
                .text
                .chars()
                .last()
                .is_some_and(|c| matches!(c, '.' | '?' | '!'));
            if gap <= 1.0
                && current.end_time_seconds - current.start_time_seconds < 10.0
                && !sentence_ended
            {
                let punctuation = word
                    .text
                    .chars()
                    .next()
                    .is_some_and(|c| matches!(c, ',' | '.' | '!' | '?' | ';' | ':' | ')'));
                if !punctuation {
                    current.text.push(' ');
                }
                current.text.push_str(&word.text);
                current.end_time_seconds = word.end_time_seconds;
                continue;
            }
        }
        grouped.push(word);
    }
    grouped
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn trusted_catalog_has_unique_ids_and_bounded_downloads() {
        let catalog = model_catalog();
        let ids: HashSet<_> = catalog.iter().map(|model| model.id.as_str()).collect();
        assert_eq!(ids.len(), catalog.len());
        assert!(catalog.iter().all(|model| {
            model.download_url.starts_with("https://huggingface.co/")
                && model.sha256.len() == 64
                && model.max_download_bytes > 0
        }));
    }

    #[test]
    fn file_hashing_is_streamed_and_deterministic() {
        let temporary = tempfile::tempdir().unwrap();
        let path = temporary.path().join("model.bin");
        fs::write(&path, b"hello").unwrap();
        assert_eq!(
            sha256_file(&path).unwrap(),
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        );
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn whisperkit_reuse_requires_complete_local_packages() {
        let temporary = tempfile::tempdir().unwrap();
        let model = temporary.path().join("model");
        fs::create_dir_all(&model).unwrap();
        fs::write(
            model.join("config.json"),
            br#"{"model_type":"whisper","d_model":1,"decoder_start_token_id":1}"#,
        )
        .unwrap();
        fs::write(
            model.join("generation_config.json"),
            br#"{"lang_to_id":{"en":1},"task_to_id":{"transcribe":1},"no_timestamps_token_id":1}"#,
        )
        .unwrap();
        for component in ["AudioEncoder", "MelSpectrogram", "TextDecoder"] {
            let compiled = model.join(format!("{component}.mlmodelc"));
            fs::create_dir_all(compiled.join("weights")).unwrap();
            for path in [
                compiled.join("model.mil"),
                compiled.join("coremldata.bin"),
                compiled.join("metadata.json"),
                compiled.join("weights/weight.bin"),
            ] {
                fs::write(path, b"present").unwrap();
            }
        }
        assert!(valid_whisperkit_model(&model));
        fs::remove_file(model.join("TextDecoder.mlmodelc/weights/weight.bin")).unwrap();
        assert!(!valid_whisperkit_model(&model));

        let tokenizer = temporary.path().join("tokenizer");
        fs::create_dir(&tokenizer).unwrap();
        fs::write(
            tokenizer.join("tokenizer.json"),
            br#"{"model":{"type":"BPE","vocab":{"a":1},"merges":["a b"]}}"#,
        )
        .unwrap();
        fs::write(
            tokenizer.join("tokenizer_config.json"),
            br#"{"tokenizer_class":"WhisperTokenizer","added_tokens_decoder":{"1":"x"}}"#,
        )
        .unwrap();
        fs::write(
            tokenizer.join("config.json"),
            br#"{"model_type":"whisper","d_model":1,"decoder_start_token_id":1}"#,
        )
        .unwrap();
        assert!(valid_whisperkit_tokenizer(&tokenizer));
        fs::write(tokenizer.join("tokenizer.json"), br#"{"model":{}}"#).unwrap();
        assert!(!valid_whisperkit_tokenizer(&tokenizer));
    }
}
