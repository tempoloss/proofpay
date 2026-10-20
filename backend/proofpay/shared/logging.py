"""structlog setup and a request-scoped identifier."""

import uuid

import structlog


def setup_logging(*, json: bool = True) -> None:
    # Processors that do not depend on the standard logging module: output
    # goes through PrintLogger, which has neither levels nor a name, and the
    # structlog.stdlib.* processors fail on it.
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    if json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]
