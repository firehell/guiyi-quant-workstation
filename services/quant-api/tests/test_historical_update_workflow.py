"""Tests for HistoricalUpdateWorkflow orchestration contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from app.data_core.catalog import CanonicalMainContractMapping
from app.data_core.contracts import BarFrequency
from app.services.data_operations.composition import build_apply_deps
from app.services.data_operations.contracts import (
    CommandResult,
    CommandStatus,
    DownloadRequest,
    EffectSummary,
    HistoricalUpdateRequest,
    MetadataSyncRequest,
    MetadataSyncScope,
    PublicError,
    ResultSchemaVersion,
    TargetResult,
    empty_effects,
)
from app.services.data_operations.historical_update import (
    HistoricalUpdateAbort,
    HistoricalUpdateWorkflow,
)
from app.services.data_operations.target_planner import (
    HistoricalUpdatePlan,
    HistoricalUpdateTargetPlanner,
    PlannedProductWindow,
    build_identity_targets,
    derive_aggregate_targets,
)


def _mapping() -> CanonicalMainContractMapping:
    return CanonicalMainContractMapping(
        id=1,
        symbol="jm",
        trading_day=date(2026, 8, 3),
        actual_contract="JM2609",
        data_version="v",
        created_at=None,
    )


def _plan(*, apply: bool) -> HistoricalUpdatePlan:
    start = datetime(2026, 8, 3, tzinfo=UTC)
    end = datetime(2026, 8, 4, tzinfo=UTC)
    direct = build_identity_targets(
        products=("jm",),
        mappings=(_mapping(),),
        start=start,
        end=end,
        weekly_end_day=date(2026, 8, 2),
    )
    return HistoricalUpdatePlan(
        request=HistoricalUpdateRequest(
            products=("jm",), through=date(2026, 8, 3), apply=apply
        ),
        products=("jm",),
        windows=(
            PlannedProductWindow(
                symbol="jm",
                since_day=date(2026, 8, 3),
                through_day=date(2026, 8, 3),
                start=start,
                end=end,
                weekly_end_day=date(2026, 8, 2),
            ),
        ),
        direct_targets=direct,
        aggregate_targets=derive_aggregate_targets(direct),
        apply=apply,
    )


def test_dry_run_has_no_mutation_effects_and_schema_v1() -> None:
    planner = HistoricalUpdateTargetPlanner(
        list_mappings=lambda *_a: (_mapping(),),
        covered_windows=lambda _probe: (),
        latest_completed_day=lambda _s: date(2026, 8, 3),
    )
    constructed: list[str] = []

    def factory():
        constructed.append("apply-deps")
        raise AssertionError("dry-run must not build apply deps")

    workflow = HistoricalUpdateWorkflow(planner=planner, apply_deps_factory=factory)
    result = workflow.run(
        HistoricalUpdateRequest(
            products=("jm",),
            since=date(2026, 8, 3),
            through=date(2026, 8, 3),
            apply=False,
        )
    )
    assert constructed == []
    assert result.schema_version == ResultSchemaVersion
    assert result.readonly is True
    assert result.effects == empty_effects()
    assert result.schema_version == 2
    assert result.effects.as_payload()["writes_provider_raw"] is False
    assert "plan_summary" in result.extras
    assert "direct_targets" not in result.extras
    assert result.status is CommandStatus.PLANNED


def test_update_request_rejects_empty_duplicate_and_inverted_products_or_dates() -> None:
    with pytest.raises(ValueError):
        HistoricalUpdateRequest(products=())
    with pytest.raises(ValueError):
        HistoricalUpdateRequest(products=("jm", "JM"))
    with pytest.raises(ValueError):
        HistoricalUpdateRequest(
            products=("jm",),
            since=date(2026, 8, 4),
            through=date(2026, 8, 3),
        )


def test_apply_noop_reports_all_write_effects_false() -> None:
    class FakeDownload:
        def run(self, request: DownloadRequest) -> CommandResult:
            raise AssertionError("noop must not download")

    class FakeAggregate:
        def run(self, request: object) -> CommandResult:
            raise AssertionError("noop must not aggregate")

    workflow = HistoricalUpdateWorkflow(
        planner=HistoricalUpdateTargetPlanner(
            list_mappings=lambda *_a: (_mapping(),),
            covered_windows=lambda _probe: (
                (
                    datetime(2020, 1, 1, tzinfo=UTC),
                    datetime(2030, 1, 1, tzinfo=UTC),
                ),
            ),
            latest_completed_day=lambda _s: date(2026, 8, 3),
        ),
        apply_deps_factory=lambda: build_apply_deps(
            download=FakeDownload(),  # type: ignore[arg-type]
            aggregate=FakeAggregate(),  # type: ignore[arg-type]
        ),
    )
    result = workflow.run(
        HistoricalUpdateRequest(products=("jm",), through=date(2026, 8, 3), apply=True)
    )
    assert result.status is CommandStatus.PASSED
    assert result.effects == empty_effects()
    assert result.extras["publication_count"] == 0


def test_direct_1m_failure_blocks_only_matching_aggregate() -> None:
    plan = _plan(apply=True)

    class FakeDownload:
        def run(self, request: DownloadRequest) -> CommandResult:
            fixed: list[TargetResult] = []
            for target in request.targets:
                if target.frequency is BarFrequency.M1:
                    fixed.append(
                        TargetResult(
                            target=target,
                            status=CommandStatus.ERROR,
                            error=PublicError(code="DOWNLOAD_FAILED", type="Err"),
                        )
                    )
                else:
                    fixed.append(
                        TargetResult(
                            target=target,
                            status=CommandStatus.PASSED,
                            detail={
                                "published_windows": [
                                    {"start": "a", "end": "b"},
                                ]
                            },
                        )
                    )
            return CommandResult(
                command="data.download",
                status=CommandStatus.PARTIAL,
                readonly=False,
                effects=EffectSummary(
                    calls_rqdata=True,
                    writes_staging=True,
                    writes_canonical=True,
                    writes_postgresql=True,
                ),
                targets=tuple(fixed),
            )

    class FakeAggregate:
        def run(self, request: object) -> CommandResult:
            assert getattr(request, "targets") == ()
            return CommandResult(
                command="data.aggregate",
                status=CommandStatus.PASSED,
                readonly=False,
                effects=empty_effects(),
                targets=(),
            )

    workflow = HistoricalUpdateWorkflow(
        planner=HistoricalUpdateTargetPlanner(list_mappings=lambda *_a: (_mapping(),)),
        apply_deps_factory=lambda: build_apply_deps(
            download=FakeDownload(),  # type: ignore[arg-type]
            aggregate=FakeAggregate(),  # type: ignore[arg-type]
        ),
    )
    result = workflow.execute(plan)
    blocked = [item for item in result.targets if item.status is CommandStatus.BLOCKED]
    assert blocked
    assert all(item.target.frequency is not BarFrequency.M1 for item in blocked)
    assert result.extras["blocked_count"] == len(blocked)


def test_global_composition_error_stops_immediately() -> None:
    workflow = HistoricalUpdateWorkflow(
        planner=HistoricalUpdateTargetPlanner(
            list_mappings=lambda *_a: (_mapping(),),
            latest_completed_day=lambda _s: date(2026, 8, 3),
        ),
        apply_deps_factory=lambda: (_ for _ in ()).throw(
            HistoricalUpdateAbort("PUBLISHER_SCHEMA_INVALID")
        ),
    )
    result = workflow.run(
        HistoricalUpdateRequest(
            products=("jm",),
            since=date(2026, 8, 3),
            through=date(2026, 8, 3),
            apply=True,
        )
    )
    assert result.status is CommandStatus.ERROR
    assert result.error is not None
    assert result.error.code == "PUBLISHER_SCHEMA_INVALID"
    assert result.effects == empty_effects()


def test_apply_runs_global_metadata_then_replans_before_direct_publish() -> None:
    request = HistoricalUpdateRequest(
        products=("jm",),
        since=date(2026, 8, 3),
        through=date(2026, 8, 3),
        apply=True,
    )
    initial = replace(_plan(apply=True), request=request)
    refreshed_target = replace(
        initial.direct_targets[0],
        contract_or_series="JM2610",
    )
    refreshed = replace(
        initial,
        direct_targets=(refreshed_target,),
        aggregate_targets=(),
    )
    planner_calls: list[HistoricalUpdateRequest] = []

    class Planner:
        def plan(self, received: HistoricalUpdateRequest) -> HistoricalUpdatePlan:
            planner_calls.append(received)
            return initial if len(planner_calls) == 1 else refreshed

    scopes: list[MetadataSyncScope] = []

    class Metadata:
        def run(self, received: MetadataSyncRequest) -> CommandResult:
            scopes.append(received.scope)
            return CommandResult(
                command="data.sync",
                status=CommandStatus.PASSED,
                readonly=False,
                effects=empty_effects(),
            )

    downloaded: list[DataTarget] = []

    class Download:
        def run(self, received: DownloadRequest) -> CommandResult:
            downloaded.extend(received.targets)
            return CommandResult(
                command="data.download",
                status=CommandStatus.PASSED,
                readonly=False,
                effects=EffectSummary(
                    calls_rqdata=True,
                    writes_provider_raw=True,
                    writes_staging=True,
                    writes_canonical=True,
                    writes_postgresql=True,
                    writes_historical_active=True,
                ),
                targets=(
                    TargetResult(
                        target=refreshed_target,
                        status=CommandStatus.PASSED,
                        detail={"published_windows": [{"start": "a", "end": "b"}]},
                    ),
                ),
            )

    class Aggregate:
        def run(self, _received: object) -> CommandResult:
            raise AssertionError("no aggregate target in this fixture")

    workflow = HistoricalUpdateWorkflow(
        planner=Planner(),  # type: ignore[arg-type]
        apply_deps_factory=lambda: build_apply_deps(
            download=Download(),  # type: ignore[arg-type]
            aggregate=Aggregate(),  # type: ignore[arg-type]
            metadata=Metadata(),  # type: ignore[arg-type]
        ),
    )

    result = workflow.run(request)

    assert result.status is CommandStatus.PASSED
    assert planner_calls == [request, request]
    assert scopes == [
        MetadataSyncScope.CALENDAR,
        MetadataSyncScope.SESSIONS,
        MetadataSyncScope.MAIN_CONTRACT_MAP,
    ]
    assert downloaded == [refreshed_target]
