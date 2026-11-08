# Archived legacy GitHub Actions workflows

These workflow definitions were archived on 2026-11-08 at the repository owner's request. Their original GitHub Actions registrations were disabled before this move. Files outside `.github/workflows/` are not runnable workflows. Definitions present on the default branch are preserved byte for byte; `manifest.json` records original paths, workflow IDs, SHA-256 hashes, and registrations whose source was already absent.

They are historical reference, not scheduled or callable release automation. Do not restore, enable, or dispatch them without a new explicit owner instruction. Their automated release publishing, retries, and reporting are retired. Existing run history and published release assets are unchanged.

The active replacement is `.github/workflows/weekly-release-smoke.yml`: weekend scheduling, new version tags only, supported Linux/Windows compilation and basic smoke checks, and no release publishing.

GitHub-managed security services are separate and were not disabled by this migration. Runtime integrity, authentication, signing verification, and separately authorized release qualification requirements are unchanged.
