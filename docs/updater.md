# Stable desktop updates

## Decision and audit (2026-09-30)

Use the standalone `tlo-updater` Rust crate, with no AVID Core or media/application dependencies. Native frontends launch a tiny application-owned helper on a background task. The installed helper binds application ID, repository and Cargo version in code. The shared component owns stable release discovery, Ed25519 authentication, semantic versions, target/OS/glibc selection, bounded downloads, SHA-256, check state, high-water replay protection, process locking and the existing AppImage staging adapter. Native installation and work coordination stay outside the protocol.

The source lives in `updater/`. During this implementation another chat/process independently started the same extraction in ATIV. EnCAP reuses that component rather than maintaining a second protocol. `updater/SNAPSHOT.json` pins the exact vendored snapshot, including the shared Python release tooling; `script/check_updater_snapshot.py --compare ../ATIV` detects divergence. `runtime/updater-source.json` records the unpublished provenance. This is intentional vendoring for independent CI builds, not a runtime dependency on ATIV. A dedicated updater repository/package is still to be published; no nonexistent remote revision is referenced. Changes must be reviewed and synchronized in both consumers before updating the pins.

| Repository | Audit finding | Migration |
| --- | --- | --- |
| EnCAP | Sparkle 2.9.6, schema-1 `latest.json`, no Windows/Linux application updater; portable ZIP and Linux tar packaging | Keep Sparkle and deployed key/feed URLs; add shared helper and native controls; AppImage packaging; qualification-gated publication |
| ATIV | Sparkle, signed base64 schema-1 manifest, portable Windows bootstrapper, AppImage atomic replacement; checks on every launch; development-channel code | Concurrent work extracts `tlo-updater`, adds schema 2 and `check-auto`; this chat reads/reuses it and does not overwrite that work |
| AVID Core | Media/runtime library, source/runtime release workflows; unrelated local edits | No desktop updater dependency added; existing FFmpeg distribution remains separate |

Scope is the two desktop applications in the supplied workspaces. No claim is made that every other project under Documents has been migrated.

### Established components

Keep [Sparkle](https://sparkle-project.org/documentation/) for native macOS UI, scheduling, authenticated extraction, installation and relaunch. Do not replace its installer with custom Rust code. Use the existing per-architecture appcasts and Developer ID security model.

[WinSparkle](https://winsparkle.org/guides/getting-started/) authenticates updates and launches an installer; it does not turn this application's existing portable ZIP into a transactional installer. Retain and adapt ATIV's external portable bootstrapper for EnCAP rather than installing into a running directory. Application-specific filenames and engine validation account for the adapter copy; discovery/version/download/signature logic is shared. It is unqualified until Windows tests below pass. Moving to a maintained MSI/MSIX installer remains preferable if crash/recovery testing cannot establish the required portable behavior.

[AppImageUpdate](https://github.com/AppImageCommunity/AppImageUpdate) supports embedded update information and delta downloads. Its documentation and older [AppImage update guide](https://docs.appimage.org/packaging-guide/optional/updates.html) do not establish this project's pinned publisher + detached signature + attestation contract. Preserve the existing small full-file adapter, with authenticated staging, fsync, retained backup and same-filesystem atomic rename. Do not substitute zsync checksums for authentication. No delta machinery is implemented here.

## GitHub contract and trust chain

Use `https://github.com/OWNER/REPO/releases/latest/download/update-manifest.json`. This is a static release asset, not the rate-limited unauthenticated REST API. GitHub latest excludes drafts/prereleases; the signed payload independently rejects either flag, any nonstable channel, noncanonical versions, mismatched tag and cross-application identity. Artifact URLs must exactly match the pinned repository, annotated `vMAJOR.MINOR.PATCH` tag and safe filename. Only GitHub and its explicit release CDN hosts may receive HTTPS redirects. There are no telemetry fields, installation IDs, API tokens, profile uploads or new services. GitHub necessarily receives ordinary HTTP requests.

Each stable release contains:

* `update-manifest.json`: schema-2 Ed25519 envelope for new helpers.
* `latest.json`: original schema-1 format for the applicable app, signed using its existing key.
* `appcast-macos-arm64.xml` and `appcast-macos-intel.xml`: existing Sparkle feed names with Ed25519 archive signatures.
* Versioned macOS ZIPs, Windows portable ZIPs and Linux AppImages, plus `SHA256SUMS` and GitHub attestations.

Envelope: `{"payload":"BASE64_EXACT_UTF8_JSON_BYTES","signature":"BASE64_ED25519_SIGNATURE"}`. The signature is checked over decoded exact bytes before parsing or using URLs. No verifier reserialization/canonicalization ambiguity. Algorithm is fixed Ed25519; trust keys come from the native-signed installed package, never the network payload.

Payload fields: `schema=2`, `application_id`, `repository`, canonical `version`, `tag`, `channel="stable"`, `draft=false`, `prerelease=false`, ISO release date `published_at`, GitHub `release_notes_url`, `restart_required=true`, `migration` (`none` or `manual`), and `assets` keyed by deterministic target. Each asset has `platform`, `architecture` (`x86_64`/`aarch64`), `minimum_os`, `minimum_glibc` on Linux, `format`, `filename`, exact `url`, byte `size`, and lowercase `sha256`. See `../updater/manifest.schema.json` and the Rust structs. The generator uses the tag commit time for a reproducible release date; it is not a claim about the wall-clock publication instant.

Accepted targets are macos-{arm64,intel}, windows-{arm64,x64}, linux-{arm64,x64}-appimage. Minimums currently match packaging: macOS 13, Windows 10 build 17763, Linux kernel 4.18 and glibc 2.39. Adjust only after native compatibility testing. Metadata is bounded to 1 MiB; artifacts to 2 GiB and their exact signed size. A checksum alone is never trusted.

Trust chain: reviewed code + embedded app/repository/version/key → signed manifest → bound target/OS/version/URL/size/hash → authenticated artifact → native adapter. Windows additionally verifies timestamped Authenticode on all executable payloads against the installed publisher before executing the staged engine or app; signed package identity/version/target/key must match. macOS relies on Sparkle's archive signature and native bundle identity, Developer ID, hardened runtime and notarization/stapling. Linux release staging verifies the exact workflow artifact and its GitHub attestation; the desktop client authenticates the whole image through Ed25519/SHA-256 and does not invoke `gh` or obtain user tokens.

EnCAP also requires signed XML feeds. The existing promotion job runs on macOS so `sign_sparkle_feeds.py` can use upstream Sparkle `sign_update` from the same checksum-pinned distribution as the app. It signs and verifies each appcast, recomputes checksums, and verifies downloaded feeds before and after publication. Seed material is passed on stdin, never command arguments or logs. `SURequireSignedFeed` and verify-before-extraction are enabled together. Old Sparkle readers continue receiving the same feed names and archive signatures. GitHub release notes use the signed item link; richer notes are optional. ATIV retains its concurrently maintained Sparkle policy.

## Keys and recovery

Existing owners are TLO Labs release maintainers. Reuse `ENCAP_UPDATE_PRIVATE_KEY` / `ENCAP_UPDATE_PUBLIC_KEY` and the corresponding ATIV variables. Local ignored EnCAP key filenames were observed, but private file contents were neither read nor copied. No private keys belong in Git, fixtures, logs, command arguments or an app bundle. Fixture seeds are deliberately public and never production credentials.

The single pinned key cannot be replaced in place. Issue a bridge signed with the old key, embedding the new trust configuration, and prove the complete old→bridge→new sequence. The portable adapter currently refuses key changes, so that bridge requires a separately authenticated installer/manual transition. Retain old feed filenames and signed legacy manifests until supported installations migrate. If the old key is lost/compromised, do not bypass verification: suspend promotion and distribute a newly native-signed installer through a separately authenticated manual recovery procedure. Keep offline escrow, two-maintainer approval and a record of key ownership outside the repository. Sparkle has specific [rotation rules](https://sparkle-project.org/documentation/); with verify-before-extraction enabled, its Developer-ID-signed DMG requirement must be planned before rotation. Never change Apple identity and update key together without a proven bridge.

Windows Azure signing and macOS Developer ID signing retain their separate credentials and policies. Linux AppImages are verified through workflow provenance and the signed update manifest. Missing required credentials block production promotion, not local app use or ordinary development builds. Native-signed executables are not replaced with ad-hoc/unsigned substitutes to pass checks.

## Conservative operation and failure behavior

Manual `check` bypasses timing. `check-auto` records the last attempt and successful authentication, checks at most daily, and backs off for at least one hour after failure. A process lock serializes state/download/install operations and releases after a crash. High-water state prevents presenting an older authenticated release after seeing a newer one; installed-version comparison always rejects downgrade/same-version installs. Corrupt state fails closed instead of resetting trust history. Clock rollback does not suppress updates forever. A stale signed feed can withhold a new release; this protocol does not claim freeze-attack prevention or recovery after signing-key compromise.

Avalonia on Windows and Linux exposes manual checks and persistent automatic-check preferences. Checks/downloads run off the UI thread. Automatic failures remain quiet. Windows refuses install during engine activity or with unsaved changes, checks again after download, and closes through the app's UI lifecycle. Sparkle automatic installation is disabled and its delegate postpones update checks/installation/relaunch while work is active; normal EnCAP termination protection prompts about unsaved work and defers termination safely. The Linux adapter never forces a relaunch; the user saves and restarts when ready.

Windows stages beside the installation, rejects traversal/duplicate/oversized ZIP entries, authenticates the payload and validates the engine before waiting for the old process to exit. A complete backup is retained. Ordinary errors restore it. A recovery JSON file is flushed before directory moves. Power loss between the two directory renames can leave the installation path absent: use the journal's `previous` directory to restore it after confirming no helper is active. Do not delete backups until a real native upgrade has been checked. This recovery gap must be exercised on Windows before qualification; the app is not presently claimed to survive every interruption automatically.

Linux stages in the same filesystem, verifies the complete download, fsyncs the staged image and backup, then atomically replaces the path. Symlinks, hardlinks, privileged images, permissions errors or incompatible OS/glibc versions fail safely. A retained `tlo-previous-*.AppImage` is available for manual rollback. The Linux adapter offers an authenticated download when automatic replacement is unavailable; it does not execute a downloaded AppImage to inspect it. Partial temp files are deleted; a completed user-requested download is retained.

## Release procedure

1. Change the workspace Cargo version once. Tag must equal `v` plus that stable SemVer. `script/update_config.py` writes package identity, macOS bundle versions and generated Windows properties. Linux Meson reads that version. No development/nightly source enters stable promotion.
2. Build native packages using `build-platforms.yml`; test the shared protocol using `updater-contract.yml`. The macOS packaging script supplies authoritative Xcode version overrides; direct Xcode builds must set ENCAP_VERSION from Cargo. Local Windows builds first run `python script/update_config.py --props build/version.props`.
3. Run manual `sign-windows.yml`, `verify-linux.yml`, and `verify-macos.yml` gates. Developer ID/notary execution remains on the release Mac. Record final artifact identities, authenticated derivative runtime hashes and native evidence.
4. Populate `runtime/application-qualification.json` only with real evidence. `application_release.py` requires the entire six-target EnCAP matrix, authenticates workflow/artifact origins and rejects missing native launch, media, lifecycle, Windows/macOS signing or Linux provenance, authenticated upgrade and manual acceptance evidence.
5. Populate `runtime/updater-qualification.json` using actual older-build reports under `docs/updates`, including old package hash/trust configuration, final new package hash, host/time/reviewer and every native upgrade/failure case. Every entry is intentionally `not_run` now. Do not invent evidence or use the new manifest's key as an independent baseline.
6. The existing release job runs on macOS for upstream Sparkle signing and stages those exact qualified artifacts. The shared generator checks packaged identity/version/key and artifact bytes, creates both modern and bridge metadata, and signs it. `tlo-qualify` exercises older trust configurations before publication.
7. Attest final packages/metadata. Refuse existing release identities and asset clobber. Upload to a draft, re-download, verify signatures/hashes/identity/attestations, then mark stable/latest. Re-download after publication and probe the actual latest static endpoint. Publication is not reversible; a failed postpublication probe requires investigation and stopping further rollout. Do not mark qualification passed automatically from this probe.

`encap-release` is a compatibility CLI delegating to the shared Python generator. Activate a Python environment containing `script/update-tool-dependencies.txt` first. The obsolete independent Rust wire-format generator is removed. No production release was created by this implementation.

## Qualification and limitations

Commands:

```
cargo test --locked -p tlo-updater -p encap-update -p encap-release
python -m unittest discover -s script -p test_tlo_update_release.py -v
python -m unittest discover -s script -p test_application_release.py -v
python script/check_updater_snapshot.py --compare ../ATIV
python script/qualify_updates.py --assets VERIFIED_ASSETS --published
```

The common suite covers newer/same/older versions, proper SemVer, malformed/prerelease/draft metadata, wrong app/repository/target/architecture, wrong key/signature, corrupted/truncated/oversized streams, checksum mismatch, unavailable endpoint, cached checks/backoff, replay, minimum OS/glibc, a local HTTP manifest→authentication→download fixture, and interrupted AppImage staging/retained backup. The local fixture contains inert bytes, not a complete native app. It is not native install evidence.

For each app and each architecture: start a real older native-signed build with a saved project and preferences; prove no-update/manual/automatic-check behavior; discover, authenticate, download, install and relaunch into the newer build; confirm actual version, all runtime identities and settings/data retention. Repeat with an active export/unsaved work, network outage, wrong app/key/platform, changed digest and interrupted installation at each move. Verify Windows Authenticode subject/timestamps and macOS notarization/stapling after extraction. Exercise nonwritable AppImage manual fallback and rollback. Record full previous/new artifact hashes and feed bytes in evidence, not just screenshots or “build passed.”

| Application/platform | Real older→newer install qualification |
| --- | --- |
| EnCAP macOS arm64 / Intel | Not run; local Developer ID identity exists, but no signed/notarized old/new upgrade evidence is supplied |
| EnCAP Windows x64 / arm64 | Not run; native host/GUI bootstrapper tests and Azure signing configuration absent |
| EnCAP Linux x64 / arm64 | Not run; final AppImage provenance and native authenticated upgrade acceptance absent |
| ATIV macOS / Windows / Linux, both architectures | Not qualified by this chat; overlapping implementation work left untouched |

Repository secret/variable name inspection confirmed EnCAP's update signing secret/public key exist. Windows Azure signing configuration was absent. macOS Developer ID Application identity for team VR64M92P2M is available; notarization was not invoked or claimed. No Windows SDK/dotnet compiler or native Windows/Linux host was available during this earlier implementation. GTK C and Objective-C bridge syntax checks were possible on that Mac; they were not native platform qualification. Later native CI results are recorded in `avalonia-migration.md`.

## Adoption and troubleshooting

Vendor the pinned independent crate and shared release script (or use their future immutable standalone release), add a tiny helper calling `client::run(APP_ID, REPOSITORY, env!("CARGO_PKG_VERSION"))`, embed the public config, wire background native controls, and supply a proven platform adapter. Preserve per-app signing keys; never share another app's identity simply to reuse code. Emit modern and any deployed legacy manifests from the same final authenticated bytes. Run both contract suites and the full native upgrade matrix before enabling promotion.

A 404 before the first modern release means no schema-2 feed is published yet. Do not fall back to an unsigned URL or HTML parsing. Signature errors require checking the installed public key and exact published bytes. A version/target failure requires correcting packaging and rebuilding, not editing a signed manifest. For state errors, preserve the state file for diagnosis; do not erase high-water history automatically. Missing baseline/evidence errors are release blockers by design. Permission failures use manual AppImage replacement or Windows backup recovery. Keep applications usable while investigating GitHub outages.

Validation performed in this checkout: 17 shared Rust contract tests passed in both EnCAP and ATIV; 9 shared release tests, 3 application promotion gate tests, 3 macOS package safety tests, and the upstream Sparkle feed signing/tamper test passed in EnCAP. EnCAP Swift compilation and GTK/Objective-C syntax checks passed. These results are not native installation evidence.


The Avalonia migration adds a Windows installer readiness handshake and serializes
installation with a directory-specific lock. The UI stays open during verification;
the new app acknowledges opening its window before installation is considered
successful. Native Windows A-to-B qualification remains required. The internal
macOS Avalonia reference cannot execute update operations or receive production
update identity; see `docs/avalonia-migration.md`.
