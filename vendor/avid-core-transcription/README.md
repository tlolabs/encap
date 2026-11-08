# AVID Core

`avid-core` is the canonical Rust implementation of the artwork-and-audio video feature used by ATIV and EnCAP Video. **Everything in ATIV's feature engine is the baseline**: presets, image/audio inspection, composition, previews, flips, validation, MP4 rendering, progress/ETA, cancellation, tool discovery, diagnostics, and safe publication. EnCAP adds chapter sequences and codec/encoding choices without narrowing that baseline.

AVID Core owns the pinned FFmpeg source build and produces a matched `ffmpeg` and
`ffprobe` runtime for TLO Labs applications. ATIV and EnCAP should load the
Core-built pair through `MediaTools::from_core_directory`, rather than select,
download, build, or bundle independent media binaries. Core publishes each verified
platform independently; ATIV and EnCAP select a published runtime and own their
integration tests and application releases. Core does not approve downstream
applications. See [the provider contract](docs/ffmpeg/provider-contract.md) and
[signing policy](CODE_SIGNING_POLICY.md).

A TLO Labs open-source project maintained by Thomas Lothian. AVID Core releases
source code and a Rust crate; it does not require portable Windows application ZIPs.

Start with [the integration contract](docs/integration.md), then follow
[ATIV migration](docs/handoff-ativ.md) or [EnCAP migration](docs/handoff-encap.md).
The original [extraction report](docs/report.md) and [inventory](docs/inventory.md)
remain useful implementation history.

Project policies: [privacy](PRIVACY.md), [security](SECURITY.md),
[support](SUPPORT.md), [contributing](CONTRIBUTING.md),
[code of conduct](CODE_OF_CONDUCT.md), [code signing policy](CODE_SIGNING_POLICY.md),
[third-party notices](THIRD_PARTY_NOTICES.md), and [changelog](CHANGELOG.md).
For development, see [architecture](docs/ARCHITECTURE.md),
[building](docs/BUILDING.md), [dependencies](docs/DEPENDENCIES.md),
[testing](docs/TESTING.md), and [releasing](docs/RELEASING.md).
CI checks are diagnostic and nonblocking for development; release artifacts remain subject to functional and integrity verification.
Tagged source releases are on [GitHub Releases](https://github.com/tlolabs/avid-core/releases).

## Architecture

```text
ATIV native UI -> ativ-engine + thin host adapter ----+
                                                     +-> avid-core -> Core FFmpeg/FFprobe runtime
EnCAP native UI -> encap-engine + Video adapter ------+
```

The library has no UI framework, global mutable state, runtime dependency on either application, FFmpeg bindings, shell commands, network client, or async runtime. Private modules implement the media process runner, filter/command construction, probing, validation, and staging. Public types describe the known feature and the specific choices needed by these two hosts.

| Public API | Responsibility |
|---|---|
| `MediaTools::from_paths` | Host-supplied executable paths and matching version identity validation |
| `MediaTools::from_core_directory` | Verify and open one complete Core source-built runtime without fallback |
| `MediaTools::core_runtime` | Pinned source, recipe, target, Core revision and both binary hashes |
| `ToolDiscovery`, `MediaTools::discover` | Optional development discovery; production hosts resolve their own layout |
| `Renderer`, `OperationOptions`, `RenderMode` | Cancellable probe, image inspection, capability query, preview and export |
| `optimize_image`, `ImageOptimizationRequest`, `ImageOptimizationOptions` | Shared source-built JPEG/PNG optimization without FFmpeg |
| `ImageOptimizationResult`, `OptimizedImageFormat` | Published format, byte counts and whether optimization reduced size |
| `RenderSettings`, `Composition`, `Codec`, `Encoding` | Execution settings, defaulting to ATIV software H.264 and fitted artwork |
| `RenderRequest`, `Input::Single` | Artwork plus original audio; no normalization/concat imposed |
| `Clip`, `Timeline`, `Input::Timeline` | Ordered hard-cut sequence with normalized stereo/48 kHz audio |
| `select_clip_indices` | Ordered ID selection before a host resolves chapter-to-source relationships |
| `Timeline::position` | Shared cumulative timing and exact-boundary lookup for playback adapters |
| `PreviewRequest` | PNG artwork composition using the same graph as export |
| `Preset`, `PRESETS` | All 27 existing presets, in original order, with a 30 fps field |
| `VideoSettings`, `VideoProjectState` | Existing feature-specific JSON state, defaults, extensions, reserved compositions |
| `CancellationToken`, `EventSink`, `Progress`, `Stage` | Per-operation cancellation and worker-thread events |
| `Error`, `ProcessFailure` | Structured diagnostics with stable category codes |

The crate does **not** own windows, menus, native playback/devices, theme preferences, dialogs, drag/drop, app lifecycle, CLI/JSON protocols, rotating logs, bundle signing, EnCAP ZIP archives, podcast metadata, audio export, transcript processing, model downloads, autosave, or project schema migration. `preview_quality` is retained as data; it does not alter offline FFmpeg rendering, matching current behavior.

## Reproducible dependency

Core uses semantic versioning independently of application and FFmpeg versions.
This checkout prepares source version `0.3.2`, including shared image optimization
and the runtime bug fixes. Until that release is published, use an immutable
source revision containing these changes. After publication, both hosts can pin:

```toml
[workspace.dependencies]
avid-core = { git = "https://github.com/tlolabs/avid-core.git", tag = "v0.3.2", version = "=0.3.2" }
```

Members use `avid-core.workspace = true`. Commit the host's `Cargo.lock` and build
with `--locked`. For the strongest immutable pin, replace `tag` with `rev` set to
the full commit from `git rev-parse 'v0.3.2^{commit}'` after publication. Never use
a moving branch as a release dependency. A sibling `path` dependency is optional local development
only; no Core API or build script requires that layout. See [versioning and migration](docs/integration.md).

```rust,no_run
use avid_core::*;
# fn main() -> Result<()> {
let cancel = CancellationToken::default();
let tools = MediaTools::from_core_directory(std::path::Path::new("/installed/core/runtime"), &cancel)?;
let renderer = Renderer::new(tools);
let request = RenderRequest {
    input: Input::Single { image: "cover.png".into(), audio: "track.wav".into() },
    output: "video.mp4".into(),
    settings: RenderSettings::default(),
    protected_paths: Vec::new(),
};
renderer.render(&request, &cancel, &())?;
# Ok(())
# }
```

Development examples (use conventional discovery/PATH):

```sh
cargo run --example standalone -- cover.png track.wav video.mp4
cargo run --example sequence -- cover.png first.wav second.wav sequence.mp4
```

## Simple still-image export

Call `renderer.render_with_mode(&request, RenderMode::Simple, &cancel, &events)` to composite the first artwork frame once per clip and reuse the composed YUV frame at the requested frame rate. Fitted/square-padded artwork, flips and blurred backgrounds keep their existing appearance. Artwork and blur do not animate. Timelines retain hard cuts and their existing audio normalization. The cache holds one output frame per clip (about 3 MiB at 1080p or 12 MiB at 4K, excluding decoder/encoder buffers), so long timelines need proportionally more frame memory.

The implementation trims the source before composition, then loops the completed frame in FFmpeg memory. It creates no intermediate PNG and avoids an RGB/YUV round trip. Requires the FFmpeg `trim`, `loop`, and `setpts` filters. Known-duration single exports explicitly stop at the probed audio duration to prevent an encoder-buffered silent video tail; unknown durations still use `-shortest`. Compositing happens within the Encoding process, so stage callback intervals do not isolate compositing CPU time.

`render()` and `RenderMode::PerFrame` preserve the original path. No fields were added to `RenderSettings` or persisted `VideoSettings`; existing host callers stay source compatible. Both modes use the same validation, staged publication, cancellation, progress and encoder fallback. ATIV's experiment branch selects Simple by default and retains `--render-mode current` for comparison. See [the benchmark and verification notes](docs/simple-export.md).

## JPEG and PNG optimization

ATIV and EnCAP can call `optimize_image(&request, &cancel)` on a worker thread to
create smaller `.jpg`/`.jpeg` and `.png` files through one shared implementation.
Core pins TurboJPEG to `=1.5.1` and OxiPNG to `=9.1.5`; Cargo builds their locked
native components from source. A target C compiler and CMake are required; the
selected scalar libjpeg-turbo build needs no NASM or downloaded tools.
The ImageOptim macOS application is not a runtime dependency.
This software is based in part on the work of the Independent JPEG Group.

Defaults follow the supplied ImageOptim preferences: lossless compression,
metadata removal, Extra effort, and Zopfli enabled. JPEG's quality
setting defaults to 80 and applies only when the caller opts into lossy encoding.
Transparent PNGs are rejected for album artwork; fully opaque alpha channels are
accepted. Outputs never exceed input size, and fallback preserves the requested
metadata-removal policy. Original inputs are protected; outputs use staged
publication at a separate path. Static
images only: APNG and CMYK JPEG are rejected. See the
[image optimization contract](docs/image-optimization.md) for the API, limits,
cancellation behavior, licensing and host integration steps. This API is an
addition in source version `0.3.2`; hosts need a source revision containing it.

## Threading, progress, cancellation, and errors

Operations block their calling worker thread, as the existing process-isolated engines do. Native UI code must continue calling its engine asynchronously; direct library hosts should use a dedicated worker or their runtime's blocking executor. Clone `CancellationToken` into the stop handler. `From<Arc<AtomicBool>>` supports ATIV's existing cancel flag. There is no detached job registry or signal handler in this crate.

Callbacks run on the operation's worker thread and must return promptly without panicking. They can forward events to a host channel. Progress reports media elapsed time, known duration, fraction and ETA from FFmpeg's speed. Unknown/nonfinite duration stays `None`; progress can be coalesced under load. Automatic hardware failure starts another Encoding stage and progress may restart. Only `Stage::Complete` means publication succeeded; an FFmpeg fraction of 1 does not mean the file is published. No host should assume cancellation after Complete can undo the output.

The runner checks cancellation before spawning, throughout probing/preview/encoding, after process exit, and immediately before publication. It drains stdout/stderr concurrently, kills and reaps its owned child on cancellation/timeout, and keeps staged output owned until success. Probe and capability processes default to 30-second timeouts; preview defaults to 120 seconds; renders have no time limit unless configured. Timeouts are per process/encoding attempt, not a whole-job deadline. There is no export pause/resume; native preview pause remains a host concern.

Errors distinguish invalid input, unavailable tools, I/O, process exit/spawn failures, timeout, capture overflow, cancellation and dual hardware/software failure. `ProcessFailure` retains executable, individual OS-string arguments, optional exit status, operation and the last 64 KiB of stderr; underlying I/O errors are retained when available. Probe stdout is limited to 4 MiB, and excess captured probe output fails explicitly. Progress stdout is drained with bounded capture. Hosts format/localize errors and keep technical diagnostics in local logs; `Display` is diagnostic text and can contain paths. The ATIV handoff explains mapping additional error categories into its existing JSON protocol.

## FFmpeg requirements and platforms

Hosts authenticate and install the matched Core runtime, then perform their
application signing and packaging checks.
`MediaTools::from_paths` accepts arbitrary executable names in independent locations,
requires no manifests, and never searches PATH or bundle directories. Both tools
must identify themselves and report matching version identifiers. This legacy
path API does not enforce the Core source pin and is not a production qualification
check. `from_paths_with_timeout` controls the per-tool version check timeout.
`Renderer::capabilities` reports advertised encoders; actual media operations and
native qualification determines runtime compatibility. The active build and
qualification process is documented in [docs/ffmpeg](docs/ffmpeg/README.md).

Single-track video needs `libx264`, AAC, MP4, image decoding, scale/crop/split/gblur/overlay/format filters. Sequences additionally use pad/trim/setpts/atrim/aformat/asetpts/concat; HEVC software requires `libx265`. No audio-intermediate encode, captions, crossfade, silence insertion, or explicit podcast/chapter metadata stream is added.

Tools are executed directly with stdin disabled; media inputs allow only `file,pipe` protocols and are passed as absolute OS paths, so spaces, Unicode, and leading dashes are not shell syntax. Explicit tool overrides are authoritative and invalid overrides fail; bundled searches cover adjacent, adjacent `ffmpeg/`, `Resources/`, and `Frameworks/` directories before PATH. The library does not read app-named environment variables. EnCAP must map its `ENCAP_FFMPEG` and `ENCAP_FFPROBE` settings in its adapter. ATIV forwards existing command-line overrides.

Automatic mode tries the first advertised hardware encoder in the original VideoToolbox/NVENC/QSV/AMF/VAAPI priority and retries in software after a process failure. Explicit hardware never silently falls back. Advertisement does not prove a usable device; no new GPU/device configuration is invented. ATIV must retain `Encoding::Software` to preserve its release policy.

Rust 1.85+ and edition 2021. The platform boundary preserves ATIV's macOS 12+, Windows 10 1809+ and current Linux requirements, and EnCAP's macOS 13+, Windows 10 1809+, and Linux requirements. No platform UI or shell dependency is introduced by the library. Native execution was verified on macOS; Windows/Linux cross-compilation and the CI matrix supplement, but do not replace, packaged runtime verification.

Output is staged in the destination directory under an exclusively created random `.avid-…` filename. Unix modes match ordinary file creation and respect umask. The completed file is flushed and published with tempfile's POSIX rename / Windows overwrite move. Failure before publication leaves existing output intact; partial output is cleaned up on normal failure/cancellation. Input identity checks use cross-platform file identity, including hard links. Pass unselected sources and project paths through `protected_paths` where appropriate. Hosts must serialize writers to the same destination. No power-loss durability or hostile concurrent-filesystem modification guarantee is made; force-killing the entire host process can leave a staging file.

## Compatibility

ATIV keeps fitted foreground + sigma40 blur, 1–240 fps, positive integer bitrate syntax with optional k/m/b, original audio layout/rate, H.264/AAC, yuv420p and faststart. Its output stays MP4 even if a caller supplies another suffix, as before; its UI should keep requesting `.mp4`. EnCAP keeps square-padded foreground + sigma20 blur, ordered chapter trims, normalized audio, MP4 suffix validation, hvc1 for HEVC, and 1–120 fps with the original bitrate presets through `VideoSettings::render_settings()`.

The `.encap` schema-2 ZIP, schema-1 migration, stored paths, compatibility payload and unknown project/audio/transcript fields remain in EnCAP. Shared video JSON preserves field names, defaults, `selection_initialized`, unknown flattened fields, `preview_quality`, and opaque `compositions`. `validate_schema()` rejects execution of unsupported video schema versions; callers must invoke it for persisted state before adapting settings. Deserialization itself preserves newer/unknown data so hosts can report incompatibility without discarding it. No new project format is introduced. Video selection does not reorder canonical Audio chapters; an empty initialized selection means none, while an empty uninitialized selection means all. Host archive loading retains its existing stale-ID cleanup behavior; the execution API rejects unresolved selections.

## Verification

```sh
cargo fmt --all -- --check
cargo check --locked --all-targets
cargo test --locked --all-targets --all-features
cargo test --locked --doc
cargo clippy --locked --all-targets -- -D warnings
cargo +1.85.0 check --locked --all-targets
cargo test --locked --test ffmpeg -- --ignored
```

Default tests do not need a built FFmpeg runtime or a sibling host checkout.
POSIX fake-process tests exercise external paths, version
validation, probing, capabilities, previews, rendering, cancellation and timeouts.
Platform-independent tests also run on Windows. The five opt-in real-media tests
accept `AVID_TEST_FFMPEG` and `AVID_TEST_FFPROBE` (set both) and verify streams,
timing, color order, codec tags and progress. Two opt-in installed-runtime lifecycle
tests accept `AVID_RUNTIME_DIRECTORY` containing a relocatable pair, with no metadata.
The native Core pipeline also runs the packaged-pair media test. See [verification instructions](docs/integration.md#verification) and the
[0.3.0 refactor report](docs/shared-library-refactor.md) for recorded results.

## Provenance

The implementation reconciles ATIV at `2c5eeed27e48d67fed128a62ff74dab6f00c2a82` and EnCAP at `a96978e5bb89189b944e5dd6a30e5ee7e8fe28d4`. Derived behavior and code locations are recorded in the inventory. EnCAP-origin video state and preset definitions retain their structure; process, timeline, renderer, and boundary APIs were reconciled here. Thomas Lothian grants the AVID Core version of this work under GPL-3.0-or-later; the source EnCAP repository retains its own GPL-3.0-only declaration. See [LICENSE](LICENSE), [provenance](docs/provenance.md), and the [licensing review](LICENSING_REVIEW.md). Copyright © Thomas Lothian.

## Apple local transcription

The separate [Apple transcription packages](apple/README.md) add desktop-first
WhisperKit, Parakeet, and MLX transcription, verified direct model downloads,
word-timed transcripts, and caption export. Model files come directly from public
upstream Hugging Face repositories; AVID does not host weights or audio inference.
These Swift packages do not change the Rust crate or its FFmpeg runtime contract.
