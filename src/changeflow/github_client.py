"""Thin async GitHub REST/GraphQL client with GitHub App installation-token auth."""
from __future__ import annotations

import time
from typing import Any

import httpx
import jwt

from .config import Settings


class GitHubError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"GitHub {status} on {url}: {body[:500]}")
        self.status = status
        self.body = body


class InstallationTokenProvider:
    """Mints and caches a short-lived installation token from the App's private key."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self._s = settings
        self._http = http
        self._token: str | None = None
        self._expires_at: float = 0

    async def get(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        now = int(time.time())
        app_jwt = jwt.encode(
            {"iat": now - 30, "exp": now + 540, "iss": str(self._s.app_id)},
            self._s.app_private_key,
            algorithm="RS256",
        )
        r = await self._http.post(
            f"{self._s.github_api_url}/app/installations/{self._s.installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
        )
        if r.status_code >= 300:
            raise GitHubError(r.status_code, r.text, str(r.url))
        data = r.json()
        self._token = data["token"]
        # expires_at is ISO8601; installation tokens last 1h, so be conservative.
        self._expires_at = time.time() + 3300
        return self._token


class GitHubClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self.s = settings
        self.http = http or httpx.AsyncClient(timeout=30)
        self.tokens = InstallationTokenProvider(settings, self.http)

    @property
    def repo_path(self) -> str:
        return f"/repos/{self.s.target_owner}/{self.s.target_repo}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict | None = None,
        token: str | None = None,
        ok_statuses: tuple[int, ...] = (),
    ) -> httpx.Response:
        token = token or await self.tokens.get()
        r = await self.http.request(
            method,
            f"{self.s.github_api_url}{path}",
            json=json,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if r.status_code >= 300 and r.status_code not in ok_statuses:
            raise GitHubError(r.status_code, r.text, str(r.url))
        return r

    async def graphql(self, query: str, variables: dict) -> dict:
        r = await self.request("POST", "/graphql", json={"query": query, "variables": variables})
        body = r.json()
        if body.get("errors"):
            raise GitHubError(200, str(body["errors"]), "graphql")
        return body["data"]
