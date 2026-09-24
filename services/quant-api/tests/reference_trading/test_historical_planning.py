from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from guiyi_quant.reference_trading import StreamIdentity
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from guiyi_quant.newow.product_identity import (
    InputQualityPolicy,
    REFERENCE_MODEL_VERSION,
    futures_adaptation_version,
)

from app.reference_trading.inputs import (
    HistoricalInputBar, HistoricalInputSnapshot, MarketDataHistoricalInputReader,
)
from app.reference_trading.planning import (
    HistoricalReferencePlanner,
    HistoricalReferenceRequest,
    HistoricalStreamRequest,
    WorkBudget,
    plan_from_dict,
    plan_to_dict,
    request_from_dict,
)


NOW = datetime(2026, 9, 20, 8, tzinfo=UTC)


def _identity(*, strategy: str = "newow-trend", frequency: str = "1d") -> StreamIdentity:
    normalized = strategy.replace("-", "_").removeprefix("newow_")
    if normalized in {item.value for item in ProductStrategy} and frequency in {
        item.value for item in ProductFrequency
    }:
        product = build_product_identity(
            "rb", ProductStrategy(normalized), ProductFrequency(frequency),
        )
        formulas = product.formula_versions
        profile = product.profile_id
        reference_model = REFERENCE_MODEL_VERSION
        futures_version = futures_adaptation_version(frequency)
    else:
        formulas = ("formula-v1",)
        profile = "profile-v1"
        reference_model = "reference-v1"
        futures_version = "futures-v1"
    return StreamIdentity(
        strategy_code=strategy,
        formula_versions=formulas,
        profile_id=profile,
        reference_model_version=reference_model,
        futures_adaptation_version=futures_version,
        product="rb",
        frequency=frequency,
        series_kind="actual_dominant",
        recording_mode="historical_replay",
        observation_policy_version=None,
    )


def _stream(**kwargs) -> HistoricalStreamRequest:
    return HistoricalStreamRequest(
        identity=_identity(**kwargs),
        since=date(2026, 9, 1),
        through=date(2026, 9, 18),
        as_of=NOW,
    )


def _budget() -> WorkBudget:
    return WorkBudget(
        max_streams=2,
        max_input_bars=100,
        max_elapsed_seconds=30,
        max_input_bytes=100_000,
    )


class Reader:
    def __init__(self) -> None:
        self.calls: list[HistoricalStreamRequest] = []

    def plan_stream(self, request: HistoricalStreamRequest) -> HistoricalInputSnapshot:
        self.calls.append(request)
        bar = HistoricalInputBar(
            bar_end=datetime(2026, 9, 18, 7, tzinfo=UTC),
            trading_day=date(2026, 9, 18),
            physical_contract="RB2610",
            owner_segment_id="owner-1",
            calculation_segment_id="calc-1",
            reference_price=Decimal("3500"),
            fingerprint="a" * 64,
            payload={"close": "3500"},
        )
        return HistoricalInputSnapshot(
            stream=request.identity,
            storage_start=date(2026, 8, 1),
            completed_through=bar.bar_end,
            bars=(bar,),
            dependency_manifest={
                "dataset": {"revision": "fixture-v1", "sha256": "b" * 64},
                "calendar": "calendar-v1",
                "session": "session-v1",
                "rank1": [["RB2610", "2026-09-01", "2026-09-18"]],
                "quality": "quality-v1",
                "formula_versions": list(request.identity.formula_versions),
            },
            source_token="source-token-v1",
            input_bytes=128,
        )


class ExplodingRepository:
    def __getattr__(self, name):
        raise AssertionError(f"dry-run touched repository method {name}")


def test_plan_is_deterministic_and_does_not_mutate_repository() -> None:
    reader = Reader()
    planner = HistoricalReferencePlanner(reader, repository=ExplodingRepository(), now=lambda: NOW)
    request = HistoricalReferenceRequest("build", (_stream(),), _budget(), batch_size=64)

    first = planner.plan(request)
    second = planner.plan(request)

    assert first == second
    assert first.plan_hash == second.plan_hash
    assert len(first.streams) == 1
    assert first.streams[0].dependency_digest == first.streams[0].input_manifest_sha256
    assert first.streams[0].target_completed_through == datetime(2026, 9, 18, 7, tzinfo=UTC)
    assert len(reader.calls) == 2


def test_plan_accepts_formal_weekly_v2_identity_and_rejects_v1_alias() -> None:
    product = build_product_identity(
        "b", ProductStrategy.TREND, ProductFrequency.WEEKLY,
        input_quality_policy=InputQualityPolicy.WEEKLY_V2,
    )
    base = _identity(strategy="newow_trend", frequency="1w")
    formal = replace(
        base, product="b", formula_versions=product.formula_versions,
        profile_id=product.profile_id,
        futures_adaptation_version=futures_adaptation_version(
            "1w", InputQualityPolicy.WEEKLY_V2,
        ),
    )
    planner = HistoricalReferencePlanner(Reader(), now=lambda: NOW)
    request = HistoricalStreamRequest(formal, date(2026, 9, 1), date(2026, 9, 18), NOW)
    assert planner.plan(HistoricalReferenceRequest("build", (request,), _budget())).streams[0].request == request
    with pytest.raises(ValueError, match="REFERENCE_IDENTITY_VERSION_UNSUPPORTED"):
        planner.plan(HistoricalReferenceRequest(
            "build", (replace(request, identity=replace(
                formal, futures_adaptation_version=futures_adaptation_version("1w"),
            )),), _budget(),
        ))


def test_historical_input_estimate_selects_reader_by_formal_identity() -> None:
    product = build_product_identity(
        "b", ProductStrategy.TREND, ProductFrequency.WEEKLY,
        input_quality_policy=InputQualityPolicy.WEEKLY_V2,
    )
    identity = replace(
        _identity(strategy="newow_trend", frequency="1w"),
        product="b", formula_versions=product.formula_versions,
        profile_id=product.profile_id,
        futures_adaptation_version=futures_adaptation_version(
            "1w", InputQualityPolicy.WEEKLY_V2,
        ),
    )
    seen = []

    class Bound:
        def historical_input_bound(self, **kwargs):
            seen.append(kwargs)
            return 42, 4096

    reader = MarketDataHistoricalInputReader(
        newow_reader=object(), subing_service=object(),
        newow_reader_for_identity=lambda selected: Bound() if selected == identity else None,
    )
    request = HistoricalStreamRequest(identity, date(2026, 9, 1), date(2026, 9, 18), NOW)
    assert reader.estimate_stream(request) == (42, 4096)
    assert seen == [{
        "product": "b", "frequency": "1w", "since": request.since,
        "through": request.through, "as_of": request.as_of,
    }]


@pytest.mark.parametrize(
    ("strategy", "frequency"),
    [
        ("newow-trend", "15m"),
        ("newow-oscillation", "30m"),
        ("newow-main-rise", "5m"),
        ("subing-reference", "1w"),
        ("htdy-first-seen", "1d"),
    ],
)
def test_plan_rejects_unsupported_strategy_frequency_before_read(
    strategy: str, frequency: str,
) -> None:
    reader = Reader()
    planner = HistoricalReferencePlanner(reader, now=lambda: NOW)
    with pytest.raises(ValueError, match="REFERENCE_CAPABILITY_UNSUPPORTED"):
        planner.plan(HistoricalReferenceRequest(
            "build", (_stream(strategy=strategy, frequency=frequency),), _budget(),
        ))
    assert reader.calls == []


def test_request_rejects_duplicate_streams_future_as_of_and_boolean_budget() -> None:
    stream = _stream()
    with pytest.raises(ValueError, match="duplicate"):
        HistoricalReferenceRequest("build", (stream, stream), _budget())
    with pytest.raises(ValueError, match="positive integer"):
        replace(_budget(), max_input_bars=True)
    future = replace(stream, as_of=datetime(2026, 9, 21, tzinfo=UTC))
    with pytest.raises(ValueError, match="REFERENCE_AS_OF_IN_FUTURE"):
        HistoricalReferencePlanner(Reader(), now=lambda: NOW).plan(
            HistoricalReferenceRequest("build", (future,), _budget())
        )


def test_plan_rejects_missing_complete_input_and_budget_overrun() -> None:
    class Empty(Reader):
        def plan_stream(self, request):
            result = super().plan_stream(request)
            return replace(result, bars=(), completed_through=None)

    with pytest.raises(ValueError, match="REFERENCE_INPUT_INCOMPLETE"):
        HistoricalReferencePlanner(Empty(), now=lambda: NOW).plan(
            HistoricalReferenceRequest("build", (_stream(),), _budget())
        )

    tiny = replace(_budget(), max_input_bytes=1)
    with pytest.raises(ValueError, match="REFERENCE_BUDGET_EXCEEDED"):
        HistoricalReferencePlanner(Reader(), now=lambda: NOW).plan(
            HistoricalReferenceRequest("build", (_stream(),), tiny)
        )


def test_plan_rejects_estimated_overrun_before_materializing_input() -> None:
    class BoundedReader(Reader):
        def estimate_stream(self, request):
            return 101, 1

    reader = BoundedReader()

    with pytest.raises(ValueError, match="REFERENCE_BUDGET_EXCEEDED"):
        HistoricalReferencePlanner(reader, now=lambda: NOW).plan(
            HistoricalReferenceRequest("build", (_stream(),), _budget())
        )

    assert reader.calls == []


def test_plan_elapsed_budget_includes_input_materialization() -> None:
    times = iter((0.0, 0.0, 31.0))
    planner = HistoricalReferencePlanner(
        Reader(), now=lambda: NOW, monotonic_clock=lambda: next(times),
    )

    with pytest.raises(ValueError, match="REFERENCE_BUDGET_EXCEEDED"):
        planner.plan(HistoricalReferenceRequest(
            "build", (_stream(),), _budget(),
        ))


def test_plan_rejects_unknown_formula_or_model_version_before_read() -> None:
    reader = Reader()
    invalid = replace(
        _stream(),
        identity=replace(_stream().identity, reference_model_version="unknown-v99"),
    )

    with pytest.raises(ValueError, match="REFERENCE_IDENTITY_VERSION_UNSUPPORTED"):
        HistoricalReferencePlanner(reader, now=lambda: NOW).plan(
            HistoricalReferenceRequest("build", (invalid,), _budget())
        )
    assert reader.calls == []


def test_plan_json_roundtrip_is_strict_and_rejects_boolean_integer() -> None:
    plan = HistoricalReferencePlanner(Reader(), now=lambda: NOW).plan(
        HistoricalReferenceRequest("build", (_stream(),), _budget())
    )
    payload = plan_to_dict(plan)

    assert plan_from_dict(payload) == plan

    payload["streams"][0]["input_count"] = True
    with pytest.raises(ValueError, match="REFERENCE_PLAN_INVALID"):
        plan_from_dict(payload)


def test_request_json_rejects_non_text_dates_without_leaking_type_errors() -> None:
    stream = _stream()
    identity = {
        "strategy_code": stream.identity.strategy_code,
        "formula_versions": list(stream.identity.formula_versions),
        "profile_id": stream.identity.profile_id,
        "reference_model_version": stream.identity.reference_model_version,
        "futures_adaptation_version": stream.identity.futures_adaptation_version,
        "product": stream.identity.product,
        "frequency": stream.identity.frequency,
        "series_kind": stream.identity.series_kind,
        "recording_mode": stream.identity.recording_mode.value,
        "observation_policy_version": None,
    }
    payload = {
        "operation": "build",
        "streams": [{"identity": identity, "since": True, "through": "2026-09-18", "as_of": NOW.isoformat()}],
        "budget": {
            "max_streams": 1,
            "max_input_bars": 1,
            "max_elapsed_seconds": 1,
            "max_input_bytes": 1,
        },
        "batch_size": 1,
    }

    with pytest.raises(ValueError, match="REFERENCE_REQUEST_INVALID"):
        request_from_dict(payload)
