from __future__ import annotations

from app.reference_trading.health import ForwardReferenceHealth
from app.reference_trading.repository import ReferenceRepository
from test_forward_capture import _active, _capture


def test_health_distinguishes_enabled_and_pending_from_success():
    factory, identity, revision, activation = _active()
    before = ForwardReferenceHealth(factory).read()
    assert before["enabled_count"] == 1
    assert before["streams"][0]["pending_capture_count"] == 0
    ReferenceRepository(factory).capture_forward(_capture(identity, revision))
    pending = ForwardReferenceHealth(factory).read()["streams"][0]
    assert pending["pending_capture_count"] == 1
    assert pending["computed_through"] is None
    assert pending["last_success"] is None
