# Performance claim verification and remediation

Date: 2026-10-14 (America/Los_Angeles). Work is local; no version change,
remote branch/tag writes, pull requests, releases, workflow dispatches or Actions.
No required tests, reviews, timing thresholds or publication gates were added.

## Revision and evidence scope

The report is `docs/PERFORMANCE.md` as introduced by
`cd973d9c6016741129c78e875aa6e47bccbf4a87`. That commit exists and is an
ancestor of the initial checkout, `9faeeb02d1e54d03b40c7e6c50a2e733ea5b1836`.
Its actual parent, **3cf5b2b4efc3072a9ac8ab3657395069e1b6fb03**, is the
pre-optimization baseline. The current parent is not the baseline.
The intervening `f10fa87`, `9c02394`, and `9faeeb0` changes were inspected;
they retain the reported optimizations while modifying archive path protection,
Qt accessibility/session ownership, media handling, and duration validation.
Those changes remain intact. Three pre-existing untracked GitHub Actions audit
files were left untouched.

Read `AGENTS.md`, `CONTRIBUTING.md`, and `docs/development.md`. Reviewed every
requested Rust, Qt, test, benchmark and documentation file, plus EngineClient,
archive incremental saves, waveform tests, and the production macOS client.
This is an implementation and correctness audit, not a security-scan certification.

The original ignored `build/benchmark_baseline.json` and
`build/benchmark_current.json` both exist and match the report's numeric rows.
They have timestamps but no revision, build identity, repetitions, raw timings,
fixture hash or hardware metadata. Their presence does not independently verify
the original experiment. The former harness did not check many exit codes or
JSON responses, silently accepted missing core metrics, reused existing binaries,
and ignored the advertised `--compare` arguments. It did not measure Qt CPU,
wakeups, paints, leaks, or UI readiness.

## Complete disposition of report items

“Historical” numbers below are retained here for traceability, not asserted as
reproduced percentages. New measurements follow separately.

| Report item / historical claim | Implementation / evidence | Disposition | Required action / result |
|---|---|---|---|
| Startup three calls → one, 18.51 → 9.74 ms (−47.4%) | engine `Commands::Startup`; Qt constructor; `build_identity.rs` | Implementation confirmed; local improvement observed | Retain. Compare exact providers, presets, and empty/populated/corrupt recovery behavior. Correct payload key is `presets`, not report's `video_presets`. |
| Seamless older-engine fallback | Qt constructor / `EngineClient::run` | **Defect**: any error triggered legacy probes; malformed success silently converted missing fields | Fall back only for normal exit 2 and Clap's exact unknown-`startup` diagnostic. Surface protocol/execution/recovery errors; validate response shape. Fake cases and real baseline engine pass. |
| Startup hardware detection unchanged | Startup calls same `encap_transcript::providers()` and `encap_video::PRESETS` as legacy commands | Confirmed by code and payload comparisons | Preserve separate capabilities/FFmpeg behavior. No claim of detecting unavailable hardware. |
| Synchronous logging, RSS 11.63 → 7.46 “MB” (−35.9%) | `init_logging`; local `time -l build-info`, five RSS probes/run | New build-info RSS reduction observed; original attribution not independently isolated | Retain direct rotating **file** logging. It is not stdout logging. Original thread was an intentional worker, not a rogue/leaked thread. RSS is per build-info process, not application or export RSS. |
| Buffered stdout is safe and flushed | engine `main` | **Defect**: newline/flush errors ignored, potentially exit 0 with missing/truncated response | Centralize response writing; propagate serialization/write/flush failures and exit nonzero. Unit test failing writers and exact one-value/newline output; IPC/media tests pass. |
| Logging during long operations / shutdown | rotating file writer; actual media exports/cancellation and Swift pipe tests | Normal local behavior verified; slow-destination and pathological shutdown performance unavailable | Logs do not enter protocol stdout. Synchronous file writes can block on slow storage. No general latency/leak superiority claim; no slow/network-volume experiment or leak profiler was run. |
| Cold startup 72.46 → 68.58 ms (−5.3%) | old harness copied binary to a new filename once | Unsupported cold-cache claim | Remove cold label. Copying does not evict caches. New harness labels first invocation separately and excludes it from warm summaries. |
| Warm build-info 4.13 → 4.20 ms (+1.7%) | repeated child process launch | Historical variation unsupported; new samples available | Retain separate build-info metric. Do not equate it with startup aggregation or application readiness. |
| Idle timer 10 → 1 Hz (−90%) and near-zero CPU/power | Qt `clock_`, `tick`, `refreshPlayback` | Interval ratio confirmed; wakeup/CPU/power reductions are estimates | **Fix** up-to-1-second activation delay: refresh timer and playhead immediately on play, pause, seek, source selection, keyboard/system actions and async open. Deterministic clock tests pass. |
| “60 updates/s → 0”, −100% paints/layout, pixel-perfect UI | Qt value guards | Unsupported paint/layout claims; nominal setter-call calculation only | Keep redundant-update guards. Qt setters may already suppress equal values. **Fix** slider maximum-before-value ordering and status guard that failed to clear identical-message error styling. No paint-event instrumentation or pixel-level manual validation performed. |
| Waveform cancellation race fixed by `cancel()` alone | Qt `loadWaveforms`, `loadWaveformAt`; EngineClient process remains busy until completion | **Defect**: immediate replacement was rejected as busy and newest request lost | Increment generation per request, wait for obsolete completion, then start newest list. Stale results cannot update current rows. Deterministic rapid replacements, late completion and shutdown test passes. |
| Allocation-free natural comparison, 373.88 → 343.04 µs (−8.2%) | `source::natural_cmp`, sliced ASCII digit runs | Allocation elimination and intended ordering confirmed; new local improvements observed | Retain. Parent already compared digit lengths/lexically; report's description of `u64` parsing was wrong. No integer parse/overflow; tests cover long runs, leading zeros, ASCII case, Unicode, antisymmetry and transitivity. |
| WAV inspect 10.08 → 9.54 µs (−5.4%) | tracked offsets, 40-byte bounded fmt array | Optimization confirmed; new results available | Retain bounded reads/seeks. Add padding/truncated-header/oversized-chunk and extensible-header checks. No giant allocation from declared fmt length. |
| AIFF inspect 10.13 → 9.25 µs (−8.6%) | tracked offsets, bounded COMM prefix | Optimization confirmed; **correctness defects** found | Account for SSND offset before available-frame validation; reject invalid offsets/trailing headers/missing pad and unsupported AIFC compression; skip unread COMM tails. Regression tests cover odd unknown chunks, extended COMM, every supported AIFC compression tag and extensible WAV subformats. COMM reads 18 bytes for AIFF, 22 for AIFC. |
| Waveform 83.92 → 53.63 µs (−36.1%), “2-minute scan”, RMS/dynamic dispatch | `waveform::preview`, `scan_peaks`, generic `sample` | Fast paths confirmed; workload/algorithm description incorrect | Retain PCM16 LE/BE and float32 LE fast paths. Exact tests compare generic scanner across formats/endian/channel stride, partial frames, full-scale, silence and nonfinite floats; independent fixture reference validates timed results. Algorithm computes peak thumbnails, not RMS or full-file decoding. |
| Full save 17.95 → 12.98 ms (−27.7%) | `project::copy_buffered`, incremental archive writer | New medium/large improvements observed; not universal | Keep 128 KiB buffer. Small-file difference is noisy. Do not claim `io::copy` always uses 8 KiB or a measured 16× syscall reduction. No syscall trace taken. |
| Extraction 8.48 → 5.06 ms (−40.3%) | `project::extract` bounded reader/copy | New improvement observed, different validated timing scope | Preserve traversal/type/size/ratio checks, private extraction and cleanup. Timed benchmark now byte-compares extracted media and includes cleanup; not equivalent to historical extraction-only timing. |
| Incremental save 10.01 → 10.24 ms (+2.3%), APFS clone | `project_save.rs`, `archive_copy.rs`; mode-switch and 256 MiB checks | Existing optimization retained; new changes vary by size | Verify reopen, cache loss, changed media/artwork and no accumulated manifests. No speed guarantee on other filesystems. |
| Archive cancellation / failure cleanup / progress | save/open CLI previously never inspected cancellation token | **Defect**: cancel could still finish and replace project | Add cancellable variants behind unchanged normal APIs and unchanged CLI JSON. Check archive reads/writes and before replacement; private scratch cleans on cooperative cancellation. Full/incremental/extraction tests and actual SIGINT save pass. Progress remains the existing indeterminate UI; no progress-stream protocol added. OS clone/copy calls are checked before publication, not interrupted inside kernel calls. Hard kill/crash can leave private scratch; destination remains staged/atomic. |
| Audio triage 1.42 → 1.50 µs (+5.6%) | benchmark `edit_audio` | No optimization-specific benefit established | Consume and validate result; report measured variation without declaring noise bounds from one run. |
| Transcript text 11.21 → 8.58 µs (−23.4%) | `transcript.rs` capacity/trim reuse | Equivalent output confirmed; new local improvement observed | Retain; use checked reservation arithmetic. Compare 10,001 segments to legacy formatting with Unicode/empty text, speaker trimming, and newline conventions. |
| SRT 155.42 → 100.63 µs (−35.3%); matches SRT and VTT | direct timestamp `write!` | SRT equivalence confirmed; VTT claim unsupported | Retain direct formatting. Test second/minute/hour rounding, negative/nonfinite/huge values and large lists. No VTT renderer or VTT-compliance claim. |
| Qt suite 0.60 → 0.21 s (−65%); verification says 0.40 s | original JSON contains no Qt suite timing | Conflicting unsupported historical evidence | No retained logs identify these as separate runs. Withdraw both as performance evidence; do not choose the favorable number. New four-test suite timings below are validation durations only. |
| Engine size 6.83 → 6.77 MB (−1%) | original JSON 6,833,520 → 6,766,352 bytes | Historical artifact sizes only | New exact sizes recorded per build. Decimal MB differs from former harness's MiB mislabeled MB. Size change does not isolate logging causality. |
| No leaks/thread leaks, idle CPU near zero, all native targets work | original report has no leak/CPU captures or six-platform artifacts | Unverified / overbroad | Replace with explicit local passing checks and unavailable platform/hardware verification below. |
| Rayon multi-source waveform generation scales linearly with cores | current Qt serial child-process queue; measured bounded previews | Defer | No 50+-source bottleneck or foreground responsiveness profile establishes benefit. Many concurrent engine processes and existing decoder/transcription workers may oversubscribe CPU/storage. Linear scaling is unjustified. |
| SIMD peak/RMS scans 8–16 samples per cycle | 16K first-channel frames maximum in standard thumbnail; fast paths ~50 µs locally | Defer | No representative bottleneck justifies architecture-specific code. Integer/float reductions must preserve nonfinite handling and normalization, plus supported fallback. Existing generic PCM24 remains correct. No RMS calculation exists here. |
| Dirty-rect waveform repaint | Qt waveform column is cached text bars | Defer / report target mismatch | This Qt implementation has no waveform canvas/playhead animation to repaint as described. Instrument a real renderer before changing it. |
| Memory-mapped archive/source reads >500 MiB | bounded waveform windows and existing archive streams | Defer | File duration does not scale preview read budget; no measured hash/index bottleneck. Mapping adds truncation/lifetime/portability considerations without demonstrated benefit. |

## New measurement method

Same Apple M5 Max host, aarch64, Rust/compiler/environment and workspace release
profile on both revisions. Exact host/toolchain, executable size/hash, revision,
tracked-diff digest, benchmark-source hash and raw engine samples are retained in
`performance-evidence/*.json`. Baseline is an isolated detached worktree under
`build/performance-remediation/before`; current builds use a separate
`build/performance-remediation/after-target`. The corrected benchmark test file
is overlaid identically on the baseline; its library/engine sources are untouched.
The after side includes later audits and these remediations; deltas are not an
isolation of each line in cd973d9.

Dependencies are cached (`--offline --locked`). Build before measurement;
timing excludes compilation. Three standard paired runs alternate order
before/after, after/before, before/after. No concurrent builds/tests were run
during measurements. No cache eviction, CPU affinity, thermal control, or
background-system isolation was performed. Fixtures and filesystem caches are
warm. Each engine metric has 30 timed repetitions/run, with startup forms
interleaved; every exit code and complete JSON payload is checked. One first
invocation is recorded separately, not called cold. Peak RSS has five Darwin
`time -l` observations per run, in bytes, of build-info only.

Core operations have five warmups, then 30 sorting, 100 inspection, 50 waveform,
10 full-save, 30 incremental, 20 extraction, and 50 edit/text/SRT observations
per run. Core logs preserve median/P95/min/max/ops-per-second; engine JSON also
preserves individual observations. Core timing includes result validation and
destruction. Archive full-save includes destination removal; extraction includes
byte-for-byte source checks and removing extraction scratch. Fixtures are
synthetic supported PCM, not speech/media-production traces. Default four
15-second stereo 48-kHz PCM16 sources total 11,520,176 bytes (10.99 MiB).
Additional small/large cases use four 0.25-second / 120-second sources:
192,176 bytes / 92,160,176 bytes, one paired run each. Old metric names ending
`11mb` are stable identifiers; the JSON workload states the actual selected size.

The two-minute PCM16 waveform fixture is 23,040,044 bytes: 5,760,000 stereo
frames (11,520,000 samples). Each preview seeks to 64 short windows and reads
only 16,384 frames / 65,536 sample-data bytes, inspecting channel one only.
Its microseconds measure file open/header/seeks/bounded reads/peak scanning/
normalization, not processing every sample. Float/PCM24 cases exercise the same
bounded algorithm with larger frame strides. Expected peaks are computed by an
independent full-buffer reference outside timed calls. Sorting now also covers
Unicode and long digit runs; inspection includes odd-sized metadata; rendering
adds varied Unicode, whitespace, multiline and empty segments.

No statistical significance threshold is applied. Below: median of three
run-medians, with range of run-medians in brackets. Within-run tails are in JSON.
| Metric (µs unless noted) | Before median [run range] | After median [run range] | Change |
|---|---:|---:|---:|
| natural_sort_200_files | 384.542 [384.458–480.250] | 344.834 [341.541–439.750] | -10.3% |
| natural_sort_200_mixed_unicode | 487.666 [479.458–516.667] | 455.209 [452.791–493.625] | -6.7% |
| inspect_wav_10s_audio | 10.291 [10.125–11.000] | 9.250 [9.167–9.958] | -10.1% |
| inspect_aiff_10s_audio | 10.542 [10.084–10.584] | 10.000 [9.708–10.542] | -5.1% |
| inspect_wav_odd_metadata | 11.458 [11.333–11.583] | 9.625 [9.625–10.958] | -16.0% |
| waveform_preview_2min_wav | 75.042 [72.459–81.959] | 51.458 [49.917–52.833] | -31.4% |
| waveform_preview_pcm24_stereo | 84.125 [79.708–84.708] | 83.709 [82.834–84.916] | -0.5% |
| waveform_preview_float32_stereo | 80.917 [80.208–84.542] | 54.000 [51.125–54.583] | -33.3% |
| project_first_save_11mb | 17945.000 [17945.000–18127.000] | 13032.000 [12992.000–14847.000] | -27.4% |
| project_incremental_metadata_save | 10858.000 [10644.000–11038.000] | 10822.000 [10351.000–11117.000] | -0.3% |
| project_load_and_extract | 9835.000 [9721.000–9850.000] | 5197.000 [4737.000–7050.000] | -47.2% |
| audio_edit_triage_cut | 1.458 [1.416–1.459] | 1.500 [1.500–1.583] | +2.9% |
| render_transcript_text_1000_segments | 17.958 [16.708–18.125] | 14.541 [14.209–15.208] | -19.0% |
| render_srt_1000_segments | 175.709 [174.833–177.167] | 108.084 [106.875–111.208] | -38.5% |
| render_transcript_unicode_variable | 12.583 [12.292–12.667] | 11.208 [10.917–11.333] | -10.9% |
| render_srt_unicode_variable | 177.500 [177.041–177.625] | 110.500 [109.708–111.709] | -37.7% |
| warm build-info (ms) | 4.132 [4.083–4.173] | 3.917 [3.891–4.020] | -5.2% |
| legacy → unified (ms) | 17.964 [17.925–18.180] | 8.555 [8.524–9.009] | -52.4% |
| project_first_save_11mb (small, ms) | 9.763 | 9.906 | +1.5% |
| project_incremental_metadata_save (small, ms) | 11.016 | 11.042 | +0.2% |
| project_load_and_extract (small, ms) | 2.303 | 2.063 | -10.4% |
| project_first_save_11mb (large, ms) | 76.140 | 32.214 | -57.7% |
| project_incremental_metadata_save (large, ms) | 10.386 | 10.835 | +4.3% |
| project_load_and_extract (large, ms) | 66.272 | 25.191 | -62.0% |

Median build-info RSS across the three run medians: 11,845,632 → 7,618,560
bytes (−35.7%). Within-run RSS samples and ranges are retained. Fresh engine
sizes are 6,849,952 → 6,816,496 bytes (−0.49%). These measurements do not prove
anything about full-app peak memory or long-running logging throughput.
The small first-save result (+1.5%) and incremental variations have overlapping
normal timing variation; no universal buffer benefit or significant regression
is established. Keep the buffer given the consistent medium/large improvement.
The 256 MiB diagnostic separately passed: first save 52.93 ms, metadata saves
8.72–9.66 ms, first reopened save 30.60 ms; its 2.59-second full-deflate comparison
is an existing exploratory path, not the pre-cd973d9 application baseline.

## Validation commands and outcomes

All paths below are relative to the repository root. Detailed output lives under
`build/performance-remediation/`; selected evidence is committed under
`docs/audits/performance-evidence/`. Failed diagnostics remain visible.

| Exact command / procedure | Result |
|---|---|
| `cargo test --workspace --locked --offline` | **Passed: 89 passed, 0 failed, 7 ignored.** `rust-final.log`; includes core equivalence, archive integrity/failure/cancellation and engine protocols. |
| `cargo test -p encap-engine --test build_identity --locked --offline` | **Passed: 3/3**, after isolating test recovery paths; null, populated and corrupt journal checks. `startup-final.log`. |
| `cmake -S qt -B build/performance-remediation/qt -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=/opt/homebrew` | **Passed**, actual new Release tree; CMakeCache identifies this checkout's `qt` directory. |
| `cmake --build build/performance-remediation/qt --config Release -j 6` | **Passed**, builds application plus all CTest executables. |
| `ENCAP_TEST_ENGINE="$PWD/target/release/encap-engine" ctest --test-dir build/performance-remediation/qt -C Release --output-on-failure` | **Passed: 4/4, 1.52 s** final run; real import/save/reopen enabled, not skipped by an unset engine variable. |
| `ENCAP_TEST_ENGINE="$PWD/build/performance-remediation/before/target/release/encap-engine" ctest --test-dir build/performance-remediation/qt -C Release --output-on-failure` | **Passed: 4/4, 1.35 s**; real older-engine fallback plus protocols. |
| `ENCAP_SOURCE_ROOT="$PWD" CARGO_NET_OFFLINE=true DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer ./script/build_and_run.sh --verify` | **Passed**: production Xcode SwiftUI app builds/stages/signs locally/launches; packaged-runtime provenance/dependencies checked; all 5 ignored media-contract tests run and pass; audio-edit/save protocol tests pass; Swift XCTest **30/30**, including new real-engine client test and physical host WAV playback test. No new release package published. |
| Production process inspection | Actual new `dist/EnCap.app/Contents/MacOS/EnCap` process observed with start time matching the launch, not merely an older process with the same name. |
| `cargo test --release --locked --offline -p encap-core --target-dir build/performance-remediation/after-target benchmark_large_project_saves -- --ignored --nocapture` | **Passed: 1 ignored diagnostic explicitly executed**, 256 MiB saves/reopen; other filtered test executables printed zero matching tests, which are not counted as passes. |
| `python3 -m unittest discover -s script -p test_benchmark.py -v` | **Passed: 4/4**; failed process/missing metrics rejected, exact legacy fallback classification, statistics/units, compare performs no builds/runs. |
| `python3 script/benchmark.py --compare build/performance-remediation/before-1.json build/performance-remediation/after-1.json` | **Passed**, reads saved schema-2 results only; compares workload/build provenance. |
| Actual CLI save cancellation | Built release engine saving a changed 1 GiB sparse WAV; send SIGINT after observing private staging. **Passed**: nonzero single JSON error, original valid archive byte-identical, staging directory removed (`archive-signal.log`). |
| `cargo fmt --all --check` | **Failed**, pre-existing formatting in untouched `encap-audio/src/lib.rs`, `encap-core/src/file_ops.rs`, `encap-core/src/model.rs`, `encap-ffmpeg/src/runtime.rs`, `encap-transcript/src/lib.rs`. Changed Rust files were individually rustfmt-formatted. No broad cleanup was retained. |
| `cargo clippy --workspace --all-targets --locked --offline -- -D warnings` | **Failed**, existing `manual_range_contains` in `encap-core/src/model.rs:19`, present at initial HEAD. Diagnostic-only run without `-D warnings` finishes and retains that warning. No assertions/lints were suppressed. |
| `git diff --check` | **Passed**. |

Seven default ignored tests comprise the five approved-runtime/media tests, the
existing 256 MiB archive diagnostic and the comprehensive performance diagnostic.
All were explicitly exercised locally. The comprehensive test is now explicitly
ignored by default because its timings are opt-in diagnostics, not pass/fail
performance gates; correctness is covered by ordinary regression tests. Native
Swift's secondary Testing-library runner reports zero tests; the actual XCTest
runner reports 30, and those are the counted tests. Xcode emitted its existing
App Intents metadata-extraction warning; it did not prevent the build.

No Windows/Linux native execution, Intel hardware, old macOS 13 runtime, removable/
network storage, GPU/encoder matrix, long-duration load, power sampling, exhaustive
leak analysis, screen-reader manual interaction, pixel accuracy or repaint tracing
was performed. macOS Qt is an internal reference; its build alone is not production
macOS verification, hence the separate production SwiftUI checks. Native window
startup and a production EngineClient round trip are functional smoke evidence,
not a measured end-to-end readiness benchmark. Forced Windows process-tree kill
and other hard crashes bypass RAII cleanup; atomic replacement still protects
valid archives, but private scratch cleanup on those paths needs platform testing.

## Local implementation commits

- `d6235a2`: engine response handling, bounded parsing, safe project cancellation,
  output-equivalence tests and production macOS EngineClient smoke test.
- `ebdc76e`: extensible WAV and supported AIFC parser/preview regressions.
- `77e1c09`: Qt startup fallback, newest waveform scheduling, immediate clock
  updates, value-guard corrections and deterministic process/UI tests.

The benchmark/evidence/documentation changes are a separate local signed-off
commit, reported in the final delivery. Benchmark captures identify the original
HEAD plus a dirty-diff digest because measurement preceded these local commits;
the measured production code is the committed remediation implementation. Later
format-variant/individual-sample additions change test coverage only.

## Reproducing the local comparison

Create a detached **local** worktree from the stated pre-optimization revision,
copy only the current benchmark test to it, and use separate build directories.
Do not push or dispatch workflows. Example for the first pair:

```sh
git worktree add --detach build/performance-remediation/before 3cf5b2b4efc3072a9ac8ab3657395069e1b6fb03
cp crates/encap-core/tests/benchmarks.rs build/performance-remediation/before/crates/encap-core/tests/benchmarks.rs
python3 script/benchmark.py --repo build/performance-remediation/before --target-dir build/performance-remediation/before/target --output build/performance-remediation/before-1.json --repetitions 30
python3 script/benchmark.py --target-dir build/performance-remediation/after-target --output build/performance-remediation/after-1.json --repetitions 30
python3 script/benchmark.py --compare build/performance-remediation/before-1.json build/performance-remediation/after-1.json
```

The existing audit worktree can be reused instead of recreating it. Repeat twice
more in alternating order for run variability. For the additional archive sizes,
set `ENCAP_BENCH_PROJECT_SECONDS=0.25` or `ENCAP_BENCH_PROJECT_SECONDS=120` on
**both** invocations. The harness always refreshes Release binaries, consumes
responses, validates all 16 core metrics, and rejects incomplete/error output.
It does not measure Qt or reuse a guessed Qt bundle path for binary sizes.
Historical schema-1 JSON is intentionally rejected by comparison because it lacks
workload/build provenance. Review those old numbers as historical claims only.

Evidence: ten new JSON runs and their core output, summary/comparison tables,
selected passing and failed validation logs, and original-artifact SHA-256 values
are committed in `performance-evidence/`. Full production, workspace, configuration
and build logs remain in the ignored build directory; they are supporting local
logs, not a guarantee that future checkouts possess those generated files. Exact
benchmark fixture code and tests are committed so the experiment is reproducible.

No Rayon, SIMD, rendering migration, dependency change, version bump, feed/signature
weakening, release artifact, remote write or CI policy gate was introduced.
