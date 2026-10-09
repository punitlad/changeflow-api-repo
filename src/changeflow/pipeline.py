"""Steps 3-5: find the run the merge triggered, approve its deployment gate, watch it finish."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .config import ApprovalMode, Settings
from .github_client import GitHubClient, GitHubError


@dataclass
class RunResult:
    run_id: int
    html_url: str
    conclusion: str  # success | failure | cancelled | timed_out | ...


async def find_run(gh: GitHubClient, merge_sha: str) -> dict:
    """The push to base_branch creates a run whose head_sha is the merge commit."""
    s = gh.s
    deadline = time.monotonic() + s.run_discovery_timeout
    while time.monotonic() < deadline:
        r = await gh.request(
            "GET", f"{gh.repo_path}/actions/workflows/{s.pipeline_workflow_file}/runs",
            params={"head_sha": merge_sha, "event": "push", "per_page": 5},
        )
        runs = r.json()["workflow_runs"]
        if runs:
            return runs[0]
        await asyncio.sleep(s.poll_interval)
    raise TimeoutError(f"No run of {s.pipeline_workflow_file} for {merge_sha[:7]}")


async def get_run(gh: GitHubClient, run_id: int) -> dict:
    return (await gh.request("GET", f"{gh.repo_path}/actions/runs/{run_id}")).json()


def reviewable_environment_ids(pending: list[dict], only_env: str | None) -> list[int]:
    """Environments waiting on us that we are actually allowed to approve."""
    ids = []
    for p in pending:
        if not p.get("current_user_can_approve"):
            continue
        if only_env and p["environment"]["name"] != only_env:
            continue
        ids.append(p["environment"]["id"])
    return ids


async def approve_pending(gh: GitHubClient, run_id: int) -> bool:
    """Approve any gates waiting on this run. Returns True if something was approved.

    PENDING_DEPLOYMENTS: uses a *user* token (approver_token). GitHub Apps can't be listed as
    environment reviewers, and "Prevent self-review" blocks whoever triggered the deployment
    (the merger) from approving, so the approver must be a different identity than the merger.
    """
    s = gh.s
    if s.approval_mode is ApprovalMode.PROTECTION_RULE:
        # Custom deployment protection rule: GitHub calls *our* webhook (see api.py) and we
        # answer via POST .../actions/runs/{id}/deployment_protection_rule. Nothing to poll.
        return False

    if not s.approver_token:
        raise RuntimeError("approver_token required for pending_deployments approval mode")
    path = f"{gh.repo_path}/actions/runs/{run_id}/pending_deployments"
    pending = (await gh.request("GET", path, token=s.approver_token)).json()
    env_ids = reviewable_environment_ids(pending, s.pipeline_environment)
    if not env_ids:
        return False
    await gh.request(
        "POST", path, token=s.approver_token,
        json={"environment_ids": env_ids, "state": "approved", "comment": "Auto-approved by changeflow"},
    )
    return True


async def approve_protection_rule(gh: GitHubClient, callback_url: str, environment: str) -> None:
    """Respond to a deployment_protection_rule webhook (APPROVAL_MODE=protection_rule)."""
    await gh.request(
        "POST", callback_url.replace(gh.s.github_api_url, ""),
        json={"environment_name": environment, "state": "approved", "comment": "Checks passed"},
    )


async def approve_and_monitor(gh: GitHubClient, run: dict, on_status=None) -> RunResult:
    s = gh.s
    run_id = run["id"]
    approval_deadline = time.monotonic() + s.approval_timeout
    overall_deadline = time.monotonic() + s.pipeline_timeout
    approved_once = False

    while time.monotonic() < overall_deadline:
        cur = await get_run(gh, run_id)
        if on_status:
            await on_status(cur["status"], cur.get("conclusion"))

        if cur["status"] == "completed":
            return RunResult(run_id, cur["html_url"], cur["conclusion"])

        if cur["status"] == "waiting":  # blocked on environment reviewers
            if time.monotonic() > approval_deadline and not approved_once:
                raise TimeoutError(f"Run {run_id} still waiting for approval")
            try:
                approved_once |= await approve_pending(gh, run_id)
            except GitHubError as e:
                # 403/422 here usually means we aren't a reviewer or self-review is blocked
                raise GitHubError(e.status, f"Approval failed: {e.body}", "pending_deployments") from e

        await asyncio.sleep(s.poll_interval)
    raise TimeoutError(f"Run {run_id} did not finish within {s.pipeline_timeout}s")


async def get_failed_jobs(gh: GitHubClient, run_id: int) -> list[dict]:
    jobs = (await gh.request("GET", f"{gh.repo_path}/actions/runs/{run_id}/jobs")).json()["jobs"]
    return [
        {"name": j["name"], "url": j["html_url"],
         "failed_steps": [st["name"] for st in j["steps"] if st["conclusion"] == "failure"]}
        for j in jobs if j["conclusion"] == "failure"
    ]
