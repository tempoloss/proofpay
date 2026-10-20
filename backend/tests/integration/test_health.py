"""Service endpoints and the RFC 9457 error format."""

import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient

pytestmark = pytest.mark.integration


async def test_healthz_answers_ok(client: AsyncTestClient[Litestar]) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_reports_postgres_up(client: AsyncTestClient[Litestar]) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"postgres": "ok"}}


async def test_unknown_path_returns_problem_json(
    client: AsyncTestClient[Litestar],
) -> None:
    response = await client.get("/no-such-path")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "about:blank"
    assert body["title"]
    assert body["status"] == 404
