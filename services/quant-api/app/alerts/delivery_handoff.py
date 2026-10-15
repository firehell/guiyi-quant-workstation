"""Ephemeral, bounded Alert delivery. Database rows are receipts, never a send queue."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from threading import Condition, Thread
from time import monotonic

from sqlalchemy import select, update

from app.alerts.models import AlertEvent
from app.alerts.notification import (
    AlertNotificationDispatcher,
    AlertNotificationMessage,
    NotificationTransportError,
    ProviderAcceptance,
    _notification_policy,
)

NOTIFICATION_POLICY_VERSION = "alert_memory_batch_v2"


@dataclass(frozen=True, slots=True)
class FrozenHandoff:
    event_id: int
    message: AlertNotificationMessage
    source_observation_id: str | None
    generation: int


def notification_batch_key(item: FrozenHandoff) -> tuple[object, ...]:
    message = item.message
    policy = _notification_policy(message.rule_code)
    return (
        message.rule_code,
        policy.audience,
        message.frequency,
        message.bar_end,
        NOTIFICATION_POLICY_VERSION,
        item.generation,
    )


def _utc(value: datetime) -> datetime:
    # SQLite drops timezone annotations; production PostgreSQL retains them.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class BoundedNotificationHandoff:
    def __init__(
        self,
        *,
        session_factory,
        sender: AlertNotificationDispatcher,
        assert_owned: Callable[[], None],
        clock: Callable[[], datetime],
        generation: int,
        on_result: Callable[[tuple[int, ...], str, str | None], None] | None = None,
        capacity: int = 512,
        coalesce_seconds: float = 1.0,
    ) -> None:
        if not 1 <= capacity <= 512 or not 0 <= coalesce_seconds <= 1 or generation < 1:
            raise ValueError("ALERT_HANDOFF_CONFIGURATION_INVALID")
        self._sessions, self._sender = session_factory, sender
        self._assert_owned, self._clock = assert_owned, clock
        self._generation, self._on_result = generation, on_result
        self._capacity, self._coalesce = capacity, coalesce_seconds
        self._condition = Condition()
        self._pending: deque[tuple[float, FrozenHandoff]] = deque()
        self._closed = False
        self._inflight_count = 0
        self._started = False
        self._thread: Thread | None = None
        self._fatal: BaseException | None = None

    @property
    def fatal_error(self) -> BaseException | None:
        with self._condition:
            return self._fatal

    def check_health(self) -> None:
        if self.fatal_error is not None:
            raise RuntimeError("ALERT_HANDOFF_FATAL") from self.fatal_error

    def start(self) -> None:
        with self._condition:
            if self._started or self._closed:
                raise RuntimeError("ALERT_HANDOFF_ALREADY_STARTED_OR_CLOSED")
            self._assert_owned()
            # Only terminalize orphan receipts. Never reconstruct or resend work.
            with self._sessions() as session:
                session.execute(
                    update(AlertEvent)
                    .where(
                        AlertEvent.notification_policy_version
                        == NOTIFICATION_POLICY_VERSION,
                        AlertEvent.notification_status == "HANDOFF_PENDING",
                    )
                    .values(
                        notification_status="LOST_HANDOFF_NO_SEND",
                        notification_finished_at=self._clock(),
                    )
                )
                session.commit()
            self._started = True
            self._thread = Thread(
                target=self._run, name="alert-delivery-v2", daemon=False
            )
            self._thread.start()

    def submit(self, item: FrozenHandoff) -> bool:
        if item.generation != self._generation or item.event_id < 1:
            raise ValueError("ALERT_HANDOFF_IDENTITY_INVALID")
        notification_batch_key(item)
        with self._condition:
            self.check_health()
            if not self._started:
                raise RuntimeError("ALERT_HANDOFF_NOT_STARTED")
            if (
                self._closed
                or len(self._pending) + self._inflight_count >= self._capacity
            ):
                self._terminal(
                    (item,),
                    "DRAIN_CANCELLED_NO_SEND" if self._closed else "OVERFLOW_NO_SEND",
                )
                return False
            if any(entry.event_id == item.event_id for _, entry in self._pending):
                raise ValueError("ALERT_HANDOFF_DUPLICATE")
            self._pending.append((monotonic(), item))
            self._condition.notify_all()
            return True

    def close_and_drain(self) -> None:
        with self._condition:
            self._closed = True
            items = tuple(item for _, item in self._pending)
            self._pending.clear()
            if items:
                try:
                    self._terminal(items, "DRAIN_CANCELLED_NO_SEND")
                except BaseException as exc:
                    self._fatal = exc
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join()
        if self.fatal_error is not None:
            raise RuntimeError("ALERT_HANDOFF_FATAL") from self.fatal_error

    def _report(self, items, status: str, diagnostic: str | None = None) -> None:
        if self._on_result is not None:
            self._on_result(tuple(item.event_id for item in items), status, diagnostic)

    def _validate_pending_receipts(self, session, items) -> None:
        rows = session.scalars(
            select(AlertEvent).where(
                AlertEvent.id.in_([item.event_id for item in items])
            )
        ).all()
        by_id = {row.id: row for row in rows}
        for item in items:
            row = by_id.get(item.event_id)
            if (
                row is None
                or row.notification_policy_version != NOTIFICATION_POLICY_VERSION
                or row.notification_generation != self._generation
                or row.notification_status != "HANDOFF_PENDING"
                or row.notification_attempted_at is not None
                or row.rule.rule_code != item.message.rule_code
                or tuple(row.result_codes) != item.message.result_codes
                or _utc(row.detected_at) != _utc(item.message.detected_at)
                or (row.source_observed_at is None)
                != (item.message.source_observed_at is None)
                or (
                    row.source_observed_at is not None
                    and _utc(row.source_observed_at)
                    != _utc(item.message.source_observed_at)
                )
                or row.symbol != item.message.symbol
                or row.contract != item.message.contract
                or row.frequency != item.message.frequency
                or _utc(row.bar_end) != _utc(item.message.bar_end)
                or row.source_observation_id != item.source_observation_id
            ):
                raise RuntimeError("ALERT_HANDOFF_RECEIPT_IDENTITY_INVALID")

    def _terminal(self, items, status: str) -> None:
        try:
            self._commit_terminal(items, status)
        except BaseException as exc:
            with self._condition:
                self._fatal = exc
                self._closed = True
                self._condition.notify_all()
            raise

    def _commit_terminal(self, items, status: str) -> None:
        self._assert_owned()
        with self._sessions() as session:
            self._validate_pending_receipts(session, items)
            result = session.execute(
                update(AlertEvent)
                .where(
                    AlertEvent.id.in_([item.event_id for item in items]),
                    AlertEvent.notification_generation == self._generation,
                    AlertEvent.notification_policy_version
                    == NOTIFICATION_POLICY_VERSION,
                    AlertEvent.notification_status == "HANDOFF_PENDING",
                    AlertEvent.notification_attempted_at.is_(None),
                )
                .values(
                    notification_status=status, notification_finished_at=self._clock()
                )
            )
            if result.rowcount != len(items):
                raise RuntimeError("ALERT_HANDOFF_TERMINAL_CONFLICT")
            session.commit()
        self._report(items, status)

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    while not self._pending and not self._closed:
                        self._condition.wait()
                    if self._closed:
                        return
                    queued_at, first = self._pending[0]
                    now = _utc(self._clock())
                    remaining = min(
                        30
                        - (
                            now
                            - _utc(
                                item.message.source_observed_at
                                or item.message.detected_at
                            )
                        ).total_seconds()
                        for _, item in self._pending
                    )
                    delay = min(self._coalesce - (monotonic() - queued_at), remaining)
                    if delay > 0:
                        self._condition.wait(delay)
                        continue
                    key = notification_batch_key(first)
                    batch = tuple(
                        item
                        for _, item in self._pending
                        if notification_batch_key(item) == key
                    )
                    self._pending = deque(
                        (at, item)
                        for at, item in self._pending
                        if notification_batch_key(item) != key
                    )
                    self._inflight_count = len(batch)
                    # Dequeue is the in-flight boundary, serialized with admission close.
                try:
                    self._deliver(batch)
                finally:
                    with self._condition:
                        self._inflight_count = 0
        except BaseException as exc:
            with self._condition:
                self._fatal = exc
                self._closed = True
                self._condition.notify_all()

    def _deliver(self, items: tuple[FrozenHandoff, ...]) -> None:
        # Split only into disjoint payload members. Oversized individual messages never send.
        chunk: list[FrozenHandoff] = []
        for item in sorted(items, key=lambda value: value.event_id):
            try:
                self._sender.prepare_batch(
                    tuple(entry.message for entry in (*chunk, item)),
                    event_ids=tuple(entry.event_id for entry in (*chunk, item)),
                )
            except ValueError as exc:
                if str(exc) == "ALERT_NOTIFICATION_BATCH_TOO_LARGE" and chunk:
                    self._send_chunk(tuple(chunk))
                    chunk = []
                    try:
                        self._sender.prepare_batch(
                            (item.message,), event_ids=(item.event_id,)
                        )
                    except ValueError:
                        self._terminal((item,), "PREPARATION_FAILED_NO_SEND")
                        continue
                else:
                    self._terminal((item,), "PREPARATION_FAILED_NO_SEND")
                    continue
            chunk.append(item)
        if chunk:
            self._send_chunk(tuple(chunk))

    def _prepare_and_claim(self, items: tuple[FrozenHandoff, ...]):
        if self._closed:
            self._terminal(items, "DRAIN_CANCELLED_NO_SEND")
            return None
        self._assert_owned()
        now = self._clock()
        eligible: list[FrozenHandoff] = []
        expired: list[FrozenHandoff] = []
        for item in items:
            observed = item.message.source_observed_at or item.message.detected_at
            age = (_utc(now) - _utc(observed)).total_seconds()
            (eligible if 0 <= age <= 30 else expired).append(item)
        if expired:
            self._terminal(tuple(expired), "EXPIRED_NO_SEND")
        if not eligible:
            return
        items = tuple(eligible)
        checked_at = self._clock()
        try:
            prepared = self._sender.prepare_batch(
                tuple(
                    replace(item.message, notification_checked_at=checked_at)
                    for item in items
                ),
                event_ids=tuple(item.event_id for item in items),
            )
        except ValueError:
            self._terminal(items, "PREPARATION_FAILED_NO_SEND")
            return None
        identity = json.dumps(
            {
                "events": [item.event_id for item in items],
                "generation": self._generation,
                "audience": prepared.delivery.audience,
                "title": prepared.delivery.title,
                "content": prepared.delivery.content,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        batch_id = sha256(identity.encode("utf-8")).hexdigest()
        self._assert_owned()
        with self._sessions() as session:
            self._validate_pending_receipts(session, items)
            # Claim time is intentionally not proof that HTTP happened. Crash => unknown, no retry.
            claimed_at = self._clock()
            for item in items:
                observed = item.message.source_observed_at or item.message.detected_at
                if not 0 <= (_utc(claimed_at) - _utc(observed)).total_seconds() <= 30:
                    session.rollback()
                    return self._prepare_and_claim(items)
            result = session.execute(
                update(AlertEvent)
                .where(
                    AlertEvent.id.in_([item.event_id for item in items]),
                    AlertEvent.notification_policy_version
                    == NOTIFICATION_POLICY_VERSION,
                    AlertEvent.notification_generation == self._generation,
                    AlertEvent.notification_status == "HANDOFF_PENDING",
                )
                .values(
                    notification_status="ATTEMPTED_UNKNOWN",
                    notification_attempted_at=claimed_at,
                    notification_batch_id=batch_id,
                )
            )
            if result.rowcount != len(items):
                raise RuntimeError("ALERT_HANDOFF_CLAIM_CONFLICT")
            session.commit()
        self._report(items, "ATTEMPTED_UNKNOWN")
        return items, prepared, batch_id

    def _send_chunk(self, items: tuple[FrozenHandoff, ...]) -> None:
        with self._condition:
            claimed = self._prepare_and_claim(items)
        if claimed is None:
            return
        items, prepared, batch_id = claimed
        self._assert_owned()
        checked_at = self._clock()
        # A slow commit may consume the remaining window. A claimed batch is never
        # reconstituted or retried, and its frozen payload must not reach HTTP late.
        if any(
            not 0
            <= (
                _utc(checked_at)
                - _utc(item.message.source_observed_at or item.message.detected_at)
            ).total_seconds()
            <= 30
            for item in items
        ):
            self._finish_result(items, batch_id, "CLAIM_EXPIRED_NO_SEND", None, None)
            return
        try:
            acceptance = self._sender.send_prepared_batch(prepared)
            if not isinstance(acceptance, ProviderAcceptance):
                raise NotificationTransportError(
                    diagnostic_code="PUSHPLUS_ACCEPTANCE_INVALID"
                )
            reference = acceptance.reference
            if reference is not None and (
                not isinstance(reference, str)
                or not reference.strip()
                or len(reference) > 128
            ):
                raise NotificationTransportError(
                    diagnostic_code="PUSHPLUS_ACCEPTANCE_INVALID"
                )
            status, diagnostic = "PROVIDER_ACCEPTED", None
        except Exception as exc:
            reference = None
            status = "FAILED_OR_UNKNOWN"
            diagnostic = (
                exc.diagnostic_code
                if isinstance(exc, NotificationTransportError)
                else "UNKNOWN"
            )
        self._finish_result(items, batch_id, status, reference, diagnostic)

    def _finish_result(self, items, batch_id, status, reference, diagnostic) -> None:
        self._assert_owned()
        with self._sessions() as session:
            result = session.execute(
                update(AlertEvent)
                .where(
                    AlertEvent.id.in_([item.event_id for item in items]),
                    AlertEvent.notification_status == "ATTEMPTED_UNKNOWN",
                    AlertEvent.notification_batch_id == batch_id,
                )
                .values(
                    notification_status=status,
                    notification_finished_at=self._clock(),
                    notification_provider_reference=reference,
                )
            )
            if result.rowcount != len(items):
                raise RuntimeError("ALERT_HANDOFF_RESULT_CONFLICT")
            session.commit()
        self._report(items, status, diagnostic)
