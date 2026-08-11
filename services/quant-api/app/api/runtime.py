"""Runtime 运维只读 API。

暴露分层健康检查端点，聚合 DB/Redis/RQ 真实探测与已退役组件的 stub 状态。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.runtime import RuntimeHealthOut
from app.services.runtime_health import build_runtime_health

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("/health", response_model=RuntimeHealthOut)
def runtime_health(session: Session = Depends(get_db)) -> dict:
    """返回 Runtime 分层健康快照（只读，不触发写操作或通知）。"""
    return build_runtime_health(session)
