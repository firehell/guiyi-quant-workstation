from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dashboard import DashboardSummaryOut
from app.services.dashboard_summary import build_dashboard_summary

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard/summary", response_model=DashboardSummaryOut)
def dashboard_summary(session: Session = Depends(get_db)) -> dict:
    return build_dashboard_summary(session)
