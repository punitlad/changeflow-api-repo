"""Step 2: get the PR merged. Three pluggable options; pick one via CHANGEFLOW_MERGE_MODE.

All strategies end the same way: `wait_until_merged` returns the merge commit SHA, which is
how the pipeline step finds the run it triggered.
"""
from __future__ import annotations

import asyncio
import time
from typing import Protocol

from .change_request import OpenedPR, get_pr_state
from .config import MergeMode, Settings
from .github_client import GitHubClient, GitHubError


class MergeStrategy(Protocol):
    async def ensure_merging(self, gh: GitHubClient, pr: OpenedPR) -> None: ...


class NativeAutoMerge:
    """Option A: enable GitHub's auto-merge. GitHub merges once required checks/reviews pass.

    Needs on the target repo: "Allow auto-merge" enabled, and a branch ruleset with at least
    one requirement (otherwise GitHub just merges immediately, which is also fine).
    Caveat: if the ruleset requires an approving review, an App cannot approve its own PR,
    so this only works when no review is required, or a second identity approves.
    """

    MUTATION = """
    mutation($id: ID!, $method: PullRequestMergeMethod!) {
      enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: $method}) {
        pullRequest { autoMergeRequest { enabledAt } }
      }
    }"""

    def __init__(self, method: str):
        self.method = method.upper()

    async def ensure_merging(self, gh: GitHubClient, pr: OpenedPR) -> None:
        await gh.graphql(self.MUTATION, {"id": pr.node_id, "method": self.method})


class RulesetBypassMerge:
    """Option B: our GitHub App is on the branch ruleset's bypass list; merge directly.

    Fastest and simplest, but requires the target repo's admins to grant the bypass, which is
    the biggest trust ask of the three. Scope it to "pull request only" bypass if offered.
    """

    def __init__(self, method: str):
        self.method = method

    async def ensure_merging(self, gh: GitHubClient, pr: OpenedPR) -> None:
        await gh.request(
            "PUT", f"{gh.repo_path}/pulls/{pr.number}/merge",
            json={"merge_method": self.method, "sha": pr.head_sha},
        )


class WorkflowGatedMerge:
    """Option C: nothing to do on our side. A workflow in the target repo (pull_request_target
    or a merge-queue bot) sees the PR author is our App's bot login and merges it.

    The trust logic lives in *their* repo, which is usually the easiest to get approved: they
    allow-list `<app-slug>[bot]` as an author. We just wait.
    """

    async def ensure_merging(self, gh: GitHubClient, pr: OpenedPR) -> None:
        return None


def build_strategy(s: Settings) -> MergeStrategy:
    return {
        MergeMode.NATIVE_AUTO_MERGE: lambda: NativeAutoMerge(s.merge_method),
        MergeMode.RULESET_BYPASS: lambda: RulesetBypassMerge(s.merge_method),
        MergeMode.WORKFLOW_GATED: lambda: WorkflowGatedMerge(),
    }[s.merge_mode]()


async def wait_until_merged(gh: GitHubClient, pr: OpenedPR, timeout: int, interval: int) -> str:
    """Poll until merged; returns merge_commit_sha. Raises if closed unmerged or timed out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = await get_pr_state(gh, pr.number)
        if state.get("merged"):
            return state["merge_commit_sha"]
        if state["state"] == "closed":
            raise GitHubError(409, "PR closed without merging", pr.html_url)
        await asyncio.sleep(interval)
    raise TimeoutError(f"PR #{pr.number} not merged within {timeout}s")
