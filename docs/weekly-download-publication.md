# Weekly direct-download publication

Owner clarification, November 12, 2026: the existing Sunday morning workflow
must package and publish verified Linux and Windows downloads for newly tagged
versions. This supersedes earlier smoke-only/no-publication workflow wording.
It does not enable push, PR, tag-event, manual, or retry runs, or macOS CI.

The existing claim ledger and baseline are retained. Exact selected commit and
Cargo version are checked against the immutable tag. Controller-side deployment
uses the existing Qt and authenticated Core FFmpeg acquisition/verification
code. Native final-package extraction, runtime/dependency validation, startup,
and integrity checks qualify only that target, not full regressions or updates.

Each successful target gets its own artifact and publisher. A sibling failure
does not block it. Missing artifacts fail that publisher visibly. Publication
requires an existing nondraft matching GitHub Release and unchanged remote tag.
Only platform packages, their SHA-256 files and verification reports are added;
identical existing assets are left alone and different bytes are refused.
No tag movement, release creation, Latest changes or updater feed changes occur.

Windows requires the pre-existing Azure signing variables and identity secrets,
valid federation trust, timestamped signatures and final extracted signature
checks. No credentials or trust are enrolled. Missing signing configuration
fails closed; no unsigned Windows fallback is published. The update public key
must already be configured for both platforms. Native Windows/Linux execution
is pending the next eligible scheduled run; local Python/lint checks do not
claim those platforms passed. No GitHub runs were manually started.
