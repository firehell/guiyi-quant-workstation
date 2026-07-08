from __future__ import annotations

from fastapi import APIRouter

from app.core.env import PROJECT_ROOT
from app.schemas.dashboard import StrategyRegistryItemOut, StrategyRegistryOut
from app.services.strategy_registry import list_strategy_registry

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


@router.get("/registry", response_model=StrategyRegistryOut)
def get_strategy_registry() -> dict:
    items = []
    for entry in list_strategy_registry():
        spec_path = entry.get("spec_doc_path")
        spec_exists = False
        if spec_path:
            spec_exists = (PROJECT_ROOT / spec_path).is_file()
        items.append(
            StrategyRegistryItemOut(
                **entry,
                spec_doc_exists=spec_exists,
            ).model_dump()
        )
    v1b_count = sum(1 for item in items if item["is_v1b"])
    return {
        "items": items,
        "total": len(items),
        "v1b_count": v1b_count,
    }
