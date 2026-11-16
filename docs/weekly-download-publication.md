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

Owner update, November 13, 2026: the active weekly Windows path is explicitly
unsigned until signing is configured in a future authorized change. It publishes
`EnCap-VERSION-windows-ARCH-unsigned.zip`, its checksum and verification report
with `authenticode: unsigned`. It has no Azure configuration requirements,
login/signing steps, secrets or OIDC permission. Existing signing scripts remain
unchanged for future use. This is not automatic fallback from failed signing.
Application identity/version, runtime dependencies/integrity and extracted
startup checks still run. No authenticated feed or signing claim is created.
The update public key remains required for both platforms. Native Windows/Linux
execution is pending the next eligible scheduled run; local Python/lint checks
do not claim those platforms passed. No GitHub runs were manually started.

The selector retains separate Linux/Windows matrices and independent failures.
Finalization waits for publishers and requires both smoke and publication success
for the same target. Failed, missing or ambiguous publication cannot be recorded
as success. Genuine attempts remain consumed with no automatic retry.

Before claiming attempts, selection requires an existing nondraft, non-prerelease
GitHub Release with an uploaded, nonempty matching signed macOS ZIP or DMG and
its SHA-256 file. Tags without that release are deferred without claiming them.
This metadata check does not assert notarization or the owner's manual testing.
It prevents a tag created before its macOS release from consuming native build
attempts prematurely. Previously attempted targets are still never retried.

## Windows 2.0.12 corrective validation

Owner request, November 15, 2026: after fixing the Windows file-identity
compilation error and increasing the version to 2.0.12, build the corrected
source on both Windows runners. The failed weekly run cannot validate the fix:
it uses the previous immutable tag, and its jobs skip later run attempts.

`windows-2.0.12-fix-validation.yml` is a manual-only exception for this correction.
Dispatch it after pushing the corrected source, using the intended branch as
the workflow ref. It checks out the dispatch's exact `github.sha`, refuses any
Cargo version other than 2.0.12, and runs native file-identity regression tests,
compilation and startup checks on Windows x64 and ARM64. Existing package
helpers then verify each extracted, explicitly unsigned final package, including
its application identity, dependencies, authenticated Core runtime and integrity.
Successful packages, checksums and verification reports are retained only as
Actions artifacts; the `v2.0.12` package label does not create or verify a remote
tag or GitHub Release.

This workflow has read-only repository permissions and does not publish release
assets, change tags, update feeds or modify the weekly claim ledger. The Sunday
schedule, immutable-tag selection, consumed attempts and independent platform
publication rules remain unchanged. There are no new automatic event triggers
or retries.
