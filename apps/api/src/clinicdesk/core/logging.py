"""Structured JSON logging with phone masking."""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

_PHONE = re.compile(r"\+?\d[\d\s-]{8,}\d")


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 6:
        return "***"
    return f"+{digits[:2]}******{digits[-4:]}"


def _mask_processor(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for k, v in list(event.items()):
        if isinstance(v, str) and (k in {"phone", "to", "from_phone", "caller"} or _PHONE.fullmatch(v)):
            event[k] = mask_phone(v)
    return event


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _mask_processor,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
    )


log = structlog.get_logger()
