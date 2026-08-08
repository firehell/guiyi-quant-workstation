from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence, TextIO, cast


_SENSITIVE = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|license|cookie)"
)
_CANDIDATE_SAMPLE_SYMBOL = re.compile(r"[A-Z0-9_]{1,16}\Z")
_CANDIDATE_SAMPLE_SERIES = re.compile(r"[A-Z0-9_]{1,32}\Z")
_CANDIDATE_SAMPLE_INSTANT = re.compile(r".{1,26}Z\Z")
_CANDIDATE_REASON_CODES = frozenset(
    {
        "CANDIDATE_TARGET_NOT_EMPTY",
        "CANDIDATE_METADATA_MISSING",
        "CANDIDATE_IDENTITY_MISMATCH",
        "CANDIDATE_THROUGH_REGRESSION",
        "CANDIDATE_SESSION_FACT_MISSING",
        "CANDIDATE_UNSUPPORTED_OPERATION",
        "CANDIDATE_PRECONDITION_FAILED",
    }
)


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
    if not isinstance(code, str) or not code:
        code = "CLI_INTERNAL_ERROR"
    return {
        "schema_version": 1,
        "command": command,
        "status": "error",
        "readonly": readonly,
        "error": {"code": code, "type": type(exc).__name__},
    }


def candidate_error_payload(
    *,
    reason_code: str,
    mode: str | None,
    requested_through: str | None,
    samples: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Return the bounded Candidate precondition diagnostic contract."""
    payload: dict[str, object] = {
        "reason_code": reason_code,
        "mode": mode,
        "planned_count": 0,
        "applied_count": 0,
        "noop_count": 0,
        "blocked_count": 0,
        "failed_count": 1,
        "samples": _bounded_candidate_samples(reason_code, samples),
    }
    if requested_through is not None:
        payload["requested_through"] = requested_through
    return payload


def _bounded_candidate_samples(
    reason_code: str, samples: Sequence[Mapping[str, object]]
) -> list[dict[str, str]]:
    if reason_code not in _CANDIDATE_REASON_CODES:
        return []
    result: list[dict[str, str]] = []
    required = {
        "kind", "symbol", "series_or_contract", "frequency", "start", "end", "reason_code"
    }
    for sample in samples:
        if len(result) == 20 or set(sample) != required:
            continue
        raw_values = {field: sample[field] for field in required}
        if not all(isinstance(value, str) for value in raw_values.values()):
            continue
        values = cast(dict[str, str], raw_values)
        if (
            values["kind"] not in {"continuous", "contract"}
            or _CANDIDATE_SAMPLE_SYMBOL.fullmatch(values["symbol"]) is None
            or _CANDIDATE_SAMPLE_SERIES.fullmatch(values["series_or_contract"]) is None
            or values["frequency"] not in {"1m", "5m", "15m", "30m", "60m", "1d", "1w"}
            or _CANDIDATE_SAMPLE_INSTANT.fullmatch(values["start"]) is None
            or _CANDIDATE_SAMPLE_INSTANT.fullmatch(values["end"]) is None
            or values["reason_code"] != reason_code
        ):
            continue
        try:
            if datetime.fromisoformat(values["start"].replace("Z", "+00:00")) > datetime.fromisoformat(
                values["end"].replace("Z", "+00:00")
            ):
                continue
        except ValueError:
            continue
        result.append(values)
    return result


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
