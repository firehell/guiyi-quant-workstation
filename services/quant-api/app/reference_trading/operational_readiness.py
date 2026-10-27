"""Prove durable receiving independently of Reference calculation health.

No state, cursor, protocol, schema or strategy is changed here. Only exact frozen
inbox heads can explain an operational receiving wait or a not-yet-calculated
backlog. Any unknown identity, intake, schema or DB result keeps the old gate.
"""
from __future__ import annotations

from datetime import UTC, datetime
from itertools import islice
import re

from sqlalchemy import func, select, tuple_

from app.db.readonly import readonly_transaction
from app.reference_trading.inbox import _aware, _digest, _route_identity, _validate_active, _verified_input
from app.reference_trading.models import (
    ReferenceActivationReceipt, ReferenceInboxDelivery, ReferenceInboxInput,
    ReferenceRevision, ReferenceStream,
)

from app.reference_trading.repository import _identity_from_row

KIND = "reference_receiving_operational_v1"
WAIT_REASONS = frozenset({"SUBING_PHYSICAL_PREFIX_UNAVAILABLE", "MARKET_READ_CONTRACT_HISTORY_UNAVAILABLE", "SOURCE_BUSY"})
MAX_HEADS = 4096
MAX_ROUTES = 65536


def valid_receiving_wait_proof(value):
    """Shared pure shape check for owner reporting and independent Gate readback."""
    try:
        return (isinstance(value, dict) and set(value) == {"schema_version", "kind", "waiting_count",
                    "pending_count", "blocked_pairs_sha256", "heads_sha256"}
                and type(value["schema_version"]) is int and value["schema_version"] == 1 and value["kind"] == KIND
                and all(type(value[key]) is int and 0 <= value[key] <= MAX_HEADS
                        for key in ("waiting_count", "pending_count"))
                and value["waiting_count"] + value["pending_count"] <= MAX_HEADS
                and all(isinstance(value[key], str) and re.fullmatch(r"[0-9a-f]{64}", value[key]) is not None
                        for key in ("blocked_pairs_sha256", "heads_sha256")))
    except (KeyError, TypeError, ValueError):
        return False


def _build(session_factory, expected_pairs):
    try:
        with session_factory() as session, readonly_transaction(session, timeout_seconds=20):
            from app.reference_trading.inbox_recovery import verified_resolution_ids
            resolved = verified_resolution_ids(session)
            unresolved = ReferenceInboxDelivery.delivery_id.not_in(resolved)
            unsafe = session.scalar(select(select(1).select_from(ReferenceInboxDelivery).where(
                ReferenceInboxDelivery.status.in_(("BLOCKED", "UNKNOWN")), unresolved).exists()))
            if unsafe:
                return None
            rank = select(ReferenceInboxDelivery.delivery_id,
                func.row_number().over(partition_by=ReferenceInboxDelivery.stream_id,
                    order_by=(ReferenceInboxInput.trading_day, ReferenceInboxInput.journal_ms,
                              ReferenceInboxInput.journal_sequence, ReferenceInboxDelivery.delivery_id)).label("position")
            ).outerjoin(ReferenceInboxInput, ReferenceInboxInput.input_id == ReferenceInboxDelivery.input_id).where(
                ReferenceInboxDelivery.status != "COMPLETED", unresolved).subquery()
            rows = session.execute(select(ReferenceInboxDelivery, ReferenceInboxInput).join(rank,
                rank.c.delivery_id == ReferenceInboxDelivery.delivery_id).outerjoin(ReferenceInboxInput,
                ReferenceInboxInput.input_id == ReferenceInboxDelivery.input_id).where(rank.c.position == 1)
                .order_by(ReferenceInboxDelivery.stream_id).limit(MAX_HEADS + 1)).all()
            if len(rows) > MAX_HEADS:
                return None
            if any(item is None or row.status not in {"WAITING_HISTORY", "PENDING"}
                   or row.status == "WAITING_HISTORY" and row.code not in WAIT_REASONS
                   or row.status == "PENDING" and row.code is not None for row, item in rows):
                return None
            waiting = tuple((row.stream_id, row.code) for row, _ in rows if row.status == "WAITING_HISTORY")
            if expected_pairs is not None and waiting != expected_pairs:
                return None
            # Keep strong ORM references so readonly _validate_active(lock=False)
            # uses the same batch-loaded repeatable snapshot without row locks.
            streams = session.scalars(select(ReferenceStream).where(
                ReferenceStream.stream_id.in_([row.stream_id for row, _ in rows]))).all()
            revisions = session.scalars(select(ReferenceRevision).where(tuple_(
                ReferenceRevision.stream_id, ReferenceRevision.revision_id).in_(
                    [(row.stream_id, row.revision_id) for row, _ in rows]))).all()
            receipts = session.scalars(select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.receipt_id.in_([row.activation_receipt_id for row, _ in rows]))).all()
            items = {item.input_id: item for _, item in rows}
            routes = session.scalars(select(ReferenceInboxDelivery).where(
                ReferenceInboxDelivery.input_id.in_(items)).order_by(
                    ReferenceInboxDelivery.input_id, ReferenceInboxDelivery.stream_id).limit(MAX_ROUTES + 1)).all()
            if len(routes) > MAX_ROUTES:
                return None
            by_input = {key: [] for key in items}
            for route in routes:
                by_input[route.input_id].append(route)
            envelopes = {}
            for input_id, item in items.items():
                envelope = _verified_input(item)
                frozen = by_input[input_id]
                if (envelope.notification_eligible is not True or len(frozen) != item.target_count
                        or _digest([_route_identity(row) for row in frozen]) != item.routing_sha256):
                    return None
                envelopes[input_id] = envelope
            stream_rows = {stream.stream_id: stream for stream in streams}
            heads = []
            for row, item in rows:
                _validate_active(session, row, lock=False)
                event = envelopes[item.input_id]
                stream = stream_rows[row.stream_id]
                identity = _identity_from_row(stream)
                identity_hash = identity.stream_id.removeprefix("reference-stream:")
                # Frozen revision/generation alone cannot prove what strategy,
                # product or frequency currently owns this registered stream ID.
                # _verified_input already binds item product/frequency to the
                # original envelope channel; use the native routing normalization.
                if (identity.stream_id != row.stream_id or stream.identity_hash != identity_hash
                        or identity.product.lower() != item.product or identity.frequency != item.frequency):
                    return None
                if event.confirmed_at < _aware(row.recording_start) or _aware(item.bar_end) < _aware(row.recording_start):
                    return None
                revision = session.get(ReferenceRevision, (row.stream_id, row.revision_id))
                heads.append([row.delivery_id, row.input_id, row.stream_id, row.revision_id, row.generation,
                    row.activation_receipt_id, row.activation_plan_hash, _aware(row.recording_start).astimezone(UTC).isoformat(),
                    row.status, row.code, item.envelope_sha256, item.routing_sha256, item.target_count,
                    revision.dependency_digest, identity_hash])
            # Referenced above by _validate_active through the identity map.
            _ = streams, revisions, receipts
            return {"schema_version": 1, "kind": KIND, "waiting_count": len(waiting),
                    "pending_count": len(rows) - len(waiting), "blocked_pairs_sha256": _digest(waiting),
                    "heads_sha256": _digest(heads)}
    except Exception:
        return None


def build_receiving_wait_proof(session_factory, blocked_pairs):
    """Exact worker blocked pairs must equal all first WAITING_HISTORY heads."""
    try:
        pairs = tuple(islice(iter(blocked_pairs), MAX_HEADS + 1))
        if (len(pairs) > MAX_HEADS or any(not isinstance(pair, (tuple, list)) or len(pair) != 2
                or not isinstance(pair[0], str) or not 1 <= len(pair[0]) <= 96
                or pair[1] not in WAIT_REASONS for pair in pairs)):
            return None
        pairs = tuple(sorted(tuple(pair) for pair in pairs))
        if len(set(pairs)) != len(pairs):
            return None
        return _build(session_factory, pairs)
    except Exception:
        return None


def _session_factory():
    from app.db.session import SessionLocal
    return SessionLocal


def _receiving_protocol():
    from app.reference_trading.inbox_protocol import build_receiving_protocol
    return build_receiving_protocol()


def _schema_ready(session_factory):
    from app.runtime_schema_compatibility import verify_installed_reference_inbox
    with session_factory() as session:
        return bool(verify_installed_reference_inbox(session))


def _now():
    return datetime.now(UTC)


def reference_waiting_history_mode(state):
    """Explicit receiving-only alternative; never reports calculation healthy."""
    try:
        proof = state["proof"]
        runtime = proof["reference_runtime"]
        receiving = proof["receiving"]
        expected = receiving["waiting_history_proof"]
        at = datetime.fromisoformat(state["at"])
        if (state.get("phase") != "active" or at.tzinfo is None or not 0 <= (_now() - at).total_seconds() <= 30
                or proof.get("cursor_validated") is not True
                or runtime.get("stage") not in {"cycle", "receiving_cycle"}
                or type(receiving.get("protocol_version")) is not int or receiving["protocol_version"] != 2
                or receiving.get("intake_error") is not None
                or not valid_receiving_wait_proof(expected)
                or type(runtime.get("blocked_count")) is not int or runtime["blocked_count"] != expected["waiting_count"]):
            return None
        protocol = _receiving_protocol()
        active = protocol.read()
        if (not active or type(active.get("schema_version")) is not int or active["schema_version"] != 1
                or not isinstance(active.get("boundaries"), dict) or type(active.get("protocol_version")) is not int or active["protocol_version"] != 2
                or active.get("status") != "active" or active.get("intake_error") is not None
                or active.get("binding") != protocol.binding):
            return None
        factory = _session_factory()
        if (not _schema_ready(factory) or _build(factory, None) != expected or protocol.read() != active
                or not 0 <= (_now() - at).total_seconds() <= 30):
            return None
        if expected["waiting_count"]:
            return "durable_receiving_waiting_history"
        return "durable_receiving_backlog" if expected["pending_count"] else "durable_receiving"
    except Exception:
        return None
