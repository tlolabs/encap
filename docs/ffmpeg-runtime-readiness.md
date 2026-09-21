# EnCAP source-runtime verification

FFmpeg source builds and normal packaged-engine Audio, Transcript and Video
acceptance pass on **all six targets**. Five native package jobs pass completely.
The current macOS Intel `.app` passes every media/runtime check, but its existing
250 ms project-save performance gate fails before DMG creation. The overall CI
run is therefore not green. No production release was published.

## Pinned dependency and scope

- FFmpeg and ffprobe: **9.0.2**, official tag `n9.0.2`, latest stable confirmed on
  the [official download page](https://ffmpeg.org/download.html) on 2026-09-21.
- Official source: https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz.
- SHA-256: `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`.
- Authentication: official detached OpenPGP signature, checked with `gpgv` and
  pinned fingerprint `FCF986EA15E6E293A5644F10B4322F04D67658D8`. A locally
  corrupted source archive was rejected with a bad signature.
- Machine-readable pins, external source hashes, configuration and recipe:
  [`dependencies.json`](../runtime/ffmpeg/dependencies.json).
- Complete configuration, licensing, toolchain, cache and upgrade instructions:
  [source runtime](ffmpeg-source-runtime.md).
- AVID Core remains at its existing Rust API and revision
  `eab97dd043187aa8b7a1cae4eb2c1228fa25a9db`. Neither Core nor ATIV was modified.
  EnCAP project schemas and encoder identifiers are unchanged.

## Current clean native matrix

All jobs below are from the explicit `clean_ffmpeg=true` run of code/recipe
commit [`de8c184fd69607ec296db43f379a1b58f7a07e67`](https://github.com/tlolabs/encap/commit/de8c184fd69607ec296db43f379a1b58f7a07e67).
The shared source recipe fingerprint is
`6e9f8c11040aeaf18d294a52f725be17bcd01326783e88e790610123ef8de3d1`.
Subsequent documentation-only commits do not change this recipe or the tests.

| Target | Official source/signature + both builds + versions | All five media tests, discovery and rejection | Normal native package result |
| --- | --- | --- | --- |
| macOS Apple Silicon | Pass | Pass | App and DMG pass, [job](https://github.com/tlolabs/encap/actions/runs/35568982205/job/106236408649) |
| macOS Intel | Pass | Pass | App assembled/tested; later save-latency gate blocks DMG, [job](https://github.com/tlolabs/encap/actions/runs/35568982205/job/106236408802) |
| Windows x64 | Pass | Pass | WinUI app and ZIP pass, [job](https://github.com/tlolabs/encap/actions/runs/35568982205/job/106236408606) |
| Windows ARM64 | Pass | Pass | WinUI app and ZIP pass, [job](https://github.com/tlolabs/encap/actions/runs/35568982205/job/106236408763) |
| Linux x64 | Pass | Pass | GTK package and Btrfs persistence checks pass, [job](https://github.com/tlolabs/encap/actions/runs/35568982205/job/106236408675) |
| Linux ARM64 | Pass | Pass | GTK package and Btrfs persistence checks pass, [job](https://github.com/tlolabs/encap/actions/runs/35568982205/job/106236408743) |

The same run's general engine checks (formatting, lints, Rust workspace tests and
portable chapter rules) pass. macOS ARM64 also passes the native Swift tests.
Local normal macOS app builds, application launch and DMG creation passed.

Intel's failure is `mode_switch_save_latency_does_not_scale_with_existing_media`:
the first Transcript save after reopening a 257 MiB project took **377.765862 ms**,
exceeding the existing **250 ms** limit. Its five media tests passed immediately
before this gate, followed by all missing/corrupt runtime checks and the Audio
edit/save/reopen test. The timing gate has not been weakened. An
[earlier Intel DMG job](https://github.com/tlolabs/encap/actions/runs/35561049569/job/106213863304)
passed, but it is not represented as a current-recipe DMG result.

## Normal application acceptance

`script/ffmpeg/qualify.sh` invokes the ordinary packaged release `encap-engine`
shipped with each native UI. Release subprocesses have an empty PATH and no
FFmpeg override variables. There is no separate qualification application.
The five tests cover:

1. Expected runtime version and required encoder, decoder and filter inventory.
2. Audio MP3/AAC exports (plus macOS AudioToolbox), Transcript TXT/SRT, Video
   H.264/HEVC, probing, project save/reopen/recovery and source preservation.
3. Artwork composition and flips, portrait 90x160 at 60 fps with both flips,
   and invalid-media/error paths preserving original files.
4. A real long-running FFmpeg operation cancelled and reaped within five seconds.
5. Real Whisper inference through EnCAP's normal Transcript backend, converting
   stereo 44.1 kHz speech with packaged FFmpeg to the required mono PCM.

**Audio, Transcript and Video pass on all six targets.** Qualification also
removes and corrupts each tool and the manifest while a valid pair remains on
PATH: every damaged package is rejected. Poisoned `ENCAP_FFMPEG`/`ENCAP_FFPROBE`
variables are ignored by release engines; restoring the package restores success.
Unit tests reject incorrect manifest schema, version, target and binary hashes.

Interactive Mac screen testing was interrupted by a locked desktop. These are
automated checks of normal native packages and their normal engine, not a claim
that a manual UI walkthrough completed on all platforms.

Two fixture corrections leave production persistence and rendering unchanged:
ordinary codec-failure fixtures get five seconds while deliberate timeout cases
retain 80 ms; the same-size file mutation fixture explicitly advances mtime so
two tiny writes cannot share one NTFS timestamp.

## Windows source-build resolution

Windows x64 uses **GCC 16.2.0 / MSYS2 UCRT64**; ARM64 uses **Clang 22.1.8 /
CLANGARM64** in the qualified artifacts. Earlier Clang x64 builds crashed in
Gaussian blur at portrait dimensions. An isolated synthetic run reproduced the
access violation with blur alone while simple x264 encoding passed; scalar CPU
flags and single-thread variants did not fix it. GCC/UCRT passes all nine
synthetic probes and the unchanged normal application tests. No filter, codec,
CPU optimization or render-graph behavior was removed. This establishes a tested
toolchain combination, not a proven compiler root cause.

The recipe normalizes x265's generated `-l-l:libunwind.a` metadata, supplies its
native CMake processor, and uses portable x265 on Windows ARM64. A tiny x265 C
ABI program verifies static linking before FFmpeg configure. Corresponding
sources, compiler-runtime licenses and recipe information accompany artifacts.

All **289** files in the current x64 source artifact were independently checked
against its checksum list after download. Both tools report 9.0.2 and import only
Windows system DLLs; no codec or compiler DLL is required. GCC Runtime Library
Exception texts are present. The preceding verified ARM64 source artifact also
passed independent file-hash, PE architecture and system-DLL checks; the current
clean ARM64 job repeats source/version/linkage and normal-package verification.

## Reproducibility and caching

[`repeat-macos-arm64.json`](../runtime/ffmpeg/repeat-macos-arm64.json) records clean
repeats. For the current `de8c184` recipe, ffmpeg is byte-identical. ffprobe differs
in exactly **48 bytes**: 16 in `LC_UUID` and 32 in `LC_CODE_SIGNATURE`; every byte
outside those metadata regions matches. Earlier repeats have their individual
results and limitations recorded too. Universal byte identity is not claimed.
Other targets have native clean-build evidence, without repeat-build bit-identity
claims. Fixed source epoch, prefix maps, explicit options and complete native
toolchain/provenance records make these builds reproducible as practically tested.

Cache keys include source/library versions and hashes, target, recipe, release
key, compiler/linker/assembler and native toolchain/SDK/runner-image records.
Only exact keys restore; cached contents and staging inputs are SHA-256 verified.
FFmpeg or recipe changes invalidate the cache. Packaging/test-only edits do not.
Windows ARM64 [run 35566182756](https://github.com/tlolabs/encap/actions/runs/35566182756/job/106228349067)
confirmed exact cache reuse after test-only changes. A local warm-cache check
took 0.373 seconds. Explicit clean runs bypass restore/save and rebuild both
programs; reusable source downloads are checksum-checked and signatures verified
anew. The final six-target run used this clean path.

## Ownership and remaining limits

Normal macOS builds and Windows/Linux packagers use the same EnCAP source recipe
and staging function. Release discovery accepts only the adjacent FFmpeg/ffprobe
pair matching the expected version, target, schema and SHA-256 manifest. macOS
metadata lives in `Contents/Resources/FFmpeg`; portable metadata lives beside the
engine in `ffmpeg-runtime`. No production PATH or environment fallback exists.

Third-party prebuilt FFmpeg acquisition, AVID Core runtime assets, sibling Core
checkout requirements and the managed-runtime feature split have been removed.
Core remains the pinned Rust Video dependency. Source-built external libraries
are x264, x265, LAME and zlib; GPL support is enabled, nonfree support disabled,
and corresponding sources/licenses ship with the package. macOS retains
AudioToolbox/VideoToolbox support. Signing/notarization did not block testing.

**No remaining FFmpeg-specific blocker is known.** The current Intel DMG remains
blocked by the separate project-save performance gate, and manual UI walkthroughs
were not completed. No production release or new Core API migration occurred.
