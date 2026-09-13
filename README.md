# EnCap — Encoder with Chapter Assembly Protocol

[![Latest release](https://img.shields.io/github/v/release/tlolabs/encap?display_name=tag)](https://github.com/tlolabs/encap/releases/latest)
[![Native builds](https://github.com/tlolabs/encap/actions/workflows/build-platforms.yml/badge.svg)](https://github.com/tlolabs/encap/actions/workflows/build-platforms.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

EnCap 2.0 turns a naturally ordered folder of recordings into audio, transcript,
and social-video deliverables in one portable project. Its Rust engine has native
interfaces for macOS, Windows, and Linux. The original Python application remains in
[`legacy-python/`](legacy-python/) for comparison until the rewrite has been
manually accepted.

## Architecture

EnCap has three peer application modes over one shared project format:

- **Audio** imports and validates recordings, normalizes mismatched
  sources, maintains chapter and episode metadata, and exports MP3 or AAC/M4A.
- **Transcript** discovers local providers, manages optional Whisper models,
  transcribes without uploading audio, edits timestamped segments and speakers,
  and exports TXT or SRT. Word timestamps are optional and persist in the project.
- **Video** selects and independently reorders chapters, previews the continuous
  timeline, and exports one H.264 or HEVC MP4 using the original source audio and
  chapter/main artwork. Social presets, custom dimensions/FPS, flips, preview
  quality, and automatic/hardware/software encoding are included.

The modes are separate Rust crates—`encap-audio`, `encap-transcript`, and
`encap-video`—so no workflow owns another. All use `encap-core` for the project model
and persistence and `encap-ffmpeg` for controlled subprocess execution. A small
JSON process boundary in `encap-engine` keeps the native SwiftUI, WinUI 3, and
GTK 4/libadwaita applications thin and crash-isolated. See
[`docs/architecture.md`](docs/architecture.md).
Video's timing, encoder selection, and composition rules are documented in
[`docs/video-mode.md`](docs/video-mode.md).

## Download

**[Download the latest EnCap release](https://github.com/tlolabs/encap/releases/latest)**

| Platform | Release file | Baseline |
| --- | --- | --- |
| Apple silicon Mac | `EnCap-<version>-macos-arm64.dmg` | macOS 13 |
| Intel Mac | `EnCap-<version>-macos-intel.dmg` | macOS 13 |
| Windows x64 | `EnCap-<version>-windows-x64.zip` | Windows 10 1809 |
| Windows ARM64 | `EnCap-<version>-windows-arm64.zip` | Windows 10 1809 |
| Linux x64 | `EnCap-<version>-linux-x64.tar.gz` | GTK 4 + libadwaita 1 |

Every package contains its own tested `ffmpeg` and `ffprobe`; users do not need
to install media tools. macOS builds are currently ad-hoc signed while Developer
ID signing and notarization are being prepared. If macOS blocks a first launch,
Control-click EnCap, choose **Open**, and confirm once.

## Features

- Portable, versioned `.encap` project documents with embedded source media and
  artwork.
- Defensive project loading with traversal, link, duplicate-path, archive-size,
  and compression-ratio checks.
- Atomic project, audio, and transcript output replacement.
- Lightweight edit-state autosave and crash recovery without repeatedly copying
  embedded source media.
- WAV and AIFF inspection, natural filename sorting, and FFmpeg normalization.
- MP3 through libmp3lame and AAC/M4A through FFmpeg or Apple AudioToolbox.
- Episode metadata, artwork, chapter titles, links, and source-boundary timing.
- Apple on-device Speech on macOS and verified local `whisper.cpp` models on all
  supported platforms.
- Editable transcript text, timestamps, and speaker names with TXT/SRT export.
- Hard-cut multi-chapter MP4 timelines with AVID's blurred full-canvas background,
  sharp centered artwork, horizontal/vertical flips, and capability-tested encoders.
- Responsive background operations with cancellation and owned-child cleanup.
- Native menus, dialogs, appearance, scaling, accessibility semantics, and file
  opening on each desktop platform.
- Local rotating diagnostics with no telemetry, analytics, or automatic upload.

## Local transcription and privacy

EnCap does not bundle model weights. Apple On-Device transcription requests
system-managed recognition and requires on-device processing. Optional Whisper
models are downloaded only when selected in **Manage Models**, stored in the
platform application-data directory, streamed to a temporary file, verified
against a pinned SHA-256 digest, and installed atomically. Inference has no
network fallback.

The model manager currently offers Base English, Small, and Large v3 Turbo.
Removing a model deletes only EnCap's catalog-owned file. On supported Macs,
EnCap first reuses a compatible Superwhisper model after size and full SHA-256
verification. Apple-silicon Macs running macOS 14 or newer can also reuse a
structurally validated local WhisperKit package installed by Whisper
Transcription (MacWhisper); the helper is forced into offline mode and copies
only small tokenizer metadata into a private temporary directory. While a
compatible shared model is available, duplicate EnCap model downloads are
disabled.

## Build from source

The shared engine needs the Rust toolchain pinned by `rust-toolchain.toml`.
Platform prerequisites are Xcode 26 on macOS, Visual Studio 2022 with the
Windows App SDK workload on Windows, or GTK 4/libadwaita/json-glib development
packages plus Meson on Linux. First-time packaging also needs network access to
download hash-pinned open-source dependencies.

On macOS, the project run action and the shell use the same entrypoint:

```bash
./script/build_and_run.sh
```

Useful modes are `--verify`, `--debug`, `--logs`, `--telemetry`, and
`--package`. The script builds the release Rust engine, native SwiftUI app,
static FFmpeg/ffprobe, local transcription helpers, and an application bundle
at `dist/EnCap.app`.

Shared checks:

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
python3 -m unittest discover -s tests
```

See [`docs/development.md`](docs/development.md) for platform builds, release
artifacts, and the engine protocol. The project format is specified in
[`docs/project-format.md`](docs/project-format.md).

## Run the preserved Python reference

The Python implementation is intentionally not a release dependency of the
native rewrite. To run it for behavioral comparison:

```bash
python3 -m venv .venv-legacy
.venv-legacy/bin/python -m pip install -e .
.venv-legacy/bin/encap-gui
```

Its source, packaging files, and instructions remain intact under
[`legacy-python/`](legacy-python/). Legacy UI captures are in
[`docs/legacy-ui/`](docs/legacy-ui/).

## Release process

Version the workspace in `Cargo.toml`, commit the release, and tag the matching
version (for example, version `2.0.0` uses `v2.0.0`). The native workflow builds
and tests macOS Intel/ARM64, Windows x64/ARM64, and Linux x64 packages. Tagged
runs additionally publish checksummed release assets and signed update metadata.
macOS uses Sparkle with architecture-specific appcasts. Developer ID,
notarization, and the private update-signing key remain credential-gated release
steps and are never stored in the repository.

EnCap 2.0 development builds use the normal CI workflow. The stable `v2.0.0` tag
and release must not be created until the integrated application is manually approved.

## About and license

EnCap supports practical student media workflows. It is shared publicly for
transparency, reciprocity, and educational use, without warranty or guaranteed
support. Bug reports and pull requests are welcome.

GNU General Public License v3.0. See [`LICENSE`](LICENSE).
