# EnCAP-owned FFmpeg source runtime

EnCAP consumes AVID Core 0.3.0 at `3fb68807bc7c350359e1634b32af477ea3042c16`,
the exact ATIV pin. Cargo.lock and a build-time check enforce the pin; normal
`encap-engine build-info` reports the compiled version, revision and Cargo source.
Core is a source library. It supplies no runtime assets or packaging helpers.

## Dependency and reference

[`runtime/ffmpeg/dependency.json`](../runtime/ffmpeg/dependency.json) follows ATIV's
machine-readable dependency/configuration record. FFmpeg **9.0.2**, released
September 18, is the current stable release on the [official download page](https://ffmpeg.org/download.html)
as checked September 23, 2026. Both hosts use the same official archive, SHA-256
`8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`, detached
signature and pinned signer `FCF986EA15E6E293A5644F10B4322F04D67658D8`.

The native builder and stage/finish/validate pipeline are adapted from ATIV
`bc43ed0fc3c82acc4ea2ffbf0bb65fd2c8ebb91e`. The reference files and checksums are
recorded in [ativ-reference.json](../runtime/ffmpeg/ativ-reference.json) for future
upstream comparisons. This is the same methodology with EnCAP-specific codec and
layout extensions, not a dependency on an adjacent checkout. No Core source is copied.

FFmpeg, x264 (stable `b35605a`) and zlib 1.3.1 exactly match ATIV's source pins.
EnCAP additionally builds checksum-pinned x265 4.2 and LAME 3.100 to preserve HEVC
and MP3 export. It retains all built-in encoders and filters and macOS
AudioToolbox/VideoToolbox support. ATIV's narrower H.264/AAC profile cannot preserve
EnCAP's features. The FFmpeg source version is identical; the binaries and full
configure profiles intentionally differ. No FFmpeg source patch is applied.

## Build and package

Python 3.12+, a native C/C++ compiler, make, CMake, pkg-config and GnuPG are build
tools only. The installed app remains Rust plus native SwiftUI, WinUI or GTK;
users need neither Python nor system FFmpeg. The existing shell entrypoints call
`script/ffmpeg_build.py` and `script/ffmpeg_runtime.py`.

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
python3 script/ffmpeg_build.py build macos-arm64 --clean
./script/build_and_run.sh --verify
./script/build_and_run.sh --package
```

The same workflow runs native macOS ARM64/Intel, Windows x64/ARM64 and Linux
x64/ARM64 builds. Windows uses UCRT64/GCC on x64 and CLANGARM64/Clang on ARM64,
following ATIV. Compiler packages supply tools, not FFmpeg/codec binaries.
macOS targets 13.0; Linux uses Ubuntu 24.04. Codec libraries are static; only
platform/compiler system libraries may be dynamic (including glibc vector math
and the C++ runtime needed by x265 on Linux).

The builder verifies every source archive's checksum and FFmpeg's upstream
signature in an isolated keyring before building. It rejects unsafe archive
entries, missing capabilities, incorrect executable architecture, unexpected
versions and non-system linkage. It sets SOURCE_DATE_EPOCH, locale, deterministic
archive settings, path maps and Windows timestamp flags as ATIV does. Assembly
is disabled in the portable reference profile. Reproducibility means recorded,
verified inputs and build commands; bit identity across SDK/toolchain versions
is not promised.

The exact cache fingerprint covers dependency/configuration, release key, both
build scripts, target, actual compiler/toolchain/SDK/runner inputs. A restored
payload is verified. There are no partial cache keys or binary-download fallbacks.
`clean_ffmpeg=true` bypasses CI cache restore/save. `ENCAP_FFMPEG_RUNTIME` may select
only a verified EnCAP source payload for packaging; it cannot select arbitrary binaries.

Normal package assembly calls provision, stage, finish and validate. `build.json`
records inputs, configure commands, toolchain, signature verification and original
binary hashes. `payload.json` hashes source and metadata; `signed-payload.json`
records post-signing executable hashes. `encap-runtime.json` binds these to the
compiled Core/application identity. Both executables live beside `encap-engine`.
Metadata lives in `Contents/Resources/FFmpeg` on macOS and `ffmpeg-runtime` beside
the engine on Windows/Linux. The corresponding sources, signature, release key,
build scripts and license texts travel in every package.

All modes use this one host-owned pair. Release engines ignore PATH and the
`ENCAP_FFMPEG`/`ENCAP_FFPROBE` environment variables. Debug tests may explicitly
supply both absolute paths; partial, missing or mismatched overrides fail.
Core validates the explicit pair and owns Video media operations. Audio/Transcript
retain their host workflows. Native project and ZIP schemas remain unchanged.

## Verification and updates

Run `python3 script/test_ffmpeg_build.py`, all Cargo tests, and the normal package
builder. `script/ffmpeg/qualify.sh` tests the actual packaged engine across all
modes with PATH empty, real Whisper transcription, media probing, cancellation,
project compatibility and preservation of outputs. `test_ffmpeg_runtime.py` tests
relocation, altered Core/target provenance and missing/corrupt tools or manifests
with usable tools on PATH. This test harness does not build a different application.

To update: verify the official release/signature, update the dependency record
and source epoch, review ATIV reference changes, increment the recipe for build
changes, and run the clean native matrix. Do not carry forward historical matrix
results as evidence for a new recipe. See [current migration results](normal-runtime-migration.md).
