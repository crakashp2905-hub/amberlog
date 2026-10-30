"""Structured logs: one JSON object per line, ids and codes only.

    memory-fabric --log-format json serve ...      # or MEMORY_FABRIC_LOG_FORMAT=json

Every record has `ts`, `level`, `logger` and `msg`. Fields passed through
`extra={"fields": {...}}` are merged in, so a log pipeline can filter on
`event`, `task`, `reason_code` or `store_id` without parsing text.
Exceptions carry `error_type`, not a traceback, unless the level is DEBUG:
a traceback can quote memory content.
"""

from __future__ import annotations

__stability__ = "beta"

import json
import logging
import os
import sys
import time
from typing import Any

FORMATS = ("text", "json")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            out.update({k: v for k, v in fields.items() if k not in out})
        if record.exc_info and record.exc_info[0] is not None:
            out["error_type"] = record.exc_info[0].__name__
            if record.levelno <= logging.DEBUG:
                out["traceback"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure(fmt: str | None = None, level: str | None = None) -> None:
    """Configure the root logger once, from arguments or the environment."""
    fmt = (fmt or os.environ.get("MEMORY_FABRIC_LOG_FORMAT") or "text").lower()
    if fmt not in FORMATS:
        raise ValueError(f"log format must be one of {FORMATS}")
    level = (level or os.environ.get("MEMORY_FABRIC_LOG_LEVEL") or "WARNING").upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json"
                         else logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_memory_fabric", False):
            root.removeHandler(existing)
    handler._memory_fabric = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
