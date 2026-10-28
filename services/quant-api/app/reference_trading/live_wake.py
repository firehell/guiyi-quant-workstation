"""Redis Live PubSub hints for the durable forward reference worker."""

from __future__ import annotations

from datetime import date, datetime
from contextlib import nullcontext
import json
from time import monotonic
from typing import Any

from app.market_data.domain import BarFrequency, normalize_contract_for_symbol
from app.market_data.live_market import LIVE_BAR_CHANNEL_PREFIX
from app.market_data.market_data_service import MarketDataError
from app.reference_trading.work_control import ForwardWorkCancelled


class ForwardLiveWake:
    def __init__(self, redis: Any, repository: Any, worker: Any, market_data: Any) -> None:
        self._pubsub = redis.pubsub(ignore_subscribe_messages=False)
        self._repository = repository
        self._worker = worker
        self._market_data = market_data

    def subscribe(self) -> None:
        self._pubsub.psubscribe(f"{LIVE_BAR_CHANNEL_PREFIX}:*")
        # The first scan must happen only after the subscription is active.
        deadline = monotonic() + 5
        while monotonic() < deadline:
            message = self._pubsub.get_message(timeout=1.0)
            if isinstance(message, dict) and message.get("type") == "psubscribe":
                return
        raise RuntimeError("REFERENCE_LIVE_SUBSCRIPTION_UNAVAILABLE")

    def wait(self, seconds: float) -> None:
        for index in range(512):
            message = self._pubsub.get_message(timeout=seconds if index == 0 else 0)
            if message is None:
                return
            if isinstance(message, dict) and message.get("type") == "pmessage":
                self._on_message(message.get("channel"), message.get("data"))

    def _on_message(self, raw_channel: object, raw_data: object) -> bool:
        validated = self._validated_routes(raw_channel, raw_data)
        if validated is None:
            return False
        end, routes = validated
        for stream_id in routes:
            self._worker.wake(stream_id, kind="live_event", bar_end=end)
        return True

    def _validated_routes(self, raw_channel: object, raw_data: object) -> tuple[datetime, tuple[str, ...]] | None:
        try:
            channel = raw_channel.decode() if isinstance(raw_channel, bytes) else raw_channel
            data = raw_data.decode() if isinstance(raw_data, bytes) else raw_data
            if not isinstance(channel, str) or not isinstance(data, str):
                return None
            prefix = f"{LIVE_BAR_CHANNEL_PREFIX}:"
            if not channel.startswith(prefix):
                return None
            product, frequency = channel[len(prefix):].split(":", 1)
            if product != product.lower():
                return None
            BarFrequency(frequency)
            payload = json.loads(data)
            if not isinstance(payload, dict):
                return None
            end = datetime.fromisoformat(payload["bar_end"])
            day = date.fromisoformat(payload["trading_day"])
            contract = payload["contract"]
            if (end.tzinfo is None or end.utcoffset() is None
                    or normalize_contract_for_symbol(product, contract) != contract):
                return None
            owner = self._market_data.dominant_segment_for_day(product, day)
            if owner.contract != contract:
                return None
        except (AttributeError, KeyError, TypeError, ValueError, MarketDataError):
            return None
        return end, self._repository.enabled_forward_routes(product, frequency)

    def close(self) -> None:
        self._pubsub.close()


class StreamForwardLiveWake(ForwardLiveWake):
    """Ack only committed calculations or append-only known-conflict transfers."""
    def __init__(self, redis, repository, worker, market_data):
        super().__init__(redis, repository, worker, market_data)
        from app.market_data.observation_stream import ObservationStream
        self._stream = ObservationStream(redis, kind="completed")
        self.stop_requested = lambda: False
        self._retry_after = 0.0

    def subscribe(self):
        for day in self._stream.days():
            self._stream.cursor("reference", day)

    def poll(self, *, limit: int = 128) -> bool:
        """Consume a bounded batch without sleeping; True keeps foreground priority."""
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("REFERENCE_OBSERVATION_POLL_BUDGET_INVALID")
        self._last_poll_count = 0
        if monotonic() < self._retry_after:
            return False
        if self.stop_requested():
            return True
        for day in self._stream.days():
            cursor = self._stream.cursor("reference", day)
            for observation in self._stream.read("reference", day, count=limit - self._last_poll_count):
                if self.stop_requested():
                    return True
                if observation.notification_eligible:
                    confirmed = getattr(observation, "confirmed_at", None)
                    if confirmed is None:
                        raise RuntimeError("REFERENCE_COMPLETED_TIME_MISSING")
                    self._worker.source_envelope = observation
                    self._worker.source_observed_at = confirmed
                    self._worker.raw_received_at = getattr(observation, "raw_received_at", None) or observation.source_observed_at
                    try:
                        validated = self._validated_routes(observation.channel, json.dumps(observation.data))
                        if validated is None:
                            raise RuntimeError("REFERENCE_BUFFER_IDENTITY_INVALID")
                        end, routes = validated
                        self._worker.process_live_observation(routes, end)
                    except ForwardWorkCancelled:
                        return False
                    except RuntimeError as error:
                        if str(error) != "REFERENCE_BUFFER_PROCESSING_BLOCKED":
                            raise
                        # Transfer only proven conflicts. Unknown transaction outcomes,
                        # unavailable input and gaps retain the journal cursor.
                        keys = tuple(dict.fromkeys(self._worker._work_key(route) for route in routes))
                        group_routes = tuple(dict.fromkeys(route for key in keys
                            for route in self._worker._work_routes(key)))
                        relevant = {key: reason for key, reason in self._worker.health().blocked
                            if key in (*keys, *group_routes)}
                        transfer = getattr(self._repository, "quarantine_forward_observation", None)
                        if (not relevant or set(relevant.values()) != {"REFERENCE_CANONICAL_MISMATCH"}
                                or transfer is None or not transfer(group_routes, observation, assert_owned=self._worker.assert_owned)):
                            self._retry_after = monotonic() + 5.0
                            self._worker.report_health(self._worker.diagnostic_health(
                                stage="observation_blocked", ready=False))
                            return False
                        self._worker.report_health(self._worker.diagnostic_health(
                            stage="observation_quarantined", ready=False))
                    finally:
                        self._worker.source_envelope = None
                        self._worker.source_observed_at = None
                        self._worker.raw_received_at = None
                self._worker.assert_owned()
                self._stream.ack("reference", day, expected_cursor=cursor, next_id=observation.stream_id)
                cursor = observation.stream_id
                self._last_poll_count += 1
                if self._last_poll_count == limit:
                    return True
        return False

    def wait(self, seconds):
        if self.poll() or self._last_poll_count:
            return
        from time import sleep
        sleep(min(seconds, 1))


class InboxForwardLiveWake(StreamForwardLiveWake):
    """Journal intake is durable acceptance; calculation advances per stream."""

    def __init__(self, redis, repository, worker, market_data, *, inbox, request_history=lambda *_: None):
        super().__init__(redis, repository, worker, market_data)
        self._inbox = inbox
        self.request_history = request_history
        self._after_stream_id = None
        self._retry_after_by_stream = {}

    def on_receiving_round(self):
        """Owned composition attaches its separate lifecycle report here."""

    def _block_intake(self, error):
        from app.reference_trading.runtime import diagnostic_reason
        code = diagnostic_reason(str(error))
        self.intake_error = code if code != "UNCLASSIFIED_FAILURE" else "REFERENCE_INBOX_INTAKE_BLOCKED"
        callback = getattr(self, "on_intake_failure", None)
        if callback is not None:
            self._worker.assert_owned()
            callback(self.intake_error)

    def subscribe(self):
        if getattr(self, "intake_error", None):
            return
        try:
            super().subscribe()
        except Exception as error:
            self._block_intake(error)

    def poll(self, *, limit=128):
        from app.reference_trading.work_control import ForwardWorkCancelled
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("REFERENCE_OBSERVATION_POLL_BUDGET_INVALID")
        self._last_poll_count = 0
        if not getattr(self, "intake_error", None):
            try:
                self._ingest(limit=limit)
            except Exception as error:
                self._block_intake(error)
        # Already accepted originals are independent of Redis TTL and of an
        # uncertain new intake. Never reconstruct/ACK a missing Redis cursor.
        try:
            self._calculate_heads()
        except ForwardWorkCancelled:
            return False
        # A bounded intake/calculation round proves receiver liveness even while
        # the journal still has backlog. It does not claim calculation readiness.
        if not self.stop_requested():
            self.on_receiving_round()
        return self._last_poll_count == limit

    def _measure(self, stage):
        timings = getattr(self._worker, 'timings', None)
        return timings.measure(stage) if timings is not None else nullcontext()

    def has_pending_work(self):
        return self._last_poll_count == 128 or self._inbox.has_unfinished()

    def _ingest(self, *, limit):
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("REFERENCE_OBSERVATION_POLL_BUDGET_INVALID")
        self._last_poll_count = 0
        for day in self._stream.days():
            cursor = self._stream.cursor("reference", day)
            for observation in self._stream.read("reference", day, count=limit-self._last_poll_count):
                if self.stop_requested():
                    return True
                # Ingestion itself verifies immutable identity and frozen routes.
                # Do not validate against current routes before an idempotent reread.
                self._worker.assert_owned()
                # Yield only when a real original exists, never on an idle poll.
                with getattr(self._worker, "observation_priority", nullcontext)(), self._measure("ingest"):
                    self._inbox.ingest(observation, assert_owned=self._worker.assert_owned)
                self._worker.assert_owned()
                self._stream.ack("reference", day, expected_cursor=cursor,
                                 next_id=observation.stream_id)
                cursor = observation.stream_id
                self._last_poll_count += 1
                if self._last_poll_count == limit:
                    break
            if self._last_poll_count == limit:
                break

    def _calculate_heads(self):
        from app.reference_trading.runtime import failure_reason
        from app.reference_trading.work_control import ForwardWorkCancelled
        now = monotonic()
        with self._measure("heads"):
            heads = self._inbox.next_heads(limit=32, after_stream_id=self._after_stream_id)
        if not heads and self._after_stream_id is not None:
            self._after_stream_id = None
            heads = self._inbox.next_heads(limit=32)
        for delivery in heads:
            if self.stop_requested():
                return
            self._after_stream_id = delivery.stream_id
            if delivery.status in {"BLOCKED", "UNKNOWN"}:
                continue
            if self._retry_after_by_stream.get(delivery.stream_id, 0) > now:
                continue
            observation = delivery.envelope
            try:
                self._inbox.validate_delivery(delivery.delivery_id)
                self._worker.source_envelope = observation
                reader = getattr(self._inbox, "retained_observations", None)
                def originals(identifier=delivery.delivery_id):
                    with self._measure("originals"):
                        return reader(identifier)
                self._worker.retained_source_observations = originals if reader else ()
                self._worker.source_observed_at = observation.confirmed_at
                self._worker.raw_received_at = observation.raw_received_at or observation.source_observed_at
                self._worker.inbox_ingested_at = getattr(delivery, "ingested_at", None)
                end = datetime.fromisoformat(observation.data["bar_end"])
                self._worker.process_inbox_delivery(delivery.stream_id, end,
                                                   delivery_id=delivery.delivery_id)
                self._retry_after_by_stream.pop(delivery.stream_id, None)
            except ForwardWorkCancelled:
                return  # Original and any committed capture remain pending, not failed.
            except Exception as error:
                # An old owner cannot mutate delivery state after losing its
                # authority, including an otherwise harmless waiting marker.
                self._worker.assert_owned()
                from app.reference_trading.runtime import diagnostic_reason
                code = failure_reason(error)
                if diagnostic_reason(code) == "UNCLASSIFIED_FAILURE":
                    candidate = diagnostic_reason(str(error)) if isinstance(error, (RuntimeError, ValueError)) else "UNCLASSIFIED_FAILURE"
                    code = candidate if candidate != "UNCLASSIFIED_FAILURE" else "REFERENCE_INBOX_PROCESSING_FAILED"
                if code == "REFERENCE_FUSION_SOURCE_NOT_READY":
                    self._inbox.mark_dependency_wait(delivery.delivery_id, code)
                    self._retry_after_by_stream[delivery.stream_id] = now + 1
                elif code in {"SUBING_PHYSICAL_PREFIX_UNAVAILABLE", "MARKET_READ_CONTRACT_HISTORY_UNAVAILABLE",
                            "LIVE_SOURCE_UNAVAILABLE", "SOURCE_BUSY"}:
                    self._inbox.mark_waiting(delivery.delivery_id, code)
                    product, frequency = observation.channel.rsplit(":", 2)[-2:]
                    self.request_history(product, observation.data["contract"],
                                         observation.trading_day, (frequency,))
                    self._retry_after_by_stream[delivery.stream_id] = now + 30
                elif code in {"FORWARD_COMMIT_OUTCOME_UNKNOWN", "FORWARD_CAPTURE_OUTCOME_UNKNOWN"}:
                    self._inbox.mark_unknown(delivery.delivery_id, code)
                else:
                    self._inbox.mark_blocked(delivery.delivery_id, code)
            finally:
                self._worker.source_envelope = None
                self._worker.retained_source_observations = ()
                self._worker.inbox_ingested_at = None
                self._worker.source_observed_at = None
                self._worker.raw_received_at = None
