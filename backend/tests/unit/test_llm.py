"""The model chain, offline: fake backends return raw JSON text."""

import json

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from proofpay.integrations.llm.client import (
    ChainedModel,
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
