# Native development

## Git commit policy

Create unsigned Git commits. Cryptographic commit signatures are not required
for maintainers or contributors. Disable automatic commit signing for each clone:

```sh
git config --local commit.gpgsign false
git config --local tag.gpgsign false
```

Do not pass `git commit -S`. A DCO `Signed-off-by:` trailer added with
`git commit -s` is plain commit-message text and remains required wherever the
contribution policy calls for it.

The unsigned-history migration preserves existing commit messages (including
DCO trailers), authors, committers, timestamps, file trees, and merge topology.
Removing signatures changes commit IDs and descendant IDs; local branches and
tags now point to the equivalent unsigned history. Original signed objects and
an old-to-new commit map are retained locally under
`.git/unsigned-history-backups/` in a verified Git bundle and JSON files.
The backup is local and is not included in a clone.

If a published branch still contains signed commits, first preserve a verified
backup and old-to-new commit map. Recreate those commits without signatures while
preserving their messages, DCO trailers, authors, dates, file trees and topology;
then update that branch using `git push --force-with-lease`. Update affected tags
only after checking their targets. Existing clones must realign with the new
commit IDs; avoid merging the old signed history back into rewritten branches.

Release tags are annotated and must match the Cargo version and checked-out
commit; they do not need a Git signature. Application code signing,
notarization, authenticated update metadata, and upstream source verification
retain their separate requirements.

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

Cargo consumes AVID Core `v0.3.0` from Git, pinned to immutable revision
`25d19098a22936638b0e2a70616083d929fe409c`. No sibling source checkout is
required. EnCAP acquires and packages the matched, checksum-pinned Core runtime.
The exact Core version, revision and Cargo source are available from `encap-engine build-info`.


## Engine protocol

Native clients invoke one engine process per operation. Arguments contain only
the command and paths/identifiers; project payloads are JSON temporary files, not
shell fragments. One JSON value is written to stdout. Success exits zero; failure
exits nonzero and writes `{ "error": "plain-language message" }` to stdout while
detailed diagnostics remain in the local rotating log.

Commands are `build-info`, `inspect`, `open`, `save`, `export`, `export-video`, `video-presets`,
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
engine, the Core-built FFmpeg/ffprobe 9.0.1 pair, whisper.cpp, Apple
helpers, and Sparkle. It stages `dist/EnCap.app`, validates its tools and bundle,
ad-hoc signs it, launches it, and confirms that the process remains alive.

The local Sparkle verification key belongs in `.encap-update-public-key` at the
repository root (ignored by Git). CI writes the same file from
`ENCAP_UPDATE_PUBLIC_KEY`. The old `src/encap` Python package path is no longer used.

The deployment target is macOS 13. The CI matrix builds both Intel and Apple
silicon artifacts. Packaging uses `--package` to create an architecture-labeled
ZIP.

To cross-build Intel on Apple silicon, install the `x86_64-apple-darwin`
Rust target and Rosetta, and provide the pinned Core Intel runtime artifact. The build verifies its provenance and checksums:

```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
ENCAP_BUILD_ARCH=x86_64 \
./script/build_and_run.sh --package
```

The cross-built app is staged at `dist/intel/EnCap.app`; its tests run under
Rosetta. Physical Intel hardware testing remains a separate validation step.
WhisperKit is Apple-silicon-only; Intel packages retain whisper.cpp and the
Apple Speech helper.

Sign the tested Intel bundle and notarize using a saved Keychain profile:

```bash
ENCAP_APP_BUNDLE="$PWD/dist/intel/EnCap.app" \
ENCAP_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
ENCAP_NOTARY_PROFILE=EnCAP \
./script/sign_macos_release.sh
```

The signing script derives the architecture from the app executable, signs nested
helpers, refreshes the signed-copy hashes, notarizes and staples the app, verifies
Gatekeeper acceptance, and recreates the ZIP containing the stapled app.

## Shared Windows/Linux and internal macOS frontend

Use the pinned SDK in `global.json` (.NET 10.0.401) and Avalonia 12.1.3.
There is one AXAML implementation and application layer under `desktop/`.
Windows needs the Visual Studio C++ workload and Windows SDK for the SMTC adapter.
Linux needs CMake, a C compiler, GLib/GIO and the X11/fontconfig runtime libraries.
GTK, GStreamer, WinUI and Meson are no longer application dependencies.

Run the shared tests and dependency gate:

```sh
dotnet run --project desktop/EnCap.Tests -- tests/fixtures/chapter-times.tsv
python3 script/check_desktop_dependencies.py
python3 script/test_desktop_distribution.py
```

`script/build_desktop.py --rid <win-x64|win-arm64|linux-x64|linux-arm64|osx-arm64>
--tools <verified-helper-directory>` builds on the matching native host. The helper
directory must contain the Rust engine, verified FFmpeg/ffprobe metadata and
Whisper, plus the updater on production platforms. The workflow stages these
using the existing Core acquisition/verification path before invoking the script.
Windows produces a self-contained portable ZIP; Linux produces an AppImage.

On Apple Silicon, `./script/build_and_run.sh --avalonia-reference` builds and
launches `dist/internal/EnCap-Avalonia-Reference.app` using helpers already staged
by the normal native build. Set `DOTNET` if the SDK executable is elsewhere.
The bundle is ad-hoc signed locally; it needs no Developer ID or notarization.
The default Run action still builds the native SwiftUI application.

See [the parity and validation report](avalonia-migration.md) for exact evidence
and remaining platform checks. Old frontend sources are removed, not selectable.

## Recording list behavior

The native macOS client retains its recording-row controls. Avalonia uses a
shared recording list with playback buttons and a keyboard-operable seek slider. Each client owns
one recording player and stops it before starting a different recording. The
source column initially fits the shortest filename plus control/inset space,
and its divider remains adjustable.

The metadata line places a 12-point, one-sided waveform between the file type
and duration. It always uses channel 1, including mono, stereo, and multichannel
recordings. Selected thumbnails inherit the row's text color at full contrast;
unselected ones use reduced opacity, with no animation or shape change.

`encap-engine waveform -- <path>` returns `{ "channel": 1, "peaks": [...] }`
with 64 normalized amplitude values. The sampler reads short windows spread
across the file: at most 256 frames and 32 KiB per bin (2 MiB total sample I/O),
plus bounded chunk headers. It supports integer/float WAV and uncompressed
AIFF/AIFC variants. It skips metadata by seeking, validates chunk boundaries,
and neither decodes the full track nor downmixes channels. This is an approximate
silhouette for triage, not an editing waveform or a loudness comparison.

Native clients defer work by 150 ms, favor visible rows, and run one background
job at a time. Results are cached in memory; the nominal cache cap is 512 entries
(macOS retains visible entries). Leaving the view cancels or skips pending work.
Resizing and selection redraw the cached values without rereading audio. Missing,
unsupported, or still-loading previews leave the reserved space blank; actual
silence produces a thin baseline. Waveforms never enter the saved project.
The core tests cover first-channel isolation, sample encodings, AIFF offsets,
truncation, and a 2 GB sparse-file I/O budget. A local warm-filesystem check of
17 imported recordings took 98 ms total (4 ms median) including CLI startup;
network/removable storage can take longer, so generation stays asynchronous.

Double-click a recording or choose **Play** from its context menu to play at 1×.
With the recording list focused, **Space** toggles the selected recording and
**K** pauses without losing the playhead. **L/J** play forward/backward at 1×;
repeated presses in the same direction double the speed up to 32×. The opposite
key starts at 1× in that direction. Hold **K** and **J/L** for ½× playback, releasing
the chord to pause. Key auto-repeat does not accelerate the shuttle. These are
the [Final Cut Pro playback conventions](https://support.apple.com/guide/final-cut-pro/play-media-ver90ba4ef0/mac)
for continuous audio; frame stepping is not exposed in the audio list.
Multiple selection plays the first selected recording in list order. Keyboard
shortcuts stay in the source list so metadata text entry retains normal typing.

macOS publishes a MediaPlayer Now Playing session; Windows publishes System Media
Transport Controls; Linux publishes an MPRIS session on the desktop session bus.
After starting a preview, hardware/system Play, Pause, Stop, Previous, Next, and
position controls operate on that recording session. System volume keys retain
their usual OS behavior. A system Stop resets the position; K and Pause retain it.
Playback-rate support depends on the native decoder. A rejected rate pauses the
preview and reports the limitation in the status/error or recording tooltip.
Media session routing depends on the desktop and which application it selects
as the current media player. Linux MPRIS works without X11 key grabs on Wayland.

`SourcePlaybackTests` verifies actual macOS WAV pause/resume and reverse playback.
Shared .NET tests consume `tests/fixtures/source-shuttle.tsv`. The optional real
engine test arguments add import/save/recovery/export and native audio-device
checks. `script/test_media_session.py` exercises actual MPRIS commands, metadata,
seek and busy gating on a private D-Bus session; CI runs it on Linux.

Right-click a row or the empty list area to add WAV/AIFF files. Delete/Backspace
or the context menu offers removal of the selected imports and their chapters.
Original files stay on disk. Remaining source references, numbered chapter
names, timeline positions, transcript timestamps, and video selections adjust.
Windows and Linux submit `edit-audio <project-payload> <edits-json>` to the
shared engine; the edits document contains `add_files` and/or `remove_files`
arrays. Adding duplicates is a no-op, and an invalid addition rejects the batch.

Native UI release checks on each platform should cover: multi-selection,
right-click on selected/unselected rows and empty space, cancelling and confirming
removal, adding several files after deleting all tracks, resizing narrow/wide,
hover and keyboard focus, switching playback rapidly, pause/resume, end of file,
unavailable decoders, and save/reopen with the original source files intact.

## Episode editor parity

macOS, Windows, and Linux expose Original, Chapter #, Time, and Custom naming
beside the chapter editor. Selecting a style saves a local preference for new
imports; Apply replaces current titles explicitly. Typing in a chapter title
selects Custom. Adding recordings applies the preference only to new chapters,
so earlier edits remain intact. Opening or recovering a project preserves its
saved titles.

Time reads `MMddyyyyHHmmss` from the original filename, uses the recorder's wall
clock without time-zone conversion, and rounds seconds to the nearest minute
(30 seconds rounds up). It formats names such as `6:18 AM`, including noon and
midnight rollover. Unrecognized or invalid timestamps retain the original name.
Archived media uses the preserved display name because internal archive paths
may have numeric prefixes. Chapter # follows displayed order; it never changes
the source references used for playback and export.

All three episode editors reserve an artwork preview to the right of the fields
and let the chapter area use the remaining window height. Avalonia uses editable chapter rows in a scrolling list. Recording previews retain pause/resume
behavior, with state-dependent tooltip text. Application actions and relevant
settings expose native tooltips; system-managed dialogs keep native behavior.

Shared timestamp cases live in `tests/fixtures/chapter-times.tsv`. Both native
Swift and shared .NET tests consume them. The old duplicate C/C# frontend tests
are replaced by the common test executable, retaining the naming and shuttle
assertions. Screen-reader behavior, desktop media routing and drag/drop still
require native Windows/Linux verification before release.

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

To compare full-media compression with first, incremental, and reopened-project
saves using a temporary 256 MiB fixture:

```bash
cargo test --release -p encap-core benchmark_large_project_saves -- --ignored --nocapture
```

The exploratory benchmark reports timings. A separate, non-ignored regression
test runs on all supported platforms:

```bash
cargo test -p encap-engine --test save_protocol -- --nocapture
```

`mode_switch_save_latency_does_not_scale_with_existing_media` measures the complete
JSON-payload/save-process round trip through Audio, Transcript, and Video. It
probes the actual temporary project volume using the engine's staging helper
and logs every measured save, plus the median for 1 MiB versus 257 MiB of
existing media, so regressions are visible in CI output. It covers metadata
edits, audio reordering, the switches following a new-media save, and the first
switches after reopening. No hard millisecond budget is asserted: shared CI
hardware (particularly virtualized/shared Intel macOS runners) showed too much
timing variance release over release for a fixed threshold to be a reliable
pass/fail gate. The test still verifies saved data is correct in every case.

macOS, Windows x64, and Linux package gates run the tests against their bundled
engines. macOS and a dedicated Linux Btrfs CI run set `ENCAP_REQUIRE_CLONING=1`,
which fails the test if it cannot exercise cloning. Linux also runs on the default
runner filesystem to cover fallback behavior. Windows ARM64 persistence tests run on the native ARM64 CI runner; local
cross-compilation alone does not verify execution.
Windows exercises the same logged-but-unasserted timing on clone-capable ReFS
volumes and exercises fallback saves on NTFS. These tests measure persistence
work, not GUI rendering.

## Dependency and release policy

Runtime media tools are bundled and located relative to the engine/application,
never through a user's shell configuration. Downloaded build inputs and model
weights are pinned to versions or immutable commits and verified with SHA-256.
Keep corresponding license information in `THIRD_PARTY_NOTICES.md`.

Do not commit signing credentials. Tagged CI requires the approved six-target qualification ledgers and verified
packages, then generates authenticated update metadata using the build scripts
and update private key from repository secrets. macOS notarization and
Developer ID signing require external credentials and are intentionally outside
an uncredentialed local build.

## Common media distribution gate

AVID Core owns FFmpeg/ffprobe source selection, codec dependencies, compilation,
validation and runtime releases. EnCAP pins the published Core runtime, verifies
it with Core's shared acquisition script, and packages the same matched pair for
Audio, Transcript and Video. EnCAP owns its application package metadata and
application-level tests.
See [Core runtime packaging](ffmpeg-source-runtime.md) for the six-target release
pin, authenticated downloads, cache verification, provenance and licensing.
A sibling Core source checkout is not required. The Video API preserves EnCAP
behavior.

Run all media/discovery checks on the normal packaged release engine:

```sh
bash script/ffmpeg/qualify.sh "$PWD/dist/EnCap.app/Contents/MacOS/encap-engine"
```

This requires the normal packaged Whisper helper and pinned whisper.cpp checkout
for its speech fixture; the harness fetches and verifies a test model separately.
Release discovery ignores FFmpeg overrides and PATH; debug fixture overrides must
specify both absolute tool paths. Application project and file formats are unchanged.
