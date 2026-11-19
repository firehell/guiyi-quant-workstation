"""Retired standalone JM API. Historical ledger is retained without active reads."""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/subing-model", tags=["subing-model-retired"])

@router.get("")
@router.get("/{path:path}")
def retired(path: str = ""):
    raise HTTPException(410, detail={"code": "SUBING_INDEPENDENT_MODEL_RETIRED", "replacement": "/api/v1/subing-portfolio/status"})
