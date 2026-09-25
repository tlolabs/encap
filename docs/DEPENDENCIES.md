# Dependencies

EnCap uses locked or pinned source inputs where practical. The exhaustive Rust
dependency set is in `Cargo.lock`; Swift's resolved graph is in
`helpers/whisperkit_transcriber/Package.resolved`. The source-runtime
manifest in `runtime/ffmpeg/dependency.json` records versions, hashes,
licenses, build flags, and supported targets for FFmpeg and codec libraries.
These files are machine-readable inventory inputs and must be updated with
dependency changes. License and provenance limits are recorded in
[LICENSING_AUDIT.md](LICENSING_AUDIT.md).

| Direct dependency | Purpose | Source and license |
| --- | --- | --- |
| AVID Core v0.3.0 | Video composition/export | Pinned Git revision from [tlolabs/avid-core](https://github.com/tlolabs/avid-core); GPL-3.0-only. |
| FFmpeg/ffprobe 9.0.2 | Local media probing, conversion, rendering | Authenticated [FFmpeg source](https://ffmpeg.org/); configured GPL-2.0-or-later. |
| x264, x265, LAME, zlib | FFmpeg codecs/compression | Source URLs and exact hashes in `runtime/ffmpeg/dependency.json`; GPL-2.0-or-later, LGPL-2.0-or-later, Zlib. |
| whisper.cpp v1.9.1 | Local speech inference | Pinned [upstream](https://github.com/ggml-org/whisper.cpp); MIT. |
| Argmax OSS/WhisperKit | Optional local macOS model reuse | Pinned [Argmax source](https://github.com/argmaxinc/argmax-oss-swift); MIT with Apache-2.0 portions. |
| Sparkle 2.9.6 | macOS update checks via GitHub Releases | Pinned [Sparkle release](https://github.com/sparkle-project/Sparkle); MIT. |
| Microsoft Windows App SDK 2.4.0 | WinUI 3 interface | NuGet package; see the package's redistribution and license terms. |
| GTK 4, libadwaita, JSON-GLib, GStreamer | Linux interface, media preview, JSON handling | Distribution system packages; mainly LGPL licenses, as provided by upstream packages. |
| Rust workspace crates | JSON protocol, logging, downloads, archives, filesystem and CLI | Exact transitive versions in `Cargo.lock`; inspect each package's metadata and notices when preparing a release. |

The app does not bundle speech model weights. The optional model catalog uses
Hugging Face downloads initiated by the user; model terms need separate review.
See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for preserved notices.
Dependency compatibility concerns should be prominent release warnings, while
missing required notices or incorrect declared licenses are structural errors.
