#!/usr/bin/env python3
# SPDX-FileCopyrightText: Thomas Lothian
# SPDX-License-Identifier: GPL-3.0-or-later
"""Maintain one GitHub issue with current CI and security failures."""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TITLE = "[CI/CD] Consolidated failure report"
MONITORED_WORKFLOWS = {
    "Build platform applications",
    "Authenticated updater contract",
    "Sign Windows portable packages with Azure",
    "Verify and attest native Linux AppImages",
    "Verify locally notarized Mac qualification packages",
    "CodeQL",
    "Retry failed verification workflows",
}


def gh(*args, check=True):
    return subprocess.run(
        ["gh", *args], check=check, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def fetch_json(path):
    result = gh("api", path)
    return json.loads(result.stdout)


def current_run_failures():
    runs = gh(
        "run", "list", "--limit", "100",
        "--json", "databaseId,workflowName,status,conclusion,createdAt,headBranch,headSha,url",
    )
    grouped = {}
    for run in json.loads(runs.stdout):
        if run["workflowName"] not in MONITORED_WORKFLOWS or run["status"] != "completed":
            continue
        key = (run["workflowName"], run["headBranch"])
        if key not in grouped or run["createdAt"] > grouped[key]["createdAt"]:
            grouped[key] = run

    failures = []
    for (workflow, branch), run in sorted(grouped.items()):
        if run["conclusion"] in ("success", "skipped"):
            continue
        if run["conclusion"] not in ("failure", "timed_out", "cancelled", "action_required", "startup_failure"):
            continue
        try:
            details = json.loads(gh("run", "view", str(run["databaseId"]), "--json", "jobs").stdout)
            jobs = [
                job for job in details["jobs"]
                if job.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required")
            ]
            job_names = ", ".join(job["name"] for job in jobs) or "workflow failed; job detail unavailable"
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            job_names = "workflow failed; job detail unavailable"
        failures.append({
            "key": f"{workflow}|{branch}",
            "workflow": workflow,
            "branch": branch,
            "sha": run["headSha"],
            "jobs": job_names,
            "url": run["url"],
            "created": run["createdAt"],
        })
    return failures


def security_findings():
    repo = os.environ["GITHUB_REPOSITORY"]
    findings = []
    endpoints = (
        ("Dependabot", f"repos/{repo}/dependabot/alerts?state=open&per_page=100"),
        ("Code scanning", f"repos/{repo}/code-scanning/alerts?state=open&per_page=100"),
    )
    for source, endpoint in endpoints:
        try:
            alerts = fetch_json(endpoint)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
            detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
            findings.append({
                "key": f"security-api|{source}",
                "source": source,
                "title": f"{source} alert status unavailable: {detail[:300]}",
                "url": f"https://github.com/{repo}/security",
            })
            continue
        for alert in alerts:
            if source == "Dependabot":
                detail = alert.get("security_advisory", {})
                title = detail.get("summary", "Dependency vulnerability")
                severity = detail.get("severity", "unknown")
                url = alert.get("html_url") or f"https://github.com/{repo}/security/dependabot"
                number = alert.get("number", "unknown")
            else:
                detail = alert.get("rule", {})
                title = detail.get("description", detail.get("name", "Code scanning finding"))
                severity = detail.get("security_severity_level") or detail.get("severity", "unknown")
                url = alert.get("html_url") or f"https://github.com/{repo}/security/code-scanning"
                number = alert.get("number", "unknown")
            findings.append({
                "key": f"security|{source}|{number}",
                "source": source,
                "title": f"{title} ({severity})",
                "url": url,
            })
    return findings


def get_issue():
    issues = fetch_json(f"repos/{os.environ['GITHUB_REPOSITORY']}/issues?state=all&per_page=100")
    matches = [issue for issue in issues if issue.get("title") == TITLE and "pull_request" not in issue]
    return max(matches, key=lambda item: item["number"]) if matches else None


def previous_keys(body):
    match = re.search(r"<!-- ci-active-keys:(.*?) -->", body, flags=re.S)
    if not match:
        return set()
    try:
        return set(json.loads(match.group(1)))
    except json.JSONDecodeError:
        return set()


def render(failures, previous, issue):
    current = {failure["key"] for failure in failures}
    state = {
        key: "Persistent" if key in previous else "New"
        for key in sorted(current)
    }
    resolved = sorted(previous - current)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    lines = [
        "<!-- ci-active-keys:" + json.dumps(sorted(current)) + " -->",
        f"Automatically maintained on {timestamp}. This issue is diagnostic only and never blocks development or releases.",
        "",
    ]
    if failures:
        lines.extend(["## Active failures and findings", ""])
        for item in failures:
            status = state.get(item["key"], "New")
            if "workflow" in item:
                lines.append(
                    f"- **{status} — {item['workflow']} / {item['branch']}** "
                    f"({item['sha'][:12]}): {item['jobs']}. [Workflow run]({item['url']})"
                )
            else:
                lines.append(f"- **{status} — {item['source']}**: {item['title']}. [Details]({item['url']})")
        lines.append("")
    else:
        lines.extend(["## Active failures and findings", "", "None detected in the latest monitored runs or security alerts.", ""])
    if resolved:
        lines.extend(["## Resolved since the previous update", ""])
        lines.extend(f"- **Resolved** — `{key}`" for key in resolved)
        lines.append("")
    if issue:
        lines.append(f"Report issue: https://github.com/{os.environ['GITHUB_REPOSITORY']}/issues/{issue['number']}")
    return "\n".join(lines) + "\n", current


def maintain_issue(failures):
    issue = get_issue()
    old_body = issue.get("body") or "" if issue else ""
    previous = previous_keys(old_body)
    body, active = render(failures, previous, issue)

    if not active and issue is None:
        print("No unresolved CI/CD or security findings; no issue needed.")
        return
    if issue:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write(body)
            body_path = handle.name
        try:
            gh("issue", "edit", str(issue["number"]), "--body-file", body_path)
        finally:
            Path(body_path).unlink(missing_ok=True)
        if active and issue["state"] == "CLOSED":
            gh("issue", "reopen", str(issue["number"]))
        elif not active and issue["state"] == "OPEN":
            gh("issue", "close", str(issue["number"]), "--reason", "completed")
        print(f"Updated failure report issue #{issue['number']}; active findings: {len(active)}.")
        return

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
        handle.write(body)
        body_path = handle.name
    try:
        created = gh("issue", "create", "--title", TITLE, "--body-file", body_path)
    finally:
        Path(body_path).unlink(missing_ok=True)
    print(created.stdout.strip())


def main():
    failures = current_run_failures()
    failures.extend(security_findings())
    maintain_issue(failures)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(f"Could not update the consolidated CI/CD issue: {detail}", file=sys.stderr)
        raise SystemExit(1)
