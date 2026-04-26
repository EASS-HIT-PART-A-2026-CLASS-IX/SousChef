"""
Shared logging and tracing helpers for the backend.
"""
from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import os
import time
from typing import Any, Callable

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestContextFilter(logging.Filter):
    """Attach request-scoped metadata to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get("-")
        return True


def configure_logging() -> None:
    """Configure application logging once at startup."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] [request_id=%(request_id)s] %(message)s",
        force=True,
    )

    context_filter = RequestContextFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(context_filter)
    for handler in root_logger.handlers:
        handler.addFilter(context_filter)


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module or component."""
    return logging.getLogger(name)


def set_request_id(request_id: str) -> None:
    """Set the active request identifier for log correlation."""
    _request_id_var.set(request_id)


def clear_request_id() -> None:
    """Clear the active request identifier."""
    _request_id_var.set("-")


def _summarize_value(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, (int, float, bool)):
        return repr(value)
    if isinstance(value, str):
        compact = " ".join(value.split())
        if len(compact) > 80:
            return f"str(len={len(value)})"
        return repr(compact)
    if isinstance(value, bytes):
        return f"bytes(len={len(value)})"
    if isinstance(value, dict):
        keys = list(value.keys())[:6]
        suffix = "..." if len(value) > 6 else ""
        return f"dict(keys={keys}{suffix})"
    if isinstance(value, (list, tuple, set)):
        return f"{type(value).__name__}(len={len(value)})"
    if hasattr(value, "filename"):
        filename = getattr(value, "filename", None)
        return f"{type(value).__name__}(filename={filename!r})"
    if hasattr(value, "url") and hasattr(value, "path"):
        return f"{type(value).__name__}(path={getattr(value, 'path', '')!r})"
    return type(value).__name__


def _format_call(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
    except Exception:
        return "args=<unavailable>"

    items: list[str] = []
    for key, value in bound.arguments.items():
        if key in {"self", "cls", "session", "app"}:
            continue
        items.append(f"{key}={_summarize_value(value)}")
    return ", ".join(items) if items else "no-args"


def trace_call(func: Callable[..., Any]) -> Callable[..., Any]:
    """Log entry, exit, duration, and exceptions for a function."""
    logger = get_logger(func.__module__)
    qualified_name = f"{func.__module__}.{func.__name__}"

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            call_summary = _format_call(func, args, kwargs)
            start = time.perf_counter()
            logger.info("-> %s(%s)", qualified_name, call_summary)
            try:
                result = await func(*args, **kwargs)
            except Exception:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.exception("<! %s failed after %.1fms", qualified_name, duration_ms)
                raise
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info("<- %s completed in %.1fms result=%s", qualified_name, duration_ms, _summarize_value(result))
            return result

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        call_summary = _format_call(func, args, kwargs)
        start = time.perf_counter()
        logger.info("-> %s(%s)", qualified_name, call_summary)
        try:
            result = func(*args, **kwargs)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception("<! %s failed after %.1fms", qualified_name, duration_ms)
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info("<- %s completed in %.1fms result=%s", qualified_name, duration_ms, _summarize_value(result))
        return result

    return sync_wrapper
