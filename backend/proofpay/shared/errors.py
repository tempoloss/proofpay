"""Domain exceptions and their mapping to RFC 9457 problem+json."""

from dataclasses import dataclass, field
from typing import Any

# Base prefix of error types: the value of the `type` field in problem+json.
PROBLEM_TYPE_PREFIX = "urn:proofpay:error:"


@dataclass(frozen=True, slots=True)
class DomainError(Exception):
    """Base domain exception.

    code   - machine-readable code (for example, "INVALID_TRANSITION").
    detail - human-readable explanation.
    params - substitution values for client-side localisation.
    status - HTTP status, if the error is returned to the client.
    """

    code: str
    detail: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    status: int = 400


# Subclasses are declared as dataclasses on purpose: without the decorator the
# `status` annotation in a subclass would stay a plain class attribute, while
# the inherited constructor would still write 400 into the instance, and every
# "not found" error would leave the API as a 400.
@dataclass(frozen=True, slots=True)
class NotFoundError(DomainError):
    status: int = 404


@dataclass(frozen=True, slots=True)
class ForbiddenError(DomainError):
    status: int = 403


@dataclass(frozen=True, slots=True)
class ConflictError(DomainError):
    status: int = 409


@dataclass(frozen=True, slots=True)
class UnprocessableError(DomainError):
    status: int = 422


@dataclass(frozen=True, slots=True)
class UpstreamError(DomainError):
    status: int = 502


def problem_detail(error: DomainError, instance: str | None = None) -> dict[str, Any]:
    """Body of an error response per RFC 9457.

    The code is a separate field: clients tell errors apart by code rather
    than by parsing text, and decide how to present them.
    """
    body: dict[str, Any] = {
        "type": f"{PROBLEM_TYPE_PREFIX}{error.code.lower()}",
        "title": error.detail or error.code,
        "status": error.status,
        "code": error.code,
    }
    if error.params:
        body["params"] = error.params
    if instance is not None:
        body["instance"] = instance
    return body
