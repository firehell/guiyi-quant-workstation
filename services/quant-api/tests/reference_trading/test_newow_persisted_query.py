from decimal import Decimal
from datetime import datetime
from hashlib import sha256

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from guiyi_quant.newow.product_adapters import replay_strategy
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


def test_newow_goldens_keep_public_trade_ids_and_decimal_statistics() -> None:
    from newow.product_fixtures import ProductCases

    case = ProductCases().primitive_input("trend", "1d")
    stream = StreamIdentity(
        strategy_code="newow_trend", formula_versions=case.identity.formula_versions,
        profile_id=case.identity.profile_id,
        reference_model_version=REFERENCE_MODEL_VERSION,
        futures_adaptation_version=futures_adaptation_version("1d"),
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
