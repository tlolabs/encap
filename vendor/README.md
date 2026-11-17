# AVID Core transcription source

`avid-core-transcription/` is an unmodified, attributed 38-file export from
published AVID Core `v0.4.0`, immutable Git commit
`dd112d497b68df6786f49a71b3611f7f32f090e9`. Each file was read from that commit's
Git objects; builds do not depend on a mutable sibling checkout or branch.

The deterministic source archive and per-file manifest are retained beside this
file. Archive SHA-256:
`76f517ddfcf14067ac52c0f84b61b4f3bb7dd11917df30de94385dc0d15428a3`.
The manifest identifies the published source and exact file hashes. It does not
claim that this export has a separate upstream review; EnCAP's integration review
and functional checks are recorded with the application release.
Run `ruby script/verify_avid_snapshot.rb` from EnCAP before building the linked transcription adapter.
Its package paths are `apple/AVIDTranscription` and
`apple/AVIDTranscriptionEngines`; the latter retains upstream dependency pins in
`Package.swift` and `Package.resolved`. The source's GPL license and SDK/model
notices remain intact. Model weights are not bundled here.

Update by exporting the same paths from a new immutable published source revision,
verifying its archive and all per-file hashes, replacing source/archive/manifest
together, deliberately updating the pinned hashes in the verifier and adapter
provenance, and rerunning integration checks and review.
Changes to reusable catalog, download, recognition, alignment, or caption logic
belong upstream in AVID Core. EnCAP's JSON adapter lives outside this snapshot.
The Rust Core and this Swift dependency identify the same immutable source revision.
