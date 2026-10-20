"""Shapes of the answers the AI model must return.

These models are also sent to Gemini as `response_schema`, so they stay plain:
no unions, no optional fields, no defaults that the schema cannot express.
"""

from pydantic import BaseModel, Field


class CriterionIn(BaseModel):
    """One drafted "done when" item."""

    text: str


class CriteriaAnswer(BaseModel):
    """Drafted criteria for an issue: between 2 and 6 items."""

    items: list[CriterionIn] = Field(min_length=2, max_length=6)


class JudgeItem(BaseModel):
    """The judge's verdict on one criterion, with the quote it relies on."""

    criterion_id: str
    met: bool
    quote: str
    file: str
    reason: str


class JudgeAnswer(BaseModel):
    """The judge's answer for all criteria of a bounty."""

    items: list[JudgeItem]
