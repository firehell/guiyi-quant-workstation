"""Runtime 运维只读 API。

暴露分层健康检查端点，聚合 DB/Redis 真实探测与 Market Runtime 公开状态。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.strategy_center import router as strategy_center_router
from app.db.session import get_db
from app.schemas.runtime import RuntimeHealthOut
from app.services.runtime_health import build_runtime_health

router = APIRouter()


@router.get("/api/runtime/health", response_model=RuntimeHealthOut, tags=["runtime"])
def runtime_health(session: Session = Depends(get_db)) -> dict:
    """返回 Runtime 分层健康快照（只读，不触发写操作或通知）。"""
    return build_runtime_health(session)


router.include_router(strategy_center_router)
