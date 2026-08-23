"""Independent loopback-only FastAPI application for research backtests."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.backtest.api import BacktestServiceLike, create_backtest_router
from app.backtest.artifact_store import ArtifactStore
from app.backtest.config import BacktestSettings
from app.backtest.errors import BacktestError, BacktestHttpErrorCode, RegistryError
from app.backtest.registry import StrategyRegistry
from app.backtest.runner import SubprocessRunner
from app.backtest.service import BacktestService


_PACKAGE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_STRATEGY_ROOT = _PACKAGE_ROOT / "strategies"
_REGISTRY_PATH = _STRATEGY_ROOT / "registry.json"
_LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "testserver"]


def _safe_json(status_code: int, code: BacktestHttpErrorCode) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": code.value}},
    )


class _OriginAllowlistMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *, allowed_origins: tuple[str, ...]) -> None:
        super().__init__(app)
        self.allowed_origins = frozenset(allowed_origins)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        origin = request.headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            return _safe_json(
                403,
                BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE,
            )
        return await call_next(request)


class _JsonMutationMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            media_type = request.headers.get("content-type", "").partition(";")[0]
            if media_type.strip().lower() != "application/json":
                return _safe_json(
                    415,
                    BacktestHttpErrorCode.INVALID_BACKTEST_REQUEST,
                )
        return await call_next(request)


class _UnavailableBacktestService:
    def __init__(self, code: BacktestHttpErrorCode) -> None:
        self.code = code

    def health(self) -> dict[str, Any]:
        raise BacktestError(self.code)

    def _unavailable(self) -> None:
        raise BacktestError(self.code)

    def list_strategies(self) -> list[dict[str, Any]]:
        self._unavailable()
        raise AssertionError("unreachable")

    def start_run(self, request: Any) -> dict[str, Any]:
        del request
        self._unavailable()
        raise AssertionError("unreachable")

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        del limit
        self._unavailable()
        raise AssertionError("unreachable")

    def get_run(self, run_id: str) -> dict[str, Any]:
        del run_id
        self._unavailable()
        raise AssertionError("unreachable")

    def open_artifact(self, run_id: str, kind: str) -> Any:
        del run_id, kind
        self._unavailable()
        raise AssertionError("unreachable")


def create_app(
    service: BacktestServiceLike,
    *,
    allowed_origins: tuple[str, ...],
) -> FastAPI:
    """Create a factory-testable app without importing the main API."""

    app = FastAPI(title="归一量化本机研究回测 API", version="1")
    app.include_router(create_backtest_router(service))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(_JsonMutationMiddleware)
    app.add_middleware(
        _OriginAllowlistMiddleware,
        allowed_origins=allowed_origins,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=_LOOPBACK_HOSTS,
        www_redirect=False,
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_backtest_request(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        del request, error
        return _safe_json(
            422,
            BacktestHttpErrorCode.INVALID_BACKTEST_REQUEST,
        )

    @app.exception_handler(Exception)
    async def safe_unexpected_error(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        del request, error
        return _safe_json(
            503,
            BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE,
        )

    return app


def _repository_commit() -> str:
    result = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=_PROJECT_ROOT,
        env={"LANG": "C"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    return result.stdout.strip()


def build_app() -> FastAPI:
    """Compose only filesystem/runner dependencies for the local sidecar."""

    try:
        settings = BacktestSettings.from_env()
    except BacktestError:
        return create_app(
            _UnavailableBacktestService(
                BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE
            ),
            allowed_origins=(),
        )
    try:
        registry = StrategyRegistry.load(_REGISTRY_PATH, _STRATEGY_ROOT)
        service: BacktestServiceLike = BacktestService(
            registry=registry,
            store=ArtifactStore(settings),
            runner=SubprocessRunner(settings),
            repository_commit=_repository_commit(),
        )
    except RegistryError:
        service = _UnavailableBacktestService(BacktestHttpErrorCode.REGISTRY_INVALID)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        service = _UnavailableBacktestService(
            BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE
        )
    return create_app(service, allowed_origins=settings.cors_origins)


def main() -> None:
    """Start only on the fixed loopback endpoint."""

    import uvicorn

    uvicorn.run(build_app(), host="127.0.0.1", port=8011)


if __name__ == "__main__":
    main()


__all__ = ["build_app", "create_app", "main"]
