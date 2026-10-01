# Shared Avalonia presentation migration

Validation date: 2026-10-01. This report distinguishes implementation/build
verification from production release qualification. No release or tag is created
by this migration. The existing six-target application/update qualification
ledgers remain unapproved until their platform-specific verification, upgrade
and acceptance requirements are actually satisfied.

## Architecture and files

Baseline reviewed: `9cb3ffdfaec0a00a57d7c3074395ba5afc8cf83b`.

Before: Windows WinUI 3/C#, Linux GTK 4/libadwaita/C, and native macOS
SwiftUI/AppKit each owned presentation and coordination around the same Rust
`encap-engine` JSON protocol.

After: Windows x64/ARM64, Linux x64/ARM64 and internal macOS ARM64 use exactly
`desktop/EnCap.Desktop` (one AXAML tree, Fluent theme, controls and input routing)
and `desktop/EnCap.Application` (observable models, commands, lifecycle and engine
client). Native macOS remains SwiftUI/AppKit. No Rust project/media/business
implementation was rewritten for Avalonia.

The `IEngineClient`, `IUserDialogs`, `IPlayback`, `IMediaSession` and
`IApplicationUpdates` boundaries keep process, dialog, preview, desktop media and
update behavior below presentation. Native adapters in `desktop/native` provide
miniaudio device playback, Windows SMTC and Linux GIO/MPRIS. Windows portable
installation remains a separate executable in `windows/PortableUpdate`.

Removed: `windows/EnCap`, `windows/EnCap.Tests`, `linux/EnCap`, their WinUI/GTK
framework references, Meson targets, duplicate naming implementation, and legacy
CI/package paths. Source history remains the rollback mechanism. The working
legacy sources were also captured in an ignored local audit archive before
removal; they are not built or shipped.

Added/updated: `desktop/`, root `global.json`, `script/build_desktop.py`, desktop
license/distribution checks, real MPRIS protocol tests, AppImage assembly,
platform CI, architecture/development/updater documentation and notices. The
previous task's pending updater implementation is retained and integrated,
including the native macOS Sparkle changes. The migration does not replace or
reduce the native macOS UI.

Dependencies: Avalonia 12.1.3, .NET 10 (SDK 10.0.401), SkiaSharp 3.119.4,
HarfBuzzSharp 8.3.1.3, MicroCom.Runtime 0.11.6, Tmds.DBus.Protocol 0.94.1 and
miniaudio 0.11.23. All 27 resolved direct/transitive/test NuGet packages, hashes and
notice paths are in `desktop/licenses/inventory.json`; lockfiles and
`script/check_desktop_dependencies.py` enforce the review. The registry audit
reported no known vulnerable packages. Permissive framework/graphics notices,
miniaudio's selected MIT-0 terms and .NET runtime notices are distributed with
packages; Linux retains GLib/GIO as an LGPL system integration dependency.
See `THIRD_PARTY_NOTICES.md`. No paid Avalonia component or recurring service was
introduced or provisioned.

## Functional parity audit

The audit used the previous Windows/Linux source, shared fixtures, documentation
and native macOS/core tests. “Implemented” does not imply native manual acceptance
on every operating system.

| Capability | Shared implementation and evidence |
|---|---|
| Import folder; WAV/WAVE/AIFF/AIF/AIFC | Existing Rust inspect verb; real WAV/AIFF import observed in reference UI; Unicode WAV tested through the real engine and native device |
| Add/remove multiple recordings | Existing atomic `edit-audio` operation, confirmation and original-file retention; shared commands and engine tests |
| Source list, waveform, resize, multi-selection | Shared list, core waveform sampler, splitter; headless binding/first-selected-row checks; visible reference UI inspected |
| Playback and J/K/L | Pause/resume, seek, reverse, doubled rates to 32x, half-speed chord; held-key tracking prevents repeat acceleration; native device tests and shared shuttle fixture |
| OS media controls | SMTC and MPRIS adapters; real MPRIS metadata/transport/seek/busy/shutdown tests on a private bus on macOS; native Linux CI protocol tests also pass; real desktop media-key routing still requires manual acceptance |
| Episode metadata/artwork | Two-way podcast/title/summary bindings and native pickers; keyboard editing and saved-title round-trip tested; artwork observed |
| Chapters | Add/remove, title/link/duration/artwork, timeline recomputation; Original/Numbered/Time/Custom naming; 23 timestamp cases and preserved naming/source-metadata checks |
| Preferences | Windows naming file and Linux `encap/chapter-naming.ini` retained; automatic-update preference retained; reference preferences/recovery isolated |
| Audio export | MP3/AAC, channels/bitrate; real exports passed; format switching now chooses a compatible encoder instead of retaining MP3-only `lame` for AAC |
| Transcription/models | Existing providers/catalog/download/remove/transcribe verbs; editable speaker/text, word-timestamp option, TXT/SRT export; headless routing and real export checks; packaged core speech tests |
| Video | Selection/all/none, order via drag or keyboard-accessible buttons, presets/dimensions/FPS/codec/encoding/bitrate/flips/quality setting, chapter artwork and timeline preview; real MP4 export and cross-chapter preview observed |
| Project persistence | Open/save/save-as, schema/unknown-field round-trip, unchanged Rust archive format; real save/reopen tests |
| Modes/recovery/lifecycle | Save-on-mode-switch, cancel/continue-without-saving choice, debounced recovery, busy gating, close protection, error retention; headless and real-engine tests |
| Progress/cancellation/errors | Indeterminate progress, named status live region, Cancel, asynchronous engine and preview decoding; failure/cancel state tests |
| Keyboard/accessibility | File/mode shortcuts, tab/focusable controls, J/K/L, Space, Delete/Backspace, keyboard sliders, explicit labels, readable row names, native dialogs, scalable shared layout and system/light/dark themes |
| Drag/drop and command line | Project/audio drops, video reordering and initial project argument; reopening the fixture through the initial argument was observed; native drag/drop acceptance remains manual |
| Updates | Existing signed Rust discovery/download/AppImage service; Windows verification-readiness and startup-acknowledgement handshake; installation lock; native Mac Sparkle preserved; no authenticated A-to-B installation claimed |

Layout changes are limited to consolidating the editing workflow: shared playback
buttons/seek controls, three modes, a model panel and shared forms. The Mac
reference has no separate visual theme or layout fork.

## Local verification

Logs are in the ignored `build/avalonia-migration/` directory. Counts below refer
to the final successful runs, not earlier failed attempts.

| Check | Result |
|---|---|
| Rust formatting and clippy (`-D warnings`) | VERIFIED, pass |
| Full Rust workspace | VERIFIED, 69 passed, 0 failed, 6 intentionally ignored in default run |
| Packaged real-media suite | VERIFIED, all 5 ignored media tests run and passed through normal native package assembly |
| 256 MiB save benchmark | VERIFIED, remaining ignored benchmark passed; first save 162.6 ms, subsequent mode saves 9.3–10.2 ms, reopened save 12.7 ms on this host |
| Native Swift ARM64 | VERIFIED, 26 passed, 0 failures |
| Native Swift Intel under Rosetta | VERIFIED, 26 passed, 0 failures; physical Intel hardware NOT VERIFIED |
| Shared presentation/headless checks | VERIFIED, 40 passed on Apple Silicon |
| Preserved naming/shuttle fixtures | VERIFIED, 23 timestamp cases plus naming/metadata round-trip and all shared shuttle cases |
| Real engine/native preview integration | VERIFIED, 15 checks: import, waveform, save/reopen, recovery/clear, TXT/SRT/MP3/AAC/MP4 export, native forward/pause/reverse/half-speed and original retention |
| Python suite | VERIFIED, 23 passed, including distribution and release gates |
| MPRIS protocol/lifecycle | VERIFIED on private macOS-hosted D-Bus: metadata, six transport commands, relative seek, busy gating and five immediate open/close cycles |
| Dependency audit | VERIFIED, 27 reviewed NuGet packages plus pinned miniaudio; registry vulnerability audit clean |
| Actionlint, shell syntax, source policy, updater snapshot, diff whitespace | VERIFIED in local validation |
| Reference bundle/update isolation | VERIFIED, four distribution tests plus runtime update-execution rejection; ad-hoc signature verification passed |

One intermediate MSBuild worker exited unexpectedly; the build and tests were
rerun successfully without build-server reuse. Other discovered failures were
fixed: misplaced JSON attributes, cancellation being treated as confirmation,
playback lifetime/resume/next-chapter state, AAC encoder compatibility, MPRIS
shutdown race, initial artwork, filename underscores, native build-script syntax,
portable-installer typo, Python test discovery executing a CLI at import, and
a save-cache environment-override test racing with parallel Rust tests.

## Builds and packaging

| Target | Local result |
|---|---|
| Windows x64 | VERIFIED self-contained managed publish and portable updater compilation; native SMTC DLL/full ZIP execution NOT VERIFIED locally |
| Windows ARM64 | VERIFIED self-contained managed publish and portable updater compilation; native SMTC DLL/full ZIP execution NOT VERIFIED locally |
| Linux x64 | VERIFIED self-contained managed publish; native Linux adapters/AppImage assembly/execution NOT VERIFIED locally |
| Linux ARM64 | VERIFIED self-contained managed publish; native Linux adapters/AppImage assembly/execution NOT VERIFIED locally |
| Internal macOS ARM64 Avalonia | VERIFIED app/ZIP, native playback library, real engine/media helpers, local launch/AX/screenshot inspection, import/edit/save/reopen/artwork/video preview |
| Production macOS ARM64 SwiftUI | VERIFIED normal native build/test/package, media runtime qualification and ad-hoc bundle validation |
| Production macOS Intel SwiftUI | VERIFIED cross-build/test/package under Rosetta; physical Intel acceptance NOT VERIFIED |

Internal output: `dist/internal/EnCap-Avalonia-Reference.app` and
`EnCap-2.0.5-INTERNAL-Avalonia-Reference-osx-arm64.zip`.
Native outputs: `dist/EnCap-2.0.5-macos-arm64.zip` and
`dist/EnCap-2.0.5-macos-intel.zip`. These local packages are not newly notarized
production releases. Windows/Linux cross-publish directories are build evidence,
not complete distributable packages.

## CI, release isolation and outstanding acceptance

`build-platforms.yml` builds the shared UI and headless tests on both Windows and
both Linux native runners, compiles the native adapters, preserves engine/media
checks, emits portable ZIP/AppImage artifacts, and tests Linux MPRIS and startup.
The ARM64 macOS job additionally builds/tests the identical reference UI and
uploads the distinctly named `EnCap-INTERNAL-Avalonia-Reference-osx-arm64`
artifact. Its failure fails that job. No release job consumes that artifact.

Isolation is structural: separate bundle ID and output directory, INTERNAL ZIP
and CI artifact names, separate recovery/preferences, no Sparkle/update helper or
production update-config in the reference bundle, a runtime Mac prohibition on
update operations, and a configurator that rejects relabelling the reference
bundle as production. Production signing acquisition matches exact artifact
names; promotion accepts only the established six production target filenames,
identities and evidence. Merely renaming a reference ZIP cannot supply its missing
production update identity.

Native CI results (each run identifies its exact source commit; later Windows/Linux fixes do not change the shared presentation or native macOS source):

| Target | Native CI evidence |
|---|---|
| Linux x64 and ARM64 | VERIFIED in [run 36890873483](https://github.com/tlolabs/encap/actions/runs/36890873483): 39 presentation/headless checks per target (the extra Mac-only update guard makes 40 locally), retained fixtures, native adapters, MPRIS protocol, staged startup, AppImage assembly and finished-AppImage startup, media suite and Btrfs persistence. Both artifacts uploaded. |
| Native macOS ARM64 and internal reference | VERIFIED in [run 36876431008](https://github.com/tlolabs/encap/actions/runs/36876431008): native package/tests and separate internal shared UI artifact uploaded. |
| Windows x64 and ARM64 | VERIFIED in [run 36883090923](https://github.com/tlolabs/encap/actions/runs/36883090923): native playback/SMTC adapters, 39 shared presentation/headless checks plus retained fixtures per architecture, portable updater, assembled application startup, PE architecture checks, core/save/media tests, provenance/rejection checks and portable ZIP uploads. |
| Native macOS Intel | Local cross-build/package VERIFIED. Native CI builds the application but package qualification is BLOCKED by the existing 250 ms save budget: post-reopen saves measured 456.8 ms and 705.7 ms on separate runs; another metadata save measured 410.1 ms. One intervening workspace run passed. The core save implementation and timing test are unchanged from the starting revision. |

Downloadable artifacts: [Windows x64](https://github.com/tlolabs/encap/actions/runs/36883090923/artifacts/11173952686),
[Windows ARM64](https://github.com/tlolabs/encap/actions/runs/36883090923/artifacts/11174446541),
[Linux x64](https://github.com/tlolabs/encap/actions/runs/36890873483/artifacts/11176654501),
[Linux ARM64](https://github.com/tlolabs/encap/actions/runs/36890873483/artifacts/11177320408),
and [INTERNAL macOS ARM64 reference](https://github.com/tlolabs/encap/actions/runs/36876431008/artifacts/11170288056).
These are workflow artifacts subject to GitHub retention, not production releases.

The release path accepts matching unsigned annotated Git tags. Linux final-package
qualification now uses the exact native workflow artifact and GitHub attestation
instead of a detached repository signature. The new `verify-linux.yml` manual
workflow is NOT VERIFIED in CI yet: GitHub does not dispatch a workflow that
exists only on this branch until it is present on the default branch. Its native
build inputs passed in the Linux run above; the remaining provenance and upgrade
evidence must still be recorded before production promotion.

CI exposed and corrected missing GitHub CLI visibility under MSYS2, missing token
scope for repeat Mac provenance verification, a PPM test fixture unsupported by
the pinned runtime, Windows-to-POSIX runtime path handling, and mutable AppImage
tool downloads. The Windows SMTC adapter now uses explicit WinRT namespaces,
standard C++20 coroutines and balanced WinRT initialization; CI compiles native
adapters early. AppImage tools now use versioned releases with reviewed hashes.
GLib/GIO and their OS-level transitive libraries remain system dependencies,
with notices included for the remaining bundled distribution libraries.
The optional .NET LTTng provider is retained unchanged outside linuxdeploy's
mandatory dependency resolution; opt-in LTTng tracing still needs the host's
compatible tracing prerequisites, as described by [Microsoft](https://learn.microsoft.com/dotnet/core/diagnostics/trace-perfcollect-lttng).
No application feature or verification check was removed to make packaging pass.

Before production acceptance, verify Windows SMTC/media routing, Linux desktop
MPRIS routing (including Wayland/XWayland), native file dialogs, audio devices,
scaling/multiple displays, NVDA/Orca keyboard and screen-reader behavior, drag/drop,
long source lists and long AIFF recordings. AIFF preview uses a cancellable
conversion to temporary PCM through the authenticated bundled FFmpeg before
playback, so first-play latency and temporary disk use scale with recording size.
Linux packages use the existing updater/runtime glibc 2.39 minimum (Ubuntu 24.04
or a compatible distribution), with X11/XWayland and system GLib/GIO. Model
downloads/removal need real native acceptance in addition to the existing
catalog/hash tests. No feature was removed because GUI automation was difficult.

Production release remains BLOCKED by the existing unapproved Windows/macOS
signing, Linux provenance, authenticated A-to-B update and manual acceptance
ledgers. Native Intel CI
save-latency qualification is also BLOCKED by the measurements
above; controlled native Intel profiling/acceptance remains necessary. The Windows
power-loss journal/rollback path and full installer lifecycle must be exercised
on native hosts. This report does not mark those gates passed, and no tag,
release, Developer ID signing, notarization or paid service provisioning is
performed by this migration.
