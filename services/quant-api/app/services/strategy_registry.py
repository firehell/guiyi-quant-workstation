from __future__ import annotations

from typing import Any

from app.backtest.v1b_jm_tasks import (
    JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
    JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_VERSION,
    JM_V1B_STRATEGY_CODE,
    JM_V1B_STRATEGY_VERSION,
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
            "strategy_code": JM_V1B_STRATEGY_CODE,
            "name": "JM V1-B 日线定方向 + 快入短持",
            "description": "日线 EMA21 定方向，15m/5m 独立入场，短持有 5-8 根 K 线。",
            "symbol": JM_V1B_SYMBOL,
            "product": "jm",
            "periods": ["1d", "15m", "5m"],
            "is_v1b": True,
            "capability_classes": ["formal_historical_backtest"],
            "validation_outcome": None,
            "live_observation": False,
            "backtest_endpoints": [
                {"label": "15m 入场", "path": "/api/backtests/v1b/jm/15m/tasks", "method": "POST"},
                {"label": "5m 入场", "path": "/api/backtests/v1b/jm/5m/tasks", "method": "POST"},
            ],
            "scan_endpoint": None,
            "strategy_version": JM_V1B_STRATEGY_VERSION,
            "spec_doc_path": "docs/strategy_specs/su_bing_jm_v1b_short_hold/STRATEGY_SPEC.md",
        },
        {
            "strategy_code": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
            "name": "JM 日线 EMA21 + MACD + 成交量",
            "description": "苏冰 EMA21 趋势系统 JM 日线变体，含 MACD 与成交量过滤。",
            "symbol": JM_V1B_SYMBOL,
            "product": "jm",
            "periods": ["1d"],
            "is_v1b": True,
            "capability_classes": ["formal_historical_backtest"],
            "validation_outcome": None,
            "live_observation": False,
            "backtest_endpoints": [
                {
                    "label": "日线回测",
                    "path": "/api/backtests/v1b/jm/daily-ema21-macd-volume/tasks",
                    "method": "POST",
                },
            ],
            "scan_endpoint": None,
            "strategy_version": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_VERSION,
            "spec_doc_path": "docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_SPEC.md",
        },
        {
            "strategy_code": "su_bing_jm_daily_score2of4",
            "name": "JM 日线 Score 2/4",
            "description": "日线四因子评分系统，至少 2 项满足才入场。",
            "symbol": JM_V1B_SYMBOL,
            "product": "jm",
            "periods": ["1d"],
            "is_v1b": True,
            "capability_classes": ["formal_historical_backtest"],
            "validation_outcome": None,
            "live_observation": False,
            "backtest_endpoints": [
                {"label": "日线回测", "path": "/api/backtests/v1b/jm/daily-score2of4/tasks", "method": "POST"},
            ],
            "scan_endpoint": None,
            "strategy_version": "v0.3.0-daily-score2of4",
            "spec_doc_path": None,
        },
        {
            "strategy_code": "su_bing_jm_daily_trend_cross_score2",
            "name": "JM 日线趋势交叉 Score2",
            "description": "趋势交叉结合 Score2 过滤的 JM 日线策略变体。",
            "symbol": JM_V1B_SYMBOL,
            "product": "jm",
            "periods": ["1d"],
            "is_v1b": True,
            "capability_classes": ["formal_historical_backtest"],
            "validation_outcome": None,
            "live_observation": False,
            "backtest_endpoints": [
                {
                    "label": "日线回测",
                    "path": "/api/backtests/v1b/jm/daily-trend-cross-score2/tasks",
                    "method": "POST",
                },
            ],
            "scan_endpoint": None,
            "strategy_version": "v0.3.1-daily-trend-cross-score2",
            "spec_doc_path": None,
        },
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
            "backtest_endpoints": [],
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
            "backtest_endpoints": [],
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
