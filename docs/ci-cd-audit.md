# CI/CD audit and nonblocking policy

## Audit findings

Audited on 2026-10-11 against the repository worktree and GitHub configuration.

| Area | Finding |
| --- | --- |
| Branch controls | `main` protection requires one approving review, six named status checks, and conversation resolution. Required signatures and admin enforcement are disabled. Repository rulesets API returned no rulesets. The repository account has admin permission, so these controls are repository-managed. |
| Repository guidance | No `AGENTS.md` or `CONTRIBUTING.md` exists. `README.md`, `docs/development.md`, and `docs/updater.md` describe notarization, platform signing, six-target qualification, manual acceptance, and release gates as prerequisites. |
| Workflows | `build-platforms.yml` runs functional checks and six native platform builds, but its tag release job requires `quality`, Windows, and Linux jobs together and then stages a complete six-target qualification. macOS tag builds are skipped. `updater-contract.yml` tests three OS runners but only runs for pull requests, main pushes, or manual dispatch. |
| Manual qualification/signing | `sign-windows.yml`, `verify-linux.yml`, and `verify-macos.yml` are manual dispatch workflows. Windows Azure signing and Apple Developer ID/notarization are prerequisites in the release evidence model, not ordinary build prerequisites. |
| Publication gate | `script/application_release.py` requires all six EnCap targets to have native packaging, launch, media, lifecycle, signing/provenance, authenticated upgrade, and manual-acceptance evidence; it authenticates exact workflow runs and package hashes. Both qualification ledgers currently contain no evidence. |
| Signing and updater security | macOS app bundles are locally ad-hoc signed and strictly verified during packaging. Windows optional Azure Authenticode and macOS Developer ID/notarization workflows exist. The runtime updater authenticates signed metadata and platform-specific packages; Windows additionally checks Authenticode and Sparkle verifies its signed feed/archive. Removing those verification requirements would weaken update security. |
| Security automation | GitHub-managed CodeQL, Advanced Security, Dependency Graph, and Automatic Dependency Submission workflows are active. Dependabot security updates and secret scanning are enabled. Secret-scanning push protection is disabled. Repository Actions variables include update public-key and release-signing public-key material; the only Actions secret listed is the update private key. No Azure signing secrets were listed. |
| Failure reporting | No consolidated CI/CD failure issue was found. Recent `Authenticated updater contract` runs include failures on 2026-10-08 followed by a successful run later that day; the latest listed CodeQL run succeeded. |
| Retry/release channels | The repository has a stable tag-triggered publication workflow and main/pull-request verification; no nightly or preview publication workflow was found. There is no bounded retry or failure-issue updater in repository workflows. |
| External controls | No organization rulesets were returned by the rulesets API. Repository-level main protection is removable by the current admin identity. Organization-wide or enterprise controls beyond the repository API are not observable here. |

## Authoritative policy

This repository follows a nonblocking development and CI/CD model. Automated
tests, builds, security scans, and compatibility checks provide diagnostic
information but must not prevent commits, pushes, merges, or unrelated
development. No manual approvals, required reviews, or mandatory status checks
are permitted. Releases are autonomous and platform-independent, but only
verified working artifacts may be published. Failures must remain visible and
tracked until resolved. Future development must not reintroduce blocking gates
without explicit authorization from the repository owner.

Functional verification remains a per-artifact publication condition: successful
compilation/packaging, integrity and dependency checks, and a launch or equivalent
functional smoke test must pass for that artifact. A failure on one platform
must not prevent another verified platform from being published. Unverified or
failed artifacts must never be published.

Code-signing and notarization credentials are optional publication enhancements,
not requirements for development or unsigned direct downloads. Existing runtime
update-signature, appcast, Authenticode, artifact-integrity, and provenance
verification must not be disabled or bypassed. An unsigned package that cannot
meet an updater's trust contract may be distributed only through a supported
manual-download channel and must not be represented as an authenticated update.
DCO sign-offs remain a convention, not an enforced gate.
