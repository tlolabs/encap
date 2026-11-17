# Linked EnCAP application interface

`encap-app` owns the reusable project and workflow operations formerly held in
`encap-engine/src/main.rs`. The diagnostic CLI dispatches to the same Rust
services. Swift/AppKit and Qt Widgets remain responsible for native devices,
playback controls, dialogs, permissions, lifecycle, and UI dispatch.

The C entry points are declared in `include/encap_app.h`; Swift can import the
`EncapApp` module map in that directory. Build the target-specific `encap-app`
`cdylib` against the pinned, verified linked Core SDK. A library being present is
not proof of a qualified final application package.

## ABI and transport

Check both `encap_app_abi_version()` and `encap_app_schema_version()` before any
operation; both are 1. Create an application handle with `encap_app_create()` or
`encap_app_create_json()` and one cancellation handle per operation. The optional
configuration is `{"schema_version":1,"recovery_path":"/local/recovery.json"}`.
Configuration is per handle; hosts do not change process environment variables.

Execute on a host worker. A request is operation-specific application JSON, not a
Core media request and not a serialized project:

```json
{"schema_version":1,"operation":"save","payload":"/temporary/project.json","project":"/exports/project.encap"}
```

Application requests are limited to 64 KiB. Project payloads remain separate
local files, read through a bounded 8 MiB reader matching the archive manifest
limit. An entire project or transcript is never squeezed through Core's 4 MiB
media request boundary. The response is
`{schema_version:1,ok:true,result:...}` or
`{schema_version:1,ok:false,error:{code,detail,...}}`. Native errors retain Core's
code, library, operation, native code/kind and nested hardware/software domains;
raw diagnostic strings stay in local tracing. A zero result handle is an ABI
failure. Result buffers have a separate 64 MiB maximum; oversized results fail
explicitly without truncation.

Query buffer length, validate the bound, allocate, copy the complete UTF-8 bytes,
and release the result. A short/invalid copy returns zero. Handles are opaque,
owned, type checked integers. Release each exactly once. An in-flight call holds
its references even when the caller releases a handle; release neither cancels
nor joins that operation.

Callbacks borrow bytes until return on the worker thread. Copy before queued UI
dispatch and retain the callback context until execution returns. Stage events
and successful completion events do not invent progress percentages. Callbacks
may cancel/release handles but must return promptly and never wait for the
current operation. Cancellation is cooperative: request cancellation, then await
return and cleanup. Never terminate a worker or unload the library while calls
remain active. Drain all operations before application replacement or shutdown.

All operations publish through their existing shared services. A process-wide
output lease rejects concurrent writers to the same destination, including
existing hardlink/symlink aliases. Every lease is released on normal return or
Rust unwinding. This is not an interprocess filesystem lock.

## Typed operations

Fields use snake_case and operation names use kebab-case. Optional fields may be
omitted; `render_mode` defaults to `automatic`, and `word_timestamps` to false.
Unknown fields and invalid typed values fail. Local paths must be nonempty and
contain neither a NUL nor a URI scheme. The CLI retains its existing argument
syntax, response JSON, and exit behavior through the same operation enum.

| Operations | Fields |
| --- | --- |
| `build-info`, `startup`, `video-presets`, `video-capabilities` | none |
| `inspect`, `inspect-files`, `waveform` | `folder`; `files` array; `file` respectively |
| `open` | `project`, optional `extraction_parent` |
| `save`, `edit-audio` | `payload` and `project` destination; `payload` and `edits` file respectively |
| `export`, `export-video`, `preview-video` | `payload`, `output`; video export optional `render_mode` (`automatic`, `simple`, `per-frame`); preview optional `chapter_id` |
| `inspect-artwork`, `optimize-artwork` | `image`; or `payload`, `image`, `output` |
| `export-transcript`, `export-captions` | `payload`, `output`, `format` (`txt`/`srt`/`vtt` for transcript, `srt`/`vtt` for captions) |
| `transcribe` | `payload`, `provider`, optional `word_timestamps`, `language`, `alignment_model` |
| `realign` | `payload`, `model`, optional `language` |
| `providers`, `models`, `transcription-status` | none |
| `install-model`, `remove-model`, `verify-model`, `import-model` | `model`; import additionally `source` |
| `save-recovery`, `load-recovery`, `clear-recovery` | save: `payload`; others: none |
| `validate-compatibility-tools` | none; authenticates the retained executable pair for unfinished Audio/PCM compatibility paths |
| `validate-tools` | none; linked video capabilities, no executable validation |
| `validate-core-runtime` | `directory`; explicit obsolete-runtime error |

## Completion limits

Extracting an application facade does not replace missing Core media APIs. Audio
export and Qt playback need the upstream chaptered audio/PCM contracts described
in the migration handoff. Any retained compatibility subprocess path is an
unfinished migration path, not a qualified linked replacement. Existing native
sample/waveform parsing is a documented compatibility exception. The deployment,
provider and artifact matrix remains authoritative for available functionality.

The application executables expose `--linked-operation <operation> <arguments>`
for screen-free final-package qualification. This diagnostic mode calls the same
linked facade on a worker and emits the legacy raw result or `{error:message}`
on standard output, with a nonzero status on failure. It does not create the UI,
load an external engine executable, or implement a second media path.
