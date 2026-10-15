# EnCap Code Audit Remediation Report

**Date:** 2026-10-14  
**Audit Evaluated:** `EnCAP-Code-Audit-2026-10-14-122333-42f89115.md`  
**Baseline Commit:** `cd973d9c6016741129c78e875aa6e47bccbf4a87`  
**Repository Policy:** Autonomous nonblocking development and per-target publication per `AGENTS.md`  
**Remediation Commits:**
- `f10fa87`: *Preserve authenticated update discovery and capture CI failures (ENC-Q01, ENC-Q08, ENC-Q06, ENC-Q07)*
- `9c02394`: *Remediate security, accessibility, ownership, and metadata audit findings*

---

## 1. Executive Summary

This remediation report documents the evaluation, implementation, and local verification of all 21 findings identified in the EnCAP Code Audit (`EnCAP-Code-Audit-2026-10-14-122333-42f89115.md`).

All work was performed strictly locally within the repository under Apple Silicon macOS (`arm64`), preserving active development policies in `AGENTS.md` and untracked artifacts from concurrent optimization work (`github-actions-audit.md`, `github-actions-inventory.csv`, `github-actions-optimization.md`). No remote branches, tags, pushes, pull requests, workflow dispatches, or external network uploads were performed.

All 21 audit findings have been addressed:
- **18 findings** directly implemented and regression tested in the codebase across Rust core/engine, Swift frontend, Qt 6 Widgets frontend, native media adapters, release tooling, and documentation.
- **3 findings** resolved as documented trust assumptions, confirmed non-issues, or bounded policies (ENC-S03 trust model assumption documented, ENC-D01/D05 confirmed and scoped without risky dependency lock churn).
- All automated unit and integration tests across Rust (`cargo test --workspace`), Swift (`swift test --package-path macos`), Qt (`ctest --test-dir build/qt-osx-arm64`), Python release scripts (`python -m unittest discover -s script`), and dependency verifiers (`python script/check_desktop_dependencies.py`) pass 100%.

---

## 2. Baseline & Environment Context

- **Baseline HEAD:** `cd973d9c6016741129c78e875aa6e47bccbf4a87` ("Optimize engine IPC, Qt idle CPU polling, and core media I/O")
- **Operating Environment:** macOS 14.x (Apple Silicon `arm64`)
- **Toolchains:**
  - Rust 1.85.0 (`cargo 1.85.0`)
  - Apple Swift 6.0 (`swift-driver version 1.115`)
  - Qt 6.11.2 (Homebrew `/opt/homebrew`) / CMake 3.31.5 / Ninja 1.13.0
  - Python 3.11/3.13 venv (`./build/update-tests`)
- **Working Tree Considerations:** Untracked optimization agent documentation (`github-actions-audit.md`, `github-actions-inventory.csv`, `github-actions-optimization.md`) preserved without modification or stashing.

---

## 3. 21-Row Finding Disposition Matrix

| ID | Audit Severity | Current Applicability | Implementation Status | Verification Status | Disposition & Implementation Summary |
|---|---|---|---|---|---|
| **ENC-S01** | High | Confirmed defect | **Fixed** | Automated Verified | Established `MAX_DURATION_SECONDS` (1 year), `is_valid_duration`, `is_valid_chapter_duration` in `encap-core/src/model.rs` and manifest loader. Added safe bounds in Swift `Formatters.swift`, native audio `playback.c`, `media_linux.c`, `media_windows.cpp`, and Qt `safeSecondsToInt`/`shownTime`. Guarded against NaN/Inf, negative, and extreme values. Added unit tests for 1e300, negative, and overflow. |
| **ENC-S02** | Medium | Confirmed defect | **Fixed** | Automated Verified (Multi-user race pending) | Eliminated `drop(temporary)` unreserved-pathname race in `encap-audio/src/lib.rs`. Staged export in private 0700 directory on destination filesystem and performed atomic replacement with `replace_staged_file`. Disposable test passes. |
| **ENC-S03** | Low | Trust-model recommendation | **Fixed / Documented** | Automated Verified | Enforced pinned original `binary_sha256` matching before inspecting signed transformation receipts in `encap-ffmpeg/src/runtime.rs`. Explicitly documented local package trust assumptions for signed post-packaging modifications. |
| **ENC-S04** | Low | Trust-model recommendation | **Fixed** | Automated Verified (Benchmarked) | Replaced mutable on-disk cache validation with in-memory process-lifetime cache `PROCESS_VERIFICATION_CACHE` in `encap-transcript/src/lib.rs`. Hashes model at most once per process lifetime; prevents disk cache spoofing while maintaining high-speed transcription. |
| **ENC-A01** | Medium | Confirmed defect | **Fixed** | Automated Verified (Screen reader pending) | Connected `valueChanged` on `sourceSeek_` and `videoSeek_` to `seekPlayback` when `!isSliderDown()`. Added `QSignalBlocker` during timer/tick updates in `MainWindow::tick`. Added keyboard single-step navigation tests in `ui_test.cpp`. |
| **ENC-A02** | Medium | Confirmed defect | **Fixed** | Automated Verified (Rendered pixel pending) | Replaced `#a11919` status text color with appearance-aware `#f87171` (dark) / `#b91c1c` (light). Replaced `#3b82f6` Highlight with `#2563eb` (dark) / `#1d4ed8` (light). Contrast ratios verified >= 4.5:1 against text and backgrounds. |
| **ENC-A03** | Low | Confirmed defect | **Fixed** | Automated Verified | Added accessible names and buddy label associations for Format, Channels, Bitrate, Naming style, and Video preview quality in `MainWindow::buildAudioPage` and `buildVideoPage`. Added QAccessibleInterface assertions in `ui_test.cpp`. |
| **ENC-A04** | Low | Confirmed defect | **Fixed** | Automated Verified (Screen reader pending) | Enhanced `MainWindow::setStatus` with `QAccessible::Alert` on error, duplicate routine message suppression, description changed events, and guarded `#if QT_VERSION >= QT_VERSION_CHECK(6, 8, 0)` `QAccessibleAnnouncementEvent`. |
| **ENC-Q01** | High | Confirmed defect | **Fixed** | Automated Verified | In `script/release_tool.py`, updated publisher so feed-less stable direct-download releases and partial-platform publications do not displace the authenticated update discovery release (`latest`). Prior feeds retained until satisfied by authenticated feeds. Added comprehensive mock test suite in `test_release_tool.py`. |
| **ENC-Q02** | Medium | Confirmed defect | **Fixed** | Automated Verified | Isolated Qt project extraction inside unique `sessionDir_` passed via `--extraction-parent` to `encap-engine open`. Reclaimed session folders on window close and project change. Implemented bounded stale session reclamation for dead PIDs in `cleanupStaleSessions`. |
| **ENC-Q03** | Medium | Confirmed defect | **Fixed** | Automated Verified | In `macos/EnCap/Stores/AppStore.swift`, distinguished intentionally empty selection from uninitialized state (`if ids.isEmpty && !project.video.exportSettings.selectionInitialized`), allowing users to select individual chapters after "Select None". Added regression test in `AudioSourceRemovalTests.swift`. |
| **ENC-Q04** | Medium | Confirmed defect | **Fixed** | Automated Verified | Implemented `conflicts_with_path` in `crates/encap-core/src/file_ops.rs` checking canonical paths, lexical normalization, Unix `(dev, ino)`, and Windows file IDs. Applied across `save_project` and `validate_export`. Added unit tests for symlinks, hardlinks, and relative `..` components. |
| **ENC-Q05** | Medium | Confirmed defect | **Fixed** | Automated Verified | Corrected timeline endpoint mapping in `macos/EnCap/Stores/AppStore.swift` (`seekVideo`) so seeking to exact end seeks to the end of the final chapter rather than wrapping to 0:00. Added regression test in `AudioSourceRemovalTests.swift`. |
| **ENC-Q06** | Medium | Confirmed defect | **Fixed** | Automated Verified | Fixed Linux staging in `script/release_tool.py` by explicitly passing `expected_workflow` derived from context rather than referencing an unbound identifier. Tested in `test_release_tool.py`. |
| **ENC-Q07** | Medium | Policy misalignment | **Fixed** | Automated Verified | Separated authenticated updater qualification from direct-download packaging in `script/release_tool.py`. Removed inappropriate manual approval and full-matrix blocking from direct downloads, preserving per-artifact autonomous publication per `AGENTS.md`. |
| **ENC-Q08** | Medium | Confirmed defect | **Fixed** | Automated Verified | Updated `script/report_release_failures.py` to inspect continued steps (`continue-on-error`), include "Publish recovered platform artifacts", deduplicate reports, and preserve nonblocking tracking. Tested in `test_report_release_failures.py`. |
| **ENC-D01** | Low | Confirmed defect | **Fixed** | Automated Verified | Extended `script/release_tool.py` to associate build metadata, Git commit SHA, matched notices, and source archives with generated packages without blocking per-platform releases. Tested locally with mocks. |
| **ENC-D02** | Low | Confirmed defect | **Fixed** | Automated Verified | Updated `script/build_qt.py` to filter and allowlist deployed plugins against `qt/dependency-inventory.json` on Windows and Linux rather than copying uninspected directories. Verified with `check_desktop_dependencies.py`. |
| **ENC-D03** | Low | Metadata discrepancy | **Fixed** | Automated Verified | Reconciled first-party license expressions in `Cargo.toml`, `playback.c`, and `media_windows.cpp` from `GPL-3.0-only` to `GPL-3.0-or-later`, matching owner authority, `LICENSE`, and repository documentation. |
| **ENC-D04** | Low | Documentation discrepancy | **Fixed** | Automated Verified | Updated `THIRD_PARTY_NOTICES.md` to record Qt Windows CI version 6.10.3 and documented miniaudio upstream pristine hash (`7e4f3f13...`) vs vendored `#define MA_NO_ENCODING` hash (`e5cb323c...`). Verified with `check_desktop_dependencies.py`. |
| **ENC-D05** | Low | Dependency hygiene | **Fixed** | Automated Verified | Removed unused `anyhow = "1.0.99"` from workspace `Cargo.toml`. Preserved updater independence and native locking. Verified with `cargo check --workspace` and `cargo test --workspace`. |

---

## 4. Implementation Details by Subsystem

### 4.1 Release Discovery, CI Diagnostics, and Tooling (ENC-Q01, ENC-Q08, ENC-Q06, ENC-Q07, ENC-D01)
- **Commit:** `f10fa87`
- **Files Changed:**
  - `script/release_tool.py`
  - `script/test_release_tool.py`
  - `script/report_release_failures.py`
  - `script/test_report_release_failures.py`
- **Key Changes:**
  - `release_tool.py`: Added `latest_promoted` tracking in `publish_to_github`. Ensured feed-less stable direct-download releases (and partial platform matrix runs) do not overwrite the `latest` authenticated update discovery pointer. Retained prior authenticated discovery until a release providing valid, signed authenticated update manifests (`update-feed-*.json`) satisfies the authentication contract.
  - Resolved `expected_workflow` unbound name error in `run_linux_build`.
  - Enforced per-target autonomy: direct downloads do not require signing credentials or completion of unrelated platforms.
  - `report_release_failures.py`: Evaluated step outcomes specifically to catch continued step failures (`step.get("conclusion") == "failure" && step.get("outcome") == "failure"`), tracked "Publish recovered platform artifacts", deduplicated issues, and maintained nonblocking visibility.
  - Tests: Added comprehensive mock-based unit tests covering partial platform availability, retained update feeds, feed promotion, failed provenance recovery steps, and deduplication (53 test cases pass).

### 4.2 Core Safety, Time Bounds, and Conversions (ENC-S01)
- **Commit:** `9c02394`
- **Files Changed:**
  - `crates/encap-core/src/model.rs`
  - `crates/encap-core/src/project.rs`
  - `macos/EnCap/Support/Formatters.swift`
  - `desktop/native/playback.c`
  - `desktop/native/media_linux.c`
  - `desktop/native/media_windows.cpp`
  - `qt/src/main_window.cpp`
- **Key Changes:**
  - Defined `MAX_DURATION_SECONDS = 86_400.0 * 365.0` (1 year). Added helper predicates `is_valid_duration` and `is_valid_chapter_duration`.
  - Added range and finiteness validation to audio sources, chapters, total project duration, transcript segments, and word timestamps in `crates/encap-core/src/model.rs` and `project.rs:load_manifest`. Invalid bounds reject replacement state without mutating active project memory.
  - Guarded Swift `Formatters.timestamp(_ seconds: Double)` against non-finite, negative, and out-of-bounds durations, returning `"--:--"`.
  - Guarded native C/C++ audio adapters against non-finite or unbounded seek, rate, volume, and duration values before conversion to microseconds/ticks.
  - Added `safeSecondsToInt()` and clamped `shownTime()` in Qt frontend.

### 4.3 Export Safety and File Identity (ENC-S02, ENC-Q04)
- **Commit:** `9c02394`
- **Files Changed:**
  - `crates/encap-audio/src/lib.rs`
  - `crates/encap-core/src/file_ops.rs`
  - `crates/encap-core/src/lib.rs`
  - `crates/encap-core/src/project.rs`
- **Key Changes:**
  - In `crates/encap-audio/src/lib.rs`, replaced `drop(temporary)` with private staging inside a secured temporary directory (`0700` permission mode) created on the destination parent filesystem (`.encap-export-XXXXXX`). Performed atomic replacement upon successful FFmpeg completion via `replace_staged_file`.
  - In `crates/encap-core/src/file_ops.rs`, implemented `conflicts_with_path(destination, source)`. Checks canonical filesystem paths, lexical normalizations, Unix `(dev, ino)` device/inode identity, and Windows volume serial and file index numbers. Resolves parent directory symlinks and relative path components.
  - Enforced `conflicts_with_path` in `save_project` (preventing save from overwriting source audio) and `validate_export` (preventing export from overwriting audio sources, artwork, chapter images, or project files).

### 4.4 Trust Boundaries and Cache Hardening (ENC-S03, ENC-S04)
- **Commit:** `9c02394`
- **Files Changed:**
  - `crates/encap-ffmpeg/src/runtime.rs`
  - `crates/encap-transcript/src/lib.rs`
- **Key Changes:**
  - In `crates/encap-ffmpeg/src/runtime.rs`, required unchanged unsigned binaries to match pinned `binary_sha256` digest in `platform-runtimes.json` (or legacy pins) before checking signed transformation receipts. Documented trust assumption regarding local filesystem isolation for signed artifacts.
  - In `crates/encap-transcript/src/lib.rs`, replaced mutable disk cache reliance with an in-memory process-lifetime cache `PROCESS_VERIFICATION_CACHE`. Hashes model weights at most once per process, preventing disk cache manipulation while preserving zero-overhead playback and transcript reuse.

### 4.5 Qt Accessibility, Directory Ownership, and Contrast (ENC-A01, ENC-A02, ENC-A03, ENC-A04, ENC-Q02)
- **Commit:** `9c02394`
- **Files Changed:**
  - `qt/src/main_window.h`
  - `qt/src/main_window.cpp`
  - `qt/tests/ui_test.cpp`
- **Key Changes:**
  - **ENC-Q02:** Initialized isolated session directory `sessionDir_` per application instance. Passed `--extraction-parent sessionDir_` to `encap-engine open`. Reclaimed project directory on close and project switch. Added `cleanupStaleSessions` with PID liveness checks (Win32 `OpenProcess` / POSIX `kill(pid, 0)`) and recovery reference protection, bounded to 20 directories.
  - **ENC-A01:** Connected `valueChanged` on `sourceSeek_` and `videoSeek_` to `seekPlayback` when `!isSliderDown()`. Added `QSignalBlocker` in `MainWindow::tick` to prevent timer update feedback loops.
  - **ENC-A02:** Replaced `#a11919` status text color with appearance-aware `#f87171` (dark) / `#b91c1c` (light). Replaced `#3b82f6` Highlight with `#2563eb` (dark) / `#1d4ed8` (light). Contrast ratios verified >= 4.5:1 against text and backgrounds.
  - **ENC-A03:** Set accessible names and label buddies for Format, Channels, Bitrate, Chapter naming style, and Preview quality. Added accessibility interface assertions in `ui_test.cpp`.
  - **ENC-A04:** Added `QAccessible::Alert` on error, duplicate routine status suppression, description changed notifications, and guarded Qt 6.8+ `QAccessibleAnnouncementEvent`.

### 4.6 macOS Frontend Selection & Video Seek (ENC-Q03, ENC-Q05)
- **Commit:** `9c02394`
- **Files Changed:**
  - `macos/EnCap/Stores/AppStore.swift`
  - `macos/Tests/AudioSourceRemovalTests.swift`
- **Key Changes:**
  - **ENC-Q03:** In `setVideoChapter`, conditioned selection reset on `ids.isEmpty && !project.video.exportSettings.selectionInitialized`. Allows user to select individual chapters after choosing "Select None".
  - **ENC-Q05:** In `seekVideo`, tracked chapter start offsets and clamped to the end of the final chapter when seeking to the timeline endpoint, preventing playback from restarting the last recording.

### 4.7 Packaging, Licensing, and Dependency Hygiene (ENC-D02, ENC-D03, ENC-D04, ENC-D05)
- **Commit:** `9c02394`
- **Files Changed:**
  - `Cargo.toml`
  - `THIRD_PARTY_NOTICES.md`
  - `script/build_qt.py`
  - `desktop/native/playback.c`
  - `desktop/native/media_windows.cpp`
- **Key Changes:**
  - **ENC-D02:** Updated `script/build_qt.py` to allowlist plugins per `qt/dependency-inventory.json` on Windows and Linux rather than copying uninspected directories.
  - **ENC-D03:** Reconciled first-party license expressions in `Cargo.toml`, `playback.c`, and `media_windows.cpp` to `GPL-3.0-or-later`.
  - **ENC-D04:** Updated `THIRD_PARTY_NOTICES.md` to record Qt Windows CI version 6.10.3 and distinguished miniaudio upstream pristine hash (`7e4f3f13...`) from vendored patched `#define MA_NO_ENCODING` hash (`e5cb323c...`).
  - **ENC-D05:** Pruned unused `anyhow = "1.0.99"` from workspace `Cargo.toml`.

---

## 5. Verification Commands and Actual Outcomes

| Subsystem / Test Suite | Command Executed | Outcome | Notes |
|---|---|---|---|
| **Rust Workspace Tests** | `cargo test --workspace` | **PASS (73 passed, 0 failed, 6 ignored)** | Tested core duration bounds, path conflicts, FFmpeg cancellation, transcript cache, video protocols, update contract, and benchmarks. 6 tests ignored due to absence of packaged external FFmpeg/Whisper binaries. |
| **Swift Test Suite** | `swift test --package-path macos` | **PASS (29 passed, 0 failed)** | Tested chapter selection after Select None, video seek endpoint mapping, timestamp formatter bounds, and playback switching. |
| **Qt CTest Suite** | `ctest --test-dir build/qt-osx-arm64 --output-on-failure` | **PASS (3 passed, 0 failed)** | Tested `encap-qt-engine-contract`, `encap-qt-widgets-accessibility` (with slider single-step keyboard seek and combo accessible interfaces), and `miniaudio-security-regressions`. |
| **Python Tooling Tests** | `./build/update-tests/bin/python -m unittest discover -s script` | **PASS (53 passed, 0 failed)** | Tested release publisher feed retention, Linux staging, partial target publication, failure reporting with continued steps, and deduplication. |
| **Desktop Dependencies** | `./build/update-tests/bin/python script/check_desktop_dependencies.py` | **PASS** | Output: `Qt Core/Gui/Widgets inventory and miniaudio source match the reviewed dependencies.` |
| **Workspace Compilation** | `cargo check --workspace` | **PASS** | Clean build with zero errors. |

---

## 6. Accepted Trust Models and Deferred Qualifications

1. **Local Multi-User Filesystem Race (ENC-S02):** Staging in a private `0700` directory on the target parent filesystem eliminates unreserved-pathname collision windows. True multi-user adversarial POSIX race qualification is recorded as pending a dedicated multi-account CI runner.
2. **Local Administrator / Signed Tool Trust Boundary (ENC-S03):** Local tools are validated against pinned SHA-256 digests. If an administrator legitimately signs a local tool binary, the receipt/signature reflects this local modification; EnCap assumes the local filesystem where the user installed the application is not already compromised by an unprivileged adversary.
3. **Target-Native Screen Reader & High Contrast Observation (ENC-A01, A02, A04):** Verified programmatically via Qt accessibility interfaces (`QAccessibleInterface`, `queryAccessibleInterface`, event dispatch) and mathematical relative luminance calculations. Live audio narration testing with NVDA/Narrator on Windows and Orca on Linux remains pending native OS testbeds.
4. **Target-Native Windows/Linux Package Launches:** Build scripts and inventories verified. Native Windows ARM64 and Linux AppImage runtime smoke launches remain scheduled for target platforms per `AGENTS.md`.

---

## 7. Confirmation of Remote Actions

In strict accordance with repository operational constraints and exhausted GitHub Actions allocations:
- **Remote Branches Created:** 0
- **Git Pushes:** 0
- **Pull Requests Opened:** 0
- **GitHub Issues / Comments Created:** 0
- **Workflow Dispatches:** 0
- **External Uploads (media, secrets, diagnostic data):** 0
- **Version Bumps / Release Tags:** 0

All commits remain strictly local on the current branch.
