"""CLI JSON 输出与错误载荷脱敏。

``print_json`` 递归脱敏敏感子串与路径；异常载荷仅暴露公开错误码（大写下划线）
或回退 CLI_INTERNAL_ERROR，不输出 stack trace 或原始异常消息。
"""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, TextIO

# 字符串值中命中则替换为 [REDACTED]
_SENSITIVE = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|license|cookie)"
)
# 异常 code 须为大写下划线公开码才透出，否则 CLI_INTERNAL_ERROR
_PUBLIC_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]+")


def print_json(payload: Mapping[str, Any], stream: TextIO) -> None:
    """将 payload 经脱敏后格式化 JSON 打印到指定流。"""
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
    """参数/用法错误的固定 JSON 结构（readonly，无细节消息）。"""
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
    """执行期异常的 JSON 结构；code 脱敏，type 为异常类名。"""
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
    """递归脱敏：Mapping/序列/Path/含敏感子串的 str。"""
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
    """json.dumps default：日期 ISO 化，Path 脱敏，其余 str()。"""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return "[REDACTED_PATH]"
    return str(value)
