# Weekly new-release-tag smoke gate

Files to copy into each repository:

- `weekly_release_smoke.py` → `.github/scripts/weekly_release_smoke.py`
- `test_weekly_release_smoke.py` → the same directory, or an appropriate tests directory with the script on `PYTHONPATH`.
- Generate and track `.github/weekly-smoke-baseline.json` once during setup; keep it unchanged during normal weekly runs.

Runtime: Python 3.10+, GitHub CLI (`gh`), GitHub.com. The script has no third-party Python dependencies. It never creates releases, publishes packages, uploads assets, moves tags, changes branch protection, or creates a state branch. Unit tests mock the API. Setup captures existing tags through read-only GitHub API calls.

## Identity and behavior

Each durable status context is:

`weekly-tag-smoke/v1/<native-target>/<full SHA-256 of exact tag name>`

The status is attached to the tag's **peeled commit SHA**, never the annotated tag object SHA. The logical identity is repository + exact tag name + peeled commit SHA + target.

- Separate tags pointing to one commit remain separate work items.
- A tag moved to an unseen commit is new work. Moving back to an already consumed tag/commit/target is not.
- `success`, `failure`, and `error` consume a work item. A `pending` claim consumes work while its prior run is active or if that attempt's smoke job ran. Unsuccessful builds are **not silently retried every week**.
- `pending` can mean a running build, cancellation before finalization, or a partly completed controller. The gate reports these counts explicitly. It does not guess a success or expire claims based on time. The sole recovery case is a pending claim whose exact prior run attempt is completed and whose exact smoke job is absent or provably never executed. Such never-built work becomes eligible at the next weekly schedule and is counted as `recovered_pending`.
- An explicitly skipped job is provably unexecuted only when it has a recorded steps list that is empty or contains only skipped steps with no start/completion timestamps. A cancelled job additionally requires an explicitly present, null job `started_at`; a missing start field, a nonnull start, missing steps, or any executed/unclear step does not permit recovery. Cancellation alone never authorizes a retry.
- Pending recovery requires the marker's same-repository URL to identify both run and attempt, and verifies that attempt through GitHub's API. Missing/malformed provenance, an API failure, ambiguous job names, missing skipped-step evidence, or contradictory job/run status fails closed. No unknown pending claim is silently rerun.
- Existing release tags are excluded by an immutable tracked setup snapshot, using exact tag + peeled SHA + target identity. No baseline statuses are posted, so setup does not imply any smoke test passed. New tag names, moved tags, and targets absent from the snapshot remain eligible.
- A failed/error marker remains failed/error. The helper never erases it or interprets it as a passing smoke test.
- These ledger contexts are **not required checks** and must not be added to required branch protection.

All relevant tags/statuses/jobs are paginated. Annotated tags are peeled with cycle, depth, object-type, ref-name, and SHA validation. Matching release tags use conservative safe ASCII names (maximum 240 characters); invalid matching names fail rather than being silently ignored. Nonmatching tags are irrelevant. The release regex uses Python `fullmatch`, so patterns need no surrounding anchors.

## Commands and outputs

### Read-only selection

```sh
python3 .github/scripts/weekly_release_smoke.py select \
  --repo OWNER/REPO \
  --baseline-file .github/weekly-smoke-baseline.json \
  --pattern 'v[0-9]+\.[0-9]+\.[0-9]+' \
  --targets linux-x64,linux-arm64,windows-x64,windows-arm64
```

`--repo` defaults to `GITHUB_REPOSITORY`. Selection reads only unless `--claim` is explicitly present. The deployed workflow must pass its trusted tracked baseline path; omitting `--baseline-file` intentionally means no baseline exclusions, useful for diagnostics/tests only. Configure each repository's actual source release tag pattern, including prereleases if intended; do not reuse a pattern blindly.

On success the command appends three single-line entries to `GITHUB_OUTPUT`, or writes them to stdout outside Actions:

```text
matrix={"include":[{"tag":"v1.2.3","sha":"<full 40-character commit SHA>","target":"linux-x64"}]}
has_new=true
summary={"matching_tags":1,"new":1,"baseline":0,"recovered_pending":0,"error":0,"failure":0,"pending":0,"success":0}
```

No change is success with `matrix={"include":[]}` and `has_new=false`. API failures, malformed responses, corrupt/missing/wrong-repository baseline files, unsafe inputs, races detected during enumeration, and more than 256 new matrix items are **nonzero failures with no successful outputs**, not “no change.” `--max-matrix N` can lower (not raise) the cap. Overflow never silently truncates work. Preserve the setup snapshot; do not regenerate it merely to hide a new-tag backlog.

### Claim selected work

Use the same select command with `--claim` in the trusted controller job. This posts `pending` statuses for all selected items, linked to the current workflow run and attempt. Outputs are emitted **only after every claim succeeds**.

There is no atomic multi-status GitHub endpoint. If a claim fails partway through, earlier claims remain pending, the gate fails, and build jobs must not start. The next weekly gate can recover those claims only after verifying the prior attempt is completed and the smoke job never executed. The helper never immediately retries a potentially executed POST. Unknown outcomes remain explicit failures until the ledger/provenance can be inspected.

### Finalize

Set `SMOKE_MATRIX` directly from the trusted controller output, as an environment variable, not shell interpolation:

```yaml
env:
  GH_TOKEN: ${{ github.token }}
  SMOKE_MATRIX: ${{ needs.gate.outputs.matrix }}
run: python3 .github/scripts/weekly_release_smoke.py finalize --matrix-env SMOKE_MATRIX
```

The finalizer reads the current run attempt's paginated jobs API and matches **exactly**:

```yaml
name: Smoke ${{ matrix.tag }} (${{ matrix.target }})
```

- Completed `success` → status `success`.
- Completed `failure` or `timed_out` → status `failure`.
- Missing job, or a completed skipped/cancelled job with the strict evidence above that it never executed → preserve its original `pending` claim and provenance, without a status write. Finalizer counts it as pending and reports incomplete/nonzero. The next weekly selection must independently verify that this attempt has completed before recovering it.
- Duplicate name, not completed, attempted/unknown cancellation, ambiguous skipped job, neutral, startup failure, or unknown conclusion → status `error`. These remain consumed, preventing duplicate execution when evidence is uncertain.
- Jobs API failure → no invented results; existing pending markers remain and finalizer fails.
- A failed status POST stops finalization. Previous confirmed writes remain. Inspect uncertain outcomes before retrying.
- Any failure/error result or preserved pending claim makes the finalizer exit nonzero after publishing all determined terminal results. An incomplete smoke run must not appear successful merely because no test actually ran.

Cancellation may prevent even an `always()` finalizer from running. Remaining pending markers for attempted jobs stay consumed and remain visible in later gate summaries. Only provably unexecuted claims can recover as described above. Rerunning only failed jobs is not a supported automatic recovery mechanism: the attempt-specific jobs list can omit earlier successful jobs, making absent items explicit errors. After investigating, perform an explicitly authorized targeted rerun/recovery, preserving tag/SHA/target identity; never clear ledger state automatically.

`mark --tag TAG --sha SHA --target TARGET --state pending|success|failure|error --description TEXT` is an explicit write primitive. It and claiming/finalization require matching `GITHUB_REPOSITORY`, valid `GITHUB_RUN_ID`, and `GITHUB_RUN_ATTEMPT` (default 1). Its URL is always the current repository's GitHub Actions run attempt. It must not run from untrusted source code or with an elevated token supplied to that code.

### Baseline existing tags, without writes

```sh
python3 .github/scripts/weekly_release_smoke.py baseline \
  --repo OWNER/REPO --pattern 'v[0-9]+\.[0-9]+\.[0-9]+' \
  --targets linux-x64,linux-arm64,windows-x64,windows-arm64 \
  --output .github/weekly-smoke-baseline.json
```

This only GETs tags/tag objects and creates the requested local JSON file. It does **not** read or post statuses, and contains no status payloads. The output file must not already exist; generation refuses to overwrite an existing snapshot. Without `--output`, JSON goes to stdout.

The strictly validated shape is:

```json
{
  "schema": 1,
  "repository": "OWNER/REPO",
  "captured_at": "2026-11-08T00:00:00Z",
  "entries": [
    {"tag": "v1.2.3", "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "target": "linux-x64"}
  ]
}
```

The timestamp records capture start in UTC. Historical snapshots can contain more than 256 entries. Extra/missing fields, unknown schemas, duplicate JSON keys, duplicate identities, malformed entries/timestamps, and multiple SHA values for one snapshot tag are rejected. Repository identity must match exactly. Selection skips exact baseline entries **before looking up commit statuses**, counting them separately as `baseline`, never `success`.

Rollout sequence:

1. Generate the existing-tag snapshot before rollout.
2. Review repository, release pattern, targets, names, and SHAs.
3. Verify read-only `select --baseline-file ...` excludes the snapshotted identities. New tags created after the snapshot, tags moved to new commits, and additional targets remain eligible.
4. Under the rollout authorization, disable superseded workflows, check overlapping runs, and publish the tracked snapshot with the helper and weekly workflow.
5. Leave the snapshot unchanged. It is a one-time setup exclusion list, not a runtime ledger. New claims and actual outcomes are recorded by durable commit statuses only. Baseline setup makes no API writes.

## Safe workflow skeleton

This is an integration sketch, not a complete build recipe. Use the repository's approved pinned action revisions and native smoke commands. Configure AVID Core for Saturday and all other repositories for Sunday. A single `16:17 UTC` schedule is `08:17 PST` / `09:17 PDT`, both Pacific morning, and avoids a duplicate DST schedule. Do not add push, tag, release, pull-request, or workflow-dispatch triggers when the requirement is scheduled-only weekly execution.

```yaml
name: Weekly release smoke
on:
  schedule:
    - cron: '17 16 * * 0' # Sunday; use 6 for AVID Core Saturday
permissions:
  contents: read
concurrency:
  group: weekly-release-smoke-ledger
  cancel-in-progress: false
jobs:
  gate:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      actions: read
      statuses: write
    outputs:
      matrix: ${{ steps.select.outputs.matrix }}
      has_new: ${{ steps.select.outputs.has_new }}
    steps:
      # Checkout trusted scheduled workflow commit, not a release tag.
      - uses: actions/checkout@v4 # Pin approved immutable revision in real workflow.
        with:
          path: control
          ref: ${{ github.sha }}
          persist-credentials: false
      - id: select
        env:
          GH_TOKEN: ${{ github.token }}
        run: >-
          python3 control/.github/scripts/weekly_release_smoke.py select
          --pattern 'v[0-9]+\.[0-9]+\.[0-9]+'
          --targets linux-x64,linux-arm64,windows-x64,windows-arm64
          --baseline-file control/.github/weekly-smoke-baseline.json
          --claim

  smoke:
    name: Smoke ${{ matrix.tag }} (${{ matrix.target }})
    needs: gate
    if: needs.gate.outputs.has_new == 'true'
    permissions:
      contents: read
    strategy:
      fail-fast: false
      matrix: ${{ fromJSON(needs.gate.outputs.matrix) }}
    # Map only validated target names to approved GitHub-hosted native runners.
    runs-on: ${{ fromJSON('{"linux-x64":"ubuntu-24.04","linux-arm64":"ubuntu-24.04-arm","windows-x64":"windows-2022","windows-arm64":"windows-11-arm"}')[matrix.target] }}
    steps:
      - uses: actions/checkout@v4 # Pin approved immutable revision.
        with:
          ref: ${{ matrix.sha }}
          persist-credentials: false
      # Insert approved basic native build/smoke commands here. No publish,
      # releases, signing secrets, statuses:write, or reusable self-hosted host.

  finalize:
    needs: [gate, smoke]
    if: always() && needs.gate.result == 'success' && needs.gate.outputs.has_new == 'true'
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      actions: read
      statuses: write
    steps:
      - uses: actions/checkout@v4 # Pin approved immutable revision.
        with:
          path: control
          ref: ${{ github.sha }}
          persist-credentials: false
      - env:
          GH_TOKEN: ${{ github.token }}
          SMOKE_MATRIX: ${{ needs.gate.outputs.matrix }}
        run: python3 control/.github/scripts/weekly_release_smoke.py finalize
```

Security boundaries:

- Controller/finalizer load the helper from the trusted scheduled workflow commit. Never run a helper, local action, shell startup hook, or imported Python module from the source release tag in a write-token job.
- Load the immutable baseline from that same trusted checkout, never from a release-tag checkout or build output. Scheduled jobs must not regenerate or edit it.
- Build jobs use isolated GitHub-hosted runners, `contents: read` only, and `persist-credentials: false`. No repository secrets, elevated PAT, signing keys, write-token environment variables, or publishing permissions.
- Checkout immutable `matrix.sha`, not the mutable tag name. The tag is display/identity data only.
- Keep all workflows capable of claiming the ledger in one non-cancelling concurrency group. Status claims are not a distributed atomic lock.
- Finalizer consumes only the controller's validated matrix and GitHub's jobs API, not build-produced files, artifacts, caches, or shell outputs.
- Do not interpolate tag/matrix values into executable shell text. Pass JSON through an environment variable.

## Tests

```sh
python3 -m unittest discover -s .github/scripts -p 'test_weekly_release_smoke.py' -v
```

Tests mock transport and cover pagination, annotated/nested tags, cycles and depth limits, malformed tags/SHA/refs, moved tags, shared commits, all ledger states, matrix overflow, immutable baseline schema/identity validation, snapshot nonmutation, new-target eligibility, partially failed claims, safe orphan-claim recovery, finalizer-to-next-schedule recovery, explicit unstarted versus ambiguous cancellations, active/attempted-job non-recovery, mixed terminal/incomplete outcomes, malformed provenance, run identity, exact attempt/job matching, inconclusive jobs, API errors, JSON transport, and output safety. Passing these tests does not claim the repository-specific Linux/Windows builds themselves have executed.
