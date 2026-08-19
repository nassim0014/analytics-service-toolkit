"""Structured logging setup shared across services: one call configures the
root logger to emit JSON lines tagged with the service name and a per-run id,
so logs from different services can be aggregated and correlated later.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from typing import Any


class _JsonFormatter(logging.Formatter):
    def __init__(self, app_name: str, run_id: str) -> None:
        super().__init__()
        self.app_name = app_name
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "app": self.app_name,
            "run_id": self.run_id,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(app_name: str, level: str = "INFO", json_output: bool = True) -> str:
    """Configure the root logger. Returns the generated run id (also embedded
    in every log line) so callers can include it in alerts for correlation.
    """
    run_id = uuid.uuid4().hex[:12]
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(_JsonFormatter(app_name, run_id))
    else:
        fmt = f"%(asctime)s [{app_name}:{run_id}] %(levelname)s %(name)s: %(message)s"
        handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)
    return run_id
