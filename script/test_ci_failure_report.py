"""Regression checks for the consolidated CI failure tracker."""

import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import report_ci_failures


class CurrentRunFailuresTests(unittest.TestCase):
    def setUp(self):
        self.workflow = sorted(report_ci_failures.MONITORED_WORKFLOWS)[0]

    def run_record(self, branch, status, conclusion, created):
        return {
            "databaseId": 123,
            "workflowName": self.workflow,
            "status": status,
            "conclusion": conclusion,
            "createdAt": created,
            "headBranch": branch,
            "headSha": "abc123",
            "url": "https://github.com/example/repo/actions/runs/123",
            "event": "push",
        }

    def test_pending_successor_and_deleted_branch_do_not_report_old_failures(self):
        runs = [
            self.run_record("main", "completed", "failure", "2026-10-11T10:00:00Z"),
            self.run_record("main", "queued", "", "2026-10-11T11:00:00Z"),
            self.run_record("deleted-branch", "completed", "failure", "2026-10-11T12:00:00Z"),
        ]
        runs[-1]["event"] = "pull_request"

        def fake_gh(*args, **_kwargs):
            self.assertEqual(args[:2], ("run", "list"))
            return SimpleNamespace(stdout=json.dumps(runs))

        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "example/repo"}), \
             patch.object(report_ci_failures, "fetch_json", side_effect=lambda path: [{"name": "main"}] if "/branches?" in path else []), \
             patch.object(report_ci_failures, "gh", side_effect=fake_gh):
            self.assertEqual(report_ci_failures.current_run_failures(), [])

    def test_current_failed_job_remains_visible(self):
        runs = [
            self.run_record("main", "completed", "failure", "2026-10-11T12:00:00Z"),
            self.run_record("open-pr", "completed", "failure", "2026-10-11T12:00:00Z"),
        ]
        runs[-1]["event"] = "pull_request"

        def fake_gh(*args, **_kwargs):
            if args[:2] == ("run", "list"):
                return SimpleNamespace(stdout=json.dumps(runs))
            self.assertEqual(args[:2], ("run", "view"))
            return SimpleNamespace(stdout=json.dumps({"jobs": [{"name": "Linux arm64", "conclusion": "failure"}]}))

        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "example/repo"}), \
             patch.object(report_ci_failures, "fetch_json", side_effect=lambda path: [{"name": "main"}] if "/branches?" in path else [{"head": {"ref": "open-pr"}}] if "/pulls?" in path else []), \
             patch.object(report_ci_failures, "gh", side_effect=fake_gh):
            failures = report_ci_failures.current_run_failures()
        self.assertEqual({item["branch"] for item in failures}, {"main", "open-pr"})
        self.assertTrue(all(item["jobs"] == "Linux arm64" for item in failures))


if __name__ == "__main__":
    unittest.main()
