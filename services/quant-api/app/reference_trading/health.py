"""Independent read-only forward reference health, separate from Market/Alert health."""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.readonly import readonly_transaction
from app.reference_trading.models import (
    ReferenceBatch, ReferenceCaptureReconciliation, ReferenceStream,
)


class ForwardReferenceHealth:
    def __init__(self, session_factory):
        self._factory = session_factory

    def read(self) -> dict[str, object]:
        with self._factory() as session, readonly_transaction(session, timeout_seconds=15):
            streams = session.scalars(select(ReferenceStream).where(
                ReferenceStream.recording_mode == "forward_observation",
            ).order_by(ReferenceStream.stream_id).limit(512)).all()
            items: list[dict[str, object]] = []
            for stream in streams:
                pending_count, oldest = session.execute(select(
                    func.count(ReferenceBatch.batch_id), func.min(ReferenceBatch.observed_at),
                ).where(
                    ReferenceBatch.stream_id == stream.stream_id,
                    ReferenceBatch.kind == "capture",
                    ReferenceBatch.consumed_by_batch_id.is_(None),
                )).one()
                last_success, computed = session.execute(select(
                    func.max(ReferenceBatch.processed_at), func.max(ReferenceBatch.computed_through),
                ).where(
                    ReferenceBatch.stream_id == stream.stream_id,
                    ReferenceBatch.kind == "calculation",
                    ~ReferenceBatch.batch_key.like("forward:observation-gap:%"),
                    ReferenceBatch.seq <= stream.latest_seq,
                )).one()
                gap_at = session.scalar(select(func.max(ReferenceBatch.observed_at)).where(
                    ReferenceBatch.stream_id == stream.stream_id,
                    ReferenceBatch.kind == "calculation",
                    ReferenceBatch.batch_key.like("forward:observation-gap:%"),
                    ReferenceBatch.seq <= stream.latest_seq,
                ))
                captures = select(ReferenceBatch.batch_id).where(
                    ReferenceBatch.stream_id == stream.stream_id,
                    ReferenceBatch.kind == "capture",
                )
                mismatch_count = session.scalar(select(func.count()).select_from(
                    ReferenceCaptureReconciliation,
                ).where(
                    ReferenceCaptureReconciliation.capture_batch_id.in_(captures),
                    ReferenceCaptureReconciliation.status == "mismatch",
                )) or 0
                items.append({
                    "stream_id": stream.stream_id, "enabled": stream.enabled,
                    "activation_generation": stream.activation_generation,
                    "recording_start": stream.recording_start.isoformat() if stream.recording_start else None,
                    "computed_through": computed.isoformat() if computed else None,
                    "observation_boundary_at": gap_at.isoformat() if gap_at else None,
                    "expected_through": None,
                    "last_success": last_success.isoformat() if last_success else None,
                    "pending_capture_count": pending_count,
                    "oldest_pending_observed_at": oldest.isoformat() if oldest else None,
                    "reconciliation_mismatch_count": mismatch_count,
                    "status": stream.health,
                })
            return {"enabled_count": sum(item["enabled"] is True for item in items),
                    "streams": items}
