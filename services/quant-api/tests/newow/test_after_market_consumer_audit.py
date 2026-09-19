from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.market_data.newow.after_market_consumer_audit import (
    ConsumerAuditScope,
    run_bounded_consumer_audits,
    summarize_readiness,
)


def _case(
    product: str, strategy: str, chart: str, reference: str, auxiliary: str,
    *, frequency: str = "1w",
):
    return {
        "symbol": product,
        "strategy": strategy,
        "frequency": frequency,
        "main": {"status": chart},
        "sections": {
            "chart": {"status": chart},
            "reference": {"status": reference},
            "auxiliary:macd": {"status": auxiliary, "reason": "NEWOW_MACD_WARMING"},
            "auxiliary:main_force_control": {"status": auxiliary, "reason": "NEWOW_AUXILIARY_WARMING"},
            "auxiliary:up_down_energy": {"status": auxiliary, "reason": "NEWOW_AUXILIARY_WARMING"},
            "auxiliary:zhaoyao_mirror": {"status": auxiliary, "reason": "NEWOW_AUXILIARY_WARMING"},
            "auxiliary:cup_handle": {"status": auxiliary, "reason": "NEWOW_AUXILIARY_WARMING"},
        },
    }


def test_summarize_readiness_accepts_legal_non_ready_strategy_states():
    report = {
        "complete": True,
        "budget_exhausted": False,
        "cases": [
            _case("au", strategy, "READY", "READY", "WARMING")
            for strategy in ("trend", "oscillation", "main_rise")
        ],
        "repair_targets": [],
        "provider_requests": 0,
        "writes": 0,
    }
    result = summarize_readiness(
        report, products=("au",), frequency="1w",
        cutoffs={"au": "2026-09-18T07:00:00.000001+00:00"},
        input_revision="a" * 64,
    )
    assert result["status"] == "audited"
    assert result["case_count"] == 3
    assert result["main_ready_count"] == 3
    assert result["reference_ready_count"] == 3
    assert result["auxiliary_ready_count"] == 0
    assert result["failures"] == []


@pytest.mark.parametrize(
    ("mutation", "section"),
    (("remove", "chart"), ("remove", "reference"),
     ("remove", "auxiliary:cup_handle"), ("add", "explanation")),
)
def test_summarize_readiness_rejects_missing_or_extra_consumer_section(
    mutation, section,
):
    cases = [
        _case("au", strategy, "READY", "READY", "READY")
        for strategy in ("trend", "oscillation", "main_rise")
    ]
    if mutation == "remove":
        cases[0]["sections"].pop(section)
    else:
        cases[0]["sections"][section] = {"status": "UNOPENED"}
    report = {
        "complete": True,
        "budget_exhausted": False,
        "cases": cases,
        "repair_targets": [],
        "provider_requests": 0,
        "writes": 0,
    }

    result = summarize_readiness(
        report, products=("au",), frequency="1w",
        cutoffs={"au": "2026-09-18T07:00:00.000001+00:00"},
        input_revision="a" * 64,
    )

    assert result["status"] == "incomplete"
    assert result["unverified_products"] == ["au"]


def test_summarize_readiness_preserves_exact_readonly_warmup_proposal():
    report = {
        "complete": True,
        "budget_exhausted": False,
        "cases": [
            _case("au", strategy, "DATA_UNAVAILABLE", "DATA_UNAVAILABLE", "DATA_UNAVAILABLE")
            for strategy in ("trend", "oscillation", "main_rise")
        ],
        "repair_targets": [{
            "symbol": "au", "contract": "AU2612", "frequency": "1w",
            "through": "2026-09-18", "status": "PROPOSED",
            "expected_bar_count": 44, "provider_request_count": 3,
            "plan_sha256": "b" * 64,
        }],
        "provider_requests": 0,
        "writes": 0,
    }
    result = summarize_readiness(
        report, products=("au",), frequency="1w",
        cutoffs={"au": "2026-09-18T07:00:00.000001+00:00"},
        input_revision="a" * 64,
    )
    assert result["status"] == "incomplete"
    assert result["warmup_proposals"] == [{
        "product": "au", "contract": "AU2612", "frequency": "1w",
        "through": "2026-09-18", "status": "PROPOSED",
        "expected_bar_count": 44, "provider_request_count": 3,
        "plan_sha256": "b" * 64,
    }]
    assert report["provider_requests"] == 0 and report["writes"] == 0


def test_bounded_consumer_audits_keep_scopes_and_total_deadline_separate():
    ticks = iter((0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0))
    calls = []

    def build(scope, products, as_of, timeout):
        calls.append((scope.key, products, as_of, timeout))
        return {
            "complete": True, "budget_exhausted": False,
            "provider_requests": 0, "writes": 0, "repair_targets": [],
            "cases": [
                _case(
                    product, strategy, "READY", "READY", "NOT_APPLICABLE",
                    frequency=scope.frequency,
                )
                for product in products
                for strategy in ("trend", "oscillation", "main_rise")
            ],
        }

    scopes = (
        ConsumerAuditScope("newow_d1", ("au", "rb"), "1d", 4),
        ConsumerAuditScope("newow_w1", ("au",), "1w", 4),
    )
    result = run_bounded_consumer_audits(
        scopes,
        resolve_cutoff=lambda scope, product: datetime(2026, 9, 18, 7, 0, 0, 1, tzinfo=UTC),
        build_report=build,
        input_revision=lambda scope: ("a" if scope.frequency == "1d" else "b") * 64,
        clock=lambda: next(ticks),
        total_timeout_seconds=8,
    )
    assert set(result) == {"newow_d1", "newow_w1"}
    assert result["newow_d1"]["case_count"] == 6
    assert result["newow_w1"]["case_count"] == 3
    assert [call[0] for call in calls] == ["newow_d1", "newow_w1"]
    assert all(1 <= call[3] <= 4 for call in calls)
