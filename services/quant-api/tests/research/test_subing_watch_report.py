from __future__ import annotations

from datetime import date
from decimal import Decimal
import importlib

import pytest


def _modules():
    try:
        service = importlib.import_module(
            "app.research.subing.subing_watch_research_service"
        )
    except ModuleNotFoundError:
        pytest.fail("SuBing Watch research service is not implemented")
    payloads = importlib.import_module("app.guiyi_cli.research_payloads")
    return service, payloads


def _rate(module, numerator: int, denominator: int, value: str | None):
    return module.SubingWatchRate(
        numerator=numerator,
        denominator=denominator,
        value=None if value is None else Decimal(value),
    )


def test_report_has_exact_deterministic_readonly_shape() -> None:
    module, payloads = _modules()
    request = module.SubingWatchResearchRequest(
        since=date(2026, 8, 1),
        through=date(2026, 8, 31),
        symbols=("jm", "ag"),
        forward_bars=(1, 4),
    )
    products = (
        module.SubingWatchProductDiagnostics(
            symbol="jm",
            candidate_count=2,
            direction_counts={"sell": 1, "buy": 1},
            candidates_per_trading_day={"2026-08-31": 1, "2026-08-30": 1},
            same_direction_clustering=module.SubingWatchClustering(
                adjacent_pair_count=1,
                same_direction_pair_count=0,
                rate=_rate(module, 0, 1, "0"),
            ),
            session_distribution={"session_2": 1, "session_1": 1},
            context_availability=module.SubingWatchContextAvailability(
                available_count=1,
                candidate_count=2,
                rate=_rate(module, 1, 2, "0.5"),
            ),
            range_state_distribution={
                "range_unavailable": 1,
                "no_active_range": 0,
                "intact": 1,
                "broken_up": 0,
                "broken_down": 0,
            },
            higher_timeframe_alignment_distribution={
                "aligned": 1,
                "opposed": 0,
                "neutral": 0,
                "unavailable": 1,
            },
            forward_diagnostics={
                4: module.SubingWatchForwardDiagnostics(
                    horizon=4,
                    sample_count=1,
                    truncated_count=1,
                    median_directional_close_change_bps=Decimal("12.340000"),
                    median_mfe_bps=Decimal("18.500000"),
                    median_mae_bps=Decimal("-3.250000"),
                ),
                1: module.SubingWatchForwardDiagnostics(
                    horizon=1,
                    sample_count=2,
                    truncated_count=0,
                    median_directional_close_change_bps=Decimal("0.000000"),
                    median_mfe_bps=Decimal("4.000000"),
                    median_mae_bps=Decimal("-2.000000"),
                ),
            },
        ),
        module.SubingWatchProductDiagnostics(
            symbol="ag",
            candidate_count=0,
            direction_counts={"buy": 0, "sell": 0},
            candidates_per_trading_day={},
            same_direction_clustering=module.SubingWatchClustering(
                adjacent_pair_count=0,
                same_direction_pair_count=0,
                rate=_rate(module, 0, 0, None),
            ),
            session_distribution={},
            context_availability=module.SubingWatchContextAvailability(
                available_count=0,
                candidate_count=0,
                rate=_rate(module, 0, 0, None),
            ),
            range_state_distribution={
                "range_unavailable": 0,
                "no_active_range": 0,
                "intact": 0,
                "broken_up": 0,
                "broken_down": 0,
            },
            higher_timeframe_alignment_distribution={
                "aligned": 0,
                "opposed": 0,
                "neutral": 0,
                "unavailable": 0,
            },
            forward_diagnostics={
                4: module.SubingWatchForwardDiagnostics(4, 0, 0, None, None, None),
                1: module.SubingWatchForwardDiagnostics(1, 0, 0, None, None, None),
            },
        ),
    )
    result = module.SubingWatchResearchResult(products)

    assert payloads._subing_watch_payload(request, result) == {
        "schema_version": 1,
        "command": "research.subing-watch",
        "status": "ok",
        "readonly": True,
        "formula_version": "subing_watch_15m_v1",
        "since": "2026-08-01",
        "through": "2026-08-31",
        "symbols": ["ag", "jm"],
        "forward_bars": [1, 4],
        "products": [
            {
                "symbol": "ag",
                "candidate_count": 0,
                "direction_counts": {"buy": 0, "sell": 0},
                "candidates_per_trading_day": {},
                "same_direction_clustering": {
                    "adjacent_pair_count": 0,
                    "same_direction_pair_count": 0,
                    "rate": {"numerator": 0, "denominator": 0, "value": None},
                },
                "session_distribution": {},
                "context_availability": {
                    "available_count": 0,
                    "candidate_count": 0,
                    "rate": {"numerator": 0, "denominator": 0, "value": None},
                },
                "range_state_distribution": {
                    "range_unavailable": 0,
                    "no_active_range": 0,
                    "intact": 0,
                    "broken_up": 0,
                    "broken_down": 0,
                },
                "higher_timeframe_alignment_distribution": {
                    "aligned": 0,
                    "opposed": 0,
                    "neutral": 0,
                    "unavailable": 0,
                },
                "forward_diagnostics": {
                    "1": {
                        "sample_count": 0,
                        "truncated_count": 0,
                        "median_directional_close_change_bps": None,
                        "median_mfe_bps": None,
                        "median_mae_bps": None,
                    },
                    "4": {
                        "sample_count": 0,
                        "truncated_count": 0,
                        "median_directional_close_change_bps": None,
                        "median_mfe_bps": None,
                        "median_mae_bps": None,
                    },
                },
            },
            {
                "symbol": "jm",
                "candidate_count": 2,
                "direction_counts": {"buy": 1, "sell": 1},
                "candidates_per_trading_day": {
                    "2026-08-30": 1,
                    "2026-08-31": 1,
                },
                "same_direction_clustering": {
                    "adjacent_pair_count": 1,
                    "same_direction_pair_count": 0,
                    "rate": {"numerator": 0, "denominator": 1, "value": "0"},
                },
                "session_distribution": {"session_1": 1, "session_2": 1},
                "context_availability": {
                    "available_count": 1,
                    "candidate_count": 2,
                    "rate": {"numerator": 1, "denominator": 2, "value": "0.5"},
                },
                "range_state_distribution": {
                    "range_unavailable": 1,
                    "no_active_range": 0,
                    "intact": 1,
                    "broken_up": 0,
                    "broken_down": 0,
                },
                "higher_timeframe_alignment_distribution": {
                    "aligned": 1,
                    "opposed": 0,
                    "neutral": 0,
                    "unavailable": 1,
                },
                "forward_diagnostics": {
                    "1": {
                        "sample_count": 2,
                        "truncated_count": 0,
                        "median_directional_close_change_bps": "0",
                        "median_mfe_bps": "4.000000",
                        "median_mae_bps": "-2.000000",
                    },
                    "4": {
                        "sample_count": 1,
                        "truncated_count": 1,
                        "median_directional_close_change_bps": "12.340000",
                        "median_mfe_bps": "18.500000",
                        "median_mae_bps": "-3.250000",
                    },
                },
            },
        ],
    }


def test_empty_report_uses_explicit_zero_denominators() -> None:
    module, payloads = _modules()
    request = module.SubingWatchResearchRequest(
        since=date(2026, 8, 31),
        through=date(2026, 8, 31),
        symbols="active",
        forward_bars=(),
    )
    product = module.empty_subing_watch_product_diagnostics("jm", ())

    payload = payloads._subing_watch_payload(
        request,
        module.SubingWatchResearchResult((product,)),
    )

    assert payload["forward_bars"] == []
    assert payload["symbols"] == "active"
    assert payload["products"][0]["candidate_count"] == 0
    assert payload["products"][0]["same_direction_clustering"]["rate"] == {
        "numerator": 0,
        "denominator": 0,
        "value": None,
    }
    assert payload["products"][0]["context_availability"]["rate"] == {
        "numerator": 0,
        "denominator": 0,
        "value": None,
    }
