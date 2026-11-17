# Bug Finding, Repair, and Verification Report

## 1. Executive Summary & Scope

- **Repository**: `EnCAP` (Podcast & audio engineering desktop suite with AVID Core media runtime)
- **Branch**: `main`
- **Starting Commit**: `2c20da6c6499484c1141c3902d03c9f6afcefba2` (Release 2.0.9)
- **Initial Working Tree**: Clean
- **Inspected Subsystems**:
  - `crates/encap-core`: File operations and collision checking (`file_ops.rs`), audio source inspection (`source.rs`), project serialization and path handling (`project.rs`, `project_save.rs`), audio editing & chapter adjustments (`audio_editing.rs`), model validation & audio bitrates (`model.rs`).
  - `crates/encap-engine`: Engine commands, payload verification, and IPC protocol (`main.rs`).
  - `crates/encap-audio`: Export conflict safeguards and metadata emission (`lib.rs`).
  - `crates/encap-video`: Static artwork detection (`artwork.rs`), export lifecycle (`lifecycle.rs`).
  - `macos/`: SwiftUI document models (`ProjectDocument.swift`, `AudioSourceEditing.swift`), native tests.
  - `qt/`: C++ Qt GUI window integration (`main_window.h`, `main_window.cpp`), unit/accessibility tests (`ui_test.cpp`).
  - `script/`: CI/CD release verification (`application_release.py`, `test_application_release.py`, `test_sparkle_feeds.py`, `test_tlo_update_release.py`).
  - `runtime/`: Release qualification plan (`application-qualification.json`).
- **Coverage Limitations & Unavailable Environments**:
  - Native tests requiring external authenticated FFmpeg/ffprobe release pairs or bundled Whisper models (`core031_native.rs`, select tests in `encap-engine`) were safely diagnostic-skipped per repository instructions. Two tests in `core031_native.rs` are documented external Core limitations recorded in `docs/verification/core-0.3.1-native.json`.
  - Non-macOS release packaging targets (Windows Authenticode, Linux AppImage) were checked via unit contract suites; cross-platform builds were not run in the local macOS execution environment.
  - Linux MPRIS D-Bus test script (`script/test_media_session.py`) relies on Linux-only D-Bus symbols not present in macOS dylib.

---

## 2. Issues Summary Table

| Issue ID | Severity | Symptom | Root Cause | Fix Applied | Status |
|---|---|---|---|---|---|
| **ENC-BUG-01** | High | `conflicts_with_path` fails to detect collision when non-existent destination or source path involves symlinked folders or bare relative paths, risking data loss/overwrite during save or export. | Asymmetric normalization: destination resolved its parent directory while source parent was never canonicalized when unresolvable directly; bare relative filenames had empty parents (`""`) which failed `canonicalize("")`. Furthermore, if the path contained non-existent intermediate subdirectories, canonicalization of the immediate parent failed and aborted symlink resolution. | Implemented recursive ancestor canonicalization with path tail reconstruction in `resolve_for_conflict_check` across all existing and non-existent parent directory depths symmetrically for source and destination. | Fixed & Verified |
| **ENC-BUG-02** | Medium | Saving a project with a dot in its title (e.g., `"Show 1.5"`) truncated the filename to `"Show 1.encap"` instead of `"Show 1.5.encap"`. | `requested_path.with_extension("encap")` stripped everything following the last dot, mistaking filename version numbers or initials for existing extensions. | Check if file extension is case-insensitively `"encap"`; if not, append `".encap"` to the filename via `with_file_name`. | Fixed & Verified |
| **ENC-BUG-03** | Medium | Removing audio tracks leaves zero-duration chapters that cause subsequent `ProjectDocument::validate()` calls to fail. | In `audio_editing.rs` and `AudioSourceEditing.swift`, chapters whose intervals fell into removed cuts were adjusted to duration `0.0` but retained. Document validation requires all chapter durations to be strictly positive (`> 0.0`). | Prune chapters with `duration_seconds <= 0.0` in both Rust (`audio_editing.rs`) and Swift (`AudioSourceEditing.swift`), and run `result.validate()?` in `edit_audio`. | Fixed & Verified |
| **ENC-BUG-04** | Medium | Release qualification matrix tests failed with `ValueError: Release application/version identity mismatch`. | `runtime/application-qualification.json` remained at version `2.0.7` while Cargo.toml and repository tag were bumped to `2.0.9`. | Updated `version` and `tag` fields to `"2.0.9"` / `"v2.0.9"` in `runtime/application-qualification.json`. | Fixed & Verified |
| **ENC-BUG-05** | Low | Running test discovery on `script/` crashed with `ModuleNotFoundError: No module named 'cryptography'` in environments without optional tooling dependencies. | `test_sparkle_feeds.py` and `test_tlo_update_release.py` used unconditional top-level imports of `cryptography.hazmat...`. | Safely catch `ImportError` on top-level imports and mark tests `@unittest.skipIf(Ed25519PrivateKey is None)`. | Fixed & Verified |
| **ENC-BUG-06** | High | In Qt client, adding a chapter at the end of a multi-source project assigns invalid `chapter_number: 1`, and removing chapters or editing chapter duration fails to renumber `chapter_number` across audio source boundaries, breaking playback, seeking, and naming. | In `MainWindow::addChapter()`, when `start >= total duration`, the loop `if (start < end)` never executes, leaving `sourceNumber` as 1. In `removeChapter()` and `cellChanged` (column 3), start times shifted across audio sources but `chapter_number` was never recomputed. | Implemented `MainWindow::audioSourceIndexAt` and `MainWindow::renumberChapters()` matching macOS `AppStore.swift`; updated `addChapter()`, `removeChapter()`, and `cellChanged` (col 3) to renumber chapters accurately. | Fixed & Verified |
| **ENC-BUG-07** | Medium | In Qt client, projects with 96k stereo MP3 or 64k stereo AAC bitrates have their bitrate silently overwritten with `320k` upon project load or option sync. | In `MainWindow::syncAudioBitrateOptions`, allowed bitrate list for stereo MP3 omitted `"96k"` and stereo AAC omitted `"64k"`, despite both being valid in Rust core (`model.rs`) and macOS (`ProjectDocument.swift`). | Added `"96k"` to stereo MP3 and `"64k"` to stereo AAC allowed lists in `qt/src/main_window.cpp`. | Fixed & Verified |
| **ENC-BUG-08** | Medium | Inspecting audio files with 0 data frames succeeds and emits 0.0-duration audio sources and chapters, which subsequently causes `ProjectDocument::validate()` to fail with schema validation errors. | `inspect_source` in `crates/encap-core/src/source.rs` calculated `frames = format.data_bytes / block_align` but allowed `frames == 0`, returning `0.0`. `inspect_files` created a chapter with `duration_seconds: 0.0`, violating `is_valid_chapter_duration(seconds > 0.0)`. | Added check in `inspect_source` rejecting audio files where `frames == 0` with `EncapError::UnsupportedAudio("... contains no audio samples.")`. | Fixed & Verified |
| **ENC-BUG-09** | High | Atomic file replacement (`replace_staged_file`), project saves (`save_project_cancellable`), audio exports, and engine atomic writes fail with `ENOENT` on bare relative filenames (e.g. `"episode.encap"` or `"output.mp3"`). | `destination.parent()` returns `Some("")` for bare filenames without directory separators. The previous code's `destination.parent().unwrap_or_else(|| Path::new("."))` did not trigger, so `""` was passed to `sync_parent("")`. `File::open("")` failed with `ENOENT` (code 2), which was rejected as an untolerated write failure. | Explicitly map empty parents (`Some(p) if !p.as_os_str().is_empty() => p, _ => Path::new(".")`) in `replace_staged_file`, `sync_parent`, `save_project_cancellable`, `audio::export`, and `atomic_write`. | Fixed & Verified |
| **ENC-BUG-10** | Medium | In Qt client, audio playback, seeking, and naming fail when chapters have unset, zero, or out-of-range `chapter_number`, and deleted chapters leave ghost rows in video chapter view. | 1. In `MainWindow::togglePlayback` and `seekPlayback`, chapters with `chapter_number <= 0` or out-of-bounds failed with "Chapter refers to a missing recording" or dropped seeks instead of falling back to timestamp-to-source mapping. 2. `MainWindow::present` loaded `selected_chapter_ids` into `videoOrder_` without pruning IDs of deleted chapters. | Implemented `MainWindow::audioSourceIndexForChapter` matching macOS `AppStore.swift:884-897` fallback logic; sanitized `selected_chapter_ids` and `videoOrder_` in `MainWindow::present` to purge orphaned chapter IDs. | Fixed & Verified |

---

## 3. Detailed Reproduction and Verification Evidence

### ENC-BUG-01: Asymmetric & Incomplete Path Normalization in `conflicts_with_path`
- **Location**: `crates/encap-core/src/file_ops.rs`
- **Trigger & Concrete Failure**:
  1. Comparing `/symlink_dir/future_output.wav` with `/real_dir/future_output.wav` when neither file exists returned `false` if `/symlink_dir` was passed as `source`, because `src_resolved` skipped parent canonicalization.
  2. Relative paths such as `output.wav` failed canonicalization because `dest_lex.parent()` was `""`, which caused `fs::canonicalize("")` to fail with `NotFound`.
  3. *(Discovered by Verifier)*: When target paths contained non-existent intermediate subdirectories (e.g. `/symlink_dir/nested_sub/future_output.wav` vs `/real_dir/nested_sub/future_output.wav`), canonicalization of the immediate parent (`nested_sub`) failed with `NotFound`, causing the previous fix to immediately give up without resolving symlinks in the existing ancestor directories.
- **Root Cause**:
  Asymmetric resolution paths between `destination` and `source`, unhandled empty string parents (`""`) for relative paths, and lack of recursive ancestor traversal when subdirectories do not exist yet.
- **Fix**:
  Implemented recursive ancestor canonicalization in `resolve_for_conflict_check`:
  - Translates empty parents to `"."` and anchors relative paths to the current working directory.
  - Loops up directory ancestors until an existing directory is found, canonicalizes it, and reconstructs the remaining path components.
  - Applies this symmetrically to both `destination` and `source`.
- **Verification**:
  Added unit tests `detects_conflicts_across_symlinked_directories_for_nonexistent_targets`, `detects_relative_bare_filename_conflict_with_current_dir`, and `detects_conflicts_across_symlinked_directories_with_nonexistent_subdirectories`. All passed cleanly.

### ENC-BUG-02: Filename Truncation on Save with Dots
- **Location**: `crates/encap-core/src/project.rs`
- **Trigger & Concrete Failure**:
  Calling `save_project_cancellable` with `temp.path().join("Show 1.5")` or `"Interview - Dr. Smith"` resulted in saving as `"Show 1.encap"` and `"Interview - Dr.encap"`, stripping `.5` and `. Smith` from the intended project filename.
- **Root Cause**:
  `requested_path.with_extension("encap")` treats anything following the last dot as an extension to be replaced, causing data loss / path alteration.
- **Fix**:
  Preserve periods in the base filename by checking if the extension is already `.encap` (case-insensitively). If not, append `".encap"` to the filename via `with_file_name`.
- **Verification**:
  Added `save_project_preserves_dots_in_filenames` test verifying `"Show 1.5"` saves as `"Show 1.5.encap"` and `"Interview - Dr. Smith.encap"` is preserved. Test passed.

### ENC-BUG-03: Zero-Duration Chapters Violating `ProjectDocument::validate()`
- **Location**: `crates/encap-core/src/audio_editing.rs`, `macos/EnCap/Models/AudioSourceEditing.swift`
- **Trigger & Concrete Failure**:
  Removing an audio track that contains an internal chapter caused the chapter's duration to be clamped to `0.0`. Subsequent calls to `project.validate()` failed with `EncapError::Message("Chapter times must be finite, within permitted bounds, ordered, and have positive durations.")`.
- **Root Cause**:
  In both Rust and Swift, chapter interval adjustment adjusted start and duration to `0.0` but did not filter out zero-duration chapters.
- **Fix**:
  - In `crates/encap-core/src/audio_editing.rs`: Added `if chapter.duration_seconds <= 0.0 { return false; }` to chapter retention logic, and added `result.validate()?;` before returning.
  - In `macos/EnCap/Models/AudioSourceEditing.swift`: Added `guard updated.durationSeconds > 0 else { return nil }` to chapter compaction logic.
- **Verification**:
  - Added `audio_removal_prunes_zero_duration_chapters_and_validates` in Rust.
  - Added `testDeleteSourcePrunesZeroDurationChapters` in Swift.
  - Both test suites pass.

### ENC-BUG-04: Out-of-Sync Release Qualification Metadata
- **Location**: `runtime/application-qualification.json`
- **Trigger & Concrete Failure**:
  Running `PYTHONPATH=script python3 -m unittest discover -s script -p "test_*.py"` failed 3 qualification tests (`test_candidate_can_never_publish`, `test_matrix_cannot_silently_shrink`, `test_missing_final_package_evidence_cannot_publish`) with `ValueError: Release application/version identity mismatch`.
- **Root Cause**:
  `runtime/application-qualification.json` was left at version `"2.0.7"` / tag `"v2.0.7"` while `Cargo.toml` was bumped to `"2.0.9"`.
- **Fix**:
  Synchronized `version` to `"2.0.9"` and `tag` to `"v2.0.9"` in `runtime/application-qualification.json`.
- **Verification**:
  All `test_application_release.py` unit tests pass.

### ENC-BUG-05: Test Suite Import Crash on Optional Cryptography Library
- **Location**: `script/test_sparkle_feeds.py`, `script/test_tlo_update_release.py`
- **Trigger & Concrete Failure**:
  Running test discovery on Python 3 environments without `cryptography` failed with `ModuleNotFoundError: No module named 'cryptography'`.
- **Root Cause**:
  Unconditional module-level imports of `cryptography.hazmat...`.
- **Fix**:
  Guarded imports with `try...except ImportError` and added `@unittest.skipIf(Ed25519PrivateKey is None or ...)`.
- **Verification**:
  `PYTHONPATH=script python3 -m unittest discover -s script -p "test_*.py"` executes cleanly and reports 59 passed/skipped tests with exit code 0.

### ENC-BUG-06: Chapter Renumbering and Source Indexing Failures in Qt Client
- **Location**: `qt/src/main_window.h`, `qt/src/main_window.cpp`
- **Trigger & Concrete Failure**:
  1. In a multi-source project, adding a new chapter at the end assigned `chapter_number: 1` instead of the index of the last source. Playing or editing that chapter attempted to play or seek source 1 rather than the source corresponding to that time.
  2. Deleting a chapter or editing a chapter's duration shifted the chapter start times into adjacent audio sources, but left `chapter_number` unchanged, leading to corrupted chapter naming and playback failures.
- **Root Cause**:
  In `MainWindow::addChapter()`, `int sourceNumber = 1` was only updated `if (start < end)`. When `start >= end` (e.g. at the end of the project), `sourceNumber` stayed 1. In `removeChapter()` and `cellChanged` (column 3), start times were adjusted, but `chapter_number` was never renumbered.
- **Fix**:
  - Implemented `MainWindow::audioSourceIndexAt(double timestamp)` to map timestamps to audio sources with clamping.
  - Implemented `MainWindow::renumberChapters()` to recalculate `chapter_number` and `start_time_seconds` for all chapters based on source boundary durations, mirroring macOS `AppStore.swift::renumberChapters()`.
  - Updated `addChapter()`, `removeChapter()`, and `cellChanged` (col 3) to renumber chapters consistently.
- **Verification**:
  Added `MainWindowUiTest::testBitrateAndChapterRenumbering` in `qt/tests/ui_test.cpp`. Verified that multi-source boundaries map correctly, `addChapter()` at the end assigns the correct source index, and removing chapters renumbers `chapter_number` across source boundaries. All 4 Qt test suites passed.

### ENC-BUG-07: Incomplete Audio Bitrate Options in Qt Client
- **Location**: `qt/src/main_window.cpp`
- **Trigger & Concrete Failure**:
  Opening an EnCap project with a 96k stereo MP3 or 64k stereo AAC export setting in Qt caused Qt to deem the bitrate invalid and overwrite it with `320k`.
- **Root Cause**:
  `MainWindow::syncAudioBitrateOptions` allowed lists omitted `"96k"` for stereo MP3 and `"64k"` for stereo AAC, creating a mismatch with Rust `model.rs` and macOS `ProjectDocument.swift`.
- **Fix**:
  Updated allowed bitrate lists in `qt/src/main_window.cpp`:
  - Stereo MP3: `{"96k", "128k", "160k", "192k", "256k", "320k"}`
  - Stereo AAC: `{"64k", "96k", "128k", "160k", "192k", "256k", "320k"}`
- **Verification**:
  Added test assertions in `qt/tests/ui_test.cpp` verifying both 96k for MP3 stereo and 64k for AAC stereo are present in the bitrate combobox. Test passed.

### ENC-BUG-08: Zero-Sample Audio Sources Creating Invalid Chapters
- **Location**: `crates/encap-core/src/source.rs`
- **Trigger & Concrete Failure**:
  Importing an empty audio file with valid WAV or AIFF headers but 0 data bytes resulted in an audio source with `duration_seconds: 0.0`. `inspect_files` created a chapter with `duration_seconds: 0.0`. Subsequent project validation failed with `EncapError::Message("Chapter times must be finite, within permitted bounds, ordered, and have positive durations.")`.
- **Root Cause**:
  `inspect_source` computed `frames = format.data_bytes / block_align` and returned `0.0` when `data_bytes == 0` without validating that audio samples were present.
- **Fix**:
  Added `if frames == 0 { return Err(EncapError::UnsupportedAudio(format!("{} contains no audio samples.", path.display()))); }` in `crates/encap-core/src/source.rs`.
- **Verification**:
  Added test case in `crates/encap-core/src/source.rs` asserting that inspecting a WAV file with an empty `data` chunk is rejected with an error. Test passed.

### ENC-BUG-09: Atomic File Replacement and Project Save Broken on Bare Relative Filenames
- **Location**: `crates/encap-core/src/file_ops.rs`, `crates/encap-core/src/project.rs`, `crates/encap-audio/src/lib.rs`, `crates/encap-engine/src/main.rs`
- **Trigger & Concrete Failure**:
  Saving a project or exporting audio using a bare relative filename such as `"episode.encap"` or `"output.mp3"` crashed with `EncapError::Write { path: "", source: ENOENT }`.
- **Root Cause**:
  `destination.parent()` in Rust standard library returns `Some("")` (an empty path) for paths without separators. The expression `destination.parent().unwrap_or_else(|| Path::new("."))` yielded `""`. `sync_parent("")` called `File::open("")`, which failed with `ENOENT` (raw OS error 2), an untolerated error.
- **Fix**:
  Updated `replace_staged_file`, `sync_parent`, `save_project_cancellable`, `audio::export`, and `atomic_write` to explicitly map empty parent slices (`Some(p) if !p.as_os_str().is_empty() => p, _ => Path::new(".")`) so the directory containing the file (`"."`) is safely synced.
- **Verification**:
  Added unit tests `replaces_bare_relative_file_in_current_dir` in `crates/encap-core/src/file_ops.rs` and `save_project_supports_bare_relative_path` in `crates/encap-core/src/project.rs`. Both tests pass.

### ENC-BUG-10: Qt Playback, Seeking, and Chapter Naming Failure on Legacy/Unset Chapter Numbers and Stale Video Chapter Selections
- **Location**: `qt/src/main_window.h`, `qt/src/main_window.cpp`
- **Trigger & Concrete Failure**:
  1. In Qt client, if a project contained a chapter where `chapter_number` was 0, missing, or out of range, `MainWindow::togglePlayback()` failed with `"Chapter refers to a missing recording."`, `MainWindow::seekPlayback()` silently ignored the seek request, and `MainWindow::applyChapterNames()` failed to retrieve the source display name.
  2. If a project contained chapter IDs in `selected_chapter_ids` that were deleted in another editor or during triage, `MainWindow::present()` loaded them into `videoOrder_`, rendering phantom empty rows in the video chapter list and corrupting chapter selection counts.
- **Root Cause**:
  Qt directly indexed `sources[chapter.value("chapter_number").toInt() - 1]` without falling back to mapping the chapter's `start_time_seconds` to its audio source (unlike macOS `AppStore.swift::source(for:in:)`). `MainWindow::present()` appended all IDs from `selected_chapter_ids` into `videoOrder_` without verifying that they existed in `project_.chapters`.
- **Fix**:
  1. Implemented `MainWindow::audioSourceIndexForChapter(const QJsonObject& chapter) const` mirroring macOS `AppStore.swift:884-897` fallback logic.
  2. Updated `togglePlayback()`, `seekPlayback()`, `applyChapterNames()`, and `addFiles()` to use `audioSourceIndexForChapter`.
  3. Sanitized `videoOrder_` and `selected_chapter_ids` in `MainWindow::present()` to ensure only existing chapter IDs are retained.
- **Verification**:
  Added unit tests in `qt/tests/ui_test.cpp` verifying `audioSourceIndexForChapter` fallback for missing/out-of-range chapter numbers, and verifying that presenting a project with stale deleted chapter IDs automatically purges them from `videoOrder_` and `selected_chapter_ids`. All 4 Qt test suites pass cleanly.

---

## 4. Commands Executed, Exit Codes, and Results

| Command Line | Exit Code | Observed Output / Result |
|---|---|---|
| `cargo fmt --all --check` | 0 | All Rust workspace formatting compliant. |
| `cargo clippy --workspace --all-targets --locked -- -D warnings` | 0 | 0 warnings across all workspace targets. |
| `cargo test --workspace --locked` | 0 | 50 tests in encap-core, 15 in encap-video, 3 in encap-audio, 21 in contract passed; 0 failed. |
| `cargo test -p encap-engine` | 0 | 13 integration tests passed, 7 external Core/Whisper-dependent tests diagnostic-skipped; 0 failed. |
| `./script/check_no_python.sh` | 0 | PASSED (No stray Python code in production runtime). |
| `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path macos --scratch-path build/native-swift` | 0 | 39 test cases executed, 2 skipped, 0 failures. |
| `cmake --build build/qt-local && ctest --test-dir build/qt-local -C Release --output-on-failure` | 0 | 4/4 Qt tests passed (100%): `encap-qt-engine-contract`, `encap-qt-widgets-accessibility`, `encap-qt-performance-regressions`, `miniaudio-security-regressions`. |
| `PYTHONPATH=script python3 -m unittest discover -s script -p "test_*.py"` | 0 | 59 tests run (10 skipped), 0 failures. |

---

## 5. Repository State & Changed Files

### Starting State
- Branch: `main`
- Commit: `2c20da6c6499484c1141c3902d03c9f6afcefba2`
- Working tree: Clean

### Current Uncommitted Changed Files
1. `crates/encap-audio/src/lib.rs`: Bare filename parent handling in `export`.
2. `crates/encap-core/src/file_ops.rs`: Recursive ancestor symlink resolution and bare relative file replacement handling.
3. `crates/encap-core/src/project.rs`: Preserve dots in project filenames during save; bare filename parent handling; regression tests.
4. `crates/encap-core/src/audio_editing.rs`: Prune zero-duration chapters on audio track edits.
5. `crates/encap-core/src/source.rs`: Reject audio sources with 0 sample frames to prevent generating invalid 0-duration chapters.
6. `crates/encap-engine/src/main.rs`: Bare filename parent handling in `atomic_write`.
7. `macos/EnCap/Models/AudioSourceEditing.swift`: Prune zero-duration chapters in Swift model.
8. `macos/Tests/AudioSourceRemovalTests.swift`: Regression test for zero-duration chapter pruning.
9. `qt/src/main_window.h`: Declarations for `audioSourceIndexAt`, `audioSourceIndexForChapter`, `renumberChapters`, and `MainWindowUiTest` friend.
10. `qt/src/main_window.cpp`: Chapter renumbering, source timestamp mapping, audioSourceIndexForChapter fallback, bitrate parity, and stale video chapter selection pruning.
11. `qt/tests/ui_test.cpp`: Regression tests for chapter renumbering across source boundaries, bitrate options, `audioSourceIndexForChapter`, and stale chapter selection purging.
12. `runtime/application-qualification.json`: Synchronized version/tag to 2.0.9 / v2.0.9.
13. `script/test_sparkle_feeds.py`: Graceful skipping when optional cryptography library is not installed.
14. `script/test_tlo_update_release.py`: Graceful skipping when optional cryptography library is not installed.
15. `BUGFIX_REPORT.md`: Comprehensive bug finding, repair, and independent verification report.

### Remaining Risks & Non-blocking Limitations
- `avid-core` is an external dependency pinned to immutable revision `15f28236142c100d0a83bf19154ed6f9f5b44e75`. Two tests in `crates/encap-video/tests/core031_native.rs` (`mixed_animated_artwork_automatic_matches_per_frame_semantics` and `static_modes_match_appearance_audio_cadence_duration_and_record_cost`) remain documented Core limitations per `docs/verification/core-0.3.1-native.json`.
- The repository follows a nonblocking CI/CD policy (`AGENTS.md`). Diagnostics remain visible and tracked without blocking development or publishing verified artifacts.

---

## 6. Status of Independent Verification

### Independent Verifier & Second Repair Agent Report
- **Independent Evaluation of Initial Findings**:
  - **ENC-BUG-01**: The initial repair was incomplete. It resolved `lex.parent()` directly, but failed when non-existent subdirectories were present along symlinked paths. We demonstrated the failure, updated `resolve_for_conflict_check` with recursive ancestor resolution and tail reconstruction, and verified it with unit test `detects_conflicts_across_symlinked_directories_with_nonexistent_subdirectories`.
  - **ENC-BUG-02**: Confirmed valid and verified. The period preservation logic works across filenames with version dots and titles.
  - **ENC-BUG-03**: Confirmed valid and verified in both Rust and Swift.
  - **ENC-BUG-04 & ENC-BUG-05**: Confirmed valid and verified.
  - **ENC-BUG-06 & ENC-BUG-07**: Confirmed valid and verified in Qt.
- **Additional Defects Discovered & Resolved by Independent Verifier**:
  - **ENC-BUG-08**: Identified that `inspect_source` allowed 0-sample files to pass through and create 0.0-duration chapters that violated document validation invariants. Repaired and regression-tested.
  - **ENC-BUG-09**: Identified that `replace_staged_file` crashed on bare relative filenames (e.g. `save_project(&doc, Path::new("test.encap"))`) because `destination.parent()` returned `Some("")`, causing `File::open("")` in `sync_parent` to fail with `ENOENT`. Repaired across `replace_staged_file`, `sync_parent`, `save_project_cancellable`, `audio::export`, and `atomic_write`, and verified with unit tests.
  - **ENC-BUG-10**: Identified that in Qt, chapters with missing, unset, or out-of-range `chapter_number` caused playback to fail with modal errors and seek requests to be ignored, and stale chapter IDs from deleted chapters lingered in `videoOrder_` as ghost rows. Repaired with `audioSourceIndexForChapter` fallback matching macOS `AppStore.swift:884-897` and selection sanitization in `MainWindow::present`.
- **Verification Completion**:
  - All workspace test suites (`cargo test --workspace`, `cargo test -p encap-engine`, `swift test`, `ctest`, Python unittest) executed cleanly with 0 unexpected failures.
  - Strict formatting and linting (`cargo fmt --check`, `cargo clippy -D warnings`, `check_no_python.sh`) passed with 0 warnings.
  - All modifications remain fully compliant with repository guidelines and `AGENTS.md`.
