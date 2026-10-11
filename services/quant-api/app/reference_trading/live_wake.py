"""Redis Live PubSub hints for the durable forward reference worker."""

from __future__ import annotations

from datetime import date, datetime
import json
from time import monotonic
from typing import Any

from app.market_data.domain import BarFrequency, normalize_contract_for_symbol
from app.market_data.live_market import LIVE_BAR_CHANNEL_PREFIX
from app.market_data.market_data_service import MarketDataError


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
    """Do not acknowledge a durable observation until every route is committed."""
    def __init__(self, redis, repository, worker, market_data):
        super().__init__(redis, repository, worker, market_data)
        from app.market_data.observation_stream import ObservationStream
        self._stream = ObservationStream(redis, kind="completed")
        self.stop_requested = lambda: False

    def subscribe(self):
        for day in self._stream.days():
            self._stream.cursor("reference", day)

    def poll(self, *, limit: int = 128) -> bool:
        """Consume a bounded batch without sleeping; True keeps foreground priority."""
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("REFERENCE_OBSERVATION_POLL_BUDGET_INVALID")
        self._last_poll_count = 0
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
                    self._worker.source_observed_at = confirmed
                    self._worker.raw_received_at = observation.source_observed_at
                    try:
                        validated = self._validated_routes(observation.channel, json.dumps(observation.data))
                        if validated is None:
                            raise RuntimeError("REFERENCE_BUFFER_IDENTITY_INVALID")
                        end, routes = validated
                        self._worker.process_live_observation(routes, end)
                    finally:
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
