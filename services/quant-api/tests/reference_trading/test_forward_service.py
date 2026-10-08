from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from guiyi_quant.reference_trading import CompletedReferenceBar, reduce_reference
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint

from app.reference_trading.contracts import PreparedBatch
from app.reference_trading.forward_service import ForwardReferenceService
from app.reference_trading.presentation import envelope
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.repository import RepositoryConflict
from test_activation import NOW
from test_forward_capture import _active, _capture


def test_pending_capture_is_consumed_atomically_with_no_signal_mark():
    factory, identity, revision, _ = _active()
    repository = ReferenceRepository(factory)
    capture = _capture(identity, revision)
    capture_id = repository.capture_forward(capture)

    def evaluate(token, checkpoint, evidence):
        prior = checkpoint.reference_state
        transition = reduce_reference(
            prior, completed_bar=CompletedReferenceBar(
                "RB2610", "owner", "calc", capture.bar_end,
                capture.bar_end.date(), Decimal("3500"),
            ),
        )
        next_checkpoint = AdapterCheckpoint(
            checkpoint.strategy_state, capture.bar_end, capture.capture_hash,
            "RB2610", "owner", "calc", identity, transition.state,
        )
        return PreparedBatch(
            identity.stream_id, revision, "forward:1", token,
            {"source": "fixture"}, (), (transition,), next_checkpoint,
            "newow_product_replay_v1",
            {"forward_capture_v1": {
                "capture_id": capture_id, "hash": capture.capture_hash, "generation": 1,
            }, "presentation_v1": envelope([])},
            capture.observed_at,
        )

    service = ForwardReferenceService(repository, evaluate)
    result = service.process_pending(identity.stream_id)
    assert result.seq == 2
    assert repository.read_pending_capture(identity.stream_id) is None
    assert repository.read_batch(identity.stream_id, revision, "forward:1").seq == 2
    assert service.process_pending(identity.stream_id) is None


@pytest.mark.parametrize('strategy', ('newow_trend','newow_dual_fusion'))
def test_pending_recovery_checks_reconciliation_before_evaluation(strategy):
    from app.reference_trading.composition import build_forward_reference_worker
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    calls = []
    class Repository:
        def enabled_forward_stream_ids(self, **_): return (strategy,)
        def read_pending_capture(self, _): return ('pending', {})
        def read_state(self, _):
            calls.append('state')
            raise AssertionError('known mismatch must stop before reading/evaluating pending input')
    def guard(stream):
        calls.append(stream)
        raise ForwardInputUnavailable('REFERENCE_CANONICAL_MISMATCH')
    worker = build_forward_reference_worker(repository=Repository(), market_read=None,
        newow_reader=None,owner_segments=None,expected_endpoints=None,newow_capability_ready=None,
        enabled=True,reconciliation_guard=guard)
    worker.scan()
    assert worker.run_round() == 0
    assert calls == [strategy]
    assert worker.health().blocked == ((strategy,'REFERENCE_CANONICAL_MISMATCH'),)


def test_forward_commit_guard_rolls_back_prepared_pending_batch():
    factory, identity, revision, _ = _active()
    repository = ReferenceRepository(factory)
    capture = _capture(identity, revision)
    capture_id = repository.capture_forward(capture)
    before = repository.read_state(identity.stream_id)
    def evaluate(token, checkpoint, evidence):
        transition = reduce_reference(checkpoint.reference_state,completed_bar=CompletedReferenceBar(
            'RB2610','owner','calc',capture.bar_end,capture.bar_end.date(),Decimal('3500')))
        return PreparedBatch(identity.stream_id,revision,'forward:guarded',token,{'source':'fixture'},(),
            (transition,),AdapterCheckpoint(checkpoint.strategy_state,capture.bar_end,capture.capture_hash,
                'RB2610','owner','calc',identity,transition.state),'newow_product_replay_v1',
            {'forward_capture_v1':{'capture_id':capture_id,'hash':capture.capture_hash,'generation':1},
             'presentation_v1':envelope([])},capture.observed_at)
    def guard(session, stream):
        assert session.in_transaction() and stream == identity.stream_id
        raise RepositoryConflict('REFERENCE_CANONICAL_MISMATCH')
    with pytest.raises(RepositoryConflict,match='REFERENCE_CANONICAL_MISMATCH'):
        ForwardReferenceService(repository,evaluate,commit_guard=guard).process_pending(identity.stream_id)
    assert repository.read_state(identity.stream_id) == before
    assert repository.read_pending_capture(identity.stream_id)[0] == capture_id
    assert repository.read_batch(identity.stream_id,revision,'forward:guarded') is None


def test_disable_during_evaluation_prevents_stale_commit():
    factory, identity, revision, activation = _active()
    repository = ReferenceRepository(factory)
    capture = _capture(identity, revision)
    capture_id = repository.capture_forward(capture)

    def evaluate(token, checkpoint, evidence):
        activation.disable(identity.stream_id, expected_generation=1, now=NOW + timedelta(seconds=3))
        transition = reduce_reference(
            checkpoint.reference_state,
            completed_bar=CompletedReferenceBar(
                "RB2610", "owner", "calc", capture.bar_end,
                capture.bar_end.date(), Decimal("3500"),
            ),
        )
        return PreparedBatch(
            identity.stream_id, revision, "forward:stale", token,
            {"source": "fixture"}, (), (transition,),
            AdapterCheckpoint(
                checkpoint.strategy_state, capture.bar_end, capture.capture_hash,
                "RB2610", "owner", "calc", identity, transition.state,
            ),
            "newow_product_replay_v1",
            {"forward_capture_v1": {
                "capture_id": capture_id, "hash": capture.capture_hash, "generation": 1,
            }, "presentation_v1": envelope([])},
            capture.observed_at,
        )

    with pytest.raises(RepositoryConflict, match="FORWARD_CAPTURE_CONFLICT"):
        ForwardReferenceService(repository, evaluate).process_pending(identity.stream_id)
