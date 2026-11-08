# AVID Core transcription source

`avid-core-transcription/` is an unmodified, attributed 34-file export from
published AVID Core `v0.3.2`, immutable Git commit
`8296a9e623c6924c12e456b5fe9e7c10b59dfbde`. Each file was read from that commit's
Git objects; builds do not depend on a mutable sibling checkout or branch.

The deterministic source archive and per-file manifest are retained beside this
file. Archive SHA-256:
`a302200860bde5c47cd4aeabacefedefa30e6112248302925164589ce9f45937`.
The manifest identifies the published source and exact file hashes. It does not
claim that this export has a separate upstream review; EnCAP's integration review
and functional checks are recorded with the application release.
Run `ruby script/verify_avid_snapshot.rb` from EnCAP before building the sidecar.
Its package paths are `apple/AVIDTranscription` and
`apple/AVIDTranscriptionEngines`; the latter retains upstream dependency pins in
`Package.swift` and `Package.resolved`. The source's GPL license and SDK/model
notices remain intact. Model weights are not bundled here.

Update by exporting the same paths from a new immutable published source revision,
verifying its archive and all per-file hashes, replacing source/archive/manifest
together, deliberately updating the pinned hashes in the verifier and sidecar
provenance, and rerunning integration checks and review.
Changes to reusable catalog, download, recognition, alignment, or caption logic
belong upstream in AVID Core. EnCAP's JSON adapter lives outside this snapshot.
The independent Rust AVID Core/FFmpeg pin is separate from this Swift dependency.
