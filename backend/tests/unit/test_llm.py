"""The model chain, offline: fake backends return raw JSON text."""

import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai.models import AsyncModels
from pydantic import BaseModel, SecretStr
from structlog.testing import capture_logs

from proofpay.integrations.llm.client import (
    ChainedModel,
    GeminiBackend,
    OpenAICompatBackend,
    build_structured_model,
)
from proofpay.integrations.llm.ports import LLMUnavailable
from proofpay.settings import Settings


class Answer(BaseModel):
    verdict: str
    score: int


class FakeBackend:
    def __init__(self, name: str, text: str | Exception) -> None:
        self.name = name
        self._text = text
        self.calls = 0

    async def complete(self, system: str, prompt: str, schema: type[BaseModel]) -> str:
        self.calls += 1
        if isinstance(self._text, Exception):
            raise self._text
        return self._text

    async def aclose(self) -> None:
        return None


GOOD = json.dumps({"verdict": "ok", "score": 3})


async def test_primary_answer_is_validated_and_returned() -> None:
    primary = FakeBackend("primary", GOOD)
    fallback = FakeBackend("fallback", json.dumps({"verdict": "other", "score": 9}))

    answer = await ChainedModel([primary, fallback]).ask("sys", "prompt", Answer)

    assert answer == Answer(verdict="ok", score=3)
    assert fallback.calls == 0


async def test_fallback_is_used_when_primary_raises() -> None:
    primary = FakeBackend("primary", RuntimeError("HTTP 429"))
    fallback = FakeBackend("fallback", GOOD)

    answer = await ChainedModel([primary, fallback]).ask("sys", "prompt", Answer)

    assert answer == Answer(verdict="ok", score=3)
    assert (primary.calls, fallback.calls) == (1, 1)


@pytest.mark.parametrize(
    "bad_text",
    ['{"verdict": "ok"}', '{"verdict": "ok", "score": "many"}', "not json", ""],
    ids=["missing_field", "wrong_type", "not_json", "empty"],
)
async def test_fallback_is_used_when_primary_json_fails_the_schema(
    bad_text: str,
) -> None:
    primary = FakeBackend("primary", bad_text)
    fallback = FakeBackend("fallback", GOOD)

    answer = await ChainedModel([primary, fallback]).ask("sys", "prompt", Answer)

    assert answer == Answer(verdict="ok", score=3)


async def test_unavailable_when_primary_fails_and_there_is_no_fallback() -> None:
    primary = FakeBackend("primary", RuntimeError("boom"))

    with pytest.raises(LLMUnavailable):
        await ChainedModel([primary]).ask("sys", "prompt", Answer)


async def test_unavailable_when_every_backend_fails() -> None:
    chain = ChainedModel(
        [FakeBackend("primary", "nope"), FakeBackend("fallback", RuntimeError("down"))]
    )

    with pytest.raises(LLMUnavailable):
        await chain.ask("sys", "prompt", Answer)


async def test_unconfigured_chain_is_unavailable_instead_of_crashing() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr(""),
        fallback_base_url="",
        fallback_model="",
        fallback_api_key=SecretStr(""),
    )

    with pytest.raises(LLMUnavailable):
        await build_structured_model(settings).ask("sys", "prompt", Answer)


async def test_openai_compatible_backend_sends_json_mode_request_and_reads_content() -> (
    None
):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        content = f"```json\n{GOOD}\n```"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = OpenAICompatBackend(http, "https://llm.test/v1/", "small-model", "k-123")

    answer = await ChainedModel([backend]).ask("Be strict.", "Judge this.", Answer)

    assert answer == Answer(verdict="ok", score=3)
    [request] = seen
    assert str(request.url) == "https://llm.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer k-123"
    body = json.loads(request.content)
    assert body["model"] == "small-model"
    assert body["response_format"] == {"type": "json_object"}
    system_message, user_message = body["messages"]
    assert system_message["role"] == "system"
    assert "Be strict." in system_message["content"]
    assert '"score"' in system_message["content"]  # the JSON schema is in the prompt
    assert user_message == {"role": "user", "content": "Judge this."}


async def test_openai_compatible_http_error_moves_the_chain_on() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    chain = ChainedModel([OpenAICompatBackend(http, "https://llm.test/v1", "m", "k")])

    with pytest.raises(LLMUnavailable):
        await chain.ask("sys", "prompt", Answer)


class FlakyGemini:
    """Stands in for `generate_content`: plays a script of errors, then text."""

    def __init__(self, script: list[int | str]) -> None:
        self.script = script
        self.calls = 0

    async def __call__(self, **_: object) -> SimpleNamespace:
        step = self.script[self.calls]
        self.calls += 1
        if isinstance(step, int):
            raise genai_errors.APIError(
                step, {"error": {"code": step, "message": "boom", "status": "X"}}
            )
        return SimpleNamespace(text=step)


def _gemini(
    monkeypatch: pytest.MonkeyPatch, script: list[int | str]
) -> tuple[GeminiBackend, FlakyGemini, list[float]]:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    backend = GeminiBackend("k", "m", sleep=sleep)
    flaky = FlakyGemini(script)

    async def generate_content(
        _models: AsyncModels, **kwargs: object
    ) -> SimpleNamespace:
        return await flaky(**kwargs)

    monkeypatch.setattr(AsyncModels, "generate_content", generate_content)
    return backend, flaky, slept


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_gemini_retries_a_transient_error_after_one_second(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    backend, flaky, slept = _gemini(monkeypatch, [status, GOOD])

    answer = await ChainedModel([backend]).ask("sys", "prompt", Answer)

    assert answer == Answer(verdict="ok", score=3)
    assert (flaky.calls, slept) == (2, [1.0])


async def test_gemini_backs_off_one_then_three_seconds_and_gives_up_after_two_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, flaky, slept = _gemini(monkeypatch, [503, 503, 503, GOOD])

    with pytest.raises(LLMUnavailable):
        await ChainedModel([backend]).ask("sys", "prompt", Answer)

    assert (flaky.calls, slept) == (3, [1.0, 3.0])


async def test_gemini_second_retry_can_still_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, flaky, slept = _gemini(monkeypatch, [429, 503, GOOD])

    answer = await ChainedModel([backend]).ask("sys", "prompt", Answer)

    assert answer == Answer(verdict="ok", score=3)
    assert (flaky.calls, slept) == (3, [1.0, 3.0])


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_gemini_does_not_retry_other_client_errors(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    backend, flaky, slept = _gemini(monkeypatch, [status, GOOD])

    with pytest.raises(LLMUnavailable):
        await ChainedModel([backend]).ask("sys", "prompt", Answer)

    assert (flaky.calls, slept) == (1, [])


async def test_failure_log_has_class_and_status_but_no_url_and_is_cut() -> None:
    message = (
        "gateway https://secret-gateway.example/v1/chat?key=abc failed " + "x" * 500
    )
    chain = ChainedModel([FakeBackend("fallback", RuntimeError(message))])

    with capture_logs() as logs, pytest.raises(LLMUnavailable):
        await chain.ask("sys", "prompt", Answer)

    [entry] = [item for item in logs if item["event"] == "llm_backend_failed"]
    assert entry["error"] == "RuntimeError"
    assert "secret-gateway" not in str(logs)
    assert "<url>" in entry["message"]
    assert len(entry["message"]) <= 200


async def test_failure_log_reports_the_http_status_of_a_gateway_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "no"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    chain = ChainedModel([OpenAICompatBackend(http, "https://gw.example/v1", "m", "k")])

    with capture_logs() as logs, pytest.raises(LLMUnavailable):
        await chain.ask("sys", "prompt", Answer)

    [entry] = [item for item in logs if item["event"] == "llm_backend_failed"]
    assert (entry["error"], entry["status"]) == ("HTTPStatusError", 401)
    assert "gw.example" not in str(logs)
