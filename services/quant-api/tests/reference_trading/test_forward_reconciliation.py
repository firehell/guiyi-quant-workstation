from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest

from app.reference_trading.capture import ForwardCapture
from app.reference_trading.reconciliation import CanonicalEvidence, ForwardReconciler
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict
from test_activation import NOW
from test_forward_capture import _active


def test_reconciliation_is_append_only_and_never_changes_observation():
    factory, identity, revision, _ = _active()
    source_hash = sha256(b"exact-physical-bar").hexdigest()
    capture = ForwardCapture(
        identity.stream_id, revision, 1, "exact-bar", NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=2), "completed_live", {"close": "3500"},
        {"source_sha256": source_hash}, "first_seen",
    )
    repository = ReferenceRepository(factory)
    capture_id = repository.capture_forward(capture)
    matched = ForwardReconciler(
        factory, lambda _: CanonicalEvidence("canonical-v1", source_hash),
    )
    assert matched.reconcile(capture_id, now=NOW + timedelta(hours=1)) == "matched"
    assert matched.reconcile(capture_id, now=NOW + timedelta(hours=2)) == "matched"
    revised = ForwardReconciler(
        factory, lambda _: CanonicalEvidence("canonical-v2", sha256(b"revised").hexdigest()),
    )
    assert revised.reconcile(capture_id, now=NOW + timedelta(hours=3)) == "mismatch"
    with pytest.raises(RepositoryConflict, match="RECONCILIATION_REVISION_CONFLICT"):
        ForwardReconciler(
            factory, lambda _: CanonicalEvidence("canonical-v1", sha256(b"changed").hexdigest()),
        ).reconcile(capture_id, now=NOW + timedelta(hours=4))
    assert repository.read_pending_capture(identity.stream_id)[0] == capture_id
