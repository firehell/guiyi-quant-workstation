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
        "explanation",
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
    assert all(item["status"] == "UNKNOWN" for item in report["enumerations"])


def test_budget_preserves_all_540_main_cases_as_unstarted():
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
    assert all(item["main"]["status"] == "UNSTARTED" for item in report["cases"])


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


def test_matrix_preserves_section_evidence_states_and_fixed_asof():
    module = _audit_module()
    from guiyi_quant.newow.product_contracts import FeatureStatus
    from app.market_data.newow.product_service import SectionDelivery

    as_of = datetime(2026, 9, 4, 8, tzinfo=UTC)
    seen = []

    class Service:
        def query(self, request):
            seen.append(request.as_of)
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
    assert len(report["cases"]) == report["main_ready_count"] == 9
    assert all(
        case["sections"]["explanation"]["status"] == "EVIDENCE_REQUIRED"
        for case in report["cases"]
    )
    assert all(
        case["sections"]["comparator"]["status"] == "NOT_APPLICABLE"
        for case in report["cases"]
    )
    assert set(seen) == {as_of}


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
    assert all(row["status"] == "UNSTARTED" for row in report["enumerations"])


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
