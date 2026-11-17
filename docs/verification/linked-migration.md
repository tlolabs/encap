# Linked migration verification record

Task `encap-linked-20261116-dc1e968`, baseline
`dc1e96879f434b8ec05d2965c4938fb7cd5f7cdf`. All original requirements and
pre-existing hashes are retained under
`/private/tmp/encap-linked-20261116-dc1e968`. This record covers development
integration, not a qualified distribution. See the [mode/platform matrix](../linked-migration.md).

## Checks executed before the independent audit

| Check | Actual result / scope |
| --- | --- |
| Immutable source | Remote/local v0.4.0 verified as dd112d4; independent remote Git cache acquired; dirty sibling source excluded |
| Swift source snapshot | Manifest/archive and every vendored source entry verified against dd112d4; archive SHA76f517ddfcf14067ac52c0f84b61b4f3bb7dd11917df30de94385dc0d15428a3 |
| Rust media units | Video12, Audio3 and compatibility transport3 passed; actual generated PNG/WAV inputs and linked MP4 previews/exports included |
| Rust project contracts | Core51 passed/1 ignored with writable cache; transcript persistence9, Video persistence2 passed; a later added progress-scope test is counted in final commands below |
| Facade/CLI | Initial ABI6 and CLI1 passed; later alias/progress/compatibility regressions verified in final commands below |
| Native Swift | 54 tests passed, including actual linked import/waveform/save/open/preview and cancellation. SwiftPM cache read-only warnings remain; no native UI visual assertion inferred |
| Native Qt | All4 CTest entries passed (contract, Widgets, stale-result/performance, miniaudio security). Repeated with actual dylib and empty media PATH; shared-library fixture tests are not native target qualification |
| Swift transcription adapter | 12 tests passed; staged debug module loaded and checked ABI with empty PATH, including actual catalog/Metal resources |
| Portable Tiny English | One explicit native integration test passed: deliberate verified GGML import, two recognitions, real word captions, runtime/model identity, stable projection, pre-cancel and removal |
| Apple Parakeet v3 | Two actual offline recognitions and a loading-stage cancellation passed; callbacks on executing C caller; awaited teardown |
| Apple Qwen ASR | Two actual offline recognitions and loading cancellation passed; untimed words remain absent; verified model/runtime identities retained |
| Apple Qwen forced alignment | Two actual corrected-text alignments and loading cancellation passed; exact corrected text and original recognition retained separately; staging directories removed |
| Acquisition/source bundle | Seven linked-runtime integrity tests initially passed; exact registry checksums and per-file inventory verified for offline Cargo bundle (15,846 files; SHA733eeb171a4bb01128c6131239854bd1782dd385246cfabc848eb9cc81c422d1) |
| Python/native packaging policy | Transcription staging7 and local-notarization policy8 passed (mocked notarization, not an Apple submission); weekly tooling103 passed; workflow YAML and shell syntax parsed |
| Broad Python suite, initial | 86 tests, 4 failures, 10 skipped: three baseline release-fixture version mismatches reproduced using the original commit; one obsolete runtime-ownership assertion updated for retained immutable compatibility spec |
| Broad Rust suite, initial | Compile failed on a test referring to the removed legacy Core runtime constant; test migrated to the retained compatibility spec without enabling legacy-subprocess |
| Native decoded static-mode regression | **Failed**: Simple/PerFrame mean RGB difference2.109520961934156 exceeds existing0.1 tolerance. Fixture outputs, hashes and logs retained; upstream handoff includes reproduction; tolerance unchanged |

The speech fixture is locally synthesized English, SHA-256
`aba2d8c896a7c480dbcff3aa35d1a4bc9d946b3ea7eff64fb58da0628a84d88e`.
These tests establish pipeline/lifecycle behavior on this Mac, not acoustic accuracy
or other provider/device/long-recording qualification. The tested debug Swift
module SHA is
`a72764b25771ab3b35a4df59f3988a3f0dd2db7d45ad3761a7fcc0f5932f9d49`;
its exact native results are in `transcription-native-summary.json` outside the
repository. Later builds have their own receipts and do not inherit this hash.

Initial project-save tests without a writable cache failed because the default
user Library cache was sandbox-restricted. The same suite passed with
`ENCAP_SAVE_CACHE_DIR` inside the task directory. The failure and correction are
retained in logs. Failed native-mode equivalence remains unresolved.

Two opt-in real-file compatibility tests also passed against the authenticated
existing executable pair: relative/colon input paths, and a reopened project with
PSD artwork exporting complete audio/metadata. This verifies retained behavior;
it does not supply or qualify a linked Audio implementation.

## Unrun and unavailable checks

No native Windows x64/ARM64, Linux x64/ARM64 or Intel Mac package was qualified.
Core's Windows recipes require explicitly provisioned GNU/gnullvm target compilers,
C++ runtime selection and target Rust libraries; Qt and updater MSVC builds do not
supply those prerequisites. The C ABI DLL arrangement is explicit; incompatible
static archives are not interchanged. No CI run was dispatched.

Full Whisper large-v3 and Whisper Turbo real inference were not rerun. Optional
portable inference is not in the default macOS13 media library, and it is not
full Whisper/provider parity. Non-Apple Parakeet/Qwen/forced alignment and portable
model downloads remain unavailable. No real model was silently downloaded or
adopted from a legacy cache. The explicitly verified existing Core cache was used
only by explicit native verification harnesses.

Linked Audio exports cannot be tested because Core has no required public
chaptered MP3/AAC/artwork API or libmp3lame profile. Existing executable Audio
behavior remains compatibility code. Qt's public PCM replacement and structured
sample/window contracts are also absent. No all-mode, no-media-executable final
package qualification is claimed.

No standard Developer ID/notarized replacement was produced. Notarization tests
use mocks; no submission, credential enrollment, release, push, tag move, upload
or publication was performed. Explicit development candidates are unnotarized
and unqualified. The existing three release-fixture failures remain visible.

## Combined final-check status

The combined final workspace run passed156 tests with13 ignored tests and zero
failures, including the updater contracts. An earlier restricted run reached
the updater contracts. Three updater tests could not bind their loopback fixtures
under the filesystem/terminal sandbox; the complete21-test updater contract suite
then passed with native loopback access. The original restricted failure remains
recorded. The broad Python rerun executed103 tests: only the three reproduced
baseline release-fixture mismatches failed; ten tests were skipped. Weekly103
checks, formatting, whitespace checks, shell syntax and YAML parsing passed.
The final preparation/shutdown and truthful-publication regressions brought the
Swift suite to56 passing tests; all4 Qt checks passed with updater exclusion tests. Runtime resource-preflight coverage brought transcription to29 passing
Rust tests; staging9, snapshot3 and mocked notarization8 passed.

Xcode's sandboxed release build failed in the existing Icon Composer export step
because its native service was inaccessible. The same native release build passed
with icon-service access; it used `CODE_SIGNING_ALLOWED=NO`. This is compilation
and app assembly, not a notarized or all-mode qualified distribution.

Same-model concurrent Parakeet requests produced one explicit Core model-busy
error and one successful recognition; this is not a cancel/survivor pass. An
independent-provider Parakeet cancellation plus Qwen recognition subsequently
passed with separate tokens and correct callback threads. Missing Swift catalog
resources were deliberately reproduced as an in-process abort in an isolated
copy; the new runtime preflight and signature-bound resource receipt address that
failure before loading. Corruption evidence is retained separately from healthy
module inference evidence.

The first complete development-package attempt compiled the ARM64 library and
isolated release inference module but failed app signing: ordinary source/license
metadata had been placed under Frameworks, where codesign treats it as nested
code. Inspection also found the Swift compatibility runtime resolving through
Xcode runpaths. The corrected layout stores ordinary metadata under Resources,
uses a proper optional framework, and packages the exact required Swift runtime;
its relocated signing/loader checks are recorded with the final candidate rather
than treating the failed attempt as a pass. A further actual relocated Qwen run
exposed MLX's framework resource lookup; the EnCAP adapter now sets its bundled
metallib through the pinned public MLX API. The final isolated framework passed
strict ad-hoc app verification, empty-PATH catalog loading, two actual Qwen
recognitions and one awaited loading cancellation. Earlier failed attempts remain
in the task logs. The exact matching Apple Swift compatibility-runtime source
revision is not exposed by the installed Xcode toolchain; compiler/build and
runtime byte identities/notices are recorded, and the source limitation remains
explicit for distribution.

The assembled development app passed strict signatures and linked-library
integrity checks. Its first transcription-status check exposed a lexical `..`
in the generated framework path; that path is now constructed directly through
Contents/Frameworks, with a production-layout and hostile-link regression. The
Swift module itself did not change for this fix. The final rebuilt app passed strict ad-hoc signatures, verified linked-library
receipts, empty-PATH ABI/build identity/status, and actual packaged offline
Parakeet recognition with word timing plus TXT/SRT exports and unchanged inputs.
Its transcription report is `passed`, not `unavailable` or `not_run`. The bundle
contains neither encap-engine nor avid-transcriber. This is one provider/mode
smoke on an unnotarized development app, not all-mode distribution qualification.

## Final checks and independent review

The primary Codex agent invoked one fresh Antigravity CLI audit with profile
`gemini`, selected model `gemini-3.8-flash-high`, and provider fallback explicitly
`none`. The unchanged baseline/task ID/original requirements and configured
`/Users/tlothian/.local/share/codex-external-review/runs` state directory were used.
No alternate model/provider, recursive reviewer or UI verification was used.

The report is preserved at:
`/Users/tlothian/.local/share/codex-external-review/runs/478632546bc299ae/776bd250c08712970961/20261116-165631-1d140ab4/`.
Codex read both `result.json` and `review.md`, checked completeness, source/token
identity, coverage, validation and attribution. The runner exited20, with
`completed:true`, `status:incomplete`, `coverage:partial`, `validation:passed` and
**zero findings**. This consumes one of six completed reports (five remain).
There is **no accepted complete independent audit**, and no clean-audit or full
migration claim. The reviewer summary's broad migration wording is limited by the
explicit unfinished paths and native qualification matrix in this task.

The full working-source snapshot was
`2c3b35a12747a45a5cdc701bee164c3ec50931472cfbcf38bb8720b78ee8dc8e`
(445 files). The actual code-only review payload was
`1a7d5b88d13e12d15fa9e8dbd0bbd31a1495fe173fbd9a369d5a7642dced884d`
(362 files). The runner rejected source mutation and observed no source changes
during invocation. Excluded material includes binary assets/source archive,
Package.resolved files, module map, Qt resource file and Ruby snapshot verifier;
those received local native/build/integrity checks, not external review coverage.

The requested profile and recorded CLI selection match. The report exposes
`model_attribution:cli_selection`; no independent provider/backend serving-model
identity was returned. Its absence is disclosed, not invented attribution.

All three runner commands actually passed in the isolated source copy:7 Rust
facade tests,13 linked-artifact tests and103 weekly policy tests. The Rust command
used the explicitly verified installed native SDK and Cargo cache; it did not
need the sibling Core repository. Swift/Qt, actual media/model operations,
notarization, visual UI and other native targets were not executed by Gemini.

Codex assessed the empty finding list and the partial-coverage limits. Its own
second pass checked foreign buffers/handles, cooperative cancellation and truthful
publication, worker/updater exclusion, output aliases, source/model identity,
resource corruption, loader relocation and signature binding. Substantiated issues
found locally were fixed and tested before the audit; no Gemini finding required
a code fix. Later edits only record this verification/review outcome. A final
source receipt and development rebuild are recorded outside the checkout after
this documentation update; the earlier audited hash is not relabeled as reviewing
later text. No additional unchanged audit is requested solely to reset coverage.
