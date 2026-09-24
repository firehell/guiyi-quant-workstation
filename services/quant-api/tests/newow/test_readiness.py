"""Readiness must collect independent gaps and never turn evidence into success."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.market_data.market_data_service import MarketDataError


def test_owner_enumeration_survives_missing_physical_data(product_cases):
    reader, query, source = product_cases.paged_reader(prefix_bars=3, frequency="1d")
    source.physical.clear()
    owners = reader.dependency_owners(query.product, query.since, query.through)
    assert [owner.contract for owner in owners] == ["RB2605"]
    assert source.physical_page_requests == []


def _audit_module():
    from app.market_data.newow import readiness

    return readiness


class AuditReader:
    """Boundary fixture: two independently missing physical owners."""

    def resolve_chart_window(self, product, frequency, limit, as_of):
        from app.market_data.newow.product_query import ProductReadWindow

        return ProductReadWindow(date(2026, 9, 1), date(2026, 9, 4))

    def resolve_performance_window(self, product, frequency, since, through, as_of):
        return SimpleNamespace(
            requested_since=date(2026, 9, 1),
            actual_through=date(2026, 9, 4),
            cutoff=as_of,
        )

    def dependency_owners(self, product, since, through):
        from app.market_data.domain import ResolvedContractSegment

        return (
            ResolvedContractSegment("RB2609", since, date(2026, 9, 2)),
            ResolvedContractSegment("RB2701", date(2026, 9, 3), through),
        )

    def check_dependency(self, product, frequency, owner, as_of):
        raise MarketDataError(
            "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason="REPLAY_PREFIX_MISSING"
        )


class NoMetadataReader(AuditReader):
    def dependency_owners(self, product, since, through):
        raise MarketDataError("TRADING_CALENDAR_MISSING")


def test_collects_all_contract_frequency_failures_and_deduplicates_provenance():
    module = _audit_module()
    planned = []

    def plan(request):
        planned.append(request)
        return {
            "plan_sha256": "a" * 64,
            "expected_bar_count": 3,
            "provider_request_count": 1,
            "targets": [],
            "scope_diagnostics": (),
        }

    audit = module.NewowReadinessAudit(reader=AuditReader(), plan=plan)
    report = audit.run(
        module.ReadinessRequest(
            ("rb",), datetime(2026, 9, 4, 8, tzinfo=UTC), max_work=1000
        )
    )
    assert report["complete"] is True
    assert len(report["dependencies"]) == 6
    assert {row["contract"] for row in report["dependencies"]} == {"RB2609", "RB2701"}
    assert all(row["status"] == "DATA_UNAVAILABLE" for row in report["dependencies"])
    assert len(report["repair_targets"]) == len(planned) == 6
    assert {item["section"] for item in report["dependencies"][0]["consumers"]} >= {
        "chart",
        "auxiliary",
        "reference",
    }


def test_metadata_failure_keeps_unknown_counts_and_never_invokes_warmup():
    module = _audit_module()

    def forbidden(_request):
        raise AssertionError("metadata is not authoritative")

    report = module.NewowReadinessAudit(reader=NoMetadataReader(), plan=forbidden).run(
        module.ReadinessRequest(("rb",), datetime(2026, 9, 4, 8, tzinfo=UTC))
    )
    assert report["complete"] is False
    assert report["repair_targets"] == []
    assert report["metadata_proposals"]
    assert all(
        item["expected_bar_count"] is None for item in report["metadata_proposals"]
    )
    assert all(
        item["status"]
        == ("UNOPENED" if item["section"] == "explanation" else "UNKNOWN")
        for item in report["enumerations"]
    )


def test_budget_preserves_open_daily_weekly_cases_and_marks_deferred_scope_unopened():
    module = _audit_module()
    from app.market_data.operational_universe import load_active_products

    report = module.NewowReadinessAudit(reader=AuditReader()).run(
        module.ReadinessRequest(
            load_active_products(),
            datetime(2026, 9, 4, 8, tzinfo=UTC),
            matrix=True,
            max_work=1,
        )
    )
    assert len(report["cases"]) == 540
    assert report["complete"] is False
    assert report["budget_exhausted"] is True
    assert sum(item["main"]["status"] == "UNSTARTED" for item in report["cases"]) == 354
    assert sum(item["main"]["status"] == "UNOPENED" for item in report["cases"]) == 186


def test_weekly_scope_preserves_complete_planned_matrix_without_deferred_dependencies():
    module = _audit_module()
    from guiyi_quant.newow.product_contracts import ProductFrequency

    report = module.NewowReadinessAudit(reader=AuditReader()).run(
        module.ReadinessRequest(
            ("rb", "au"),
            datetime(2026, 9, 4, 8, tzinfo=UTC),
            matrix=True,
            frequencies=(ProductFrequency.WEEKLY,),
            max_work=1,
        )
    )

    assert len(report["cases"]) == 18
    assert {row["frequency"] for row in report["cases"]} == {"1w", "1d", "60m"}
    assert len(report["enumerations"]) == 8
    assert {row["frequency"] for row in report["enumerations"]} == {"1w"}
    assert report["frequency_scope"] == ["1w"]
    assert report["release_stage"] == "daily_weekly"
    assert all(
        row["status"] == "UNOPENED"
        for row in report["enumerations"]
        if row["section"] == "explanation"
    )
    assert all(
        consumer["section"] != "explanation"
        for dependency in report["dependencies"]
        for consumer in dependency["consumers"]
    )
    assert sum(item["main"]["status"] == "UNSTARTED" for item in report["cases"]) == 12
    assert sum(item["main"]["status"] == "UNOPENED" for item in report["cases"]) == 6


def test_candidate_weekly_scope_opens_the_versioned_60_products_only():
    module = _audit_module()
    from guiyi_quant.newow.product_contracts import ProductFrequency

    report = module.NewowReadinessAudit(reader=AuditReader()).run(
        module.ReadinessRequest(
            ("rb", "au"),
            datetime(2026, 9, 4, 8, tzinfo=UTC),
            matrix=True,
            frequencies=(ProductFrequency.WEEKLY,),
            max_work=1,
            candidate_weekly=True,
        )
    )
    weekly = [case for case in report["cases"] if case["frequency"] == "1w"]
    assert report["release_stage"] == "daily_weekly_candidate"
    assert weekly
    assert all(case["main"]["status"] != "UNOPENED" for case in weekly)

    with pytest.raises(ValueError, match="NEWOW_READINESS_ARGUMENT_INVALID"):
        module.ReadinessRequest(
            ("zz",),
            datetime(2026, 9, 4, 8, tzinfo=UTC),
            frequencies=(ProductFrequency.WEEKLY,),
            candidate_weekly=True,
        )


def test_remaining19_weekly_matrix_declares_v2_policy_per_combination():
    module = _audit_module()
    from guiyi_quant.newow.product_contracts import ProductFrequency

    report = module.NewowReadinessAudit(reader=AuditReader()).run(
        module.ReadinessRequest(
            ("b",),
            datetime(2026, 9, 4, 8, tzinfo=UTC),
            matrix=True,
            frequencies=(ProductFrequency.WEEKLY,),
            candidate_weekly=True,
            consumer_only=True,
            max_work=1,
        )
    )

    assert len(report["cases"]) == 3
    assert {
        case["input_quality_policy"] for case in report["cases"]
    } == {"newow_weekly_input_quality_v2"}


def test_daily_readonly_scope_and_public_daily_matrix_are_distinct():
    module = _audit_module()
    from guiyi_quant.newow.product_contracts import ProductFrequency

    audit = module.NewowReadinessAudit(
        reader=AuditReader(),
        plan=lambda _request: {
            "plan_sha256": "a" * 64,
            "expected_bar_count": 3,
            "provider_request_count": 1,
            "targets": [],
            "scope_diagnostics": (),
        },
    )
    report = audit.run(
        module.ReadinessRequest(
            ("rb", "au"),
            datetime(2026, 9, 4, 8, tzinfo=UTC),
            matrix=False,
            frequencies=(ProductFrequency.DAILY,),
            max_work=1000,
        )
    )

    assert report["complete"] is True
    assert report["frequency_scope"] == ["1d"]
    assert report["matrix"] is False
    assert report["cases"] == []
    assert {row["frequency"] for row in report["enumerations"]} == {"1d"}
    assert all(row["frequency"] == "1d" for row in report["dependencies"])

    public = module.NewowReadinessAudit(reader=AuditReader()).run(
        module.ReadinessRequest(
            ("rb",), datetime(2026, 9, 4, 8, tzinfo=UTC), matrix=True
        )
    )
    assert all(
        case["main"]["status"] != "UNOPENED"
        for case in public["cases"]
        if case["frequency"] == "1d"
    )


@pytest.mark.parametrize("frequency", ["1w", "1d"])
def test_single_frequency_matrix_respects_formal_daily_weekly_product_gate(frequency):
    module = _audit_module()
    from guiyi_quant.newow.product_contracts import ProductFrequency

    seen = []

    class Service:
        def query(self, request):
            seen.append(request.frequency.value)
            raise MarketDataError("CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason="REPLAY_PREFIX_MISSING")

    report = module.NewowReadinessAudit(
        reader=AuditReader(),
        service=Service(),
        plan=lambda _request: {
            "plan_sha256": "a" * 64,
            "expected_bar_count": 3,
            "provider_request_count": 1,
            "targets": [],
            "scope_diagnostics": (),
        },
    ).run(
        module.ReadinessRequest(
            ("rb",),
            datetime(2026, 9, 4, 8, tzinfo=UTC),
            matrix=True,
            frequencies=(ProductFrequency(frequency),),
            max_work=1000,
        )
    )

    assert report["frequency_scope"] == [frequency]
    assert report["complete"] is True
    assert set(seen) == {frequency}
    other = "1d" if frequency == "1w" else "1w"
    assert all(
        case["main"]["status"] == "UNSTARTED"
        for case in report["cases"]
        if case["frequency"] == other
    )


def test_formal_weekly_matrix_keeps_remaining_product_unopened():
    module = _audit_module()
    from guiyi_quant.newow.product_contracts import ProductFrequency

    report = module.NewowReadinessAudit(reader=AuditReader()).run(
        module.ReadinessRequest(
            ("sh",),
            datetime(2026, 9, 4, 8, tzinfo=UTC),
            matrix=True,
            frequencies=(ProductFrequency.WEEKLY,),
            max_work=1000,
        )
    )

    weekly = [case for case in report["cases"] if case["frequency"] == "1w"]
    assert len(weekly) == 3
    assert all(case["main"] == {
        "status": "UNOPENED", "reason": "NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"
    } for case in weekly)


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("SOURCE_NONPOSITIVE_PRICE", "SOURCE_EXCEPTION"),
        ("REPLAY_ENDPOINTS_EXTRA", "INTEGRITY_ERROR"),
    ],
)
def test_source_and_integrity_failures_are_not_blind_download_targets(reason, expected):
    module = _audit_module()

    class Reader(AuditReader):
        def check_dependency(self, *args):
            raise MarketDataError("CONTRACT_REPLAY_COVERAGE_UNAVAILABLE", reason=reason)

    def forbidden(_request):
        raise AssertionError("must not propose repeated downloads")

    report = module.NewowReadinessAudit(reader=Reader(), plan=forbidden).run(
        module.ReadinessRequest(("rb",), datetime(2026, 9, 4, 8, tzinfo=UTC))
    )
    assert all(item["status"] == expected for item in report["dependencies"])
    assert report["repair_targets"] == []


def test_verified_price_unavailable_is_a_known_interruption_not_unknown():
    module = _audit_module()

    class Reader(AuditReader):
        def check_dependency(self, *args):
            raise MarketDataError("PRICE_UNAVAILABLE")

    def forbidden(_request):
        raise AssertionError("proven source interruption must not become a download")

    report = module.NewowReadinessAudit(reader=Reader(), plan=forbidden).run(
        module.ReadinessRequest(("rb",), datetime(2026, 9, 4, 8, tzinfo=UTC))
    )

    assert all(row["status"] == "DATA_INTERRUPTED" for row in report["dependencies"])
    assert all(row["reason"] == "PRICE_UNAVAILABLE" for row in report["dependencies"])
    assert report["repair_targets"] == []


def test_matrix_preserves_section_evidence_states_and_fixed_asof():
    module = _audit_module()
    from guiyi_quant.newow.product_contracts import FeatureStatus
    from app.market_data.newow.product_service import SectionDelivery

    as_of = datetime(2026, 9, 4, 8, tzinfo=UTC)
    seen = []

    class Service:
        def query(self, request):
            seen.append((request.frequency.value, request.section.value, request.as_of))
            status = {
                "explanation": "evidence_required",
                "comparator": "not_applicable",
            }.get(request.section, "ready")
            return SimpleNamespace(
                **{
                    request.section: SectionDelivery(
                        "delivered",
                        FeatureStatus(
                            status,
                            "EVIDENCE_REQUIRED"
                            if status == "evidence_required"
                            else "ACTIVE_CODE_VERIFIED",
                            "TEST_EVIDENCE_BOUNDARY",
                        ),
                        None,
                    )
                }
            )

    report = module.NewowReadinessAudit(reader=AuditReader(), service=Service()).run(
        module.ReadinessRequest(("rb",), as_of, matrix=True)
    )
    assert len(report["cases"]) == 9
    assert report["main_ready_count"] == 6
    assert all(
        case["sections"]["explanation"]["status"] == "UNOPENED"
        for case in report["cases"]
    )
    assert all(
        case["sections"]["comparator"]["status"] == "NOT_APPLICABLE"
        for case in report["cases"]
        if case["frequency"] == "1d"
    )
    assert all(
        case["main"]["status"] == "UNOPENED"
        for case in report["cases"]
        if case["frequency"] == "60m"
    )
    assert {(frequency, section) for frequency, section, _ in seen} == {
        ("1d", "chart"),
        ("1d", "auxiliary"),
        ("1d", "reference"),
        ("1d", "comparator"),
        ("1w", "chart"),
        ("1w", "auxiliary"),
        ("1w", "reference"),
        ("1w", "comparator"),
    }
    assert {observed for _, _, observed in seen} == {as_of}


def test_deadline_discards_late_result_and_keeps_later_case_unstarted():
    module = _audit_module()
    clock = [0.0]
    owner_calls = []

    class LateReader(AuditReader):
        def resolve_chart_window(self, *args):
            clock[0] = 2.0
            return super().resolve_chart_window(*args)

        def dependency_owners(self, *args):
            owner_calls.append(args)
            raise AssertionError(
                "deadline must stop before another authority operation"
            )

    report = module.NewowReadinessAudit(
        reader=LateReader(), clock=lambda: clock[0]
    ).run(
        module.ReadinessRequest(
            ("rb",), datetime(2026, 9, 4, 8, tzinfo=UTC), matrix=True, timeout_seconds=1
        )
    )
    assert report["budget_exhausted"] is True
    assert report["dependencies"] == []
    assert owner_calls == []
    assert all(
        row["status"]
        == ("UNOPENED" if row["section"] == "explanation" else "UNSTARTED")
        for row in report["enumerations"]
    )


def test_real_reader_collects_two_missing_lifecycle_prefixes(product_cases):
    from app.market_data.domain import BarFrequency, ResolvedContractSegment
    from app.market_data.market_data_service import MarketDataService
    from types import MethodType

    module = _audit_module()
    reader, _query, source = product_cases.paged_reader(prefix_bars=6, frequency="1d")
    complete = source.expected_physical[("RB2605", BarFrequency.D1)]
    source.coverage.start = complete[0].trading_day
    source.segments = (
        ResolvedContractSegment(
            "RB2605", complete[0].trading_day, complete[2].trading_day
        ),
        ResolvedContractSegment(
            "RB2609", complete[3].trading_day, complete[-1].trading_day
        ),
    )
    for contract in ("RB2605", "RB2609"):
        source.expected_physical[(contract, BarFrequency.D1)] = complete
        source.physical[(contract, BarFrequency.D1)] = complete[1:]

    def expected(**kwargs):
        return tuple(
            (bar.bar_end, bar.trading_day)
            for bar in source.expected_physical[
                (kwargs["contract"], kwargs["frequency"])
            ]
            if bar.bar_end <= kwargs["cutoff"]
            and bar.trading_day <= kwargs["trading_day"]
        )

    source.expected_contract_replay_endpoints = expected
    source.validate_contract_replay_coverage = MethodType(
        MarketDataService.validate_contract_replay_coverage, source
    )
    report = module.NewowReadinessAudit(reader=reader).run(
        module.ReadinessRequest(("rb",), source.as_of)
    )
    daily = [item for item in report["dependencies"] if item["frequency"] == "1d"]
    assert {item["contract"] for item in daily} == {"RB2605", "RB2609"}
    assert {item["reason"] for item in daily} == {"REPLAY_PREFIX_MISSING"}
    assert source.actual_requests == []


def test_metadata_catalog_error_has_bounded_proposal_and_unknown_counts():
    from app.market_data.catalog import CatalogError

    module = _audit_module()

    class Reader(AuditReader):
        def dependency_owners(self, *args):
            raise CatalogError("CONTRACT_NOT_FOUND")

    report = module.NewowReadinessAudit(reader=Reader()).run(
        module.ReadinessRequest(("rb",), datetime(2026, 9, 4, 8, tzinfo=UTC))
    )
    assert report["metadata_proposals"]
    assert all(
        row["reason"] == "CONTRACT_METADATA_MISSING"
        for row in report["metadata_proposals"]
    )
    assert all(
        row["expected_bar_count"] is None for row in report["metadata_proposals"]
    )


def test_dependency_enumeration_rejects_wrong_contract_identity(product_cases):
    from dataclasses import replace

    reader, query, source = product_cases.paged_reader(prefix_bars=3, frequency="1d")
    source.segments = (replace(source.segments[0], contract="AU2701"),)
    with pytest.raises(ValueError):
        reader.dependency_owners(query.product, query.since, query.through)


def test_dependency_suffix_gap_uses_expected_day_not_last_persisted_day(product_cases):
    from app.market_data.domain import BarFrequency
    from app.market_data.market_data_service import MarketDataService
    from guiyi_quant.newow.product_contracts import ProductFrequency
    from types import MethodType

    reader, _query, source = product_cases.paged_reader(prefix_bars=3, frequency="1d")
    complete = source.physical[("RB2605", BarFrequency.D1)]
    source.physical[("RB2605", BarFrequency.D1)] = complete[:-1]
    source.expected_contract_replay_endpoints = lambda **kw: tuple(
        (bar.bar_end, bar.trading_day)
        for bar in complete
        if bar.bar_end <= kw["cutoff"] and bar.trading_day <= kw["trading_day"]
    )
    source.validate_contract_replay_coverage = MethodType(
        MarketDataService.validate_contract_replay_coverage, source
    )
    with pytest.raises(MarketDataError) as raised:
        reader.check_dependency(
            "rb", ProductFrequency.DAILY, source.segments[0], source.as_of
        )
    assert raised.value.reason == "REPLAY_ENDPOINTS_MISSING"


def test_global_owner_future_end_cannot_extend_dependency_or_repair_cutoff(
    product_cases,
):
    from dataclasses import replace
    from datetime import timedelta
    from app.market_data.domain import BarFrequency

    reader, _query, source = product_cases.paged_reader(prefix_bars=3, frequency="1d")
    module = _audit_module()
    through = source.coverage.through
    source.segments = (
        replace(source.segments[0], end_trading_day=through + timedelta(days=90)),
    )
    endpoints = []

    def expected(**kwargs):
        endpoints.append(kwargs)
        return tuple(
            (bar.bar_end, bar.trading_day)
            for bar in source.expected_physical[
                (kwargs["contract"], kwargs["frequency"])
            ]
            if bar.trading_day <= kwargs["trading_day"]
            and bar.bar_end <= kwargs["cutoff"]
        )

    source.expected_contract_replay_endpoints = expected
    source.failures["physical"] = MarketDataError("DATASET_OR_PARTITION_MISSING")
    planned = []

    def plan(request):
        planned.append(request)
        return {
            "expected_bar_count": 3,
            "provider_request_count": 1,
            "plan_sha256": "b" * 64,
        }

    report = module.NewowReadinessAudit(reader=reader, plan=plan).run(
        module.ReadinessRequest(("rb",), source.as_of)
    )
    assert endpoints and planned
    assert all(item["trading_day"] == through for item in endpoints)
    assert all(item.through == through for item in planned)
    assert all(
        item["through"] == through.isoformat() for item in report["dependencies"]
    )
    assert any(item.frequency == BarFrequency.D1 for item in planned)


def test_short_owner_without_completed_weekly_bar_is_not_a_download_gap(product_cases):
    from .test_product_reader import _weekly_reader
    from guiyi_quant.newow.product_contracts import ProductFrequency

    reader, _query, source = _weekly_reader(product_cases)
    source.expected_contract_replay_endpoints = lambda **kwargs: (
        (datetime(2023, 1, 6, 7, tzinfo=UTC), date(2023, 1, 6)),
    )
    result = reader.check_dependency(
        "rb", ProductFrequency.WEEKLY, source.segments[1], source.as_of
    )
    assert result == {
        "status": "NOT_APPLICABLE",
        "reason": "OWNER_HAS_NO_COMPLETED_BAR",
    }
    assert source.physical_page_requests == []


@pytest.mark.parametrize("frequency,companion", [("1w", "1d"), ("60m", "1m")])
@pytest.mark.parametrize(
    "reason", ["DATA_INTEGRITY_INVALID", "SOURCE_NONPOSITIVE_PRICE"]
)
def test_entire_planner_scope_cannot_reintroduce_excluded_companion(
    frequency, companion, reason
):
    module = _audit_module()

    def plan(request):
        return {
            "plan_sha256": "a" * 64,
            "expected_bar_count": 4,
            "provider_request_count": 2,
            "frequencies": (companion, frequency),
            "scope_diagnostics": (
                {
                    "dataset": ("contract", "rb", request.contract, companion),
                    "year": 2026,
                    "month": 9,
                    "reason_codes": (reason,),
                },
            ),
        }

    report = module.NewowReadinessAudit(reader=AuditReader(), plan=plan).run(
        module.ReadinessRequest(("rb",), datetime(2026, 9, 4, 8, tzinfo=UTC))
    )
    target = next(
        row for row in report["repair_targets"] if row["frequency"] == frequency
    )
    assert target["status"] == "REVIEW_REQUIRED"
    assert target["plan_sha256"] is None
    assert target["provider_request_count"] is None
    assert target["scope_diagnostics"][0]["reason_codes"] == (reason,)


def test_known_daily_integrity_cannot_be_hidden_by_weekly_missing_candidate():
    module = _audit_module()

    class Reader(AuditReader):
        def check_dependency(self, product, frequency, owner, as_of):
            if frequency == "1d":
                raise MarketDataError(
                    "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE",
                    reason="REPLAY_ENDPOINTS_EXTRA",
                )
            return super().check_dependency(product, frequency, owner, as_of)

    def plan(request):
        return {
            "plan_sha256": "a" * 64,
            "provider_request_count": 2,
            "scope_diagnostics": (),
            "frequencies": ("1d", "1w"),
        }

    report = module.NewowReadinessAudit(reader=Reader(), plan=plan).run(
        module.ReadinessRequest(("rb",), datetime(2026, 9, 4, 8, tzinfo=UTC))
    )
    weekly = [row for row in report["repair_targets"] if row["frequency"] == "1w"]
    assert weekly and all(row["status"] == "REVIEW_REQUIRED" for row in weekly)
    assert all(row["scope_conflicts"][0]["frequency"] == "1d" for row in weekly)


def test_repair_scope_coalesces_one_contract_to_latest_required_through():
    module = _audit_module()
    from app.market_data.domain import ResolvedContractSegment

    class Reader(AuditReader):
        def resolve_chart_window(self, product, frequency, limit, as_of):
            from app.market_data.newow.product_query import ProductReadWindow

            return ProductReadWindow(date(2026, 8, 1), date(2026, 8, 15))

        def resolve_performance_window(self, product, frequency, since, through, as_of):
            return SimpleNamespace(
                requested_since=date(2026, 8, 1),
                actual_through=date(2026, 9, 4),
                cutoff=as_of,
            )

        def dependency_owners(self, product, since, through):
            return (ResolvedContractSegment("RB2701", since, through),)

    planned = []

    def plan(request):
        planned.append(request)
        return {
            "plan_sha256": "a" * 64,
            "expected_bar_count": 3,
            "provider_request_count": 1,
            "frequencies": ("1d", "1w"),
            "scope_diagnostics": (),
        }

    report = module.NewowReadinessAudit(reader=Reader(), plan=plan).run(
        module.ReadinessRequest(
            ("rb",),
            datetime(2026, 9, 4, 8, tzinfo=UTC),
            frequencies=("1w",),
        )
    )

    assert len(planned) == len(report["repair_targets"]) == 1
    assert planned[0].through == date(2026, 9, 4)
    assert report["repair_targets"][0]["through"] == "2026-09-04"
    assert {item["section"] for item in report["repair_targets"][0]["consumers"]} == {
        "chart",
        "auxiliary",
        "reference",
    }


def test_consumer_only_matrix_skips_dependency_enumeration_and_keeps_all_sections():
    module = _audit_module()
    from app.market_data.newow.product_service import SectionDelivery
    from guiyi_quant.newow.product_contracts import FeatureStatus

    class Reader:
        def __getattr__(self, name):
            raise AssertionError(f"consumer-only audit must not call reader.{name}")

    class Service:
        def query(self, request):
            return SimpleNamespace(**{
                request.section: SectionDelivery(
                    "delivered",
                    FeatureStatus("ready", "ACTIVE_CODE_VERIFIED"),
                    None,
                )
            })

    report = module.NewowReadinessAudit(reader=Reader(), service=Service()).run(
        module.ReadinessRequest(
            ("rb",),
            datetime(2026, 9, 4, 8, tzinfo=UTC),
            matrix=True,
            frequencies=("1w",),
            candidate_weekly=True,
            consumer_only=True,
        )
    )

    assert report["complete"] is True
    assert report["enumerations"] == report["dependencies"] == []
    assert len(report["cases"]) == 3
    assert all(len(case["sections"]) == 7 for case in report["cases"])
    assert report["work_used"] == 21
