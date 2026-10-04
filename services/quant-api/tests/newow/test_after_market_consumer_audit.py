from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.market_data.newow.after_market_consumer_audit import (
    ConsumerAuditScope,
    run_bounded_consumer_audits,
    summarize_readiness,
)


def test_scope_retains_child_unverified_without_claiming_budget_exhaustion():
    from app.market_data.newow.after_market_consumer_audit import _merge_scope_parts

    part = {
        "status": "incomplete",
        "unverified_products": ["au"],
        "failures": [],
        "warmup_proposals": [],
        "case_count": 3,
        "main_ready_count": 0,
        "reference_ready_count": 0,
        "auxiliary_ready_count": 0,
        "budget_exhausted": False,
    }
    result = _merge_scope_parts(
        ConsumerAuditScope("newow_d1", ("au",), "1d", 600),
        [part],
        {"au": datetime(2026, 9, 29, 7, tzinfo=UTC)},
        [],
        "a" * 64,
    )
    assert result["unverified_products"] == ["au"]
    assert result["budget_exhausted"] is False


def test_unstarted_section_is_unverified_even_with_complete_case_structure():
    cases = [
        _case("au", strategy, "READY", "READY", "READY")
        for strategy in ("trend", "oscillation", "main_rise")
    ]
    cases[0]["sections"]["reference"] = {"status": "UNSTARTED"}
    result = summarize_readiness(
        {
            "complete": False,
            "budget_exhausted": True,
            "cases": cases,
            "provider_requests": 0,
            "writes": 0,
            "repair_targets": [],
        },
        products=("au",),
        frequency="1w",
        cutoffs={"au": "2026-09-24T07:00:00+00:00"},
        input_revision="a" * 64,
    )
    assert result["unverified_products"] == ["au"]


def test_cutoff_failure_is_unverified_but_not_a_timeout():
    def cutoff(scope, product):
        raise ValueError("CALENDAR_MISSING")

    result = run_bounded_consumer_audits(
        (ConsumerAuditScope("newow_d1", ("au",), "1d", 600),),
        resolve_cutoff=cutoff,
        input_revision=lambda scope: "a" * 64,
        build_report=lambda *args: pytest.fail("no cutoff means no report call"),
        clock=lambda: 0.0,
        total_timeout_seconds=1200,
    )["newow_d1"]
    assert result["unverified_products"] == ["au"]
    assert result["budget_exhausted"] is False


@pytest.mark.parametrize("number", [float("inf"), float("nan"), -1, True])
def test_diagnostics_reject_invalid_durations(number):
    from app.market_data.newow.after_market_consumer_audit import (
        public_consumer_diagnostics,
    )

    with pytest.raises(ValueError, match="NEWOW_CONSUMER_DIAGNOSTICS_INVALID"):
        public_consumer_diagnostics({"consumer_seconds": number})


def test_diagnostics_drop_untrusted_details_and_reject_unknown_call_identity():
    from app.market_data.newow.after_market_consumer_audit import (
        public_consumer_diagnostics,
    )

    call = {
        "product": "au",
        "strategy": "trend",
        "section": "chart",
        "elapsed_seconds": 1,
        "status": "error",
        "exception": "private-detail",
    }
    clean = public_consumer_diagnostics({"slow_calls": [call], "sql": "private-detail"})
    assert "sql" not in clean and "exception" not in clean["slow_calls"][0]
    call["section"] = "private-detail"
    with pytest.raises(ValueError, match="NEWOW_CONSUMER_DIAGNOSTICS_INVALID"):
        public_consumer_diagnostics({"slow_calls": [call]})


def test_scope_diagnostics_record_stage_time_and_skipped_group():
    elapsed = [0.0]

    def cutoff(scope, product):
        elapsed[0] += 1
        return datetime(2026, 9, 24, 7, tzinfo=UTC)

    def revision(scope):
        elapsed[0] += 1
        return "a" * 64

    def report(scope, products, at, remaining):
        assert remaining == 7
        elapsed[0] += 7
        return {
            "complete": True,
            "budget_exhausted": False,
            "cases": [
                _case(products[0], strategy, "READY", "READY", "READY")
                for strategy in ("trend", "oscillation", "main_rise")
            ],
            "provider_requests": 0,
            "writes": 0,
            "repair_targets": [],
        }

    result = run_bounded_consumer_audits(
        (ConsumerAuditScope("newow_w1", ("au", "b"), "1w", 10),),
        resolve_cutoff=cutoff,
        input_revision=revision,
        build_report=report,
        clock=lambda: elapsed[0],
        total_timeout_seconds=10,
        partition_key=lambda scope, product: product,
    )["newow_w1"]
    assert result["unverified_products"] == ["b"]
    assert result["budget_exhausted"] is True
    diagnostics = result["diagnostics"]
    assert diagnostics["cutoff_seconds"] == 2
    assert diagnostics["revision_seconds"] == 1
    assert diagnostics["report_seconds"] == 7
    assert diagnostics["elapsed_seconds"] == 10
    assert [g["status"] for g in diagnostics["groups"]] == [
        "completed",
        "skipped_budget",
    ]
    from app.market_data.after_market import _public_consumer_audit

    assert _public_consumer_audit(result)["diagnostics"] == diagnostics

    diagnostics["elapsed_seconds"] = float("nan")
    assert _public_consumer_audit(result) == {"status": "not_verified"}


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
            "auxiliary:trend_reversal": {"status": auxiliary, "reason": "NEWOW_AUXILIARY_WARMING"},
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


@pytest.mark.parametrize("frequency", ["1d", "1w"])
def test_summarize_readiness_accepts_all_current_consumer_sections(frequency):
    result = summarize_readiness(
        {
            "complete": True, "budget_exhausted": False,
            "cases": [
                _case("au", strategy, "READY", "READY", "READY", frequency=frequency)
                for strategy in ("trend", "oscillation", "main_rise")
            ],
            "repair_targets": [], "provider_requests": 0, "writes": 0,
        },
        products=("au",), frequency=frequency,
        cutoffs={"au": "2026-09-18T07:00:00.000001+00:00"},
        input_revision="a" * 64,
    )
    assert result["status"] == "audited"
    assert result["main_ready_count"] == result["reference_ready_count"] == 3
    assert result["auxiliary_ready_count"] == 18
    assert result["unverified_products"] == result["failures"] == []


def test_trend_reversal_failure_survives_public_consumer_status():
    from app.market_data.after_market import _public_consumer_audit

    cases = [_case("au", strategy, "READY", "READY", "READY")
             for strategy in ("trend", "oscillation", "main_rise")]
    failure = {"status": "UNKNOWN", "reason": "TRADING_SESSION_MISSING"}
    cases[0]["sections"]["auxiliary:trend_reversal"] = failure
    result = summarize_readiness(
        {"complete": False, "budget_exhausted": False, "cases": cases,
         "repair_targets": [], "provider_requests": 0, "writes": 0},
        products=("au",), frequency="1w",
        cutoffs={"au": "2026-09-18T07:00:00.000001+00:00"},
        input_revision="a" * 64,
    )
    public = _public_consumer_audit(result)
    assert public["status"] == "incomplete"
    assert public["failures"] == [{
        "product": "au", "strategy": "trend", "section": "auxiliary:trend_reversal",
        "reason": "TRADING_SESSION_MISSING",
    }]


@pytest.mark.parametrize(
    ("mutation", "section"),
    (("remove", "chart"), ("remove", "reference"),
     ("remove", "auxiliary:cup_handle"), ("remove", "auxiliary:trend_reversal"),
     ("add", "explanation")),
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


@pytest.mark.parametrize("repair_status", ["UNSTARTED", "UNKNOWN", "INTEGRITY_ERROR"])
def test_unverified_repair_retains_product_without_claiming_a_plan(repair_status):
    report = {
        "complete": False, "budget_exhausted": repair_status == "UNSTARTED",
        "cases": [
            _case("au", strategy, "DATA_UNAVAILABLE", "DATA_UNAVAILABLE", "DATA_UNAVAILABLE", frequency="1d")
            for strategy in ("trend", "oscillation", "main_rise")
        ],
        "repair_targets": [{
            "symbol": "au", "contract": "AU2612", "frequency": "1d",
            "through": "2026-09-30", "status": repair_status,
            "expected_bar_count": None, "provider_request_count": None,
            "plan_sha256": None,
        }],
        "provider_requests": 0, "writes": 0,
    }
    result = summarize_readiness(
        report, products=("au",), frequency="1d",
        cutoffs={"au": "2026-09-30T07:00:00.000001+00:00"},
        input_revision="a" * 64,
    )
    assert result["status"] == "incomplete"
    assert result["unverified_products"] == ["au"]
    assert result["warmup_proposals"] == []
    assert result["failures"]
    report["repair_targets"][0]["plan_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="NEWOW_CONSUMER_AUDIT_INVALID"):
        summarize_readiness(
            report, products=("au",), frequency="1d",
            cutoffs={"au": "2026-09-30T07:00:00.000001+00:00"},
            input_revision="a" * 64,
        )
    report["repair_targets"][0].update(plan_sha256=None, symbol="rb")
    with pytest.raises(ValueError, match="NEWOW_CONSUMER_AUDIT_INVALID"):
        summarize_readiness(
            report, products=("au",), frequency="1d",
            cutoffs={"au": "2026-09-30T07:00:00.000001+00:00"},
            input_revision="a" * 64,
        )


def test_bounded_consumer_audits_keep_scopes_and_total_deadline_separate():
    elapsed = [0.0]
    calls = []

    def build(scope, products, as_of, timeout):
        calls.append((scope.key, products, as_of, timeout))
        elapsed[0] += 3
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
        resolve_cutoff=lambda scope, product: datetime(
            2026, 9, 18, 7, 0, 0, 1, tzinfo=UTC
        ),
        build_report=build,
        input_revision=lambda scope: ("a" if scope.frequency == "1d" else "b") * 64,
        clock=lambda: elapsed[0],
        total_timeout_seconds=8,
    )
    assert set(result) == {"newow_d1", "newow_w1"}
    assert result["newow_d1"]["case_count"] == 6
    assert result["newow_w1"]["case_count"] == 3
    assert [call[0] for call in calls] == ["newow_d1", "newow_w1"]
    assert all(1 <= call[3] <= 4 for call in calls)


def test_candidate_weekly_audit_partitions_same_cutoff_by_quality_policy():
    calls = []

    def build(scope, products, as_of, timeout):
        calls.append(products)
        return {
            "complete": True,
            "budget_exhausted": False,
            "provider_requests": 0,
            "writes": 0,
            "repair_targets": [],
            "cases": [
                _case(product, strategy, "READY", "READY", "NOT_APPLICABLE")
                for product in products
                for strategy in ("trend", "oscillation", "main_rise")
            ],
        }

    cutoff = datetime(2026, 9, 18, 7, 0, 0, 1, tzinfo=UTC)
    result = run_bounded_consumer_audits(
        (ConsumerAuditScope("newow_w1", ("au", "b"), "1w", 10),),
        resolve_cutoff=lambda _scope, _product: cutoff,
        build_report=build,
        input_revision=lambda _scope: "a" * 64,
        clock=lambda: 0.0,
        total_timeout_seconds=20,
        partition_key=lambda _scope, product: (
            "weekly_v2" if product == "b" else "v1"
        ),
    )

    assert calls == [("au",), ("b",)]
    assert result["newow_w1"]["case_count"] == 6
