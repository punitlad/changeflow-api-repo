"""State machine tying the steps together. Swap `JobStore` for DynamoDB/Aurora when you persist."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from . import change_request as cr
from . import pipeline as pl
from .github_client import GitHubClient
from .merge_strategies import build_strategy, wait_until_merged


class Phase(str, Enum):
    QUEUED = "queued"
    PR_OPEN = "pr_open"
    MERGING = "merging"
    MERGED = "merged"
    PIPELINE_RUNNING = "pipeline_running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ALREADY_ONBOARDED = "already_onboarded"


@dataclass
class Job:
    team: str
    requested_by: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    phase: Phase = Phase.QUEUED
    pr_url: str | None = None
    merge_sha: str | None = None
    run_url: str | None = None
    run_status: str | None = None
    error: str | None = None
    failed_jobs: list[dict] = field(default_factory=list)


class JobStore:
    """In-memory. Replace with a durable store before running more than one replica."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}

    def add(self, job: Job) -> Job:
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)


async def run_job(gh: GitHubClient, job: Job) -> None:
    s = gh.s
    try:
        pr = await cr.open_onboarding_pr(gh, job.team, job.requested_by)
        job.pr_url, job.phase = pr.html_url, Phase.PR_OPEN

        job.phase = Phase.MERGING
        await build_strategy(s).ensure_merging(gh, pr)
        job.merge_sha = await wait_until_merged(gh, pr, s.merge_timeout, s.poll_interval)
        job.phase = Phase.MERGED

        run = await pl.find_run(gh, job.merge_sha)
        job.run_url, job.phase = run["html_url"], Phase.PIPELINE_RUNNING

        async def on_status(status, _conclusion):
            job.run_status = status

        result = await pl.approve_and_monitor(gh, run, on_status)
        job.run_status = result.conclusion
        if result.conclusion == "success":
            job.phase = Phase.SUCCEEDED
        else:
            job.phase = Phase.FAILED
            job.error = f"Pipeline concluded: {result.conclusion}"
            job.failed_jobs = await pl.get_failed_jobs(gh, result.run_id)
    except cr.AlreadyOnboarded:
        job.phase = Phase.ALREADY_ONBOARDED
    except Exception as e:  # surface everything on the job; log in real life
        job.phase, job.error = Phase.FAILED, f"{type(e).__name__}: {e}"
