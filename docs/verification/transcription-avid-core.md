# EnCAP AVID transcription verification

Task `encap-avid-integration-20261103`, baseline
`2c20da6c6499484c1141c3902d03c9f6afcefba2`. Host: Apple silicon,
macOS 27.2, Xcode 27.2, Swift 6.4.2. Session evidence is retained under
`/tmp/encap-avid-integration-20261103/`; this directory is machine-local and
temporary. Existing working changes were captured in `baseline.diff`,
`initial-status.txt`, and `preexisting-BUGFIX_REPORT.md` before reconciliation.

## Automated integration checks

- `ruby script/verify_avid_snapshot.rb`: verified the pinned source archive,
  pinned manifest and all 34 source files. No vendored source was modified.
- `cargo fmt --all --check`: passed.
- `cargo clippy --workspace --all-targets --locked -- -D warnings`: passed.
- `env ENCAP_SAVE_CACHE_DIR=/tmp/encap-avid-integration-20261103/save-cache cargo test --workspace --locked`:
  final full integration run passed 134 tests, with 13 ignored diagnostics.
- Native client suite: `env CLANG_MODULE_CACHE_PATH=/tmp/encap-native-ui-clang-cache SWIFTPM_MODULECACHE_OVERRIDE=/tmp/encap-native-ui-module-cache swift test --package-path macos --scratch-path /tmp/encap-native-avid-ui-build --disable-sandbox -j 4`:
  52 tests executed, zero failures, two existing environmental skips. Log:
  `/tmp/encap-native-avid-ui-tests.log`.
- Qt: `cmake --build build/qt-test -j 4` and
  `ctest --test-dir build/qt-test --output-on-failure`: all four suites passed
  on this Mac. This does not qualify Windows/Linux binaries.
- New core migration coverage checks schema-1/2, unknown extensions,
  compatibility payloads, recovery, immutable recognition records, source
  relocation/removal, untimed text, and text-alignment invalidation.
- New bridge/client coverage checks typed errors and progress, malformed and
  large output, literal path arguments, owned-child cancellation/cleanup,
  failure preservation, missing helpers, model selection, realignment, and
  bounded raw failure diagnostics kept off stdout.
- Seven sidecar Swift tests passed. New-helper native smoke checks passed for
  Parakeet (17 timed words), full Whisper with `EN_us` and source offset 12.5
  (17 timed words), and Qwen recognition plus forced alignment (17 words).
  Corrected-text realignment retained the edited text and original model
  identity; Core WebVTT produced four cues. SIGTERM and parent-crash cancellation
  returned JSON errors and removed temporary Qwen staging. See
  [helper verification](../../helpers/avid_transcriber/VERIFICATION.md).
- Seven packaging tests and 12 publication-validator tests passed. Publication
  tests mock the remote service; they do not publish a release.

The initial default Rust run failed three optional save-index tests because the
sandbox denied its normal application cache. Writable cache overrides resolved
those failures. Updater HTTP fixtures also required host loopback access; the
full suite was rerun with that access. The first native manifest run could not
write the default Clang module cache; temporary module caches resolved it. An
overlapping early Swift build observed an incremental-link failure while agents
were editing; subsequent complete native tests passed. These failed attempts
remain in the session logs and are not counted as passing checks.

## Normal package and functional checks

The canonical entrypoint is `./script/build_and_run.sh --verify`, with
`ENCAP_AVID_BUILD_DIR=/tmp/encap-avid-helper-build`,
`ENCAP_AVID_MODEL_CACHE=/tmp/desktop-transcription-20261102-e8b98234/models`,
and a writable `ENCAP_SAVE_CACHE_DIR` for this session. A fresh supported host
must provision a shared smoke model or explicitly opt into anonymous installation
with `ENCAP_QUALIFICATION_INSTALL_MODELS=1`. CI opts in for the supported target.

The first sandboxed invocation could not authenticate the pinned cached runtime
against GitHub or inspect host processes. Retrying with host access preserved
all FFmpeg integrity/provenance checks and compiled the normal native app,
Rust release engine, and release AVID helper. Packaging then exposed unsigned
SwiftPM resource bundles; this was corrected before functional qualification.
The subsequent packaged smoke exposed a real resource lookup failure: SwiftPM
resolves its bundles under the enclosing app's Resources directory. The package
layout was corrected rather than weakening the inference check.
The corrected normal entrypoint completed with exit 0. The actual packaged
engine used Parakeet v3 offline with an empty PATH: 17 timed words, unchanged
source audio/project, successful TXT/SRT export, and recorded hashes of the
signed helper, catalog, Metal and other resources. All six generic packaged
media tests passed, as did missing/damaged/mismatched runtime rejection,
save/audio protocol tests, strict bundle-signature verification, 48 native
tests (two environmental skips), and application launch/process verification.
Log: `normal-verify-resource-layout.log`. An incremental final-source rebuild
also includes the last failure-diagnostic-only change; its record is retained
with this session's logs. No minimum-macOS claim follows from this host launch.

Exact resolved SDK license collection covered 15 pinned dependencies and 37
license/notice texts, plus a revision/hash manifest, under the app's
`Contents/Resources/AVIDTranscriptionLicenses`. No legacy helper executable was
present in the rebuilt package. The supported Mac app is staged at
`dist/EnCap.app`; signing/notarization credentials and publication were not used.

## Independent review

Antigravity-first independent review runs after final implementation/checks,
using this task's original requirements and unchanged baseline/task ID. The
upstream Core review is separate and does not establish EnCAP correctness.
Round 1 completed with Antigravity alone, complete coverage, no findings and
passing validation. Snapshot:
`a9d16f482f134f43398d58425840deddf78219779ea4ad6c8c624d31d5974280`.
The review runner ran the eight listed Rust/native/policy/packaging commands in
a clean source copy; neural, Qt and packaged-media runs were separate host checks.

Additional integration checks after that review reproduced three source-edit
defects: a retained source's slightly overshooting timing could be deleted when
the next source was removed; saved rerecognition history could disappear with
its carrier source; and reimporting original media after save/reopen could reuse
a path-derived source identity. All three were fixed with Rust/Swift regressions,
including real inspect/save/open/reimport/removal. History also falls back to
project-level storage if audio remains without an active segment; save/reopen,
recovery and delete-all tombstones are tested. Core tests passed (60 tests, two
ignored benchmarks), and full native tests passed (52 tests, two skips). A second
review uses the same baseline/task ID. Qt text edits
also now preserve the truthful `untimed` state across JSON round-trips.

A native GUI check opened a synthetic real-transcription project, inspected the
shared model manager, edited text and saved. The segment ID, manual speaker and
original recognition remained intact; the word array was cleared and caption
buttons disabled. Only temporary test projects were used. Machine-readable
result: `ui-fixture/native-ui-verification.json` in the session directory.

Round 2 completed with Antigravity alone, complete coverage, no findings and
passing validation, snapshot
`35fa4c7597115705a26db2a47f816e0b0e0e94f00aae282aed77c43af73d8f9c`.
All 11 clean-copy commands passed, including 134 Rust tests, 52 native tests
(two skips), and all four Qt CTest suites. Antigravity explicitly checked the
source-edit/history/identity and Qt timing-state fixes. Its phrase “Round 1
findings” refers to the additional integration reproductions supplied for this
round; the first external review itself reported no findings. Neural inference
and packaging were separate host checks, not executions by the reviewer.

The normal entrypoint was rebuilt after these fixes and completed with exit 0
(`normal-verify-post-review-fixes.log`): real packaged inference, exports,
signature/resource integrity, six media tests, three audio/persistence tests,
52 native tests (two skips), and launch passed again. The final local ZIP passed
archive integrity and transcription publication preflight without publishing:
`/tmp/encap-avid-integration-20261103/EnCap-2.0.9-macos-arm64.zip`, SHA-256
`f2beaad4feb649246e16926686d3ca395339709c08e2adc02482151e4dbd3f22`.

Additional packaging diagnostics passed: four desktop-distribution tests, nine
platform-runtime tests, four runtime-ownership tests, and the desktop dependency
inventory check. Full-suite ignored diagnostics remain visible: the normal
packaged harness separately runs six media, one audio-edit and two save tests;
the two large benchmark diagnostics, separate Rust model qualification fixture,
and Core native fixture are not counted as independently executed here.

[Durable evidence](transcription-avid-core-evidence/) includes both original
review reports, a review-results summary, final clean-copy command output,
packaged helper/resource hashes, package preflight, helper functional/cancellation
summaries and the native GUI result. Temporary complete build logs remain in the
session directory. The tested ZIP and app are local development artifacts;
nothing was committed, pushed or published.

## Limits and unresolved support decision

Intel Mac, macOS 13, Windows x64/ARM64 and Linux x64/ARM64 have no qualified new
inference path. Their base-app configurations and saved transcript editing/export
remain. Owner approval to ship those targets without transcription, or upstream
AVID Core support for them, is still required. No platform-policy decision is
inferred from elapsed time or a successful supported-host build.

Minimum macOS 14, physical Intel hardware, Windows/Linux native UI/runtime,
long-form/multilingual accuracy, measured acoustic boundaries, peak memory,
comparative throughput, mobile inference and animated caption burn-in are unrun.
The upstream shared-store tests cover downloads/resume, integrity failures,
imports, offline reuse and locking, but those previous results are not relabeled
as new EnCAP network/long-running concurrency tests. A small synthesized-English
smoke is not a representative accuracy benchmark.

No commit, push, merge, public release or authenticated-feed update is performed
by this task. Target qualification is per artifact; failures do not introduce
required reviews, manual approval gates, or six-target publication gates.
