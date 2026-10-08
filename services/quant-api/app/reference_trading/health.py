"""Independent read-only forward health, using bounded set-based queries."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import and_, case, func, select

from app.db.readonly import readonly_transaction
from app.reference_trading.models import (
    ReferenceBatch, ReferenceCaptureReconciliation, ReferenceStream,
)
from app.reference_trading.presentation import require_envelope


def read_completed_canonical_endpoints(session, keys, at):
    """One bounded MDS read per product-period, shared across all strategy routes."""
    from app.market_data.composition import build_market_data_service
    from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery
    from app.market_data.market_data_service import MarketDataError

    market = build_market_data_service(session)
    result = {}
    for product, frequency in keys:
        value = {"expected_through": None, "expected_source": "canonical_completed",
                 "endpoint_status": "UNKNOWN", "endpoint_reason": None}
        try:
            page = market.query_page(SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT, product, BarFrequency(frequency),
                # Catalog publication determines this historical endpoint;
                # prepared Session/MainMap metadata and Live time do not.
                before=None, limit=1,
            ))
            if not page.bars or page.bars[-1].bar_end > at:
                value["endpoint_reason"] = "COMPLETE_PERIOD_MISSING"
            else:
                value.update(expected_through=page.bars[-1].bar_end.isoformat(), endpoint_status="READY")
        except MarketDataError:
            value["endpoint_reason"] = "AUTHORITATIVE_ENDPOINT_UNAVAILABLE"
        result[(product, frequency)] = value
    return result


class ForwardReferenceHealth:
    def __init__(self, session_factory, *, endpoint_reader=None, now=lambda: datetime.now(UTC)):
        self._factory = session_factory
        self._endpoint_reader = endpoint_reader
        self._now = now

    def read(self, *, products=()) -> dict[str, object]:
        with self._factory() as session, readonly_transaction(session, timeout_seconds=15):
            streams = session.scalars(select(ReferenceStream).where(
                ReferenceStream.recording_mode == "forward_observation",
            ).order_by(ReferenceStream.stream_id)).all()
            keys = {(stream.product.lower(), stream.frequency) for stream in streams
                    if stream.strategy_code.replace("-", "_").startswith("newow_")
                    and stream.frequency in {"1d", "1w", "60m"}}
            keys.update((product.lower(), frequency) for product in products
                        for frequency in ("1d", "1w", "60m"))
            endpoints = self._endpoint_reader(session, tuple(sorted(keys)), self._now()) if self._endpoint_reader and keys else {}
            public_endpoints = [{"product": product, "frequency": frequency, **value}
                                for (product, frequency), value in sorted(endpoints.items())]
            if not streams:
                return {"enabled_count": 0, "streams": [], "source_endpoints": public_endpoints}
            ids = [stream.stream_id for stream in streams]
            b, s = ReferenceBatch, ReferenceStream
            active = and_(b.stream_id == s.stream_id, b.revision_id == s.active_revision_id)
            pending = {
                row[0]: row[1:] for row in session.execute(select(
                    b.stream_id, func.count(b.batch_id), func.min(b.observed_at),
                ).join(s, active).where(
                    b.stream_id.in_(ids), b.kind == "capture",
                    b.consumed_by_batch_id.is_(None),
                ).group_by(b.stream_id))
            }
            observed = and_(b.kind == "calculation", b.observed_at.is_not(None),
                            b.observed_at >= s.recording_start)
            calculations = {
                row[0]: row[1:] for row in session.execute(select(
                    b.stream_id, func.max(case((observed, b.processed_at))), func.max(b.computed_through),
                    func.max(b.seq), func.max(case((b.observed_at.is_(None), b.computed_through))),
                    func.max(case((observed, b.computed_through))), func.max(case((observed, b.observed_at))),
                ).join(s, active).where(
                    b.stream_id.in_(ids), b.kind.in_(("seed_seal", "calculation")),
                    ~b.batch_key.like("forward:observation-gap:%"), b.seq <= s.latest_seq,
                ).group_by(b.stream_id))
            }
            gaps = dict(session.execute(select(
                b.stream_id, func.max(b.observed_at),
            ).join(s, active).where(
                b.stream_id.in_(ids), b.kind == "calculation",
                b.batch_key.like("forward:observation-gap:%"), b.seq <= s.latest_seq,
            ).group_by(b.stream_id)).all())
            r = ReferenceCaptureReconciliation
            mismatches = dict(session.execute(select(
                b.stream_id, func.count(r.reconciliation_id),
            ).join(r, r.capture_batch_id == b.batch_id).join(s, active).where(
                b.stream_id.in_(ids), b.kind == "capture", r.status == "mismatch",
            ).group_by(b.stream_id)).all())
            latest = select(b.stream_id, func.max(b.seq).label("seq")).join(s, active).where(
                b.stream_id.in_(ids), b.kind == "calculation", b.seq <= s.latest_seq,
                ~b.batch_key.like("forward:observation-gap:%"),
            ).group_by(b.stream_id).subquery()
            from app.reference_trading.scheduled_reconciliation import capture_reconciliation_statuses

            latest_capture = select(
                b.stream_id, b.batch_id,
                func.row_number().over(partition_by=b.stream_id,
                    order_by=(b.observed_at.desc(), b.batch_id.desc())).label("position"),
            ).join(s, active).where(b.stream_id.in_(ids), b.kind == "capture").subquery()
            capture_ids = dict(session.execute(select(
                latest_capture.c.stream_id, latest_capture.c.batch_id,
            ).where(latest_capture.c.position == 1)).all())
            reconciliation = capture_reconciliation_statuses(session, tuple(capture_ids.values()))
            states = {}
            state_sources = {}
            observed_days = {}
            starts = {stream.stream_id: stream.recording_start for stream in streams}
            for batch in session.scalars(select(b).join(
                latest, (b.stream_id == latest.c.stream_id) & (b.seq == latest.c.seq),
            ).join(s, active)):
                presentation = batch.source_evidence.get("presentation_v1")
                if presentation is not None:
                    points = require_envelope(presentation)
                    state_point = next((
                        point for point in reversed(points)
                        if point.get("kind") == "indicator" and isinstance(point.get("value"), dict)
                        and point["value"].get("version") == "newow_bar_state_v1"
                    ), None)
                    states[batch.stream_id] = state_point["value"] if state_point else None
                    if state_point is not None:
                        state_sources[batch.stream_id] = "observed" if batch.observed_at is not None and stream_time_valid(batch.observed_at, starts[batch.stream_id]) else "historical_seed"
                        if state_sources[batch.stream_id] == "observed":
                            day = state_point.get("trading_day")
                            from app.reference_trading.presentation import PresentationUnavailable
                            try:
                                if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
                                    raise ValueError
                            except ValueError as error:
                                raise PresentationUnavailable("PRESENTATION_CORRUPT") from error
                            observed_days[batch.stream_id] = day
            items = []
            for stream in streams:
                count, oldest = pending.get(stream.stream_id, (0, None))
                success, computed, _seq, historical, observed_end, last_observed = calculations.get(stream.stream_id, (None,) * 6)
                gap = gaps.get(stream.stream_id)
                items.append({
                    "stream_id": stream.stream_id, "enabled": stream.enabled,
                    "strategy_code": stream.strategy_code, "product": stream.product,
                    "frequency": stream.frequency, "active_revision_id": stream.active_revision_id,
                    "activation_generation": stream.activation_generation,
                    "recording_start": _iso(stream.recording_start),
                    "computed_through": _iso(computed),
                    "observation_boundary_at": _iso(gap),
                    "historical_computed_through": _iso(historical),
                    "observed_through": _iso(observed_end),
                    "last_observed_at": _iso(last_observed),
                    "latest_state_source": state_sources.get(stream.stream_id),
                    "latest_observed_trading_day": observed_days.get(stream.stream_id),
                    **endpoints.get((stream.product.lower(), stream.frequency), {
                        "expected_through": None, "expected_source": "canonical_completed",
                        "endpoint_status": "UNKNOWN", "endpoint_reason": "ENDPOINT_NOT_VERIFIED",
                    }),
                    "last_success": _iso(success),
                    "latest_reconciliation_status": reconciliation.get(capture_ids.get(stream.stream_id)),
                    "pending_capture_count": count,
                    "oldest_pending_observed_at": _iso(oldest),
                    "reconciliation_mismatch_count": mismatches.get(stream.stream_id, 0),
                    "status": stream.health, "latest_state": states.get(stream.stream_id),
                })
            return {"enabled_count": sum(item["enabled"] is True for item in items), "streams": items,
                    "source_endpoints": public_endpoints}


def stream_time_valid(observed, start):
    if start is None:
        return False
    return observed.replace(tzinfo=observed.tzinfo or UTC) >= start.replace(tzinfo=start.tzinfo or UTC)


def _iso(value):
    return value.replace(tzinfo=value.tzinfo or UTC).isoformat() if value is not None else None
