> Historical audit (2026-09-16). Its Core-runtime migration proposal is superseded
> by EnCAP's independent [source runtime](ffmpeg-source-runtime.md). These older
> candidate results and prerequisites do not describe current normal packaging.

# Normal-build AVID Core migration

## Audit before structural changes — 2026-09-16

Baseline EnCAP commit: `97df274`, branch `codex/encap-managed-runtime-preflight`;
working tree clean. Inspected all tracked source/build/workflow/documentation
references to FFmpeg, FFprobe, AVID Core, environment overrides and managed runtime,
plus generated candidate provenance, Core provisioning interfaces and remote CI.
There is one tracked workflow, `build-platforms.yml`; no separate nightly runtime
workflow was found. Native macOS/Windows/Linux UIs call `encap-engine`, rather than
acquiring or directly invoking FFmpeg themselves.

### Ownership inventory

| Location | Existing behavior / migration obligation |
| --- | --- |
| `Cargo.toml`, `Cargo.lock` | Mutable sibling Core path; no immutable Cargo source identity. |
| `runtime/core-revision`, `script/check_core_runtime.sh` | Candidate helpers require Core `2e2e8eb79ae80d40823ae3b37f83464e31750cd3`; normal Cargo builds do not enforce this file. |
| `.github/workflows/build-platforms.yml` | Five sibling Core checkouts pin that same older commit; common `FFMPEG_VERSION` is host-owned. Handles PR, main push, tag and manual builds and gated release publishing. |
| `script/fetch_ffmpeg.sh` | Host-owned version/release/architecture/URL/hash table. Downloads separate Martin Riedl macOS tools or BtbN Windows/Linux archives, checks hashes, extracts/copies the pair and optional license. |
| `script/prepare_ffmpeg.sh` | Cache under `.build-tools/ffmpeg-9.0.1-install-$ARCH`; host-script hash and binary checksums determine reuse. Calls legacy fetch on a miss. |
| `script/build_ffmpeg.sh`, `script/build_ffmpeg_linux.sh` | Thin host wrappers around prepare; their names no longer mean compilation from source. |
| `script/build_and_run.sh` | Normal macOS development/run/debug/verify/package entrypoint. Uses legacy prepare, default-feature Cargo build, copies tools to `Contents/MacOS`, records buildconf, signs helpers and app, tests and creates DMG. No managed manifests or source provenance. |
| Workflow Windows matrix/download/assembly | Duplicates BtbN filenames, digests and URL; extracts into `.build-tools/ffmpeg`, recursively chooses tools, copies to portable stage, writes buildconf, tests and zips. ARM64 uses an x64 runner and skips some native checks. |
| Workflow Linux build/assembly | Calls legacy prepare, copies tools to portable `bin`, records buildconf, runs media tests and makes archive. |
| `script/acquire_core_runtime.sh` | Existing thin Core acquisition wrapper; normal builds never call it. Core requires qualified immutable release assets and attestation before staging. |
| `script/package_core_candidate_macos.sh` | Separate build/package implementation. Takes a caller-supplied validated runtime, explicitly enables `managed-runtime`, stages through Core `host.py --candidate`, records pre/post-sign hashes, relocates manifests to `Resources/FFmpeg`, tests without PATH, gives app separate identity. |
| `script/test_core_runtime.sh` | Candidate-only Core staging and all-mode media tests; removes/corrupts manifests and tools and checks failure with an external pair on PATH. |
| `crates/encap-ffmpeg/src/lib.rs` | Default path independently resolves overrides, executable-adjacent tools, Resources, then PATH. Invalid override can fall through. Default validation only checks nonempty version output. Optional managed feature calls Core `from_managed_layout` unless either override is set. |
| `crates/encap-audio/src/lib.rs` | Uses shared host resolver, then invokes its explicit ffmpeg path for audio export. Retains audio metadata/encoding policy; not an independent acquisition mechanism. |
| `crates/encap-transcript/src/lib.rs` | Same resolver; explicit ffmpeg for mono16k PCM preparation for Whisper/WhisperKit. Apple Speech and transcription helpers are separate host features. Generic optional-tool lookup is also used for those helpers. |
| `crates/encap-video/src/lib.rs` | Host resolver supplies explicit paths to Core discovery/rendering. Core owns video command graphs, probing and rendering. |
| `crates/encap-engine/src/main.rs` | Mode routing and `validate-tools` use those adapters. |
| `crates/encap-core/src/model.rs`, `project.rs` | User-facing encoder identifiers and legacy project migration, not runtime version/acquisition ownership; preserve project compatibility. |
| `crates/encap-engine/tests/media_contract.rs` | Three real-media tests use explicit tools; `ENCAP_TEST_MANAGED` clears engine overrides and PATH. Other protocol/unit tests contain tool fixtures. |
| `README.md`, `docs/development.md`, `docs/architecture.md`, `THIRD_PARTY_NOTICES.md` | Describe sibling dependencies, legacy provisioning/discovery/notices. Historical migration/readiness reports must remain clearly dated, not masquerade as current production documentation. |
| `dist/EnCap.app`, `/Applications/EnCap.app`, `.build-tools` | Generated normal/installed bundles and old caches; not tracked replacement candidates. Preserve until replacement passes. |
| `build/runtime-qualification/package.SIvnrq/EnCap Runtime Qualification.app` | Existing recipe-6 candidate. Its build manifest records Core `9eb8651bc09b6fb007784d3df840d51fa7bbba82`, not a published v0.2.1 runtime. |

### Why qualification differs from production

The candidate enables an opt-in Cargo feature, takes a separately validated local
Core payload and calls Core staging/signature-record helpers. Normal builds omit
that feature, call the legacy downloader and copy only tools/buildconf. Candidate
success therefore does not prove production provisioning or artifact authentication.
The two scripts duplicate bundle assembly. The eventual replacement must extract
one production assembly path and let qualification test it with explicit candidate
inputs; it must not add a third downloader or copy Core verification logic.

## Core release and exact blocking failure

Source tag `v0.2.1` resolves to `eab97dd043187aa8b7a1cae4eb2c1228fa25a9db`.
GitHub releases API still returns `[]`. The tag's specification is recipe 6,
FFmpeg 9.0.1, status `candidate`, with unresolved matrix/repeat-build, environment
and host/minimum-OS gates. An application source tag is not a runtime publication.

[Core runtime run 35065840420](https://github.com/tlolabs/avid-core/actions/runs/35065840420)
compiled Windows x64 FFmpeg, but its real-media suite passed 4/5 tests.
`simple_matches_legacy_pixels_audio_and_requested_cadence` failed at
`tests/ffmpeg.rs:328` because the packaged `ffmpeg.exe` exited with decimal
`3221225477` (`0xC0000005`, Windows access violation). The failing software command
used a looped image at 60 fps, both flips, 90x160 blur/overlay composition,
`libx264`, AAC and MP4. Stderr only recorded the guessed mono channel layout.
The log establishes the crash, not whether FFmpeg, a library, assembly or compiler
caused it. Core must reproduce/debug/fix this exact software path, preserve its
regression test, then rebuild and pass the matrix. No EnCAP encoder/filter workaround
is justified. The `complete` and `publish` jobs were skipped.

[Core source run 35065840426](https://github.com/tlolabs/avid-core/actions/runs/35065840426)
also failed on Ubuntu: lifecycle test `cancellation_after_encoding_prevents_publication`
could not execute its fake `ffmpeg -version`, returning `ExecutableFileBusy` /
`Text file busy` at `tests/lifecycle.rs:42`. Core owns diagnosing that failure too.

### Missing production input

Core's acquisition/staging/runtime interfaces already exist. The missing input is
an immutable qualified runtime release tied to the selected Core commit, with
runtime and matching source archives, trusted asset SHA-256 values, attestations
and complete per-target evidence. The current candidate derives
`ffmpeg-9.0.1-r6` / `avid-ffmpeg-9.0.1-r6-<target>`; those names are observations,
not new EnCAP constants. A recipe correction may require a new recipe and source tag.
The successful local candidate cannot be relabeled as that future release.

Per the request's Phase 2/3 conditions, do not edit Core or replace/delete the normal
runtime mechanism before that prerequisite exists. Source dependency pinning and
its compatibility checks can proceed independently. Core's software-only Windows/
Linux policy stands; GPU validation is not being reintroduced as a blocker.

## Existing remote platform evidence

These results predate changes in this task. EnCAP's
[run 35064906664](https://github.com/tlolabs/encap/actions/runs/35064906664)
uses legacy runtime acquisition, not the managed candidate.

| Target/check | Core recipe-6 runtime CI | EnCAP normal CI |
| --- | --- | --- |
| macOS ARM64 | Passed | Passed with legacy pair |
| macOS Intel | Passed | Failed save latency/cloning contract |
| Windows x64 | Failed FFmpeg access violation | Passed with legacy pair |
| Windows ARM64 | Passed native runtime job | Failed executing legacy ARM64 ffmpeg buildconf from x64 job; no native acceptance |
| Linux x64 | Passed | Media suites/validate-tools passed; subsequent assembly shell check failed |
| Linux ARM64 | Passed (ATIV union target) | Not a distributed EnCAP target |
| General checks | Ubuntu lifecycle failure in separate source workflow | C `format-truncation` error in chapter-name test with warnings denied |

Linux assembly's next source command matches literal `ffmpeg version 9.0.1`
against the BtbN build's `n9.0.1-...` identity; this is the likely failing legacy
version check (the log has no shell trace). Replace it with Core validation in the
actual migration, rather than treating it as a successful package.

## Completion status

Normal-runtime migration is blocked. No legacy binaries, caches, acquisition
scripts or UI behavior have been removed or changed. No new application package
or release has been produced. Phase 3–7 acceptance cannot pass until the Core
runtime supply and qualification gate is resolved. Post-audit changes and local
checks are recorded below as they complete.


## Changes completed after the audit

- Pinned Cargo to AVID Core `v0.2.1` commit
  `eab97dd043187aa8b7a1cae4eb2c1228fa25a9db`, with exact package version `=0.2.1`.
  The lockfile records the Git source and commit; arbitrary sibling HEAD no longer
  supplies the Rust dependency. No Core source file changed.
- Updated all five workflow helper checkouts and `runtime/core-revision` to the
  same commit. Normal macOS packaging and each CI job check helper-source agreement
  with Cargo and reject dirty or mismatched sibling checkouts before packaging.
- Added `script/test_core_revision.sh`, run by CI, to exercise clean LF/CRLF success and
  rejection of modified files, untracked source, mismatched Cargo pin and wrong HEAD.
- Updated developer instructions and corrected the stale pending-CI statement.
- Removed no legacy provisioning mechanisms, caches or binaries: the replacement
  production runtime remains unavailable. These changes complete the source-pin
  preparation only; they do not claim the normal-runtime migration is complete.

### Checks performed for these changes (local macOS ARM64)

| Check | Result |
| --- | --- |
| Default-feature workspace/all-target Cargo check | Passed |
| Workspace all-feature tests | 46 passed; 3 opt-in media tests and 1 large-save benchmark omitted in this invocation |
| Rust formatting; all-target/all-feature Clippy with warnings denied | Passed |
| Rebuilt pinned managed engine staged with existing Core recipe-6 candidate | All 3 media contracts passed with engine overrides removed and PATH empty |
| Missing/damaged tools and manifests with usable external tools on PATH | Passed through existing candidate test harness |
| Rebuilt pinned normal/default-feature engine with explicit existing bundled tool paths | All 3 media contracts passed |
| Production acquisition via Core wrapper | Correctly rejected `candidate` with `Runtime qualification is incomplete; preserve the working host runtime`; no destination created |
| Source pin positive/negative regression checks | Passed |
| Shell syntax, native-only source policy, workflow YAML parsing, diff whitespace | Passed |

Managed staging above is compatibility evidence using the old validated local
candidate, not authenticated production acquisition. The normal engine test uses
the existing normal-app FFmpeg/FFprobe bytes with a newly compiled engine; it is
not a freshly packaged normal app. The existing candidate app and installed app
were not overwritten. Core real-media CI results are the remote evidence above;
no new Core native matrix, EnCAP native UI matrix or minimum-OS test was run here.
No CI was dispatched for this source-pin preparation; the known platform failures
remain open and no all-platform success is claimed.

### Required next handoff

Core must fix and verify the Windows x64 software-encode access violation and the
Ubuntu lifecycle-test execution failure, finish recorded qualification gates, and
publish the full immutable attested runtime/source matrix from a clean selected
revision. Do not weaken gates or remove the failing media test. If that requires a
new recipe/source tag, EnCAP must move its consistent source/helper pins to it.
Then normal and qualification packaging can share Core acquisition/staging,
pre-sign verification and signed provenance recording, turn managed discovery into
the production default, remove legacy provisioning after verified replacement,
and run the complete native EnCAP matrix including native Windows ARM64.
