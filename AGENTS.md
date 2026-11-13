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

Standard local macOS app distributions require Developer ID signing and
notarization. Explicit development/test packages remain unnotarized; other
platform signing prerequisites are unchanged. Preserve runtime update-signature,
appcast, Authenticode, artifact-integrity, and provenance checks. Do not put an
unsigned package on an authenticated update feed. DCO sign-offs remain a
convention, not an enforced gate.

## Archived legacy automation

The former custom workflows are preserved, inactive, under `.github/workflow-archive/2026-11-08/`, with original paths and hashes recorded in its manifest. This archive supersedes older descriptions of automatic builds, retries, reporting, and release publishing. Do not move them back to `.github/workflows/`, enable, or dispatch them without a new explicit owner instruction. GitHub-managed security services remain separate and enabled.

## Local macOS notarization (owner update, 2026-11-09)

Standard local distributable macOS app packages require Developer ID Application
signing, Apple notarization acceptance, stapling, and signature/Gatekeeper checks
of the final extracted app. Missing credentials stop that packaging path before
building; they never silently select an unsigned download. Use an existing
Keychain notarytool profile and keep credentials out of source control.
Ordinary debug/test runs and explicitly named development/reference artifacts
remain local and unnotarized. This supersedes older optional-notarization wording
for macOS app distribution only. Windows/Linux policy, authenticated updates,
DCO conventions, and the restricted weekly CI schedule are unchanged.

## Weekly publication clarification (owner update, 2026-11-12)

The weekly Sunday Windows/Linux job now packages and publishes independently
verified native downloads from new unattempted version tags to their existing
GitHub Release. This supersedes the earlier weekly no-packaging/no-publication
restriction only. Keep basic final-package smoke scope, immutable tags, native
platform validation, existing signing requirements, no automatic retries and
no push/PR/tag-event/manual triggers. Do not create a release, change Latest,
overwrite release assets or update authenticated feeds from this workflow.
Missing existing Windows signing configuration fails closed without enrollment.
See docs/weekly-download-publication.md for the workflow and remaining limits.

## Unsigned Windows downloads (owner update, 2026-11-13)

The active weekly Windows path publishes explicitly unsigned direct downloads
with `-unsigned.zip` names and `authenticode: unsigned` verification evidence.
It has no Azure login, signing secrets or OIDC permission. Existing signing
scripts and archived workflows remain intact for a future explicitly configured
signing path; no signing failure is silently converted into unsigned publication.
Application identity, dependency/runtime integrity and native final-package
smoke checks remain mandatory. No unsigned download enters authenticated update
feeds. Local macOS signing/notarization and scheduling policies are unchanged.
This supersedes the prior missing-Windows-signing-configuration blocker only.
Finalization requires successful smoke and publication for the same target.
