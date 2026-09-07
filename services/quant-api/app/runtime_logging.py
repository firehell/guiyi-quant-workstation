"""Bounded Runtime diagnostics that survive removal/rotation of their log file."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from logging.handlers import WatchedFileHandler
import os
from pathlib import Path
import re
import stat
import sys


class _SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        code = record.msg if isinstance(record.msg, str) else ""
        if record.args or re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code) is None:
            code = "RUNTIME_DIAGNOSTIC_REDACTED"
        payload: dict[str, object] = {
            "at": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "code": code,
        }
        fields = getattr(record, "diagnostic_fields", {})
        if isinstance(fields, dict):
            for key in ("symbol", "contract", "bar_end", "trading_day", "missing_count", "attempt"):
                value = fields.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100000:
                    payload[key] = value
                elif isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9:+.\-]{1,40}", value):
                    # Fields have semantic grammars; arbitrary credential-shaped text is rejected.
                    pattern = {"symbol": r"[a-z]{1,2}", "contract": r"[A-Z]{1,2}[0-9]{3,4}",
                               "bar_end": r"[0-9T:+.Z\-]{10,40}", "trading_day": r"[0-9\-]{10}"}.get(key)
                    if pattern and re.fullmatch(pattern, value):
                        payload[key] = value
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)


class _SafeWatchedHandler(WatchedFileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except Exception:
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        # logging's default handler prints the original message/args and traceback.
        print("RUNTIME_LOG_UNAVAILABLE", file=sys.stderr)

    def _open(self):
        parent = Path(self.baseFilename).parent
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("RUNTIME_LOG_UNSAFE")
        try:
            fd = os.open(self.baseFilename, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError:
            raise ValueError("RUNTIME_LOG_UNSAFE") from None
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            os.close(fd)
            raise ValueError("RUNTIME_LOG_UNSAFE")
        return os.fdopen(fd, "a", encoding="utf-8")


def runtime_diagnostic_handler(path: Path) -> logging.Handler:
    handler = _SafeWatchedHandler(path, encoding="utf-8")
    handler.setFormatter(_SafeFormatter())
    return handler


def install_runtime_diagnostics(service: str) -> logging.Handler:
    filename = {"live": "live-market.log", "alert": "alert-runtime.log"}[service]
    root = Path(os.environ.get("GUIYI_LOG_DIR", str(Path.home() / "Library/Logs/GuiyiQuant")))
    handler = runtime_diagnostic_handler(root / filename)
    logger = logging.getLogger("app")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return handler
