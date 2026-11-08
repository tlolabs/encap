# EnCAP AVID transcription bridge

This sidecar adapts the vendored, reviewed AVID Core Swift libraries to EnCAP's
owned-process boundary. It contains no model catalog, downloader, recognizer,
alignment implementation, or caption grouping implementation of its own.
Production engine support is Apple silicon and macOS 14 or later; the base app
has its own deployment target. This package does not establish support for other
targets.

Build with Swift 6.3 or later, Xcode, and the installed Metal toolchain. Use
`script/build_avid_transcriber.sh` to stage the executable **and** its SwiftPM
resource bundles/Metal library. An executable copied without resources is not a
complete helper installation. `Package.resolved` retains the reviewed dependency
pins; the local packages come from `vendor/avid-core-transcription/apple`, not a
mutable sibling checkout.

## Protocol version 1

The executable is `avid-transcriber`. Each invocation emits exactly one JSON
value on stdout. Success exits zero. Failure exits nonzero with
`{"error":"plain-language explanation"}`. Error 130 represents cancellation.
Library diagnostics and newline-delimited progress JSON use stderr. SDK stdout
is redirected to stderr internally so it cannot corrupt the protocol. A progress
record has `event:"progress"`, `stage`, optional `fraction`, `model_id`,
`artifact_path`, `completed_bytes`, and `total_bytes`.

All commands accept optional `--cache DIRECTORY`. Otherwise
`ENCAP_AVID_MODEL_CACHE` overrides the shared default
`~/Library/Application Support/AVID/Transcription/Models`. The default remains
shared across AVID hosts. These options do not import legacy GGML weights.

| Command | Arguments | JSON result |
| --- | --- | --- |
| `status` | none | Protocol version, default model ID, platform, and cache path |
| `models` | none | All shared catalog models, including the separate aligner |
| `providers` | none | Present recognition model choices; verification occurs before inference |
| `install-model` | `--model ID` | Model metadata after shared verified installation |
| `verify-model` | `--model ID` | Model metadata after offline verification |
| `import-model` | `--model ID --source DIRECTORY` | Metadata after exact verified copy into the shared cache |
| `remove-model` | `--model ID` | Metadata after removal of shared managed revisions/partials |
| `transcribe` | `--input AUDIO [--model ID] [--language CODE] [--alignment-model ID] [--source-offset SECONDS]` | Source-clock transcript |
| `realign` | `--input AUDIO --transcript JSON [--model ALIGNER_ID] [--language CODE] [--source-offset SECONDS]` | Corrected text with separate alignment provenance |
| `captions` | `--transcript JSON --format srt\|vtt` | JSON string containing shared grouped captions |

`transcribe` defaults to the shared quality model, full Whisper large-v3.
`realign` defaults to the shared Qwen forced aligner. Inference and alignment
require already installed, locally verified models. They never install a missing
model implicitly. Installation is a separate explicit operation. Recognition and
alignment language lists are validated separately; locale hints are normalized to
base language codes before validation.

Model metadata retains EnCAP's existing `id`, `name`, `download_size`,
`languages`, `description`, `installed`, and `download_allowed` fields. Additional
fields expose `download_size_bytes`, `role`, `engine`, `recognition_languages`,
`timing_languages`, `license`, `installation_id`, `repository`, `revision`,
`installation_state`, and `is_default`. `installed` is a cheap presence check,
not an integrity assertion. `installation_state` distinguishes `missing`,
`present_unverified`, and a freshly `verified` mutation/verification result.

Transcript objects use explicit snake_case keys: `segments`, `language`,
`provenance`, and optional `alignment_provenance`. Each provenance has
`engine_id`/`model_id`, plus `model_installation_id` (the full-manifest identity
used by Core's model store) and `source_bundle_sha256` for newly produced records.
Realignment preserves the original recognition identity while recording the new
alignment identity. The shared source hash in `TranscriptWire.swift` must be
updated together with a deliberate vendor-snapshot update. Segments have `text`, `words`, and optional
`start_seconds`/`end_seconds`; words add optional `confidence`/`timing_method`.
`timing_method` retains AVID's enum values (`recognizer`, `forcedAlignment`,
`manual`, `estimated`). Missing boundaries remain absent. The adapter never
invents word timing and never adds EnCAP episode offsets. Rust owns the
reversible source-to-episode projection. A nonzero `--source-offset` is for an
extracted input clip and is applied by Core exactly once; realignment inputs
already contain their source-clock offset.
When recognition and alignment are requested together, `recognition_segments`
also preserves the original recognition segments/words before alignment. The
normal `segments` array contains the aligned view. Rust retains the original
recognition record separately from later alignment and episode projections.

The caption command applies the shared default grouping options to the provided
clock without modifying the recognition record. EnCAP must pass its explicitly
projected episode view when episode captions are wanted. Missing word timing is
an error. SRT/WebVTT export provides timed subtitle cues; animated or burned-in
captions require a separate host renderer.

SIGINT and SIGTERM cancel the operation's Swift task and await provider cleanup.
An owned-parent monitor also cancels if the Rust parent exits or crashes.
The shared model lease spans verification, loading, inference, and unload;
concurrent removal fails while leased. A currently executing Core ML or Metal
kernel may finish before cancellation is observed. The owning host must drain
both pipes and wait for its child; a forced process termination cannot report
graceful task cleanup. No other process is targeted by this helper.

Model removal only calls Core's managed-store removal. It does not delete manual
import source folders, legacy EnCAP GGML files, or third-party model caches.
