"""GitHub client against a mocked transport: no network, no token."""

from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from proofpay.integrations.github.client import GitHubClient
from proofpay.settings import Settings
from proofpay.shared.errors import NotFoundError, UpstreamError

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler, token: str = "") -> GitHubClient:
    settings = Settings(_env_file=None, github_token=SecretStr(token))
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GitHubClient(http, settings)


class Recorder:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


async def test_missing_resource_is_a_not_found_error() -> None:
    recorder = Recorder(httpx.Response(404, json={"message": "Not Found"}))

    with pytest.raises(NotFoundError) as raised:
        await make_client(recorder).issue("o", "r", 7)

    assert raised.value.code == "GITHUB_NOT_FOUND"
    assert raised.value.status == 404


@pytest.mark.parametrize("status", [403, 500, 502])
async def test_other_http_failures_are_upstream_errors(status: int) -> None:
    recorder = Recorder(httpx.Response(status, json={"message": "rate limit"}))

    with pytest.raises(UpstreamError) as raised:
        await make_client(recorder).pull_request("o", "r", 1)

    assert raised.value.code == "GITHUB_ERROR"


async def test_transport_failure_is_an_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(UpstreamError) as raised:
        await make_client(handler).issue("o", "r", 1)

    assert raised.value.code == "GITHUB_ERROR"


async def test_no_authorization_header_without_a_token() -> None:
    recorder = Recorder(
        httpx.Response(
            200, json={"title": "t", "body": None, "html_url": "https://gh/1"}
        )
    )

    await make_client(recorder, token="").issue("o", "r", 1)

    [request] = recorder.requests
    assert "Authorization" not in request.headers


async def test_bearer_authorization_header_with_a_token() -> None:
    recorder = Recorder(
        httpx.Response(
            200, json={"title": "t", "body": "b", "html_url": "https://gh/1"}
        )
    )

    await make_client(recorder, token="ghp_abc").issue("o", "r", 1)

    [request] = recorder.requests
    assert request.headers["Authorization"] == "Bearer ghp_abc"
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert request.headers["User-Agent"] == "proofpay"


async def test_diff_requests_the_diff_media_type_and_returns_the_text() -> None:
    patch = "diff --git a/f.py b/f.py\n+++ b/f.py\n+x = 1\n"
    recorder = Recorder(httpx.Response(200, text=patch))

    result = await make_client(recorder).diff("owner", "repo", 5)

    assert result == patch
    [request] = recorder.requests
    assert request.headers["Accept"] == "application/vnd.github.diff"
    assert request.url.path == "/repos/owner/repo/pulls/5"


async def test_json_requests_do_not_inherit_the_diff_media_type() -> None:
    patch_response = httpx.Response(200, text="+x")
    json_response = httpx.Response(
        200, json={"title": "t", "body": "", "html_url": "https://gh/1"}
    )
    responses = iter([patch_response, json_response])
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Accept"])
        return next(responses)

    client = make_client(handler)
    await client.diff("o", "r", 1)
    await client.issue("o", "r", 1)

    assert seen == ["application/vnd.github.diff", "application/vnd.github+json"]


async def test_pull_request_maps_fields_and_null_body() -> None:
    payload = {
        "title": "Fix divide",
        "body": None,
        "state": "open",
        "html_url": "https://github.com/o/r/pull/3",
        "head": {"sha": "abc123"},
    }
    recorder = Recorder(httpx.Response(200, json=payload))

    pr = await make_client(recorder).pull_request("o", "r", 3)

    assert (pr.title, pr.body, pr.head_sha, pr.state, pr.html_url) == (
        "Fix divide",
        "",
        "abc123",
        "open",
        "https://github.com/o/r/pull/3",
    )


async def test_checks_lists_runs_with_pending_conclusion_as_none() -> None:
    payload = {
        "total_count": 2,
        "check_runs": [
            {"name": "test", "status": "completed", "conclusion": "success"},
            {"name": "lint", "status": "in_progress", "conclusion": None},
        ],
    }
    recorder = Recorder(httpx.Response(200, json=payload))

    runs = await make_client(recorder).checks("o", "r", "abc123")

    assert [(r.name, r.status, r.conclusion) for r in runs] == [
        ("test", "completed", "success"),
        ("lint", "in_progress", None),
    ]
    [request] = recorder.requests
    assert request.url.path == "/repos/o/r/commits/abc123/check-runs"
    assert request.url.params["per_page"] == "100"


async def test_malformed_payload_is_an_upstream_error() -> None:
    recorder = Recorder(httpx.Response(200, json={"unexpected": True}))

    with pytest.raises(UpstreamError) as raised:
        await make_client(recorder).checks("o", "r", "abc")

    assert raised.value.code == "GITHUB_ERROR"
