# Repository development and CI/CD policy

This repository follows a nonblocking development and CI/CD model. Automated
tests, builds, security scans, and compatibility checks provide diagnostic
information but must not prevent commits, pushes, merges, or unrelated
development. No manual approvals, required reviews, or mandatory status checks
are permitted. Only verified working artifacts may be published. Failures must
remain visible until resolved. Future development must not reintroduce blocking
gates without explicit authorization from the repository owner.

The owner's CI policy, updated 2026-11-08, is one scheduled check on Sunday
morning Pacific time. Build only newly tagged version releases, on native Linux
and Windows x64 and ARM64 runners, and perform basic compilation and startup
smoke checks. Do not run CI on pushes, pull requests, or tag creation, and do not
automatically retry previously attempted releases. Do not run macOS CI, full
regression suites, signing, attestation, publishing, or release creation from
this weekly workflow. Legacy workflows retained for reference must remain
disabled unless the owner changes this policy. A smoke pass is not package,
media-processing, or authenticated-update qualification.

Functional verification is a per-artifact publication condition. Verify
compilation/packaging, integrity, required dependencies, and launch or an
equivalent functional smoke test on the target platform. A failed platform
must not prevent another verified platform from publishing. Never publish an
unverified or nonfunctional artifact.

Code signing and notarization credentials are optional enhancements, not
development or direct-download prerequisites. Preserve runtime update-signature,
appcast, Authenticode, artifact-integrity, and provenance checks. Do not put an
unsigned package on an authenticated update feed. DCO sign-offs remain a
convention, not an enforced gate.

## Archived legacy automation

The former custom workflows are preserved, inactive, under `.github/workflow-archive/2026-11-08/`, with original paths and hashes recorded in its manifest. This archive supersedes older descriptions of automatic builds, retries, reporting, and release publishing. Do not move them back to `.github/workflows/`, enable, or dispatch them without a new explicit owner instruction. GitHub-managed security services remain separate and enabled.
