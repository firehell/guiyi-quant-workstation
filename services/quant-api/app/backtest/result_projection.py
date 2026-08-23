"""Safe, JSON-only projection of the RQAlpha analyser result."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import stat
from typing import Any, NoReturn


SUMMARY_KEYS = (
    "total_returns",
    "annualized_returns",
    "max_drawdown",
    "sharpe",
    "sortino",
    "volatility",
    "total_value",
    "cash",
)


class ResultProjectionError(ValueError):
    """The RQAlpha result does not satisfy the fixed Web projection."""


def _invalid() -> NoReturn:
    raise ResultProjectionError("RUNNER_RESULT_INVALID")


def _decimal_string(value: object) -> str:
    if isinstance(value, bool) or value is None:
        _invalid()
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        _invalid()
    if not parsed.is_finite():
        _invalid()
    rendered = format(parsed, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _date_string(value: object) -> str:
    if isinstance(value, datetime):
        rendered = value.date().isoformat()
    elif isinstance(value, date):
        rendered = value.isoformat()
    else:
        date_method = getattr(value, "date", None)
        if callable(date_method):
            return _date_string(date_method())
        rendered = str(value)[:10]
    try:
        parsed = date.fromisoformat(rendered)
    except ValueError:
        _invalid()
    if parsed.isoformat() != rendered:
        _invalid()
    return rendered


def _row_value(row: object, name: str) -> object:
    if isinstance(row, Mapping):
        if name not in row:
            _invalid()
        return row[name]
    try:
        return row[name]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        _invalid()


def _project_equity(portfolio: object) -> list[dict[str, str]]:
    iterrows = getattr(portfolio, "iterrows", None)
    columns = getattr(portfolio, "columns", ())
    if callable(iterrows):
        if "unit_net_value" not in columns:
            _invalid()
        rows: Iterable[tuple[object, object]] = iterrows()
    elif isinstance(portfolio, Sequence) and not isinstance(
        portfolio, (str, bytes, bytearray)
    ):
        rows = ((_row_value(row, "date"), row) for row in portfolio)
    else:
        _invalid()
    projected: list[dict[str, str]] = []
    try:
        for index, row in rows:
            projected.append(
                {
                    "date": _date_string(index),
                    "unit_net_value": _decimal_string(
                        _row_value(row, "unit_net_value")
                    ),
                }
            )
    except ResultProjectionError:
        raise
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _invalid()
    return projected


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _report_available(report_dir: Path) -> bool:
    try:
        if not stat.S_ISDIR(report_dir.lstat().st_mode):
            return False
        for root, directories, files in os.walk(report_dir, followlinks=False):
            root_path = Path(root)
            for name in directories:
                candidate = root_path / name
                if candidate.is_symlink():
                    return False
            for name in files:
                if _regular_file(root_path / name):
                    return True
        return False
    except OSError:
        return False


def project_result(result: object, run_root: Path) -> dict[str, Any]:
    """Project only the fixed summary, equity, count, and artifact allowlist."""

    if not isinstance(result, Mapping):
        _invalid()
    analyser = result.get("sys_analyser")
    if not isinstance(analyser, Mapping):
        _invalid()
    summary = analyser.get("summary")
    if not isinstance(summary, Mapping) or any(
        key not in summary for key in SUMMARY_KEYS
    ):
        _invalid()
    portfolio = analyser.get("portfolio")
    trades = analyser.get("trades")
    if trades is None or isinstance(trades, (str, bytes, bytearray)):
        _invalid()
    try:
        trade_count = len(trades)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        _invalid()
    if isinstance(trade_count, bool) or trade_count < 0:
        _invalid()

    root = Path(run_root)
    return {
        "summary": {key: _decimal_string(summary[key]) for key in SUMMARY_KEYS},
        "equity": _project_equity(portfolio),
        "trade_count": str(trade_count),
        "artifacts": {
            "report_zip": _report_available(root / "report"),
            "result_pickle": _regular_file(root / "result.pkl"),
            "equity_png": _regular_file(root / "equity.png"),
            "stdout_log": _regular_file(root / "stdout.log"),
            "stderr_log": _regular_file(root / "stderr.log"),
            "run_json": _regular_file(root / "run.json"),
        },
    }


__all__ = ["ResultProjectionError", "SUMMARY_KEYS", "project_result"]
