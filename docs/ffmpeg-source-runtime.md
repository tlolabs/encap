# AVID Core runtime packaging

The 2.0.5 integration consumes AVID Core's matched FFmpeg/ffprobe 9.0.1 runtime, recipe 7.
Core owns source acquisition, signature verification, codec configuration, native
compilation, media validation, repeat-build checks, runtime packaging and licenses.
EnCAP's former FFmpeg source builder and dependency recipe have been removed.

Cargo pins Core 0.3.0 at `25d19098a22936638b0e2a70616083d929fe409c`.
`runtime/core-runtime.json` pins the six candidate artifacts from successful Core
workflow run `36681249099`, their archive SHA-256 values, original checksum manifests,
and corresponding-source archive hashes. These are validated Core candidates;
EnCAP packaging additionally runs its application contracts. No qualification of
an EnCAP platform is inferred solely from Core's native build result.

`script/prepare_ffmpeg.sh <platform> <architecture>` uses the identical vendored Core verifier pinned at `runtime/core-acquirer.json`. Production requires a durable, exact published Core release with its manifest digest and promotion workflow identity; it currently fails closed because publication/pinning is outstanding.

Unpublished qualification is explicit: set `AVID_CORE_QUALIFICATION=1` locally or dispatch `build-platforms.yml` with `qualify_core_candidate=true`. The verifier checks the complete pinned Core run, repository, dispatch event, source revision, workflow, native jobs and artifact container digest before extraction. Candidates cannot enter push/PR production paths. Cached/selected runtimes require verified original archives and authenticated origin or release receipts; production rechecks the manifest attestation. Python and GitHub CLI are build tools only. End-user packages work offline with their embedded tools, with no PATH fallback.

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
