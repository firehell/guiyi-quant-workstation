from datetime import UTC, date, datetime, timedelta
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from random import Random

import pytest

from app.reference_trading.presentation import (
    MAX_PRESENTATION_BYTES, PresentationUnavailable, envelope,
    presentation_point, require_envelope,
)
from app.reference_trading.inputs import HistoricalInputBar
from app.reference_trading.service import SubingHistoricalPayload, _advance_batch, _seed_checkpoint
from tests.reference_trading.test_historical_integration import _subing_stream
from guiyi_quant.subing_reference import (
    REFERENCE_MODEL_VERSION, ReferenceBar, ReferenceSegment, project_reference,
)


def test_presentation_keeps_decimal_and_same_direction_signal() -> None:
    point = presentation_point(
        kind="signal",
        value={"signal_id": "s1", "action": "SAME_DIRECTION", "reference_price": Decimal("2.500")},
        trading_day=date(2026, 9, 23), formula_versions=("v1",),
    )
    saved = envelope([point])
    assert require_envelope(saved)[0]["value"] == {
        "signal_id": "s1", "action": "SAME_DIRECTION", "reference_price": "2.500",
    }


def test_old_batch_cannot_be_read_as_empty_presentation() -> None:
    with pytest.raises(PresentationUnavailable, match="PRESENTATION_NOT_MATERIALIZED"):
        require_envelope(None)


def test_presentation_has_byte_budget() -> None:
    with pytest.raises(ValueError, match="PRESENTATION_BATCH_LIMIT"):
        envelope([{"value": "x" * MAX_PRESENTATION_BYTES}])


def test_subing_materialization_matches_kernel_signals_and_warmup_indicators() -> None:
    at = datetime(2026, 1, 1, 15, tzinfo=UTC)
    random = Random(0)
    prices = [100] * 50
    last = 100
    for _ in range(200):
        last = max(10, last + random.choice((-12, -8, -4, -2, 2, 4, 8, 12)))
        prices.append(last)
    bars = tuple(
        ReferenceBar(at + timedelta(hours=index), (at + timedelta(hours=index)).date(), Decimal(price))
        for index, price in enumerate(prices)
    )
    segment = ReferenceSegment(
        "RB2601", "owner", bars, bars[0].trading_day, bars[-1].trading_day,
    )
    stream = replace(_subing_stream("1d"), reference_model_version=REFERENCE_MODEL_VERSION)
    inputs = tuple(
        HistoricalInputBar(
            bar.bar_end, bar.trading_day, "RB2601", "owner", "owner", bar.close,
            sha256(f"bar-{index}".encode()).hexdigest(),
            SubingHistoricalPayload(
                segment, bar, segment.owner_since, segment.owner_through, False,
            ),
        ) for index, bar in enumerate(bars)
    )
    checkpoint, _schema = _seed_checkpoint(stream)
    points: list[dict[str, object]] = []
    _next, sources, _transitions, _schema = _advance_batch(
        stream, checkpoint, inputs, points,
    )
    saved = require_envelope(envelope(points))
    legacy = project_reference(
        "rb", (segment,), since=segment.owner_since,
        through=segment.owner_through, as_of=bars[-1].bar_end,
        frequency="1d", quality_segmented=False,
    )
    assert [point["value"]["signal_id"] for point in saved if point["kind"] == "signal"] == [
        signal.signal_id for signal in legacy.signals
    ]
    assert len([point for point in saved if point["kind"] == "indicator"]) == len(legacy.indicators)
    assert any(point["value"]["action"] == "SAME_DIRECTION" for point in saved if point["kind"] == "signal")
    assert len(sources) < len(legacy.signals) * 2
    assert any(
        point["value"]["dif"] is None for point in saved if point["kind"] == "indicator"
    )
