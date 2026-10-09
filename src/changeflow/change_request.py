"""Step 1: open the standardized PR that appends {"team": "<name>"} to the JSON array."""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

from .github_client import GitHubClient, GitHubError


class AlreadyOnboarded(Exception):
    """The team is already present in the JSON array; no PR is needed."""


@dataclass
class OpenedPR:
    number: int
    node_id: str
    head_sha: str
    branch: str
    html_url: str


def append_team(raw_json: str, team: str, array_key: str) -> str:
    """Pure function: returns updated JSON text, or raises AlreadyOnboarded.

    Preserves 2-space indentation and a trailing newline so the diff stays one entry.
    """
    doc = json.loads(raw_json)
    arr = doc[array_key] if array_key else doc
    if any(isinstance(e, dict) and e.get("team") == team for e in arr):
        raise AlreadyOnboarded(team)
    arr.append({"team": team})
    return json.dumps(doc, indent=2) + "\n"


def _slug(team: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", team.lower()).strip("-")


async def open_onboarding_pr(gh: GitHubClient, team: str, requested_by: str) -> OpenedPR:
    s = gh.s
    repo = gh.repo_path

    # 1. Base branch tip
    ref = (await gh.request("GET", f"{repo}/git/ref/heads/{s.base_branch}")).json()
    base_sha = ref["object"]["sha"]

    # 2. Current file contents (need its blob sha to update it)
    f = (await gh.request("GET", f"{repo}/contents/{s.json_path}", params={"ref": s.base_branch})).json()
    current = base64.b64decode(f["content"]).decode()
    updated = append_team(current, team, s.json_array_key)  # may raise AlreadyOnboarded

    # 3. Branch (deterministic name => retries are idempotent)
    branch = f"onboard/{_slug(team)}"
    r = await gh.request(
        "POST", f"{repo}/git/refs",
        json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        ok_statuses=(422,),  # 422 = branch already exists (previous attempt)
    )
    if r.status_code == 422:
        await gh.request("PATCH", f"{repo}/git/refs/heads/{branch}", json={"sha": base_sha, "force": True})

    # 4. Commit the file change via the contents API (creates a signed-by-GitHub commit for Apps)
    await gh.request(
        "PUT", f"{repo}/contents/{s.json_path}",
        json={
            "message": f"onboard team {team}",
            "content": base64.b64encode(updated.encode()).decode(),
            "sha": f["sha"],
            "branch": branch,
        },
    )

    # 5. PR
    pr = (await gh.request(
        "POST", f"{repo}/pulls",
        json={
            "title": f"Onboard team: {team}",
            "head": branch,
            "base": s.base_branch,
            "body": f"Automated onboarding for `{team}`.\n\nRequested by: `{requested_by}`",
            "maintainer_can_modify": False,
        },
    )).json()
    return OpenedPR(pr["number"], pr["node_id"], pr["head"]["sha"], branch, pr["html_url"])


async def get_pr_state(gh: GitHubClient, number: int) -> dict:
    return (await gh.request("GET", f"{gh.repo_path}/pulls/{number}")).json()


__all__ = ["open_onboarding_pr", "get_pr_state", "append_team", "AlreadyOnboarded", "OpenedPR", "GitHubError"]
