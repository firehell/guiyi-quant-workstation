from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.runtime import RuntimeHealthOut
from app.services.runtime_health import build_runtime_health

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("/health", response_model=RuntimeHealthOut)
def runtime_health(session: Session = Depends(get_db)) -> dict:
    return build_runtime_health(session)
