# Releasing EnCap

GitHub Releases are the canonical direct-distribution and update source.
The intended channels are stable `vMAJOR.MINOR.PATCH`, prerelease tags such
as `vMAJOR.MINOR.PATCH-rc.1`, and unsupported development builds from
`main`. The Git tag must agree with the application/package version.
Only a verifiable signed stable tag from Thomas Lothian authorizes an official
production release. Release notes should include useful Highlights, Changes,
Fixes, Known issues, Supported platforms, Installation/update notes, and
Verification/security information; omit empty sections.

The intended stable packages are lowercase
`encap-<version>-<platform>-<architecture>.<extension>`: a Developer ID
signed, notarized, verified macOS `.app` in ZIP; an Azure Artifact Signing
signed and Authenticode-verified portable Windows ZIP; and a GPG-signed Linux
AppImage. Each should have an SBOM, SHA-256 checksum, and provenance
attestation. A failed platform must be marked missing and cannot block a
successful platform from publishing its valid artifact.

The separate development workflow is scheduled from `main` and publishes
only a macOS (ARM64) runnable ZIP as a CI artifact. It is clearly marked
unsupported, is not production signed, and is retained for 30 days.

## Current implementation and gaps

The current workflow builds/test-qualifies six targets, but its release job
requires every Windows and Linux job to succeed before publishing. It expects
manually prepared, signed/notarized Mac DMGs and committed hashes; Windows
portable ZIPs are unsigned and Linux ships tarballs. The release job now
requires a trusted signed tag and generates a dependency SPDX SBOM, but it
does not produce complete binary-level SBOMs or artifact attestations.
Prerelease tags are build/test qualified without production signing; their
GitHub Release publication is not yet automated.
The existing `v2.0.3` tag is annotated but unsigned; it predates the new
gate and is not retroactively changed.
It must not be treated as implementing the intended stable release policy.

Do not issue a new official stable tag until these gates, signing credentials,
and packaging changes are completed and tested. Thomas must configure the
Apple Developer ID/notary credentials, Azure Artifact Signing, Linux GPG key,
and their CI secret storage. The maintainer should also establish a trusted
tag-signing key and verification path in CI. Prerelease and development
packages must not receive production signatures. Runnable development
packages should default to macOS (ARM64) with 30-day retention.

The legacy manual release procedure is recorded in Git history. The current
implementation can be inspected in `.github/workflows/build-platforms.yml`
and `script/sign_macos_release.sh`; publishing through it requires a
separate review of the above gaps.
