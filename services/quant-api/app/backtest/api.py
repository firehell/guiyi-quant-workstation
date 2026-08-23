"""Stable HTTP boundary for the independent local backtest application."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Any, BinaryIO, Literal, Protocol, cast

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.backtest.contracts import BacktestRunRequest, RunStatus
from app.backtest.errors import BacktestError, BacktestHttpErrorCode


ArtifactKind = Literal[
    "report_zip",
    "result_pickle",
    "equity_png",
    "stdout_log",
    "stderr_log",
    "run_json",
]

_ERROR_STATUS = {
    BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE: 503,
    BacktestHttpErrorCode.RUNNER_UNAVAILABLE: 503,
    BacktestHttpErrorCode.BUNDLE_UNAVAILABLE: 503,
    BacktestHttpErrorCode.REGISTRY_INVALID: 503,
    BacktestHttpErrorCode.STRATEGY_NOT_FOUND: 404,
    BacktestHttpErrorCode.INVALID_BACKTEST_REQUEST: 422,
    BacktestHttpErrorCode.BACKTEST_ALREADY_RUNNING: 409,
    BacktestHttpErrorCode.BACKTEST_RUN_NOT_FOUND: 404,
    BacktestHttpErrorCode.BACKTEST_ARTIFACT_NOT_FOUND: 404,
}
_ARTIFACT_RESPONSE = {
    "report_zip": ("application/zip", "report.zip", True),
    "result_pickle": ("application/octet-stream", "result.pkl", True),
    "equity_png": ("image/png", "equity.png", False),
    "stdout_log": ("text/plain; charset=utf-8", "stdout.log", True),
    "stderr_log": ("text/plain; charset=utf-8", "stderr.log", True),
    "run_json": ("application/json", "run.json", True),
}


class BacktestServiceLike(Protocol):
    def health(self) -> dict[str, Any]: ...

    def list_strategies(self) -> list[dict[str, Any]]: ...

    def start_run(self, request: BacktestRunRequest) -> dict[str, Any]: ...

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]: ...

    def get_run(self, run_id: str) -> dict[str, Any]: ...

    def open_artifact(
        self, run_id: str, kind: str
    ) -> AbstractContextManager[BinaryIO]: ...


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(_StrictModel):
    code: BacktestHttpErrorCode


class RunnerHealth(_StrictModel):
    available: bool
    rqalpha_version: str | None
    rqsdk_version: str | None
    python_version: str | None


class BacktestHealth(_StrictModel):
    status: Literal["ready", "degraded"]
    research_only: Literal[True]
    formal_evidence: Literal[False]
    promotion_eligible: Literal[False]
    busy: bool
    runner: RunnerHealth
    bundle_available: bool
    runs_root_available: bool
    registry_available: bool
    error: ErrorDetail | None


class ParameterDto(_StrictModel):
    name: str
    type: Literal["integer", "decimal", "boolean", "enum"]
    default: int | str | bool
    minimum: int | str | None
    maximum: int | str | None
    options: list[str]


class StrategyDto(_StrictModel):
    id: str
    name: str
    description: str
    supported_frequencies: list[Literal["1d", "1m"]]
    defaults: dict[str, str]
    parameters: list[ParameterDto]
    research_only: Literal[True]
    formal_evidence: Literal[False]
    promotion_eligible: Literal[False]


class VersionDto(_StrictModel):
    rqalpha: str | None
    rqsdk: str | None
    python: str | None


class RunDto(_StrictModel):
    run_id: str
    research_only: Literal[True]
    formal_evidence: Literal[False]
    promotion_eligible: Literal[False]
    strategy_id: str
    strategy_name: str
    strategy_entry_file: str
    strategy_sha256: str
    repository_commit: str
    bundle_path: str
    versions: VersionDto
    requested_config: BacktestRunRequest
    effective_config: dict[str, Any]
    effective_parameters: dict[str, int | str | bool]
    status: RunStatus
    started_at: str
    finished_at: str | None
    exit_code: int | None
    failure_code: str | None


class SummaryDto(_StrictModel):
    total_returns: str
    annualized_returns: str
    max_drawdown: str
    sharpe: str
    sortino: str
    volatility: str
    total_value: str
    cash: str


class EquityPointDto(_StrictModel):
    date: str
    unit_net_value: str


class ArtifactAvailabilityDto(_StrictModel):
    report_zip: bool
    result_pickle: bool
    equity_png: bool
    stdout_log: bool
    stderr_log: bool
    run_json: bool


class ResultDto(_StrictModel):
    summary: SummaryDto
    equity: list[EquityPointDto]
    trade_count: str
    artifacts: ArtifactAvailabilityDto


class RunDetailDto(RunDto):
    result: ResultDto | None
    stdout_tail: str
    stderr_tail: str


def _known_code(error: BacktestError) -> BacktestHttpErrorCode | None:
    try:
        return BacktestHttpErrorCode(str(error))
    except ValueError:
        return None


def _http_error(code: BacktestHttpErrorCode) -> HTTPException:
    return HTTPException(
        status_code=_ERROR_STATUS[code],
        detail={"code": code.value},
    )


def _safe_call(function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except BacktestError as error:
        code = _known_code(error)
        if code is not None:
            raise _http_error(code) from None
    except Exception:
        pass
    raise _http_error(BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE) from None


def _degraded_health(error: Exception) -> dict[str, Any]:
    code = (
        _known_code(error)
        if isinstance(error, BacktestError)
        else BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE
    )
    if code is None:
        code = BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE
    return {
        "status": "degraded",
        "research_only": True,
        "formal_evidence": False,
        "promotion_eligible": False,
        "busy": False,
        "runner": {
            "available": False,
            "rqalpha_version": None,
            "rqsdk_version": None,
            "python_version": None,
        },
        "bundle_available": False,
        "runs_root_available": False,
        "registry_available": code is not BacktestHttpErrorCode.REGISTRY_INVALID,
        "error": {"code": code.value},
    }


def _stream_artifact(
    manager: AbstractContextManager[BinaryIO],
) -> tuple[BinaryIO, Iterator[bytes]]:
    try:
        stream = manager.__enter__()
    except BacktestError as error:
        code = _known_code(error)
        if code is not None:
            raise _http_error(code) from None
        raise _http_error(BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE) from None
    except Exception:
        raise _http_error(BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE) from None

    def iterator() -> Iterator[bytes]:
        try:
            while chunk := stream.read(64 * 1024):
                yield chunk
        finally:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                pass

    return stream, iterator()


def create_backtest_router(service: BacktestServiceLike) -> APIRouter:
    """Bind the six fixed routes to one injected service."""

    router = APIRouter(prefix="/api/v1/backtests", tags=["local-backtests"])

    @router.get("/health", response_model=BacktestHealth)
    def health() -> dict[str, Any]:
        try:
            payload = service.health()
        except Exception as error:
            return _degraded_health(error)
        return {
            **payload,
            "registry_available": True,
            "error": None,
        }

    @router.get("/strategies", response_model=list[StrategyDto])
    def strategies() -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], _safe_call(service.list_strategies))

    @router.post("/runs", response_model=RunDto, status_code=202)
    def start_run(request: BacktestRunRequest) -> dict[str, Any]:
        return cast(dict[str, Any], _safe_call(service.start_run, request))

    @router.get("/runs", response_model=list[RunDto])
    def runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], _safe_call(service.list_runs, limit))

    @router.get("/runs/{run_id}", response_model=RunDetailDto)
    def run_detail(run_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], _safe_call(service.get_run, run_id))

    @router.get("/runs/{run_id}/artifacts/{kind}")
    def artifact(run_id: str, kind: ArtifactKind) -> StreamingResponse:
        manager = cast(
            AbstractContextManager[BinaryIO],
            _safe_call(service.open_artifact, run_id, kind),
        )
        _stream, iterator = _stream_artifact(manager)
        media_type, filename, attachment = _ARTIFACT_RESPONSE[kind]
        disposition = "attachment" if attachment else "inline"
        return StreamingResponse(
            iterator,
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    f'{disposition}; filename="{run_id}-{filename}"'
                )
            },
        )

    return router


__all__ = [
    "ArtifactKind",
    "BacktestHealth",
    "BacktestServiceLike",
    "RunDetailDto",
    "RunDto",
    "StrategyDto",
    "create_backtest_router",
]
