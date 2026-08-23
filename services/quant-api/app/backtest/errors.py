"""Stable safe error contracts for the local backtest application."""

from __future__ import annotations

from enum import StrEnum


class BacktestHttpErrorCode(StrEnum):
    """Public error codes exposed by the future loopback HTTP API."""

    BACKTEST_LOCAL_UNAVAILABLE = "BACKTEST_LOCAL_UNAVAILABLE"
    RUNNER_UNAVAILABLE = "RUNNER_UNAVAILABLE"
    BUNDLE_UNAVAILABLE = "BUNDLE_UNAVAILABLE"
    REGISTRY_INVALID = "REGISTRY_INVALID"
    STRATEGY_NOT_FOUND = "STRATEGY_NOT_FOUND"
    INVALID_BACKTEST_REQUEST = "INVALID_BACKTEST_REQUEST"
    BACKTEST_ALREADY_RUNNING = "BACKTEST_ALREADY_RUNNING"
    BACKTEST_RUN_NOT_FOUND = "BACKTEST_RUN_NOT_FOUND"
    BACKTEST_ARTIFACT_NOT_FOUND = "BACKTEST_ARTIFACT_NOT_FOUND"


class RunFailureCode(StrEnum):
    """Filesystem-safe terminal failure classifications for one run."""

    RUNNER_UNAVAILABLE = "RUNNER_UNAVAILABLE"
    STRATEGY_EXECUTION_FAILED = "STRATEGY_EXECUTION_FAILED"
    RUN_TIMED_OUT = "RUN_TIMED_OUT"
    RUN_INTERRUPTED = "RUN_INTERRUPTED"
    RESULT_INCOMPLETE = "RESULT_INCOMPLETE"


class BacktestError(ValueError):
    """Base class whose message is a stable non-sensitive code."""


class BacktestConfigError(BacktestError):
    def __init__(self) -> None:
        super().__init__("BACKTEST_CONFIG_INVALID")


class RegistryError(BacktestError):
    def __init__(self) -> None:
        super().__init__(BacktestHttpErrorCode.REGISTRY_INVALID)


class StrategyNotFoundError(BacktestError):
    def __init__(self) -> None:
        super().__init__(BacktestHttpErrorCode.STRATEGY_NOT_FOUND)


class InvalidBacktestRequestError(BacktestError):
    def __init__(self) -> None:
        super().__init__(BacktestHttpErrorCode.INVALID_BACKTEST_REQUEST)
