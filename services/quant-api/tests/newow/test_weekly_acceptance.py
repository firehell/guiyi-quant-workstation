"""Deterministic offline acceptance for the frozen Newow weekly closeout."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import (
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    ProductBar,
    ProductFrequency,
    ProductStrategy,
)
from guiyi_quant.newow.product_identity import build_segment_id
from app.market_data.newow.product_query import ProductReadWindow
from app.market_data.newow.product_reader import (
    ProductReadSet,
    ResolvedPerformanceWindow,
)
from app.market_data.newow.product_service import (
    NewowProductService,
    ProductSection,
    ProductServiceQuery,
)


AS_OF = datetime(2026, 9, 13, 6, 36, 13, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[4]
PRODUCTS = tuple(
    line.strip()
    for line in (ROOT / "data/universe/operational_products.txt")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
)
STRATEGIES = ("trend", "oscillation", "main_rise")
AUXILIARY = (
    "auxiliary:macd",
    "auxiliary:main_force_control",
    "auxiliary:up_down_energy",
    "auxiliary:zhaoyao_mirror",
    "auxiliary:cup_handle",
)


class _InitialClearReader:
    def __init__(self, bars, evidence):
        self.bars = bars
        self.evidence = evidence
        self.window = ProductReadWindow(
            bars[0].bar.trading_day, bars[-1].bar.trading_day
        )

    def resolve_older_chart_window(self, *_args):
        return None

    def resolve_chart_window(self, *_args):
        return self.window

    def resolve_performance_window(self, *_args):
        return ResolvedPerformanceWindow(
            self.window.since,
            self.window.through,
            self.window.through,
            self.bars[-1].bar.bar_end,
        )

    def load(self, query, as_of):
        return ProductReadSet(
            query.frequency,
            {query.frequency: self.bars},
            (),
            (),
            self.window,
            self.window,
            {},
            as_of,
            {query.frequency: (self.evidence,)},
        )


@pytest.fixture
def pt_results(product_cases):
    base = product_cases.initial_clear_input("1w")
    segment = build_segment_id(
        "pt", "PT2610", datetime(2025, 1, 1, tzinfo=UTC)
    )
    bars = tuple(
        ProductBar(
            replace(
                item.bar,
                product="pt",
                physical_contract="PT2610",
                segment_id=segment,
            ),
            ProductFrequency.WEEKLY,
        )
        for item in base.bars
    )
    evidence = product_cases.synthetic_lifecycle_evidence(bars)
    reader = _InitialClearReader(bars, evidence)
    service = NewowProductService(lambda *_args: reader, now=lambda: AS_OF)
    chart = service.query(
        ProductServiceQuery(
            "pt",
            ProductStrategy.MAIN_RISE,
            ProductFrequency.WEEKLY,
            as_of=AS_OF,
            chart_limit=1,
        )
    )
    reference = service.query(
        ProductServiceQuery(
            "pt",
            ProductStrategy.MAIN_RISE,
            ProductFrequency.WEEKLY,
            section="reference",
            as_of=AS_OF,
            snapshot_token=chart.meta.snapshot_token,
        )
    )
    return chart, reference


def _report() -> dict:
    cases = []
    for product_index, product in enumerate(PRODUCTS):
        for strategy in STRATEGIES:
            ready = product_index == 0
            chart = (
                {
                    "status": "READY",
                    "evidence_status": "ACTIVE_CODE_VERIFIED",
                    "reason": None,
                }
                if ready
                else {
                    "status": "DATA_UNAVAILABLE",
                    "reason": "REPLAY_PREFIX_MISSING",
                    "error": {"diagnostic": {"reason": "REPLAY_PREFIX_MISSING"}},
                }
            )
            reference = dict(chart)
            cases.append(
                {
                    "symbol": product,
                    "strategy": strategy,
                    "frequency": "1w",
                    "main": dict(chart),
                    "sections": {
                        "chart": dict(chart),
                        **{
                            name: {
                                "status": "WARMING",
                                "evidence_status": "ACTIVE_CODE_VERIFIED",
                                "reason": "NEWOW_AUXILIARY_WARMING",
                            }
                            for name in AUXILIARY
                        },
                        "reference": reference,
                        "explanation": {
                            "status": "UNOPENED",
                            "reason": "NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN",
                        },
                        "comparator": {
                            "status": "NOT_APPLICABLE",
                            "evidence_status": "ACTIVE_CODE_VERIFIED",
                            "reason": "NEWOW_COMPARATOR_SAMPLE_INSUFFICIENT",
                        },
                    },
                }
            )
    enumerations = [
        {
            "symbol": product,
            "frequency": "1w",
            "section": section,
            "status": "UNOPENED" if section == "explanation" else "ENUMERATED",
            "reason": (
                "NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN"
                if section == "explanation"
                else None
            ),
            "as_of": AS_OF.isoformat(),
            **(
                {}
                if section == "explanation"
                else {
                    "since": "2026-01-01",
                    "through": "2026-09-11",
                    "owner_count": 1,
                }
            ),
        }
        for product in PRODUCTS
        for section in ("chart", "auxiliary", "reference", "explanation")
    ]
    return {
        "schema_version": 1,
        "command": "data.newow-readiness",
        "readonly": True,
        "status": "audited",
        "complete": True,
        "as_of": AS_OF.isoformat(),
        "release_stage": "weekly",
        "matrix": True,
        "frequency_scope": ["1w"],
        "product_count": 60,
        "main_case_count": 180,
        "main_ready_count": 3,
        "budget_exhausted": False,
        "work_used": 1000,
        "enumerations": enumerations,
        "dependencies": [
            {
                "symbol": PRODUCTS[1],
                "contract": "AG2701",
                "frequency": "1w",
                "through": "2026-09-11",
                "as_of": AS_OF.isoformat(),
                "status": "DATA_UNAVAILABLE",
                "reason": "REPLAY_PREFIX_MISSING",
                "error": {"diagnostic": {"reason": "REPLAY_PREFIX_MISSING"}},
                "owners": [{"since": "2026-01-01", "through": "2026-09-11"}],
                "consumers": [
                    {"strategy": "trend", "frequency": "1w", "section": "chart"}
                ],
            }
        ],
        "repair_targets": [
            {
                "symbol": PRODUCTS[1],
                "contract": "AG2701",
                "frequency": "1w",
                "through": "2026-09-11",
                "status": "PROPOSED",
                "reason": None,
                "expected_bar_count": 10,
                "provider_request_count": 1,
                "plan_sha256": "a" * 64,
                "consumers": [
                    {"strategy": "trend", "frequency": "1w", "section": "chart"}
                ],
                "dependency_frequencies": ["1d"],
                "frequencies": ["1d", "1w"],
                "requested_through": "2026-09-11",
                "effective_through": "2026-09-11",
                "direct_target_count": 1,
                "derived_target_count": 0,
                "target_windows": [
                    {
                        "dataset": ["contract", PRODUCTS[1], "AG2701", "1w"],
                        "expected_bar_count": 10,
                        "expected_start": "2026-09-11T07:00:00+00:00",
                        "expected_end": "2026-09-11T07:00:00+00:00",
                        "missing_start": "2026-09-11T07:00:00+00:00",
                        "missing_end": "2026-09-11T07:00:00+00:00",
                        "missing_bar_count": 10,
                        "month": 9,
                        "year": 2026,
                    }
                ],
            }
        ],
        "metadata_proposals": [],
        "cases": cases,
        "provider_requests": 0,
        "writes": 0,
    }


def test_typed_ready_initial_clear_pair_is_accepted_without_rebuilding_hidden_history(
    pt_results,
):
    from scripts.newow_weekly_acceptance import validate_pt_initial_clear

    chart, reference = pt_results
    assert len(chart.chart.value.bars) == 1
    result = validate_pt_initial_clear(chart, reference, expected_as_of=AS_OF)

    assert result["accepted"] is True
    assert result["violations"] == []
    assert result["initial_clear"]["physical_contract"] == "PT2610"
    assert result["initial_clear"]["sequence"] == 0
    assert result["reference_trade_count"] == 0
    assert chart.meta.input_content_sha256 != reference.meta.input_content_sha256


@pytest.mark.parametrize(
    "mutate,code",
    [
        (
            lambda chart, reference: (
                replace(
                    chart,
                    chart=replace(
                        chart.chart,
                        status=FeatureStatus(
                            FeatureRuntimeStatus.WARMING,
                            EvidenceStatus.ACTIVE_CODE_VERIFIED,
                            "NEWOW_CHART_WARMING",
                        ),
                    ),
                ),
                reference,
            ),
            "CHART_NOT_READY",
        ),
        (
            lambda chart, reference: (
                chart,
                replace(reference, reference=replace(reference.reference, value=None)),
            ),
            "REFERENCE_VALUE_MISSING",
        ),
        (
            lambda chart, reference: (
                chart,
                replace(
                    reference,
                    meta=replace(reference.meta, snapshot_token="other-token"),
                ),
            ),
            "SNAPSHOT_TOKEN_MISMATCH",
        ),
        (
            lambda chart, reference: (
                replace(
                    chart,
                    meta=replace(
                        chart.meta,
                        identity=build_product_identity(
                            "rb", ProductStrategy.MAIN_RISE, ProductFrequency.WEEKLY
                        ),
                    ),
                ),
                reference,
            ),
            "CHART_IDENTITY_MISMATCH",
        ),
        (
            lambda chart, reference: (
                chart,
                replace(
                    reference,
                    meta=replace(
                        reference.meta,
                        reference_model_version="newow_marker_reference_zero_cost_v1",
                    ),
                ),
            ),
            "REFERENCE_CONTRACT_MISMATCH",
        ),
        (
            lambda chart, reference: (
                replace(chart, meta=replace(chart.meta, data_revision_identity="fake")),
                reference,
            ),
            "CHART_DATA_REVISION_UNEXPECTED",
        ),
    ],
)
def test_pt_validator_rejects_wrong_typed_status_identity_or_generation(
    pt_results, mutate, code
):
    from scripts.newow_weekly_acceptance import validate_pt_initial_clear

    result = validate_pt_initial_clear(*mutate(*pt_results), expected_as_of=AS_OF)
    assert result["accepted"] is False
    assert code in result["violations"]


def test_pt_validator_rejects_related_initial_clear_and_phantom_trade(pt_results):
    from scripts.newow_weekly_acceptance import validate_pt_initial_clear

    chart, reference = pt_results
    clear = chart.chart.value.replay.actions[0]
    forged = SimpleNamespace(
        entry_signal_id=clear.signal_id,
        exit_signal_id=None,
    )
    projection = replace(
        reference.reference.value.projection,
        trades=reference.reference.value.projection.trades,
    )
    object.__setattr__(projection, "trades", (forged,))
    reference = replace(
        reference,
        reference=replace(
            reference.reference,
            value=replace(reference.reference.value, projection=projection),
        ),
    )

    result = validate_pt_initial_clear(chart, reference, expected_as_of=AS_OF)
    assert result["accepted"] is False
    assert "INITIAL_CLEAR_REFERENCED_BY_TRADE" in result["violations"]


def _with_invalid_identity(result, field, value):
    identity = deepcopy(result.meta.identity)
    object.__setattr__(identity, field, value)
    return replace(result, meta=replace(result.meta, identity=identity))


def _with_invalid_initial_clear(chart, field, value):
    changed = deepcopy(chart)
    object.__setattr__(changed.chart.value.replay.actions[0], field, value)
    return changed


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda chart, reference: (replace(chart, section=ProductSection.REFERENCE), reference), "CHART_SECTION_MISMATCH"),
        (lambda chart, reference: (replace(chart, chart=replace(chart.chart, delivery="deferred")), reference), "CHART_NOT_DELIVERED"),
        (lambda chart, reference: (replace(chart, chart=replace(chart.chart, value=None)), reference), "CHART_VALUE_MISSING"),
        (lambda chart, reference: (replace(chart, meta=replace(chart.meta, snapshot_token="")), reference), "CHART_SNAPSHOT_TOKEN_MISSING"),
        (lambda chart, reference: (replace(chart, meta=replace(chart.meta, as_of=AS_OF.replace(day=12))), reference), "CHART_AS_OF_MISMATCH"),
        (lambda chart, reference: (replace(chart, meta=replace(chart.meta, schema_version="v1")), reference), "CHART_SCHEMA_MISMATCH"),
        (lambda chart, reference: (replace(chart, meta=replace(chart.meta, futures_adaptation_version="wrong")), reference), "CHART_CONTRACT_MISMATCH"),
        (lambda chart, reference: (_with_invalid_identity(chart, "strategy", ProductStrategy.TREND), reference), "CHART_IDENTITY_MISMATCH"),
        (lambda chart, reference: (_with_invalid_identity(chart, "frequency", ProductFrequency.DAILY), reference), "CHART_IDENTITY_MISMATCH"),
        (lambda chart, reference: (_with_invalid_identity(chart, "series_kind", "continuous"), reference), "CHART_IDENTITY_MISMATCH"),
        (lambda chart, reference: (_with_invalid_identity(chart, "profile_id", "wrong"), reference), "CHART_IDENTITY_MISMATCH"),
        (lambda chart, reference: (_with_invalid_identity(chart, "formula_versions", ("wrong",)), reference), "CHART_IDENTITY_MISMATCH"),
        (lambda chart, reference: (_with_invalid_initial_clear(chart, "trade_eligibility", "ELIGIBLE"), reference), "INITIAL_CLEAR_COUNT_INVALID"),
        (lambda chart, reference: (_with_invalid_initial_clear(chart, "related_build_id", "fake-build"), reference), "INITIAL_CLEAR_FIELDS_INVALID"),
        (lambda chart, reference: (_with_invalid_initial_clear(chart, "sequence", 1), reference), "INITIAL_CLEAR_FIELDS_INVALID"),
    ],
)
def test_pt_validator_rejects_each_frozen_contract_boundary(pt_results, mutate, code):
    from scripts.newow_weekly_acceptance import validate_pt_initial_clear

    result = validate_pt_initial_clear(*mutate(*pt_results), expected_as_of=AS_OF)

    assert result["accepted"] is False
    assert code in result["violations"]


def test_summary_recomputes_three_of_180_ready_but_keeps_audit_complete():
    from scripts.newow_weekly_acceptance import summarize_readiness

    result = summarize_readiness(_report(), PRODUCTS, AS_OF)

    assert result["valid"] is True
    assert result["audit_complete"] is True
    assert result["matrix_covered"] is True
    assert result["scope_covered"] is True
    assert result["counts"] == {
        "total": 180,
        "main_ready": 3,
        "reference_ready": 3,
        "joint_ready": 3,
    }
    assert result["joint_ready_cases"] == [
        {"symbol": PRODUCTS[0], "strategy": strategy, "frequency": "1w"}
        for strategy in STRATEGIES
    ]
    assert result["non_joint_ready_outcome_counts"] == {
        "DATA_UNAVAILABLE:REPLAY_PREFIX_MISSING|DATA_UNAVAILABLE:REPLAY_PREFIX_MISSING": 177
    }


def test_summary_accepts_honest_incomplete_audit_and_preserves_pending_reason():
    from scripts.newow_weekly_acceptance import summarize_readiness

    report = _report()
    report["dependencies"][0].update(
        status="UNKNOWN",
        reason="HISTORICAL_SESSION_FACT_MISSING",
        error={"diagnostic": {"reason": "HISTORICAL_SESSION_FACT_MISSING"}},
    )
    report.update(complete=False, status="incomplete")

    result = summarize_readiness(report, PRODUCTS, AS_OF)

    assert result["valid"] is True
    assert result["audit_complete"] is False
    assert result["counts"]["joint_ready"] == 3
    assert result["pending_count"] == 1
    assert result["pending_outcome_counts"] == {
        "dependency:UNKNOWN:HISTORICAL_SESSION_FACT_MISSING": 1
    }


@pytest.mark.parametrize(
    "status,reason",
    [("UNSTARTED", None), ("UNKNOWN", "PLANNER_UNAVAILABLE")],
)
def test_summary_accepts_native_unfinished_repair_without_planner_fields(
    status, reason
):
    from scripts.newow_weekly_acceptance import summarize_readiness

    report = _report()
    repair = report["repair_targets"][0]
    report["repair_targets"] = [
        {
            key: repair[key]
            for key in (
                "symbol",
                "contract",
                "frequency",
                "through",
                "consumers",
                "expected_bar_count",
                "provider_request_count",
                "plan_sha256",
            )
        }
    ]
    report["repair_targets"][0].update(
        status=status,
        reason=reason,
        expected_bar_count=None,
        provider_request_count=None,
        plan_sha256=None,
    )
    report.update(complete=False, status="incomplete")

    result = summarize_readiness(report, PRODUCTS, AS_OF)

    assert result["valid"] is True
    assert result["audit_complete"] is False
    assert result["pending_outcome_counts"] == {
        f"repair:{status}:{reason or '-'}": 1
    }


def test_summary_accepts_native_repair_metadata_failure_without_planner_fields():
    from scripts.newow_weekly_acceptance import summarize_readiness

    report = _report()
    repair = report["repair_targets"][0]
    report["repair_targets"] = [
        {
            key: repair[key]
            for key in (
                "symbol",
                "contract",
                "frequency",
                "through",
                "consumers",
            )
        }
    ]
    report["repair_targets"][0].update(
        status="UNKNOWN",
        reason="HISTORICAL_SESSION_FACT_MISSING",
        error={"diagnostic": {"reason": "HISTORICAL_SESSION_FACT_MISSING"}},
        expected_bar_count=None,
        provider_request_count=None,
        plan_sha256=None,
    )
    report.update(complete=False, status="incomplete")

    result = summarize_readiness(report, PRODUCTS, AS_OF)

    assert result["valid"] is True
    assert result["audit_complete"] is False
    assert result["pending_outcome_counts"] == {
        "repair:UNKNOWN:HISTORICAL_SESSION_FACT_MISSING": 1
    }


def test_summary_accepts_native_enumeration_metadata_proposal():
    from scripts.newow_weekly_acceptance import summarize_readiness

    report = _report()
    report["metadata_proposals"] = [
        {
            "symbol": "ag",
            "frequency": "1w",
            "section": "chart",
            "status": "UNKNOWN",
            "as_of": AS_OF.isoformat(),
            "reason": "HISTORICAL_SESSION_FACT_MISSING",
            "error": {
                "diagnostic": {"reason": "HISTORICAL_SESSION_FACT_MISSING"}
            },
            "expected_bar_count": None,
            "provider_request_count": None,
            "proposal": "BOUNDED_METADATA_REPAIR_REVIEW_REQUIRED",
        }
    ]
    report.update(complete=False, status="incomplete")

    result = summarize_readiness(report, PRODUCTS, AS_OF)

    assert result["valid"] is True
    assert result["audit_complete"] is False
    assert result["pending_outcome_counts"] == {
        "metadata:UNKNOWN:HISTORICAL_SESSION_FACT_MISSING": 1
    }


def test_summary_aggregates_repair_and_metadata_rows_without_large_private_details():
    from scripts.newow_weekly_acceptance import summarize_readiness

    report = _report()
    report["repair_targets"][0].update(
        targets=[{"large": "discard"}],
        scope_diagnostics=[{"large": "discard"}],
    )
    report["metadata_proposals"] = [
        {
            "symbol": "ag",
            "contract": "AG2701",
            "frequency": "1w",
            "through": "2026-09-11",
            "as_of": AS_OF.isoformat(),
            "status": "UNKNOWN",
            "reason": "HISTORICAL_SESSION_FACT_MISSING",
            "proposal": "BOUNDED_METADATA_REPAIR_REVIEW_REQUIRED",
            "expected_bar_count": None,
            "provider_request_count": None,
            "owners": [{"since": "2026-01-01", "through": "2026-09-11"}],
            "consumers": [
                {"strategy": "trend", "frequency": "1w", "section": "chart"}
            ],
            "error": {
                "diagnostic": {"reason": "HISTORICAL_SESSION_FACT_MISSING"},
                "private": "discard",
            },
        }
    ]
    report.update(complete=False, status="incomplete")

    result = summarize_readiness(report, PRODUCTS, AS_OF)

    assert result["valid"] is True
    assert result["repair_target_count"] == 1
    assert result["repair_target_outcome_counts"] == {"PROPOSED:-": 1}
    assert result["metadata_proposal_count"] == 1
    assert result["metadata_proposal_outcome_counts"] == {
        "UNKNOWN:HISTORICAL_SESSION_FACT_MISSING": 1
    }
    assert "repair_targets" not in result
    assert "metadata_proposals" not in result
    assert "discard" not in __import__("json").dumps(result)


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda report: report.update(schema_version="newow_readiness_compact_v1"), "REPORT_SCHEMA_INVALID"),
        (lambda report: report.update(matrix=False), "MATRIX_REQUIRED"),
        (lambda report: report.update(as_of="2026-09-12T00:00:00+00:00"), "AS_OF_MISMATCH"),
        (lambda report: report.update(provider_requests=None), "PROVIDER_REQUESTS_NOT_ZERO"),
        (lambda report: report.update(writes="0"), "WRITES_NOT_ZERO"),
        (lambda report: report.pop("work_used"), "WORK_USED_INVALID"),
        (
            lambda report: report["dependencies"][0].update(frequency="60m"),
            "DEPENDENCY_IDENTITY_INVALID",
        ),
        (
            lambda report: report["dependencies"][0].update(contract="RB9999"),
            "DEPENDENCY_IDENTITY_INVALID",
        ),
        (
            lambda report: report["dependencies"][0]["consumers"][0].update(
                strategy="foreign"
            ),
            "DEPENDENCY_IDENTITY_INVALID",
        ),
        (
            lambda report: report["repair_targets"][0].pop("plan_sha256"),
            "REPAIR_SCHEMA_INVALID",
        ),
        (
            lambda report: report["repair_targets"][0]["target_windows"][0].update(
                expected_bar_count=11
            ),
            "REPAIR_SCHEMA_INVALID",
        ),
        (lambda report: report["cases"].append(deepcopy(report["cases"][0])), "CASE_KEYS_INVALID"),
        (lambda report: report["cases"].pop(), "CASE_KEYS_INVALID"),
        (
            lambda report: report["cases"][0]["sections"]["reference"].update(
                status="BANANA"
            ),
            "CASE_STATE_INVALID",
        ),
        (
            lambda report: report["enumerations"][0].update(status="BANANA"),
            "ENUMERATION_IDENTITY_INVALID",
        ),
        (lambda report: report.update(main_ready_count=180), "MAIN_READY_COUNT_MISMATCH"),
        (lambda report: report.update(complete=False), "COMPLETE_FLAG_MISMATCH"),
        (lambda report: report.update(status="incomplete"), "STATUS_MISMATCH"),
        (
            lambda report: report.update(budget_exhausted=True),
            "COMPLETE_FLAG_MISMATCH",
        ),
        (
            lambda report: report["dependencies"][0].update(status="UNKNOWN"),
            "COMPLETE_FLAG_MISMATCH",
        ),
        (
            lambda report: report["cases"][0]["sections"]["chart"].update(
                status="UNSTARTED"
            ),
            "MAIN_CHART_MISMATCH",
        ),
    ],
)
def test_summary_rejects_incomplete_scope_fake_counts_and_fake_completion(mutate, code):
    from scripts.newow_weekly_acceptance import summarize_readiness

    report = _report()
    mutate(report)
    result = summarize_readiness(report, PRODUCTS, AS_OF)
    assert result["valid"] is False
    assert code in result["violations"]


def test_summary_cli_never_opens_session_or_provider(tmp_path):
    from scripts.newow_weekly_acceptance import main

    report_path = tmp_path / "full.json"
    scope_path = tmp_path / "scope.txt"
    report_path.write_text(__import__("json").dumps(_report()), encoding="utf-8")
    scope_path.write_text("\n".join(PRODUCTS) + "\n", encoding="utf-8")
    calls = []

    def forbidden():
        calls.append(True)
        raise AssertionError("summary opened a session/provider")

    output = io.StringIO()
    code = main(
        [
            "summary",
            "--report",
            str(report_path),
            "--scope",
            str(scope_path),
            "--expected-as-of",
            AS_OF.isoformat(),
        ],
        stdout=output,
        session_factory=forbidden,
        service_factory=forbidden,
    )

    payload = __import__("json").loads(output.getvalue())
    assert code == 0
    assert payload["valid"] is True
    assert payload["scope_file_sha256"] != payload["normalized_scope_sha256"]
    assert calls == []


def test_pt_runner_uses_one_readonly_transaction_and_rolls_back(pt_results):
    from scripts.newow_weekly_acceptance import run_pt_probe

    engine = create_engine("sqlite+pysqlite:///:memory:")
    rolled_back = []
    event.listen(engine, "rollback", lambda _connection: rolled_back.append(True))
    chart, reference = pt_results

    class Service:
        def __init__(self):
            self.queries = []

        def query(self, query):
            self.queries.append(query)
            return chart if len(self.queries) == 1 else reference

    service = Service()
    result = run_pt_probe(
        session_factory=lambda: Session(engine),
        service_factory=lambda _session, _as_of: service,
    )

    assert result["accepted"] is True
    assert len(service.queries) == 2
    assert service.queries[1].snapshot_token == chart.meta.snapshot_token
    assert rolled_back == [True]


def test_pt_cli_serializes_the_two_already_read_results_without_a_third_query(
    pt_results,
):
    from scripts.newow_weekly_acceptance import main

    chart, reference = pt_results

    class Service:
        def __init__(self):
            self.queries = []

        def query(self, query):
            self.queries.append(query)
            if len(self.queries) > 2:
                raise AssertionError("accepted output queried a third time")
            return chart if len(self.queries) == 1 else reference

    engine = create_engine("sqlite+pysqlite:///:memory:")
    service = Service()
    output = io.StringIO()
    code = main(
        ["pt"],
        stdout=output,
        session_factory=lambda: Session(engine),
        service_factory=lambda _session, _as_of: service,
    )

    payload = __import__("json").loads(output.getvalue())
    assert code == 0
    assert payload["accepted"] is True
    assert payload["chart_result"]["section"] == "chart"
    assert payload["reference_result"]["section"] == "reference"
    assert len(service.queries) == 2
