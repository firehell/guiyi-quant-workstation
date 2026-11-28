"""Origin policy shared by local workstation writes."""

import os

from fastapi import HTTPException, Request

_DEVELOP_ORIGINS = frozenset(f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 5175))


def require_workstation_origin(request: Request, error_code: str):
    if origin := request.headers.get("origin"):
        allowed = set(_DEVELOP_ORIGINS)
        if request.base_url.hostname in {"localhost", "127.0.0.1", "::1"}:
            allowed.add(str(request.base_url).rstrip("/"))
        allowed.update(item.strip() for item in os.getenv("CORS_ORIGINS", "").split(",") if item.strip())
        if origin.rstrip("/") not in allowed:
            raise HTTPException(403, detail={"code": error_code})
