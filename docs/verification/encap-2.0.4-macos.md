# EnCAP 2.0.4 Mac release verification

Verified September 30, 2026. The local Xcode project additions are preserved;
the release builds use the existing `EnCap` scheme with the full application UI.
The separate generated `EnCAP` starter target is not the release target.

## Dependency and packaging changes

- Core 0.3.0: `25d19098a22936638b0e2a70616083d929fe409c` from its committed,
  published branch; no changes or commits were made to the dirty sibling Core checkout.
- Core FFmpeg/ffprobe 9.0.1, recipe 7, native workflow run `36681249099`.
- All six runtime archives, checksum manifests and matching source archives are
  pinned in `runtime/core-runtime.json`. EnCAP's FFmpeg builder, recipe, release
  key and source-build CI action were removed.
- Before staging, Core validates the original complete runtime directory.
  Original evidence remains unchanged after signing; EnCAP validates the signed
  pair against its original manifest and app/Core provenance.
- Developer ID identity: Thomas Lothian, team `VR64M92P2M`.
- Both ZIPs contain the notarized app with its ticket stapled. The final ZIP
  checksums below were computed after stapling and repackaging.

## Validation

- Rust workspace: 50 tests passed; media tests that require a package were
  subsequently exercised by each Mac build.
- Rust formatting, Clippy with warnings denied, Core ownership checks,
  native-only policy, shell syntax, Git diff whitespace and actionlint passed.
- ARM64 and Intel Xcode release builds passed.
- Each package passed five real media contracts covering Audio, Transcript with
  real Whisper recognition, Video, capabilities, persistence, failures and cancellation.
- Each passed relocated-package, corrupted/missing-tool and metadata rejection,
  empty-PATH discovery and poisoned-environment checks.
- Each passed save and audio-edit protocols plus 26 native Swift tests.
- Final ZIP extraction: deep strict signature verification, stapled-ticket
  validation, Gatekeeper (`Notarized Developer ID`) and runtime identity passed.
- The final ARM64 app extracted from its ZIP launched and remained running.

Intel tests ran under Rosetta on Apple silicon. Physical Intel hardware,
minimum-OS testing and new EnCAP Windows/Linux application builds were not run
in this release task. Their Core runtime artifacts passed Core's native CI;
that does not substitute for new application package tests.

## Final notarized artifacts

| Architecture | Final ZIP SHA-256 | Apple submission ID | Status |
| --- | --- | --- | --- |
| arm64 | `73c21c8cba94c68e46e2cbf9ecdbdf68ef833f49f8e05c4d95e7b9c50d0aa440` | `85254728-844d-4c42-9889-3e90b933e30e` | Accepted |
| intel | `0076fb60711a8f48351f6897c3f65c18be3447bb039ff941129709b82716f0be` | `c070e14c-ab06-49c4-80c2-052c04c91e58` | Accepted |

Artifacts are in `dist/EnCap-2.0.4-macos-<arch>-signed.zip`.
Final checksums are committed in `runtime/releases/2.0.4-macos.sha256`.
Local build/notarization logs are retained in ignored `build/encap-2.0.4-*.log`.
