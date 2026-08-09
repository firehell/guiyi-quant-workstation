from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, TextIO


_SENSITIVE = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|license|cookie)"
)
_PUBLIC_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]+")

def print_json(payload: Mapping[str, Any], stream: TextIO) -> None:
    print(
        json.dumps(
            _redact(dict(payload)),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_default,
        ),
        file=stream,
    )


def argument_error_payload(command: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command": command,
        "status": "error",
        "readonly": True,
        "error": {"code": "CLI_ARGUMENT_INVALID", "type": "CliUsageError"},
    }


def exception_error_payload(
    *, command: str, exc: BaseException, readonly: bool = True
) -> dict[str, object]:
    code = getattr(exc, "code", None)
    if not isinstance(code, str) or _PUBLIC_ERROR_CODE.fullmatch(code) is None:
        code = "CLI_INTERNAL_ERROR"
    return {
        "schema_version": 1,
        "command": command,
        "status": "error",
        "readonly": readonly,
        "error": {"code": code, "type": type(exc).__name__},
    }


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, Path):
        return "[REDACTED_PATH]"
    if isinstance(value, str):
        return _SENSITIVE.sub("[REDACTED]", value)
    return value


def _default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return "[REDACTED_PATH]"
    return str(value)
