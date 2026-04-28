"""Structlog configuration with OpenTelemetry trace correlation.

The processor chain produces JSON lines with these fields:
    timestamp, level, logger, event, plus any kwargs passed to the call,
    plus trace_id / span_id when a span is active.

Importing this module has no side effects — call ``configure_logging`` explicitly
in each service's startup path so test harnesses can decline JSON output.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from opentelemetry import trace
from structlog.types import EventDict, WrappedLogger

_LEVELS: dict[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def _add_otel_context(
    _logger: WrappedLogger,
    _name: str,
    event_dict: EventDict,
) -> EventDict:
    """Add OTel ``trace_id``/``span_id`` to log records when a span is active."""
    span = trace.get_current_span()
    ctx = span.get_span_context() if span else None
    if ctx and ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = True,
    service_name: str | None = None,
) -> None:
    """Configure structlog + stdlib logging.

    Args:
        level: One of CRITICAL, ERROR, WARNING, INFO, DEBUG.
        json_output: True → JSON lines (production). False → console renderer (dev).
        service_name: Bound to every record as ``service``.
    """
    log_level = _LEVELS.get(level.upper(), logging.INFO)

    # Stdlib root logger — captures third-party libraries that use logging.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )

    # Silence chatty libraries.
    for chatty in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(chatty).setLevel(logging.WARNING)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.add_logger_name,
        _add_otel_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if service_name:
        structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to ``name`` (defaults to caller module)."""
    return structlog.get_logger(name)
