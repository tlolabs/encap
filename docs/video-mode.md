# Video mode

Video is an export workflow over the currently open EnCap project. Audio owns
the canonical chapter order, source recordings, main artwork, and optional
chapter artwork. Video stores only a selected chapter ID order and one current
export configuration; reordering it never changes Audio.

The preview plays each selected source directly and changes its effective
artwork at the cumulative boundary. Effective artwork is the chapter image when
present, otherwise the project's main artwork. The canvas matches the selected
aspect ratio: a cropped, Gaussian-blurred copy fills the background and a sharp
square copy is centered in front. Horizontal and vertical flips affect both.

Export uses the same timing model. FFmpeg receives each original chapter audio
source and artwork as a separate input, trims them to the chapter duration, and
concatenates normalized video/audio pairs in one filter graph. There is no MP3
intermediate, added silence, overlap, crossfade, caption stream, or MP4 chapter
metadata. Output is staged beside the destination and atomically published only
after FFmpeg succeeds.

Video 2.0 exports MP4 with H.264 or HEVC. Automatic encoding prefers an encoder
actually reported by the bundled FFmpeg (`VideoToolbox`, NVENC, QSV, AMF, or
VAAPI as appropriate) and falls back to `libx264`/`libx265`. Hardware mode fails
preflight with a clear message if none is present; Software mode always requires
the matching software encoder. Dimensions are even, at most 8192 on either axis,
and at most 33,177,600 pixels. Frame rate is 1–120 fps.

Video does not require a transcript and does not render captions in 2.0. The
project schema separately persists optional word timings so a later composition
engine can build transcript-driven graphics without changing Audio or Video 2.0.

`encap-video` is a host adapter over the immutable Git dependency `avid-core` 0.3.3.
No adjacent source checkout is required. Core owns presets, persisted Video types, validation,
selection, encoder choice, composition, media execution, and atomic publication.
The adapter retains whole-project checks, the required main-artwork inspection,
checked chapter-number mapping, all protected project/media paths, and safe messages.
Reusable `VideoRenderer` sessions and clones share Core's bounded probe caches.
The engine and both native clients use Core's PNG composition previews; playback
of the selected audio sources and the existing transport controls remain native.

The shared settings adapter explicitly selects `Composition::SquarePadded` (sigma20).
PNG previews show the first artwork frame using the export composition and flips.
Pause/seek/next/previous and preview_quality remain host state; export pause/resume
is not provided. Preview tasks are independent of playback and export tasks and
do not recompose on every playhead tick.
Probes default to 30 seconds, preview to 120 seconds, and export has no default timeout.
Shared events go only to local tracing; stdout remains one JSON value.

Automatic export selects `RenderMode::Simple` only for confidently static PNG/JPEG
containers and an estimate of at most 256 MiB of cached composed frames (four
bytes per output pixel per clip, including repeated artwork). Simple composes once
per clip in FFmpeg memory without temporary PNG files. Larger timelines, APNG,
GIF, WebP, and unknown media retain PerFrame for the entire render. Explicit
`--render-mode simple` and `--render-mode per-frame` are comparison controls;
Simple deliberately freezes animation. The budget is not a total process memory
limit. Core's size/mtime probe fingerprints invalidate ordinary changed sources.

The 0.3.2/0.3.3 Core source fixes square-pixel normalization for mixed-aspect
portrait timelines and content-based GIF/APNG option selection. The authenticated
runtime pin remains independent of this library update. Earlier failure evidence
in the 0.3.1 report is historical, not a claim that those fixes are absent.

The [ownership audit](avid-core-audit.md) records the remaining automatic-mode
classifier overlap. Core exposes explicit Simple/PerFrame modes but no public
static-image classifier or aggregate cache-budget API; EnCAP's existing conservative
mode policy remains an explicit Core gap. Composition, decoding and rendering
still delegate to Core. Artwork optimization is a separate explicit operation using
Core's in-process JPEG/PNG API; it does not run FFmpeg or change Video settings.

See [0.3.1 integration verification](core-031-integration.md) for historical evidence
and restrictions; current ownership and remaining gaps are in the audit above.
