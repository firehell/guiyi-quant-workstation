"""Versioned safe JSON envelope for guiyi CLI results."""

from __future__ import annotations

from datetime import date, datetime
import json
import re
from pathlib import Path
from typing import Any, Mapping, TextIO

from app.services.data_operations.contracts import (
    CommandResult,
    CommandStatus,
    EffectSummary,
    PublicError,
    empty_effects,
)


_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|bearer\s+\S+|"
    r"webhook|cookie|license|private[_-]?key)"
)
_SQL_PATTERN = re.compile(r"(?i)\b(select|insert|update|delete|drop|alter)\b.+\bfrom\b")
_URL_PATTERN = re.compile(r"(?i)\bhttps?://[^\s\"']+")
_PATH_PATTERN = re.compile(r"(?i)([a-z]:\\|/)(?:[^\s\"']+){8,}")
_STACK_PATTERN = re.compile(r"(?i)traceback \(most recent call last\)|file \".+\", line \d+")


def print_json(payload: Mapping[str, Any], stream: TextIO) -> None:
    print(
        json.dumps(
            redact_payload(dict(payload)),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        ),
        file=stream,
    )


def command_result_payload(result: CommandResult) -> dict[str, Any]:
    return redact_payload(result.as_payload())


def argument_error_payload(command: str) -> dict[str, Any]:
    return CommandResult(
        command=command,
        status=CommandStatus.ERROR,
        readonly=True,
        effects=empty_effects(),
        error=PublicError(code="CLI_ARGUMENT_INVALID", type="CliUsageError"),
    ).as_payload()


def exception_error_payload(
    *,
    command: str,
    exc: BaseException,
    readonly: bool = True,
    effects: EffectSummary | None = None,
    status: CommandStatus = CommandStatus.ERROR,
) -> dict[str, Any]:
    code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    if not isinstance(code, str) or not code:
        code = "CLI_INTERNAL_ERROR"
    return redact_payload(
        CommandResult(
            command=command,
            status=status,
            readonly=readonly,
            effects=effects or empty_effects(),
            error=PublicError(code=code, type=type(exc).__name__),
        ).as_payload()
    )


def redact_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(value) for key, value in payload.items()}


def redact_text(value: str) -> str:
    text = value
    text = _SECRET_PATTERN.sub("[REDACTED]", text)
    text = _SQL_PATTERN.sub("[REDACTED_SQL]", text)
    text = _URL_PATTERN.sub("[REDACTED_URL]", text)
    text = _PATH_PATTERN.sub("[REDACTED_PATH]", text)
    text = _STACK_PATTERN.sub("[REDACTED_STACK]", text)
    return text


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, Path):
        return "[REDACTED_PATH]"
    if isinstance(value, str):
        return redact_text(value)
    return value


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return "[REDACTED_PATH]"
    return str(value)
