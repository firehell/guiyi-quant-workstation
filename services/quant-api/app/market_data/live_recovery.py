"""Bounded current-day Live repair; never publishes or touches Canonical.

Authority and the frozen rank1 snapshot are collected on the foreground thread.
The worker owns no SQLAlchemy Session and only consumes that immutable request.
"""

from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from typing import ContextManager
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.market_data.aggregation import (
    SessionWindow,
    aggregate_from_1m,
    bucket_window_for_bar,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    normalize_contract_for_symbol,
)
from app.market_data.live_market import (
    RedisLiveStore,
    _LIVE_TTL_SECONDS,
    _as_text,
    _bar_observation_from_payload,
    _bar_payload,
    _compact_json,
    _epoch_millis,
)
from app.market_data.live_recovery_scripts import CLAIM_ATTEMPT, COMMIT_RECOVERY

_FREQUENCIES = (
    BarFrequency.M1,
    BarFrequency.M5,
    BarFrequency.M15,
    BarFrequency.M30,
    BarFrequency.H1,
)


@dataclass(frozen=True, slots=True)
class LiveRecoveryRequest:
    trading_day: date
    symbol: str
    contract: str
    snapshot: tuple[tuple[str, str], ...]
    sessions: tuple[SessionWindow, ...]
    cutoff: datetime

    def endpoints(self) -> tuple[datetime, ...]:
        if (
            normalize_contract_for_symbol(self.symbol, self.contract) != self.contract
            or dict(self.snapshot).get(self.symbol) != self.contract
            or self.cutoff.tzinfo is None
            or not self.sessions
        ):
            raise ValueError("LIVE_RECOVERY_REQUEST_INVALID")
        ends = tuple(
            window.start + timedelta(minutes=minute)
            for window in self.sessions
            for minute in range(
                1, int((window.end - window.start).total_seconds() // 60) + 1
            )
            if window.start + timedelta(minutes=minute, seconds=2) <= self.cutoff
        )
        if tuple(sorted(set(ends))) != ends:
            raise ValueError("LIVE_RECOVERY_SESSION_INVALID")
        return ends


def recover_product(
    store: RedisLiveStore,
    request: LiveRecoveryRequest,
    fetch: Callable[[LiveRecoveryRequest], tuple[CanonicalBar, ...]],
    *,
    clock: Callable[[], datetime],
    commit_guard: Callable[[], ContextManager] = nullcontext,
) -> str:
    """Validate a full completed prefix and atomically add only missing observations."""
    ends = request.endpoints()
    if not ends:
        return "NO_GAP"
    redis = store._redis
    subscription_key = store._subscription_key(request.trading_day)
    subscription = redis.get(subscription_key)
    if subscription is None or json.loads(_as_text(subscription)) != dict(
        request.snapshot
    ):
        raise ValueError("LIVE_RECOVERY_SNAPSHOT_DRIFT")
    state_key = store._recovery_key(
        request.trading_day, request.symbol, request.contract
    )
    state_raw = redis.get(state_key)
    state = store.recovery_state(request.trading_day, request.symbol, request.contract)
    before = []
    existing = []
    for frequency in _FREQUENCIES:
        raw = tuple(
            _as_text(v)
            for v in redis.zrangebyscore(
                store._bars_key(request.trading_day, request.symbol, frequency),
                "-inf",
                _epoch_millis(ends[-1]),
            )
        )
        observations = tuple(
            _bar_observation_from_payload(
                v,
                symbol=request.symbol,
                expected_contract=request.contract,
            ).bar
            for v in raw
        )
        if len({v.bar_end for v in observations}) != len(observations):
            raise ValueError("LIVE_RECOVERY_DUPLICATE")
        if any(v.trading_day != request.trading_day for v in observations):
            raise ValueError("LIVE_RECOVERY_TRADING_DAY_INVALID")
        before.append(raw)
        existing.append({v.bar_end: v for v in observations})
    expected = set(ends)
    if any(end not in expected for end in existing[0]):
        raise ValueError("LIVE_RECOVERY_SESSION_INVALID")
    missing = expected - existing[0].keys()
    if not missing:
        source = tuple(existing[0][end] for end in ends)
    else:
        # Budget is persisted before the provider call, including failures/restarts.
        active_session = next(
            (w for w in reversed(request.sessions) if w.start <= request.cutoff), None
        )
        if active_session is None:
            raise ValueError("LIVE_RECOVERY_SESSION_INVALID")
        budget_key = f"{state_key}:attempt:{active_session.start.isoformat()}"
        circuit_key = f"live:recovery:circuit:{request.trading_day.isoformat()}"
        if (
            redis.eval(
                CLAIM_ATTEMPT,
                2,
                budget_key,
                circuit_key,
                _epoch_millis(request.cutoff),
                _LIVE_TTL_SECONDS,
            )
            != 1
        ):
            return "RETRY_BUDGET_BLOCKED"
        try:
            source = fetch(request)
        except Exception as exc:
            # Only stable public classifications are recorded; never provider text.
            if str(exc) in ("PROVIDER_QUOTA_EXHAUSTED", "PROVIDER_ACCESS_DENIED"):
                redis.set(circuit_key, "STOPPED", ex=_LIVE_TTL_SECONDS)
            raise
    if len(source) != len(ends) or tuple(v.bar_end for v in source) != ends:
        raise ValueError("LIVE_RECOVERY_COVERAGE_INVALID")
    if any(v.trading_day != request.trading_day for v in source):
        raise ValueError("LIVE_RECOVERY_TRADING_DAY_INVALID")
    if any(v.bar_end in existing[0] and existing[0][v.bar_end] != v for v in source):
        raise ValueError("LIVE_BAR_CONFLICT")
    additions: list[list[CanonicalBar]] = [[v for v in source if v.bar_end in missing]]
    by_end = {v.bar_end: v for v in source}
    for index, frequency in enumerate(_FREQUENCIES[1:], 1):
        derived = []
        for session in request.sessions:
            buckets = {
                bucket_window_for_bar(session, frequency, end)
                for end in ends
                if session.start < end <= session.end
            }
            for bucket in sorted(buckets, key=lambda v: v.start):
                bucket_ends = tuple(
                    bucket.start + timedelta(minutes=i)
                    for i in range(
                        1, int((bucket.end - bucket.start).total_seconds() // 60) + 1
                    )
                )
                if any(end not in by_end for end in bucket_ends):
                    continue
                bar = aggregate_from_1m(
                    tuple(by_end[end] for end in bucket_ends),
                    target_frequency=frequency,
                    sessions=(bucket,),
                )[0]
                previous = existing[index].get(bar.bar_end)
                if previous is not None and previous != bar:
                    raise ValueError("LIVE_BAR_CONFLICT")
                if previous is None:
                    derived.append(bar)
        additions.append(derived)
    if not any(additions):
        return "NO_GAP"
    with commit_guard():
        committed_at = clock().astimezone(UTC)
        if committed_at < request.cutoff or committed_at - request.cutoff > timedelta(
            seconds=60
        ):
            raise ValueError("LIVE_RECOVERY_CLOCK_INVALID")
        through = max(committed_at, state.recovered_through) if state else committed_at
        payload = _compact_json(
            {
                "revision": state.revision + 1 if state else 1,
                "recovered_through": through.isoformat(),
            }
        )
        plan = json.dumps(
            [
                {
                    "before": raw,
                    "add": [
                        {
                            "score": _epoch_millis(v.bar_end),
                            "payload": _compact_json(
                                _bar_payload(v, contract=request.contract)
                            ),
                        }
                        for v in bars
                    ],
                }
                for raw, bars in zip(before, additions, strict=True)
            ],
            separators=(",", ":"),
        )
        keys = [
            subscription_key,
            state_key,
            *(
                store._bars_key(request.trading_day, request.symbol, f)
                for f in _FREQUENCIES
            ),
        ]
        result = redis.eval(
            COMMIT_RECOVERY,
            len(keys),
            *keys,
            _as_text(subscription),
            "" if state_raw is None else _as_text(state_raw),
            plan,
            _epoch_millis(ends[-1]),
            payload,
            _LIVE_TTL_SECONDS,
        )
        if result != 1:
            raise ValueError("LIVE_RECOVERY_SNAPSHOT_DRIFT")
        return "RECOVERED"


class LiveRecoveryWorker:
    """One grouped background job, at least 60 seconds apart; lazy provider factory."""

    def __init__(
        self,
        store: RedisLiveStore,
        fetch_factory,
        *,
        clock: Callable[[], datetime],
        guard_factory: Callable[[str], ContextManager] | None = None,
    ):
        self._store = store
        self._fetch_factory = fetch_factory
        self._clock = clock
        self._guard_factory = guard_factory
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="live-recovery"
        )
        self._future: Future | None = None
        self._next_at: datetime | None = None
        self.outcomes: tuple[tuple[str, str], ...] = ()

    def due(self, now: datetime) -> bool:
        return (self._future is None or self._future.done()) and (
            self._next_at is None or now >= self._next_at
        )

    def schedule(
        self, requests: tuple[LiveRecoveryRequest, ...], now: datetime
    ) -> None:
        if self._future is not None and not self._future.done():
            return
        if self._next_at is not None and now < self._next_at:
            return
        if not requests:
            return
        self._next_at = now + timedelta(seconds=60)
        self._future = self._executor.submit(self._run, requests)

    def _run(self, requests: tuple[LiveRecoveryRequest, ...]) -> None:
        fetch = None

        def lazy_fetch(request):
            nonlocal fetch
            if fetch is None:
                fetch = self._fetch_factory()
            return fetch(request)

        outcomes = []
        guard_factory = self._guard_factory
        for request in requests:
            try:
                result = recover_product(
                    self._store,
                    request,
                    lazy_fetch,
                    clock=self._clock,
                    commit_guard=(lambda: guard_factory(request.symbol))
                    if guard_factory
                    else nullcontext,
                )
            except (
                Exception
            ) as exc:  # provider/Redis boundary: never emit raw error text
                allowed = {
                    "LIVE_RECOVERY_SNAPSHOT_DRIFT",
                    "LIVE_RECOVERY_CLOCK_INVALID",
                    "LIVE_RECOVERY_BUSY",
                    "PROVIDER_QUOTA_EXHAUSTED",
                    "PROVIDER_ACCESS_DENIED",
                    "LIVE_BAR_CONFLICT",
                    "LIVE_RECOVERY_COVERAGE_INVALID",
                    "LIVE_RECOVERY_SESSION_INVALID",
                }
                result = str(exc) if str(exc) in allowed else "LIVE_RECOVERY_FAILED"
            if result != "NO_GAP":
                logging.getLogger(__name__).info(
                    result,
                    extra={
                        "diagnostic_fields": {
                            "symbol": request.symbol,
                            "contract": request.contract,
                            "trading_day": request.trading_day.isoformat(),
                        }
                    },
                )
            outcomes.append((request.symbol, result))
        self.outcomes = tuple(outcomes)
