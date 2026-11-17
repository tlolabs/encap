//! The only unsafe code is foreign buffer access at this narrow C boundary.
use crate::{ApplicationConfig, Operation};
use encap_core::{EncapError, Result};
use encap_ffmpeg::CancellationToken;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    ffi::c_void,
    path::{Component, Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex, OnceLock,
    },
};

pub const ENCAP_APP_ABI_VERSION: u32 = 1;
pub const ENCAP_APP_SCHEMA_VERSION: u32 = 1;
pub const ENCAP_APP_MAX_REQUEST: usize = 64 * 1024;
pub const ENCAP_APP_MAX_RESULT: usize = 64 * 1024 * 1024;
pub type EncapEventCallback = Option<unsafe extern "C" fn(*mut c_void, *const u8, usize)>;

enum Handle {
    Application(ApplicationConfig),
    Cancellation(CancellationToken),
    Buffer(Vec<u8>),
}
static HANDLES: OnceLock<Mutex<HashMap<u64, Arc<Handle>>>> = OnceLock::new();
static NEXT: AtomicU64 = AtomicU64::new(1);
fn handles() -> &'static Mutex<HashMap<u64, Arc<Handle>>> {
    HANDLES.get_or_init(Default::default)
}
fn next_identifier() -> Option<u64> {
    let mut current = NEXT.load(Ordering::Relaxed);
    loop {
        let next = current.checked_add(1)?;
        match NEXT.compare_exchange_weak(current, next, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_) => return Some(current),
            Err(observed) => current = observed,
        }
    }
}
fn insert(value: Handle) -> u64 {
    let Some(id) = next_identifier() else {
        return 0;
    };
    let Ok(mut entries) = handles().lock() else {
        return 0;
    };
    entries.insert(id, Arc::new(value));
    id
}
fn get(id: u64) -> Option<Arc<Handle>> {
    handles().lock().ok()?.get(&id).cloned()
}
fn guarded<T: Default>(operation: impl FnOnce() -> T) -> T {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(operation)).unwrap_or_default()
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Configuration {
    schema_version: u32,
    recovery_path: Option<PathBuf>,
}
#[derive(Deserialize)]
struct Request {
    schema_version: u32,
    #[serde(flatten)]
    operation: Operation,
}

#[no_mangle]
pub extern "C" fn encap_app_abi_version() -> u32 {
    ENCAP_APP_ABI_VERSION
}
#[no_mangle]
pub extern "C" fn encap_app_schema_version() -> u32 {
    ENCAP_APP_SCHEMA_VERSION
}
#[no_mangle]
pub extern "C" fn encap_app_create() -> u64 {
    guarded(|| insert(Handle::Application(ApplicationConfig::default())))
}
/// # Safety
/// `request` must designate `length` readable bytes until this function returns.
#[no_mangle]
pub unsafe extern "C" fn encap_app_create_json(request: *const u8, length: usize) -> u64 {
    guarded(|| {
        if request.is_null() || length == 0 || length > ENCAP_APP_MAX_REQUEST {
            return 0;
        }
        let Ok(config) = serde_json::from_slice::<Configuration>(unsafe {
            std::slice::from_raw_parts(request, length)
        }) else {
            return 0;
        };
        if config.schema_version != ENCAP_APP_SCHEMA_VERSION
            || config
                .recovery_path
                .as_ref()
                .is_some_and(|path| !valid_local_path(path))
        {
            return 0;
        }
        insert(Handle::Application(ApplicationConfig {
            recovery_path: config.recovery_path,
        }))
    })
}
#[no_mangle]
pub extern "C" fn encap_app_cancel_create() -> u64 {
    guarded(|| insert(Handle::Cancellation(CancellationToken::default())))
}
#[no_mangle]
pub extern "C" fn encap_app_cancel(token: u64) -> i32 {
    std::panic::catch_unwind(|| match get(token).as_deref() {
        Some(Handle::Cancellation(token)) => {
            token.cancel();
            0
        }
        _ => -1,
    })
    .unwrap_or(-1)
}
#[no_mangle]
pub extern "C" fn encap_app_release(handle: u64) -> i32 {
    std::panic::catch_unwind(|| {
        handles()
            .lock()
            .map(|mut handles| {
                if handles.remove(&handle).is_some() {
                    0
                } else {
                    -1
                }
            })
            .unwrap_or(-1)
    })
    .unwrap_or(-1)
}
#[no_mangle]
pub extern "C" fn encap_app_buffer_len(handle: u64) -> usize {
    guarded(|| match get(handle).as_deref() {
        Some(Handle::Buffer(bytes)) => bytes.len(),
        _ => 0,
    })
}
/// # Safety
/// `output` must designate `capacity` writable bytes for the duration of this call.
#[no_mangle]
pub unsafe extern "C" fn encap_app_buffer_copy(
    handle: u64,
    output: *mut u8,
    capacity: usize,
) -> usize {
    guarded(|| {
        let Some(value) = get(handle) else { return 0 };
        let Handle::Buffer(bytes) = value.as_ref() else {
            return 0;
        };
        if output.is_null() || capacity < bytes.len() {
            return 0;
        }
        unsafe {
            std::ptr::copy_nonoverlapping(bytes.as_ptr(), output, bytes.len());
        }
        bytes.len()
    })
}
fn response(value: Value) -> u64 {
    match serde_json::to_vec(&value) {
        Ok(bytes) if bytes.len() <= ENCAP_APP_MAX_RESULT => insert(Handle::Buffer(bytes)),
        _ => insert(Handle::Buffer(br#"{"schema_version":1,"ok":false,"error":{"code":"result_too_large","detail":"The application result exceeds its 64 MiB transport limit; no result was truncated."}}"#.to_vec())),
    }
}
fn failure(code: &str, detail: &str) -> u64 {
    response(json!({"schema_version":1,"ok":false,"error":{"code":code,"detail":detail}}))
}
fn error_code(error: &EncapError) -> &'static str {
    match error {
        EncapError::Read { .. } => "read",
        EncapError::Write { .. } => "write",
        EncapError::Archive(_) => "archive",
        EncapError::Json(_) => "project_json",
        EncapError::UnsupportedAudio(_) => "unsupported_audio",
        EncapError::UnsupportedSchema { .. } => "unsupported_schema",
        EncapError::Message(_) => "application",
        EncapError::Media { source, .. } => source.code(),
    }
}
fn native_diagnostic(error: &avid_core::Error) -> Value {
    let mut value = json!({"code":error.code()});
    match error {
        avid_core::Error::Linked {
            operation, code, ..
        } => {
            value["library"] = json!("libav");
            value["operation"] = json!(operation);
            value["native_code"] = json!(code);
        }
        avid_core::Error::NativeLibrary {
            library,
            operation,
            code,
            kind,
            ..
        } => {
            value["library"] = json!(library);
            value["operation"] = json!(operation);
            value["native_code"] = json!(code);
            value["native_kind"] = json!(kind);
        }
        avid_core::Error::Fallback { hardware, software } => {
            value["hardware"] = native_diagnostic(hardware);
            value["software"] = native_diagnostic(software);
        }
        avid_core::Error::Deadline { operation } | avid_core::Error::Io { operation, .. } => {
            value["operation"] = json!(operation);
        }
        avid_core::Error::Unsupported { capability, .. } => {
            value["capability"] = json!(capability);
        }
        _ => {}
    }
    value
}
fn application_failure(error: &EncapError) -> u64 {
    let mut details = json!({"code":error_code(error),"detail":error.to_string()});
    if let EncapError::Media { source, .. } = error {
        let diagnostic = native_diagnostic(source);
        if let Some(fields) = diagnostic.as_object() {
            for (key, value) in fields {
                details[key] = value.clone();
            }
        }
    }
    response(json!({"schema_version":1,"ok":false,"error":details}))
}

fn event(callback: EncapEventCallback, context: *mut c_void, event: Value) {
    if let (Some(callback), Ok(bytes)) = (callback, serde_json::to_vec(&event)) {
        unsafe { callback(context, bytes.as_ptr(), bytes.len()) };
    }
}
/// # Safety
/// The request span and callback context must remain valid until return. Callback
/// bytes are borrowed for that callback only. Foreign callbacks must not unwind.
#[no_mangle]
pub unsafe extern "C" fn encap_app_execute_json(
    application: u64,
    cancellation: u64,
    request: *const u8,
    length: usize,
    callback: EncapEventCallback,
    context: *mut c_void,
) -> u64 {
    guarded(|| {
        let Some(application) = get(application) else {
            return failure("invalid_handle", "Invalid application handle.");
        };
        let Handle::Application(config) = application.as_ref() else {
            return failure("invalid_handle", "Expected an application handle.");
        };
        let Some(cancellation) = get(cancellation) else {
            return failure("invalid_handle", "Invalid cancellation handle.");
        };
        let Handle::Cancellation(token) = cancellation.as_ref() else {
            return failure("invalid_handle", "Expected a cancellation handle.");
        };
        if request.is_null() || length == 0 || length > ENCAP_APP_MAX_REQUEST {
            return failure(
                "request_size",
                "Application requests must contain 1 to 65536 bytes.",
            );
        }
        let request = unsafe { std::slice::from_raw_parts(request, length) };
        if let Err(error) = validate_request_fields(request) {
            return failure("invalid_request", &error);
        }
        let request = match serde_json::from_slice::<Request>(request) {
            Ok(request) => request,
            Err(error) => return failure("invalid_request", &error.to_string()),
        };
        if request.schema_version != ENCAP_APP_SCHEMA_VERSION {
            return failure("schema_version", "Unsupported application request schema.");
        }
        if let Err(error) = validate_paths(&request.operation) {
            return failure("invalid_path", &error.to_string());
        }
        event(
            callback,
            context,
            json!({"schema_version":1,"event":"stage","stage":"started"}),
        );
        let context_address = context as usize;
        let handler: encap_core::ProgressHandler = Arc::new(move |mut progress| {
            if let Some(object) = progress.as_object_mut() {
                object.insert("schema_version".into(), json!(1));
            }
            event(callback, context_address as *mut c_void, progress);
        });
        let result = encap_core::with_progress_handler(handler, || {
            crate::execute_with_config(request.operation, token, token, config)
        });
        match result {
            Ok(result) => {
                event(
                    callback,
                    context,
                    json!({"schema_version":1,"event":"complete"}),
                );
                response(json!({"schema_version":1,"ok":true,"result":result}))
            }
            Err(error) => {
                tracing::error!(%error, "linked application operation failed");
                application_failure(&error)
            }
        }
    })
}

fn validate_request_fields(bytes: &[u8]) -> std::result::Result<(), String> {
    let value: Value = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    let object = value
        .as_object()
        .ok_or("Expected an application request object.")?;
    let fields: &[&str] = match object.get("operation").and_then(Value::as_str) {
        Some("inspect") => &["folder"],
        Some("waveform") => &["file"],
        Some("inspect-files") => &["files"],
        Some("edit-audio") => &["payload", "edits"],
        Some("open") => &["project", "extraction_parent"],
        Some("save") => &["payload", "project"],
        Some("export") => &["payload", "output"],
        Some("export-video") => &["payload", "output", "render_mode"],
        Some("inspect-artwork") => &["image"],
        Some("optimize-artwork") => &["payload", "image", "output"],
        Some("preview-video") => &["payload", "output", "chapter_id"],
        Some("export-transcript" | "export-captions") => &["payload", "output", "format"],
        Some("transcribe") => &[
            "payload",
            "provider",
            "word_timestamps",
            "language",
            "alignment_model",
        ],
        Some("realign") => &["payload", "model", "language"],
        Some("install-model" | "remove-model" | "verify-model") => &["model"],
        Some("import-model") => &["model", "source"],
        Some("save-recovery") => &["payload"],
        Some("validate-core-runtime") => &["directory"],
        Some(
            "build-info"
            | "startup"
            | "video-presets"
            | "video-capabilities"
            | "transcription-status"
            | "providers"
            | "models"
            | "load-recovery"
            | "clear-recovery"
            | "validate-tools"
            | "validate-compatibility-tools",
        ) => &[],
        _ => return Err("Unknown application operation.".into()),
    };
    if let Some(unknown) = object.keys().find(|key| {
        key.as_str() != "schema_version"
            && key.as_str() != "operation"
            && !fields.contains(&key.as_str())
    }) {
        return Err(format!("Unknown application request field: {unknown}"));
    }
    Ok(())
}

fn valid_local_path(path: &Path) -> bool {
    let text = path.to_string_lossy();
    !text.is_empty() && !text.contains('\0') && !text.contains("://")
}
fn validate_paths(operation: &Operation) -> Result<()> {
    use Operation::*;
    let mut paths: Vec<&Path> = Vec::new();
    match operation {
        Inspect { folder } => paths.push(folder),
        Waveform { file } => paths.push(file),
        InspectFiles { files } => paths.extend(files.iter().map(PathBuf::as_path)),
        EditAudio { payload, edits } => paths.extend([payload.as_path(), edits.as_path()]),
        Open {
            project,
            extraction_parent,
        } => {
            paths.push(project);
            paths.extend(extraction_parent.as_deref());
        }
        Save { payload, project } => paths.extend([payload.as_path(), project.as_path()]),
        Export { payload, output }
        | ExportVideo {
            payload, output, ..
        }
        | PreviewVideo {
            payload, output, ..
        }
        | ExportTranscript {
            payload, output, ..
        }
        | ExportCaptions {
            payload, output, ..
        } => paths.extend([payload.as_path(), output.as_path()]),
        OptimizeArtwork {
            payload,
            image,
            output,
        } => paths.extend([payload.as_path(), image.as_path(), output.as_path()]),
        InspectArtwork { image } => paths.push(image),
        Transcribe { payload, .. } | Realign { payload, .. } | SaveRecovery { payload } => {
            paths.push(payload)
        }
        ImportModel { source, .. } => paths.push(source),
        ValidateCoreRuntime { directory } => paths.push(directory),
        _ => {}
    }
    if paths.iter().all(|path| valid_local_path(path)) {
        Ok(())
    } else {
        Err(EncapError::Message(
            "Expected a nonempty local path without a NUL or URI scheme.".into(),
        ))
    }
}

static WRITERS: OnceLock<Mutex<Vec<(u64, PathBuf)>>> = OnceLock::new();
pub(crate) struct WriterLease(u64);
impl Drop for WriterLease {
    fn drop(&mut self) {
        if let Ok(mut writers) = WRITERS.get_or_init(Default::default).lock() {
            writers.retain(|entry| entry.0 != self.0);
        }
    }
}
fn normalized_path(path: &Path) -> Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|source| EncapError::Read {
                path: path.to_path_buf(),
                source,
            })?
            .join(path)
    };
    // Resolve the longest existing ancestor before simplifying `..`: an
    // existing symlink/.. pair has filesystem semantics, not lexical semantics.
    let components: Vec<_> = absolute.components().collect();
    for boundary in (0..=components.len()).rev() {
        let ancestor: PathBuf = components[..boundary].iter().collect();
        if let Ok(mut resolved) = ancestor.canonicalize() {
            for component in &components[boundary..] {
                match component {
                    Component::CurDir => {}
                    Component::ParentDir => {
                        resolved.pop();
                    }
                    other => resolved.push(other.as_os_str()),
                }
            }
            return Ok(resolved);
        }
    }
    Err(EncapError::Message(
        "The output path has no accessible filesystem ancestor.".into(),
    ))
}
pub(crate) fn reserve_output(
    operation: &Operation,
    config: &ApplicationConfig,
) -> Result<Option<WriterLease>> {
    use Operation::*;
    let path = match operation {
        Save { project, .. } => Some(encap_core::project_save_path(project)),
        Export { output, .. }
        | ExportVideo { output, .. }
        | PreviewVideo { output, .. }
        | OptimizeArtwork { output, .. }
        | ExportTranscript { output, .. }
        | ExportCaptions { output, .. } => Some(output.clone()),
        SaveRecovery { .. } | ClearRecovery => Some(crate::configured_recovery_path(config)?),
        _ => None,
    };
    let Some(path) = path else { return Ok(None) };
    let path = normalized_path(&path)?;
    let mut writers = WRITERS
        .get_or_init(Default::default)
        .lock()
        .map_err(|_| EncapError::Message("Application output registry is unavailable.".into()))?;
    if writers
        .iter()
        .any(|(_, active)| active == &path || encap_core::conflicts_with_path(active, &path))
    {
        return Err(EncapError::Message(
            "Another application operation is already writing this destination.".into(),
        ));
    }
    let id = next_identifier().ok_or_else(|| {
        EncapError::Message("Application operation identifiers are exhausted.".into())
    })?;
    writers.push((id, path));
    Ok(Some(WriterLease(id)))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn execute_bytes(application: u64, token: u64, bytes: &[u8]) -> Value {
        let result = unsafe {
            encap_app_execute_json(
                application,
                token,
                bytes.as_ptr(),
                bytes.len(),
                None,
                std::ptr::null_mut(),
            )
        };
        assert_ne!(result, 0);
        let len = encap_app_buffer_len(result);
        assert!(len > 0 && len <= ENCAP_APP_MAX_RESULT);
        let mut bytes = vec![0; len];
        assert_eq!(
            unsafe { encap_app_buffer_copy(result, bytes.as_mut_ptr(), len - 1) },
            0
        );
        assert_eq!(
            unsafe { encap_app_buffer_copy(result, bytes.as_mut_ptr(), len) },
            len
        );
        assert_eq!(encap_app_release(result), 0);
        assert_eq!(encap_app_buffer_len(result), 0);
        serde_json::from_slice(&bytes).unwrap()
    }
    #[test]
    fn typed_handles_schema_bounds_and_independent_cancellation() {
        assert_eq!(encap_app_abi_version(), 1);
        assert_eq!(encap_app_schema_version(), 1);
        let app = encap_app_create();
        let token = encap_app_cancel_create();
        let request = br#"{"schema_version":1,"operation":"build-info"}"#;
        let result = execute_bytes(app, token, request);
        assert_eq!(result["ok"], true);
        assert_eq!(result["result"]["encap_version"], env!("CARGO_PKG_VERSION"));
        for (a, t) in [(0, token), (token, token), (app, app)] {
            assert_eq!(
                execute_bytes(a, t, request)["error"]["code"],
                "invalid_handle"
            );
        }
        assert_eq!(
            execute_bytes(
                app,
                token,
                br#"{"schema_version":2,"operation":"build-info"}"#
            )["error"]["code"],
            "schema_version"
        );
        assert_eq!(
            execute_bytes(
                app,
                token,
                br#"{"schema_version":1,"operation":"build-info","unexpected":true}"#
            )["error"]["code"],
            "invalid_request"
        );
        assert_eq!(
            execute_bytes(app, token, &vec![b' '; ENCAP_APP_MAX_REQUEST + 1])["error"]["code"],
            "request_size"
        );
        assert_eq!(
            execute_bytes(
                app,
                token,
                br#"{"schema_version":1,"operation":"inspect","folder":"file://bad"}"#
            )["error"]["code"],
            "invalid_path"
        );
        assert_eq!(encap_app_cancel(token), 0);
        assert_eq!(execute_bytes(app, token, request)["ok"], false);
        let independent = encap_app_cancel_create();
        assert_eq!(execute_bytes(app, independent, request)["ok"], true);
        assert_eq!(encap_app_cancel(app), -1);
        for handle in [app, token, independent] {
            assert_eq!(encap_app_release(handle), 0);
            assert_eq!(encap_app_release(handle), -1);
        }
    }
    #[test]
    fn callbacks_can_release_handles_without_detaching_work() {
        struct Context {
            app: u64,
            token: u64,
            events: Vec<Value>,
        }
        unsafe extern "C" fn callback(context: *mut c_void, data: *const u8, length: usize) {
            let context = unsafe { &mut *(context as *mut Context) };
            let copy = unsafe { std::slice::from_raw_parts(data, length) }.to_vec();
            context.events.push(serde_json::from_slice(&copy).unwrap());
            encap_app_release(context.app);
            encap_app_release(context.token);
        }
        let app = encap_app_create();
        let token = encap_app_cancel_create();
        let mut context = Context {
            app,
            token,
            events: Vec::new(),
        };
        let request = br#"{"schema_version":1,"operation":"build-info"}"#;
        let result = unsafe {
            encap_app_execute_json(
                app,
                token,
                request.as_ptr(),
                request.len(),
                Some(callback),
                &mut context as *mut _ as *mut c_void,
            )
        };
        assert!(encap_app_buffer_len(result) > 0);
        assert_eq!(context.events.len(), 2);
        assert_eq!(context.events[0]["event"], "stage");
        assert_eq!(context.events[1]["event"], "complete");
        encap_app_release(result);
        assert_eq!(encap_app_release(app), -1);
    }
    #[test]
    fn recovery_configuration_is_per_application_and_never_changes_environment() {
        let root = tempfile::tempdir().unwrap();
        let first = root.path().join("first.json");
        let second = root.path().join("second.json");
        std::fs::write(
            &first,
            serde_json::to_vec(&encap_core::ProjectDocument::default()).unwrap(),
        )
        .unwrap();
        let create = |path: &Path| {
            let bytes =
                serde_json::to_vec(&json!({"schema_version":1,"recovery_path":path})).unwrap();
            unsafe { encap_app_create_json(bytes.as_ptr(), bytes.len()) }
        };
        let a = create(&first);
        let b = create(&second);
        let token = encap_app_cancel_create();
        let request = br#"{"schema_version":1,"operation":"load-recovery"}"#;
        assert!(execute_bytes(a, token, request)["result"]["project"].is_object());
        assert!(execute_bytes(b, token, request)["result"]["project"].is_null());
        for handle in [a, b, token] {
            encap_app_release(handle);
        }
    }
    #[test]
    fn full_project_payload_does_not_cross_media_request_limit() {
        let root = tempfile::tempdir().unwrap();
        let payload = root.path().join("payload.json");
        let mut project = encap_core::ProjectDocument::default();
        project.extensions.insert(
            "large_compatibility_payload".into(),
            Value::String("x".repeat(4 * 1024 * 1024 + 100)),
        );
        std::fs::write(&payload, serde_json::to_vec(&project).unwrap()).unwrap();
        let restored = crate::read_payload(&payload).unwrap();
        assert_eq!(restored, project);
        std::fs::write(&payload, vec![b' '; 8 * 1024 * 1024 + 1]).unwrap();
        assert!(crate::read_payload(&payload)
            .unwrap_err()
            .to_string()
            .contains("8 MiB"));
    }
    #[test]
    fn native_domains_and_fallbacks_survive_without_raw_diagnostic_text() {
        let error = EncapError::from(avid_core::Error::Fallback {
            hardware: Box::new(avid_core::Error::Linked {
                operation: "open encoder",
                code: -12908,
                detail: "private diagnostic".into(),
            }),
            software: Box::new(avid_core::Error::NativeLibrary {
                library: "whisper",
                operation: "decode",
                code: 7,
                kind: "allocation",
                detail: "private diagnostic".into(),
            }),
        });
        let result = application_failure(&error);
        let mut bytes = vec![0; encap_app_buffer_len(result)];
        assert_eq!(
            unsafe { encap_app_buffer_copy(result, bytes.as_mut_ptr(), bytes.len()) },
            bytes.len()
        );
        encap_app_release(result);
        let value: Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(value["error"]["hardware"]["library"], "libav");
        assert_eq!(value["error"]["hardware"]["native_code"], -12908);
        assert_eq!(value["error"]["software"]["library"], "whisper");
        assert_eq!(value["error"]["software"]["native_kind"], "allocation");
        assert!(!String::from_utf8(bytes)
            .unwrap()
            .contains("private diagnostic"));
    }

    #[test]
    fn save_output_leases_reserve_the_effective_archive_name() {
        let root = tempfile::tempdir().unwrap();
        let operation = |destination| Operation::Save {
            payload: root.path().join("payload.json"),
            project: destination,
        };
        let config = ApplicationConfig::default();
        for requested in ["new", "new.wav", "new.ENCAP"] {
            let requested = root.path().join(requested);
            let effective = encap_core::project_save_path(&requested);
            assert!(!effective.exists());
            let lease = reserve_output(&operation(requested), &config).unwrap();
            assert!(reserve_output(&operation(effective.clone()), &config).is_err());
            // Every other operation writing the resolved archive also conflicts.
            assert!(reserve_output(
                &Operation::ExportTranscript {
                    payload: root.path().join("payload.json"),
                    output: effective.clone(),
                    format: crate::TranscriptFormat::Txt,
                },
                &config,
            )
            .is_err());
            drop(lease);
            assert!(reserve_output(&operation(effective), &config).is_ok());
        }
    }

    #[test]
    fn output_leases_reject_aliases_and_release_after_cleanup() {
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("output.encap");
        std::fs::write(&output, b"existing").unwrap();
        let alias = root.path().join("alias.encap");
        std::fs::hard_link(&output, &alias).unwrap();
        let operation = |destination| Operation::Save {
            payload: root.path().join("payload.json"),
            project: destination,
        };
        let config = ApplicationConfig::default();
        let lease = reserve_output(&operation(output.clone()), &config).unwrap();
        assert!(reserve_output(&operation(alias), &config).is_err());
        assert!(reserve_output(&operation(root.path().join("./output.encap")), &config).is_err());
        drop(lease);
        assert!(reserve_output(&operation(output), &config).is_ok());
        #[cfg(unix)]
        {
            let real = root.path().join("real/child");
            std::fs::create_dir_all(&real).unwrap();
            let alias = root.path().join("directory-alias");
            std::os::unix::fs::symlink(&real, &alias).unwrap();
            let destination = root.path().join("real/new.encap");
            let lease = reserve_output(&operation(destination), &config).unwrap();
            assert!(reserve_output(&operation(alias.join("../new.encap")), &config).is_err());
            drop(lease);
            let destination = real.join("missing/nested/new.encap");
            let lease = reserve_output(&operation(destination), &config).unwrap();
            assert!(
                reserve_output(&operation(alias.join("missing/nested/new.encap")), &config)
                    .is_err()
            );
            drop(lease);
        }
    }
}
