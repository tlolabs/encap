# Repository development and CI/CD policy

This repository follows a nonblocking development and CI/CD model. Automated tests, builds, security scans, and compatibility checks provide diagnostic information; they must not prevent commits, pushes, merges, or unrelated development. Their failures must remain visible and be tracked until resolved.

No manual approvals, required reviews, or mandatory status checks are permitted. Do not add branch protection, repository rulesets, or workflow checks that enforce these gates. DCO trailers are a development convention, not an enforced requirement. Cryptographic commit/tag signing and distribution signing are not prerequisites for development or source releases.

Deliberate release operations are platform-independent where the artifact format and its consumers support that safely; scheduled smoke CI never publishes releases. Never publish an artifact that fails its functional, integrity, dependency, or target-platform verification. Do not weaken runtime or update-signature verification to make publication easier. Preserve diagnostics and publish successful platforms independently when the release contract permits; document external or consumer-contract restrictions in the consolidated CI/CD failure issue.

Verified FFmpeg/FFprobe direct downloads publish as independent, immutable platform releases. They never replace the authenticated six-target runtime manifest or change its pinned consumers. Build and test jobs remain read-only; only the per-platform publisher may write release assets.

AVID Core owns FFmpeg/ffprobe source acquisition, compilation, dependencies, target configuration, native runtime tests, packaging, licenses, checksums, provenance, version identity, documentation, and publication. ATIV, EnCAP, and other consumers own their integration tests, application compatibility decisions, signing, notarization, and release schedules. No Core build or publisher may depend on a downstream repository or application approval. Each direct-download publisher depends only on its own platform; the preserved authenticated six-target promotion remains a separate consumer contract. Downstream failures are not Core release failures.

The published `ffmpeg-9.0.1-r7.1` contract and its pinned Recipe 7 specification are immutable compatibility evidence. The specification's historical `qualification_policy.host_packaging: required` field is not an executable gate. Current release policy is enforced by `script/core_release.py` and the schema-3 ledger, which require host evidence to remain optional. Do not change the pinned specification or weaken authenticated acquisition to remove that historical field. See [the provider contract](docs/ffmpeg/provider-contract.md).

Future development must not reintroduce blocking gates without explicit authorization from the repository owner. Keep workflows and documentation consistent with this policy. Every task's final report must include a concise summary of failed or unrun checks and unresolved restrictions; do not present a failure as success.

## Owner-directed weekly smoke CI

Automatic CI runs once weekly on Saturday mornings Pacific time (16:17 UTC, 08:17 PST / 09:17 PDT), and native work runs only for a new stable `vMAJOR.MINOR.PATCH` source-release tag that has not already been attempted. Run only native Linux and Windows x86_64/arm64 compilation and basic smoke tests. Do not run macOS CI, push/PR/tag-triggered CI, automatic retries, full diagnostic suites, or release/publication jobs on the scheduled path. Retain broader test and signing tools for deliberate local use. CI remains diagnostic and nonblocking; do not add required checks or approval gates.

The scheduled smoke result is not release qualification. Preserve runtime acquisition, source and package integrity, target identity, and signature/update verification. Do not publish smoke artifacts as verified releases or change authenticated runtime/update contracts.

## Archived legacy automation

The former custom workflows are preserved, inactive, under `.github/workflow-archive/2026-11-08/`, with original paths and hashes recorded in its manifest. This archive supersedes older descriptions of automatic builds, retries, reporting, and release publishing. Do not move them back to `.github/workflows/`, enable, or dispatch them without a new explicit owner instruction. GitHub-managed security services remain separate and enabled.
