# AVID Core transcription source

`avid-core-transcription/` is the unmodified, attributed 34-file source export
from AVID Core's completed transcription review, task
`desktop-transcription-20261102-e8b98234`, round 3. It is not acquired from a
mutable sibling checkout, branch, or unestablished public release.

The original archive and per-file manifest are retained beside this file.
Archive SHA-256:
`f4555615571d54b96d714be26caf0484f6049835065d7215820c3244bf761c5a`.
Run `ruby script/verify_avid_snapshot.rb` from EnCAP before building the sidecar.
Its package paths are `apple/AVIDTranscription` and
`apple/AVIDTranscriptionEngines`; the latter retains upstream dependency pins in
`Package.swift` and `Package.resolved`. The source's GPL license and SDK/model
notices remain intact. Model weights are not bundled here.

Update by obtaining a new reviewed source export, verifying its archive and all
per-file hashes, replacing the source/archive/manifest together, deliberately
updating the pinned hash in the verifier, and rerunning integration checks.
Changes to reusable catalog, download, recognition, alignment, or caption logic
belong upstream in AVID Core. EnCAP's JSON adapter lives outside this snapshot.
The independent Rust AVID Core/FFmpeg pin is unchanged by this Swift dependency.
