# AVID Core ownership audit

This corrective audit was prepared on 2026-11-10 against task-start EnCAP HEAD
`eae227e5e76a825d52540dd418cbe7844a1fac21` and its pre-existing working edits.
The originally requested pre-integration `docs/avid-core-audit.md` was absent.
This report records the current implementation; it does not claim the historical
Phase 1 audit or its requested stop occurred. The current user has explicitly
requested independent Gemini verification followed by Codex repairs.

The available Core checkout is `v0.3.3`, immutable revision
`8e27a86ec106028d93130de35a35c0eeda7a9ce3`; EnCAP initially pins Rust Core
`v0.3.2` at `8296a9e623c6924c12e456b5fe9e7c10b59dfbde`. Core's README,
`docs/image-optimization.md`, `apple/README.md`, changelog and
`docs/integration.md` were inspected. The Rust crate and separate Swift packages
have different public/platform contracts. Ownership requested by the user is
broader than the public APIs currently supplied; those differences are recorded
as **Core gaps**, rather than being treated as completed removal.

Line references below identify the audited initial source. Later repairs may
move them; implementation verification belongs in the accompanying repair report.

| EnCAP location (file:line) | What it does | Matching AVID Core capability and API | Status | Action |
| --- | --- | --- | --- | --- |
| `Cargo.toml:25`; `Cargo.lock:92` | Pins immutable Rust Core source/version and resolves its codec dependencies. | Core `0.3.3` source release; all retained public APIs are compatible. | wrapper only (acceptable) | Update manifest and lock together to the immutable published new revision; keep the independently authenticated FFmpeg runtime pin separate. |
| `crates/encap-core/src/model.rs:27` | Re-exports shared Video settings/state; owns EnCAP project, chapters, episode metadata and compatibility extensions. | `VideoSettings`, `VideoProjectState`; Core does not own EnCAP archive schema. | wrapper only (acceptable) | Retain shared re-exports and project-specific records/migrations. Do not replace persistent EnCAP records with ephemeral inference types. |
| `crates/encap-core/src/source.rs:66` | Validates WAV/AIFF/AIFC container/sample layout and computes sample-accurate duration; creates ordered source/chapter records. | `Renderer::probe_audio_duration` overlaps duration inspection. No public Core sample-format/container-inspection API supplies the data needed by waveform/import validation. | partially duplicated | Record Core gap for structured sample/container information. Evaluate duration delegation at a runtime-aware application adapter; preserve current WAV/AIFF import contract until equivalent Core validation exists. |
| `crates/encap-core/src/waveform.rs:37` | Bounded native PCM reads for first-channel waveform thumbnails. | No public Core waveform/sample-window API. | partially duplicated | **Core gap**: retain existing parser/preview as an explicit outstanding exception; do not create a replacement parser. |
| `crates/encap-core/src/transcript.rs:45` | Plain-text transcript export with EnCAP speaker labels. | Core caption exporters do not provide EnCAP's plain-text project export. | EnCAP-only | Retain text projection; it contains no timing writer or caption grouping. |
| `crates/encap-core/src/transcript.rs:63`; `crates/encap-engine/src/main.rs:317` | Ordinary segment SRT formatting and millisecond timestamps. | Swift `CaptionCue`, `CaptionExporter.srt`; Core exporter is packaged only with the Apple-silicon/macOS 14+ helper. | duplicated | Delegate supported-host subtitle formatting through a thin cue adapter. Record portable-exporter **Core gap** for other supported EnCAP platforms; preserve saved-transcript export there explicitly. Do not silently fall back after a supported helper fails. Document Core's stricter cue validation/escaping before changing behavior. |
| `crates/encap-core/src/transcript_origin.rs:25`; `crates/encap-core/src/audio_editing.rs:14` | Preserves recognition/alignment provenance, maps source to episode clock, reconciles edits/removals and invalidates edited timing. | Swift `Transcript`, `TranscriptWord`, provenance records; EnCAP owns project edit history and source/chapter relations. | wrapper only (acceptable) | Retain conversion/migration and stable EnCAP IDs; Core remains authoritative for generated timing. No interpolated timing is acceptable. |
| `crates/encap-core/src/project.rs:128`; `crates/encap-core/src/project_save.rs:214`; `crates/encap-core/src/archive_copy.rs:16` | ZIP project save/open, incremental cache, extraction, safe archive copying and schema migration. | Core media/image staged publication is private; it does not own EnCAP ZIP archives or archive migration. | EnCAP-only | Retain archive-specific staging and cancellation callbacks. Integrity and source protection remain required. |
| `crates/encap-core/src/file_ops.rs:13`; `crates/encap-core/src/file_ops.rs:149` | Project/output atomic replacement and alias detection. | Core performs equivalent protection internally for its render/image operations; no public general host-file publication/alias API exists. | partially duplicated | **Core gap** for reusable generic output protection. Keep host project/recovery safety and existing non-Core export protection; delegate Core operations without duplicating their internal publication. |
| `crates/encap-core/src/error.rs:32` | Logs structured Core error code and maps errors to concise Video UI messages. | Core `Error`, `ProcessFailure`, `Error::code`. | wrapper only (acceptable) | Retain privacy-aware presentation adapter; provide artwork-specific wording when adding optimization rather than displaying Video errors for an image operation. |
| `crates/encap-core/build.rs:4` | Embeds resolved Core version/revision after checking lock/manifest agreement. | Immutable source integration contract. | wrapper only (acceptable) | Retain source identity binding; runtime recipe/source pins are separate identities. |
| `crates/encap-ffmpeg/src/lib.rs:23`; `crates/encap-ffmpeg/src/runtime.rs:209` | Resolves one installed authenticated pair; maps host layout and debug fixture overrides into Core validation. | `MediaTools::from_paths`, `MediaTools::from_core_directory`, `CoreRuntimeInfo`, `FFMPEG_RUNTIME_SPECIFICATION`. | wrapper only (acceptable) | Retain host-specific signed-layout mapping and call Core's pair validator; keep release PATH/environment fallback disabled. |
| `crates/encap-ffmpeg/src/runtime.rs:81` | Binds original runtime metadata to application-signed/post-sign executable hashes and application/Core identities. | Core verifies original runtime directories. Application signing changes binary bytes, and external authenticity remains a host responsibility. | wrapper only (acceptable) | Preserve authenticated acquisition, original and post-sign checks, complete metadata and one paired runtime. Do not delete security checks as generic hashing duplication. |
| `crates/encap-ffmpeg/src/lib.rs:47` | Owns cancellable FFmpeg child execution, diagnostics capture and process cleanup for audio export. | Core process runner is private; `Renderer` exposes image/video/duration operations, not arbitrary audio commands. | partially duplicated | **Core gap**: general audio export/process API. Keep this existing implementation visible until Core supplies the required operation; it cannot honestly be described as a thin type adapter. |
| `crates/encap-audio/src/lib.rs:14`; `crates/encap-audio/src/lib.rs:49` | Builds normalization/concat/MP3/AAC/artwork arguments, stages media and publishes an audio-only export. | No public Core audio-only export API. `Renderer::render` produces MP4 video and is not a behavior-equivalent substitute. | partially duplicated | **Core gap**: shared audio export. Retain existing behavior and flag unfinished ownership migration; do not create a new host implementation. |
| `crates/encap-audio/src/lib.rs:147` | Converts podcast/chapter metadata into FFmetadata records. | EnCAP episode/chapter product metadata stays host-owned; no public Core metadata DTO/export operation exists. | EnCAP-only | Retain metadata projection; future Core audio API should accept host metadata without owning project persistence. |
| `crates/encap-transcript/src/lib.rs:68`; `crates/encap-transcript/src/lib.rs:105`; `crates/encap-transcript/src/lib.rs:340` | Routes model operations, recognition and realignment to the Core helper; projects its records into EnCAP source/episode clocks. | Swift `ModelStore`, `withInstalledModel`, `WhisperKitProvider`, `FluidAudioProvider`, `QwenASRProvider`, `QwenAlignmentProvider`. | wrapper only (acceptable) | Retain thin JSON orchestration, EnCAP edit reconciliation and explicit unavailable states. Production Transcript does not build or run FFmpeg arguments. |
| `crates/encap-transcript/src/lib.rs:471` | Converts current timed words to the shared caption contract and requests grouped captions. | Swift `CaptionBuilder.cues`, `CaptionExporter.srt`, `CaptionExporter.webVTT`. | wrapper only (acceptable) | Retain Core grouping/export; WebVTT word-caption export already exists. Keep original-source timing and episode offsets explicit. |
| `crates/encap-transcript/src/lib.rs:737`; `runtime/transcription-platform-support.json:1` | Detects supported helper platform and reports absent/unavailable engine instead of selecting legacy backends. | Apple transcription engines require Apple silicon/macOS 14+; no equivalent Core backend on other targets. | wrapper only (acceptable) | Retain explicit availability. Existing saved project editing/export is separate from inference availability. |
| `crates/encap-transcript/src/lib.rs:813` | Owns the JSON sidecar child, forwards structured progress, bounds responses, propagates cancellation and awaits cleanup. | Core Swift task cancellation and typed model/inference progress; Core does not own the EnCAP JSON process boundary. | wrapper only (acceptable) | Retain boundary lifecycle adapter; do not mistake helper process spawning for a second inference implementation. |
| `crates/encap-video/src/lib.rs:90`; `crates/encap-video/src/lib.rs:162`; `crates/encap-video/src/lib.rs:321` | Maps selected EnCAP chapter/source/artwork records into Core requests and delegates previews/rendering. | `Clip`, `Timeline::new`, `RenderRequest`, `PreviewRequest`, `Renderer::render_with_mode`, `Renderer::preview`, `select_clip_indices`. | wrapper only (acceptable) | Retain source-reference mapping and protected project paths. Shared Core owns filters, layouts, blur, flips, encoder choice, presets and media publication. |
| `crates/encap-video/src/lib.rs:254`; `crates/encap-video/src/artwork.rs:11` | Chooses Simple/PerFrame for host memory policy using conservative static-artwork sniffing. | Core exposes `RenderMode` choices and privately detects animated image containers, but no public automatic-classification/planning API. | partially duplicated | Record **Core gap** for reusable animation/static classification or automatic render policy. Keep the current bounded host scheduling policy explicit; no new decoder should be added. |
| `crates/encap-video/src/lifecycle.rs:62` | Serializes host operations/destinations and observes shutdown/cancellation while waiting. | Core per-operation `CancellationToken`; Core does not own a global host job registry or cross-call writer serialization. | wrapper only (acceptable) | Retain host scheduling; it uses the shared token and does not recreate process cancellation. |
| `crates/encap-video/src/lib.rs:412`; `crates/encap-video/src/lib.rs:428` | Forwards shared stages/progress/diagnostics and requires Complete before reporting publication. | `EventSink`, `Progress`, `Stage`. | wrapper only (acceptable) | Retain boundary conversion. Do not report fraction 1 as success before the operation returns. |
| `crates/encap-engine/src/main.rs:198`; `crates/encap-engine/src/main.rs:503` | Defines one-JSON-response CLI, converts project payloads, installs signal handling, saves recovery and transcript files. | Core token/error/progress for Core operations; no general Rust/Swift unified JSON protocol or host recovery publication API. | wrapper only (acceptable) | Retain product boundary and file publication. Add optimize-artwork command invoking Core directly; no FFmpeg dependency is needed for this operation. Document differing Rust/Swift progress contracts rather than claiming one shared type across languages. |
| `crates/encap-release/src/main.rs:2` | Compatibility launcher for shared authenticated update-release tooling. | No media-Core equivalent; release publication is application infrastructure. | EnCAP-only | Preserve command authorization and verified-artifact requirements. |
| `crates/encap-update/src/main.rs:1`; `updater/src/lib.rs:102`; `updater/src/client.rs:134` | Verifies signed update envelopes, allowlisted release URLs, versions, platform/assets and download hashes. | Core runtime integrity does not implement authenticated application updates. | EnCAP-only | Preserve update signatures, appcast rules and authenticated package handling. Do not remove these hashes as media duplication. |
| `crates/encap-portable-update/src/main.rs:35` | Extracts/validates Windows package, checks Authenticode and identity, coordinates replacement/rollback/relaunch. | No media-Core equivalent. | EnCAP-only | Preserve signer, archive integrity, runtime validation and user-file protection. |
| `macos/EnCap/Services/EngineClient.swift:73`; `macos/EnCap/Stores/AppStore.swift:589` | UI-to-engine requests, source/episode artwork choice, model interaction, user operation lifecycle. | Host-only UI/JSON boundary; artwork optimization should invoke Core via engine. | EnCAP-only | Add explicit opt-in Optimize Copy action. Keep originals and project references unchanged until successful Core output. Default metadata removal may affect EXIF orientation/ICC interpretation and needs UI explanation. |
| `macos/EnCap/Views/VideoCompositionPreview.swift:35` | Displays PNGs composed by the engine/Core and tracks preview identity. | `Renderer::preview`, existing JSON adapter. | wrapper only (acceptable) | Retain image display/cancellation. This is no longer a separate export-composition graph. |
| `macos/EnCap/Stores/AppStore.swift:846`; `macos/EnCap/Stores/AppStore.swift:924`; `macos/EnCap/Support/SourcePlayback.swift:104` | Native playback seek/next/previous and chapter/source presentation timing. | `Timeline::position` exists in Rust; Core intentionally does not own native playback devices/lifecycle. | EnCAP-only | Retain native player control and project selection display; authoritative export timeline construction remains in Core. Any future shared timing query must preserve UI state and JSON process boundaries. |
| `qt/src/engine_client.cpp:74`; `qt/src/main_window.cpp:902` | Qt engine JSON requests, caption/export dialogs, model state and supported/unavailable presentation. | Host UI adapter over existing engine/Core operations. | EnCAP-only | Retain UI. Add opt-in artwork optimization through engine and keep existing explicit unavailable inference state. |
| `qt/src/main_window.cpp:1771` | Starts the validated bundled FFmpeg to convert unsupported native-preview media into PCM. | No public Core generic PCM decoding/preview-stream API; native playback itself is host-owned. | partially duplicated | **Core gap**: shared PCM decode. Keep this direct process as a specifically listed exception, not evidence that all FFmpeg invocation has been removed. |
| `qt/src/main_window.cpp:807`; `qt/src/main_window.cpp:1951` | Maps playback position to source and selected chapter display. | Core `Timeline::position` for Rust video timelines; native presentation/product state is host-owned. | EnCAP-only | Retain presentation mapping; export requests must continue to use shared authoritative timeline selection. |
| `desktop/native/playback.c:1`; `desktop/native/media_linux.c:1`; `desktop/native/media_windows.cpp:1` | Native audio device playback, miniaudio integration, MPRIS/SMTC transport controls. | No Core device/native media-control API; Core explicitly excludes native playback. | EnCAP-only | Retain device integration and required third-party license/security fixes. Do not confuse native playback decoding with an alternative export pipeline. |
| `helpers/avid_transcriber/Sources/AVIDTranscriber/Command.swift:48`; `helpers/avid_transcriber/Sources/AVIDTranscriber/Command.swift:125` | Adapts model/install/recognition/alignment/caption commands to Core Swift SDKs and emits typed JSON. | `ModelCatalog`, `ModelStore`, provider protocols, `CaptionBuilder`, `CaptionExporter`. | wrapper only (acceptable) | Retain adapter, progress conversion and cleanup. Add segment-cue export without regrouping words when repairing ordinary supported-host SRT. |
| `helpers/apple_aac_info.swift:1` | Queries system AudioToolbox encoder manufacturers for UI/build diagnostics. | Core reports FFmpeg encoder advertisements; no matching native manufacturer-query API. | EnCAP-only | Retain diagnostic helper; it is not the removed Apple Speech transcription backend. |
| `vendor/README.md:1`; `vendor/AVID_CORE_TRANSCRIPTION_SOURCE_MANIFEST.json:1`; `vendor/avid-core-transcription/apple/AVIDTranscription/Sources/AVIDTranscription/ModelStore.swift:1` | Ships an immutable, unmodified Core Swift source export including upstream model transport/cache/inference/caption implementation. | Canonical Core Swift packages; source vendoring is the documented SwiftPM subdirectory integration route. | wrapper only (acceptable) | Keep source/archive/manifest/provenance synchronized and verify every file; never repair shared implementation inside vendor. Do not count upstream-owned vendored source as EnCAP duplicate implementation. |
| `runtime/core-runtime.json:1`; `runtime/platform-runtimes.json:1`; `runtime/core-acquirer.json:1` | Pins authenticated provider runtime artifacts, acquisition implementation and target provenance. | Core-owned source-built matched FFmpeg package and provider contract. | wrapper only (acceptable) | Retain immutable provider pins and authenticity checks. No application FFmpeg source builder or second Video runtime is present. |
| `script/core_runtime.py:228`; `script/platform_runtime.py:166`; `script/ffmpeg_runtime.py:95` | Acquires/verifies published Core runtime and stages app-specific layout; checks attestations/manifests/original hashes. | Core provider packaging contract; hosts verify external authenticity and installation. | wrapper only (acceptable) | Retain external trust and signed-layout checks. These downloads are Core runtime acquisition, not a new media build or model downloader. |
| `script/prepare_ffmpeg.sh:1`; `script/ffmpeg/stage.sh:1`; `script/ffmpeg/qualify.sh:1` | Compatibility entrypoint, paired runtime staging and application-specific qualification fixtures. | Published Core runtime; Core validation APIs plus host media acceptance. | wrapper only (acceptable) | Keep one pair; test the exact staged/signed pair. Qualification and fixture commands may invoke FFmpeg directly as test evidence. |
| `script/build_and_run.sh:101`; `script/build_qt.py:46`; `script/package_appimage.sh:23` | Builds application and stages the Core runtime plus host dependencies. | Core owns media runtime build/packaging; host owns final app bundle/Qt/AppImage packaging. | wrapper only (acceptable) | Preserve one staged ffmpeg/ffprobe pair, required metadata/dependencies, target-specific verification and explicit development vs distributable paths. |
| `script/build_avid_transcriber.sh:1`; `script/stage_avid_transcriber.py:46`; `script/verify_avid_snapshot.rb:1` | Builds host sidecar against pinned Core source; stages Metal/catalog/notices and verifies source snapshot. | Core Swift packages/SDK dependencies; host process packaging. | wrapper only (acceptable) | Preserve pinned snapshot, Metal/catalog resources and license staging; model weights remain separately user-acquired through Core. |
| `script/qualify_transcription.py:38`; `script/test_ffmpeg_runtime.py:1`; `crates/encap-engine/tests/media_contract.rs:427` | Executes fixture/runtime/helper qualification and records not-run/unavailable honestly. | Host acceptance of shared Core APIs/runtime. | EnCAP-only | Retain diagnostic tests; do not count ignored tests or earlier artifacts as current successful verification. Direct fixture tool calls are acceptable test exceptions. |
| `script/sign_macos_release.sh:1`; `script/publish_verified_artifacts.py:1`; `script/sign_sparkle_feeds.py:1` | Developer ID signing/notarization, authenticated update feeds and verified-artifact publication. | No media-Core equivalent. | EnCAP-only | Preserve owner permissions, notarization Accepted/staple/Gatekeeper evidence and authenticated feeds. No publication or signing run is authorized merely by this audit. |
| `THIRD_PARTY_NOTICES.md:7`; `THIRD_PARTY_NOTICES.md:29`; `runtime/AVIDCoreImageLicenses/README.md:1` | Attributes Core runtime, Rust/Swift source, codecs, model/SDK and host playback dependencies. | Core license and image-codec notices; distinct SDK/model licenses. | wrapper only (acceptable) | Update Rust revision/version when pin changes; retain complete redistributed license texts. Remove obsolete dependency claims only after confirming no shipped component still requires them. ImageOptim is not a dependency. |

## Core gaps and completion limits

1. **Audio-only export and generic PCM decode.** The current public Rust Core API
   supplies video rendering, previews, image inspection and audio duration, but no
   audio-only MP3/AAC export or generic PCM decode request. Its process runner is
   private. Existing `encap-audio`, its runner, and Qt fallback decoder cannot be
   removed without changing Core or removing behavior. This task forbids changes
   to Core and forbids replacing the gap with a new host implementation.
2. **Structured audio/sample and waveform APIs.** Core does not expose EnCAP's
   validated WAV/AIFF sample layout or bounded waveform previews. Duration alone
   has a public overlap; those format/preview contracts do not.
3. **Portable subtitle exporter.** Core caption code is currently in a Swift
   package using Apple platform modules; EnCAP's shipped helper additionally
   requires Apple silicon/macOS 14. Saved SRT export on Intel Mac/macOS 13,
   Windows and Linux has no equivalent packaged Core exporter. A retained legacy
   writer must be disclosed, never characterized as complete deduplication.
4. **Generic host safe publication.** Core's media/image staging is internal,
   while EnCAP must safely publish project ZIPs, recovery data and text exports.
   No public generic equivalent exists. Those host safety checks remain.
5. **Automatic image/render policy.** Core exposes explicit render modes but no
   public animation/static classifier or host aggregate-memory scheduler. Current
   conservative host selection overlaps private image inspection and remains
   explicit pending an upstream API.
6. **Unified progress/diagnostic wire contract.** Rust Core uses `EventSink`,
   `Progress`, `Stage` and structured `Error`; Swift Core has model/inference
   progress and Swift errors. The EnCAP JSON sidecar boundary necessarily adapts
   both. No universal Core cross-language JSON protocol should be invented.

Transcription production code already delegates original-media decoding, model
download/resume/cache/checksum/lease handling, recognition, forced alignment and
word-caption grouping/export to Core. The FFmpeg PCM conversion in
`media_contract.rs` is a fixture operation, not a remaining production Transcript
implementation. Vendored Core Swift source is upstream-owned, verified code,
not a fork or second EnCAP implementation.

## Grep evidence to retain with final verification

Run these source searches after repairs and interpret the hits using the table;
an empty-result claim would be false while the Core gaps remain:

```sh
rg -n 'Command::new|encap_ffmpeg::run|export_arguments|ffmpeg|ffprobe' crates/encap-audio/src crates/encap-ffmpeg/src crates/encap-transcript/src qt/src
rg -n 'render_srt|write_time|CaptionBuilder|CaptionExporter|ModelStore|install-model|HTTPModelDownloadTransport' crates helpers vendor/avid-core-transcription/apple
rg -n 'optimize_image|ImageOptimizationRequest|ImageOptim' crates macos qt helpers THIRD_PARTY_NOTICES.md
```

Acceptable exceptions: Core SDK source under `vendor/`; JSON/helper process
adapters; fixture-generation and qualification tests; authenticated Core runtime
acquisition and app signing/update integrity; EnCAP project ZIP/recovery writes;
native device playback and platform transport controls. Outstanding **Core gap**
exceptions are audio-only processing/PCM decode, sample/waveform parsing,
portable legacy SRT, and conservative staticness/automatic render scheduling.

This audit does not certify full ownership migration. Final reporting must list
the repairs actually made, each remaining Core gap and the tests actually run,
including failed, skipped and unavailable checks. CI policy and archived workflow
bytes must remain unchanged by the repair task.

## Corrective implementation status

The table above records the initial reviewed source, before these Codex repairs.
The following current-source entries supersede its proposed actions where stated.
They describe implementation inspection; the final verification report records
the checks actually executed and the final source identity.

| Current EnCAP location (file:line) | What it does | Matching AVID Core capability and API | Status | Action |
| --- | --- | --- | --- | --- |
| `Cargo.toml:25`; `Cargo.lock:92` | Pins Rust Core `0.3.3` at immutable revision `8e27a86ec106028d93130de35a35c0eeda7a9ce3`. | Published Core source release with compatible public APIs. | wrapper only (acceptable) | Updated together. The separately authenticated FFmpeg runtime and independently pinned, unmodified Swift `0.3.2` source export retain their own identities. |
| `crates/encap-engine/src/artwork.rs:9`; `crates/encap-engine/src/main.rs:304` | Maps project/payload protection and JSON results to lossless same-format image optimization. | `optimize_image`, `ImageOptimizationRequest`, `ImageOptimizationOptions::default`, `CancellationToken`. | wrapper only (acceptable) | Added direct Core delegation, without FFmpeg or an application image codec. Core owns metadata stripping, codec work, alias checks and staged publication. |
| `macos/EnCap/Stores/AppStore.swift:601`; `qt/src/main_window.cpp:804` | Offers explicit episode-artwork Optimize Copy actions and adopts the successful output path. | Existing engine JSON boundary to Core image optimization. | EnCAP-only | Added opt-in UI in both clients; source images remain unchanged. Save dialogs/tooltips disclose metadata removal, including orientation/color interpretation. Chapter artwork can be passed to the engine command; a separate chapter optimization button was not added. |
| `crates/encap-transcript/src/lib.rs:473`; `helpers/avid_transcriber/Sources/AVIDTranscriber/Command.swift:173` | Projects saved segment bounds, text and speakers into one Core cue per segment. | Swift `CaptionCue`, `CaptionExporter.srt`, `CaptionExporter.webVTT`. | wrapper only (acceptable) | Added the `subtitles` helper command. It performs no word regrouping and needs no model installation. A supported-host helper error propagates; it does not select the legacy writer. |
| `crates/encap-engine/src/main.rs:334`; `crates/encap-engine/src/main.rs:339` | Routes ordinary SRT and newly accepted `export-transcript ... vtt` through the segment adapter. | Core SRT/WebVTT export. | wrapper only (acceptable) | Added the small ordinary WebVTT CLI change. Existing word-caption WebVTT UI remains; ordinary segment WebVTT UI was not added. Core escaping/newline folding and ordered, positive-duration cue requirements are intentional documented export differences. |
| `crates/encap-transcript/src/lib.rs:505`; `crates/encap-core/src/transcript.rs:63` | Preserves existing saved SRT export on platforms where the packaged Core helper is unavailable. | No packaged portable Core subtitle exporter for Intel Mac, macOS 13, Windows or Linux. | partially duplicated | Retained as an explicit **Core gap**. WebVTT reports unavailable there rather than creating a second writer. This is platform selection, never recovery from a failing supported helper. |
| `docs/architecture.md:27`; `docs/video-mode.md:63`; `README.md:37`; `THIRD_PARTY_NOTICES.md:33` | Documents actual Core delegation, remaining gaps, new opt-in behavior and immutable Rust identity. | Core integration/ownership and codec/license contracts. | wrapper only (acceptable) | Updated. Audio-only processing, sample/waveform parsing, portable legacy SRT and automatic staticness policy remain disclosed rather than being called completed migration. |

## Assessment of the Gemini findings

The requested Antigravity invocation selected profile `gemini`, CLI model ID
`gemini-3.8-flash-high`, and disabled provider fallback. Its original full-tree
source SHA-256 was
`f870cf7cf5766ee1e7a84248993d7660af80b07303156bd1aee5d9d83ec500bc`.
The provider returned six findings and explicitly reported **partial** coverage.
The runner rejected the report because its missing-file finding named
`docs/avid-core-audit.md`, a path absent from the captured source. Consequently
`result.json` records `completed: false`, `status: incomplete`; this is **not an
accepted completed Gemini audit**. The raw provider response remains evidence for
assessment and must not be discarded. No independently reported backend model
identity was exposed beyond the recorded CLI selection.

| Original Gemini finding | Codex assessment | Corrective disposition |
| --- | --- | --- |
| Missing capability-audit deliverable, `docs/avid-core-audit.md:1` | Substantiated: the required file did not exist in the reviewed source. The runner's absent-path validation failure does not invalidate this factual observation. | Added this file, including every requested crate/directory, API/status/action mapping, Core gaps and grep exceptions. The historical pre-edit Phase 1 stop is not retroactively claimed. |
| Core dependency remains `0.3.2`, `Cargo.toml:25` | Substantiated against the supplied updated `0.3.3` checkout. The external reviewer did not inspect that sibling checkout; Codex verified the public source revision/API locally. | Updated Cargo manifest and lock to immutable Rust `0.3.3` revision `8e27a86ec106028d93130de35a35c0eeda7a9ce3`. |
| Audio manually constructs/executes FFmpeg, `crates/encap-audio/src/lib.rs:44` | Substantiated remaining ownership duplication, but an immediately available Core audio-export replacement was not substantiated. Core's public renderer produces video; its generic process runner is private. | Retained existing audio export and runner as an explicit unresolved **Core gap**. No new audio implementation and no Core edits were made. Full deduplication remains incomplete. |
| Duplicate SRT writer, `crates/encap-core/src/transcript.rs:63` | Substantiated. Core's available exporter can own supported-host segment formatting, but cannot currently replace existing saved SRT export on every EnCAP platform. | Added supported-host `CaptionCue`/`CaptionExporter` delegation and ordinary VTT CLI export. Retained the legacy writer only through the disclosed unsupported-platform adapter; supported helper failures do not fall back. |
| PNG/JPEG parsing duplicates inspection, `crates/encap-video/src/artwork.rs:11` | The parser and overlap with Core's private image handling are real. A behavior-equivalent public replacement was not substantiated: `Renderer::inspect_image` returns dimensions, not animation/staticness. Removing this check or forcing Simple mode could freeze animation; forcing PerFrame everywhere would discard the existing bounded static-render policy. | Retained existing conservative parser/automatic scheduling as an explicit **Core gap** pending a public classifier/planner. No arbitrary replacement or new parser was introduced. |
| Architecture incorrectly declares media work host-owned, `docs/architecture.md:27` | Substantiated: the previous ownership language obscured unfinished migration and available shared capabilities. Project archives/metadata remain legitimate EnCAP product responsibilities. | Rewrote architecture and related docs to distinguish implemented Core delegation from missing public APIs and product-owned persistence. |

Codex additionally identified and repaired absent artwork optimization, using the
already available Core codec API. That repair was not a seventh Gemini finding
and is not represented as externally reviewed code. The original Gemini snapshot
predates all repairs above; a final source hash and later Codex verification must
be reported separately.

## Current grep assessment and explicit exceptions

The source searches above were rerun during repair inspection. They do **not**
show complete removal of direct FFmpeg or caption-writer code. Current meaningful
hits are:

- `encap-audio/src/lib.rs:44` and `:49`, plus
  `encap-ffmpeg/src/lib.rs:74`: existing audio argument construction/process
  execution, retained for the audio-export **Core gap**.
- `qt/src/main_window.cpp:1800`: bundled FFmpeg fallback PCM decoding for native
  playback, retained for the generic decode **Core gap**. Normal UI process calls
  otherwise invoke the engine or authenticated updater boundary.
- `encap-ffmpeg/src/runtime.rs:231`: Core pair validation after host authenticated
  signed-layout resolution. Filename, manifest, hash and source-pin hits in that
  adapter and acquisition scripts preserve provenance; they are not independent
  media processing implementations.
- `encap-transcript/src/lib.rs:855` and `:935`: OS capability check and the owned
  JSON helper process. Production Transcript has no FFmpeg argument construction
  or subprocess invocation. Model download hits outside `vendor/` are calls to
  the shared `ModelStore`, command names, or JSON/UI projection.
- `encap-transcript/src/lib.rs:510` and `encap-core/src/transcript.rs:63`: the
  specifically documented legacy SRT platform gap. Supported-host segment SRT/VTT
  and word captions call Core exporters; no host WebVTT writer was added.
- `encap-engine/src/artwork.rs:31`: direct `avid_core::optimize_image` delegation.
  There is no EnCAP JPEG/PNG compression or metadata-removal implementation and
  no ImageOptim application dependency.
- Vendored Core `ModelStore`, `HTTPModelDownloadTransport`, providers and
  `CaptionExporter`: verified upstream-owned source, deliberately retained
  unmodified. Test fixtures, archived evidence and qualification scripts may
  invoke tools or contain writer expectations without defining production media
  ownership.

The remaining sample-format/waveform parser and static-artwork classifier are
also explicit Core gaps even when a particular subprocess-oriented grep does not
match them. Safe host ZIP/recovery/text publication, native device playback,
signed application/runtime acquisition, update signatures and appcast checks
remain legitimate host responsibilities and were not removed to obtain a clean
grep result.


## Final independent review and later Codex correction

The same task/baseline/state was retried after the concrete repairs above. The
second invocation returned an accepted complete Antigravity audit with no findings
and all seven clean-copy checks passing. Its full-tree source SHA-256 is
`a888446df283e53929ec0d18770f24eaebed7e33b8c7717861608c5dc281cb41`.
Requested profile `gemini` and recorded CLI selection `gemini-3.8-flash-high`
agree; fallback was explicitly disabled. The provider exposed no independent
backend model identity. This later accepted snapshot covers the artwork and
subtitle repairs; it does not erase the first incomplete attempt or its findings.

The review could not inspect the external Core sibling, execute interactive GUI
flows, qualify untested target platforms, run new model inference or submit
signing/notarization. Native fixture and development-build checks were performed
separately by Codex. The remaining Core gaps above are still unresolved; an
accepted code audit does not mean complete ownership deduplication or a qualified
distributable. One completed report was added, conservatively reaching six
completed reports across the five known related historical reports and this one.

A read-only Codex second pass found a later UI issue: an artwork save panel could
be accepted after another window opened a project sharing the same image path.
After the frozen audit finished, the SwiftUI and Qt actions were bound to a
captured project snapshot before starting and before adopting results. Those
small later guards and this final documentation are outside the audited hash;
Codex verifies them separately. No additional external audit is claimed. The
final full source identity and actual verification results are reported with the
task evidence.


## 2.0.11 release follow-through

The owner subsequently requested a version bump, local notarized build, annotated
release tag and remote source commit. Version 2.0.11 retains the implementation
review baseline/task/history above. Codex corrected a release-path defect: nested
Developer ID signing changed hashes after transcription qualification. The signer
now refreshes the qualification report before sealing the app. Eight mocked
notarization regressions, actual final-byte report validation, offline recognition,
six final-package media tests and native launch passed. Apple accepted submission
`142a42fa-f072-4362-9b74-4cc785b79ca0`; final ZIP signature, staple and Gatekeeper
checks passed. This later signer fix is Codex-verified; the six-report external
review allowance is exhausted and no additional Gemini audit is claimed. See
[the release evidence](verification/encap-2.0.11-macos-arm64.json).
