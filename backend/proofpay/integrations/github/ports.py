"""Code host port: read issues, pull requests, diffs and CI check runs."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PullRequest:
    title: str
    body: str
    head_sha: str
    state: str  # "open" or "closed"
    merged: bool
    html_url: str


@dataclass(frozen=True, slots=True)
class CheckRun:
    name: str
    status: str
    conclusion: str | None


@dataclass(frozen=True, slots=True)
class Issue:
    title: str
    body: str
    html_url: str


class CodeHost(Protocol):
    async def pull_request(self, owner: str, repo: str, number: int) -> PullRequest: ...

    async def diff(self, owner: str, repo: str, number: int) -> str:
        """Unified diff of the whole pull request."""
        ...

    async def checks(self, owner: str, repo: str, sha: str) -> list[CheckRun]: ...

    async def issue(self, owner: str, repo: str, number: int) -> Issue: ...
