from dataclasses import replace
from decimal import Decimal
from datetime import datetime
from hashlib import sha256

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from guiyi_quant.newow.product_adapters import replay_strategy, build_product_identity, label_calculation_segments
from guiyi_quant.newow.product_identity import InputQualityPolicy
from guiyi_quant.newow.product_identity import (
    REFERENCE_MODEL_VERSION, futures_adaptation_version,
)
from guiyi_quant.newow.reference_statistics import PerformanceWindow, summarize_reference
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector
from guiyi_quant.reference_trading import StreamIdentity
from guiyi_quant.reference_trading.adapters import strategy_input_fingerprint

from app.db.base import Base
from app.reference_trading.contracts import PreparedBatch, SeedChunk
from app.reference_trading.inputs import HistoricalInputBar
from app.reference_trading.presentation import envelope
from app.reference_trading.persisted_newow import PersistedNewowReference
from app.reference_trading.query import HistoricalReferenceQuery
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.service import (
    NewowHistoricalPayload, _advance_batch, _seed_checkpoint,
)
from tests.reference_trading.test_repository import _digest


def test_same_bar_hint_before_exit_sequence_is_retained() -> None:
    at = "2026-09-19T08:00:00+00:00"
    exit_at = "2026-09-20T08:00:00+00:00"
    trades = [{
        "reference_trade_id": "trade-1", "physical_contract": "RB2610",
        "owner_segment_id": "owner-1", "entry_bar_end": at,
        "entry_sequence": 0, "exit_bar_end": exit_at,
        "exit_sequence": 2, "status": "CLOSED",
    }]
    hints = [{"value": {
        "hint_id": "hint-before-clear", "kind": "process", "retrospective": False,
        "physical_contract": "RB2610", "segment_id": "owner-1",
        "bar_end": exit_at, "known_at": exit_at, "sequence": 1,
    }}]
    attached = PersistedNewowReference._hint_ids(
        trades, [], hints, datetime.fromisoformat(exit_at),
    )
    assert attached == {"trade-1": ["hint-before-clear"]}


def test_data_interruption_does_not_attach_later_hint_to_old_trade() -> None:
    trade = {
        "reference_trade_id": "old", "physical_contract": "RB2610",
        "owner_segment_id": "owner-1", "calculation_segment_id": "calc-1",
        "entry_bar_end": "2026-09-01T08:00:00+00:00", "entry_sequence": 0,
        "status": "DATA_INTERRUPTED", "interrupted_at": "2026-09-02T08:00:00+00:00",
    }
    hint = {"value": {
        "hint_id": "after-gap", "kind": "process", "retrospective": False,
        "physical_contract": "RB2610", "segment_id": "owner-1",
        "calculation_segment_id": "calc-2",
        "bar_end": "2026-09-03T08:00:00+00:00",
        "known_at": "2026-09-03T08:00:00+00:00", "sequence": 1,
    }}
    same_segment_hint = {"value": {
        **hint["value"], "hint_id": "after-gap-same-segment",
        "calculation_segment_id": "calc-1",
    }}
    assert PersistedNewowReference._hint_ids(
        [trade], [], [hint, same_segment_hint],
        datetime.fromisoformat("2026-09-04T08:00:00+00:00"),
    ) == {"old": []}


def test_newow_goldens_keep_public_trade_ids_and_decimal_statistics() -> None:
    from newow.product_fixtures import ProductCases

    case = ProductCases().primitive_input("trend", "1d")
    case = replace(case, identity=build_product_identity(
        case.identity.product, case.identity.strategy, case.identity.frequency,
        input_quality_policy=InputQualityPolicy.DAILY_V2,
    ))
    case = replace(case, bars=label_calculation_segments(case.identity, case.bars, ()))
    stream = StreamIdentity(
        strategy_code="newow_trend", formula_versions=case.identity.formula_versions,
        profile_id=case.identity.profile_id,
        reference_model_version=REFERENCE_MODEL_VERSION,
        futures_adaptation_version=futures_adaptation_version("1d", case.identity.input_quality_policy),
        product=case.identity.product, frequency="1d",
        series_kind="actual_dominant", recording_mode="historical_replay",
        observation_policy_version=None,
    )
    bars = tuple(HistoricalInputBar(
        item.bar.bar_end, item.bar.trading_day, item.bar.physical_contract,
        item.bar.segment_id, item.calculation_segment_id, item.bar.close,
        strategy_input_fingerprint({"bar_end": item.bar.bar_end, "source": item.source_bar_sha256}),
        NewowHistoricalPayload(case.identity, item),
    ) for item in case.bars)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = ReferenceRepository(factory)
    stored = repository.ensure_stream(stream)
    manifest = {"fixture": "newow-trend-v1"}
    revision = repository.create_revision(stream.stream_id, stored.row_version, _digest(manifest))
    checkpoint, schema = _seed_checkpoint(stream)
    root = sha256(b"seed").hexdigest()
    repository.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, root, "seed"))
    token = repository.seal_seed(revision, manifest, checkpoint, schema)
    for start in range(0, len(bars), 23):
        points: list[dict[str, object]] = []
        next_checkpoint, sources, transitions, schema = _advance_batch(
            stream, checkpoint, bars[start:start + 23], points,
        )
        prepared = PreparedBatch(
            stream.stream_id, revision, f"bar-{start}", token, manifest,
            sources, transitions, next_checkpoint, schema,
            {"presentation_v1": envelope(points)},
        )
        repository.commit_batch(token, prepared)
        token, checkpoint = repository.load_checkpoint(stream.stream_id, revision)
    snapshot = repository.publish_revision(
        stream.stream_id, revision, token.row_version, _digest(manifest),
    )
    assert snapshot.seq > 1
    since = case.bars[0].bar.trading_day
    through = case.bars[-1].bar.trading_day
    query = HistoricalReferenceQuery(factory)
    actual = query.trades(
        stream.stream_id, since=since, through=through,
        cutoff=case.bars[-1].bar.bar_end, limit=200,
    )
    replay = replay_strategy(case.identity, case.bars)
    projection = ReferenceTradeProjector().project(
        replay, (), case.bars[-1].bar.bar_end,
    )
    assert {item["public_reference_trade_id"] for item in actual["items"]} == {
        item.reference_trade_id for item in projection.trades
    }
    # SQLite Numeric is rounded by its driver; exact Decimal storage is a PG gate.
    for item in actual["items"]:
        expected_trade = next(
            trade for trade in projection.trades
            if trade.reference_trade_id == item["public_reference_trade_id"]
        )
        assert abs(Decimal(item["reference_return"]) - expected_trade.reference_return_pct) < Decimal("0.000000001")
    expected = summarize_reference(
        projection, PerformanceWindow(since, through, case.bars[-1].bar.bar_end),
    )
    summary = query.summary(
        stream.stream_id, since=since, through=through,
        cutoff=case.bars[-1].bar.bar_end, snapshot_token=actual["snapshot"],
    )
    assert summary["closed_count"] == expected.closed_count
    assert abs(
        Decimal(summary["sum_return_percentage_points"]) - expected.sum_return_percentage_points
    ) < Decimal("0.00000001")
    later_since = case.bars[len(case.bars) // 2].bar.trading_day
    initial_page = query.trades(
        stream.stream_id, since=later_since, through=through,
        cutoff=case.bars[-1].bar.bar_end, limit=200,
    )
    initial_summary = query.summary(
        stream.stream_id, since=later_since, through=through,
        cutoff=case.bars[-1].bar.bar_end, snapshot_token=initial_page["snapshot"],
    )
    expected_initial = summarize_reference(
        projection, PerformanceWindow(later_since, through, case.bars[-1].bar.bar_end),
    )
    assert initial_summary["initial_count"] == expected_initial.initial_count
    assert {item["public_reference_trade_id"] for item in initial_page["items"]} == {
        item.reference_trade_id for item in (
            *expected_initial.closed_trades, *expected_initial.open_trades,
            *expected_initial.interrupted_trades, *expected_initial.initial_trades,
        )
    }


def test_hint_interval_index_preserves_ambiguity_and_nested_older_interval():
    base = {
        'physical_contract': 'RB2610', 'owner_segment_id': 'owner-1',
        'entry_bar_end': '2026-09-01T08:00:00+00:00', 'entry_sequence': 0,
        'exit_bar_end': '2026-09-20T08:00:00+00:00', 'exit_sequence': 2,
        'status': 'CLOSED',
    }
    trades = [dict(base, reference_trade_id='long'), dict(base, reference_trade_id='short', entry_bar_end='2026-09-02T08:00:00+00:00', exit_bar_end='2026-09-03T08:00:00+00:00')]
    def hint(day):
        at = f'2026-09-{day:02d}T09:00:00+00:00'
        return {'value': {'hint_id': f'h{day}', 'kind': 'process', 'retrospective': False, 'physical_contract': 'RB2610', 'segment_id': 'owner-1', 'bar_end': at, 'known_at': at, 'sequence': 1}}
    assert PersistedNewowReference._hint_ids(trades, [], [hint(2), hint(4)], datetime.fromisoformat(base['exit_bar_end'])) == {'long': ['h4'], 'short': []}


@pytest.mark.parametrize("frequency", ["1d", "1w"])
def test_persisted_daily_weekly_availability_uses_authoritative_owner(monkeypatch, frequency):
    """Saved next-contract warmup must not collide with the current owner's day."""
    from datetime import UTC, date, time
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.market_data.aggregation import SessionWindow
    from app.market_data.domain import ResolvedContractSegment
    from app.market_data.newow.product_reader import NewowProductReader
    from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
    from guiyi_quant.newow.product_identity import build_segment_id

    day = date(2026, 9, 2)
    owners = (
        ResolvedContractSegment("RB2610", date(2026, 9, 1), date(2026, 9, 3)),
        ResolvedContractSegment("RB2701", date(2026, 9, 8), date(2026, 9, 10)),
    )
    def sessions(*, symbol, trading_day):
        assert symbol == "rb"
        return (SessionWindow(datetime.combine(trading_day, time(1), UTC),
                              datetime.combine(trading_day, time(7), UTC)),)
    reader = object.__new__(NewowProductReader)
    reader._market_data = SimpleNamespace(session_windows=sessions)
    reader.historical_source_evidence = Mock(return_value={})
    points = [{"trading_day": day.isoformat(), "value": {
        "physical_contract": owner.contract,
        "segment_id": build_segment_id("rb", owner.contract, sessions(
            symbol="rb", trading_day=owner.start_trading_day)[0].start),
        "calculation_segment_id": f"calculation-{index}", "status": "ready",
    }} for index, owner in enumerate(owners)]
    cutoff = datetime(2026, 9, 10, 7, 0, 1, tzinfo=UTC)
    saved = PersistedNewowReference(lambda: None)
    page = {"snapshot": "snapshot", "revision_id": "revision", "seq": 2,
            "items": [], "next_cursor": None}
    saved._query = SimpleNamespace(streams=lambda **kwargs: [{"stream_id": "stream"}],
                                   trades=lambda *args, **kwargs: page,
                                   summary=lambda *args, **kwargs: {})
    manifest = {"query_since": day.isoformat(), "query_through": "2026-09-10",
                "query_as_of": cutoff.isoformat(), "reader": "newow_product_reader_intraday_v3"}
    saved._manifest = lambda *args: (None, manifest)
    saved._reference_facts = lambda *args: {"availability": points,
        "boundary": [], "hint": [], "action": []}
    monkeypatch.setattr("app.reference_trading.persisted_newow.verify_saved_compact_source",
                        lambda *args: None)
    resolved = SimpleNamespace(requested_since=day, requested_through=date(2026, 9, 10),
                               actual_through=date(2026, 9, 10), cutoff=cutoff)
    read = SimpleNamespace(owners=owners, data_interruptions=())
    class CoverageChecked(Exception):
        pass
    def coverage(availability, gaps, since, through):
        intervals = PersistedNewowReference._coverage(availability, gaps, since, through)
        assert len(intervals) == 1
        assert intervals[0]["physical_contract"] == "RB2610"
        assert intervals[0]["status"] == "VALID"
        assert availability == points[:1]
        raise CoverageChecked
    saved._coverage = coverage
    request = SimpleNamespace(product="rb", strategy=ProductStrategy.TREND,
        frequency=ProductFrequency(frequency), history_before=None, history_limit=200)
    with pytest.raises(CoverageChecked):
        saved.section(request, read, None, reader, "fact", None, resolved)


def test_saved_owner_date_boundaries_and_calculation_conflict():
    from datetime import UTC, date, time, timedelta
    from types import SimpleNamespace
    from app.market_data.aggregation import SessionWindow
    from app.market_data.domain import ResolvedContractSegment
    from app.market_data.newow.product_reader import NewowProductReader
    from app.reference_trading.query import QueryConflict
    from guiyi_quant.newow.product_identity import build_segment_id

    owners = (ResolvedContractSegment("RB2610", date(2026, 9, 1), date(2026, 9, 3)),
              ResolvedContractSegment("RB2701", date(2026, 9, 4), date(2026, 9, 8)))
    def sessions(*, symbol, trading_day):
        return (SessionWindow(datetime.combine(trading_day, time(1), UTC),
                              datetime.combine(trading_day, time(7), UTC)),)
    reader = object.__new__(NewowProductReader)
    reader._market_data = SimpleNamespace(session_windows=sessions)
    def point(owner, day, calculation="calc"):
        return {"trading_day": day.isoformat(), "value": {
            "physical_contract": owner.contract,
            "segment_id": build_segment_id("rb", owner.contract, sessions(
                symbol="rb", trading_day=owner.start_trading_day)[0].start),
            "calculation_segment_id": calculation, "status": "ready"}}
    points = [point(owner, day) for owner in owners for day in (
        owner.start_trading_day - timedelta(days=1), owner.start_trading_day,
        owner.end_trading_day, owner.end_trading_day + timedelta(days=1))]
    assert reader.reference_owned_points("rb", points, owners) == [points[i] for i in (1, 2, 5, 6)]
    # On the switch day only the new owner survives, even when both saved facts exist.
    switch = date(2026, 9, 4)
    switched = [point(owner, switch) for owner in owners]
    assert reader.reference_owned_points("rb", switched, owners) == switched[1:]
    # Filtering physical warmup cannot hide a real calculation identity conflict.
    conflict = [point(owners[1], switch, calculation) for calculation in ("calc-a", "calc-b")]
    filtered = reader.reference_owned_points("rb", conflict, owners)
    assert filtered == conflict
    with pytest.raises(QueryConflict, match="COVERAGE_IDENTITY_CONFLICT"):
        PersistedNewowReference._coverage(filtered, (), switch, switch)
