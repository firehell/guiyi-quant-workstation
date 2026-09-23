from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.reference_trading import TradeStatus
from guiyi_quant.subing_reference import ReferenceBar, ReferenceSegment

from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.planning import (
    HistoricalReferencePlanner,
    HistoricalReferenceRequest,
    HistoricalStreamRequest,
    WorkBudget,
)
from app.reference_trading.service import HistoricalReferenceService
from tests.reference_trading.test_bootstrap import _repository, _stream


class _SubingInputs:
    def __init__(self) -> None:
        self.market_data = self
        start = datetime(2026, 1, 1, 15, tzinfo=UTC)
        first_values = [100] * 50 + [120, 80, 120, 80]
        second_values = [100] * 50 + [120, 80, 120, 80] + [100] * 7
        first = tuple(
            ReferenceBar(start + timedelta(days=index), (start + timedelta(days=index)).date(), Decimal(value))
            for index, value in enumerate(first_values)
        )
        second_start = start + timedelta(days=20)
        second = tuple(
            ReferenceBar(
                second_start + timedelta(days=index),
                (second_start + timedelta(days=index)).date(),
                Decimal(value),
            )
            for index, value in enumerate(second_values)
        )
        rollover = start + timedelta(days=60)
        self.segments = (
            ReferenceSegment(
                "RB2605", "owner-1", first, first[0].trading_day,
                (rollover - timedelta(days=1)).date(), interrupted_at=rollover,
            ),
            ReferenceSegment(
                "RB2610", "owner-2", second, rollover.date(),
                second[-1].trading_day,
            ),
        )
        self.cutoff = second[-1].bar_end
        self.revision = "source-a"

    def historical_metadata_evidence(self, *, symbol, since, through):
        return {
            "schema_version": "historical_metadata_evidence_v1",
            "exchange": "SHFE",
            "symbol": symbol,
            "since": since.isoformat(),
            "through": through.isoformat(),
            "calendar": [[since.isoformat(), True, False, "fixture", None]],
            "sessions": [[
                "day", "09:00:00", "15:00:00", since.isoformat(), None,
                False, "fixture", "2026-01-01T00:00:00+00:00",
            ]],
        }

    def historical_storage_start(self, _symbol):
        return self.segments[0].bars[0].trading_day

    def historical_input_bound(self, **_kwargs):
        event_count = sum(len(segment.bars) + 1 for segment in self.segments)
        return event_count, event_count * 4096

    def load_historical_inputs(self, **_kwargs):
        raw = []
        for segment in self.segments:
            raw.append({
                "contract": segment.physical_contract,
                "segment_id": segment.segment_id,
                "calculation_segment_id": segment.calculation_segment_id,
                "owner_since": segment.owner_since,
                "owner_through": segment.owner_through,
                "revision": self.revision,
                "bars": [
                    {
                        "bar_end": bar.bar_end,
                        "trading_day": bar.trading_day,
                        "open": bar.close - 1,
                        "high": bar.close + (2 if self.revision == "source-a" else 3),
                        "low": bar.close - 2,
                        "close": bar.close,
                        "volume": 10,
                    }
                    for bar in segment.bars
                ],
            })
        return self.segments, raw, {}, self.cutoff


class _QualitySubingInputs(_SubingInputs):
    def __init__(self) -> None:
        self.market_data = self
        start = datetime(2026, 1, 1, 15, tzinfo=UTC)
        values = [100] * 50 + [120, 80, 120, 80]
        first = tuple(
            ReferenceBar(start + timedelta(days=index), (start + timedelta(days=index)).date(), Decimal(value))
            for index, value in enumerate(values)
        )
        interruption = start + timedelta(days=60)
        second_start = interruption + timedelta(days=1)
        second = tuple(
            ReferenceBar(
                second_start + timedelta(days=index),
                (second_start + timedelta(days=index)).date(),
                Decimal(value),
            )
            for index, value in enumerate(values)
        )
        self.cutoff = second[-1].bar_end
        self.revision = "source-a"
        owner_through = second[-1].trading_day
        self.segments = (
            ReferenceSegment(
                "RB2605", "owner-1", first, first[0].trading_day,
                owner_through,
                calculation_segment_id="calc-1",
                quality_interrupted_at=interruption,
                quality_interruption_trading_day=interruption.date(),
                quality_classification="PRICE_UNAVAILABLE",
            ),
            ReferenceSegment(
                "RB2605", "owner-1", second, first[0].trading_day,
                owner_through, calculation_segment_id="calc-2",
            ),
        )


def _request(source: _SubingInputs):
    stream = _stream()
    return HistoricalStreamRequest(
        stream,
        source.segments[0].bars[0].trading_day,
        source.segments[-1].bars[-1].trading_day,
        source.cutoff + timedelta(seconds=1),
    )


@pytest.mark.parametrize("batch_size", (17, 55))
def test_overlapping_owner_warmup_and_boundary_without_physical_bar_replay(
    batch_size: int,
) -> None:
    source = _SubingInputs()
    reader = MarketDataHistoricalInputReader(newow_reader=None, subing_service=source)
    request = _request(source)
    snapshot = reader.plan_stream(request)

    boundary_indexes = [
        index for index, item in enumerate(snapshot.bars) if not item.strategy_input
    ]
    assert len(boundary_indexes) == 1
    boundary_index = boundary_indexes[0]
    assert snapshot.bars[boundary_index].bar_end == source.segments[0].interrupted_at
    assert snapshot.bars[boundary_index + 1].bar_end < snapshot.bars[boundary_index].bar_end

    planned = HistoricalReferencePlanner(
        reader, now=lambda: request.as_of,
    ).plan(HistoricalReferenceRequest(
        "build", (request,), WorkBudget(1, 500, 30, 1_000_000), batch_size,
    ))
    repository = _repository()
    report = HistoricalReferenceService(repository, reader).execute(
        planned, planned.plan_hash,
    )

    assert report.status == "completed"
    page = repository.read_trades(report.streams[0].snapshot, cutoff=None, limit=100)
    assert any(item.status is TradeStatus.ROLLOVER_INTERRUPTED for item in page.items)


def test_full_source_bar_revision_changes_source_token_when_close_is_unchanged() -> None:
    source = _SubingInputs()
    reader = MarketDataHistoricalInputReader(newow_reader=None, subing_service=source)
    request = _request(source)
    before = reader.plan_stream(request)

    source.revision = "source-b"
    after = reader.plan_stream(request)

    assert before.source_token != after.source_token
    assert before.dependency_manifest["input_fingerprints"] != after.dependency_manifest["input_fingerprints"]


def test_multi_owner_bound_rejects_before_materializing_physical_prefixes() -> None:
    class OverBudgetInputs(_SubingInputs):
        materialized = False

        def historical_input_bound(self, **_kwargs):
            return 213, 213 * 4096

        def load_historical_inputs(self, **kwargs):
            self.materialized = True
            return super().load_historical_inputs(**kwargs)

    source = OverBudgetInputs()
    reader = MarketDataHistoricalInputReader(newow_reader=None, subing_service=source)
    request = _request(source)

    with pytest.raises(ValueError, match="REFERENCE_BUDGET_EXCEEDED"):
        HistoricalReferencePlanner(reader, now=lambda: request.as_of).plan(
            HistoricalReferenceRequest(
                "build", (request,), WorkBudget(1, 150, 30, 1_000_000), 17,
            )
        )

    assert source.materialized is False


def test_quality_gap_boundary_crosses_batches_and_interrupts_open() -> None:
    source = _QualitySubingInputs()
    reader = MarketDataHistoricalInputReader(newow_reader=None, subing_service=source)
    request = _request(source)
    plan = HistoricalReferencePlanner(
        reader, now=lambda: request.as_of,
    ).plan(HistoricalReferenceRequest(
        "build", (request,), WorkBudget(1, 500, 30, 1_000_000), 13,
    ))
    repository = _repository()

    report = HistoricalReferenceService(repository, reader).execute(plan, plan.plan_hash)

    assert report.status == "completed"
    page = repository.read_trades(report.streams[0].snapshot, cutoff=None, limit=100)
    assert any(item.status is TradeStatus.DATA_INTERRUPTED for item in page.items)
