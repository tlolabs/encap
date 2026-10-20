# AVID Core runtime packaging

EnCAP 2.0.8 consumes AVID Core's matched FFmpeg/ffprobe 9.0.1 runtime, recipe 7.
Core owns source acquisition, signature verification, codec configuration, native
compilation, media validation, repeat-build checks, runtime packaging and licenses.
EnCAP's former FFmpeg source builder and dependency recipe have been removed.

Cargo pins Core 0.3.0 at `25d19098a22936638b0e2a70616083d929fe409c`.
The default `runtime/platform-runtimes.json` pins one immutable, attested AVID Core
release per target from build run `38185320964`. Each record fixes its release
tag, publisher and build source commits, GitHub asset IDs and sizes, runtime and
source archive SHA-256 digests, executable hashes, and native target. EnCAP
downloads only the record for the requested target. Newer Core releases or
failures on other targets do not change that selection.

`runtime/core-runtime.json` remains the explicit compatibility pin for the
authenticated six-target [`ffmpeg-9.0.1-r7.1`](https://github.com/tlolabs/avid-core/releases/tag/ffmpeg-9.0.1-r7.1)
release. Set `ENCAP_CORE_RUNTIME_SOURCE=legacy` to use it for a build. There is
no automatic fallback from a missing or invalid platform release. Normal
platform acquisition makes no request to the legacy release and does not wait
for its six-target manifest.

`script/prepare_ffmpeg.sh <platform> <architecture>` selects the target's pin.
`script/platform_runtime.py` verifies the immutable GitHub Release and tag,
the exact `platform-release.json` bytes, its GitHub attestation from AVID Core's
`platform-publisher.yml` on `main`, the publisher source commit, build origin,
target, archive and source hashes, and executable architecture before accepting
the pair. The attested manifest is checked before executable bytes are fetched.
The unchanged shared archive verifier in `script/core_runtime.py` is pinned by
`runtime/core-acquirer.json` and checks the extracted runtime's own evidence.
The selected release tag appears in the build cache and verification receipt.
Python 3.12+ and authenticated GitHub CLI are build tools only.
`ENCAP_FFMPEG_RUNTIME` may select only an extracted runtime matching the
explicitly selected source, with its original archives, manifest and receipt
alongside it. Cached platform acquisitions recheck the release, attestation,
archive, source and extracted bytes. Candidate-only caches and system binaries
cannot substitute for a published release.
There is no application-owned source build or system-tool fallback.

EnCAP packages and tests the runtime in the actual application. Core's native
build results alone do not establish EnCAP's platform acceptance. Build-time
release authentication needs network access; the packaged application uses its
embedded tools offline.

Before staging, `encap-engine validate-core-runtime <directory>` delegates the
original complete directory to `avid_core::MediaTools::from_core_directory`.
EnCAP preserves Core's manifest and evidence unchanged, includes the corresponding
source archive, and records the app/Core identity. Platform signing changes binary
bytes, so `signed-payload.json` binds both original and signed binary hashes.
Production discovery recognizes only the exact target-specific or explicit
legacy archive pin and verifies the Core checksum manifest, every metadata file,
source archive and signed executable, then lets Core validate and execute the pair.
Release builds ignore PATH and environment tool overrides. Debug fixture overrides
require both absolute tool paths.

`script/ffmpeg/qualify.sh` runs the real packaged Audio, Transcript and Video
contracts, checks discovery with an empty PATH and poisoned overrides, and tests
relocated packages with missing or damaged tools, metadata, sources and manifests.

Mac development packaging produces `EnCap-<version>-macos-<arch>.zip`.
`script/sign_macos_release.sh` signs nested code and the app with Developer ID,
submits a ZIP, requires notarization status `Accepted`, staples and validates the
app ticket, checks Gatekeeper, then recreates
`EnCap-<version>-macos-<arch>-signed.zip` containing the stapled app.
The ZIP's final checksum is recorded only after stapling and repackaging.
