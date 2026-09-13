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

The implementation adapts the user-facing presets and artwork treatment from
the former AVID application into `encap-video`; AVID is neither a submodule nor
a build/runtime dependency.
