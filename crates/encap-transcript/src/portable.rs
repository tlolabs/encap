//! Explicit Tiny English addition, using Core's public model lease/inference APIs.
//! No downloader, third-party cache discovery or legacy GGML adoption exists.
use super::*;
use avid_transcription::{ModelManifest, ModelStore};
pub(super) const ID: &str = "whisper-cpp-tiny-en";
fn native(error: avid_transcription::Error) -> EncapError {
    let text = error.to_string();
    let source = match error {
        avid_transcription::Error::NativeMedia {
            code,
            operation,
            detail,
        } => Some(avid_core::Error::Linked {
            operation: "transcription_decode_audio",
            code,
            detail: format!("{operation}: {detail}"),
        }),
        avid_transcription::Error::NativeInference {
            code,
            kind,
            operation,
            detail,
        } => Some(avid_core::Error::NativeLibrary {
            library: "whisper.cpp",
            operation,
            code,
            kind,
            detail,
        }),
        _ => None,
    };
    match source {
        Some(source) => EncapError::Media {
            message: text,
            source: Box::new(source),
        },
        None => message(text),
    }
}
fn root() -> Result<PathBuf> {
    // This cache is owned by EnCAP and deliberately separate from historical
    // EnCAP GGML files and the Apple/third-party provider stores.
    #[cfg(debug_assertions)]
    if let Some(path) = std::env::var_os("ENCAP_AVID_PORTABLE_CACHE") {
        let path = PathBuf::from(path);
        if !path.is_absolute() {
            return Err(message("Portable model cache override must be absolute."));
        }
        return Ok(path);
    }
    directories::ProjectDirs::from("org", "tlolabs", "EnCAP")
        .map(|paths| paths.cache_dir().join("AVIDPortableTranscription"))
        .ok_or_else(|| message("A private EnCAP model cache could not be determined."))
}
pub(super) fn model() -> Result<ModelInfo> {
    let model = ModelManifest::tiny_english();
    let installation = model.installation_id().map_err(native)?;
    let installed = root()?
        .join(ID)
        .join(&installation)
        .join(&model.file)
        .is_file();
    Ok(ModelInfo {
        id: ID.into(), name: "Whisper Tiny English (portable CPU)".into(),
        download_size: format!("{} bytes", model.size_bytes), languages: "en".into(),
        description: "Explicit additional English-only Tiny model. It does not replace full Whisper large-v3 or the Apple provider catalog. Import the exact verified GGML file deliberately; downloading and forced alignment are unavailable.".into(),
        installed, download_allowed: false,
        extensions: BTreeMap::from([
            ("engine".into(), Value::String(model.runtime.clone())),
            ("role".into(), Value::String("recognizer".into())),
            ("is_default".into(), Value::Bool(false)),
            ("inference_compiled".into(), Value::Bool(cfg!(feature="portable-whisper"))),
            ("download_size_bytes".into(), model.size_bytes.into()),
            ("installation_id".into(), installation.into()),
            ("installation_state".into(), if installed {"present_unverified"} else {"missing"}.into()),
            ("revision".into(), model.revision.clone().into()),
            ("repository".into(), model.repository.clone().into()),
            ("sha256".into(), model.sha256.clone().into()),
            ("license".into(), model.model_license.clone().into()),
            ("recognition_languages".into(), serde_json::json!(["en"])),
            ("timing_languages".into(), serde_json::json!([])),
            ("forced_alignment".into(), Value::Bool(false)),
        ]),
    })
}
pub(super) fn import(source: &Path, cancellation: &CancellationToken) -> Result<ModelInfo> {
    let store = ModelStore::new(root()?).map_err(native)?;
    store
        .import(&ModelManifest::tiny_english(), source, &|| {
            cancellation.is_cancelled()
        })
        .map_err(native)?;
    let mut info = model()?;
    info.extensions
        .insert("installation_state".into(), "verified".into());
    Ok(info)
}
pub(super) fn remove() -> Result<ModelInfo> {
    ModelStore::new(root()?)
        .map_err(native)?
        .remove(&ModelManifest::tiny_english())
        .map_err(native)?;
    model()
}
pub(super) fn verify(cancellation: &CancellationToken) -> Result<ModelInfo> {
    let store = ModelStore::new(root()?).map_err(native)?;
    let _lease = store
        .lease(&ModelManifest::tiny_english(), &|| {
            cancellation.is_cancelled()
        })
        .map_err(native)?;
    let mut info = model()?;
    info.extensions
        .insert("installation_state".into(), "verified".into());
    Ok(info)
}
/// Convert the actual public Core record to the EnCAP adapter schema. Keep the
/// complete model/tokenizer/runtime identity and source clock exactly once.
#[cfg(feature = "portable-whisper")]
fn wire(record: avid_transcription::Transcript) -> Value {
    fn provenance(value: avid_transcription::Provenance) -> Value {
        serde_json::json!({"engine_id":value.engine_id,"model_id":value.model_id,
            "model_identity":value.model_identity,"runtime_revisions":value.runtime_revisions,
            "runtime_build_sha256":value.runtime_build_sha256})
    }
    serde_json::json!({"language":record.language,"provenance":provenance(record.provenance),
        "alignment_provenance":record.alignment_provenance.map(provenance),
        "segments":record.segments.into_iter().map(|s| serde_json::json!({"text":s.text,
            "start_seconds":s.start_seconds,"end_seconds":s.end_seconds,
            "words":s.words.into_iter().map(|w|serde_json::json!({"text":w.text,
                "start_seconds":w.start_seconds,"end_seconds":w.end_seconds,
                "confidence":w.confidence,"timing_method":w.timing_method})).collect::<Vec<_>>()
        })).collect::<Vec<_>>()})
}
pub(super) fn recognize(
    audio: &Path,
    language: Option<&str>,
    cancellation: &CancellationToken,
) -> Result<Value> {
    #[cfg(feature = "portable-whisper")]
    {
        let store = ModelStore::new(root()?).map_err(native)?;
        let lease = store
            .lease(&ModelManifest::tiny_english(), &|| {
                cancellation.is_cancelled()
            })
            .map_err(native)?;
        let result = avid_transcription::recognize_audio(
            &lease,
            audio,
            &avid_transcription::RecognitionOptions {
                language,
                ..Default::default()
            },
            &|| cancellation.is_cancelled(),
            &|progress| {
                encap_core::emit_progress(serde_json::json!({"event":"progress",
                    "stage":progress.stage,"fraction":progress.fraction,"model_id":ID}));
            },
        )
        .map_err(native)?;
        Ok(wire(result))
    }
    #[cfg(not(feature = "portable-whisper"))]
    {
        let _ = (audio, language, cancellation);
        Err(message("Portable Tiny English recognition was not compiled. Build explicitly with portable-whisper and the verified target SDK; full Whisper remains a separate provider."))
    }
}
