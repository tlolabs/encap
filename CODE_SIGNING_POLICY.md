# Code signing policy

Thomas Lothian is EnCap's maintainer, release approver, and final signing
authority. An official stable release is a GitHub Release associated with a
cryptographically signed and verifiable `vMAJOR.MINOR.PATCH` Git tag approved
by Thomas. Maintainer commits should be signed; outside contributors are
encouraged, but not required, to cryptographically sign normal commits.

Stable production artifacts are intended to use Developer ID signing and
Apple notarization on macOS, Azure Artifact Signing and Authenticode on Windows,
and a GPG-signed AppImage plus GitHub/Sigstore attestation on Linux. Prereleases
and development builds are not production signed. CI builds and tests the
source, checks release identities and provenance, and must verify each
platform's signature before labeling its artifact official. Signing keys and
credentials belong in protected provider/CI storage, never in the repository.
The release tag is the authorization signal; no redundant GitHub Environment
human approval is required. A signing provider's own approval still applies.

**Current gap:** The existing workflow does not yet implement this whole
policy. It consumes separately prepared signed macOS DMGs, does not verify a
signed tag, and does not sign Windows or Linux artifacts. Those gaps are
documented in [docs/RELEASING.md](docs/RELEASING.md). Do not describe an
artifact as production signed until its platform verification succeeds.

This project does not currently use SignPath Foundation signing. If that
changes, this policy and the release process must be updated to name the
actual signing provider and meet its rules.
