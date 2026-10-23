"""Read the exact independent historical identity; never substitute its state for Live."""
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select

from app.reference_trading.models import ReferenceBatch, ReferenceRevision, ReferenceStream
from app.reference_trading.repository import _identity_from_row
from guiyi_quant.reference_trading import RecordingMode


def read_independent_history(session, streams, endpoints):
    identities = {stream.stream_id: replace(_identity_from_row(stream),
                  recording_mode=RecordingMode.HISTORICAL_REPLAY,
                  observation_policy_version=None).stream_id for stream in streams}
    rows = session.execute(select(
        ReferenceStream.stream_id, ReferenceStream.health, ReferenceRevision.revision_id,
        ReferenceRevision.status, ReferenceBatch.computed_through,
    ).outerjoin(ReferenceRevision, (ReferenceRevision.stream_id == ReferenceStream.stream_id)
                & (ReferenceRevision.revision_id == ReferenceStream.active_revision_id))
      .outerjoin(ReferenceBatch, ReferenceBatch.batch_id == ReferenceRevision.checkpoint_batch_id)
      .where(ReferenceStream.stream_id.in_(tuple(identities.values())))).all()
    stored = {row[0]: row[1:] for row in rows}
    result = {}
    for stream in streams:
        identifier = identities[stream.stream_id]
        value = stored.get(identifier)
        endpoint = endpoints.get((stream.product.lower(), stream.frequency), {})
        expected = endpoint.get("canonical_expected_through") or (
            endpoint.get("expected_through") if endpoint.get("expected_source") == "canonical_completed" else None)
        item = {"stream_id": identifier, "status": "NOT_BUILT", "revision_id": None,
                "computed_through": None, "expected_through": expected,
                "recording_mode": "historical_replay", "source": "canonical",
                "freshness_scope": "COMPUTED_ENDPOINT_ONLY",
                "canonical_revision_verified": False}
        if value:
            health, revision_id, revision_status, computed = value
            if computed is not None:
                computed = computed.replace(tzinfo=computed.tzinfo or UTC)
            status = "REBUILD_REQUIRED"
            if revision_status == "active" and health == "READY":
                status = "UNVERIFIED" if not expected or computed is None else (
                    "CURRENT" if computed >= datetime.fromisoformat(expected) else "LAGGING")
            item.update(status=status, revision_id=revision_id,
                        computed_through=computed.isoformat() if computed else None)
        result[stream.stream_id] = item
    return result
