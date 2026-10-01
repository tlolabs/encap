# AVID Core runtime packaging

EnCAP 2.0.5 consumes AVID Core's matched FFmpeg/ffprobe 9.0.1 runtime, recipe 7.
Core owns source acquisition, signature verification, codec configuration, native
compilation, media validation, repeat-build checks, runtime packaging and licenses.
EnCAP's former FFmpeg source builder and dependency recipe have been removed.

Cargo pins Core 0.3.0 at `25d19098a22936638b0e2a70616083d929fe409c`.
`runtime/core-runtime.json` pins the published Core release
[`ffmpeg-9.0.1-r7.1`](https://github.com/tlolabs/avid-core/releases/tag/ffmpeg-9.0.1-r7.1),
its promotion revision `2e137df692aa612e0dd62ebd93b5fff26c61663a`, authenticated
manifest digest, and six runtime and corresponding-source archive hashes.
The binaries come from Core run `36681249099`; EnCAP downloads the durable release
assets rather than that run's expiring candidate artifacts.

`script/prepare_ffmpeg.sh <platform> <architecture>` delegates acquisition to
Core's unchanged verifier in `script/core_runtime.py`, pinned by
`runtime/core-acquirer.json`. It authenticates the release manifest with GitHub
attestations, checks archive hashes, architecture and Core evidence, then extracts
the pair under `build/core-acquisition/ffmpeg-9.0.1-r7.1/<target>`.
Python 3.12+ and authenticated GitHub CLI are build tools only.
`ENCAP_FFMPEG_RUNTIME` may select an identical extracted release with its original
archives, manifest and verification receipt alongside it. Cached acquisitions
are reverified. Candidate-only caches from older builds cannot substitute for a
release; leave the override unset to acquire the published runtime automatically.
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
Production discovery verifies the exact pinned Core manifest, every metadata file,
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
