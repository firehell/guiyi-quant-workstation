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
