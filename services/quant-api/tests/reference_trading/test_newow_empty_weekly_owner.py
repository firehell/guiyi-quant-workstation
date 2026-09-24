"""A short rank-1 owner with no completed W1 bar cannot own a trade."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.planning import HistoricalStreamRequest
from app.reference_trading.service import _advance_batch, _seed_checkpoint
from guiyi_quant.newow.product_adapters import (
    build_product_identity, replay_step, seed_replay_state,
)
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import (
    DataInterruption, ProductBar, ProductFrequency, ProductStrategy,
)
from guiyi_quant.newow.product_identity import (
    InputQualityPolicy, REFERENCE_MODEL_VERSION, build_calculation_segment_id,
    futures_adaptation_version,
)
from guiyi_quant.reference_trading import RecordingMode, StreamIdentity


def _request(
    policy: InputQualityPolicy = InputQualityPolicy.V1,
) -> HistoricalStreamRequest:
    product = build_product_identity(
        "rb", ProductStrategy.TREND, ProductFrequency.WEEKLY,
        input_quality_policy=policy,
    )
    stream = StreamIdentity(
        "newow_trend", product.formula_versions, product.profile_id,
        REFERENCE_MODEL_VERSION, futures_adaptation_version("1w", policy),
        "rb", "1w", "actual_dominant", RecordingMode.HISTORICAL_REPLAY, None,
    )
    return HistoricalStreamRequest(
        stream, date(2026, 1, 1), date(2026, 1, 31),
        datetime(2026, 2, 1, tzinfo=UTC),
    )


def _read_set(
    *, missing_kind: str = "rollover",
    policy: InputQualityPolicy = InputQualityPolicy.V1,
) -> SimpleNamespace:
    first_segment = "rb:RB2605:2026-01-05T01:00:00+00:00"
    empty_segment = "rb:RB2610:2026-01-12T01:00:00+00:00"
    bar_end = datetime(2026, 1, 9, 7, tzinfo=UTC)
    replay_bar = _bar(
        "RB2605", first_segment, bar_end, Decimal("100"), True, "a",
    )
    boundaries = (
        SimpleNamespace(
            old_contract="RB2605", old_segment_id=first_segment,
            effective_at=datetime(2026, 1, 10, 7, tzinfo=UTC),
            effective_trading_day=date(2026, 1, 10),
        ),
    )
    empty_boundary = SimpleNamespace(
        old_contract="RB2610", old_segment_id=empty_segment,
        effective_at=datetime(2026, 1, 14, 7, tzinfo=UTC),
        effective_trading_day=date(2026, 1, 14),
    )
    gaps = ()
    if missing_kind == "rollover":
        boundaries += (empty_boundary,)
    else:
        gaps = (DataInterruption(
            "rb", ProductFrequency.WEEKLY, "RB2610", empty_segment,
            empty_boundary.effective_trading_day, empty_boundary.effective_at,
            "quality:test",
        ),)
    return SimpleNamespace(
        replay_bars=(replay_bar,), boundaries=boundaries,
        data_interruptions=gaps, lifecycle_evidence=(),
        input_quality_policy=policy,
        owners=(
            SimpleNamespace(contract="RB2605", start_trading_day=date(2026, 1, 5),
                            end_trading_day=date(2026, 1, 9)),
            SimpleNamespace(contract="RB2610", start_trading_day=date(2026, 1, 12),
                            end_trading_day=date(
                                2026, 1, 31 if missing_kind == "quality" else 14,
                            )),
        ),
        sources={ProductFrequency.WEEKLY: SimpleNamespace(
            source_identity="canonical:test", input_policy_version="v1",
        )},
    )


def _bar(
    contract: str, segment: str, end: datetime, price: Decimal,
    eligible: bool, source_letter: str,
) -> ProductBar:
    return ProductBar(
        NewowDailyBar(
            "rb", contract, segment, end.date(), end,
            price, price, price, price, 1, 1,
            "canonical:test", eligible, True,
        ),
        ProductFrequency.WEEKLY,
        source_bar_sha256=source_letter * 64,
    )


class _Reader:
    def __init__(self, read_set: SimpleNamespace) -> None:
        self.read_set = read_set

    def load(self, _query, _as_of):
        return self.read_set

    def historical_metadata_evidence(self, **_kwargs):
        return {"source": "test"}

    def historical_input_bound(self, **_kwargs):
        return 2, 1024


def test_empty_weekly_owner_rollover_is_evidence_without_replay_event() -> None:
    source = _read_set()
    snapshot = MarketDataHistoricalInputReader(
        newow_reader=_Reader(source), subing_service=None,
    ).plan_stream(_request())

    assert len(source.boundaries) == 2
    assert len(snapshot.dependency_manifest["boundaries"]) == 2
    assert [bar.physical_contract for bar in snapshot.bars] == ["RB2605", "RB2605"]
    assert snapshot.bars[1].strategy_input is False
    assert snapshot.bars[1].boundaries[0].physical_contract == "RB2605"


def test_quality_boundary_before_any_eligible_owner_bar_keeps_source_evidence() -> None:
    source = _read_set(missing_kind="quality")
    snapshot = MarketDataHistoricalInputReader(
        newow_reader=_Reader(source), subing_service=None,
    ).plan_stream(_request())
    assert len(snapshot.dependency_manifest["data_interruptions"]) == 1
    assert all(
        not any(boundary.physical_contract == "RB2610" for boundary in bar.boundaries)
        for bar in snapshot.bars
    )

    changed = _read_set(missing_kind="quality")
    changed.data_interruptions = (DataInterruption(
        "rb", ProductFrequency.WEEKLY, "RB2610",
        "rb:RB2610:2026-01-12T01:00:00+00:00",
        date(2026, 1, 15), datetime(2026, 1, 15, 7, tzinfo=UTC),
        "quality:test",
    ),)
    changed_snapshot = MarketDataHistoricalInputReader(
        newow_reader=_Reader(changed), subing_service=None,
    ).plan_stream(_request())
    assert snapshot.source_token != changed_snapshot.source_token


def test_quality_boundary_before_first_eligible_bar_keeps_later_replay() -> None:
    source = _read_set(missing_kind="quality", policy=InputQualityPolicy.WEEKLY_V2)
    warmup = _bar(
        "RB2610", "rb:RB2610:2026-01-12T01:00:00+00:00",
        datetime(2026, 1, 9, 7, tzinfo=UTC), Decimal("105"), False, "c",
    )
    later = _bar(
        "RB2610", "rb:RB2610:2026-01-12T01:00:00+00:00",
        datetime(2026, 1, 16, 7, tzinfo=UTC), Decimal("110"), True, "b",
    )
    source.replay_bars += (warmup, later)
    snapshot = MarketDataHistoricalInputReader(
        newow_reader=_Reader(source), subing_service=None,
    ).plan_stream(_request(InputQualityPolicy.WEEKLY_V2))
    assert len(snapshot.dependency_manifest["data_interruptions"]) == 1
    assert snapshot.bars[-1].bar_end == later.bar.bar_end
    assert snapshot.bars[-1].calculation_segment_id == build_calculation_segment_id(
        later.bar.segment_id, source.data_interruptions[0].effective_at,
        InputQualityPolicy.WEEKLY_V2,
    )
    assert snapshot.bars[-1].payload.bar.calculation_segment_id == (
        snapshot.bars[-1].calculation_segment_id
    )
    checkpoint, _schema = _seed_checkpoint(snapshot.stream)
    checkpoint, _sources, _transitions, _schema = _advance_batch(
        snapshot.stream, checkpoint, snapshot.bars,
    )
    expected_state, _frame, _diagnostics = replay_step(
        snapshot.bars[-1].payload.identity,
        seed_replay_state(), snapshot.bars[-1].payload.bar,
    )
    assert checkpoint.strategy_state.calculation_segment_id == (
        expected_state.calculation_segment_id
    )
    assert checkpoint.strategy_state.trend_state == expected_state.trend_state
    assert checkpoint.strategy_state.escape_state == expected_state.escape_state
    assert checkpoint.strategy_state.pairing == expected_state.pairing
    assert checkpoint.reference_state.open_trade is None
    assert all(
        not any(boundary.physical_contract == "RB2610" for boundary in bar.boundaries)
        for bar in snapshot.bars
    )


def test_quality_boundary_after_eligible_bar_is_replayed() -> None:
    source = _read_set(missing_kind="quality")
    before = _bar(
        "RB2610", "rb:RB2610:2026-01-12T01:00:00+00:00",
        datetime(2026, 1, 13, 7, tzinfo=UTC), Decimal("105"), True, "b",
    )
    source.replay_bars += (before,)
    snapshot = MarketDataHistoricalInputReader(
        newow_reader=_Reader(source), subing_service=None,
    ).plan_stream(_request())
    assert len(snapshot.dependency_manifest["data_interruptions"]) == 1
    assert any(
        boundary.physical_contract == "RB2610"
        for bar in snapshot.bars for boundary in bar.boundaries
    )


def test_inconsistent_rollover_before_later_eligible_weekly_bar_fails_closed() -> None:
    source = _read_set()
    later = _bar(
        "RB2610", "rb:RB2610:2026-01-12T01:00:00+00:00",
        datetime(2026, 1, 16, 7, tzinfo=UTC), Decimal("110"), True, "b",
    )
    source.replay_bars += (later,)
    with pytest.raises(ValueError, match="REFERENCE_BOUNDARY_CONTEXT_MISSING"):
        MarketDataHistoricalInputReader(
            newow_reader=_Reader(source), subing_service=None,
        ).plan_stream(_request())


def test_newow_reader_factory_uses_stream_identity_for_bound_and_replay() -> None:
    selected = []
    policy = InputQualityPolicy.WEEKLY_V2
    request = _request(policy)

    def factory(identity):
        selected.append(identity.stream_id)
        return _Reader(_read_set(policy=policy))

    reader = MarketDataHistoricalInputReader(
        newow_reader=factory, subing_service=None,
    )
    assert reader.estimate_stream(request) == (2, 1024)
    assert reader.plan_stream(request).dependency_manifest["quality_policy"] == policy.value
    assert selected == [request.identity.stream_id, request.identity.stream_id]


def test_warmup_only_owner_does_not_anchor_rollover() -> None:
    source = _read_set()
    warmup = _bar(
        "RB2610", "rb:RB2610:2026-01-12T01:00:00+00:00",
        datetime(2026, 1, 9, 7, tzinfo=UTC), Decimal("105"), False, "b",
    )
    source.replay_bars += (warmup,)
    snapshot = MarketDataHistoricalInputReader(
        newow_reader=_Reader(source), subing_service=None,
    ).plan_stream(_request())
    assert len(snapshot.dependency_manifest["boundaries"]) == 2
    assert all(
        not any(boundary.physical_contract == "RB2610" for boundary in bar.boundaries)
        for bar in snapshot.bars
    )


def test_weekly_input_rejects_mismatched_adaptation() -> None:
    source = _read_set(policy=InputQualityPolicy.WEEKLY_V2)
    with pytest.raises(ValueError, match="REFERENCE_INPUT_IDENTITY_CONFLICT"):
        MarketDataHistoricalInputReader(
            newow_reader=_Reader(source), subing_service=None,
        ).plan_stream(_request())
