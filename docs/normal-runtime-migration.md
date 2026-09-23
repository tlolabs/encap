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

## Native matrix

The final implementation is `b6452ebae3481b3f68bd6ead8bf37ac93f6cc9f3` with recipe
2 (`d8c5f43d9f00ba09b9eea69e0e49366057d8346b85261a856ca64dcd0d35f7f8`).
Subsequent commits improve CI ordering and verified-payload handoff, without
changing application or runtime code. Historical 0.2.1/recipe-1 results are not
used to qualify this recipe.

| Native target | Normal app and packaged media | Complete job |
| --- | --- | --- |
| macOS ARM64 | Pass: all three modes, strict discovery, native tests, DMG | [Pass](https://github.com/tlolabs/encap/actions/runs/35898348711/job/107307857378) |
| macOS Intel | Pass: all five packaged media contracts and discovery/rejection | [Blocked by save performance](https://github.com/tlolabs/encap/actions/runs/35898348711/job/107307857220) |
| Linux x64 | Pass: all three modes, normal GTK package, Btrfs save contract | [Pass](https://github.com/tlolabs/encap/actions/runs/35897372702/job/107304555837) |
| Linux ARM64 | Pass: all three modes, normal GTK package, Btrfs save contract | [Pass](https://github.com/tlolabs/encap/actions/runs/35897372702/job/107304555923) |
| Windows x64 | Pass: all three modes, native WinUI portable package | [Pass](https://github.com/tlolabs/encap/actions/runs/35897372702/job/107304555958) |
| Windows ARM64 | Pass: all three modes, native WinUI portable package | [Pass](https://github.com/tlolabs/encap/actions/runs/35897372702/job/107304555982) |

Native CI used macOS 15 ARM64/Intel, Windows 2025 x64/Windows 11 ARM64 runners,
and Ubuntu 24.04 x64/ARM64. The normal application media tests pass on all six
targets; five complete package jobs pass. The overall matrix is red because of
the Intel save-performance gate. The [native matrix record](verification/core-030-native-matrix.json)
preserves exact run/commit and step outcomes.

General native engine checks pass. The local [machine-readable ARM64 record](verification/core-030-macos-arm64.json)
records the mounted DMG identity, exact executable hashes and additional Core
real-media/lifecycle tests. CI package checks exercise the ordinary release
engine built into each native application, not a qualification application.

## Remaining release blockers and limits

- Intel macOS fails the unchanged `mode_switch_save_latency_does_not_scale_with_existing_media`
  gate. In the final complete Rust suite, a 257 MiB project save after reopening
  took 271.44 ms against 250 ms; earlier runs also exceeded the limit. Archive
  implementation and this test were not changed by the migration. This is a
  measured release blocker, not evidence of media or project-format failure;
  a pre-migration baseline on the same runner was not established. The threshold
  remains required. The Intel native app/media tests passed before this gate,
  but the gate stopped DMG creation and later Swift checks on that runner.
- Interactive acceptance on minimum supported OS versions and a complete manual
  loaded-Video UI pass remain unverified. Automated Video operations pass.
- Developer ID signing/notarization and credentialed release publication were
  not performed. CI/local package checks do not substitute for those release steps.

No AVID Core change or EnCAP-specific Core workaround was required. AVID Core
and ATIV source checkouts were left untouched. The branch is pushed; no release
was published.
