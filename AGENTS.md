# Repository development and CI/CD policy

This repository follows a nonblocking development and CI/CD model. Automated
tests, builds, security scans, and compatibility checks provide diagnostic
information but must not prevent commits, pushes, merges, or unrelated
development. No manual approvals, required reviews, or mandatory status checks
are permitted. Releases are autonomous and platform-independent, but only
verified working artifacts may be published. Failures must remain visible and
tracked until resolved. Future development must not reintroduce blocking gates
without explicit authorization from the repository owner.

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
