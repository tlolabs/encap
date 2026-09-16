# Software FFmpeg source runtime qualification

The authoritative implementation is Core’s pinned source-built FFmpeg software runtime (libx264/libx265 plus the shared Audio/Transcript codecs). Quality, predictable behavior, compatibility, reproducibility and cross-platform consistency take priority over encoding speed.

Windows/Linux GPU encoding is outside this project’s scope. NVENC, QSV, AMF and VAAPI capabilities or GPU-machine access do not gate CI, packaging or release qualification. macOS VideoToolbox remains optional, with valid-stream/decode checks independent of software output; byte and file-size equivalence are not required. Software encoding remains available and is the default for new Video settings.

Minimum OS remains macOS 13, Windows 10 1809 and the established Linux glibc/toolkit baseline (Ubuntu 24.04). Newer hosted CI does not establish exact minimum-OS runtime behavior. The Core ledger preserves these required gates separately.

## Candidate integration

`runtime/core-revision` and the workflow checkout select the same tested Core revision. The `managed-runtime` engine feature selects the complete bundled pair through Core validation, with no silent PATH fallback. Deliberate development overrides remain available. Normal release acquisition is not switched until the remaining software, minimum-OS, toolchain and packaged-host gates pass.

The candidate package script stages a separate application with source/license manifests, verifies original hashes before signing, records signed hashes separately, and exercises the packaged pair. No published release or old download cache is replaced by candidate tests.

```sh
bash script/package_core_candidate_macos.sh '/absolute/path/to/validated/Core/runtime'
```

These are local qualification apps, not release artifacts. See AVID Core `docs/ffmpeg/README.md` and `runtime/ffmpeg/qualification.json` for the authoritative policy and current evidence.

## Local result (2026-09-15)

The recipe-6 macOS ARM64 pair passed two clean builds with byte-identical executables. This host’s separate qualification app passed original-hash verification, ad-hoc signing, bundled media tests and native tests, then launched successfully. Missing/damaged bundle tests passed with a usable external runtime on PATH. macOS executables remain in Contents/MacOS while spec/build/source/signature records and notices are sealed in Contents/Resources/FFmpeg; Core validates the explicit metadata location without fallback.

These checks ran on macOS 26.7 and do not qualify macOS 13. Windows/Linux and Intel macOS source-runtime CI, exact minimum-OS execution and full production-release acceptance remain incomplete. Windows/Linux GPU qualification is not required. The prepared source changes are local: automatic approval review requires explicit permission before pushing to the public repositories and running new build-only CI.

See Core’s `docs/ffmpeg/software-qualification.md` and exact-binary evidence ledger. Local logs are `build/managed-package.log`, `build/managed-bundle-tests.log` and `build/managed-launch.json`.
