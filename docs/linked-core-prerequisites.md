# Core prerequisites for the remaining EnCAP paths

Inspected immutable source: AVID Core `0.4.0`,
`dd112d497b68df6786f49a71b3611f7f32f090e9`. Its public Rust renderer and
`include/avid_core.h` expose capabilities, image inspection, audio duration,
preview, video render and image optimization. They do not expose the operations
below. The private/native audio decoder used for inference is not a supported
playback contract. The three linked FFmpeg profiles do not include libmp3lame.
An executable-runtime receipt cannot authenticate a linked library.

These are proposed **upstream contracts**, not implemented Core operations.
This document is a handoff; it does not claim that the migration is complete.
Until equivalent APIs and artifacts exist, existing Audio export, Qt PCM
playback and bounded WAV/AIFF/AIFC inspection/waveform compatibility code remain
unfinished ownership boundaries. They must not be removed to qualify a reduced
application or replaced by another libav implementation inside EnCAP.

## Audio export

Core should own `AudioExportRequest` / `export_audio`, with typed Rust and
versioned foreign interfaces. Suggested fields:

| Field | Required meaning |
| --- | --- |
| `sources` | Ordered local paths with optional exact decoded sample trim ranges; preserve canonical episode order, never a Video selection or an encoded Audio export intermediate. |
| `output` / `protected_paths` | Local output plus every project/source/artwork path. Same-directory staging, alias checks and atomic publication. Success/Complete only after publication; preserve an old destination on every failure/cancel. |
| `normalization` | Each input normalized to stereo/48 kHz before concatenation, followed by requested final mono/stereo channel count. Explicit duration/sample-boundary policy and no inserted silence/crossfade. |
| `encoding` | MP3/libmp3lame bitrate and ID3v2.3, or AAC/M4A bitrate with explicit native `aac` / Apple `aac_at`, plus MP4 faststart. Unsupported requested encoder is an error, never substitution. |
| `metadata` | Album/artist, episode title, description; ordered chapter stable ID/title, start/end sample or rational time, and link URL. Preserve Unicode, escaped values and empty optional fields. |
| `artwork` | Episode image path, one attached PNG frame, aspect ratio retained, maximum edge 3000 pixels. Image EOF/frame limit must never shorten the audio. Per-chapter artwork must remain an explicit unsupported error. |
| `control` | Separate cancellation token and borrowed copied progress; return only after encoder/file cleanup. No hard thread-kill timeout guarantee. |

The linked artifact specification must add a deliberate libmp3lame source/hash,
build recipe, encoder enablement, static/dynamic dependencies, corresponding
source and license inventory. A media profile with AAC and video encoders alone
does not provide chaptered MP3/AAC/M4A parity.

Keep project manifests out of Core JSON. Core's 4 MiB request maximum and EnCAP's
8 MiB manifest maximum remain unchanged. The EnCAP facade reads a bounded project
file and creates operation-specific typed requests. An upstream foreign metadata
extension can use a separately owned immutable metadata-resource handle,
populated in bounded chunks and finalized with byte length/hash, rather than
requiring a whole 8 MiB manifest in a 4 MiB request. Specify its own chapter/text
limits and reject oversize data before writing; never silently truncate it.

## Public playback decoding

Add an owned `PcmDecoder` with `open`, `seek`, `read_frames`, `cancel`, `close`.
Expose it in the supported Rust API and an opaque C ABI, not private native
symbols. `open` validates a local path and requested output sample format/rate/
channels, returning the actual negotiated format and exact clock origin.
`read_frames(max_frames)` returns a bounded interleaved PCM buffer (for example
at most 16,384 frames), source-clock sample index/rational timestamp, valid frame
count and explicit EOF. Buffer ownership, copy/release and cancellation must be
defined. A byte count is not a timestamp.

Seeking must report the first returned source-clock sample and discard codec
preroll consistently, including decoder delay, nonzero start times and the final
partial frame. Permit independent decoder/render jobs and reject use after
close. Return native library/operation/code errors without a fabricated process
record. EnCAP retains native audio devices, timeline mapping, seeking controls,
generation guards, SMTC/MPRIS, cleanup and UI dispatch. It must join work before
library unload/update; superseded decoded buffers must never reach a new source.

## Structured inspection and waveform windows

Add public sample/container inspection returning codec/container, sample rate,
channel layout, sample format/valid bits, exact decoded sample count or explicit
unknown, start time and duration provenance. Define WAV extensible valid bits,
AIFF/AIFC big/little endian/compression, sound offsets, malformed/truncated chunks
and nonfinite float behavior before replacing the bounded compatibility parsers.
Container duration alone is insufficient for existing sample-accurate imports.

A waveform/sample-window API should accept a bounded source range, channel
selection and maximum output bucket count, returning source-clock min/max/RMS
or the documented first-channel representation. Define empty windows,
downsampling, seek accuracy and I/O/memory bounds for long recordings. Preserve
current behavior until equivalence tests demonstrate an intentional replacement.

## Reproducing fixtures and acceptance

Existing executable compatibility behavior is specified by
`crates/encap-audio/src/lib.rs` (`export_arguments`, `ffmetadata`, validation),
`crates/encap-engine/tests/media_contract.rs`, and bounded sample/waveform tests
in `crates/encap-core/src/source.rs` / `waveform.rs`. Tests are retained as
requirements evidence; an argument-only test is not actual linked export evidence.

`crates/encap-video/src/tests.rs::linked` generates real PNG and mixed
44.1/48 kHz PCM WAV fixtures without media executables. The native Video suite
`crates/encap-video/tests/core031_native.rs` uses explicitly selected diagnostic
tools only to generate/check fixtures; rendering itself calls linked Core.
Its external tool directory does not authenticate any production library.

Before adopting the proposed upstream operations, run actual final-file cases:

1. Naturally ordered mixed WAV/AIFF/AIFC mono/stereo, differing rates/valid bits;
   sample counts crossing concatenation boundaries and no additional gaps.
2. MP3 and AAC/M4A, each supported encoder/bitrate/channel choice; independently
   decode full duration and inspect sample rate, channel count, ID3 version,
   episode tags, chapter millisecond/sample boundaries and chapter URLs.
3. Portrait/landscape/oversized/animated episode artwork: exactly one attached
   PNG, retained aspect ratio, maximum 3000-pixel edge, complete recording audio.
   Explicitly reject chapter artwork and unsupported codec/profile choices.
4. Unicode/colon/space paths, symlink/hardlink/protected aliases, existing
   destination, corrupt input, cancellation before/during encode and output
   publication failure. No changed source/destination or leaked staging files.
5. PCM playback repeated open/seek/read/close, source/timeline boundary seeks,
   partial final frames, cancellation, stale generations, simultaneous render,
   removed/reordered sources and shutdown/update exclusion. Compare decoded
   timestamps and waveform windows with established bounded-parser fixtures.
6. Execute production application operations with all media executables absent.
   Qualify macOS Intel/ARM64 and native Windows/Linux x64/ARM64 independently.

No upstream source changes, tags, releases, uploads or publication are authorized
by this handoff. Native application acceptance and distributable notarization
remain separate from a source pin, SDK receipt or upstream test pass.

## Reproduced Video difference at the immutable pin

The native `static_modes_match_appearance_audio_cadence_duration_and_record_cost`
test fails at Core `dd112d4` with the verified macOS ARM64 `gpl-software` SDK.
The first H.264 case is 320×180 at 24 fps, with the existing mixed-rate timeline,
portrait/landscape artwork, SquarePadded composition and no flips. Simple versus
PerFrame decoded RGB mean absolute difference is **2.109520961934156**, above the
existing 0.1 expectation. This is not converted into a pass or hidden by forcing
every operation to PerFrame; conservative static scheduling remains intact.

Reproduce with the pinned SDK and an explicitly selected external diagnostic
fixture/decoder directory:

```sh
ENCAP_CORE_RUNTIME_DIR=/absolute/diagnostic-tools \
ENCAP_CORE031_EVIDENCE_DIR=/absolute/evidence \
AVID_FFMPEG_PREFIX=/absolute/verified-linked-prefix AVID_FFMPEG_STATIC=1 \
MACOSX_DEPLOYMENT_TARGET=13.0 \
cargo test --locked --offline -p encap-video --test core031_native \
  static_modes_match -- --ignored --test-threads=1
```

The regression retains both actual MP4 outputs and its measurements on failure.
Task evidence is outside the repository at
`/private/tmp/encap-linked-20261116-dc1e968/video-native/` with hashes, plus the
separate static-test log. The native preview/cache/failure/independent-cancellation
test passed. Neither this partial result nor the basic linked unit exports
qualifies the complete Video path or another target.
