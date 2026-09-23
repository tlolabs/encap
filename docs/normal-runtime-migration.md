# EnCAP migration to the simplified AVID Core architecture

## Scope and reference

Initial read-only inspection covered EnCAP `cb096f3`, ATIV `bc43ed0`, and AVID Core
`3fb6880`. ATIV had two existing documentation edits; they were left untouched.
The Core source checkout was not changed. No shared-Core defect was found.

The normal EnCAP application uses AVID Core **0.3.0**, pinned to the same immutable
commit as ATIV: `3fb68807bc7c350359e1634b32af477ea3042c16`. Cargo.lock and the
normal engine's build-info command enforce and expose this identity.

EnCAP owns its FFmpeg/ffprobe **9.0.2** source runtime. The official source/version,
signature verification, dependency record and provision/stage/finish/validate
methodology match ATIV. The documented profile extension preserves EnCAP's HEVC,
MP3, Apple AAC and broader built-in media functionality; the full binaries are
therefore not identical to ATIV's H.264/AAC-only profile.

## Production path

The native apps still call the ordinary encap-engine. Core validates the one
host-owned packaged pair for Audio, Transcript and Video. Core owns Video probing,
capabilities, selection/timeline behavior and rendering; EnCAP owns audio export,
transcription providers, native audio editing/parsing, project archives and UI.
There are no Core runtime-release downloads, Recipe qualification gates, sibling
checkout requirements, alternate Cargo features or separate qualification app.
The remaining package test harness runs the actual normal release engine.
The obsolete independent builder and legacy downloader-named entrypoint are removed.

Project schemas 1/2, unknown fields, chapter/source mapping, selection order,
artwork, export settings, native playback and user-visible mode behavior remain.
One cancellation token reaches pair validation and all media operations; owned
Audio/Transcript children are reaped on cancellation or monitoring failure.

## Verification

Local macOS ARM64 results (2026-09-23):

- Default and all-feature workspace tests pass, including schema-1/2 archive
  compatibility, unknown fields, Audio edits, Transcript data and Video state.
- All-target/all-feature Clippy with warnings denied and formatting pass.
- Eight source-builder tests and two production-ownership tests pass.
- The normal app built and launched. All five packaged media contracts pass:
  MP3/AAC Audio export, real packaged Whisper transcription, Video H.264/HEVC,
  probing, ordered chapters/artwork/flips, corrupt-input/output preservation,
  real FFmpeg cancellation, and save/reopen/recovery round-trips.
- Normal package relocation and missing/damaged/mismatched provenance tests pass
  with usable fallback tools on PATH. Release overrides are ignored as intended.
- Native Swift tests: 26 pass, including playback and mode/model compatibility.
- Core's five existing real-media tests and both installed-runtime replacement,
  rollback, cancellation and cleanup tests pass against this exact FFmpeg pair.
- The normal ARM64 DMG was created and the UI opened the saved verification project;
  Audio showed its source/artwork/settings and Transcript displayed the real result.
- An additional default-suite run during concurrent package compilation exceeded
  the existing 250 ms save threshold (642 ms after reopening). The isolated full
  default suite then passed, as did both packaged runs. No threshold was relaxed.
- Existing 256 MiB release-mode save benchmark and portable C chapter tests pass.

The first native CI run passed general engine checks and built macOS ARM64
FFmpeg, then exposed a fresh-checkout staging-directory omission and an Intel
Homebrew Python symlink conflict. These packaging issues were corrected; the
runner's existing Python is used, and staging explicitly creates its parent.
The next run exposed an overly narrow Linux linkage allowlist: the broader
EnCAP codec profile links glibc's system libmvec in addition to libm. Recipe 2
allows that system library, retains rejection of dynamic codec dependencies,
and records the C++ compiler version on every target. No upstream/Core patch
or change to media behavior is required.
The six-target native workflow verifies the committed migration. Earlier
0.2.1 runtime results are historical and do not qualify this recipe. Until the
new matrix completes, Windows/Linux and macOS Intel package acceptance remain
release gates. Interactive testing on minimum supported OS versions, Developer
ID/notarization and credentialed release publication are not claimed here.
