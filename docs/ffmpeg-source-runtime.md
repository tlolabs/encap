# EnCAP-owned FFmpeg source runtime

EnCAP builds and distributes FFmpeg and ffprobe **9.0.2**, official tag `n9.0.2`,
from https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz. The official download page
identified this as the latest stable release on 2026-09-20 (released 2026-09-18).
`runtime/ffmpeg/dependencies.json` is the dependency/update-check record and the
single version/configuration source. AVID Core remains the immutable Rust Video
implementation at its existing API/revision; it supplies no runtime assets.

## Trust and provenance

The source archive must match SHA-256
`8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`.
Every source build also verifies the official detached OpenPGP signature with
`gpgv` against the checked-in upstream public key, requiring `VALIDSIG` fingerprint
`FCF986EA15E6E293A5644F10B4322F04D67658D8`. This fingerprint is published at
https://www.ffmpeg.org/download.html#release_9.0. No keyserver or user trustdb is
used. Every external-library source URL, revision and SHA-256 is pinned in the
same record. x264 is fetched by exact commit from its official Git repository;
a deterministic uncompressed `git archive` must also match its pinned SHA-256.
This avoids the archive web endpoint's bot challenge on hosted runners.
Downloads fail closed, use HTTPS, and are verified before extraction.
No FFmpeg prebuilt executable, system FFmpeg or Core runtime asset is downloaded.

## Configuration and licensing

Common FFmpeg options:

```
--disable-autodetect --disable-shared --enable-static --enable-gpl
--disable-nonfree --enable-libx264 --enable-libx265 --enable-libmp3lame
--enable-zlib --enable-ffmpeg --enable-ffprobe --disable-ffplay
--disable-doc --disable-debug
```

All default internal codecs, formats, protocols and filters remain enabled.
There is no minimal codec allowlist. EnCAP's Audio exports MP3/LAME and AAC,
including AudioToolbox on macOS; Transcript converts to mono 16 kHz PCM;
Video retains software H.264/HEVC, artwork, composition, scale/crop/blur/overlay,
flips, frame rates and audio resampling. Native decoders, PNG/JPEG, WAV/AIFF and
metadata/chapter handling remain available. x265 is an 8-bit build, matching
EnCAP's existing `yuv420p` output. macOS additionally enables AudioToolbox and
VideoToolbox. Windows/Linux keep the existing software video policy.

External libraries are built statically from source:

| Library | Pin | License |
| --- | --- | --- |
| x264 | `b35605ace3ddf7c1a5d67a2eb553f034aef41d55` | GPL-2.0-or-later |
| x265 | 4.2 | GPL-2.0-or-later |
| LAME | 3.100 | LGPL-2.0-or-later |
| zlib | 1.3.1 | Zlib |

The resulting FFmpeg programs report GPL v2 or later; nonfree components are
forbidden. EnCAP itself remains GPL-3.0-only and invokes the programs as separate
processes. Official guidance: https://ffmpeg.org/legal.html. Each application
package contains the exact corresponding source archives (including libraries),
licenses, recipe, configure arguments, toolchain record, source verification and
pre/post-ad-hoc-sign binary hashes under `FFmpeg/`. This also makes source
available wherever the application artifact is distributed. No source patches
are applied. OS system frameworks/libc remain system dependencies; Windows
compiler runtimes must be linked statically. Windows uses the matching C++
linker and disables libc++ DLL-import annotations for static x265 compilation,
as required by the [libc++ build configuration](https://github.com/llvm/llvm-project/blob/main/libcxx/CMakeLists.txt).
Installed compiler-runtime license texts are included alongside codec licenses;
these cover libc++, libc++abi, libunwind, compiler-rt and MinGW runtime code. The linkage audit rejects codec or
compiler DLL dependencies and Homebrew dylibs.

## Building and upgrading

Prerequisites: Bash, C/C++ compiler, make, CMake, NASM, pkg-config, jq, curl, tar,
xz, Perl (`shasum`), GnuPG/gpgv. On macOS use Xcode and deployment target 13.0.
Windows uses MSYS2 CLANG64 or CLANGARM64 on the corresponding native runner.
Linux uses the Ubuntu 24.04 toolchain, separately on x64 and ARM64. Package
managers supply build tools only, never the distributed FFmpeg runtime.

```
bash script/prepare_ffmpeg.sh macos arm64
bash script/prepare_ffmpeg.sh linux x86_64
bash script/prepare_ffmpeg.sh windows arm64
```

The native compiler architecture must match. `aarch64` is accepted as `arm64`.
stdout contains only the built prefix; progress goes to stderr. The legacy
`build_ffmpeg.sh`, `build_ffmpeg_linux.sh` and `fetch_ffmpeg.sh` entrypoints all
call this same source recipe. `script/ffmpeg/stage.sh` verifies and packages the
result. Normal macOS development and packaging use `script/build_and_run.sh`;
Windows/Linux normal native CI uses the same source action and staging function.
There is no qualification-only application, runtime feature or Core staging path.

To upgrade, select a stable release from the official download page, verify its
signature using the published fingerprint, update the version/tag/URL/SHA-256 in
`dependencies.json`, and run the clean six-target workflow. Change library pins
and hashes explicitly when updating them. Configuration changes belong in the
record or versioned recipe, never undocumented local compiler flags. Existing
project schemas, encoder identifiers and Core API calls are unchanged.

## Reproducibility and cache boundaries

`SOURCE_DATE_EPOCH=1789699562`, `TZ=UTC`, `LC_ALL=C`, `ZERO_AR_DATE=1`, prefix maps,
no debug information, no host-native CPU tuning, no Windows PE timestamps, Apple linker reproducible mode, and
static external libraries reduce variability. Build logs record every effective
configure/CMake command. Per-target `toolchain.txt` records compiler, C++ compiler,
assembler, linker, archiver, make, CMake, pkg-config, SDK/Xcode/deployment target,
runner image and MSYS2 package versions (or Linux libc/binutils/compiler package
versions). Build jobs are native for all six targets.

The exact artifact cache key hashes target, dependency record, public key, the
source build script and toolchain record. There are no prefix/partial restore keys.
Cached files are verified by SHA-256 before reuse and again before staging.
Recipe, FFmpeg, library, compiler, SDK and runner-image changes invalidate it.
Build directories and downloads are not restored as compiled artifacts.
Packaging/test-only edits do not force recompilation of unchanged FFmpeg sources.

`workflow_dispatch: clean_ffmpeg=true` bypasses restore/save and deletes the
matching build/install trees. Locally use a third argument `clean`. Downloads
may be reused only after their pinned checksum is checked; signatures are
verified anew. Compare the two `runtime.json` binary digests from clean builds
for repeatability. The recorded macOS ARM64 clean-repeat check is in
`runtime/ffmpeg/repeat-macos-arm64.json`. In the final-recipe repeat, ffprobe
matched byte for byte; ffmpeg differed in its Mach-O UUID/signature metadata,
with the executable payload unchanged. An earlier repeat matched both binaries,
so that result is not treated as a general guarantee of Apple linker bit identity.
Bit identity across different toolchains/SDKs, OS patch levels
or signing identities is not promised. The cache keys deliberately distinguish
these environments, and signing hashes are separate from source-build hashes.

## Discovery and acceptance

The release engine resolves `ffmpeg[.exe]` and `ffprobe[.exe]` beside its own
executable. Metadata is `Contents/Resources/FFmpeg/runtime.json` on macOS and
`ffmpeg-runtime/runtime.json` beside the engine in portable packages. It requires the
expected version/target/schema and SHA-256 of both binaries before any mode can
use them. Missing/malformed/corrupt pairs fail with a reinstall message. Release
engines ignore FFmpeg environment overrides and never search PATH. Debug builds
allow an explicit absolute *pair* for process fixtures; an invalid override fails.
Optional transcription helper discovery retains its existing behavior.

`script/ffmpeg/qualify.sh <normal packaged engine>` runs real Audio, Transcript
and Video operations, project save/reopen/recovery, codec/filter inventories,
actual FFmpeg cancellation, real Whisper inference using the normal Transcript
backend, and missing/corrupt tool/manifest tests while a working pair is on PATH.
The engine subprocesses have PATH empty for media tests. The speech fixture comes
from the pinned whisper.cpp checkout; the Base English test model is hash-checked
and stored only in the ignored qualification cache, not shipped in the app.
These tests use the release engine packaged with the ordinary native UI.
Native app build/model checks remain in the workflow. Signing is ad-hoc only on
macOS; no Developer ID/notarization credential is needed.

For actual run results and limitations, see [verification results](ffmpeg-runtime-readiness.md).
