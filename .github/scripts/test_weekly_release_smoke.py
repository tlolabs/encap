"""Offline tests: no gh process, real API request, or status mutation is used."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import weekly_release_smoke as gate

SHA = "a" * 40
OTHER_SHA = "b" * 40
TAG_SHA = "c" * 40
REPO = "example/project"
ROOT = "repos/" + REPO
URL = f"https://github.com/{REPO}/actions/runs/123/attempts/1"
PATTERN = r"v\d+\.\d+\.\d+"
TARGETS = ["linux-x64", "linux-arm64", "windows-x64", "windows-arm64"]


def item(tag="v1.2.3", sha=SHA, target="linux-x64"):
    return {"tag": tag, "sha": sha, "target": target}


def status(tag="v1.2.3", target="linux-x64", state="success", identifier=1):
    return {"id": identifier, "context": gate.context_for(tag, target), "state": state, "target_url": URL}


class FakeAPI(gate.GitHub):
    def __init__(self, tags=None, statuses=None, jobs=None, refs=None, annotations=None, run=None):
        super().__init__(REPO)
        self.tag_rows = tags or []
        self.status_rows = statuses or {}
        self.job_rows = jobs or []
        self.refs = refs or {}
        self.annotations = annotations or {}
        self.run = run if run is not None else {"id": 123, "run_attempt": 1, "status": "in_progress"}
        self.calls = []
        self.writes = []
        self.failure = None
        self.fail_write_at = None

    def request(self, endpoint, payload=None):
        self.calls.append((endpoint, payload))
        if self.failure and self.failure in endpoint:
            raise gate.GateError("mocked HTTP 403 or 500")
        if payload is not None:
            if self.fail_write_at == len(self.writes):
                raise gate.GateError("mocked write failure")
            self.writes.append((endpoint, payload))
            return {"id": len(self.writes), **payload}
        if "/git/ref/tags/" in endpoint:
            from urllib.parse import unquote
            tag = unquote(endpoint.split("/git/ref/tags/", 1)[1])
            if tag in self.refs:
                return self.refs[tag]
            row = next(row for row in self.tag_rows if row["name"] == tag)
            return {"ref": "refs/tags/" + tag, "object": {"type": "commit", "sha": row["commit"]["sha"]}}
        if "/git/tags/" in endpoint:
            return self.annotations[endpoint.rsplit("/", 1)[1]]
        if "/actions/runs/" in endpoint and "?" not in endpoint:
            return self.run
        path, query = endpoint.split("?", 1)
        from urllib.parse import parse_qs
        page = int(parse_qs(query)["page"][0])
        size = int(parse_qs(query)["per_page"][0])
        if path == ROOT + "/tags":
            rows = self.tag_rows
        elif path.endswith("/statuses"):
            rows = self.status_rows.get(path.split("/")[-2], [])
        elif path.endswith("/jobs"):
            return {"total_count": len(self.job_rows), "jobs": self.job_rows[(page - 1) * size:page * size]}
        else:
            raise AssertionError("Unexpected endpoint " + endpoint)
        return rows[(page - 1) * size:page * size]


def tagrow(tag="v1.2.3", sha=SHA):
    return {"name": tag, "commit": {"sha": sha}}


def baseline(entries=None):
    return {"schema": 1, "repository": REPO, "captured_at": "2026-11-08T00:00:00Z", "entries": entries or []}


class IdentityTests(unittest.TestCase):
    def test_context_is_stable_full_hash_tag_and_target_specific(self):
        expected = gate.context_for("v1.2.3", "linux-x64")
        self.assertEqual(expected, gate.context_for("v1.2.3", "linux-x64"))
        self.assertEqual(len(expected.rsplit("/", 1)[1]), 64)
        self.assertNotEqual(expected, gate.context_for("v1.2.4", "linux-x64"))
        self.assertNotEqual(expected, gate.context_for("v1.2.3", "windows-x64"))
        self.assertLess(len(expected), 256)

    def test_valid_tags(self):
        for tag in ("v1.2.3", "release/v1.2.3-rc.1", "v1.2.3+metadata", "release@1"):
            with self.subTest(tag=tag):
                self.assertEqual(gate.validate_tag(tag), tag)

    def test_invalid_tags(self):
        for tag in (None, "", "v1\nforged=true", "v 1", "../x", "v..1", "release//v1", "v1/", "v1.",
                    "v1/.hidden", "v1/foo.lock", "v1.lock/x", "-v1", "v1;echo", "v${thing}", "v1[0]", "v1\\x",
                    "v1:other", "v1~x", "v1^x", "v1?x", "v1*x", "v1@{x}", "v1'é", "a" * 241):
            with self.subTest(tag=tag), self.assertRaises(gate.GateError):
                gate.validate_tag(tag)

    def test_invalid_shas(self):
        for sha in (None, "main", "-x", "a" * 39, "a" * 41, "A" * 40, "g" * 40, SHA + "\n", SHA + "/x"):
            with self.subTest(sha=sha), self.assertRaises(gate.GateError):
                gate.validate_sha(sha)

    def test_targets(self):
        self.assertEqual(gate.parse_targets(",".join(TARGETS)), TARGETS)
        for value in ("", "linux-x64,linux-x64", "linux-x64,", "linux_x64", "linux-x64, windows-x64", "a" * 41):
            with self.subTest(value=value), self.assertRaises(gate.GateError):
                gate.parse_targets(value)

    def test_repo_validation(self):
        self.assertEqual(gate.validate_repo(REPO), REPO)
        for repo in ("", "example", "example/repo/other", "../x", "a/..", "-a/x", "a/x?foo"):
            with self.subTest(repo=repo), self.assertRaises(gate.GateError):
                gate.validate_repo(repo)


class SelectionTests(unittest.TestCase):
    def test_empty_repo_is_no_change(self):
        api = FakeAPI()
        matrix, summary = gate.Gate(api).select(PATTERN, TARGETS)
        self.assertEqual(matrix, {"include": []})
        self.assertEqual(summary["new"], 0)
        self.assertEqual(api.writes, [])

    def test_first_tag_selects_four_targets_without_write(self):
        api = FakeAPI([tagrow()])
        matrix, summary = gate.Gate(api).select(PATTERN, TARGETS)
        self.assertEqual(matrix["include"], [item(target=target) for target in TARGETS])
        self.assertEqual(summary["new"], 4)
        self.assertEqual(api.writes, [])

    def test_fullmatch_excludes_near_match_and_irrelevant_unsafe_tag(self):
        api = FakeAPI([tagrow("v1.2.3-extra"), tagrow("other unsafe"), tagrow()])
        matrix, _ = gate.Gate(api).select(PATTERN, ["linux-x64"])
        self.assertEqual(matrix["include"], [item()])

    def test_matching_unsafe_tag_fails(self):
        with self.assertRaises(gate.GateError):
            gate.Gate(FakeAPI([tagrow("v1;boom")])).select(r"v.*", TARGETS)

    def test_invalid_regex_fails(self):
        with self.assertRaises(gate.GateError):
            gate.Gate(FakeAPI()).select("[", TARGETS)

    def test_all_four_previous_states_are_consumed(self):
        rows = [status(target=target, state=state, identifier=i + 1)
                for i, (target, state) in enumerate(zip(TARGETS, ["success", "pending", "failure", "error"]))]
        matrix, summary = gate.Gate(FakeAPI([tagrow()], {SHA: rows})).select(PATTERN, TARGETS)
        self.assertEqual(matrix, {"include": []})
        for state in gate.STATES:
            self.assertEqual(summary[state], 1)

    def test_latest_status_by_id_even_when_api_order_is_unexpected(self):
        rows = [status(state="pending", identifier=1), status(state="success", identifier=3), status(state="failure", identifier=2)]
        _, summary = gate.Gate(FakeAPI([tagrow()], {SHA: rows})).select(PATTERN, ["linux-x64"])
        self.assertEqual(summary["success"], 1)
        self.assertEqual(summary["failure"], 0)

    def test_distinct_tags_on_same_commit_do_not_collapse(self):
        api = FakeAPI([tagrow(), tagrow("v1.2.4")], {SHA: [status()]})
        matrix, _ = gate.Gate(api).select(PATTERN, ["linux-x64"])
        self.assertEqual(matrix["include"], [item(tag="v1.2.4")])
        self.assertEqual(len([c for c, _ in api.calls if "/statuses?" in c]), 1)

    def test_moved_tag_on_new_commit_is_new(self):
        api = FakeAPI([tagrow(sha=OTHER_SHA)], {SHA: [status()]})
        matrix, _ = gate.Gate(api).select(PATTERN, ["linux-x64"])
        self.assertEqual(matrix["include"], [item(sha=OTHER_SHA)])

    def test_move_back_to_consumed_commit_is_not_new(self):
        matrix, _ = gate.Gate(FakeAPI([tagrow()], {SHA: [status()]})).select(PATTERN, ["linux-x64"])
        self.assertEqual(matrix["include"], [])

    def test_paginates_tags_and_statuses(self):
        api = FakeAPI([tagrow(f"v1.2.{i}") for i in range(101)],
                      {SHA: [{"context": f"other/{i}"} for i in range(100)] + [status("v1.2.100")]})
        matrix, _ = gate.Gate(api).select(PATTERN, ["linux-x64"])
        self.assertEqual(len(matrix["include"]), 100)
        self.assertNotIn(item(tag="v1.2.100"), matrix["include"])
        self.assertTrue(any("/tags?per_page=100&page=2" in c for c, _ in api.calls))
        self.assertTrue(any("/statuses?per_page=100&page=2" in c for c, _ in api.calls))

    def test_exact_full_page_reads_next_empty_page(self):
        api = FakeAPI([tagrow(f"v1.2.{i}") for i in range(100)])
        self.assertEqual(len(gate.Gate(api).tags(PATTERN)), 100)
        self.assertTrue(any("/tags?per_page=100&page=2" in c for c, _ in api.calls))

    def test_api_failure_is_not_empty_selection(self):
        for endpoint in ("/tags?", "/git/ref", "/statuses?"):
            api = FakeAPI([tagrow()])
            api.failure = endpoint
            with self.subTest(endpoint=endpoint), self.assertRaises(gate.GateError):
                gate.Gate(api).select(PATTERN, TARGETS)
            self.assertEqual(api.writes, [])

    def test_matrix_overflow_fails_before_claim(self):
        api = FakeAPI([tagrow(f"v1.2.{i}") for i in range(65)])
        with self.assertRaisesRegex(gate.GateError, "260.*limit 256"):
            gate.Gate(api).select(PATTERN, TARGETS)
        self.assertEqual(api.writes, [])

    def test_matrix_limit_bounds(self):
        for maximum in (0, 257, True):
            with self.subTest(maximum=maximum), self.assertRaises(gate.GateError):
                gate.Gate(FakeAPI()).select(PATTERN, TARGETS, maximum)

    def test_duplicate_tag_fails(self):
        with self.assertRaisesRegex(gate.GateError, "Duplicate tag"):
            gate.Gate(FakeAPI([tagrow(), tagrow()])).select(PATTERN, TARGETS)

    def test_invalid_relevant_status_fails(self):
        for row in (status(state="mystery"), {**status(), "id": False}, {**status(), "id": "wat"}):
            with self.subTest(row=row), self.assertRaises(gate.GateError):
                gate.Gate(FakeAPI([tagrow()], {SHA: [row]})).select(PATTERN, TARGETS)

    def test_duplicate_status_fails(self):
        with self.assertRaisesRegex(gate.GateError, "Duplicate relevant status"):
            gate.Gate(FakeAPI([tagrow()], {SHA: [status(), status()]})).select(PATTERN, TARGETS)


class PeelingTests(unittest.TestCase):
    def test_annotated_tag_uses_peeled_commit(self):
        api = FakeAPI([tagrow()], refs={"v1.2.3": {"ref": "refs/tags/v1.2.3", "object": {"type": "tag", "sha": TAG_SHA}}},
                      annotations={TAG_SHA: {"sha": TAG_SHA, "object": {"type": "commit", "sha": SHA}}})
        self.assertEqual(gate.Gate(api).tags(PATTERN), [{"tag": "v1.2.3", "sha": SHA}])

    def test_nested_annotated_tag(self):
        api = FakeAPI([tagrow()], refs={"v1.2.3": {"ref": "refs/tags/v1.2.3", "object": {"type": "tag", "sha": TAG_SHA}}},
                      annotations={TAG_SHA: {"sha": TAG_SHA, "object": {"type": "tag", "sha": OTHER_SHA}},
                                   OTHER_SHA: {"sha": OTHER_SHA, "object": {"type": "commit", "sha": SHA}}})
        self.assertEqual(gate.Gate(api).tags(PATTERN)[0]["sha"], SHA)

    def test_cycle_fails(self):
        api = FakeAPI([tagrow()], refs={"v1.2.3": {"ref": "refs/tags/v1.2.3", "object": {"type": "tag", "sha": TAG_SHA}}},
                      annotations={TAG_SHA: {"sha": TAG_SHA, "object": {"type": "tag", "sha": TAG_SHA}}})
        with self.assertRaisesRegex(gate.GateError, "Cyclic"):
            gate.Gate(api).tags(PATTERN)

    def test_depth_limit(self):
        shas = [f"{n:040x}" for n in range(1, 19)]
        api = FakeAPI([tagrow()], refs={"v1.2.3": {"ref": "refs/tags/v1.2.3", "object": {"type": "tag", "sha": shas[0]}}},
                      annotations={sha: {"sha": sha, "object": {"type": "tag", "sha": shas[i + 1]}} for i, sha in enumerate(shas[:-1])})
        with self.assertRaisesRegex(gate.GateError, "nesting exceeds"):
            gate.Gate(api).tags(PATTERN)

    def test_wrong_ref_and_unsupported_type_and_mid_selection_move(self):
        for ref in ({"ref": "refs/tags/other", "object": {"type": "commit", "sha": SHA}},
                    {"ref": "refs/tags/v1.2.3", "object": {"type": "tree", "sha": SHA}},
                    {"ref": "refs/tags/v1.2.3", "object": {"type": "commit", "sha": OTHER_SHA}},
                    {"ref": "refs/tags/v1.2.3", "object": {"type": "commit", "sha": "main"}}):
            with self.subTest(ref=ref), self.assertRaises(gate.GateError):
                gate.Gate(FakeAPI([tagrow()], refs={"v1.2.3": ref})).tags(PATTERN)

    def test_wrong_annotation_sha(self):
        api = FakeAPI([tagrow()], refs={"v1.2.3": {"ref": "refs/tags/v1.2.3", "object": {"type": "tag", "sha": TAG_SHA}}},
                      annotations={TAG_SHA: {"sha": OTHER_SHA, "object": {"type": "commit", "sha": SHA}}})
        with self.assertRaisesRegex(gate.GateError, "SHA mismatch"):
            gate.Gate(api).tags(PATTERN)

    def test_slash_tag_is_url_encoded(self):
        api = FakeAPI([tagrow("release/v1.2.3")])
        gate.Gate(api).tags(r"release/v.*")
        self.assertTrue(any("/tags/release%2Fv1.2.3" in endpoint for endpoint, _ in api.calls))


class OrphanClaimTests(unittest.TestCase):
    def select(self, jobs=None, run=None, marker=None):
        api = FakeAPI([tagrow()], {SHA: [marker or status(state="pending")]}, jobs=jobs,
                      run=run or {"id": 123, "run_attempt": 1, "status": "completed"})
        matrix, summary = gate.Gate(api).select(PATTERN, ["linux-x64"])
        return api, matrix, summary

    def test_partial_claim_from_completed_attempt_missing_job_is_recovered(self):
        api, matrix, summary = self.select()
        self.assertEqual(matrix["include"], [item()])
        self.assertEqual(summary["recovered_pending"], 1)
        self.assertEqual(summary["pending"], 0)
        self.assertEqual(api.writes, [])

    def test_running_or_queued_prior_attempt_is_never_recovered(self):
        for run_status in ("in_progress", "queued", "requested", "waiting", "pending"):
            with self.subTest(run_status=run_status):
                api, matrix, summary = self.select(run={"id": 123, "run_attempt": 1, "status": run_status})
                self.assertEqual(matrix["include"], [])
                self.assertEqual(summary["pending"], 1)
                self.assertFalse(any("/jobs?" in endpoint for endpoint, _ in api.calls))

    def test_any_attempted_job_is_consumed_even_if_marker_still_pending(self):
        for conclusion in ("success", "failure", "cancelled", "timed_out", "neutral", "startup_failure", None, "unknown"):
            with self.subTest(conclusion=conclusion):
                _, matrix, summary = self.select(jobs=[{"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": conclusion}])
                self.assertEqual(matrix["include"], [])
                self.assertEqual(summary["pending"], 1)

    def test_explicit_skipped_job_without_executed_steps_recovers(self):
        for steps in ([], [{"name": "Build", "conclusion": "skipped", "started_at": None, "completed_at": None}]):
            with self.subTest(steps=steps):
                _, matrix, summary = self.select(jobs=[{"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "skipped", "steps": steps}])
                self.assertEqual(matrix["include"], [item()])
                self.assertEqual(summary["recovered_pending"], 1)

    def test_skipped_job_with_executed_step_does_not_recover(self):
        for step in ({"conclusion": "success"}, {"conclusion": "skipped", "started_at": "2026-11-08T00:00:00Z"},
                     {"conclusion": "skipped", "completed_at": "2026-11-08T00:00:00Z"}):
            with self.subTest(step=step):
                _, matrix, summary = self.select(jobs=[{"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "skipped", "steps": [step]}])
                self.assertEqual(matrix["include"], [])
                self.assertEqual(summary["pending"], 1)

    def test_missing_steps_for_skipped_job_fails_closed(self):
        with self.assertRaisesRegex(gate.GateError, "lacks step evidence"):
            self.select(jobs=[{"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "skipped"}])

    def test_unknown_or_malformed_provenance_fails_closed(self):
        for url in (None, "", URL.replace("example/project", "other/repo"), URL.replace("https://", "http://"),
                    URL.replace("/attempts/1", ""), URL + "?x=1", URL.replace("123", "../123")):
            with self.subTest(url=url), self.assertRaisesRegex(gate.GateError, "unknown run/attempt provenance"):
                self.select(marker={**status(state="pending"), "target_url": url})

    def test_attempt_identity_and_unknown_status_fail_closed(self):
        for run in ({"id": 124, "run_attempt": 1, "status": "completed"},
                    {"id": 123, "run_attempt": 2, "status": "completed"},
                    {"id": 123, "run_attempt": 1, "status": "unexpected"}):
            with self.subTest(run=run), self.assertRaises(gate.GateError):
                self.select(run=run)

    def test_duplicate_or_unfinished_matching_jobs_fail_closed(self):
        job = {"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "success"}
        for jobs in ([job, job], [{**job, "status": "in_progress"}]):
            with self.subTest(jobs=jobs), self.assertRaises(gate.GateError):
                self.select(jobs=jobs)

    def test_attempt_and_jobs_api_failures_do_not_drop_claims_or_return_no_change(self):
        for failure in ("/attempts/1", "/jobs?"):
            api = FakeAPI([tagrow()], {SHA: [status(state="pending")]}, run={"id": 123, "run_attempt": 1, "status": "completed"})
            api.failure = failure
            with self.subTest(failure=failure), self.assertRaises(gate.GateError):
                gate.Gate(api).select(PATTERN, ["linux-x64"])
            self.assertEqual(api.writes, [])

    def test_attempt_evidence_is_cached_across_pending_targets(self):
        api = FakeAPI([tagrow()], {SHA: [status(target=t, state="pending", identifier=i + 1) for i, t in enumerate(TARGETS)]},
                      run={"id": 123, "run_attempt": 1, "status": "completed"})
        matrix, summary = gate.Gate(api).select(PATTERN, TARGETS)
        self.assertEqual(len(matrix["include"]), 4)
        self.assertEqual(summary["recovered_pending"], 4)
        self.assertEqual(sum(endpoint.endswith("/attempts/1") for endpoint, _ in api.calls), 1)
        self.assertEqual(sum("/jobs?" in endpoint for endpoint, _ in api.calls), 1)

    def test_recovered_claim_counts_toward_matrix_limit(self):
        api = FakeAPI([tagrow()], {SHA: [status(state="pending")]}, run={"id": 123, "run_attempt": 1, "status": "completed"})
        with self.assertRaisesRegex(gate.GateError, "4.*limit 1"):
            gate.Gate(api).select(PATTERN, TARGETS, max_matrix=1)


class BaselineTests(unittest.TestCase):
    def test_exact_identity_is_excluded_before_status_lookup(self):
        api = FakeAPI([tagrow()])
        api.failure = "/statuses"
        matrix, summary = gate.Gate(api).select(PATTERN, TARGETS, baseline=baseline([item(target=t) for t in TARGETS]))
        self.assertEqual(matrix["include"], [])
        self.assertEqual(summary["baseline"], 4)
        self.assertEqual(summary["success"], 0)
        self.assertFalse(any("/statuses" in endpoint for endpoint, _ in api.calls))
        self.assertEqual(api.writes, [])

    def test_moved_tag_remains_eligible(self):
        api = FakeAPI([tagrow(sha=OTHER_SHA)])
        matrix, summary = gate.Gate(api).select(PATTERN, ["linux-x64"], baseline=baseline([item()]))
        self.assertEqual(matrix["include"], [item(sha=OTHER_SHA)])
        self.assertEqual(summary["baseline"], 0)

    def test_new_target_remains_eligible(self):
        api = FakeAPI([tagrow()])
        matrix, summary = gate.Gate(api).select(PATTERN, TARGETS, baseline=baseline([item()]))
        self.assertEqual(matrix["include"], [item(target=t) for t in TARGETS[1:]])
        self.assertEqual(summary["baseline"], 1)

    def test_new_tag_on_same_sha_remains_eligible(self):
        api = FakeAPI([tagrow(), tagrow("v1.2.4")])
        matrix, summary = gate.Gate(api).select(PATTERN, ["linux-x64"], baseline=baseline([item()]))
        self.assertEqual(matrix["include"], [item(tag="v1.2.4")])
        self.assertEqual(summary["baseline"], 1)

    def test_multiple_baselined_tags_on_same_sha_remain_distinct(self):
        api = FakeAPI([tagrow(), tagrow("v1.2.4")])
        entries = [item(tag=tag, target=target) for tag in ("v1.2.3", "v1.2.4") for target in TARGETS]
        matrix, summary = gate.Gate(api).select(PATTERN, TARGETS, baseline=baseline(entries))
        self.assertEqual(matrix["include"], [])
        self.assertEqual(summary["baseline"], 8)
        self.assertFalse(any("/statuses" in endpoint for endpoint, _ in api.calls))

    def test_empty_snapshot_means_no_exclusions(self):
        matrix, summary = gate.Gate(FakeAPI([tagrow()])).select(PATTERN, ["linux-x64"], baseline=baseline())
        self.assertEqual(matrix["include"], [item()])
        self.assertEqual(summary["baseline"], 0)

    def test_wrong_repository_fails_before_api_access(self):
        api = FakeAPI([tagrow()])
        with self.assertRaisesRegex(gate.GateError, "repository does not match"):
            gate.Gate(api).select(PATTERN, TARGETS, baseline={**baseline(), "repository": "wrong/repo"})
        self.assertEqual(api.calls, [])

    def test_unknown_or_noninteger_schema_rejected(self):
        for schema in (0, 2, "1", True, None, 1.0):
            with self.subTest(schema=schema), self.assertRaisesRegex(gate.GateError, "Unsupported baseline schema"):
                gate.validate_baseline({**baseline(), "schema": schema}, REPO)

    def test_bad_metadata_shape_rejected(self):
        for value in (None, [], {}, {**baseline(), "payloads": []}, {k: v for k, v in baseline().items() if k != "captured_at"}):
            with self.subTest(value=value), self.assertRaises(gate.GateError):
                gate.validate_baseline(value, REPO)

    def test_bad_timestamp_rejected(self):
        for timestamp in (None, "", "2026-11-08", "2026-11-08T00:00:00+00:00", "2026-13-08T00:00:00Z", "2026-02-30T00:00:00Z", "2026-11-08T24:00:00Z"):
            with self.subTest(timestamp=timestamp), self.assertRaises(gate.GateError):
                gate.validate_baseline({**baseline(), "captured_at": timestamp}, REPO)

    def test_corrupt_entries_and_duplicates_rejected(self):
        for entries in (None, {}, [None], [item(sha="main")], [{**item(), "payload": {"state": "success"}}],
                        [item(), item()], [item(), item(sha=OTHER_SHA)]):
            with self.subTest(entries=entries), self.assertRaises(gate.GateError):
                gate.validate_baseline({**baseline(), "entries": entries}, REPO)

    def test_read_round_trip_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            snapshot = baseline([item()])
            path.write_text(json.dumps(snapshot))
            self.assertEqual(gate.load_baseline(str(path), REPO), snapshot)
            for content in ("{broken", "null", '{"schema": 1, "schema": 2}', '[]'):
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(gate.GateError):
                    gate.load_baseline(str(path), REPO)
            path.write_bytes(b"\xff")
            with self.assertRaises(gate.GateError):
                gate.load_baseline(str(path), REPO)
            with self.assertRaises(gate.GateError):
                gate.load_baseline(str(path) + ".missing", REPO)

    def test_cli_invalid_baseline_does_not_emit_no_change_or_access_api(self):
        api = FakeAPI([tagrow()])
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text("{}")
            with patch.object(gate, "GitHub", return_value=api), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                result = gate.main(["select", "--repo", REPO, "--pattern", PATTERN, "--targets", ",".join(TARGETS), "--baseline-file", str(path)])
        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(api.calls, [])

    def test_cli_select_reads_snapshot_and_skips_without_claim(self):
        api = FakeAPI([tagrow()])
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(json.dumps(baseline([item(target=t) for t in TARGETS])))
            with patch.object(gate, "GitHub", return_value=api), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()), patch.dict(os.environ, {}, clear=True):
                result = gate.main(["select", "--repo", REPO, "--pattern", PATTERN, "--targets", ",".join(TARGETS), "--baseline-file", str(path), "--claim"])
        self.assertEqual(result, 0)
        self.assertIn("has_new=false\n", stdout.getvalue())
        self.assertEqual(api.writes, [])

    def test_cli_baseline_creates_but_never_overwrites_snapshot(self):
        api = FakeAPI([tagrow()])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            args = ["baseline", "--repo", REPO, "--pattern", PATTERN, "--targets", ",".join(TARGETS), "--output", str(path)]
            with patch.object(gate, "GitHub", return_value=api), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gate.main(args), 0)
                original = path.read_bytes()
                self.assertEqual(gate.main(args), 1)
                self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(gate.load_baseline(str(path), REPO)["entries"]), 4)
        self.assertFalse(any("/statuses" in endpoint for endpoint, _ in api.calls))
        self.assertEqual(api.writes, [])

    def test_snapshot_with_over_256_entries_is_valid(self):
        entries = [item(tag=f"v1.2.{i}", target=t) for i in range(65) for t in TARGETS]
        self.assertEqual(len(gate.validate_baseline(baseline(entries), REPO)), 260)


class MutationTests(unittest.TestCase):
    def test_baseline_is_read_only_snapshot_without_status_payloads(self):
        api = FakeAPI([tagrow()], {SHA: [status(state="failure")]})
        plan = gate.Gate(api).baseline(PATTERN, TARGETS)
        self.assertEqual(plan["entries"], [item(target=t) for t in TARGETS])
        self.assertEqual(set(plan), {"schema", "repository", "captured_at", "entries"})
        self.assertEqual(plan["schema"], 1)
        self.assertEqual(plan["repository"], REPO)
        self.assertTrue(plan["captured_at"].endswith("Z"))
        self.assertFalse(any("/statuses" in endpoint for endpoint, _ in api.calls))
        self.assertEqual(api.writes, [])

    def test_baseline_not_limited_to_matrix_size(self):
        api = FakeAPI([tagrow(f"v1.2.{i}") for i in range(65)])
        self.assertEqual(len(gate.Gate(api).baseline(PATTERN, TARGETS)["entries"]), 260)
        self.assertEqual(api.writes, [])

    def test_claim_posts_each_pending_with_run_link(self):
        api = FakeAPI()
        gate.Gate(api).claim({"include": [item(target=t) for t in TARGETS]}, URL)
        self.assertEqual(len(api.writes), 4)
        for endpoint, payload in api.writes:
            self.assertEqual(endpoint, ROOT + "/statuses/" + SHA)
            self.assertEqual(payload["state"], "pending")
            self.assertEqual(payload["target_url"], URL)

    def test_invalid_matrix_fails_before_any_write(self):
        invalid = [{"include": [item(), item()]}, {"include": [item(), item(sha=OTHER_SHA)]},
                   {"include": [item(), item(sha="main")]}, {"include": [{**item(), "runner": "evil"}]},
                   {"include": [item()] * 257}, {"include": {}, "other": []}]
        for matrix in invalid:
            api = FakeAPI()
            with self.subTest(matrix=str(matrix)[:100]), self.assertRaises(gate.GateError):
                gate.Gate(api).claim(matrix, URL)
            self.assertEqual(api.writes, [])

    def test_partial_claim_failure_is_fatal_without_retry(self):
        api = FakeAPI()
        api.fail_write_at = 1
        with self.assertRaises(gate.GateError):
            gate.Gate(api).claim({"include": [item(target=t) for t in TARGETS]}, URL)
        self.assertEqual(len(api.writes), 1)
        self.assertEqual(len(api.calls), 2)

    def test_mark_rejects_invalid_description_and_url(self):
        for description, url in (("", URL), ("x" * 141, URL), ("line\nbreak", URL), ("okay", "https://evil.example"),
                                 ("okay", "https://github.com/other/repo/actions/runs/1")):
            api = FakeAPI()
            with self.subTest(description=description, url=url), self.assertRaises(gate.GateError):
                gate.Gate(api).mark(item(), "success", description, url)
            self.assertEqual(api.writes, [])

    def test_mark_checks_confirmation_response(self):
        api = FakeAPI()
        with patch.object(api, "request", return_value={"state": "success", "context": "wrong"}):
            with self.assertRaisesRegex(gate.GateError, "outcome is uncertain"):
                gate.Gate(api).mark(item(), "success", "ok", URL)


class FinalizeTests(unittest.TestCase):
    def test_all_conclusions_and_missing_jobs(self):
        outcomes = {"success": "success", "failure": "failure", "timed_out": "failure", "cancelled": "error",
                    "skipped": "error", "neutral": "error", "action_required": "error", "startup_failure": "error",
                    "stale": "error", "new_conclusion": "error", None: "error"}
        for conclusion, expected in outcomes.items():
            job = {"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": conclusion}
            api = FakeAPI(jobs=[job])
            with self.subTest(conclusion=conclusion):
                summary = gate.Gate(api).finalize({"include": [item()]}, 123, 1, URL)
                self.assertEqual(summary[expected], 1)
                self.assertEqual(api.writes[0][1]["state"], expected)

    def test_duplicate_and_running_jobs_are_errors(self):
        job = {"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "success"}
        for jobs in ([job, job], [{**job, "status": "in_progress"}]):
            api = FakeAPI(jobs=jobs)
            with self.subTest(jobs=jobs):
                summary = gate.Gate(api).finalize({"include": [item()]}, 123, 1, URL)
                self.assertEqual(summary["error"], 1)

    def test_missing_job_preserves_original_pending_claim(self):
        api = FakeAPI()
        summary = gate.Gate(api).finalize({"include": [item()]}, 123, 1, URL)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["error"], 0)
        self.assertEqual(api.writes, [])

    def test_explicit_unexecuted_skipped_jobs_preserve_pending(self):
        for steps in ([], [{"conclusion": "skipped", "started_at": None, "completed_at": None}]):
            api = FakeAPI(jobs=[{"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "skipped", "steps": steps}])
            with self.subTest(steps=steps):
                summary = gate.Gate(api).finalize({"include": [item()]}, 123, 1, URL)
                self.assertEqual(summary["pending"], 1)
                self.assertEqual(api.writes, [])

    def test_proven_unstarted_cancellation_preserves_pending(self):
        api = FakeAPI(jobs=[{"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "cancelled", "started_at": None, "steps": []}])
        summary = gate.Gate(api).finalize({"include": [item()]}, 123, 1, URL)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(api.writes, [])

    def test_ambiguous_or_attempted_cancellation_is_terminal_error(self):
        base = {"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "cancelled"}
        for detail in ({}, {"steps": []}, {"started_at": None}, {"started_at": "2026-11-08T01:00:00Z", "steps": []},
                       {"started_at": None, "steps": [{"conclusion": "success"}]}, {"started_at": None, "steps": [None]},
                       {"started_at": None, "steps": [{"conclusion": "skipped", "started_at": "2026-11-08T01:00:00Z"}]}):
            api = FakeAPI(jobs=[{**base, **detail}])
            with self.subTest(detail=detail):
                summary = gate.Gate(api).finalize({"include": [item()]}, 123, 1, URL)
                self.assertEqual(summary["error"], 1)
                self.assertEqual(api.writes[0][1]["state"], "error")

    def test_attempted_or_unknown_skipped_jobs_are_terminal_errors(self):
        for steps in (None, [{"conclusion": "success"}], [None], [{"conclusion": "skipped", "completed_at": "2026-11-08T01:00:00Z"}]):
            api = FakeAPI(jobs=[{"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "skipped", "steps": steps}])
            with self.subTest(steps=steps):
                summary = gate.Gate(api).finalize({"include": [item()]}, 123, 1, URL)
                self.assertEqual(summary["error"], 1)
                self.assertEqual(api.writes[0][1]["state"], "error")

    def test_finalized_unexecuted_claim_recovers_only_after_attempt_completes(self):
        job = {"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "cancelled", "started_at": None, "steps": []}
        for jobs in ([], [job], [{**job, "conclusion": "skipped"}]):
            api = FakeAPI([tagrow()], {SHA: [status(state="pending")]}, jobs=jobs)
            helper = gate.Gate(api)
            with self.subTest(jobs=jobs):
                self.assertEqual(helper.finalize({"include": [item()]}, 123, 1, URL)["pending"], 1)
                self.assertEqual(api.writes, [])
                matrix, summary = helper.select(PATTERN, ["linux-x64"])
                self.assertEqual(matrix["include"], [])
                self.assertEqual(summary["pending"], 1)
                api.run["status"] = "completed"
                matrix, summary = helper.select(PATTERN, ["linux-x64"])
                self.assertEqual(matrix["include"], [item()])
                self.assertEqual(summary["recovered_pending"], 1)

    def test_cli_incomplete_finalization_returns_nonzero_and_reports_pending(self):
        api = FakeAPI()
        stdout, stderr = io.StringIO(), io.StringIO()
        env = {"GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "SMOKE_MATRIX": json.dumps({"include": [item()]})}
        with patch.object(gate, "GitHub", return_value=api), patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = gate.main(["finalize"])
        self.assertEqual(result, 1)
        self.assertIn('"pending": 1', stdout.getvalue())
        self.assertIn("Finalization incomplete", stderr.getvalue())
        self.assertEqual(api.writes, [])

    def test_mixed_finalization_preserves_only_unexecuted_claim(self):
        jobs = [{"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "success"},
                {"name": "Smoke v1.2.3 (linux-arm64)", "status": "completed", "conclusion": "failure"},
                {"name": "Smoke v1.2.3 (windows-x64)", "status": "completed", "conclusion": "skipped", "steps": []},
                {"name": "Smoke v1.2.3 (windows-arm64)", "status": "completed", "conclusion": "cancelled"}]
        api = FakeAPI(jobs=jobs)
        summary = gate.Gate(api).finalize({"include": [item(target=t) for t in TARGETS]}, 123, 1, URL)
        self.assertEqual(summary, {"error": 1, "failure": 1, "pending": 1, "success": 1})
        self.assertEqual(len(api.writes), 3)
        self.assertFalse(any(payload["context"] == gate.context_for("v1.2.3", "windows-x64") for _, payload in api.writes))

    def test_jobs_are_attempt_specific_and_paginated(self):
        jobs = [{"name": "unrelated " + str(i), "status": "completed", "conclusion": "success"} for i in range(100)]
        jobs += [{"name": "Smoke v1.2.3 (linux-x64)", "status": "completed", "conclusion": "success"}]
        api = FakeAPI(jobs=jobs)
        summary = gate.Gate(api).finalize({"include": [item()]}, 123, 2, URL.replace("/1", "/2"))
        self.assertEqual(summary["success"], 1)
        self.assertTrue(any("/runs/123/attempts/2/jobs?per_page=100&page=2" in c for c, _ in api.calls))

    def test_jobs_api_failure_never_writes_guessed_success(self):
        api = FakeAPI()
        api.failure = "/jobs?"
        with self.assertRaises(gate.GateError):
            gate.Gate(api).finalize({"include": [item()]}, 123, 1, URL)
        self.assertEqual(api.writes, [])


class TransportAndCLITests(unittest.TestCase):
    def test_get_uses_explicit_get_no_shell(self):
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "[]", "")) as run:
            self.assertEqual(gate.GitHub(REPO).request(ROOT + "/tags?per_page=100&page=1"), [])
        args, kwargs = run.call_args
        self.assertIn("GET", args[0])
        self.assertEqual(args[0][0:4], ["gh", "api", "--hostname", "github.com"])
        self.assertNotIn("shell", kwargs)
        self.assertIsNone(kwargs["input"])

    def test_post_uses_json_stdin(self):
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run:
            gate.GitHub(REPO).request(ROOT + "/statuses/" + SHA, {"description": "safe text", "state": "pending"})
        self.assertIn("POST", run.call_args.args[0])
        self.assertEqual(json.loads(run.call_args.kwargs["input"])["state"], "pending")

    def test_process_errors_and_invalid_json_fail(self):
        for result in (subprocess.CompletedProcess([], 1, "", "HTTP 403"), subprocess.CompletedProcess([], 0, "not json", "")):
            with patch.object(subprocess, "run", return_value=result), self.assertRaises(gate.GateError):
                gate.GitHub(REPO).request(ROOT + "/tags")
        for exc in (OSError("missing gh"), subprocess.TimeoutExpired("gh", 120)):
            with patch.object(subprocess, "run", side_effect=exc), self.assertRaises(gate.GateError):
                gate.GitHub(REPO).request(ROOT + "/tags")

    def test_pagination_rejects_invalid_repeated_or_incomplete_pages(self):
        api = gate.GitHub(REPO)
        for value in ({"wrong": []}, [1] * 101):
            with patch.object(api, "request", return_value=value), self.assertRaises(gate.GateError):
                list(api.pages(ROOT + "/tags"))
        with patch.object(api, "request", return_value=[1] * 100), self.assertRaisesRegex(gate.GateError, "repeated page"):
            list(api.pages(ROOT + "/tags"))
        with patch.object(api, "request", return_value={"jobs": [], "total_count": 10}), self.assertRaisesRegex(gate.GateError, "incomplete pagination"):
            list(api.pages(ROOT + "/jobs", key="jobs"))

    def test_current_run_requires_matching_repo_and_valid_identifiers(self):
        valid = {"GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
        with patch.dict(os.environ, valid, clear=True):
            self.assertEqual(gate.current_run(gate.GitHub(REPO)), (123, 1, URL))
        for change in ({"GITHUB_REPOSITORY": "other/repo"}, {"GITHUB_RUN_ID": "../x"},
                       {"GITHUB_RUN_ATTEMPT": "0"}, {"GITHUB_SERVER_URL": "https://evil.example"}):
            with patch.dict(os.environ, {**valid, **change}, clear=True), self.assertRaises(gate.GateError):
                gate.current_run(gate.GitHub(REPO))

    def test_outputs_exact_single_line_json(self):
        matrix = {"include": [item()]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(path)}, clear=True), contextlib.redirect_stderr(io.StringIO()):
                gate.emit_outputs(matrix, {"new": 1})
            lines = path.read_text().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(json.loads(lines[0].split("=", 1)[1]), matrix)
        self.assertEqual(lines[1], "has_new=true")

    def test_cli_failure_never_emits_has_new_false(self):
        api = FakeAPI([tagrow()])
        api.failure = "/tags?"
        stdout = io.StringIO()
        with patch.object(gate, "GitHub", return_value=api), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            result = gate.main(["select", "--repo", REPO, "--pattern", PATTERN, "--targets", ",".join(TARGETS)])
        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")

    def test_cli_partial_claim_never_emits_matrix(self):
        api = FakeAPI([tagrow()])
        api.fail_write_at = 1
        stdout = io.StringIO()
        with patch.object(gate, "GitHub", return_value=api), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()), \
                patch.dict(os.environ, {"GITHUB_REPOSITORY": REPO, "GITHUB_RUN_ID": "123"}, clear=True):
            result = gate.main(["select", "--pattern", PATTERN, "--targets", ",".join(TARGETS), "--claim"])
        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(len(api.writes), 1)

    def test_cli_no_change_is_success_and_explicit_false(self):
        stdout = io.StringIO()
        with patch.object(gate, "GitHub", return_value=FakeAPI()), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()), \
                patch.dict(os.environ, {}, clear=True):
            result = gate.main(["select", "--repo", REPO, "--pattern", PATTERN, "--targets", ",".join(TARGETS)])
        self.assertEqual(result, 0)
        self.assertIn("has_new=false\n", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
