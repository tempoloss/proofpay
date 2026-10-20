"""Structured model port: a prompt in, a validated pydantic object out."""

from typing import Protocol

from pydantic import BaseModel


class LLMUnavailable(Exception):  # noqa: N818 - public name fixed by the contract
    """No model produced an answer that validates against the schema."""


class StructuredModel(Protocol):
    async def ask[T: BaseModel](self, system: str, prompt: str, schema: type[T]) -> T:
        """Returns the model's answer parsed into schema.

        Raises LLMUnavailable when every configured model failed or answered
        with JSON that does not validate.
        """
        ...
