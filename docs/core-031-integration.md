EnCAP's local integration with AVID Core 0.3.1 is implemented and built. Supported
native media paths pass on macOS ARM64. Two reproduced Core failures remain
visible below; this is not a claim that every artwork format or platform is
qualified. This report records the integration before the subsequent
[2.0.9 release](releases/2.0.9.md); nothing was committed, pushed, dispatched to
CI/CD, or published during the integration itself.

Work began on `main` at `c3939b7`, with 15 already modified tracked files and
five untracked entries. Those changes and user files were preserved. Changes
to shared files were additive to that work. No adjacent repository was modified.

The workspace now pins exactly:

```toml
avid-core = { git = "https://github.com/tlolabs/avid-core.git", rev = "15f28236142c100d0a83bf19154ed6f9f5b44e75", version = "=0.3.1" }
```

`Cargo.lock`, Cargo metadata, and `encap-engine build-info` resolve that identity.
Both debug and release workspace builds use Cargo's Git dependency cache without
an adjacent AVID Core checkout. The current resolved `src/renderer.rs`,
`src/command.rs`, `src/state.rs`, `src/storage.rs`, `docs/integration.md`,
`docs/simple-export.md`, and `docs/ffmpeg/provider-contract.md` informed the
integration. Older EnCAP/Core handoffs describe obsolete host-owned FFmpeg builds
and removed managed APIs; they do not override the provider contract.

`VideoRenderer` is a cloneable EnCAP adapter over Core's public `Renderer`.
Inspection, PNG composition preview, export, and explicit mode comparison use
Core operations. Clones retain Core's artwork/duration caches. Free functions
revalidate runtime discovery before reusing a matching process-local session;
there is no cross-process cache claim. Core's probe cache uses path, size and
modification time and is bounded internally; content changes preserving those
attributes are outside that fingerprint's guarantee.

Automatic export uses `render_with_mode(..., Simple, ...)` only when every
selected image is a confidently static PNG or JPEG and the estimated cached-frame
cost fits 256 MiB. Container contents determine staticness; extensions do not.
APNG, GIF, WebP, malformed/unknown containers and larger sequences retain
PerFrame for the entire render. The estimate is four bytes per output pixel per
clip, including repeated artwork, to conservatively account for Core's roughly
1.5-byte YUV420 frame plus overhead. This is not a total RSS bound. Simple
composes once per clip inside FFmpeg, without intermediate PNG files. Explicit
`--render-mode simple|per-frame` enables comparisons; Simple intentionally
freezes animation. No saved rendering-mode field or project schema was added.

`Input::Timeline`, canonical chapter-number/source mapping, selected order,
chapter image/main-artwork fallback, durations, and hard cuts remain delegated
through the existing adapter. Uninitialized empty selection means all; initialized
empty means none. Missing/duplicate IDs remain errors. Settings come from
`VideoSettings::render_settings()`: SquarePadded/sigma20, flips, H.264/HEVC with
`hvc1`, encoding policies, presets, 1–120 fps, and existing bitrate choices.
Core's timeline graph supplies stereo/48 kHz audio. Audio and Transcript export
graphs were not changed by this integration.

The engine adds `inspect-artwork <image>` and
`preview-video <payload> <output> [--chapter-id <id>]`. Both macOS and Qt clients
request Core-composed PNGs on their existing asynchronous engine mechanism;
native playback and transport controls remain. Preview identity excludes
playhead ticks, includes artwork file fingerprints and composition/project
identity, and rejects obsolete results. Qt separately tracks requested and
published previews, including failed/cancelled requests and empty selection.
Swift Task cancellation now terminates and joins its own engine process and
drains pipes before cleaning temporary preview resources.

Two application operation slots, shared through file locks across engine
processes, bound aggregate Core artwork probing to at most eight workers.
Destination locks serialize Video preview/export writers. Waits are independently
cancellable. Core retains ownership of child processes, probe workers, filter
graphs and atomic publication. The adapter forwards stages/progress/diagnostics
to the existing tracing path and requires both successful return and
`Stage::Complete`. Every job receives an independent cancellation token; the
engine signal handler reaches the token belonging to its operation. Native
clients join their work on shutdown. No runtime replacement flow was introduced.

Protected paths contain every audio source, main and chapter artwork, and the
project archive, including unselected media. The engine separately rejects
output aliases to its transient JSON payload. Failed/cancelled operations retain
existing destinations. Archives, schemas, unknown fields, compositions payloads,
saved settings, native source playback, save protocol and audio-edit protocol
retain their existing contracts.

The FFmpeg runtime pin is unchanged. Native tests reauthenticated
`platform-ffmpeg-9.0.1-r7-macos-arm64-run38185320964`, including immutable release
origin, GitHub attestation, assets, provenance, receipt, corresponding source and
extracted files. `validate-core-runtime` loads the original complete directory
through `MediaTools::from_core_directory`. Packaging preserves that preflight
and the signed-copy verification path needed for EnCAP's separated runtime
metadata layout. Manifest, attestation, signed-payload hashes, provenance and
production no-fallback discovery remain enforced. Packaging identity validation
now correctly treats library source and runtime build revisions as independent
immutable pins. No independent FFmpeg build, system-tool fallback, or checksum-only
authentication was added.

Local verification results on macOS ARM64:

| Check | Result and coverage |
| --- | --- |
| Formatting / workspace check | `cargo fmt --all -- --check`, `cargo check --workspace --locked --offline`: pass |
| Workspace builds | Debug and release `cargo build --workspace --locked --offline`: pass |
| Default workspace tests | 104 passed, 0 failed, 13 ignored; explicit writable temporary save cache, local loopback available |
| All-feature workspace tests | 104 passed, 0 failed, 13 ignored |
| Workspace lint | All targets/all features Clippy with `-D warnings`: pass |
| Video unit/injected-process tests | 15 passed; includes child-process locks, bounds, cache invalidation, cancellation, publication and settings |
| Engine artwork protocol | 1 passed; injected tools, exact JSON, mode controls and protected payload/archive/media |
| Project compatibility | 2 passed; archive schema migration, unknown fields/compositions, saved Video policy |
| Packaged release engine media | 7 passed; actual matched runtime, Audio MP3/AAC/AudioToolbox, real Whisper, Transcript, H.264/HEVC, ordering, artwork, cancellation, archive/recovery |
| Runtime packaging/rejection | Pass; actual relocated release engine, missing/damaged binaries/metadata/source, provenance substitution, poisoned overrides, usable PATH rejected |
| Python runtime contracts | 13 passed: 9 platform acquisition tests + 4 source/runtime identity tests; mocked remote responses |
| Swift native tests | 38 passed, no skips; includes production-client Core PNG dimensions/flip colors and injected cancellation/join |
| Native macOS app | Xcode Release build and launch passed; complete interactive loaded-project preview acceptance remains limited by computer-use service failure |
| Qt build / CTest | Build passed; 4/4 targets passed, including preview stale-generation/failure/deselection and shutdown tests |
| Qt real engine UI harness | Passed against the authenticated staged release engine; offscreen UI |
| New explicit native renderer tests | 2 passed, 2 failed for the reproduced Core defects below |

The 13 ordinary-suite ignores comprise seven native engine media tests, four new
native renderer tests, and two large save benchmarks. The seven media tests and
four renderer tests were executed separately as shown. The two optional large
save benchmarks were not run. Initial sandbox runs failed optional save-cache
tests because the home cache was unwritable and updater tests because loopback
binding was denied; reruns with a temporary cache and local test permissions
passed. Initial native runs lacked the speech-fixture environment and denied
AudioToolbox; the fully configured native and packaged reruns passed all seven.
An invalid new chapter fixture and a new Clippy initializer warning were corrected
before the passing final checks. No check was converted into a publication gate.

Five supported Simple/PerFrame comparison pairs (ten exports) used identical
inputs/settings and covered landscape/portrait output, asymmetric artwork,
horizontal/vertical/both flips, fractional chapter durations, repeated fallback
artwork, Unicode paths and H.264/HEVC. Decoded RGB mean absolute difference was
zero, decoded PCM was identical, and all 36 frame timestamps matched at 24 fps
over 1.5 seconds. Stereo/48 kHz and HEVC `hvc1` were verified. Existing engine
tests provide independent selection/order/artwork assertions; these comparisons
establish equivalence between modes.

A separate single-run six-clip 1280×720, 12-second, 30 fps software-H.264 comparison
measured PerFrame at 0.734 seconds and Simple at 0.278 seconds (about 2.64× faster).
Observed aggregate descendant peak RSS was 542,784 KiB and 494,512 KiB respectively.
RSS is sampled, with 25 ms sleeps plus query time, and excludes the sampler.
The comparison is diagnostic, not a general performance or memory guarantee.
Native lifecycle checks also cover changed image dimensions/preview, repeated
inspection, corrupt/40,000-pixel inputs, independent job tokens, protected paths,
and existing-output preservation. Timed cancellation checks do not establish
Core's exact internal stage or prove concurrent child overlap; deterministic
injected-process tests cover active cancellation and independent jobs separately.

Two unresolved Core limitations are tracked in the opt-in native tests and
[native evidence](verification/core-0.3.1-native.json):

- A mixed-aspect timeline at 180×320 fails in both modes because composed clips
  reach concat with sample aspect ratios `1:1` and `640:639`. Another portrait
  size (180×360) passes. Both failed attempts preserve the existing destination.
- A valid two-frame GIF probes successfully but automatic and explicit PerFrame
  export fail with `Option loop not found`. Automatic retains existing PerFrame
  semantics and does not silently freeze the animation to make the test pass.

These require Core changes outside this task's allowed repository scope. Animated
export support cannot be claimed from dimension inspection alone. Core's public
inspection returns dimensions, not frame count or an animation flag; preview is
a first-frame PNG. Core has no `optimize_image`, TurboJPEG, OxiPNG or standalone
image optimizer API. This integration makes no JPEG optimization, metadata
stripping or image privacy claim. Other OS/architecture native execution,
minimum-supported-OS testing, signing/notarization, update installation while
media workers are active, and release publication were not performed.

Implementation files changed by this task (pre-existing edits elsewhere remain
separate): `Cargo.toml`, `Cargo.lock`; `crates/encap-video/Cargo.toml`,
`crates/encap-video/src/{lib,artwork,lifecycle,tests}.rs`,
`crates/encap-video/tests/core031_native.rs`; `crates/encap-engine/src/main.rs`,
`crates/encap-engine/tests/artwork_protocol.rs`;
`crates/encap-core/tests/video_persistence.rs`; `script/ffmpeg_runtime.py`,
`script/test_runtime_ownership.py`; `qt/src/main_window.{cpp,h}`,
`qt/tests/performance_test.cpp`; `macos/EnCap/Services/EngineClient.swift`,
`macos/EnCap/Views/{VideoView,VideoCompositionPreview}.swift`,
`macos/EnCap.xcodeproj/project.pbxproj`, `macos/Tests/VideoPreviewTests.swift`;
this report, the current development/Video/runtime guides and the two
`docs/verification/core-0.3.1-*.json` records. Raw local logs and measurements are
under `target/core031`; aggregate Rust identity/counts are also saved in
[checks](verification/core-0.3.1-checks.json).
