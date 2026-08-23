"""Git-out configuration for the independent loopback backtest app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.backtest.errors import BacktestConfigError


_PYTHON_EXECUTABLE_ENV = "GUIYI_BACKTEST_PYTHON_EXECUTABLE"
_BUNDLE_PATH_ENV = "GUIYI_BACKTEST_BUNDLE_PATH"
_RUNS_ROOT_ENV = "GUIYI_BACKTEST_RUNS_ROOT"
_TIMEOUT_SECONDS_ENV = "GUIYI_BACKTEST_TIMEOUT_SECONDS"
_CORS_ORIGINS_ENV = "GUIYI_BACKTEST_CORS_ORIGINS"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


def _absolute_path(name: str) -> Path:
    value = os.environ.get(name, "")
    path = Path(value) if value else Path()
    if not value or not path.is_absolute():
        raise BacktestConfigError
    return path.resolve(strict=False)


def _is_same_or_parent(parent: Path, child: Path) -> bool:
    return child == parent or child.is_relative_to(parent)


def _cors_origins() -> tuple[str, ...]:
    raw = os.environ.get(_CORS_ORIGINS_ENV, "")
    origins = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not origins or len(set(origins)) != len(origins):
        raise BacktestConfigError
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in _LOOPBACK_HOSTS
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise BacktestConfigError
        try:
            if parsed.port is None:
                raise BacktestConfigError
        except ValueError as exc:
            raise BacktestConfigError from exc
    return origins


@dataclass(frozen=True, slots=True)
class BacktestSettings:
    """Validated local paths and process limits for the backtest sidecar."""

    python_executable: Path
    bundle_path: Path
    runs_root: Path
    timeout_seconds: int
    cors_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> BacktestSettings:
        """Load only the documented Git-out environment variables."""

        python_executable = _absolute_path(_PYTHON_EXECUTABLE_ENV)
        bundle_path = _absolute_path(_BUNDLE_PATH_ENV)
        runs_root = _absolute_path(_RUNS_ROOT_ENV)
        try:
            timeout_seconds = int(os.environ.get(_TIMEOUT_SECONDS_ENV, "3600"))
        except ValueError as exc:
            raise BacktestConfigError from exc
        if timeout_seconds <= 0:
            raise BacktestConfigError
        if _is_same_or_parent(bundle_path, runs_root) or _is_same_or_parent(
            runs_root, bundle_path
        ):
            raise BacktestConfigError
        return cls(
            python_executable=python_executable,
            bundle_path=bundle_path,
            runs_root=runs_root,
            timeout_seconds=timeout_seconds,
            cors_origins=_cors_origins(),
        )


__all__ = ["BacktestConfigError", "BacktestSettings"]
