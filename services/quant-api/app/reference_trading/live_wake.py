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
        try:
            channel = raw_channel.decode() if isinstance(raw_channel, bytes) else raw_channel
            data = raw_data.decode() if isinstance(raw_data, bytes) else raw_data
            if not isinstance(channel, str) or not isinstance(data, str):
                return False
            prefix = f"{LIVE_BAR_CHANNEL_PREFIX}:"
            if not channel.startswith(prefix):
                return False
            product, frequency = channel[len(prefix):].split(":", 1)
            if product != product.lower():
                return False
            BarFrequency(frequency)
            payload = json.loads(data)
            if not isinstance(payload, dict):
                return False
            end = datetime.fromisoformat(payload["bar_end"])
            day = date.fromisoformat(payload["trading_day"])
            contract = payload["contract"]
            if (end.tzinfo is None or end.utcoffset() is None
                    or normalize_contract_for_symbol(product, contract) != contract):
                return False
            owner = self._market_data.dominant_segment_for_day(product, day)
            if owner.contract != contract:
                return False
        except (AttributeError, KeyError, TypeError, ValueError, MarketDataError):
            return False
        for stream_id in self._repository.enabled_forward_routes(product, frequency):
            self._worker.wake(stream_id, kind="live_event", bar_end=end)

        return True

    def close(self) -> None:
        self._pubsub.close()


class StreamForwardLiveWake(ForwardLiveWake):
    """Do not acknowledge a durable observation until every route is committed."""
    def __init__(self, redis, repository, worker, market_data):
        super().__init__(redis, repository, worker, market_data)
        from app.market_data.observation_stream import ObservationStream
        self._stream = ObservationStream(redis, kind="completed")

    def subscribe(self):
        for day in self._stream.days():
            self._stream.cursor("reference", day)

    def wait(self, seconds):
        for day in self._stream.days():
            cursor = self._stream.cursor("reference", day)
            for observation in self._stream.read("reference", day, count=1):
                if observation.notification_eligible:
                    confirmed = getattr(observation, "confirmed_at", None)
                    if confirmed is None:
                        raise RuntimeError("REFERENCE_COMPLETED_TIME_MISSING")
                    self._worker.source_observed_at = confirmed
                    self._worker.raw_received_at = observation.source_observed_at
                    try:
                        if not self._on_message(observation.channel, json.dumps(observation.data)):
                            raise RuntimeError("REFERENCE_BUFFER_IDENTITY_INVALID")
                        while self._worker.health().pending_keys:
                            self._worker.assert_owned()
                            self._worker.run_round()
                            if self._worker.health().blocked:
                                raise RuntimeError("REFERENCE_BUFFER_PROCESSING_BLOCKED")
                    finally:
                        self._worker.source_observed_at = None
                        self._worker.raw_received_at = None
                self._stream.ack("reference", day, expected_cursor=cursor, next_id=observation.stream_id)
                return
        from time import sleep
        sleep(min(seconds, 1))
