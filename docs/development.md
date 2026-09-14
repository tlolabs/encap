# Native development

## Workspace ownership

The Rust workspace is intentionally layered:

- `encap-core`: typed project model, validation, archive persistence,
  transcript rendering, and safe file replacement.
- `encap-ffmpeg`: bundled-tool discovery, validation, subprocess execution,
  logging, and cancellation.
- `encap-audio`: folder ingest, normalization, chapter editing, metadata,
  and MP3/AAC export.
- `encap-transcript`: local provider discovery, model lifecycle, Apple Speech,
  and whisper.cpp execution.
- `encap-video`: project preflight, selected chapter/source mapping, and host diagnostics
  over `avid-core`, which owns Video presets, settings, graphs, processes, and publication.
- `encap-engine`: a small JSON command boundary consumed by native apps.

The three mode crates are siblings. Do not add dependencies between them. Video
media behavior belongs in `avid-core`; unrelated Audio/Transcript process behavior
remains in `encap-ffmpeg`. Whole-project data and archive persistence stay in `encap-core`.

Check out `tlolabs/avid-core` beside EnCAP as `AVID Core`. The workspace path dependency
and CI use shared revision `0cce6ba838827d0bed540efc98731e74a1014456`. Update it only
after rerunning shared tests and EnCAP compatibility tests; never copy media implementation.

## Engine protocol

Native clients invoke one engine process per operation. Arguments contain only
the command and paths/identifiers; project payloads are JSON temporary files, not
shell fragments. One JSON value is written to stdout. Success exits zero; failure
exits nonzero and writes `{ "error": "plain-language message" }` to stdout while
detailed diagnostics remain in the local rotating log.

Commands are `inspect`, `open`, `save`, `export`, `export-video`, `video-presets`,
`video-capabilities`, `export-transcript`,
`transcribe`, `providers`, `models`, `install-model`, `remove-model`, and
`validate-tools`, plus `save-recovery`, `load-recovery`, and `clear-recovery`
for the crash-safe edit journal. Long-running native tasks keep a handle only to the process
they own. Cancellation terminates that process and the Rust runner terminates
its owned FFmpeg/transcription child, so unrelated system processes are never
targeted.

Recovery records are small JSON snapshots referencing the current session's
media rather than duplicate `.encap` archives. A normal save or confirmed clean
quit clears the record. A crash leaves it in application data; restoration
validates its schema and every referenced audio path, preserves an invalid
record for manual recovery, and never overwrites a known-good project file.

## macOS

```bash
./script/build_and_run.sh --verify
```

This is the canonical build-and-launch path used by the Codex Run action. It
builds the Xcode SwiftUI target for the host architecture, the release Rust
engine, the approved common FFmpeg/ffprobe 9.0.1 artifact, whisper.cpp, Apple
helpers, and Sparkle. It stages `dist/EnCap.app`, validates its tools and bundle,
ad-hoc signs it, launches it, and confirms that the process remains alive.

The deployment target is macOS 13. The CI matrix builds both Intel and Apple
silicon artifacts. Packaging uses `--package` to create an architecture-labeled
DMG.

## Windows

The WinUI 3 application is under `windows/EnCap`. CI publishes self-contained
Windows App SDK builds for `win-x64` and `win-arm64`, copies the matching Rust
engine, hash-pinned static FFmpeg/ffprobe, whisper.cpp runtime, licenses, and
notices into the bundle, validates the packaged tools, then creates a ZIP.

The minimum target is Windows 10 version 1809. Platform compilation requires a
Windows host with Visual Studio 2022, the .NET 8 SDK, and the Windows App SDK
workload.

## Linux

The native GTK 4/libadwaita client is under `linux/EnCap` and builds with Meson.
CI builds the Rust engine, fetches the pinned common Linux FFmpeg artifact,
builds whisper.cpp, stages the application layout, runs
tool validation, and creates an x64 tarball. A development host needs Meson,
Ninja, GTK 4, libadwaita 1, and json-glib headers.

## Verification

Run the shared checks before committing:

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
./script/check_no_python.sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  swift test --package-path macos --scratch-path build/native-swift
```

Cross-platform compilation and package validation run in
`.github/workflows/build-platforms.yml`. Native tests retain schema-1 compatibility
coverage. Tests must not require network access; model downloads are validated
through local streams and catalog metadata tests.

## Dependency and release policy

Runtime media tools are bundled and located relative to the engine/application,
never through a user's shell configuration. Downloaded build inputs and model
weights are pinned to versions or immutable commits and verified with SHA-256.
Keep corresponding license information in `THIRD_PARTY_NOTICES.md`.

Do not commit signing credentials. Tagged CI uses the native `encap-release` tool
with the update private key from repository secrets and emits hashes plus signed
metadata. macOS notarization and
Developer ID signing require external credentials and are intentionally outside
an uncredentialed local build.

## Common media distribution gate

`script/fetch_ffmpeg.sh` records the same immutable upstream platform artifacts as ATIV.
The existing `build_ffmpeg.sh` and `build_ffmpeg_linux.sh` entrypoints now prepare that
one pair in the existing install directory, replacing the previous recipe. The shared
crate bundles nothing. No Video-specific binary directory or runtime fallback exists.
Cache reuse checks both the recipe hash and executable hashes.

Before launch/package, macOS runs the three `encap-engine` media contract tests and
three shared real-media tests against the staged pair. Windows x64 and Linux CI use
the same gates; Windows ARM64 still needs native execution. The tests cover codec/filter
requirements plus MP3/AAC/AudioToolbox, Transcript PCM conversion, and Video rendering.
Platform capability advertisement alone is not approval for a release artifact.

Run the explicit tests with the actual distribution paths:

```sh
ENCAP_FFMPEG="$PWD/dist/EnCap.app/Contents/MacOS/ffmpeg" \
ENCAP_FFPROBE="$PWD/dist/EnCap.app/Contents/MacOS/ffprobe" \
ENCAP_TEST_ENGINE="$PWD/dist/EnCap.app/Contents/MacOS/encap-engine" \
cargo test --locked -p encap-engine --test media_contract -- --ignored
```

`ENCAP_TEST_ENGINE` and optional `ENCAP_REFERENCE_ENGINE` are test-harness inputs only.
See [migration evidence and remaining gates](migration-avid-core.md).
