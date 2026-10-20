"""Structured model chain: Gemini first, an OpenAI-compatible endpoint second.

Each backend returns raw JSON text; the chain validates it against the schema.
A backend that raises, returns nothing or returns JSON that does not validate
is skipped. Neither prompts nor keys are logged.
"""

import json
from collections.abc import Sequence
from typing import Any, Protocol

import httpx
import structlog
from google import genai
from google.genai import types
from pydantic import BaseModel

from proofpay.integrations.llm.ports import LLMUnavailable
from proofpay.settings import Settings

TEMPERATURE = 0.3
# Live probe (20 Oct): a trivial gemini-3.7-flash call took 43 s and a 20 s deadline
# answered 504 DEADLINE_EXCEEDED, so the deadline is generous. The API also rejects
# deadlines below 10 s.
GEMINI_TIMEOUT_MS = 60_000

log = structlog.get_logger(__name__)


class TextBackend(Protocol):
    """One model: returns the raw text of an answer that should be JSON."""

    name: str

    async def complete(
        self, system: str, prompt: str, schema: type[BaseModel]
    ) -> str: ...

    async def aclose(self) -> None: ...


class GeminiBackend:
    """Gemini through google-genai with a JSON response schema."""

    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
        )

    async def complete(self, system: str, prompt: str, schema: type[BaseModel]) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=TEMPERATURE,
            # MINIMAL is rejected with HTTP 400 by gemini-3.7-flash.
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.LOW
            ),
        )
        response = await self._client.aio.models.generate_content(
            model=self._model, contents=prompt, config=config
        )
        return response.text or ""

    async def aclose(self) -> None:
        await self._client.aio.aclose()


class OpenAICompatBackend:
    """Any endpoint that speaks POST {base_url}/chat/completions."""

    name = "fallback"

    def __init__(
        self, http: httpx.AsyncClient, base_url: str, model: str, api_key: str
    ) -> None:
        self._http = http
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._api_key = api_key

    async def complete(self, system: str, prompt: str, schema: type[BaseModel]) -> str:
        hint = (
            "Reply with ONE JSON object only (no markdown, no commentary) that "
            "validates against this JSON Schema:\n"
            + json.dumps(schema.model_json_schema())
        )
        body: dict[str, Any] = {
            "model": self._model,
            "temperature": TEMPERATURE,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": f"{system}\n\n{hint}"},
                {"role": "user", "content": prompt},
            ],
        }
        response = await self._http.post(
            self._url,
            json=body,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError("answer has no choices[0].message.content") from exc
        return _strip_fence(content or "")

    async def aclose(self) -> None:
        await self._http.aclose()


def _strip_fence(text: str) -> str:
    """Removes a markdown code fence some endpoints wrap around JSON."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```")
        stripped = stripped.removesuffix("```")
    return stripped.strip()


class ChainedModel:
    """Implements StructuredModel by trying backends in order."""

    def __init__(self, backends: Sequence[TextBackend]) -> None:
        self._backends = tuple(backends)

    async def ask[T: BaseModel](self, system: str, prompt: str, schema: type[T]) -> T:
        for backend in self._backends:
            try:
                text = await backend.complete(system, prompt, schema)
                answer = schema.model_validate_json(text)
            except Exception as exc:  # any failure moves on to the next model
                log.warning(
                    "llm_backend_failed",
                    backend=backend.name,
                    error=type(exc).__name__,
                )
                continue
            return answer
        raise LLMUnavailable("no model produced a valid answer")

    async def aclose(self) -> None:
        for backend in self._backends:
            await backend.aclose()


def build_structured_model(settings: Settings) -> ChainedModel:
    """Gemini when a key is set, then the fallback when all its settings are set."""
    backends: list[TextBackend] = []
    gemini_key = settings.gemini_api_key.get_secret_value()
    if gemini_key:
        backends.append(GeminiBackend(gemini_key, settings.llm_model))
    fallback_key = settings.fallback_api_key.get_secret_value()
    if settings.fallback_base_url and settings.fallback_model and fallback_key:
        backends.append(
            OpenAICompatBackend(
                httpx.AsyncClient(timeout=httpx.Timeout(20.0)),
                settings.fallback_base_url,
                settings.fallback_model,
                fallback_key,
            )
        )
    return ChainedModel(backends)
