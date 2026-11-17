# Linked AVID Core transcription in EnCAP

EnCAP pins immutable Core `v0.4.0`, commit
`dd112d497b68df6786f49a71b3611f7f32f090e9`. The separate Swift source export contains
38 unmodified files; its deterministic archive SHA-256 is
`76f517ddfcf14067ac52c0f84b61b4f3bb7dd11917df30de94385dc0d15428a3`.
`vendor/AVID_CORE_TRANSCRIPTION_SOURCE_MANIFEST.json` and
`script/verify_avid_snapshot.rb` authenticate the export, while the adapter's
`Package.resolved` retains the actual SDK revisions. No build needs an adjacent
Core repository. Historical verification reports remain historical evidence.

## Application boundary and deployment

`encap-transcript` retains EnCAP's project projection and reconciliation. It
calls the optional Apple `libEnCAPTranscription.dylib` through ABI/schema 1, or
Core's public portable Rust APIs. The `helpers/avid_transcriber` directory now
contains a reusable dynamic-library target plus an optional diagnostic CLI using
the same service. Production has no `avid-transcriber` process transport.
The old subprocess adapter is compiled only in tests to preserve historical
failure/reconciliation fixtures; it is not a production fallback.

Apple catalog, installation/resume, verified import/removal, inference and
alignment remain in the unmodified `AVIDTranscription` and
`AVIDTranscriptionEngines` Swift libraries. The optional module is loaded only on
Apple silicon/macOS 14+, from `Contents/Frameworks/EnCAPTranscription.framework`, with its
SwiftPM catalog, SDK and Metal bundles. The macOS 13 base application and Intel
media/project support do not gain a launch dependency on it. A debug-only
`ENCAP_AVID_TRANSCRIPTION_LIBRARY` override names one explicit absolute developer
library; it establishes no production artifact provenance.

The optional portable SDK feature is `encap-transcript/portable-whisper`.
It uses Core's actual `ModelStore`, verified leases and `recognize_audio`; no
second PCM decoder or inference engine was added. Build with the exact target
FFmpeg and patched Whisper SDK receipts. The currently tested macOS Whisper SDK
has a macOS 14 deployment minimum: enabling that combined feature in the macOS 13
base artifact is unsupported. Default application builds omit it. Windows/Linux
build recipes may select it deliberately after provisioning target SDKs and
native qualification; source portability alone is not target qualification.

## Capability and verification matrix

| Target / provider | Implemented application path | Current EnCAP verification / limitation |
| --- | --- | --- |
| macOS ARM64/macOS 14+, full Whisper large-v3 | Optional linked WhisperKit module; quality default | Adapter builds and contract/provenance tests pass; no new full-model inference run |
| macOS ARM64/macOS 14+, Whisper Turbo | Same module, explicit Turbo selection | Adapter build/contracts; no new actual Turbo inference |
| macOS ARM64/macOS 14+, Parakeet | Same module, explicit verified installed model | Direct-library actual offline inference/lifecycle diagnostic recorded in task evidence; no universal provider/device qualification |
| macOS ARM64/macOS 14+, Qwen recognition/alignment | Same module; corrected-text alignment is separate | Direct-library actual recognition and corrected-text alignment each pass two runs, loading cancellation and awaited cleanup; corrected text and original recognition provenance preserved |
| macOS ARM64, portable Tiny English CPU | Opt-in linked Rust feature; explicit `whisper-cpp-tiny-en` | Actual pinned-model test passes repeated recognition, real word captions, identity, pre-cancel and managed removal; development evidence only |
| macOS 13/Intel default base | Saved project/transcript editing and portable text contracts | Optional Apple inference unavailable; portable combined SDK deployment/native qualification unresolved |
| Windows/Linux x64/ARM64 | Portable text contracts; optional Tiny source adapter | Native inference and final artifact qualification unrun; Apple catalog and portable forced alignment unavailable |

Tiny English is additional and English-only. Full Whisper remains the default;
no absent provider silently selects Tiny or a cloud service. Its model metadata
has `is_default:false`, `download_allowed:false` and `inference_compiled`.
It imports only Core's exact pinned 77,704,715-byte GGML file, SHA-256
`921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`, after deliberate
user selection. It has no downloader, resume API, forced aligner, Parakeet or
Qwen implementation. Its private EnCAP cache is separate from historical GGML
files and all Apple/third-party stores. Explicit import copies and verifies the
source; removal affects only that managed cache. No old cache is auto-adopted.

## Records, editing and subtitle contracts

Both Apple recognition and alignment construct Core's installed-model request
APIs within `withInstalledModel`, retaining leases through backend unload.
The adapter persists the complete verified model/tokenizer identity and runtime
pins rather than attaching today's catalog hash to historical recognition.
`avid_source_id`, segment `avid_core`, original recognition, later alignment,
`previous_transcript`, speaker-review warnings and unknown compatibility data
remain EnCAP project records. Source times are projected into the assembled
episode exactly once. Trims, offsets, removal/reordering, stable IDs and surviving
history remain covered by Rust projection/reconciliation tests. Ambiguous legacy
sources do not receive guessed mappings or invented word timing.

Ordinary segment SRT/WebVTT exports use Core `export_captions` with one explicit
cue per valid saved segment and current speaker labels. Grouped word captions use
Core `caption_cues` and require actual current word timing. Both operations are
linked and available without an inference SDK, model or Apple module on every
base target. Core owns ordering, positive duration, escaping/newline and timestamp
validation. TXT remains EnCAP's speaker-aware projection. Export does not mutate
saved text or manufacture timings; no animation or burned-in captions were added.

## Lifetime, testing and unresolved qualification

Before loading Swift, Rust checks the bounded original source/ABI/platform receipt, complete resource inventory and hashes, including the required Core catalog and MLX metallib. Missing/corrupt resources return an error before SwiftPM can evaluate its fatal resource accessor. Packaging records normalized dylib code identities; after signing, the binder verifies unchanged code and binds the new raw dylib/signature bytes to the original receipt. Runtime verification launches no integrity helper.

Every inference invocation owns a token and retained request/resources until
blocking execution returns. Swift provider progress first enters a copied queue;
the synchronous C entry point drains callbacks on its calling worker, so UI
callbacks never borrow provider-owned buffers. Cancellation signals the Swift
task and waits for provider cleanup. No library thread is killed and no hard
process-style timeout is promised. The dynamic module remains loaded until
process exit; the application drains jobs before quitting or updating.

`script/build_avid_transcriber.sh` stages the linked module/resources/SDK licenses
and checksummed source receipt. Its relocation probe directly loads the staged
library with an empty PATH and lists the catalog without acquiring models.
`script/qualify_transcription.py --application ...` uses the native application's
linked-operation diagnostics; `--engine` remains an optional diagnostic client.
Catalog smoke is separate from actual inference and final signed-package smoke.
Standard distribution still requires complete functional/artifact qualification
and the repository's signing/notarization policy. The overall linked migration
remains incomplete while required upstream Audio/playback contracts are missing.

Task diagnostics are retained outside the repository at
`/private/tmp/encap-linked-20261116-dc1e968`: Swift adapter tests, source verifier,
Python staging/notarization checks, native Tiny model test and direct-library
Apple runs identify their actual inputs. Upstream Core qualification is supporting
evidence; it never qualifies an EnCAP target or a later source/artifact by itself.

The packaged optional module uses a standard versioned framework with catalog/Metal resources and notices in its Resources directory. The compatibility runtime is copied from the selected Xcode toolchain and referenced directly relative to the framework executable; developer runpaths are removed. Original and signed raw-hash receipts live in outer application Resources/EnCAPTranscription and are sealed by the enclosing app. Runtime source Git identity is not exposed by the installed toolchain; exact vendor/compiler/binary/notice identities are recorded and missing corresponding Swift runtime sources remain a distribution limitation.
