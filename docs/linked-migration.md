# EnCAP linked-library migration

This is an **unfinished, unqualified migration**, not a replacement release.
SwiftUI/AppKit and Qt Widgets now call the same EnCAP application library. Video,
image operations and supported transcription execute linked code. Chaptered Audio
export and Qt's unsupported-format PCM decoder still use the existing authenticated
executable runtime because Core exposes no behavior-equivalent public operation.
Removing those working features, or wrapping another private libav engine, would
not complete the migration. Do not publish this candidate as qualified.

## Source identity

Task `encap-linked-20261116-dc1e968` starts at EnCAP
`dc1e96879f434b8ec05d2965c4938fb7cd5f7cdf`. Original requirements, starting status,
pre-existing file hashes, command logs and review evidence are outside the checkout
in `/private/tmp/encap-linked-20261116-dc1e968`. The pre-existing `BUGFIX_REPORT.md`,
`docs/verification/transcription-avid-core.md`, its evidence directory and
`helpers/avid_transcriber/VERIFICATION.md` are preserved, not current qualification.
The sibling Core checkout contained unrelated working changes and was not consumed.

Remote and local `v0.4.0` resolve to immutable
`dd112d497b68df6786f49a71b3611f7f32f090e9`; there was no newer remote version tag
when checked. Rust Core uses `=0.4.0` and the portable transcription crate uses its actual `=0.1.0` package version at that revision.
`Cargo.lock` and the independent Swift source snapshot match that source. The
Swift archive SHA-256 is
`76f517ddfcf14067ac52c0f84b61b4f3bb7dd11917df30de94385dc0d15428a3`.
The manifest/verifier authenticate every vendored file; `Package.resolved` retains
Core's immutable provider dependencies. No reproducible build uses a sibling path
or a moving branch. Core's old executable handoff is historical only.

`runtime/linked-core.json` authenticates the new source/profile contract. Historical
`runtime/core-runtime.json` authenticates only the retained executable compatibility
pair. Neither receipt is substituted for the other. No linked binary release
asset was available to pin: linked candidates are built deliberately from the
immutable source and verified native SDK receipts, with exact binary hashes issued
per build. A development SDK bypass never establishes production provenance.

## Integration boundary and acceptance inventory

| Boundary / operation | Shared implementation and Core contract | Artifact / platform | Acceptance and unfinished work |
| --- | --- | --- | --- |
| `encap-core` project inspect/open/save/edit/recovery | EnCAP Rust project/episode/archive services, unchanged schema-2 model and schema-1 migration | EnCAP ABI1/schema1, portable media library | Unknown fields/history/IDs, hostile ZIPs, incremental/atomic save, source change detection, cancellation and preserved destination tests |
| `encap-app`, diagnostic `encap-engine` | One typed operation dispatcher; CLI calls the same services | `libencap_app` / `encap_app.dll`, no engine child required | Invalid handles/schema/fields, explicit result bounds, independent tokens, callback copies, writer exclusion, project payload above 4 MiB |
| macOS `EngineClient.swift` | Worker calls application ABI; typed host fields, opaque tokens/results | macOS 13 ARM64/Intel base; SwiftUI/AppKit retained | Native import/open/save/preview/cancel tests; shutdown drains workers and updater excludes library work |
| Qt `engine_client.cpp` | Worker calls the identical application ABI, queued copied events, joined teardown | Qt Widgets; supported DLL C boundary for MSVC hosts and GNU/gnullvm library | Contract, large responses, callback copies, cancellation, stale results, repeated/reentrant calls, UI project operations |
| `encap-video` capabilities/probe/preview/render | `Renderer::new`, typed `RenderRequest`/timeline/preview, compiled versus usable encoder state | Verified Core media SDK; Apple GPL or GPL software profile selected explicitly | Native ARM64 linked exports, decoded duration and PNG previews; a retained decoded Simple/PerFrame regression fails, see prerequisite handoff |
| New project defaults | `Renderer::default_settings`; persisted explicit settings are retained | Depends on actual linked profile | Profile supported defaults on new imports; no saved hardware/software setting rewrite |
| Image inspection/optimization, engine artwork adoption | Core `inspect_image` / `optimize_image`, original protected paths and separate staged output | Core native media + pinned JPEG/PNG dependencies | Alias/failure preservation, validation and optimization tests; adopt only on success |
| `encap-audio`, `encap-ffmpeg` | Existing Audio orchestration and authenticated executable transport remain unfinished | Original matched executable pair, independent signed-runtime checks | Existing MP3/AAC metadata/chapters/artwork and duration contracts retained; no linked equivalent exists and no linked Audio qualification claimed |
| Native WAV/AIFF/AIFC import and waveform | Existing bounded `encap-core` sample parsers retained as compatibility exceptions | No additional engine/parser introduced | Sample-accurate validation and waveform tests; public structured Core inspection/sample-window API needed |
| Qt direct FFmpeg PCM playback | Existing decoder child remains after explicit compatibility-runtime validation | Native miniaudio output, SMTC/MPRIS and controls remain host-owned | Generation guards, source/timeline seeking and cleanup retained; public Core PCM decoding prerequisite still blocks removal |
| `encap-transcript` Apple recognition/alignment/models | Isolated linked EnCAP Swift adapter calls Core installed-model request APIs | `EnCAPTranscription.framework/Versions/A/EnCAPTranscription`, macOS 14 ARM64, catalog/Metal/SwiftPM resources | Module/contracts/staging tests and per-provider actual inference recorded separately; no helper process transport |
| Portable Tiny English recognition | Optional `portable-whisper` feature, linked `avid-transcription`/Whisper SDK; explicit `whisper-cpp-tiny-en` selection and verified import | Separate exact patched native SDK/model receipt; default base build excludes it | Actual ARM64 Tiny recognition/cancel/repeat/model removal tests; no other target native qualification or full Whisper equivalence |
| Transcript editing and projection | EnCAP project adapters preserve source clocks, speakers, corrections, original recognition/history | All saved projects, independent of inference availability | Existing source removal/trim/reorder/reconciliation/timing invalidation tests retained |
| Segment SRT/WebVTT | Public portable Core `CaptionCue`/`CaptionExporter` contracts | No model or inference SDK needed | Positive valid segment bounds, escaping/newlines/order validation; does not fabricate word timings |
| Grouped word captions | Public Core `CaptionBuilder`, actual word clocks only | Same portable contracts | Untimed/corrected word timing rejected; TXT remains EnCAP's speaker-aware projection; no burn-in implied |
| Acquisition/build/package checks | `script/linked_runtime.py` exact source, SDK, profile, binary and corresponding-source receipts | Target-specific native candidates | Source/manifest tampering, dependency/loader/deployment checks; standard distribution also requires every requested mode to be qualified |

The application request maximum is 64 KiB. Requests contain operation-specific
paths/fields. An independently read project payload retains the existing **8 MiB**
limit; no project manifest goes through Core's **4 MiB** media JSON request limit.
A result is copied completely or rejected at **64 MiB**, never truncated. The
persistent model remains EnCAP's project format, not a transient Core request.
See [the application interface](linked-application-api.md).

The application ABI and schema are checked before execution. Callbacks borrow
bytes only for the callback; native clients copy before asynchronous dispatch.
Each job retains its request, payload file, callback context, token, handles and
libraries until return. Cancellation is cooperative and shutdown joins/drains;
there is no hard library-worker timeout. Swift and Qt retain successful library
loads for the process lifetime. Optional Apple dependencies are not loaded on
macOS 13 or Intel; an availability guard is supplemented by actual module/build
isolation. Updating/replacing application files is excluded during active work.

## Platform, mode and provider matrix

“Source support” or a cross-build does not qualify a native artifact. This matrix
is specific to EnCAP integration, not upstream Core's broader historical tests.

| Target | Project/edit/subtitle | Video/image | Audio / playback | Inference and alignment | Final package |
| --- | --- | --- | --- | --- | --- |
| macOS ARM64 | Rust + Swift + internal Qt native tests | Linked native evidence; decoded-mode regression remains open | Audio executable compatibility; AVFoundation host playback; Qt decoder gap | Optional Apple module, full Whisper large-v3 default retained, Turbo/Parakeet/Qwen catalog; optional explicit Tiny tested. Provider checks are recorded per test/model | Development only; no notarized replacement qualified |
| macOS Intel, macOS 13 base | Source/library deployment contract retained | Linked SDK target recipes supplied; no Intel native execution here | Audio compatibility, host playback | Apple module unavailable; combined portable SDK cannot silently raise base minimum | Not built/qualified natively |
| Windows x64 | Shared Rust + Qt source path | GNU C ABI DLL; Qt/updaters remain MSVC; exact target SDK required | Audio and direct PCM compatibility remain | Optional Tiny source adapter; Apple providers/portable forced alignment unavailable | Not built/qualified natively; unsigned direct-download policy unchanged |
| Windows ARM64 | Same shared model and Qt host | Distinct gnullvm DLL, never interchange MSVC static archives | Same unresolved paths | Same explicit optional Tiny restriction | Not built/qualified natively; existing toolchain prerequisites remain visible |
| Linux x64 | Same shared model and Qt host | Target-specific verified GPL linked SDK | Same unresolved paths; native MPRIS/output preserved | Optional Tiny; no portable downloader/aligner/Parakeet/Qwen | Not built/qualified natively |
| Linux ARM64 | Same contracts, distinct native artifact required | Distinct native ARM64 SDK | Same unresolved paths | Same provider limits | Not built/qualified natively |

No iOS or Android app was added. Interfaces remain suitable for future hosts.
Legacy GGML files/manual sources/third-party caches are neither removed nor
silently adopted. Model installation/import/verification/removal remains explicit.

## Reproducible development and packaging

A clean checkout fetches the pinned Git source, never the adjacent checkout:

```sh
python3 script/linked_runtime.py provision --target macos-arm64 --profile apple-gpl \
  --fetch --work /private/tmp/encap-linked-sdk-macos-arm64
python3 script/linked_runtime.py build --target macos-arm64 --profile apple-gpl \
  --prefix /private/tmp/encap-linked-sdk-macos-arm64/prefix \
  --target-dir "$PWD/target" --receipt "$PWD/build/linked-macos-arm64.json"
python3 script/linked_runtime.py bundle-sources --output /private/tmp/encap-cargo-sources.tar.gz --fetch
```

The optional Apple framework records its exact compatibility-runtime bytes and
installed Xcode compiler/notices. The toolchain does not expose the exact matching
runtime source revision; that corresponding-source limitation is disclosed and
does not become an invented upstream pin or a distribution qualification.

Source builds require the upstream target compiler/SDK prerequisites and pinned
CMake 3.31.6 for x265. An explicit `--prefix` override passes the same source,
recipe, target, profile, archive/hash and license checks. It is not PATH/system
FFmpeg discovery. Older SDK spec hashes are retained with their actual identity;
only the immutable upstream validator's selected-recipe equivalence is accepted.
Builds record the full feature graph and reject `legacy-subprocess`.

`script/build_and_run.sh` stages the linked library/receipts under Frameworks and resource metadata under Resources,
optional Apple inference in its isolated framework, and the still-required
Audio compatibility pair. `script/build_qt.py` stages corresponding DLL/SO records;
Qt calls the C ABI dynamically and requires no incompatible static import archive.
`verify-stage` checks metadata inventories, exact library bytes or a checked
post-sign binding, architecture, deployment minimum, ABI/schema and dependencies.
`bundle-sources` retains Cargo-locked source files/checksums; SDK, Core, EnCAP and
Rust target-runtime source/notices have separate identities. Signing may change
bytes only with unchanged normalized Mach-O code and a verified bound signature.

`EnCap --linked-operation build-info` and other diagnostic operations run the
same facade inside the native host, with no `encap-engine` child. The standalone
Rust CLI is optional diagnostic tooling. Final-package tests must use the native
host and its actual staged dependencies/resources with media executables absent
for migrated paths. Audio and Qt fallback playback cannot pass that condition yet.

Standard Mac distributions still require Developer ID credentials and an existing
notary profile before build, Apple Accepted status, stapling, extracted-app
signature verification and Gatekeeper acceptance. Known unfinished required modes
prevent this replacement from being labeled qualified. Explicit development/test
builds remain unnotarized. No signing credential enrollment or publication occurs.

The Sunday Windows/Linux x64/ARM64 schedule, one attempt per new immutable tag,
independent successful targets, no new event/manual triggers, inactive archive,
unsigned Windows download names/evidence and authenticated updater restrictions
are preserved. Weekly source/build/startup and final-package checks now include
the linked receipt; failed prerequisites or missing mode qualification remain
visible. No push, release, tag move, upload or publication was performed.

## Required upstream work and verification

[The Core prerequisite handoff](linked-core-prerequisites.md) specifies chaptered
Audio export, attached artwork/metadata, libmp3lame profiles, a supported public PCM
streaming/seek API, structured sample/window inspection, and the reproducing
Simple/PerFrame decoded-output fixture. Existing compatibility paths remain until
those contracts have behavior-equivalent implementations. A source-library version
bump alone does not satisfy them.

Current command outcomes, skips, native provider fixtures, package prerequisites,
review snapshot identities and post-review Codex fixes are recorded in
[the verification record](verification/linked-migration.md). No upstream test,
Cross compilation, contract mock or one successful ARM64 export qualifies another
target, provider or final package.
