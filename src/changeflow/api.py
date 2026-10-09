"""FastAPI surface. Run: uvicorn changeflow.api:app"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from .config import Settings
from .github_client import GitHubClient
from .orchestrator import Job, JobStore, run_job

TEAM_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class OnboardRequest(BaseModel):
    team: str
    requested_by: str

    @field_validator("team")
    @classmethod
    def valid_team(cls, v: str) -> str:
        # The value lands in a committed JSON file and a branch name: keep it boring.
        if not TEAM_RE.match(v):
            raise ValueError("team must be lowercase alphanumeric/hyphen, 2-63 chars")
        return v


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.gh = GitHubClient(Settings())
    app.state.jobs = JobStore()
    yield
    await app.state.gh.http.aclose()


app = FastAPI(title="changeflow", lifespan=lifespan)


@app.post("/team-onboardings", status_code=202)
async def create(req: OnboardRequest, bg: BackgroundTasks):
    # TODO: authn/z for *your* callers goes here; `requested_by` should come from the caller's identity.
    job = app.state.jobs.add(Job(team=req.team, requested_by=req.requested_by))
    bg.add_task(run_job, app.state.gh, job)
    return {"id": job.id, "status_url": f"/team-onboardings/{job.id}"}


@app.get("/team-onboardings/{job_id}")
async def status(job_id: str):
    job = app.state.jobs.get(job_id)
    if not job:
        raise HTTPException(404)
    return asdict(job)
