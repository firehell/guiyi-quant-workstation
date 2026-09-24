from __future__ import annotations

from datetime import timedelta

import pytest

from app.reference_trading.activation import ForwardActivation
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.models import ReferenceBatch
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict
from test_activation import NOW, _setup


def _active():
    factory, identity, revision = _setup()
    service = ForwardActivation(factory)
    plan = service.plan(
        identity.stream_id, revision, host="test-host", environment="isolated",
        recording_start=NOW + timedelta(seconds=1), expires_at=NOW + timedelta(minutes=1),
        budget={"max_pending": 32},
    )
    service.apply(plan, expected_plan_hash=plan.plan_hash, now=NOW)
    return factory, identity, revision, service


def _capture(identity, revision, *, close="3500"):
    return ForwardCapture(
        identity.stream_id, revision, 1, "RB-20260923-1", NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=2), "completed_live", {"close": close},
        {"owner": "RB2610", "session": "fixture"}, "first_seen",
    )


def test_capture_is_durable_idempotent_and_does_not_advance_sequence():
    factory, identity, revision, _ = _active()
    repository = ReferenceRepository(factory)
    assert repository.enabled_forward_routes(identity.product.lower(), identity.frequency) == (
        identity.stream_id,
    )
    assert repository.enabled_forward_routes("cu", identity.frequency) == ()
    capture = _capture(identity, revision)
    batch_id = repository.capture_forward(capture)
    assert repository.capture_forward(capture) == batch_id
    assert repository.read_pending_capture(identity.stream_id) == (batch_id, capture.evidence())
    with factory() as session:
        row = session.get(ReferenceBatch, batch_id)
        assert row.seq is None and row.outcome == "pending"
    with pytest.raises(RepositoryConflict, match="CAPTURE_CONTENT_CONFLICT"):
        repository.capture_forward(_capture(identity, revision, close="3501"))


def test_disable_blocks_new_capture_and_preserves_pending():
    factory, identity, revision, activation = _active()
    repository = ReferenceRepository(factory)
    batch_id = repository.capture_forward(_capture(identity, revision))
    activation.disable(identity.stream_id, expected_generation=1, now=NOW + timedelta(seconds=3))
    assert repository.enabled_forward_routes(identity.product.lower(), identity.frequency) == ()
    with pytest.raises(RepositoryConflict, match="ACTIVATION_GENERATION_CONFLICT"):
        repository.capture_forward(_capture(identity, revision))
    assert repository.read_pending_capture(identity.stream_id) is None
    with factory() as session:
        assert session.get(ReferenceBatch, batch_id).outcome == "pending"
