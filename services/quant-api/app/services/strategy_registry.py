from __future__ import annotations

from typing import Any

from app.strategy.jm_v1b_identity import (
    JM_V1B_SYMBOL,
    SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_CODE,
    SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_VERSION,
)
from app.core.env import PROJECT_ROOT
from app.schemas.signal import (
    FORMAL_SIGNAL_STRATEGY_CODE,
    FORMAL_SIGNAL_STRATEGY_VERSION,
)


def list_strategy_registry() -> list[dict[str, Any]]:
    """Return readonly strategy registry entries for Web display."""
    return [
        {
            "strategy_code": SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_CODE,
            "name": "苏冰 JM V1-B 短持有规格",
            "description": "V1-B 短持有策略规格文档对应实现。",
            "symbol": JM_V1B_SYMBOL,
            "product": "jm",
            "periods": ["1d", "15m", "5m"],
            "is_v1b": True,
            "capability_classes": ["research_only"],
            "validation_outcome": None,
            "live_observation": False,
            "scan_endpoint": None,
            "strategy_version": SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_VERSION,
            "spec_doc_path": "docs/strategy_specs/su_bing_jm_v1b_short_hold/STRATEGY_SPEC.md",
        },
        {
            "strategy_code": FORMAL_SIGNAL_STRATEGY_CODE,
            "name": "苏冰 EMA21 趋势系统",
            "description": "通用 EMA21 趋势策略模板，可用于多品种回测。",
            "symbol": None,
            "product": None,
            "periods": ["15m", "60m", "1d"],
            "is_v1b": False,
            "capability_classes": ["research_only", "historical_scan"],
            "validation_outcome": None,
            "live_observation": False,
            "scan_endpoint": "/api/signals/scan",
            "strategy_version": FORMAL_SIGNAL_STRATEGY_VERSION,
            "spec_doc_path": None,
        },
    ]


def strategy_registry_summary() -> dict[str, Any]:
    entries = list_strategy_registry()
    v1b_count = sum(1 for item in entries if item["is_v1b"])
    return {
        "total": len(entries),
        "v1b_count": v1b_count,
        "project_root": str(PROJECT_ROOT),
    }
