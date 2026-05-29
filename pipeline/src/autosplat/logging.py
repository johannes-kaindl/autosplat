# SPDX-License-Identifier: AGPL-3.0-or-later

"""Structured logging — Rich for console, JSON for the per-capture pipeline.log.

Each capture run writes structured JSON events to `<capture>/pipeline.log`, and
mirrors them to the console via Rich for human-readable progress.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from datetime import UTC
from pathlib import Path
from typing import Any

import structlog
from rich.console import Console
from rich.logging import RichHandler

_console = Console(stderr=True)


def _add_iso_timestamp(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor adding ISO-8601 UTC timestamp under `ts`."""
    from datetime import datetime

    event_dict["ts"] = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return event_dict


def configure_logging(
    level: str = "INFO",
    console: str = "rich",
    log_file: Path | None = None,
) -> None:
    """Configure structlog + stdlib logging for the whole process.

    Console renders human-readable (Rich) output. If `log_file` is set, raw JSON
    events are also written to that file.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    handlers: list[logging.Handler] = []

    if console == "rich":
        handlers.append(
            RichHandler(
                console=_console,
                show_time=True,
                show_path=False,
                rich_tracebacks=True,
                markup=False,
            )
        )
    else:
        plain = logging.StreamHandler(stream=sys.stderr)
        plain.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        handlers.append(plain)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        handlers=handlers,
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _add_iso_timestamp,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name or __name__)
    return logger
