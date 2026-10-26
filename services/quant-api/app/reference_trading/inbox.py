"""Durable Reference input receipts; this inbox is never a market authority.

Ingest commits the exact source and its frozen routes before a Redis ACK. No
operation here acknowledges Redis, retries a source, deletes or trims receipts.
PostgreSQL capacity checks use a transaction advisory lock at READ COMMITTED;
SQLite supports deterministic unit fixtures only, not concurrency guarantees.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import json
import re

from sqlalchemy import case, exists, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.market_data.domain import BarFrequency, normalize_contract_for_symbol
from app.market_data.live_market import LIVE_BAR_CHANNEL_PREFIX
from app.market_data.observation_stream import ObservationEnvelope
from app.reference_trading.models import (
    ReferenceActivationReceipt, ReferenceBatch, ReferenceInboxDelivery,
    ReferenceInboxInput, ReferenceRevision, ReferenceStream,
)

DAILY_LIMIT = 120_000
UNFINISHED_BYTES_LIMIT = 6 * 1024**3
_MAX_ENVELOPE_BYTES = 262_144
_CAPACITY_LOCK = 0x47554959494E4258
_JOURNAL_ID = re.compile(r"(0|[1-9][0-9]{0,19})-(0|[1-9][0-9]{0,19})\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")


class InboxConflict(RuntimeError):
    """Known fail-closed identity, ordering or capacity failure."""


class InboxCommitUnknown(RuntimeError):
    """A fresh read did not prove the commit; callers must not retry sources."""


@dataclass(frozen=True, slots=True)
class InboxReceipt:
    input_id: str
    journal_id: str
    delivery_ids: tuple[str, ...]
    duplicate: bool


@dataclass(frozen=True, slots=True)
class InboxDelivery:
    delivery_id: str
    input_id: str
    stream_id: str
    revision_id: str
    generation: int
    activation_receipt_id: str
    status: str
    code: str | None
    envelope: ObservationEnvelope
    ingested_at: datetime
    calculated_at: datetime | None
    calculation_batch_id: str | None
    legacy_capture_batch_id: str | None = None


def _aware(value: datetime) -> datetime:
    # SQLite loses timezone metadata; persisted production columns are timestamptz.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _time(value: datetime | None) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("REFERENCE_INBOX_TIME_INVALID")
    return value


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _envelope(event: ObservationEnvelope):
    if not isinstance(event, ObservationEnvelope):
        raise TypeError("envelope must be ObservationEnvelope")
    match = _JOURNAL_ID.fullmatch(event.stream_id) if isinstance(event.stream_id, str) else None
    if match is None or any(int(part) > 2**64 - 1 for part in match.groups()):
        raise ValueError("REFERENCE_INBOX_JOURNAL_ID_INVALID")
    confirmed = _time(event.confirmed_at)
    try:
        prefix = LIVE_BAR_CHANNEL_PREFIX + ":"
        if not event.channel.startswith(prefix):
            raise ValueError
        product, frequency = event.channel[len(prefix):].split(":")
        if not re.fullmatch("[a-z]{1,32}", product):
            raise ValueError
        BarFrequency(frequency)
        end = _time(datetime.fromisoformat(event.data["bar_end"]))
        if date.fromisoformat(event.data["trading_day"]) != event.trading_day or end > confirmed:
            raise ValueError
        contract = event.data["contract"]
        if normalize_contract_for_symbol(product, contract) != contract:
            raise ValueError
        if len(event.observation_id) > 256:
            raise ValueError
        canonical = event.to_json()
        content = {"journal_id": event.stream_id, "envelope": json.loads(canonical)}
        size = len(json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        if size > _MAX_ENVELOPE_BYTES:
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("REFERENCE_INBOX_ENVELOPE_INVALID") from error
    return product, frequency, end, canonical, _digest(content), size, tuple(map(int, match.groups()))


def _route_identity(row: ReferenceInboxDelivery) -> list[object]:
    return [row.stream_id, row.revision_id, row.generation, row.activation_receipt_id,
            row.activation_plan_hash, _aware(row.recording_start).isoformat(), row.legacy_capture_batch_id]


def _head_query(stream_id: str):
    return (select(ReferenceInboxDelivery)
            .join(ReferenceInboxInput, ReferenceInboxInput.input_id == ReferenceInboxDelivery.input_id)
            .where(ReferenceInboxDelivery.stream_id == stream_id,
                   ReferenceInboxDelivery.status != "COMPLETED")
            .order_by(ReferenceInboxInput.trading_day, ReferenceInboxInput.journal_ms,
                      ReferenceInboxInput.journal_sequence, ReferenceInboxDelivery.delivery_id).limit(1))


def _validate_active(session, delivery: ReferenceInboxDelivery) -> None:
    stream = session.scalar(select(ReferenceStream).where(
        ReferenceStream.stream_id == delivery.stream_id).with_for_update())
    revision = session.get(ReferenceRevision, (delivery.stream_id, delivery.revision_id))
    receipt = session.get(ReferenceActivationReceipt, delivery.activation_receipt_id)
    if (stream is None or not stream.enabled or stream.recording_mode != "forward_observation"
            or stream.active_revision_id != delivery.revision_id
            or stream.activation_generation != delivery.generation
            or stream.activation_plan_hash != delivery.activation_plan_hash
            or stream.recording_start is None
            or _aware(stream.recording_start) != _aware(delivery.recording_start)
            or revision is None or revision.status != "active"
            or receipt is None or receipt.stream_id != delivery.stream_id
            or receipt.revision_id != delivery.revision_id or receipt.generation != delivery.generation
            or receipt.disabled_at is not None or receipt.plan_hash != delivery.activation_plan_hash
            or _aware(receipt.recording_start) != _aware(delivery.recording_start)):
        raise InboxConflict("REFERENCE_INBOX_ACTIVATION_DRIFT")


def _dto(session, delivery: ReferenceInboxDelivery) -> InboxDelivery:
    item = session.get(ReferenceInboxInput, delivery.input_id)
    if item is None:
        raise InboxConflict("REFERENCE_INBOX_RECEIPT_MISSING")
    envelope = _verified_input(item)
    return InboxDelivery(delivery.delivery_id, delivery.input_id, delivery.stream_id,
        delivery.revision_id, delivery.generation, delivery.activation_receipt_id,
        delivery.status, delivery.code,
        envelope,
        _aware(item.ingested_at), _aware(delivery.calculated_at) if delivery.calculated_at else None,
        delivery.calculation_batch_id, delivery.legacy_capture_batch_id)


def _verified_input(item: ReferenceInboxInput) -> ObservationEnvelope:
    try:
        envelope = ObservationEnvelope.from_json(item.canonical_envelope, stream_id=item.journal_id)
        product, frequency, end, canonical, digest, size, order = _envelope(envelope)
        if (canonical != item.canonical_envelope or digest != item.envelope_sha256 or size != item.payload_bytes
                or envelope.trading_day != item.trading_day or envelope.observation_id != item.observation_id
                or product != item.product or frequency != item.frequency or end != _aware(item.bar_end)
                or order != (item.journal_ms, item.journal_sequence)
                or envelope.source_observed_at != _aware(item.source_observed_at)
                or envelope.confirmed_at != _aware(item.confirmed_at)
                or envelope.raw_received_at != (_aware(item.raw_received_at) if item.raw_received_at else None)):
            raise ValueError
        return envelope
    except (KeyError, TypeError, ValueError):
        raise InboxConflict("REFERENCE_INBOX_CONTENT_CONFLICT") from None


def _exact_legacy_capture(capture, delivery, envelope) -> bool:
    from app.market_data.live_market import _bar_from_payload
    from app.reference_trading.capture import ForwardCapture
    from app.reference_trading.forward_inputs import _bar_wire

    proof = capture.source_evidence.get("forward_capture_v1", {})
    source = proof.get("source_proof", {})
    try:
        reconstructed = ForwardCapture(capture.stream_id, capture.revision_id, proof["generation"],
            proof["source_key"], datetime.fromisoformat(proof["bar_end"]),
            datetime.fromisoformat(proof["observed_at"]), proof["source_kind"],
            proof["input_payload"], source, proof["eligibility"])
        return (capture.kind == "capture" and capture.stream_id == delivery.stream_id
            and capture.revision_id == delivery.revision_id
            and reconstructed.capture_hash == capture.payload_hash == proof["hash"]
            and reconstructed.generation == delivery.generation
            and reconstructed.source_kind == "completed_live"
            and reconstructed.observed_at == envelope.confirmed_at
            and reconstructed.bar_end == datetime.fromisoformat(envelope.data["bar_end"])
            and reconstructed.input_payload.get("contract") == envelope.data["contract"]
            and reconstructed.input_payload.get("bar") == _bar_wire(_bar_from_payload(json.dumps(envelope.data)))
            and source.get("journal_stream_id", source.get("journal_id")) == envelope.stream_id
            and source.get("journal_envelope_sha256") == sha256(envelope.to_json().encode()).hexdigest()
            and datetime.fromisoformat(source["raw_received_at"]) == (envelope.raw_received_at or envelope.source_observed_at)
            and datetime.fromisoformat(source["confirmed_at"]) == envelope.confirmed_at)
    except (KeyError, TypeError, ValueError):
        return False


def _exact_fusion_capture(capture, delivery, envelope) -> bool:
    from app.market_data.live_market import _bar_from_payload
    from app.reference_trading.capture import ForwardCapture
    from app.reference_trading.forward_inputs import _bar_wire

    proof = capture.source_evidence.get("forward_capture_v1", {})
    source = proof.get("source_proof", {})
    try:
        reconstructed = ForwardCapture(capture.stream_id, capture.revision_id, proof["generation"],
            proof["source_key"], datetime.fromisoformat(proof["bar_end"]),
            datetime.fromisoformat(proof["observed_at"]), proof["source_kind"],
            proof["input_payload"], source, proof["eligibility"])
        sources = reconstructed.input_payload["sources"]
        expected_bar = _bar_wire(_bar_from_payload(json.dumps(envelope.data)))
        return (capture.kind == "capture" and capture.stream_id == delivery.stream_id
            and capture.revision_id == delivery.revision_id and reconstructed.generation == delivery.generation
            and reconstructed.capture_hash == capture.payload_hash == proof["hash"]
            and reconstructed.source_kind == "completed_fusion_sources"
            and reconstructed.observed_at == envelope.confirmed_at
            and reconstructed.bar_end == datetime.fromisoformat(envelope.data["bar_end"])
            and source.get("journal_stream_id") == envelope.stream_id
            and source.get("journal_envelope_sha256") == sha256(envelope.to_json().encode()).hexdigest()
            and datetime.fromisoformat(source["raw_received_at"]) == (envelope.raw_received_at or envelope.source_observed_at)
            and datetime.fromisoformat(source["confirmed_at"]) == envelope.confirmed_at
            and isinstance(sources, list) and len(sources) == 2
            and all(dependency["capture"]["input_payload"]["contract"] == envelope.data["contract"]
                    and dependency["capture"]["input_payload"]["bar"] == expected_bar
                    for dependency in sources))
    except (KeyError, TypeError, ValueError):
        return False


def _legacy_calculation(session, capture):
    calculation = session.get(ReferenceBatch, capture.consumed_by_batch_id) if capture.consumed_by_batch_id else None
    proof = calculation.source_evidence.get("forward_capture_v1", {}) if calculation else {}
    if (calculation is None or calculation.kind != "calculation" or calculation.outcome != "committed"
            or calculation.seq is None or calculation.stream_id != capture.stream_id
            or calculation.revision_id != capture.revision_id
            or proof.get("capture_id") != capture.batch_id or proof.get("hash") != capture.payload_hash):
        raise InboxConflict("REFERENCE_INBOX_LEGACY_CALCULATION_CONFLICT")
    return calculation


def _reconcile_legacy(session, delivery, envelope, ingested_at):
    capture = session.scalar(select(ReferenceBatch).where(
        ReferenceBatch.stream_id == delivery.stream_id, ReferenceBatch.revision_id == delivery.revision_id,
        ReferenceBatch.batch_key == "capture:" + envelope.data["contract"] + ":" + envelope.data["bar_end"]))
    if capture is None:
        return
    delivery.legacy_capture_batch_id = capture.batch_id
    if not _exact_legacy_capture(capture, delivery, envelope):
        delivery.status, delivery.code, delivery.blocked_at = (
            "BLOCKED", "REFERENCE_INBOX_LEGACY_EVIDENCE_INCOMPLETE", ingested_at)
        return
    if capture.consumed_by_batch_id is not None:
        calculation = _legacy_calculation(session, capture)
        delivery.status = "COMPLETED"
        delivery.calculation_batch_id = calculation.batch_id
        delivery.calculated_at = calculation.processed_at


class ReferenceInboxRepository:
    def __init__(self, session_factory: Callable, *, daily_limit: int = DAILY_LIMIT,
                 unfinished_bytes_limit: int = UNFINISHED_BYTES_LIMIT, fault_injector=None):
        if (type(daily_limit) is not int or not 1 <= daily_limit <= DAILY_LIMIT
                or type(unfinished_bytes_limit) is not int
                or not 1 <= unfinished_bytes_limit <= UNFINISHED_BYTES_LIMIT):
            raise ValueError("REFERENCE_INBOX_CAPACITY_INVALID")
        self._session_factory = session_factory
        self._daily_limit = daily_limit
        self._unfinished_bytes_limit = unfinished_bytes_limit
        self._fault = fault_injector or (lambda _: None)

    def _existing(self, session, day, journal_id, canonical, envelope_hash):
        item = session.scalar(select(ReferenceInboxInput).where(
            ReferenceInboxInput.trading_day == day, ReferenceInboxInput.journal_id == journal_id))
        if item is None:
            return None
        if item.envelope_sha256 != envelope_hash or item.canonical_envelope != canonical:
            raise InboxConflict("REFERENCE_INBOX_CONTENT_CONFLICT")
        _verified_input(item)
        deliveries = session.scalars(select(ReferenceInboxDelivery).where(
            ReferenceInboxDelivery.input_id == item.input_id).order_by(ReferenceInboxDelivery.stream_id)).all()
        if (len(deliveries) != item.target_count
                or _digest([_route_identity(row) for row in deliveries]) != item.routing_sha256):
            raise InboxConflict("REFERENCE_INBOX_ROUTING_CONFLICT")
        return InboxReceipt(item.input_id, journal_id, tuple(row.delivery_id for row in deliveries), True)

    def ingest(self, envelope: ObservationEnvelope, *, ingested_at=None, assert_owned=None) -> InboxReceipt:
        product, frequency, end, canonical, digest, size, order = _envelope(envelope)
        ingested_at = _time(ingested_at or datetime.now(UTC))
        try:
            with self._session_factory() as session, session.begin():
                if session.get_bind().dialect.name == "postgresql":
                    if session.connection().get_isolation_level() != "READ COMMITTED":
                        raise InboxConflict("REFERENCE_INBOX_ISOLATION_INVALID")
                    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CAPACITY_LOCK})
                existing = self._existing(session, envelope.trading_day, envelope.stream_id, canonical, digest)
                if existing is not None:
                    if assert_owned:
                        assert_owned()
                    return existing
                routes = []
                if envelope.notification_eligible:
                    streams = session.scalars(select(ReferenceStream).where(
                        ReferenceStream.enabled.is_(True),
                        ReferenceStream.recording_mode == "forward_observation",
                        func.lower(ReferenceStream.product) == product,
                        ReferenceStream.frequency == frequency,
                    ).order_by(ReferenceStream.stream_id).with_for_update()).all()
                    if len(streams) > 512:
                        raise InboxConflict("REFERENCE_INBOX_SCOPE_EXCEEDED")
                    for stream in streams:
                        if stream.recording_start is None or stream.active_revision_id is None:
                            raise InboxConflict("REFERENCE_INBOX_ACTIVATION_DRIFT")
                        if end < _aware(stream.recording_start) or envelope.confirmed_at < _aware(stream.recording_start):
                            continue
                        receipt = session.scalar(select(ReferenceActivationReceipt).where(
                            ReferenceActivationReceipt.stream_id == stream.stream_id,
                            ReferenceActivationReceipt.generation == stream.activation_generation))
                        if receipt is None:
                            raise InboxConflict("REFERENCE_INBOX_ACTIVATION_DRIFT")
                        route = ReferenceInboxDelivery(
                            delivery_id=_digest([envelope.trading_day.isoformat(), envelope.stream_id, stream.stream_id]),
                            stream_id=stream.stream_id, revision_id=stream.active_revision_id,
                            generation=stream.activation_generation, activation_receipt_id=receipt.receipt_id,
                            activation_plan_hash=receipt.plan_hash, recording_start=stream.recording_start,
                            status="PENDING", created_at=ingested_at, updated_at=ingested_at)
                        _validate_active(session, route)
                        _reconcile_legacy(session, route, envelope, ingested_at)
                        routes.append(route)
                count = session.scalar(select(func.count()).select_from(ReferenceInboxInput).where(
                    ReferenceInboxInput.trading_day == envelope.trading_day))
                if count >= self._daily_limit:
                    raise InboxConflict("REFERENCE_INBOX_DAILY_CAPACITY_EXCEEDED")
                unfinished = exists(select(1).where(
                    ReferenceInboxDelivery.input_id == ReferenceInboxInput.input_id,
                    ReferenceInboxDelivery.status != "COMPLETED"))
                used = session.scalar(select(func.coalesce(func.sum(ReferenceInboxInput.payload_bytes), 0)).where(unfinished))
                if any(route.status != "COMPLETED" for route in routes) and used + size > self._unfinished_bytes_limit:
                    raise InboxConflict("REFERENCE_INBOX_UNFINISHED_CAPACITY_EXCEEDED")
                input_id = _digest([envelope.trading_day.isoformat(), envelope.stream_id])
                item = ReferenceInboxInput(
                    input_id=input_id, trading_day=envelope.trading_day, journal_id=envelope.stream_id,
                    journal_ms=order[0], journal_sequence=order[1], observation_id=envelope.observation_id,
                    product=product, frequency=frequency, canonical_envelope=canonical,
                    envelope_sha256=digest, routing_sha256=_digest([_route_identity(row) for row in routes]),
                    payload_bytes=size, target_count=len(routes), bar_end=end,
                    source_observed_at=envelope.source_observed_at, raw_received_at=envelope.raw_received_at,
                    confirmed_at=envelope.confirmed_at, ingested_at=ingested_at)
                session.add(item)
                session.flush()
                for route in routes:
                    route.input_id = input_id
                    session.add(route)
                session.flush()
                if assert_owned:
                    assert_owned()
                self._fault("before_commit")
                result = InboxReceipt(input_id, envelope.stream_id, tuple(row.delivery_id for row in routes), False)
            self._fault("after_commit")
            return result
        except SQLAlchemyError:
            # Never retry the mutation: exact independent readback alone may
            # prove success after a connection was lost during COMMIT.
            try:
                with self._session_factory() as session:
                    existing = self._existing(session, envelope.trading_day, envelope.stream_id, canonical, digest)
            except InboxConflict:
                raise
            except SQLAlchemyError:
                raise InboxCommitUnknown("REFERENCE_INBOX_COMMIT_UNKNOWN") from None
            if existing is not None:
                return existing
            raise InboxCommitUnknown("REFERENCE_INBOX_COMMIT_UNKNOWN") from None

    def pending_head(self, stream_id: str) -> InboxDelivery | None:
        with self._session_factory() as session, session.begin():
            row = session.scalar(_head_query(stream_id))
            if row is None:
                return None
            _validate_active(session, row)
            return _dto(session, row)

    def next_heads(self, *, limit: int = 32, after_stream_id: str | None = None) -> tuple[InboxDelivery, ...]:
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError("REFERENCE_INBOX_HEAD_BUDGET_INVALID")
        rank = select(ReferenceInboxDelivery.delivery_id,
            func.row_number().over(partition_by=ReferenceInboxDelivery.stream_id,
                order_by=(ReferenceInboxInput.trading_day, ReferenceInboxInput.journal_ms,
                          ReferenceInboxInput.journal_sequence, ReferenceInboxDelivery.delivery_id)).label("position")
        ).join(ReferenceInboxInput, ReferenceInboxInput.input_id == ReferenceInboxDelivery.input_id).where(
            ReferenceInboxDelivery.status != "COMPLETED").subquery()
        query = select(ReferenceInboxDelivery).join(rank,
            rank.c.delivery_id == ReferenceInboxDelivery.delivery_id).where(rank.c.position == 1)
        if after_stream_id is not None:
            query = query.order_by(case((ReferenceInboxDelivery.stream_id > after_stream_id, 0), else_=1))
        query = query.order_by(ReferenceInboxDelivery.stream_id).limit(limit)
        with self._session_factory() as session:
            return tuple(_dto(session, row) for row in session.scalars(query))

    def validate_delivery(self, delivery_id: str) -> InboxDelivery:
        with self._session_factory() as session, session.begin():
            row = session.get(ReferenceInboxDelivery, delivery_id)
            if row is None:
                raise InboxConflict("REFERENCE_INBOX_DELIVERY_MISSING")
            _validate_active(session, row)
            return _dto(session, row)

    def retained_observations(self, delivery_id: str) -> tuple[ObservationEnvelope, ...]:
        """Verified original inputs known by this delivery's original confirmation.

        These receipts supply retained Live evidence after Redis expiry; callers
        still use MDS for authoritative mapping, physical prefix and coverage.
        """
        with self._session_factory() as session, session.begin():
            delivery = session.get(ReferenceInboxDelivery, delivery_id)
            if delivery is None:
                raise InboxConflict("REFERENCE_INBOX_DELIVERY_MISSING")
            _validate_active(session, delivery)
            target = session.get(ReferenceInboxInput, delivery.input_id)
            _verified_input(target)
            rows = session.scalars(select(ReferenceInboxInput).where(
                ReferenceInboxInput.product == target.product,
                ReferenceInboxInput.frequency == target.frequency,
                ReferenceInboxInput.trading_day == target.trading_day,
                ReferenceInboxInput.bar_end <= target.bar_end,
                ReferenceInboxInput.confirmed_at <= target.confirmed_at,
            ).order_by(ReferenceInboxInput.bar_end, ReferenceInboxInput.journal_ms,
                       ReferenceInboxInput.journal_sequence).limit(DAILY_LIMIT + 1)).all()
            if len(rows) > DAILY_LIMIT:
                raise InboxConflict("REFERENCE_INBOX_RETAINED_CAPACITY_EXCEEDED")
            unique = {}
            for row in rows:
                original = _verified_input(row)
                if not original.notification_eligible:
                    continue
                key = (original.data["contract"], original.data["bar_end"])
                previous = unique.get(key)
                if previous is not None and previous.data != original.data:
                    raise InboxConflict("REFERENCE_INBOX_RETAINED_CONTENT_CONFLICT")
                if previous is None:
                    unique[key] = original
            return tuple(unique.values())

    def mark_dependency_wait(self, delivery_id: str, code: str, *, at=None) -> None:
        """Defer a causal stream dependency without scheduling data maintenance."""
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise ValueError("REFERENCE_INBOX_CODE_INVALID")
        at = _time(at or datetime.now(UTC))
        with self._session_factory() as session, session.begin():
            row = session.get(ReferenceInboxDelivery, delivery_id)
            if row is None:
                raise InboxConflict("REFERENCE_INBOX_DELIVERY_MISSING")
            _validate_active(session, row)
            row = session.scalar(select(ReferenceInboxDelivery).where(
                ReferenceInboxDelivery.delivery_id == delivery_id).with_for_update())
            if row.status != "PENDING":
                raise InboxConflict("REFERENCE_INBOX_STATE_CONFLICT")
            head = session.scalar(_head_query(row.stream_id))
            if head is None or head.delivery_id != delivery_id:
                raise InboxConflict("REFERENCE_INBOX_ORDER_CONFLICT")
            row.code, row.updated_at = code, at

    def _mark(self, delivery_id: str, status: str, code: str, *, at=None) -> None:
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise ValueError("REFERENCE_INBOX_CODE_INVALID")
        at = _time(at or datetime.now(UTC))
        with self._session_factory() as session, session.begin():
            row = session.scalar(select(ReferenceInboxDelivery).where(
                ReferenceInboxDelivery.delivery_id == delivery_id).with_for_update())
            if row is None:
                raise InboxConflict("REFERENCE_INBOX_DELIVERY_MISSING")
            if row.status not in {"PENDING", "WAITING_HISTORY"} and row.status != status:
                raise InboxConflict("REFERENCE_INBOX_STATE_CONFLICT")
            row.status, row.code, row.updated_at = status, code, at
            field = {"WAITING_HISTORY": "waiting_at", "BLOCKED": "blocked_at", "UNKNOWN": "unknown_at"}[status]
            if getattr(row, field) is None:
                setattr(row, field, at)

    def mark_waiting(self, delivery_id: str, code: str, *, at=None) -> None:
        self._mark(delivery_id, "WAITING_HISTORY", code, at=at)

    def mark_blocked(self, delivery_id: str, code: str, *, at=None) -> None:
        self._mark(delivery_id, "BLOCKED", code, at=at)

    def mark_unknown(self, delivery_id: str, code: str = "REFERENCE_INBOX_COMMIT_UNKNOWN", *, at=None) -> None:
        self._mark(delivery_id, "UNKNOWN", code, at=at)

    def health(self) -> dict[str, object]:
        with self._session_factory() as session:
            # One SQL statement uses one PostgreSQL snapshot for every aggregate.
            unfinished = exists(select(1).where(
                ReferenceInboxDelivery.input_id == ReferenceInboxInput.input_id,
                ReferenceInboxDelivery.status != "COMPLETED"))
            counts = select(
                func.count().filter(ReferenceInboxDelivery.status == "PENDING").label("pending_count"),
                func.count().filter(ReferenceInboxDelivery.status == "WAITING_HISTORY").label("waiting_history_count"),
                func.count().filter(ReferenceInboxDelivery.status == "BLOCKED").label("blocked_count"),
                func.count().filter(ReferenceInboxDelivery.status == "UNKNOWN").label("unknown_count"),
                func.count().filter(ReferenceInboxDelivery.status == "COMPLETED").label("completed_count"),
                func.count().filter((ReferenceInboxDelivery.status == "PENDING") & ReferenceInboxDelivery.code.is_not(None)).label("dependency_wait_count"),
                func.count().filter(ReferenceInboxDelivery.status != "COMPLETED").label("unfinished_deliveries"),
                func.max(ReferenceInboxDelivery.calculated_at).label("last_calculated_at"),
            ).subquery()
            inputs = select(func.count().label("unfinished_inputs"),
                func.coalesce(func.sum(ReferenceInboxInput.payload_bytes), 0).label("unfinished_bytes"),
                func.min(ReferenceInboxInput.ingested_at).label("oldest_ingested_at"),
                func.min(ReferenceInboxInput.bar_end).label("oldest_original_bar_end")).where(unfinished).subquery()
            ingestion = select(func.max(ReferenceInboxInput.ingested_at).label("last_ingested_at")).scalar_subquery()
            values = dict(session.execute(select(*counts.c, *inputs.c,
                ingestion.label("last_ingested_at")).select_from(counts.join(inputs, text("true")))).mappings().one())
            for key in ("last_calculated_at", "oldest_ingested_at", "oldest_original_bar_end", "last_ingested_at"):
                values[key] = _aware(values[key]) if values[key] else None
            values["unfinished_bytes"] = int(values["unfinished_bytes"])
            # The SQL code grouping has a bounded status/code domain and returns
            # counts only, never envelopes or credentials.
            reasons = session.execute(select(ReferenceInboxDelivery.status, ReferenceInboxDelivery.code, func.count()).where(
                ReferenceInboxDelivery.status.in_(("WAITING_HISTORY", "BLOCKED", "UNKNOWN"))
                | ((ReferenceInboxDelivery.status == "PENDING") & ReferenceInboxDelivery.code.is_not(None))
            ).group_by(ReferenceInboxDelivery.status, ReferenceInboxDelivery.code)
             .order_by(ReferenceInboxDelivery.status, ReferenceInboxDelivery.code).limit(385)).all()
            values["by_code"] = tuple({"status": status, "code": code, "count": count} for status, code, count in reasons[:384])
            values["codes_truncated"] = len(reasons) > 384
            values.update(daily_limit=self._daily_limit, unfinished_bytes_limit=self._unfinished_bytes_limit)
            return values


def complete_inbox_delivery(session, stream_id: str, revision_id: str, source_evidence=None,
                            *, capture_row=None, calculation_batch_id: str,
                            calculated_at: datetime) -> bool:
    """Complete exactly one delivery in the caller's calculation transaction.

    Legacy captures without an inbox marker return False. A marked capture must
    have the same frozen owner, be the first unfinished journal row, and point
    to this exact committed calculation. No session/commit/retry is created here.
    """
    if capture_row is not None:
        source_evidence = capture_row.source_evidence
    proof = source_evidence.get("forward_capture_v1", {}) if isinstance(source_evidence, dict) else {}
    source = proof.get("source_proof", {}) if isinstance(proof, dict) else {}
    if not isinstance(source, dict) or "inbox_delivery_id" not in source:
        if capture_row is None:
            return False
        identifier = session.scalar(select(ReferenceInboxDelivery.delivery_id).where(
            ReferenceInboxDelivery.legacy_capture_batch_id == capture_row.batch_id))
        if identifier is None:
            return False
    else:
        identifier = source["inbox_delivery_id"]
    if not isinstance(identifier, str):
        raise InboxConflict("REFERENCE_INBOX_DELIVERY_ID_INVALID")
    calculated_at = _time(calculated_at)
    # Stream-before-delivery lock order matches ReferenceRepository.commit_batch.
    stream = session.scalar(select(ReferenceStream).where(ReferenceStream.stream_id == stream_id).with_for_update())
    row = session.scalar(select(ReferenceInboxDelivery).where(
        ReferenceInboxDelivery.delivery_id == identifier).with_for_update())
    if row is None or row.stream_id != stream_id or row.revision_id != revision_id or stream is None:
        raise InboxConflict("REFERENCE_INBOX_COMPLETION_CONFLICT")
    if row.status == "COMPLETED":
        if row.calculation_batch_id != calculation_batch_id or _aware(row.calculated_at) != calculated_at:
            raise InboxConflict("REFERENCE_INBOX_COMPLETION_CONFLICT")
        return True
    _validate_active(session, row)
    if row.status not in {"PENDING", "WAITING_HISTORY"}:
        raise InboxConflict("REFERENCE_INBOX_STATE_CONFLICT")
    head = session.scalar(_head_query(stream_id))
    if head is None or head.delivery_id != row.delivery_id:
        raise InboxConflict("REFERENCE_INBOX_ORDER_CONFLICT")
    calculation = session.get(ReferenceBatch, calculation_batch_id)
    if (calculation is None or calculation.stream_id != stream_id or calculation.revision_id != revision_id
            or calculation.kind != "calculation" or calculation.outcome != "committed"
            or calculation.seq is None):
        raise InboxConflict("REFERENCE_INBOX_CALCULATION_CONFLICT")
    if capture_row is not None:
        item = session.get(ReferenceInboxInput, row.input_id)
        envelope = _verified_input(item)
        if row.legacy_capture_batch_id is not None and row.legacy_capture_batch_id != capture_row.batch_id:
            raise InboxConflict("REFERENCE_INBOX_CAPTURE_CONFLICT")
        if not _exact_legacy_capture(capture_row, row, envelope):
            if not _exact_fusion_capture(capture_row, row, envelope):
                raise InboxConflict("REFERENCE_INBOX_CAPTURE_CONFLICT")
    if capture_row is not None and (
            capture_row.kind != "capture" or capture_row.stream_id != stream_id
            or capture_row.revision_id != revision_id or capture_row.consumed_by_batch_id != calculation_batch_id):
        raise InboxConflict("REFERENCE_INBOX_CAPTURE_CONFLICT")
    row.status, row.code = "COMPLETED", None
    row.calculation_batch_id, row.calculated_at, row.updated_at = calculation_batch_id, calculated_at, calculated_at
    session.flush()
    return True
