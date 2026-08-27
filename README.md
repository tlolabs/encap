# EnCap — Encoder with Chapter Assembly Protocol

[![Latest release](https://img.shields.io/github/v/release/tlolabs/encap?display_name=tag)](https://github.com/tlolabs/encap/releases/latest)
[![Build platform apps](https://github.com/tlolabs/encap/actions/workflows/build-platforms.yml/badge.svg)](https://github.com/tlolabs/encap/actions/workflows/build-platforms.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

EnCap assembles a folder of recordings into a finished, chaptered audio file.
It can normalize mismatched sources, encode MP3 or AAC, attach episode metadata
and artwork, create and edit transcripts, and export a reusable project.

## Download

**[Download the latest EnCap release](https://github.com/tlolabs/encap/releases/latest)**

Choose the file for your computer:

| Platform | Release file |
| --- | --- |
| Apple silicon Mac (M1 or newer) | `EnCap-<version>-macos-arm64.dmg` |
| Intel Mac | `EnCap-<version>-macos-intel.dmg` |
| Windows x64 | `EnCap-<version>-windows-x64.zip` |
| Linux x64 | `EnCap-<version>-linux-x64.tar.gz` |

On macOS, open the DMG and copy EnCap to **Applications**. Current builds are
ad-hoc signed while Developer ID signing and notarization are being prepared.
If macOS blocks the first launch, Control-click EnCap, choose **Open**, and
confirm once.

## Features

- Imports and naturally sorts a folder of WAV recordings.
- Validates source formats and can convert mismatched files with FFmpeg.
- Builds RIFF `cue ` markers and `LIST/adtl` chapter labels at source boundaries.
- Edits podcast title, episode title, summary, artwork, chapter titles, links,
  timing, and chapter images in a native desktop workspace.
- Encodes with bundled LAME MP3, FFmpeg MP3/AAC, or Apple AudioToolbox AAC.
- Supports stereo and mono output with codec-appropriate bitrate choices.
- Transcribes on macOS with Apple's on-device Speech engine.
- Downloads optional Whisper models on demand and runs them locally with
  `whisper.cpp`.
- Edits transcript segments, speaker names, and free-form transcript text.
- Exports audio, plain-text transcripts, SRT captions, or all deliverables
  together.
- Saves portable EnCap project files with their referenced media.
- Follows the macOS light/dark appearance, including live appearance changes.
- Checks GitHub Releases for signed automatic updates.
- Provides both a desktop app and a command-line interface.

## Local transcription and privacy

EnCap does not include transcription model weights in the application bundle.
On macOS, **Apple On-Device** uses speech assets managed by the operating system
and sets `requiresOnDeviceRecognition`, preventing the recognition request from
sending audio over the network.

Optional Whisper models are available from **Transcription > Manage Models**.
Downloads are stored outside the app in the user's application-data directory,
verified with SHA-256, and can be selected or removed from the same window.
After a model is installed, Whisper transcription works offline. The packaged
app includes only the lightweight `whisper.cpp` runtime, not model weights.

On macOS, EnCap avoids duplicate multi-gigabyte downloads when another supported
transcription app already has a usable Large V3 model. It checks for a verified
Superwhisper `ggml-large-v3.bin` first, then for installed Apple-silicon macOS 14+
WhisperKit models managed by Whisper Transcription (MacWhisper). Shared model
weights are read in place and are never copied, removed, or updated by EnCap;
small tokenizer metadata is staged only in a temporary working directory. If
neither shared source is usable, EnCap falls back to its own model manager.

## Automatic updates

Packaged EnCap builds use the latest GitHub Release as the update source. macOS
uses Sparkle 2 with architecture-specific appcasts; Windows and Linux use an
Ed25519-signed manifest and a bundled replacement helper. Release assets are
also SHA-256 verified before installation.

Use **Help > Check for Updates…** to check manually. Source checkouts never
overwrite themselves.

## Install from source

EnCap requires Python 3.11 or newer. The desktop interface uses PySide6/Qt 6.

```bash
git clone https://github.com/tlolabs/encap.git
cd encap
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

Launch the desktop app:

```bash
encap-gui
```

Run the CLI:

```bash
encap /path/to/source_dir --output-dir /path/to/output_dir --output-name stitched.wav
```

Use `--write-report` to emit a troubleshooting report next to the output WAV.

## Maintainer release process

One-time update-signing setup:

```bash
python3 scripts/configure_update_keys.py --configure-github
```

Back up `.encap-update-private-key` somewhere secure and never commit it. The
command stores the private key as the `ENCAP_UPDATE_PRIVATE_KEY` GitHub Actions
secret and the public key as the `ENCAP_UPDATE_PUBLIC_KEY` repository variable.

To publish a release:

1. Update `src/encap/version.py`.
2. Commit and push the source changes.
3. Push the exact matching tag: version `0.2.0` uses tag `v0.2.0`.

The tagged GitHub Actions build tests and packages Apple-silicon macOS, Intel
macOS, Windows x64, and Linux x64. It publishes the installers, signed
`latest.json`, and both Sparkle appcasts to the GitHub Release.

## About

This tool was built to support my students' media workflow. I'm an instructor
first, and I write code when it solves a practical problem in my classes or
media environment.

The project is shared publicly under GPLv3 for transparency, reciprocity, and
educational use. The software is provided as-is, without warranty or guaranteed
support. Bug reports and pull requests are welcome, but response times may vary
during the academic term.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
