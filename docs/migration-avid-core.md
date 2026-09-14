# EnCAP Video migration to AVID Core

EnCAP Video now delegates media behavior to the canonical `avid-core` crate.
The migration and local macOS verification are implemented; the platform/manual
release gates below remain open. This report does not complete the final
cross-repository audit.

## Revisions and scope

- EnCAP baseline: `a96978e5bb89189b944e5dd6a30e5ee7e8fe28d4`, initially clean.
- Branch: `codex/encap-shared-core`.
- `76383b1`: shared Video adapter, persisted type re-exports, dual signal cancellation,
  and adapter/engine media contracts.
- `c23cc25`: preserve unknown Transcript word extensions through native round trips.
- `0b33613`: mixed WAV/AIFF format and sample-rate verification.
- Packaging, CI, notices, and this report are committed separately after those changes.
- Exact shared revision: **`0cce6ba838827d0bed540efc98731e74a1014456`** at
  `/Users/tlothian/Documents/Projects/AVID Core`.
- The standalone app's migration report and workspace dependency resolve to that
  same revision. Its HEAD is `17dc43c72509e455d3d5a71b9a2eb086a28f4121`.
  Its source and pre-existing untracked `assets/` were not changed. AVID Core is
  also unchanged and clean; no common implementation gap required a shared patch.
- The user explicitly approved proceeding while carrying forward the standalone
  app's outstanding interactive/native platform verification gaps.

The shared README, extraction report, inventory, and completed standalone migration
report were inspected before editing. The original EnCAP engine is retained under
ignored `target/migration-reference/encap-engine` for decoded-media comparisons.
No changes were pushed and no release was published.

## Adapter boundaries

The workspace consumes `avid-core = { path = "../AVID Core" }`; `encap-core`,
`encap-video`, and `encap-engine` use the workspace dependency. `encap-video` is
now 129 lines of production adapter code, plus tests. It owns project preflight,
main-artwork workflow requirements, selected-record mapping, and host diagnostics.

`encap-core` re-exports shared VideoSettings/VideoProjectState and calls
`video.validate_schema()` during whole-project validation. ProjectDocument,
Audio/Transcript models, ZIP schema migration/extraction, session ownership,
recovery, atomic saves, and compatibility merging remain in EnCAP.

Selection delegates to `select_clip_indices`. Only selected chapters are mapped;
chapter_number minus one is checked against the canonical audio_sources collection.
The selected-order index and cumulative chapter start time are never used as a
source index or seek. The adapter builds a shared Timeline and passes the settings
through `render_settings()`, retaining square padding/sigma20, both flips,
H.264/HEVC, all three encoding policies, and the original FPS/bitrate limits.
All audio, main/chapter artwork, and the current project file are protected,
including unselected sources. Main artwork is inspected even when every selected
chapter has an override. Successful responses retain the caller's destination spelling.

The original presets, graph builder, settings/image validators, encoder parser and
selector, process execution, destination checks, retry/staging cleanup, and
publication code were removed from encap-video. Shared code owns those operations.
Remaining preset DTOs in native clients are wire models, not preset tables.
Remaining Audio/Transcript commands and staging in encap-ffmpeg are intentional.
Packaging capability lists and fake-tool test strings are also intentional.

## Discovery, signals, and protocol

All modes use the same host resolution policy and executable paths. A narrow
`MediaTools::discover_with_validator` extension lets Video validate the host-resolved
pair through shared discovery while ordinary `discover()` keeps the existing
Audio/Transcript validation. This avoids the old uncancellable validation followed
by duplicate shared validation. Both resolved getters become explicit shared
ToolDiscovery overrides. The host's existing `is_file()` filter preserves invalid
ENCAP_FFMPEG/ENCAP_FFPROBE fallback; an engine regression tests both modes against
that same fallback pair. Shared validation then rejects mismatched version identities.

The single existing signal handler cancels both the retained Audio/Transcript token
and a shared Video token. There is no second handler or polling bridge. Process-level
SIGTERM tests cover Video tool validation, capabilities, main-artwork probing, and
encoding. Shared defaults remain 30-second probes, 120-second previews, and unlimited
renders. Shorter options are used only by deterministic lifecycle tests.

ExportVideo, VideoPresets, VideoCapabilities and error responses remain one JSON value
on stdout. Stages/diagnostics go to tracing. Shared errors are logged structurally,
including both fallback attempts. User messages distinguish cancellation, timeout,
missing software/hardware encoders, incompatible tools, and failed fallback, without
forwarding paths/stderr from shared Display text. The four encoder-availability
message mappings are pinned-version presentation adapters, not encoder selection logic.

Native playback remains unchanged: async engine calls, native artwork presentation,
preview_quality, pause/seek/next/previous, and mode navigation stay in the clients.
Native artwork blur/scale is approximate and is not claimed pixel-identical to export.
No export pause/resume or new UI graph/selection implementation was added.

## One approved FFmpeg pair

Both original custom source-build entrypoints now prepare the same pinned upstream
artifacts used by the standalone app. `script/fetch_ffmpeg.sh` records the immutable
Martin Riedl macOS and BtbN Windows/Linux inputs. Windows pins were aligned to the
same 2026-09-11 BtbN release. This is host packaging metadata; the shared crate builds
and bundles no tools. There is no runtime dependency on the standalone checkout.

The common macOS arm64 candidate was checked against EnCAP requirements before
adoption: libmp3lame, native AAC, AudioToolbox AAC, libx264/libx265, PCM codecs,
image decoding, resampling, and composition/concat filters. Actual MP3/AAC exports,
mixed WAV/AIFF import and conversion, and Transcript mono/16 kHz preparation passed.
The executable uses only system dynamic libraries; its Mach-O minimum OS is 12.0,
below EnCAP's unchanged macOS 13 deployment target.

The already-existing verified candidate replaced the binaries in EnCAP's existing
`.build-tools/ffmpeg-9.0.1-install-arm64/bin` location. No second Video pair was
introduced. Cache reuse checks the fetch-recipe digest plus executable SHA-256;
clean machines download the hash-pinned archives. Packaging stages just one pair
and tests all modes against those exact paths.

Input executable hashes (before EnCAP bundle signing):

- ffmpeg: `393e4c395020a1cb7cbd77fbe00599ce69d1c6466fee0dbd59d13f86a81a1611`
- ffprobe: `7abc49fb2bdf2204f018e76dc6e0a8ae7643313bae09a9fa43e7eb12442271bc`

Both identify as `9.0.1-https://www.martin-riedl.de`. Bundle signing changes their hashes:

- ffmpeg: `65948fb06823b2f6c2a95932b21c9abaa9d0e730f4dbbb7bcaa975eb87f31621`
- ffprobe: `2d0f252b6ceb0a8125d3f6d2eac8ce8204ef835b05498953323cb17ba161c9fb`

Build configuration and AVID Core's license are included in the app resources.
CI checks out the exact shared revision beside EnCAP. Native packaging runs shared
real-media tests and EnCAP's release-pair suite; Windows ARM64 runtime verification
still requires its native runner. CI YAML was parsed locally but not dispatched.

## Verification actually run

| Check | Result |
| --- | --- |
| Pre-edit EnCAP workspace fmt/check/test/clippy + native-only policy | Passed; 18 original tests |
| Shared fmt/check/test/clippy at the exact revision | Passed; 36 tests |
| Three explicit shared FFmpeg tests | Passed before migration and with the final bundled pair |
| Final EnCAP workspace fmt/check/test/clippy | Passed; 23 default tests, 3 media tests explicitly ignored in default invocation |
| Three explicit EnCAP release-pair tests | Passed on candidate and final bundle |
| Original vs migrated engine | Preset JSON equality; identical decoded H.264 video and audio for reordered source sequence, including final packaged engine |
| Native macOS model tests | 9 passed |
| `script/build_and_run.sh --verify` | Built, signed, launched; process check passed |
| `script/build_and_run.sh --package` | Passed, including staged EnCAP/shared media tests |
| Deep strict app signature and DMG checksum | Passed |
| Packaged VideoCapabilities with empty PATH | Passed; bundle discovery independent of developer tools |
| Real explicit hardware export | H.264 and HEVC VideoToolbox succeeded; avc1/hvc1 plus stereo/48 kHz AAC verified |
| Shell syntax, workflow YAML, git diff whitespace | Passed |

Adapter tests cover reordered subsets, intentional empty selection, duplicate/missing
IDs, unchecked chapter-number hazards, unselected invalid source mapping, main/chapter
artwork fallback, all protected-path hard-link/symlink aliases, invalid execution
settings/durations, exact shared graph delegation, automatic fallback, explicit
hardware failure, cancellation, timeout, and old-output/source preservation with no
remaining `.avid-*` stages. The three original Video test intentions are retained.

Real-media tests use generated WAV/24-bit AIFF at different sample rates, colored and
asymmetric quadrant artwork, and paths with spaces/Unicode. They verify order,
duration, both codec tags, stereo/48 kHz AAC, all four flip combinations, corrupt or
missing media, invalid settings, main-artwork validation despite chapter overrides,
and preservation of original sources and existing output on failures. Decoded parity
with the original engine verifies the original trimming/concat behavior, without
added silence or crossfade.

Engine tests also cover MP3/native AAC/AudioToolbox AAC export, provider discovery and
unknown-provider rejection, Transcript PCM preparation and TXT/SRT export, save/open,
recovery, and exactly one JSON response. Actual speech-recognition quality is not
claimed from those routing/preparation checks.

Schema-1/schema-2 archive fixtures open/edit/save/reopen unknown project, metadata,
audio, chapter, Transcript, export, Video fields and reserved compositions. Unknown
codec/preview values survive; unknown executable settings fail rather than default.
Video reorder preserves canonical Audio order/timing. Existing load-time stale-ID
cleanup and empty/uninitialized semantics remain unchanged. Tests simulate a native
client dropping extension maps while retaining known data and compatibility_payload.

This exposed an existing word-extension hole: native Codable words omit unknown keys,
but the compatibility payload had not retained them. The narrow project-layer fix
stores word extension maps by segment and word IDs, defaults the new payload field
for older clients, and merges only surviving words. Archive schema and Video ownership
are unchanged. The regression now explicitly drops and recovers those word extensions.

## Artifacts and remaining gates

- Application: `dist/EnCap.app`.
- DMG: `dist/EnCap-2.0.0-macos-arm64.dmg`.
- DMG SHA-256: `86e18953568c8d785aa006c9d35eb0e16641b65bb96697beed2b8a724837b934`.
- Ignored local logs: `build/migration-build.log`, `build/migration-package.log`,
  `build/migration-dmg-verify.log`; generated native/hardware fixtures in `build/migration-ui`.

Native tests initially hit stale Swift module caches containing the old lowercase
`encap` path. A fresh test scratch directory and removal of the generated WhisperKit
architecture cache resolved this; no native source changes were needed.

The newly built native UI was observed with Audio/Transcript/Video controls. The
computer-use connection then failed during test-project opening with
`Sky Computer Use native pipe closed before response`, and failed again on readback.
Interactive mode navigation, playback pause/seek/next/previous, reorder/save from the
UI, accessibility, and UI Stop behavior remain unverified. Engine/model results do
not substitute for those checks.

Windows/MSVC x64/ARM64 and Linux GTK package builds/runtime tests were not run on this
macOS host, which lacks dotnet/Windows SDK and Meson/GTK tooling. No cross-compilation
result is claimed. Intel macOS and minimum-OS runtime verification remain pending.
Windows file locking/overwrite and clean-machine bundled discovery need native tests.
Other platform artifacts share the pinned catalog but are not certified here solely
from capability declarations. NVENC/QSV/AMF/VAAPI were not tested on real devices.

Actual Apple Speech/Whisper recognition, model downloads, low-disk/read-only and remote
filesystem behavior, Developer ID/notarization, Windows signing, and clean installs
remain release gates. Local macOS artifacts are ad-hoc signed. The standalone app's
remaining native verification and the final two-host cross-repository audit are still
separate work; neither is declared complete by this migration.
