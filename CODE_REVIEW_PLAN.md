# EnCAP Autonomous Codebase Review, Repair and Optimization

**Working Record and Audit Plan**
*Date: 2026-09-14*
*Target: EnCAP Native Application and Rust Engine Workspace*

---

## 1. Repository Assessment

EnCAP is a native desktop application (SwiftUI on macOS, with WinUI and GTK implementations planned/structured) backed by a modular Rust engine (`encap-engine`) and domain crates (`encap-core`, `encap-audio`, `encap-transcript`, `encap-video`, `encap-ffmpeg`, `encap-release`).

### User-Facing Functionality
* **Audio Mode**: Ingests folders of broadcast WAV and AIFF recordings, naturally sorted; provides chapter marker editing and chapter naming automation; previews source recordings; exports final master audio (MP3 via LAME or AAC via Apple AudioToolbox / FFmpeg) with embedded ID3v2/MP4 chapter marks and metadata.
* **Transcript Mode**: Transcribes audio using on-device models (Apple Speech framework on macOS, whisper.cpp with EnCap catalog models, or reused WhisperKit models); supports word-level timestamps; provides full transcript search, speaker assignment, and export to plain text or SRT subtitles.
* **Video Mode**: Composes podcast video episodes with custom aspect ratios, platforms (Instagram, YouTube, etc.), chapter artwork overrides, animated or styled video rendering delegated to `avid-core` (AVID Core), and hardware/software H.264/HEVC encoding.

### Architecture and Shared Core
* The shared core was extracted to `avid-core` (located at `/Users/tlothian/Documents/Projects/AVID Core`), shared between EnCAP and ATIV.
* Access to ATIV is strictly read-only.
* AVID Core changes require explicit permission (AVID Core is clean and working).
* EnCAP interacts with the engine via a single JSON process boundary (`encap-engine`), returning single JSON responses with structured error reporting.
* Projects are persisted as ZIP archives (`.encap`, schema version 2) containing a `manifest.json` and portable audio/artwork assets. An incremental save index uses APFS copy-on-write clones to achieve sub-15ms save latency during metadata and mode changes.

---

## 2. Baseline Build and Test Status

* **Rust Workspace**:
  * `cargo check --workspace`: Passed cleanly.
  * `cargo test --workspace`: 23 passed, 4 ignored (3 release-pair media contract tests, 1 256 MiB benchmark).
  * `cargo clippy --workspace --all-targets`: Passed with 0 warnings.
  * `cargo fmt --check`: Passed cleanly.
  * `./script/check_no_python.sh`: Passed cleanly (zero legacy Python dependencies).
* **Release-Pair Media Tests**:
  * `ENCAP_FFMPEG` + `ENCAP_FFPROBE` pinned 9.0.1 tools verified: All 3 ignored `media_contract` tests passed.
  * `benchmark_large_project_saves` release benchmark: 256 MiB full deflate baseline 2.41s vs incremental metadata save 9.9ms (Audio) / 10.6ms (Video) / 9.1ms (Transcript).
* **Native macOS Swift Application**:
  * Xcode debug build (`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild -scheme EnCap`): Built successfully.
  * Swift Package Tests (`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path macos`): 12 tests passed, 0 failures.

---

## 3. Discovered Issues & Remediation Register

| ID | Category | Severity | Description | Resolution Status |
|---|---|---|---|---|
| **BUG-01** | Correctness | **High** | `natural_cmp` in `source.rs` incorrectly evaluated numbers with leading zeroes (e.g., evaluating `"part2.wav"` > `"part03.wav"` because `'2' > '0'`) due to comparing unstripped digit slices before stripped digit values. | **Resolved & Verified** |
| **BUG-02** | Data Integrity | **High** | Unknown chapter, transcript segment, and audio source extensions in `CompatibilityPayload` were stored and restored positionally by vector index. Reordering, inserting, or deleting chapters/segments assigned extensions to wrong items or lost them. | **Resolved & Verified** |
| **BUG-03** | Reliability / UX | **Medium-High** | `addChapter()` assigned `chapterNumber = count + 1` exceeding `audioSources.count`, causing Video export and video playback to fail with "Chapter X has no source audio" on projects with fewer files than chapters. | **Resolved & Verified** |
| **BUG-04** | Reliability | **Medium** | `replace_staged_file` parent directory `fsync` failed on non-POSIX/remote/exFAT filesystems returning `EINVAL`/`ENOTSUP`, failing atomic saves after a successful rename. | **Resolved & Verified** |
| **BUG-05** | Testing / Architecture | **Medium** | `SaveCache::path` did not support an environment override (`ENCAP_SAVE_CACHE_DIR`), preventing test cache isolation and polluting system cache directories. | **Resolved & Verified** |
| **BUG-06** | Usability / Platform | **Medium** | ⌘S (Save) always displayed `NSSavePanel` dialog even when `projectPath` was known, violating native macOS document save conventions. | **Resolved & Verified** |
| **BUG-07** | Reliability | **Medium** | Force unwrapping `store.project!` in `TranscriptView.swift` segment binding could cause runtime crashes during asynchronous state updates or segment count changes. | **Resolved & Verified** |
| **BUG-08** | Build Infrastructure | **Low-Medium** | `script/build_and_run.sh` did not run native Swift unit tests during build verification, unlike CI. | **Resolved & Verified** |

---

## 4. Implementation Details & Fix Walkthrough

### BUG-01: Natural Sort Ordering (`crates/encap-core/src/source.rs`)
- **Root Cause**: In `natural_cmp`, numeric digit runs were compared by trimmed string length, then fell back to comparing raw unstripped strings (`an.cmp(&bn)`). When trimmed digit lengths matched, `"2"` was compared to `"03"`, evaluating `'2' > '0'`, which incorrectly inverted the sort order.
- **Fix**: Updated `natural_cmp` to compare trimmed lengths, then compare the trimmed numeric slices (`atrim.cmp(btrim)`), and only then fall back to original slices (`an.cmp(&bn)`) to break ties with equal values.
- **Verification**: Added `natural_sort_orders_recording_numbers` test covering mixed zero-padded and non-zero-padded filenames: `["part1.wav", "part002.wav", "part2.wav", "part03.wav", "part10.wav"]`. Passed.

### BUG-02: Identity-Based Extension Preservation (`crates/encap-core/src/project.rs`)
- **Root Cause**: `CompatibilityPayload` stored preserved extensions for chapters and transcript segments as flat vectors (`Vec<BTreeMap<String, Value>>`). When chapters or segments were reordered, inserted, or deleted by a native client, positional restoration misaligned extensions or attached old extensions to new items.
- **Fix**:
  - Updated `CompatibilityPayload` to map unknown extensions by stable element ID (`chapters_by_id: BTreeMap<String, BTreeMap<String, Value>>`, `transcript_segments_by_id`, and `audio_sources_by_name`).
  - Maintained legacy vector fields for backward compatibility with schema-1/older archives.
  - In `save_project`, look up extensions by ID first; only fall back to positional index if the ID map is empty.
- **Verification**: Added `native_client_round_trip_preserves_extensions_when_reordered_or_inserted` test verifying that reordering chapters, inserting new chapters, reordering transcript segments, and reordering audio sources preserves extensions on their matching elements without data corruption or leakage. Passed.

### BUG-03: Chapter Audio Source Mapping & Clamping (`macos/EnCap/`)
- **Root Cause**: `addChapter()` assigned `chapterNumber = project.chapters.count + 1`. In projects with a single master recording (or fewer recordings than chapters), `chapterNumber` exceeded `audioSources.count`. Video rendering (`render_request` in `encap-video`) strictly checks `chapter_number` against `audio_sources`, failing with `"Chapter X has no source audio"`.
- **Fix**:
  - Added `audioSourceIndex(at: Double) -> Int` to `ProjectDocument`.
  - In `AppStore.swift`, `addChapter()` resolves the audio source covering the chapter's start timestamp and clamps `chapterNumber` to `min(sourceIndex + 1, max(1, project.audioSources.count))`. Title uses `Chapter \(titleNumber)`.
  - In `renumberChapters()`, clamped `chapterNumber` to available audio sources.
  - In `source(for:in:)`, added fallback by start timestamp and single-source check.
  - In `AudioView.swift`, `ChapterRow` now displays the chapter's sequential row index (`displayNumber`) so the UI table always displays `# 1, 2, 3...`.
- **Verification**: Added `testAddingAndRenumberingChaptersClampsChapterNumberToAudioSources` in `ProjectDocumentTests.swift`. All 13 Swift tests pass.

### BUG-04: Directory Sync Resilience (`crates/encap-core/src/file_ops.rs`)
- **Root Cause**: `replace_staged_file` called `sync_parent(parent)` after an atomic rename. On non-POSIX, network (SMB/NFS), FUSE, or exFAT/FAT32 filesystems, opening a directory or calling `fsync` on a directory returns `EINVAL`, `ENOTSUP`, `EOPNOTSUPP`, `EACCES`, or `EPERM`, causing an already-successful save to report a failure.
- **Fix**: `sync_parent` inspects raw OS error codes and `io::ErrorKind`. If directory sync fails due to unsupported filesystem operations or permissions (`1, 13, 22, 30, 45, 95`), the error is safely tolerated rather than aborting.
- **Verification**: Validated with `replaces_existing_file_after_staging_completes` and full workspace test suite.

### BUG-05: `ENCAP_SAVE_CACHE_DIR` Environment Override (`crates/encap-core/src/project_save.rs`)
- **Root Cause**: `SaveCache::path` relied solely on `ProjectDirs::from("com", "TLO Labs", "EnCap")`, preventing test isolation and polluting `~/Library/Caches` during CI or unit test execution.
- **Fix**: `SaveCache::path` now checks `std::env::var_os("ENCAP_SAVE_CACHE_DIR")` before `ProjectDirs`.
- **Verification**: Added `save_cache_respects_env_override` unit test in `project_save.rs`. Passed.

### BUG-06: Native macOS Save (⌘S) vs Save As (⇧⌘S) (`macos/EnCap/`)
- **Root Cause**: ⌘S unconditionally invoked `presentSavePanel()`, prompting with `NSSavePanel` on every save even when `project.projectPath` was already known.
- **Fix**:
  - Implemented `saveProject(switchingTo:)` in `AppStore.swift` that writes directly to `project.projectPath` if set, and prompts `presentSavePanel()` only if `projectPath` is nil.
  - Updated `ContentView.swift` toolbar button, `confirmDiscardChanges()`, and `switchWorkspace()` to call `saveProject()`.
  - Added "Save Project" (⌘S) and "Save Project As…" (⇧⌘S) to the application menu in `EnCapApp.swift`.
- **Verification**: Verified via Swift package build and automated test suite.

### BUG-07: Crash Prevention in TranscriptView (`macos/EnCap/Views/TranscriptView.swift`)
- **Root Cause**: `segmentBinding(_ index: Int)` used `store.project!.transcriptSegments[index]`. If `store.project` was nil during async state transitions, or if `index` went out of bounds while filtering/updating segments, the force-unwrap panicked.
- **Fix**: Replaced force unwrap with safe optional binding, bounds checking against `segments.indices`, and a safe fallback segment binding.
- **Verification**: Verified with `swift test`. All 13 tests passed.

### BUG-08: Native Swift Tests in Build Script (`script/build_and_run.sh`)
- **Root Cause**: `./script/build_and_run.sh` validated release-pair media contract tests, save protocol tests, and AVID Core tests, but omitted the native Swift package unit test suite.
- **Fix**: Added `DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" swift test --package-path "$ROOT_DIR/macos" --scratch-path "$ROOT_DIR/build/native-swift"` directly to the verification block of `build_and_run.sh`.
- **Verification**: Executed `./script/build_and_run.sh --verify`. Passed cleanly.

---

## 5. Final Validation Summary

- `cargo check --workspace`: Passed cleanly.
- `cargo test --workspace`: 26 passed, 3 ignored (release-pair media contract tests).
- `cargo clippy --workspace --all-targets`: Passed with 0 warnings.
- `cargo fmt --check`: Passed cleanly.
- `./script/check_no_python.sh`: Passed cleanly.
- `DEVELOPER_DIR=... swift test --package-path macos`: 13 passed, 0 failures.
- `./script/build_and_run.sh --verify`: Verified end-to-end (release-pair contract, incremental save latency benchmark, Swift tests, AVID Core contract, codesign & runtime launch).
