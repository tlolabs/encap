# Licensing and provenance audit

Status: **license change deferred** (2026-09-24). The project currently declares
`GPL-3.0-only` in Cargo metadata and distributes the GPL v3 text in `LICENSE`.
Those declarations remain in force. This document records the review required
before adopting `GPL-3.0-or-later`; it is not a new license grant.

## Original work and provenance

The audited branch has 176 tracked files. Its ancestor history attributes
the original source, build scripts, documentation, fixtures, and application
icon commit to Tom Lothian. Copilot-authored checkpoint commits exist on
other refs but are not ancestors of this branch. The SVG icon source and
raster derivatives were introduced together in commit `1a3d34c`, but that
commit does not establish whether the artwork was wholly original or
licensed from a third party. Thomas must confirm its provenance before the
icon can be declared `GPL-3.0-or-later`.

The repository contains no tracked vendored FFmpeg, whisper.cpp, Sparkle, or
model binary. Build caches under `.build-tools/`, `.sparkle/`, and
`.whisper-cpp/` are ignored local inputs, not repository content. The
tracked sample fixtures are small text data files; test code also generates
synthetic audio and video. No tracked fonts, audio, video, screenshots, or
external artwork were found.

## Redistribution review

| Component | Incorporation and license | Result |
| --- | --- | --- |
| AVID Core v0.3.0 | Statically linked Rust source; `GPL-3.0-only` | Compatible with GPL v3, but the combined executable cannot be offered under a later GPL version unless AVID Core itself permits it. |
| FFmpeg 9.0.2, x264, x265, LAME, zlib | Separate bundled FFmpeg/ffprobe processes built from source; GPL-2.0-or-later, LGPL-2.0-or-later, and Zlib licenses | GPL v3 compatible as configured; corresponding source and notices must accompany binaries. |
| whisper.cpp and Sparkle | Bundled runtime/framework; MIT | GPL v3 compatible; preserve upstream notices. |
| WhisperKit/Argmax, Swift Argument Parser, transitive Swift packages | Build-time resolved source; chiefly MIT/Apache-2.0 as recorded upstream | Verify the exact resolved dependency graph and included notices for every release. |
| Rust Cargo.lock packages | Locked source dependencies with various licenses | Machine inventory is required; any unknown license needs release review, not an automatic assertion of compatibility. |
| Windows App SDK and platform frameworks | Windows/macOS/Linux platform components | Review redistribution terms for packaged Windows App SDK and system-library classification before claiming all signed-package components satisfy SignPath's OSS terms. |
| Optional Whisper model weights | Downloaded only at user request, not bundled | Model license and service terms require separate review; do not claim the models are GPL. |

The GPL compatibility distinction follows the [FSF license compatibility
FAQ](https://www.gnu.org/licenses/gpl-faq.en.html). AVID Core's current
`GPL-3.0-only` grant is the immediate material complication. Its license is
preserved in `runtime/AVID_CORE_LICENSE.txt` and described in
`THIRD_PARTY_NOTICES.md`.

## Decision required

Thomas should confirm the icon source/provenance and decide whether AVID Core
can itself be licensed
`GPL-3.0-or-later` after a separate provenance audit. Only then change the
project SPDX declaration, README, metadata, and original-work notices
together. Do not alter AVID Core's or other upstream notices by implication.
