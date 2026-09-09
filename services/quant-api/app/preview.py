"""Explicit, local candidate reader. Never compose the normal application."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime
import os
import re
import subprocess
from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.db.readonly import readonly_transaction


PREVIEW_PATHS = frozenset(
    {
        "/api/preview/identity",
        "/api/v1/market/bars/page",
        "/api/v1/market/dominants",
        "/api/v1/market/research/home-overview",
        "/api/v1/market/newow/strategy-detail",
        "/api/v1/market/newow/historical-snapshot",
    }
)


def _instant(value: str | None) -> datetime:
    try:
        parsed = datetime.fromisoformat(value or "")
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, TypeError):
        raise ValueError("PREVIEW_CUTOFF_INVALID") from None


def _code_sha() -> str:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        raise ValueError("PREVIEW_CODE_IDENTITY_UNAVAILABLE") from None
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("PREVIEW_CODE_IDENTITY_UNAVAILABLE")
    return sha


def create_preview_app(
    *,
    enabled: bool | None = None,
    as_of: str | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> FastAPI:
    """Default off; explicit cutoff required before importing database composition."""
    if not (
        enabled if enabled is not None else os.getenv("GUIYI_CANDIDATE_PREVIEW") == "1"
    ):
        raise ValueError("PREVIEW_DISABLED")
    cutoff = _instant(as_of if as_of is not None else os.getenv("GUIYI_PREVIEW_AS_OF"))
    if cutoff > datetime.now(UTC):
        raise ValueError("PREVIEW_CUTOFF_INVALID")
    code_sha = _code_sha()

    from app.api import market, market_newow
    from app.db.session import SessionLocal, get_db

    factory = session_factory or SessionLocal
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def readonly_db() -> Generator[Session]:
        with factory() as session, readonly_transaction(session):
            yield session

    app.dependency_overrides[get_db] = readonly_db

    @app.middleware("http")
    async def enforce_preview(request: Request, call_next):
        raw_path = request.scope.get("raw_path", b"").decode("ascii", errors="replace")
        if request.method != "GET" or raw_path not in PREVIEW_PATHS:
            return JSONResponse(
                status_code=403, content={"detail": {"code": "PREVIEW_ROUTE_FORBIDDEN"}}
            )
        try:
            query = parse_qsl(
                request.scope["query_string"].decode("ascii"), keep_blank_values=True
            )
            if len({key for key, value in query}) != len(query):
                raise ValueError
            values = dict(query)
            field = {
                "/api/v1/market/bars/page": "before",
                "/api/v1/market/newow/strategy-detail": "as_of",
            }.get(raw_path)
            if field:
                requested = _instant(values[field]) if field in values else cutoff
                values[field] = min(requested, cutoff).isoformat()
                request.scope["query_string"] = urlencode(values).encode("ascii")
            request.state.candidate_preview_as_of = cutoff
        except (ValueError, UnicodeError):
            return JSONResponse(
                status_code=422, content={"detail": {"code": "PREVIEW_QUERY_INVALID"}}
            )
        try:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"detail": {"code": "PREVIEW_QUERY_UNAVAILABLE"}},
            )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _error):
        return JSONResponse(
            status_code=422, content={"detail": {"code": "PREVIEW_QUERY_INVALID"}}
        )

    @app.get("/api/preview/identity")
    def identity():
        return {
            "mode": "local_candidate_readonly",
            "code_sha": code_sha,
            "as_of": cutoff.isoformat(),
            "realtime": False,
            "candidate_origin": "http://127.0.0.1:8010",
            "status_origin": "http://127.0.0.1:8000",
            "cutoff_scope": "bars_and_newow; home_projection_and_dominants_have_own_timestamps",
        }

    app.include_router(market.router)
    app.include_router(market_newow.router)
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_preview_app(), host="127.0.0.1", port=8010, access_log=False)
