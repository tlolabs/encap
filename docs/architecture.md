# Native application architecture

The linked migration is in progress. The application and project boundary is
linked, as are available Video, image and Transcript operations. Audio-only
export and Qt's fallback PCM decoder still need public Core replacements; they
remain working compatibility paths and prevent a complete migration claim.

```text
SwiftUI/AppKit (production macOS) ----> EnCAP application ABI1/schema1
Qt Widgets (Windows/Linux) ----------> libencap_app
  diagnostic encap-engine ----------> same reusable application services
  built-in --linked-operation ------> same reusable application services
                                       |-- encap-core: project/ZIP/edit/recovery
                                       |-- encap-audio: peer Audio workflow
                                       |     `-- existing subprocess export [Core gap]
                                       |-- encap-video: peer Video workflow
                                       |     `-- linked avid-core 0.4.0
                                       `-- encap-transcript: peer Transcript workflow
                                             |-- linked Core Rust subtitle contracts
                                             |-- optional portable tiny.en recognition
                                             `-- isolated linked Apple Swift module
                                                   `-- AVIDTranscription / Engines
Qt native audio output <--- native decoder + FFmpeg PCM compatibility [Core gap]
```

## Application and project boundary

`encap-app` contains reusable EnCAP operations extracted from `encap-engine`.
Both existing UIs translate their application commands into a narrow, versioned,
operation-specific request and invoke `libencap_app` directly on a host worker.
The diagnostic CLI and built-in `--linked-operation` modes call those same
services. No production UI needs an `encap-engine` child for project operations.
SwiftUI/AppKit and Qt Widgets remain the desktop presentation implementations;
this migration adds no mobile app or UI rewrite.

The [application interface](linked-application-api.md) defines owned opaque
handles, ABI/schema checks, bounded result copying, callbacks, per-operation
cancellation and per-application recovery storage. Requests are at most 64 KiB.
Project payload files are read separately with the existing 8 MiB manifest
limit; Core's 4 MiB media JSON limit never receives an entire project. Typed Rust
media adapters do not assume that EnCAP's application schema is Core's schema.

`encap-core` owns the persistent model, episode/chapter/source/transcript IDs,
compatibility extensions, schema migration, project ZIPs, incremental media
copying, atomic save, autosave and recovery. It rejects unsupported future
schemas and hostile archives. Core's transient media/inference requests do not
replace this model. The three mode crates are peers and do not depend on one
another. Source-clock projection, edit history and speaker reconciliation remain
EnCAP project responsibilities; generated timing and model provenance belong to
Core and are never synthesized for ambiguous legacy records.

A process-wide output lease rejects concurrent application writers to the same
destination, including existing filesystem aliases. Mode-specific protection,
same-directory staging and successful-publication-only replacement remain in
place. Projects and export destinations are not partially changed on failure.

## Linked media and explicit compatibility paths

The immutable Rust Core pin is `0.4.0` at
`dd112d497b68df6786f49a71b3611f7f32f090e9`. The separately vendored Swift packages
and manifest are refreshed from that same source snapshot. Reproducible builds
resolve immutable source and target-specific linked SDKs; they do not depend on
an adjacent Core checkout, developer PATH or arbitrary system FFmpeg libraries.
Production Core does not enable `legacy-subprocess`.

`encap-video` uses `Renderer::new()`, linked inspection/probing, previews,
timeline rendering, capabilities, composition and codecs. New projects use
`Renderer::default_settings()`; saved explicit encoder choices stay unchanged.
Compiled encoder support is distinct from usable device initialization. Original
source audio, independent Video ordering/selection, hard cuts, artwork fallback,
conservative static-image scheduling and the existing memory policy remain host
adapters. A public Core classifier/planner is still needed before removing that
compatibility sniffing. Core owns native contexts, filters and media publication.

`encap-app` delegates image optimization directly to Core with protected project,
payload and source paths. Clients adopt the separate optimized image only after
success. There is no EnCAP JPEG/PNG compression engine.

Core 0.4 does not provide complete chaptered MP3/AAC/M4A export with EnCAP's
metadata/artwork contract, libmp3lame profiles, or a supported high-level PCM
playback decoder. Existing `encap-audio` argument construction and
`encap-ffmpeg` transport, plus Qt's direct FFmpeg-to-PCM playback subprocess,
remain unfinished migration paths. They are not a final linked implementation
or a qualified replacement. No new raw libav/audio engine was introduced.
Existing bounded WAV/AIFF/AIFC sample validation and waveform parsers also remain
explicit compatibility exceptions until public equivalent Core APIs exist.

## Transcription and subtitles

`encap-transcript` uses linked APIs; `avid-transcriber` is retained only as a
diagnostic client of the same Swift services. An isolated higher-minimum Apple
inference library links the verified `AVIDTranscription` and
`AVIDTranscriptionEngines` sources, allowing the base macOS app to retain macOS13
and Intel media/project support. Availability checks happen before loading the
optional incompatible module; an availability guard around an eagerly linked
newer dependency would not be sufficient.

Apple provider selection keeps full Whisper large-v3 as the quality default,
Whisper Turbo, Parakeet, Qwen recognition and corrected-text Qwen alignment.
Installed-model requests preserve verified identity, tokenizer/runtime pins and
build provenance; leases last through backend unload. Model acquisition/removal
is explicit. Old EnCAP/manual/third-party model files are not silently adopted
or deleted. Actual provider/model/platform qualification remains separate from
catalog availability.

Portable Tiny English is an explicitly selected additional model behind the
`portable-whisper` build feature, disabled by default to preserve the base
application deployment minimum. It is not equivalent to the Apple catalog.
Portable alignment, Parakeet/Qwen and downloading remain unavailable. Saved
transcript editing and export do not depend on inference availability.

Ordinary SRT/WebVTT export passes valid segment bounds to Core's linked Rust
subtitle exporter. Grouped word captions use real timed words and Core grouping;
segment cues never receive invented timings. TXT remains EnCAP's speaker-aware
project projection. Export preserves saved text rather than editing a transcript
to satisfy an exporter, and adds no animated/burned-in captions.

## Threading, native ownership and deployment

Blocking linked work runs on native workers with independent operation tokens.
Callback buffers are borrowed only for a callback and copied before queued UI
dispatch. Shared scoped progress forwarding restores the enclosing handler after
nested calls; native Swift progress is drained on its blocking caller before
return. Superseded UI work is ignored using existing generation guards.
Cancellation requests cooperative cleanup and joins workers; no worker thread is
terminated and no hard process-style deadline is claimed. Shutdown, library
unload and authenticated application replacement must wait for active work.
Diagnostic SIGINT/SIGTERM requests follow the same cancellation-and-cleanup path.

Hosts retain native devices/output, playback controls/seeking, Windows SMTC,
Linux MPRIS, permissions, dialogs and application lifecycle. Qt's internal Mac
reference disables production updating and uses
`com.tlolabs.encap.qt-reference`; it is not the production SwiftUI macOS app.

Target receipts must validate source/artifact identity, profile/features,
ABI/schema, architecture, deployment minimum, transitive libraries, loader paths,
Swift/Metal/catalog resources, corresponding sources and licenses. A source pin,
cross-compile or one working native Mac operation does not qualify another target
or a final package. [The migration matrix](linked-migration.md) records actual
checks and blockers. Native macOS development builds are unnotarized; standard
local distributions require Developer ID, Apple Accepted status, stapling and
final extracted-app signature/Gatekeeper acceptance. Current weekly native
Windows/Linux publication and authenticated updater policies remain unchanged.

## Safety invariants

- Archives reject traversal, duplicate paths, links, special files, oversized
  manifests, extreme expansion and suspicious compression ratios.
- Outputs stage beside their destination and replace it only after success.
- Native errors retain structured domains/codes; raw diagnostics stay local.
- Source/protected-path checks and saved unknown compatibility fields remain.
- No telemetry, analytics or automatic diagnostic upload is introduced.
