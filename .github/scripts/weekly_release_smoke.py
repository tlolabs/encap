#!/usr/bin/env python3
"""Durable, tag-specific weekly smoke gate. Only explicit write commands mutate GitHub."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import quote

CONTEXT_PREFIX = "weekly-tag-smoke/v1"
PAGE_SIZE = 100
MAX_PAGES = 10000
MAX_MATRIX = 256
MAX_TAG_DEPTH = 16
STATES = frozenset({"pending", "success", "failure", "error"})
TARGET_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


class GateError(Exception):
    """An explicit failure, never interchangeable with no new tags."""


def require_object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise GateError(f"{label}: expected an object")
    return value


def validate_sha(value: Any) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise GateError(f"Invalid full lowercase commit/object SHA: {value!r}")
    return value


def validate_tag(value: Any) -> str:
    # Deliberately narrower than git-check-ref-format: release tags need no
    # whitespace, control characters, shell punctuation, or Unicode lookalikes.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/+@-]{0,239}", value):
        raise GateError(f"Unsafe release tag: {value!r}")
    if (".." in value or "@{" in value or "//" in value or value.endswith(("/", "."))
            or any(part.startswith(".") or part.endswith(".lock") for part in value.split("/"))):
        raise GateError(f"Malformed release tag: {value!r}")
    return value


def validate_target(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 40 or not TARGET_RE.fullmatch(value):
        raise GateError(f"Invalid native target: {value!r}")
    return value


def parse_targets(value: str) -> list[str]:
    targets = [validate_target(t) for t in value.split(",")]
    if len(set(targets)) != len(targets):
        raise GateError("Duplicate native targets")
    return targets


def validate_repo(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise GateError("Supply --repo OWNER/REPO or GITHUB_REPOSITORY")
    if any(part in {".", ".."} or part.startswith("-") for part in value.split("/")):
        raise GateError("Invalid repository name")
    return value


def context_for(tag: str, target: str) -> str:
    digest = hashlib.sha256(validate_tag(tag).encode("utf-8")).hexdigest()
    return f"{CONTEXT_PREFIX}/{validate_target(target)}/{digest}"


def positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise GateError(f"Invalid {label}: {value!r}")
    return int(value)


def job_proven_unstarted(job: dict) -> bool:
    """Use the same conservative execution evidence in select and finalize.

    A cancellation alone says nothing about whether native code executed.
    Recovery requires an explicit null job start and unexecuted-step evidence.
    Skipped jobs may have synthetic job-level timestamps, so their recorded
    steps are the evidence. Missing, malformed, or contradictory evidence is
    never interpreted as proof that a job did not execute.
    """
    if job.get("status") != "completed" or job.get("conclusion") not in {"skipped", "cancelled"}:
        return False
    if job["conclusion"] == "cancelled" and ("started_at" not in job or job["started_at"] is not None):
        return False
    steps = job.get("steps")
    if not isinstance(steps, list):
        return False
    return all(isinstance(step, dict) and step.get("conclusion") == "skipped"
               and step.get("started_at") is None and step.get("completed_at") is None
               for step in steps)


class GitHub:
    def __init__(self, repo: str):
        self.repo = validate_repo(repo)
        self.root = f"repos/{self.repo}"

    def request(self, endpoint: str, payload: dict | None = None) -> Any:
        command = ["gh", "api", "--hostname", "github.com", "--method", "POST" if payload is not None else "GET",
                   "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2022-11-28", endpoint]
        if payload is not None:
            command += ["--input", "-"]
        try:
            result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                                    capture_output=True, text=True, check=False, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GateError(f"GitHub API could not complete {endpoint}: {exc}") from exc
        if result.returncode:
            # Never turn a 403, 404, timeout, or rate limit into an empty ledger.
            raise GateError(f"GitHub API failed ({result.returncode}) for {endpoint}: {result.stderr.strip()}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GateError(f"GitHub API returned invalid JSON for {endpoint}") from exc

    def pages(self, endpoint: str, key: str | None = None):
        separator = "&" if "?" in endpoint else "?"
        previous = None
        total = None
        count = 0
        for page in range(1, MAX_PAGES + 1):
            result = self.request(f"{endpoint}{separator}per_page={PAGE_SIZE}&page={page}")
            if key is not None:
                obj = require_object(result, endpoint)
                result = obj.get(key)
                found_total = obj.get("total_count")
                if type(found_total) is not int or found_total < 0:
                    raise GateError(f"{endpoint}: invalid total_count")
                if total is not None and found_total != total:
                    raise GateError(f"{endpoint}: changed while paginating; retry explicitly")
                total = found_total
            if not isinstance(result, list) or len(result) > PAGE_SIZE:
                raise GateError(f"{endpoint}: invalid list page")
            fingerprint = json.dumps(result, sort_keys=True)
            if result and fingerprint == previous:
                raise GateError(f"{endpoint}: repeated page; refusing incomplete enumeration")
            previous = fingerprint
            count += len(result)
            yield from result
            if len(result) < PAGE_SIZE:
                if total is not None and count != total:
                    raise GateError(f"{endpoint}: incomplete pagination ({count}/{total})")
                return
        raise GateError(f"{endpoint}: pagination exceeded safety limit")


class Gate:
    def __init__(self, api: GitHub):
        self.api = api

    def tags(self, pattern: str) -> list[dict[str, str]]:
        try:
            matcher = re.compile(pattern)
        except re.error as exc:
            raise GateError(f"Invalid tag pattern: {exc}") from exc
        tags = {}
        for raw in self.api.pages(f"{self.api.root}/tags"):
            row = require_object(raw, "tag list entry")
            name = row.get("name")
            if not isinstance(name, str):
                raise GateError("Tag list contains a non-string name")
            if not matcher.fullmatch(name):
                continue
            tag = validate_tag(name)
            listed_sha = validate_sha(require_object(row.get("commit"), "listed commit").get("sha"))
            if tag in tags:
                raise GateError(f"Duplicate tag during pagination: {tag}")
            ref = require_object(self.api.request(f"{self.api.root}/git/ref/tags/{quote(tag, safe='')}"), "tag ref")
            if ref.get("ref") != f"refs/tags/{tag}":
                raise GateError(f"Tag ref response does not match {tag}")
            obj = require_object(ref.get("object"), "tag ref object")
            seen = set()
            for _ in range(MAX_TAG_DEPTH + 1):
                sha = validate_sha(obj.get("sha"))
                if sha in seen:
                    raise GateError(f"Cyclic annotated tag: {tag}")
                seen.add(sha)
                if obj.get("type") == "commit":
                    # A list-tags response is a peeled commit SHA. Reject a ref
                    # moved mid-selection instead of silently selecting a mix.
                    if sha != listed_sha:
                        raise GateError(f"Tag moved during selection: {tag}; retry explicitly")
                    tags[tag] = sha
                    break
                if obj.get("type") != "tag":
                    raise GateError(f"Tag {tag} points to unsupported object type {obj.get('type')!r}")
                if len(seen) > MAX_TAG_DEPTH:
                    raise GateError(f"Annotated tag nesting exceeds {MAX_TAG_DEPTH}: {tag}")
                annotation = require_object(self.api.request(f"{self.api.root}/git/tags/{sha}"), "annotated tag")
                if annotation.get("sha") != sha:
                    raise GateError(f"Annotated tag object SHA mismatch: {tag}")
                obj = require_object(annotation.get("object"), "annotated tag target")
            else:
                raise GateError(f"Could not peel tag: {tag}")
        return [{"tag": tag, "sha": sha} for tag, sha in sorted(tags.items())]

    def statuses(self, sha: str) -> dict[str, dict]:
        latest = {}
        ids = set()
        for raw in self.api.pages(f"{self.api.root}/commits/{validate_sha(sha)}/statuses"):
            row = require_object(raw, "commit status")
            context = row.get("context")
            if not isinstance(context, str):
                raise GateError("Commit status has a non-string context")
            if not context.startswith(CONTEXT_PREFIX + "/"):
                continue
            status_id = positive_int(row.get("id"), "commit status ID")
            if status_id in ids:
                raise GateError("Duplicate relevant status ID during pagination")
            ids.add(status_id)
            if row.get("state") not in STATES:
                raise GateError(f"Unknown ledger state for {context}")
            if context not in latest or status_id > int(latest[context]["id"]):
                latest[context] = row
        return latest

    def pending_is_unstarted(self, item: dict, marker: dict, attempts: dict) -> bool:
        """Recover only a provably unexecuted claim from a completed attempt.

        A pending status is not a lease. Time alone never makes it eligible.
        Only GitHub's exact immutable attempt/job evidence permits recovery.
        """
        url = marker.get("target_url")
        match = re.fullmatch(r"https://github\.com/" + re.escape(self.api.repo)
                             + r"/actions/runs/([1-9][0-9]*)/attempts/([1-9][0-9]*)", url or "") if isinstance(url, str) else None
        if match is None:
            raise GateError(f"Pending claim has unknown run/attempt provenance for {item['tag']} ({item['target']}); inspect manually")
        run_id, attempt = map(int, match.groups())
        identity = (run_id, attempt)
        if identity not in attempts:
            endpoint = f"{self.api.root}/actions/runs/{run_id}/attempts/{attempt}"
            run = require_object(self.api.request(endpoint), "prior workflow attempt")
            if run.get("id") != run_id or run.get("run_attempt") != attempt:
                raise GateError("Prior workflow attempt identity mismatch")
            run_status = run.get("status")
            if run_status == "completed":
                jobs = list(self.api.pages(endpoint + "/jobs", key="jobs"))
                names = {}
                for job in jobs:
                    job = require_object(job, "prior workflow job")
                    if not isinstance(job.get("name"), str):
                        raise GateError("Prior workflow job has no name")
                    names.setdefault(job["name"], []).append(job)
                attempts[identity] = names
            elif run_status in {"queued", "in_progress", "requested", "waiting", "pending"}:
                attempts[identity] = None
            else:
                raise GateError(f"Unknown prior workflow attempt status: {run_status!r}")
        names = attempts[identity]
        if names is None:
            return False
        matches = names.get(f"Smoke {item['tag']} ({item['target']})", [])
        if not matches:
            return True
        if len(matches) != 1:
            raise GateError("Prior Smoke job name is ambiguous; cannot prove the claim never executed")
        job = matches[0]
        if job.get("status") != "completed":
            raise GateError("Completed workflow attempt contains an unfinished Smoke job; inspect manually")
        if job.get("conclusion") == "skipped" and not isinstance(job.get("steps"), list):
            raise GateError("Skipped Smoke job lacks step evidence; cannot prove it never executed")
        # Attempted/unknown cancellations and all actual build results remain
        # consumed. Only the shared evidence predicate permits recovery.
        return job_proven_unstarted(job)

    def select(self, pattern: str, targets: list[str], max_matrix: int = MAX_MATRIX,
               baseline: dict | None = None) -> tuple[dict, dict]:
        if type(max_matrix) is not int or not 1 <= max_matrix <= MAX_MATRIX:
            raise GateError(f"max-matrix must be between 1 and {MAX_MATRIX}")
        targets = parse_targets(",".join(targets))
        baselined = validate_baseline(baseline, self.api.repo) if baseline is not None else set()
        tags = self.tags(pattern)
        cache = {}
        selected = []
        summary = {"matching_tags": len(tags), "new": 0, "baseline": 0, "recovered_pending": 0,
                   **{state: 0 for state in sorted(STATES)}}
        attempts = {}
        for row in tags:
            for target in targets:
                item = {**row, "target": target}
                if (item["tag"], item["sha"], item["target"]) in baselined:
                    summary["baseline"] += 1
                    continue
                if row["sha"] not in cache:
                    cache[row["sha"]] = self.statuses(row["sha"])
                previous = cache[row["sha"]].get(context_for(row["tag"], target))
                if previous is None:
                    selected.append(item)
                elif previous["state"] == "pending" and self.pending_is_unstarted(item, previous, attempts):
                    selected.append(item)
                    summary["recovered_pending"] += 1
                else:
                    summary[previous["state"]] += 1
        summary["new"] = len(selected)
        if len(selected) > max_matrix:
            raise GateError(f"{len(selected)} unseen tag/target pairs exceed matrix limit {max_matrix}; "
                            "nothing was claimed. Baseline historical tags or narrow the pattern explicitly.")
        return {"include": selected}, summary

    def mark(self, item: dict, state: str, description: str, target_url: str | None) -> dict:
        item = validate_item(item)
        if state not in STATES:
            raise GateError(f"Invalid status state: {state}")
        if not isinstance(description, str) or not 1 <= len(description) <= 140 or any(ord(c) < 32 for c in description):
            raise GateError("Status description must be 1-140 printable characters")
        payload = {"state": state, "context": context_for(item["tag"], item["target"]), "description": description}
        if target_url is not None:
            if not re.fullmatch(r"https://github\.com/" + re.escape(self.api.repo) + r"/actions/runs/[1-9][0-9]*(?:/attempts/[1-9][0-9]*)?", target_url):
                raise GateError("Status target URL must be this repository's GitHub Actions run")
            payload["target_url"] = target_url
        endpoint = f"{self.api.root}/statuses/{item['sha']}"
        try:
            result = require_object(self.api.request(endpoint, payload), "created status")
        except GateError as exc:
            raise GateError(f"Status write was not confirmed for {item['tag']} ({item['target']}): {exc}. "
                            "Outcome may be uncertain; inspect the ledger before retrying.") from exc
        if result.get("context") != payload["context"] or result.get("state") != state:
            raise GateError("GitHub did not confirm the requested status; outcome is uncertain, inspect before retrying")
        return result

    def released_macos_only(self, matrix: dict) -> tuple[dict, int]:
        """Defer unattempted tags until their existing macOS release is published.

        This checks publication metadata, not notarization or manual test evidence.
        No status is written for a deferred tag, so it remains eligible later.
        """
        items = validate_matrix(matrix)
        if not items:
            return matrix, 0
        eligible = set()
        wanted = {item["tag"] for item in items}
        for raw in self.api.pages(f"{self.api.root}/releases"):
            release = require_object(raw, "release")
            tag = release.get("tag_name")
            if tag not in wanted or release.get("draft") is not False or release.get("prerelease") is not False:
                continue
            if not release.get("published_at"):
                continue
            assets = release.get("assets")
            if not isinstance(assets, list):
                raise GateError("Release assets are missing or malformed")
            names = {asset.get("name") for asset in assets if isinstance(asset, dict)
                     and asset.get("state") == "uploaded"
                     and type(asset.get("size")) is int and asset["size"] > 0}
            pattern = re.compile(r"EnCap-" + re.escape(tag[1:]) + r"-macos-(?:arm64|intel)-signed\.(?:zip|dmg)")
            if any(isinstance(name, str) and pattern.fullmatch(name) and name + ".sha256" in names for name in names):
                eligible.add(tag)
        kept = [item for item in items if item["tag"] in eligible]
        return {"include": kept}, len(items) - len(kept)

    def claim(self, matrix: dict, target_url: str):
        items = validate_matrix(matrix)
        # Resolve/validate the entire matrix before the first mutation. There is
        # no atomic multi-status API: a partial failure is intentionally fatal.
        for item in items:
            self.mark(item, "pending", "Claimed for weekly smoke; attempted builds are not retried", target_url)

    def baseline(self, pattern: str, targets: list[str]) -> dict:
        # Immutable setup snapshot only: no status reads, payloads, or writes.
        captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        tags = self.tags(pattern)
        targets = parse_targets(",".join(targets))
        snapshot = {"schema": 1, "repository": self.api.repo, "captured_at": captured_at,
                    "entries": [{**row, "target": target} for row in tags for target in targets]}
        validate_baseline(snapshot, self.api.repo)
        return snapshot

    def finalize(self, matrix: dict, run_id: int, attempt: int, target_url: str, require_publication=False) -> dict:
        items = validate_matrix(matrix)
        run_id = positive_int(run_id, "run ID")
        attempt = positive_int(attempt, "run attempt")
        jobs = list(self.api.pages(f"{self.api.root}/actions/runs/{run_id}/attempts/{attempt}/jobs", key="jobs"))
        by_name = {}
        for job in jobs:
            job = require_object(job, "workflow job")
            name = job.get("name")
            if not isinstance(name, str):
                raise GateError("Workflow job has no name")
            by_name.setdefault(name, []).append(job)
        decisions = []
        for item in items:
            matches = by_name.get(f"Smoke {item['tag']} ({item['target']})", [])
            if not matches:
                state, description = "pending", "Smoke job never appeared; retain claim for verified recovery"
            elif len(matches) != 1:
                state, description = "error", "Smoke job name is ambiguous; no automatic retry"
            else:
                job = matches[0]
                conclusion = job.get("conclusion")
                if job.get("status") != "completed":
                    state, description = "error", "Smoke job did not complete; no automatic retry"
                elif job_proven_unstarted(job):
                    state, description = "pending", "Smoke job did not execute; retain claim for verified recovery"
                elif conclusion == "success":
                    state, description = "success", "Weekly native smoke passed"
                elif conclusion in {"failure", "timed_out"}:
                    state, description = "failure", f"Weekly native smoke {conclusion}; no automatic retry"
                else:
                    # Includes cancelled, skipped, neutral, action_required,
                    # startup_failure, stale and any new API conclusion.
                    state, description = "error", "Smoke cancelled, skipped, or inconclusive; no automatic retry"
            if state == 'success' and require_publication:
                publishers = by_name.get(f"Publish {item['tag']} ({item['target']})", [])
                if len(publishers) != 1 or publishers[0].get('status') != 'completed':
                    state, description = 'error', 'Publication missing, ambiguous or unfinished; no automatic retry'
                elif publishers[0].get('conclusion') == 'success':
                    description = 'Weekly native smoke and publication passed'
                elif publishers[0].get('conclusion') in {'failure', 'timed_out'}:
                    state, description = 'failure', 'Native smoke passed but publication failed; no automatic retry'
                else:
                    state, description = 'error', 'Native smoke passed but publication inconclusive; no automatic retry'
            decisions.append((item, state, description))
        summary = {state: 0 for state in sorted(STATES)}
        for item, state, description in decisions:
            if state != "pending":
                self.mark(item, state, description, target_url)
            # Do not turn never-executed work into a terminal error or replace
            # its original pending claim/provenance. The next weekly select
            # verifies the prior attempt is completed before it can recover.
            summary[state] += 1
        return summary


def validate_item(value: Any) -> dict[str, str]:
    item = require_object(value, "matrix entry")
    if set(item) != {"tag", "sha", "target"}:
        raise GateError("Each matrix entry must have exactly tag, sha, and target")
    return {"tag": validate_tag(item["tag"]), "sha": validate_sha(item["sha"]), "target": validate_target(item["target"])}


def validate_matrix(value: Any) -> list[dict[str, str]]:
    value = require_object(value, "matrix")
    if set(value) != {"include"} or not isinstance(value["include"], list) or len(value["include"]) > MAX_MATRIX:
        raise GateError("Matrix must contain only an include list with at most 256 items")
    items = [validate_item(item) for item in value["include"]]
    identities = [(item["tag"], item["sha"], item["target"]) for item in items]
    if len(identities) != len(set(identities)):
        raise GateError("Duplicate matrix entries")
    tag_shas = {}
    for item in items:
        if item["tag"] in tag_shas and tag_shas[item["tag"]] != item["sha"]:
            raise GateError("One matrix tag resolves to multiple commits")
        tag_shas[item["tag"]] = item["sha"]
    return items


def validate_baseline(value: Any, repo: str) -> set[tuple[str, str, str]]:
    value = require_object(value, "baseline")
    if set(value) != {"schema", "repository", "captured_at", "entries"}:
        raise GateError("Baseline must contain exactly schema, repository, captured_at, and entries")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise GateError("Unsupported baseline schema; expected integer 1")
    if validate_repo(value["repository"]) != validate_repo(repo):
        raise GateError("Baseline repository does not match the requested repository")
    timestamp = value["captured_at"]
    if not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", timestamp):
        raise GateError("Baseline captured_at must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise GateError("Baseline captured_at is not a valid date/time") from exc
    if not isinstance(value["entries"], list):
        raise GateError("Baseline entries must be a list")
    identities = set()
    tag_shas = {}
    for raw in value["entries"]:
        item = validate_item(raw)
        identity = (item["tag"], item["sha"], item["target"])
        if identity in identities:
            raise GateError("Duplicate baseline entries")
        if item["tag"] in tag_shas and tag_shas[item["tag"]] != item["sha"]:
            raise GateError("One baseline tag resolves to multiple commits")
        identities.add(identity)
        tag_shas[item["tag"]] = item["sha"]
    return identities


def load_baseline(path: str, repo: str) -> dict:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise GateError(f"Duplicate JSON key in baseline: {key}")
            result[key] = value
        return result

    try:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"Cannot read baseline file {path}: {exc}") from exc
    validate_baseline(snapshot, repo)
    return snapshot


def current_run(api: GitHub) -> tuple[int, int, str]:
    if os.environ.get("GITHUB_REPOSITORY") != api.repo:
        raise GateError("Write commands require GITHUB_REPOSITORY to match --repo")
    if os.environ.get("GITHUB_SERVER_URL", "https://github.com") != "https://github.com":
        raise GateError("Only github.com Actions runs are supported")
    run_id = positive_int(os.environ.get("GITHUB_RUN_ID"), "GITHUB_RUN_ID")
    attempt = positive_int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"), "GITHUB_RUN_ATTEMPT")
    return run_id, attempt, f"https://github.com/{api.repo}/actions/runs/{run_id}/attempts/{attempt}"


def emit_outputs(matrix: dict, summary: dict):
    # One-line JSON prevents newline/command injection in GITHUB_OUTPUT. Do not
    # publish successful empty outputs before *all* selection/claim calls finish.
    output = ("matrix=" + json.dumps(matrix, separators=(",", ":")) + "\n"
              + "has_new=" + str(bool(matrix["include"])).lower() + "\n"
              + "summary=" + json.dumps(summary, separators=(",", ":")) + "\n")
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a", encoding="utf-8") as stream:
            stream.write(output)
    else:
        print(output, end="")
    print("Tag gate: " + json.dumps(summary, sort_keys=True), file=sys.stderr)
    if summary.get("pending") or summary.get("failure") or summary.get("error"):
        print("Running/attempted pending markers and failed/error markers are consumed, not retried. Inspect their run links; "
              "these counts do not imply a successful smoke test.", file=sys.stderr)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    for name in ("select", "baseline", "mark", "finalize"):
        command = sub.add_parser(name)
        command.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
        if name in {"select", "baseline"}:
            command.add_argument("--pattern", required=True, help="Python regex, full-match release tag names")
            command.add_argument("--targets", required=True)
        if name == "select":
            command.add_argument("--max-matrix", type=int, default=MAX_MATRIX)
            command.add_argument("--baseline-file", help="Trusted immutable existing-tag setup snapshot")
            command.add_argument("--require-macos-release", action="store_true", help="Defer tags without an existing published signed macOS package and checksum")
            command.add_argument("--claim", action="store_true", help="Post pending statuses after full successful selection")
        if name == "baseline":
            command.add_argument("--output", help="Create an immutable local setup snapshot (refuses to overwrite)")
        if name == "mark":
            command.add_argument("--tag", required=True)
            command.add_argument("--sha", required=True)
            command.add_argument("--target", required=True)
            command.add_argument("--state", choices=sorted(STATES), required=True)
            command.add_argument("--description", required=True)
        if name == "finalize":
            command.add_argument("--require-publication", action="store_true")
            command.add_argument("--matrix-env", default="SMOKE_MATRIX", help="Environment variable containing trusted gate matrix JSON")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        api = GitHub(args.repo)
        gate = Gate(api)
        if args.command == "select":
            baseline = load_baseline(args.baseline_file, api.repo) if args.baseline_file else None
            matrix, summary = gate.select(args.pattern, parse_targets(args.targets), args.max_matrix, baseline=baseline)
            if args.require_macos_release:
                matrix, summary["deferred_release"] = gate.released_macos_only(matrix)
                summary["new"] = len(matrix["include"])
            if args.claim and matrix["include"]:
                _, _, url = current_run(api)
                gate.claim(matrix, url)
            emit_outputs(matrix, summary)
        elif args.command == "baseline":
            plan = gate.baseline(args.pattern, parse_targets(args.targets))
            content = json.dumps(plan, indent=2) + "\n"
            if args.output:
                with open(args.output, "x", encoding="utf-8") as stream:
                    stream.write(content)
            else:
                print(content, end="")
        elif args.command == "mark":
            _, _, url = current_run(api)
            gate.mark({"tag": args.tag, "sha": args.sha, "target": args.target}, args.state, args.description, url)
        elif args.command == "finalize":
            run_id, attempt, url = current_run(api)
            try:
                matrix = json.loads(os.environ[args.matrix_env])
            except (KeyError, json.JSONDecodeError) as exc:
                raise GateError(f"Missing or invalid JSON environment variable {args.matrix_env}") from exc
            summary = gate.finalize(matrix, run_id, attempt, url, require_publication=args.require_publication)
            print("Finalized: " + json.dumps(summary, sort_keys=True))
            if summary["pending"]:
                print(f"Finalization incomplete: {summary['pending']} native smoke job(s) never executed; "
                      "original pending claims retained for verified recovery after this attempt completes.", file=sys.stderr)
            if summary["failure"] or summary["error"] or summary["pending"]:
                return 1
        return 0
    except (GateError, OSError) as exc:
        print(f"Tag gate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
