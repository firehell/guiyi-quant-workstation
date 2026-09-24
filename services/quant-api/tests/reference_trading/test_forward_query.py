from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from guiyi_quant.reference_trading import (
    ActionKind, CompletedReferenceBar, ReferenceAction, reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint

from app.reference_trading.contracts import PreparedBatch, SourceAction
from app.reference_trading.presentation import envelope, presentation_point
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict
from app.reference_trading.repository import ReferenceRepository
from test_activation import NOW
from test_forward_capture import _active, _capture


def test_forward_read_filters_observation_time_and_binds_generation(monkeypatch):
    factory, identity, revision, activation = _active()
    repository = ReferenceRepository(factory)
    capture = _capture(identity, revision)
    capture_id = repository.capture_forward(capture)
    token, checkpoint = repository.load_checkpoint(identity.stream_id)
    transition = reduce_reference(
        checkpoint.reference_state,
        completed_bar=CompletedReferenceBar(
            "RB2610", "owner", "calc", capture.bar_end,
            capture.bar_end.date(), Decimal("3500"),
        ),
    )
    point = presentation_point(
        kind="signal", trading_day=capture.bar_end.date(),
        formula_versions=identity.formula_versions,
        value={"bar_end": capture.bar_end, "direction": "buy"},
    )
    prepared = PreparedBatch(
        identity.stream_id, revision, "forward:query", token, {"source": "fixture"},
        (), (transition,),
        AdapterCheckpoint(
            checkpoint.strategy_state, capture.bar_end, capture.capture_hash,
            "RB2610", "owner", "calc", identity, transition.state,
        ),
        "newow_product_replay_v1",
        {"forward_capture_v1": {
            "capture_id": capture_id, "hash": capture.capture_hash, "generation": 1,
        }, "presentation_v1": envelope([point])},
        capture.observed_at,
    )
    repository.commit_batch(token, prepared)
    monkeypatch.setattr(HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True))
    query = HistoricalReferenceQuery(factory)
    early = capture.bar_end + timedelta(milliseconds=500)
    late = capture.observed_at + timedelta(seconds=1)
    arguments = dict(since=capture.bar_end.date(), through=capture.bar_end.date())
    assert query.signals(identity.stream_id, cutoff=early, **arguments)["items"] == []
    visible = query.signals(identity.stream_id, cutoff=late, **arguments)
    assert len(visible["items"]) == 1
    assert query.trades(identity.stream_id, cutoff=late, **arguments)["items"] == []
    activation.disable(identity.stream_id, expected_generation=1, now=NOW + timedelta(seconds=3))
    with pytest.raises(QueryConflict, match="SNAPSHOT_CONFLICT"):
        query.signals(identity.stream_id, cutoff=late, snapshot_token=visible["snapshot"], **arguments)


def test_forward_read_keeps_open_trade_across_query_window(monkeypatch):
    factory, identity, revision, _activation = _active()
    repository = ReferenceRepository(factory)
    capture = _capture(identity, revision)
    capture_id = repository.capture_forward(capture)
    token, checkpoint = repository.load_checkpoint(identity.stream_id)
    action = ReferenceAction(
        stream=identity, source_action_id="forward-build", sequence=0,
        kind=ActionKind.OPEN_LONG, physical_contract="RB2610",
        owner_segment_id="owner", calculation_segment_id="calc",
        bar_end=capture.bar_end, trading_day=capture.bar_end.date(),
        reference_price=Decimal("3500"),
    )
    transition = reduce_reference(
        checkpoint.reference_state, actions=(action,),
        completed_bar=CompletedReferenceBar(
            "RB2610", "owner", "calc", capture.bar_end,
            capture.bar_end.date(), Decimal("3500"),
        ),
    )
    prepared = PreparedBatch(
        identity.stream_id, revision, "forward:open", token, {"source": "fixture"},
        (SourceAction(action, capture.observed_at),), (transition,),
        AdapterCheckpoint(
            checkpoint.strategy_state, capture.bar_end, capture.capture_hash,
            "RB2610", "owner", "calc", identity, transition.state,
        ),
        "newow_product_replay_v1",
        {"forward_capture_v1": {
            "capture_id": capture_id, "hash": capture.capture_hash, "generation": 1,
        }, "presentation_v1": envelope([presentation_point(
            kind="signal", trading_day=capture.bar_end.date(),
            formula_versions=identity.formula_versions,
            value={"bar_end": capture.bar_end, "direction": "buy"},
        )])},
        capture.observed_at,
    )
    repository.commit_batch(token, prepared)
    monkeypatch.setattr(HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True))
    query = HistoricalReferenceQuery(factory)
    future_day = capture.bar_end.date() + timedelta(days=1)
    page = query.trades(
        identity.stream_id, since=future_day, through=future_day,
        cutoff=capture.observed_at + timedelta(days=1),
    )
    assert len(page["items"]) == 1
    assert page["items"][0]["status"] == "OPEN"

    next_capture = replace(
        capture, source_key="RB-20260924-1",
        bar_end=capture.bar_end + timedelta(days=1),
        observed_at=capture.observed_at + timedelta(days=1),
    )
    next_id = repository.capture_forward(next_capture)
    next_token, next_checkpoint = repository.load_checkpoint(identity.stream_id)
    close = ReferenceAction(
        stream=identity, source_action_id="forward-clear", sequence=0,
        kind=ActionKind.CLOSE, entry_action_id=action.source_action_id,
        physical_contract="RB2610", owner_segment_id="owner",
        calculation_segment_id="calc", bar_end=next_capture.bar_end,
        trading_day=next_capture.bar_end.date(), reference_price=Decimal("3510"),
    )
    closed = reduce_reference(
        next_checkpoint.reference_state, actions=(close,),
        completed_bar=CompletedReferenceBar(
            "RB2610", "owner", "calc", next_capture.bar_end,
            next_capture.bar_end.date(), Decimal("3510"),
        ),
    )
    repository.commit_batch(next_token, PreparedBatch(
        identity.stream_id, revision, "forward:close", next_token,
        {"source": "fixture"}, (SourceAction(close, next_capture.observed_at),),
        (closed,), AdapterCheckpoint(
            next_checkpoint.strategy_state, next_capture.bar_end,
            next_capture.capture_hash, "RB2610", "owner", "calc", identity,
            closed.state,
        ), "newow_product_replay_v1",
        {"forward_capture_v1": {
            "capture_id": next_id, "hash": next_capture.capture_hash,
            "generation": 1,
        }, "presentation_v1": envelope([])}, next_capture.observed_at,
    ))
    later = next_capture.bar_end.date() + timedelta(days=1)
    assert query.trades(
        identity.stream_id, since=later, through=later,
        cutoff=next_capture.observed_at + timedelta(days=1),
    )["items"] == []
