# AVID Core

AVID Core 0.4 is the canonical artwork/audio composition library for ATIV and
EnCAP, with directly callable media and transcription libraries. Production
media calls FFmpeg libraries in-process. It never discovers or launches
ffmpeg/ffprobe, a shell, or a media service, and never downloads executable code
at runtime. The safe Core crate retains `#![forbid(unsafe_code)]`.

This migration changes Core and its examples; ATIV and EnCAP have not been
modified or qualified. See [implementation and qualification status](docs/linked-status.md),
[host migration and ABI](docs/linked-api.md), [linked artifacts](docs/linked-artifacts.md),
and [transcription providers](docs/linked-transcription.md). Incomplete platform
execution, alignment/provider coverage, and distribution decisions remain explicit.
The historical authenticated six-target executable runtime, published assets,
Recipe 7 specification and consumer pins remain immutable and separate.

## Libraries

```text
Swift / C++ / Qt / JNI host worker
                 |
        C ABI 1 or safe Rust API
                 |
       avid-core (policy, staging)
                 |
       avid-media-bridge (FFmpeg libraries)

Apple host -> AVIDTranscription + AVIDTranscriptionEngines (existing linked providers)
Other hosts -> avid-transcription -> optional pinned whisper.cpp adapter
```

Core keeps presets, settings/state serialization, fitted and square-padded
artwork, background blur, flips, square pixels, previews, single exports,
timelines, H.264/HEVC selection, cancellation, progress, limits and protected
atomic output publication. JPEG/PNG optimization stays linked to pinned
TurboJPEG/libdeflate/OxiPNG/Zopfli. This software is based in part on the work
of the Independent JPEG Group. Animated image optimization remains unsupported;
GIF/APNG export and Simple first-frame freezing are distinct operations.

| API | Responsibility |
| --- | --- |
| `Renderer::new()` | Construct the linked engine without executable paths |
| `Renderer::default_settings()` | Profile default: Software on software-only builds; Automatic on Apple profiles |
| `OperationOptions` | Cooperative probe/preview/per-attempt render deadlines |
| `probe_audio_duration`, `inspect_image`, `capabilities` | Linked inspection and compiled/initialized encoder support |
| `preview`, `render`, `render_with_mode` | PNG previews, MP4 exports and Simple/PerFrame policy |
| `RenderSettings`, `Composition`, `Codec`, `Encoding` | Explicit execution choices; unsupported choices fail |
| `Input`, `Clip`, `Timeline` | Single original audio or ordered hard cuts with stereo/48 kHz timeline audio |
| `optimize_image` | Static JPEG/PNG optimization and independent animation rejection |
| `VideoSettings`, `VideoProjectState` | Existing versioned host settings serialization |
| `CancellationToken`, `EventSink`, `Stage`, `Progress`, `Error` | Cooperative lifecycle, progress and structured library errors |
| `avid-core-ffi` / `include/avid_core.h` | Versioned C ABI with opaque handles and length-delimited JSON |
| `avid-transcription` | Portable transcript correction/captions, verified model leases and optional linked inference |

`legacy-subprocess` is an opt-in reference-test feature exposing
`LegacyRenderer`, `MediaTools` and historical runtime APIs. It is excluded from
normal artifacts and is never selected as fallback. This is an explicit pre-1.0
minor API break from `Renderer::new(tools)`; use a new verified linked artifact
and the migration recipe. Do not enable this feature in shipping hosts.

```rust,no_run
use avid_core::*;
# fn main() -> Result<()> {
let renderer = Renderer::new();
let cancel = CancellationToken::default();
renderer.render(&RenderRequest {
    input: Input::Single { image: "cover.png".into(), audio: "track.wav".into() },
    output: "video.mp4".into(),
    settings: renderer.default_settings(),
    protected_paths: Vec::new(),
}, &cancel, &())?;
# Ok(())
# }
```

Build-time `AVID_FFMPEG_PREFIX` must point to the exact target SDK produced by
Core's linked build tooling. No arbitrary installed FFmpeg is a production
fallback. `AVID_FFMPEG_DEV=1` explicitly permits an unqualified development SDK.
The [0.4.0 source release](https://github.com/tlolabs/avid-core/releases/tag/v0.4.0)
contains the complete workspace, including local bridge crates. Host adoption
still requires target-native qualification; existing consumer pins are unchanged.
See [building](docs/BUILDING.md), [dependencies](docs/DEPENDENCIES.md), and
[verification](docs/TESTING.md).

## Media and lifecycle

Fitted uses sigma40 blur and a fitted foreground; SquarePadded uses sigma20 and
a square-padded foreground. Single audio preserves sample rate/channel layout;
timelines trim ordered clips and normalize to stereo/48 kHz. PerFrame preserves
animation; GIF repeats, APNG honors embedded play counts and holds its finite
final frame, and Simple freezes the first composed frame. Both modes share
validation, composition construction, encoding, staging and publication.

Explicit Software requires the selected build's software codec. Hardware never
silently falls back. Automatic retries software after a native hardware attempt
fails and retains errors from both failed attempts. Capabilities distinguish
compiled codecs from representative hardware initialization; successful full
exports still require native qualification. Apple LGPL FFmpeg intentionally
omits x264/x265 and uses VideoToolbox H.264/HEVC with AAC; it cannot satisfy an
explicit Software request. Existing persisted software choices remain unchanged.

Run blocking calls on host workers and copy events to the UI dispatcher.
Per-operation FFmpeg contexts are deterministically destroyed before return;
independent jobs may run concurrently. Hosts serialize writers to the same
output. Cancellation checks processing loops and interruptible I/O. Native
codec/driver calls may delay cancellation or deadlines; Core promises no hard
timeout. FFmpeg global logging policy belongs to the host.

Only local direct-media formats/protocols are accepted, including restrictions
on nested media references. Source dimensions, resource limits, symlink/hardlink
aliases and protected paths are checked. Output is staged in the destination
directory, validated nonempty, synchronized and atomically replaced only after
success and cancellation checks. `Stage::Complete` follows publication. Failure
or cancellation preserves the existing destination; force-killing the host can
leave a staging file. No hostile concurrent-filesystem or power-loss guarantee
is made.

## Distribution and provenance

AVID Core-owned code remains GPL-3.0-or-later. The separate Apple GPL profile adds x264/x265 to VideoToolbox for Automatic
fallback; the software-only GPL profile uses x264/x265 across platforms.
An LGPL-only FFmpeg profile does
not relicense Core or establish App Store eligibility. Static-link obligations,
model licenses, third-party rights and copyright-holder permissions require
separate assessment for each combined distribution. See [licensing](LICENSING_REVIEW.md)
and [third-party notices](THIRD_PARTY_NOTICES.md). No stores or release assets are
published by these build/test tools.

Core owns source, build, target identity, dependency/license inventory, checksums
and linked packaging. Hosts own integration, filesystem permissions, application
signing/notarization, compatibility and releases. Automatic CI remains the
weekly diagnostic Linux/Windows native executable smoke path in [AGENTS.md](AGENTS.md);
linked verification is deliberate local work, not a new CI gate.

Original behavior derives from ATIV `2c5eeed27e48d67fed128a62ff74dab6f00c2a82`
and EnCAP `a96978e5bb89189b944e5dd6a30e5ee7e8fe28d4`; see
[provenance](docs/provenance.md) and the historical [inventory](docs/inventory.md).
Copyright © Thomas Lothian.
