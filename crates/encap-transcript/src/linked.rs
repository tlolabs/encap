//! Optional Apple module isolation: the base host still targets macOS 13/Intel.
//! Libraries remain loaded for the process lifetime; no worker may outlive invoke.
use super::*;

#[cfg(not(target_os = "macos"))]
pub(super) fn invoke(_: &Path, _: &[OsString], _: &CancellationToken) -> Result<Vec<u8>> {
    Err(message(PLATFORM_REASON))
}

#[cfg(target_os = "macos")]
mod apple {
    use super::*;
    use std::ffi::{c_char, c_int, c_void, CString};
    use std::sync::{
        atomic::{AtomicBool, Ordering},
        OnceLock,
    };
    use std::time::Duration;

    type Event = unsafe extern "C" fn(*mut c_void, *const u8, usize);
    struct Library {
        // Retain the native module (and all Swift/Metal code) until process exit.
        _handle: usize,
        create: unsafe extern "C" fn() -> u64,
        cancel: unsafe extern "C" fn(u64) -> i32,
        release: unsafe extern "C" fn(u64),
        execute: unsafe extern "C" fn(u64, *const u8, usize, Option<Event>, *mut c_void) -> u64,
        size: unsafe extern "C" fn(u64) -> usize,
        copy: unsafe extern "C" fn(u64, *mut u8, usize) -> i32,
    }
    unsafe extern "C" {
        fn dlopen(path: *const c_char, flags: c_int) -> *mut c_void;
        fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
        fn dlerror() -> *const c_char;
    }
    impl Library {
        fn load(path: &Path) -> std::result::Result<Self, String> {
            use std::os::unix::ffi::OsStrExt;
            let path = CString::new(path.as_os_str().as_bytes())
                .map_err(|_| "Library path contains NUL.")?;
            // RTLD_NOW | RTLD_LOCAL: resolve actual deployment dependencies now,
            // never expose private provider symbols to unrelated host modules.
            let handle = unsafe { dlopen(path.as_ptr(), 2 | 4) };
            if handle.is_null() {
                let error = unsafe { dlerror() };
                return Err(if error.is_null() {
                    "Failed to load linked transcription library.".into()
                } else {
                    unsafe { std::ffi::CStr::from_ptr(error) }
                        .to_string_lossy()
                        .into_owned()
                });
            }
            macro_rules! symbol {
                ($name:literal, $kind:ty) => {{
                    let symbol = CString::new($name).unwrap();
                    let pointer = unsafe { dlsym(handle, symbol.as_ptr()) };
                    if pointer.is_null() {
                        return Err(format!(
                            "Linked transcription ABI symbol missing: {}",
                            $name
                        ));
                    }
                    unsafe { std::mem::transmute::<*mut c_void, $kind>(pointer) }
                }};
            }
            let version = symbol!(
                "encap_transcription_abi_version",
                unsafe extern "C" fn() -> u32
            );
            if unsafe { version() } != 1 {
                return Err("Unsupported linked transcription ABI version.".into());
            }
            Ok(Self {
                _handle: handle as usize,
                create: symbol!(
                    "encap_transcription_token_create",
                    unsafe extern "C" fn() -> u64
                ),
                cancel: symbol!(
                    "encap_transcription_cancel",
                    unsafe extern "C" fn(u64) -> i32
                ),
                release: symbol!("encap_transcription_release", unsafe extern "C" fn(u64)),
                execute: symbol!(
                    "encap_transcription_execute",
                    unsafe extern "C" fn(u64, *const u8, usize, Option<Event>, *mut c_void) -> u64
                ),
                size: symbol!(
                    "encap_transcription_result_size",
                    unsafe extern "C" fn(u64) -> usize
                ),
                copy: symbol!(
                    "encap_transcription_result_copy",
                    unsafe extern "C" fn(u64, *mut u8, usize) -> i32
                ),
            })
        }
    }
    struct Owned<'a>(&'a Library, u64);
    impl Drop for Owned<'_> {
        fn drop(&mut self) {
            unsafe { (self.0.release)(self.1) };
        }
    }

    unsafe extern "C" fn progress(context: *mut c_void, bytes: *const u8, length: usize) {
        // Copy borrowed callback buffers before forwarding. Invalid callback
        // spans are rejected; no panic may unwind across the foreign boundary.
        let _ = std::panic::catch_unwind(|| {
            if bytes.is_null() || length > 1024 * 1024 {
                return;
            }
            let owned = unsafe { std::slice::from_raw_parts(bytes, length) }.to_vec();
            if let Ok(event) = serde_json::from_slice::<Value>(&owned) {
                if event["event"] == "progress" {
                    let handler = if context.is_null() {
                        None
                    } else {
                        unsafe { &*context.cast::<Option<ProgressHandler>>() }.as_ref()
                    };
                    encap_core::deliver_progress(event, handler);
                }
            }
        });
    }
    pub(crate) fn invoke(
        path: &Path,
        arguments: &[OsString],
        cancellation: &CancellationToken,
    ) -> Result<Vec<u8>> {
        if cancellation.is_cancelled() {
            return Err(message("AVID Core operation was cancelled safely."));
        }
        let arguments: Vec<_> = arguments
            .iter()
            .map(|s| {
                s.to_str()
                    .ok_or_else(|| message("Transcription arguments must be valid UTF-8."))
            })
            .collect::<Result<_>>()?;
        let request =
            serde_json::to_vec(&serde_json::json!({"schema_version":1,"arguments":arguments}))?;
        if request.len() > 4 * 1024 * 1024 {
            return Err(message("Transcription operation request exceeds 4 MiB; project data must remain in operation-local files."));
        }
        static LIBRARY: OnceLock<std::result::Result<Library, String>> = OnceLock::new();
        let library = LIBRARY
            .get_or_init(|| Library::load(path))
            .as_ref()
            .map_err(|e| message(e.clone()))?;
        let token = Owned(library, unsafe { (library.create)() });
        if token.1 == 0 {
            return Err(message(
                "Could not allocate linked transcription operation token.",
            ));
        }
        let done = AtomicBool::new(false);
        let progress_handler = encap_core::current_progress_handler();
        let progress_context = (&progress_handler as *const Option<ProgressHandler>)
            .cast_mut()
            .cast();
        let result = std::thread::scope(|scope| {
            let token_id = token.1;
            let finished = &done;
            scope.spawn(move || {
                while !finished.load(Ordering::Acquire) {
                    if cancellation.is_cancelled() {
                        unsafe { (library.cancel)(token_id) };
                        break;
                    }
                    std::thread::park_timeout(Duration::from_millis(30));
                }
            });
            let result = unsafe {
                (library.execute)(
                    token_id,
                    request.as_ptr(),
                    request.len(),
                    Some(progress),
                    progress_context,
                )
            };
            done.store(true, Ordering::Release);
            result
        });
        let result = Owned(library, result);
        if result.1 == 0 {
            return Err(message(
                "Linked transcription returned an invalid result handle.",
            ));
        }
        let size = unsafe { (library.size)(result.1) };
        if size == 0 || size as u64 > MAX_RESPONSE_BYTES {
            return Err(message(
                "Linked transcription result size is invalid or exceeds 512 MiB.",
            ));
        }
        let mut bytes = vec![0; size];
        if unsafe { (library.copy)(result.1, bytes.as_mut_ptr(), bytes.len()) } != 1 {
            return Err(message("Could not copy linked transcription result."));
        }
        let mut envelope: Value = serde_json::from_slice(&bytes)?;
        if envelope["schema_version"] != 1 {
            return Err(message("Unsupported linked transcription result schema."));
        }
        if envelope["ok"] != true {
            return Err(message(format!(
                "{}: {}",
                envelope["error"]["code"]
                    .as_str()
                    .unwrap_or("transcription"),
                envelope["error"]["detail"]
                    .as_str()
                    .unwrap_or("Unknown linked transcription failure.")
            )));
        }
        if cancellation.is_cancelled() {
            return Err(message(
                "AVID Core operation was cancelled safely after awaited cleanup.",
            ));
        }
        serde_json::to_vec(&envelope["result"].take()).map_err(Into::into)
    }
}
#[cfg(target_os = "macos")]
pub(super) use apple::invoke;
