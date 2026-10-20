# GitHub Actions optimization recommendations

Read-only proposals, prepared 2026-10-13 (America/Los_Angeles). No workflows, repository settings, releases or remote issues were changed. Estimates replay the observed window unless explicitly labeled as scenarios.

## Policy constraints

Preserve independent native builds for every supported architecture; existing unit, integration, security, accessibility, and regression coverage; optional signing/notarization for direct downloads; ZIP, AppImage, MSI, DMG and other established artifact formats; authenticated runtime acquisition, provenance, integrity, update-manifest, Sparkle/appcast and Authenticode checks. Publish only artifacts that pass their own compilation/packaging, dependency, integrity and native launch or equivalent functional smoke checks. A failed platform or diagnostic must not block another verified platform, commits, pushes, merges or unrelated work. DCO trailers remain voluntary conventions under the repository policies; do not add enforcement, required reviews, branch protection, paid services or manual release approvals.

## Prioritized changes

### H1: High priority — tlolabs/statstream — macos-release.yml

**Current behavior and inefficiency:** Five native application jobs each install cargo-audit 0.22.2. Across 12 pushes, that step ran 60 times and used 94.47 minutes. The application matrix is required; repeating installation is avoidable.

**Proposed change:** Cache the pinned executable with OS/architecture/toolchain/version keys and validate its version on restore, or run the common advisory scan once in an independent Linux diagnostic job. Keep application-specific Qt/native checks in all five jobs. Do not make publication depend on the advisory job.

**Estimated reduction and calculation:** Illustrative 80% installation-time reduction: 94.47 × 0.80 = 75.58 macOS job-minutes over the observed window; zero workflow runs removed. Common scan savings are additional and not quantified.

**Consequences:** Cache cold starts, executable compatibility and advisory-database freshness remain relevant. Running advisory checks once must retain reports and unresolved findings.

**Implementation difficulty:** Low.

### H2: High priority — tlolabs/encap — build-platforms.yml; tlolabs/ativ — native-release.yml; tlolabs/ewaf — native.yml and build-*.yml; tlolabs/yacht — native-macos.yml and build-*.yml

**Current behavior and inefficiency:** Current native build workflows lack systematic dependency/compiler caches. EnCAP alone recompiles Rust, Whisper and Swift work on fresh jobs. Five large native workflows used 17,923.43 job-minutes; that total is useful validation, not measured waste.

**Proposed change:** Add isolated Rust registry/Git and compilation caches keyed by OS, architecture, compiler, lockfile and flags; cache pinned Qt/Whisper/Sparkle downloads and native intermediate outputs where valid. Authenticate every restored external runtime/source and retain final artifact smoke tests. Do not reuse final packages across source revisions. Pilot on EnCAP and measure cold/warm job duration.

**Estimated reduction and calculation:** Scenario only: reducing EnCAP build runtime by 10–20% would save 483.10–966.20 job-minutes. Applying 10% to all five workflows models 1,792.34 minutes before overlaps; neither cache hit rates nor achieved savings were measured.

**Consequences:** Wrong architecture/ABI or stale build configuration can invalidate artifacts. Source verification and final target-specific tests remain required. Existing cache contents do not prove the current workflow actually restores them.

**Implementation difficulty:** Medium.

### H3: High priority — tlolabs/yacht — native-macos.yml

**Current behavior and inefficiency:** Daily scheduled native builds produced 27 runs and 925.80 job-minutes, often at unchanged source revisions; security freshness does not require repackaging every architecture daily.

**Proposed change:** Retain daily dependency/security diagnostics and failure visibility, with full six-platform builds on source changes, manual dispatch and a weekly scheduled compatibility run. Keep every platform and internal reference test automated.

**Estimated reduction and calculation:** Retrospective scenario: preserve 6.83 minutes of identifiable scheduled compliance/security/report work, run native work on 4 rather than 27 dates, and save (925.80 − 6.83) × 23/27 = 782.82 job-minutes; 23 full native suites avoided, with daily lightweight diagnostics still running. A replay of evolving historical YAML is not a future forecast.

**Consequences:** Daily detection of runner/toolchain drift becomes weekly; source-change coverage stays intact. Keep dependency/advisory checks daily and retain manual full qualification. Validate whether any unpublished external runtime requires daily native smoke coverage before reducing its cadence.

**Implementation difficulty:** Medium.

### M1: Medium priority — tlolabs/avid-core — ci.yml (shared-core)

**Current behavior and inefficiency:** Unfiltered push and pull_request triggers cover feature branches. There are 53 same-head-SHA groups containing both events; 55 non-main, non-v-tag push runs in those groups used 155.35 job-minutes. Equal head SHA alone does not prove identical tested trees.

**Proposed change:** Deduplicate same-repository feature pushes only when a matching open PR will receive its merge-context validation; retain main/tag pushes, fork PRs, manual fallback and feature pushes without an open PR. Keep pull-request merge testing. If implementing routing, recheck event ordering and do not make opening a PR mandatory.

**Estimated reduction and calculation:** Upper-bound candidate pool: 55 runs / 155.35 minutes in the observed window. Actual savings require confirming the PR existed at push time and preserves the intended validation. Do not count tag-versus-PR or main-versus-PR runs as redundant.

**Consequences:** PR checkout normally tests the merge ref, while push checks the branch tree; those contexts can differ. A simple push: branches: [main] configuration would lose branch-only automation and is not the default recommendation.

**Implementation difficulty:** Medium.

### M2: Medium priority — tlolabs/ativ — publish-recovered-artifacts.yml and native-release.yml

**Current behavior and inefficiency:** Publisher push jobs poll for native job completion (20-second polling loop; up to 150 minutes). Four push-triggered publisher runs used 95.25 job-minutes. The workflow_run filter is parsed as three names: Native build, test, and and package, because the actual comma-containing name is unquoted. No publisher workflow_run execution was observed.

**Proposed change:** Quote the exact workflow name. Move normal publication into six per-platform dependent jobs so each publishes as soon as its own native verification succeeds. Retain a correctly named completion-triggered recovery workflow and idempotent immutable-asset checks. Remove the ordinary polling push route only once direct per-platform publication covers it.

**Estimated reduction and calculation:** Scenario only: avoiding 50–90% of the observed polling-job runtime would save 47.63–85.73 Linux minutes. Correcting the trigger alone can add completion executions and is not a savings claim.

**Consequences:** Waiting until whole-workflow completion would delay successful platforms and is not the proposed replacement. Do not cancel active/pending publishers, reduce provenance validation or introduce a whole-build success condition.

**Implementation difficulty:** Medium–High.

### M3: Medium priority — tlolabs/encap — build-platforms.yml and updater-contract.yml; tlolabs/ativ, tlolabs/ewaf and tlolabs/fillr native entry points

**Current behavior and inefficiency:** Most automatic native workflows have no path filters. EnCAP updater tests run on every PR and main push. EnCAP build push activity used 2,326.37 minutes and updater push activity 99.63 minutes, but irrelevant-change counts were not collected.

**Proposed change:** Start with confirmed documentation-only directories excluded from native builds, preserving packaged license notices, assets and embedded resources. Scope updater tests to the complete transitive source/test/configuration dependency set only after mapping it; preserve dispatch and all release-tag qualification. Apply filters consistently to PR and push routes.

**Estimated reduction and calculation:** No measured savings claim. If 10% of the recorded EnCAP push workload were proven unrelated, the modeled reduction is 10% × (2,326.37 + 99.63) = 242.60 minutes. Full multi-commit push and PR diffs must be replayed before assigning an eligible run count.

**Consequences:** Broad **/*.md exclusions can suppress changes to packaged notices; narrow updater allowlists can miss shared Rust dependencies. GitHub does not evaluate path filters on tag pushes. Fail open or retain full dispatch for uncertain file sets.

**Implementation difficulty:** Medium.

### M4: Medium priority — tlolabs/encap — build-platforms.yml; selected diagnostic workflows across repositories

**Current behavior and inefficiency:** EnCAP has no workflow concurrency configuration. Across the account, cancelled jobs already used 3,147.98 minutes; that is observed cost, not all recoverable waste. ATIV and Yacht already cancel non-tag runs, including main workflows associated with publishing.

**Proposed change:** Cancel superseded PR-only validation using workflow/PR-specific groups. Keep publishing pushes, tags, qualification dispatches and recovery runs in non-cancelling groups unique to their source/run identity. Review ATIV/Yacht main-branch cancellation because it can interrupt a publication chain. Do not cancel releases to obtain savings.

**Estimated reduction and calculation:** Not quantified: requires overlap intervals and knowing which cancelled job work a newer PR superseded. Existing cancellation savings cannot be counted again.

**Consequences:** GitHub concurrency normally allows only one pending run per group; cancel-in-progress: false protects running jobs but can still replace pending runs. Avoid shared cross-revision publication groups unless pending-run loss is explicitly safe.

**Implementation difficulty:** Low–Medium.

### M5: Medium priority — tlolabs/encap — build-platforms.yml and script/build_and_run.sh

**Current behavior and inefficiency:** Mac packaging already runs Swift tests in build/native-swift-$NATIVE_ARCH; the workflow runs the same Swift test package again in build/native-swift. The subsequent full Rust workspace run repeats some packaged engine tests, but the package-context environment is different and must not be assumed redundant.

**Proposed change:** Reuse the identical Swift scratch path and run each equivalent Swift suite once after confirming flags and architecture match. Keep actual packaged runtime, media, save/audio, dependency, integrity and launch checks. Inspect the Windows portable-updater retest similarly rather than deleting package-context tests wholesale.

**Estimated reduction and calculation:** Not quantified. Wrapper-step times combine compilation, packaging and tests, so deleting the entire wrapper duration would be invalid. Measure the second Swift compilation/test invocation first.

**Consequences:** Native architecture, environment and packaged-binary selection can make apparently duplicate tests distinct. Keep full workspace coverage and diagnostics even when another platform test fails.

**Implementation difficulty:** Low–Medium.

### L1: Low priority — tlolabs/encap / tlolabs/ativ failure reporters and retry helpers; tlolabs/avid-core failure-report.yml

**Current behavior and inefficiency:** EnCAP failure reporting ran 124 times using 22.10 Linux minutes; its retry helper ran 61 times but used only 0.82 minutes because most runs skipped the runner job. Reporter reruns often share the default-branch SHA even though they reconcile different upstream events.

**Proposed change:** Serialize/debounce report updates while keeping first failure, recovery, retry exhaustion and unresolved findings visible. Keep daily reconciliation as a safety net. Retain the existing bounded failed-job-only retry; optionally classify deterministic failures to avoid pointless retries, with an explicit manual retry path.

**Estimated reduction and calculation:** EnCAP reporter 50% runtime reduction would model only 11.05 minutes. There were 21 extra run attempts across all repositories, using 1,103.77 minutes; this is a retry baseline, not proven unnecessary work or promised savings.

**Consequences:** Suppressing success completions can leave resolved failures open. Removing retries can hurt recovery from transient infrastructure failures. A skipped helper workflow record is not a billed runner job.

**Implementation difficulty:** Low.

### L2: Low priority — Artifact upload steps across tlolabs/encap, tlolabs/ativ, tlolabs/yacht, tlolabs/ewaf, tlolabs/fillr, tlolabs/avid-core and tlolabs/statstream

**Current behavior and inefficiency:** Current nonexpired Actions artifacts occupy 131.66 GiB; EnCAP alone accounts for 43.20 GiB. Most uploads omit retention-days. Caches and release assets are separate stores.

**Proposed change:** Use short explicit retention for ordinary PR diagnostics and disposable intermediate outputs (for example 7–14 days), while retaining native qualification inputs and provenance evidence long enough for all signing, recovery, update and audit consumers. Keep published immutable release formats and assets. Cache immutable dependency downloads instead of repeatedly preserving unnecessary copies, without removing legally required source archives.

**Estimated reduction and calculation:** No runner-minute savings claim. Steady-state storage is approximately upload GiB/day × retention days; lowering eligible retention from 90 to 14 days would model 84.4% reduction for that subset only. Repository defaults and eligible bytes were not verified, so that is not an account-wide storage or dollar forecast.

**Consequences:** Early expiry can break recovery/signing and provenance checks; public runner minutes are free but artifact storage can still matter. Do not remove required matching FFmpeg source/license evidence or purge artifacts during this audit.

**Implementation difficulty:** Low–Medium.

## Combining savings without double counting

The narrow tool-cache scenario (75.58 minutes), weekly native schedule scenario (782.82 minutes), branch/PR candidate upper bound (155.35 minutes), and ATIV polling scenario (47.63–85.73 minutes) concern different workloads. Their conditional arithmetic total is **1,061.38–1,099.48 job-minutes**, roughly 4.6–4.8% of the measured account runtime. This is not a promised reduction: schedule coverage, branch/PR eligibility and polling replacement must be verified first. The tool-cache part affects private StatStream; the other parts affect public standard runners and primarily save capacity and latency. Dollar savings are unavailable.

Compiler caching, path filtering and PR cancellation overlap with those changes and with each other. Do not add their scenarios to this total. No savings is assigned to security removal, architecture removal, skipped helper records, already-retired workflows or useful retries.

## Example trigger configurations

These are illustrative review material, not patches. Revalidate the complete dependency set and historical event payloads before applying them.

### EnCAP: preserve release tags and dispatch; skip only confirmed documentation directories

```yaml
on:
  push:
    branches: [main]
    tags: ["v*"]
    paths-ignore: ["docs/**"]
  pull_request:
    paths-ignore: ["docs/**"]
  workflow_dispatch:
    inputs:
      platform:
        type: choice
        options: [all, macos, windows, linux, checks, runtime-probes]
        default: all
```

Confirm that `docs/**` has no package/build inputs first. Preserve root packaged notices. Tag pushes still qualify every production target because GitHub ignores path filtering for tags. Do not add blanket exclusions for Markdown, scripts, tests, security policy or runtime specifications. [GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

### EnCAP: supersede PR validation without cancelling publishing runs

```yaml
concurrency:
  group: encap-${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

This groups PR updates together and gives every non-PR publication or qualification run its own identity. Do not use a shared `main` concurrency group for a workflow that publishes artifacts; pending runs can be replaced even when active cancellation is disabled. [GitHub concurrency behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

### ATIV: repair the exact completion filter

```yaml
on:
  workflow_run:
    workflows: ["Native build, test, and package"]
    types: [completed]
  workflow_dispatch:
    inputs:
      source_run_id:
        type: string
        required: true
```

Use this as a recovery route only after six direct per-platform publication jobs exist. Preserve first-party source checks, the correct source run/revision and package identity. The present push route supplies early independent publication, so simply deleting it would change behavior.

### Yacht: retain daily security and weekly complete native coverage

```yaml
# Separate diagnostic workflow; preserve existing advisory/report commands.
on:
  schedule:
    - cron: "17 9 * * *"
  workflow_dispatch:

# Native entry workflow: retain existing push, PR and dispatch configuration;
# replace only its daily schedule with a weekly one.
# schedule:
#   - cron: "17 9 * * 1"
```

The daily diagnostic is independent of platform publication. Weekly scheduling does not remove native jobs or source-triggered validation. Verify external runtime freshness needs before changing cadence.

## Existing improvements that should be preserved

- EnCAP no longer builds source FFmpeg in its current native workflow; it acquires authenticated Core runtime artifacts. Old source-build minutes cannot be counted as additional future savings.
- EnCAP, ATIV, EWAF, Yacht and Core publish or recover individual verified targets without requiring every target to succeed. They reuse qualified artifacts rather than rebuilding inside most publication/attestation jobs.
- Current Core `ffmpeg.yml` candidate verification is dispatch-only; its former PR/push activity accounts for much of the historical 2,009.65 minutes. Its trigger reduction is already present and is not a new savings proposal.
- Core `ffmpeg-independent.yml` already has path filtering, immutable source-download caching, reusable per-platform build/publication workflows and noncancelling source-identity concurrency. Do not remove these.
- Yacht already ignores documentation paths on push, but its PR route is unfiltered. Main and tag builds are intentional and need distinct publication behavior.
- Native matrices cover required OS/architecture pairs. Core's three Windows lifecycle workers intentionally stress race behavior; collapsing them without equivalent stress evidence would reduce coverage.

## Publication behavior that needs care during refactoring

StatStream has five distinct application targets; they are not redundant matrix entries. Its current publication condition checks structural packaging success but does not explicitly require the preceding launch step's outcome, which uses `continue-on-error`. `publish_app.sh` checks integrity and source identity but does not consume launch evidence. All 60 observed launch steps passed, so this is a static eligibility gap, not evidence of a broken published package. Any reuse/refactor must make each artifact's functional eligibility explicit while leaving diagnostics and unrelated targets nonblocking.

Do not change EWAF to a weekly/manual development-release cadence: its checked-in policy explicitly requires automatic commit-keyed development publication for eligible main builds. EnCAP's main build similarly publishes `dev-v<version>-<sha>`; reducing release API calls alone saves little native compilation. Keep production tag qualification, optional signed-package verification, update authentication, CodeQL, Advanced Security, Dependabot and dependency graph coverage. A release event authenticating final published assets is useful downstream verification, not an identical rebuild.

## Source evidence

- [encap/.github/workflows/build-platforms.yml](https://github.com/tlolabs/encap/blob/3cf5b2b4efc3072a9ac8ab3657395069e1b6fb03/.github/workflows/build-platforms.yml)
- [encap/script/build_and_run.sh](https://github.com/tlolabs/encap/blob/3cf5b2b4efc3072a9ac8ab3657395069e1b6fb03/script/build_and_run.sh)
- [statstream/.github/workflows/macos-release.yml](https://github.com/tlolabs/statstream/blob/93dae98306e0e1488960c2012fbd451678b3352a/.github/workflows/macos-release.yml)
- [statstream/script/report_checks.sh](https://github.com/tlolabs/statstream/blob/93dae98306e0e1488960c2012fbd451678b3352a/script/report_checks.sh)
- [yacht/.github/workflows/native-macos.yml](https://github.com/tlolabs/yacht/blob/113ce485d2ddf62aa543afda574f01bf185b31fe/.github/workflows/native-macos.yml)
- [ativ/.github/workflows/publish-recovered-artifacts.yml](https://github.com/tlolabs/ativ/blob/41b18aa29cccccd55187c3d99f6555779876c195/.github/workflows/publish-recovered-artifacts.yml)
- [ativ/script/publish_native_platforms.py](https://github.com/tlolabs/ativ/blob/41b18aa29cccccd55187c3d99f6555779876c195/script/publish_native_platforms.py)
- [avid-core/.github/workflows/ci.yml](https://github.com/tlolabs/avid-core/blob/7e124a3387349e38cc99e5db7e89a73cc23068ad/.github/workflows/ci.yml)
- [ewaf/AGENTS.md](https://github.com/tlolabs/ewaf/blob/5f6badf38d9da9e0d0f54bdb47c60df0a6647ed7/AGENTS.md)
