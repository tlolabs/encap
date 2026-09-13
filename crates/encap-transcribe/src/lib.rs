//! Local transcription mode and provider discovery.

use directories::ProjectDirs;
use encap_core::{AudioSource, EncapError, Result, TranscriptSegment};
use encap_ffmpeg::{locate_optional_tool, os, CancellationToken, MediaTools};
use serde::Serialize;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Serialize)]
pub struct Provider {
    pub id: String,
    pub name: String,
    pub detail: String,
}

pub fn providers() -> Vec<Provider> {
    let mut output = Vec::new();
    if cfg!(target_os = "macos")
        && locate_optional_tool("apple-transcriber", "ENCAP_APPLE_TRANSCRIBER").is_some()
    {
        output.push(Provider {
            id: "apple-local".into(),
            name: "Apple On-Device".into(),
            detail: "Apple Speech · on this Mac".into(),
        });
    }
    for model in model_catalog() {
        if model.path.is_file()
            && locate_optional_tool("whisper-cli", "ENCAP_WHISPER_CLI").is_some()
        {
            output.push(Provider {
                id: model.id,
                name: model.name,
                detail: "whisper.cpp · local model".into(),
            });
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
    let model = provider_by_id(provider);
    if provider != "apple-local" && model.is_none() {
        return Err(EncapError::Message(
            "The selected transcription engine is unavailable.".into(),
        ));
    }
    let mut output = Vec::new();
    let mut offset = 0.0;
    for source in sources {
        let mut segments = if provider == "apple-local" {
            transcribe_apple(&source.source_path, offset, cancellation)?
        } else {
            transcribe_whisper(
                &tools,
                &source.source_path,
                &model.as_ref().unwrap().path,
                offset,
                cancellation,
            )?
        };
        output.append(&mut segments);
        offset += source.duration_seconds;
    }
    Ok(output)
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
            os("auto"),
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
}

fn provider_by_id(id: &str) -> Option<Model> {
    model_catalog()
        .into_iter()
        .find(|entry| entry.id == id && entry.path.is_file())
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
        },
        Model {
            id: "whisper-small".into(),
            path: root.join("ggml-small.bin"),
            name: "Whisper Small (Multilingual)".into(),
        },
        Model {
            id: "whisper-large-v3-turbo".into(),
            path: root.join("ggml-large-v3-turbo.bin"),
            name: "Whisper Large v3 Turbo".into(),
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
