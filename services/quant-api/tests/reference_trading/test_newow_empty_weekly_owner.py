"""A short rank-1 owner with no completed W1 bar cannot own a trade."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.planning import HistoricalStreamRequest
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from guiyi_quant.newow.product_identity import (
    InputQualityPolicy, REFERENCE_MODEL_VERSION, futures_adaptation_version,
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
    replay_bar = SimpleNamespace(
        bar=SimpleNamespace(
            bar_end=bar_end, trading_day=date(2026, 1, 9),
            physical_contract="RB2605", segment_id=first_segment,
            close=Decimal("100"), observation_eligible=True,
        ),
        calculation_segment_id=first_segment,
        source_bar_sha256="a" * 64,
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
        gaps = (SimpleNamespace(
            physical_contract="RB2610", segment_id=empty_segment,
            effective_at=empty_boundary.effective_at,
            trading_day=empty_boundary.effective_trading_day,
        ),)
    return SimpleNamespace(
        replay_bars=(replay_bar,), boundaries=boundaries,
        data_interruptions=gaps, lifecycle_evidence=(),
        input_quality_policy=policy,
        owners=(
            SimpleNamespace(contract="RB2605", start_trading_day=date(2026, 1, 5),
                            end_trading_day=date(2026, 1, 9)),
            SimpleNamespace(contract="RB2610", start_trading_day=date(2026, 1, 12),
                            end_trading_day=date(2026, 1, 14)),
        ),
        sources={ProductFrequency.WEEKLY: SimpleNamespace(
            source_identity="canonical:test", input_policy_version="v1",
        )},
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


def test_empty_owner_quality_boundary_still_fails_closed() -> None:
    source = _read_set(missing_kind="quality")
    with pytest.raises(ValueError, match="REFERENCE_BOUNDARY_CONTEXT_MISSING"):
        MarketDataHistoricalInputReader(
            newow_reader=_Reader(source), subing_service=None,
        ).plan_stream(_request())


def test_rollover_before_first_weekly_bar_still_fails_closed() -> None:
    source = _read_set()
    later = SimpleNamespace(
        bar=SimpleNamespace(
            bar_end=datetime(2026, 1, 16, 7, tzinfo=UTC),
            trading_day=date(2026, 1, 16),
            physical_contract="RB2610",
            segment_id="rb:RB2610:2026-01-12T01:00:00+00:00",
            close=Decimal("110"), observation_eligible=True,
        ),
        calculation_segment_id="rb:RB2610:2026-01-12T01:00:00+00:00",
        source_bar_sha256="b" * 64,
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
    warmup = SimpleNamespace(
        bar=SimpleNamespace(
            bar_end=datetime(2026, 1, 13, 7, tzinfo=UTC),
            trading_day=date(2026, 1, 13), physical_contract="RB2610",
            segment_id="rb:RB2610:2026-01-12T01:00:00+00:00",
            close=Decimal("105"), observation_eligible=False,
        ),
        calculation_segment_id="rb:RB2610:2026-01-12T01:00:00+00:00",
        source_bar_sha256="b" * 64,
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
