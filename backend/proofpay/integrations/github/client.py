"""GitHub REST client for public repositories."""

from typing import Any
from urllib.parse import quote

import httpx
import structlog

from proofpay.integrations.github.ports import CheckRun, Issue, PullRequest
from proofpay.settings import Settings
from proofpay.shared.errors import NotFoundError, UpstreamError

BASE_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
JSON_ACCEPT = "application/vnd.github+json"
DIFF_ACCEPT = "application/vnd.github.diff"
CHECKS_PER_PAGE = 100

log = structlog.get_logger(__name__)


def _upstream(status: int | None = None) -> UpstreamError:
    return UpstreamError(
        code="GITHUB_ERROR",
        detail="GitHub request failed",
        params={} if status is None else {"status": status},
    )


class GitHubClient:
    """Implements CodeHost over one long-lived httpx client."""

    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http
        self._headers = {
            "Accept": JSON_ACCEPT,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "proofpay",
        }
        token = settings.github_token.get_secret_value()
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def pull_request(self, owner: str, repo: str, number: int) -> PullRequest:
        data = await self._get_json(f"{_repo(owner, repo)}/pulls/{number}")
        try:
            return PullRequest(
                title=str(data["title"]),
                body=data.get("body") or "",
                head_sha=str(data["head"]["sha"]),
                state=str(data["state"]),
                merged=bool(data.get("merged", False)),
                html_url=str(data["html_url"]),
            )
        except (KeyError, TypeError) as exc:
            raise _upstream() from exc

    async def diff(self, owner: str, repo: str, number: int) -> str:
        response = await self._get(
            f"{_repo(owner, repo)}/pulls/{number}", accept=DIFF_ACCEPT
        )
        return response.text

    async def checks(self, owner: str, repo: str, sha: str) -> list[CheckRun]:
        data = await self._get_json(
            f"{_repo(owner, repo)}/commits/{quote(sha, safe='')}/check-runs",
            params={"per_page": CHECKS_PER_PAGE},
        )
        try:
            return [
                CheckRun(
                    name=str(run["name"]),
                    status=str(run["status"]),
                    conclusion=run.get("conclusion"),
                )
                for run in data["check_runs"]
            ]
        except (KeyError, TypeError) as exc:
            raise _upstream() from exc

    async def issue(self, owner: str, repo: str, number: int) -> Issue:
        data = await self._get_json(f"{_repo(owner, repo)}/issues/{number}")
        try:
            return Issue(
                title=str(data["title"]),
                body=data.get("body") or "",
                html_url=str(data["html_url"]),
            )
        except (KeyError, TypeError) as exc:
            raise _upstream() from exc

    async def _get_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await self._get(path, params=params)
        try:
            body = response.json()
        except ValueError as exc:
            raise _upstream() from exc
        if not isinstance(body, dict):
            raise _upstream()
        return body

    async def _get(
        self,
        path: str,
        *,
        accept: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = (
            self._headers if accept is None else {**self._headers, "Accept": accept}
        )
        try:
            response = await self._http.get(
                f"{BASE_URL}{path}", headers=headers, params=params
            )
        except httpx.TransportError as exc:
            log.warning("github_unavailable", error=type(exc).__name__)
            raise _upstream() from exc
        if response.status_code == httpx.codes.NOT_FOUND:
            raise NotFoundError(
                code="GITHUB_NOT_FOUND", detail="GitHub resource not found"
            )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            log.warning("github_error", status=response.status_code)
            raise _upstream(response.status_code)
        return response


def _repo(owner: str, repo: str) -> str:
    return f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
