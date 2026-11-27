"""Cross-instance observation evidence for an already supervised Market stop."""
from __future__ import annotations

from datetime import date, datetime
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import stat
from time import monotonic
from typing import BinaryIO

from app.market_data.aggregation import expected_intraday_ends
from app.market_data.market_foundation_scope import (
    LIVE_FINALIZATION_DELAY,
    check_empty_formal_tick_baseline,
    require_bar_writer_namespace,
    require_formal_tick_binding,
    stage_empty_formal_tick_namespace,
)
from app.market_data.live_market import RedisLiveStore, _bar_observation_from_payload, live_bar_channel
from app.market_data.observation_stream import (
    DAILY_LIMIT, ObservationEnvelope, ObservationStream, _text, completed_observation_id,
)
from app.runtime_cohort_errors import CohortError

_MAX_DAYS = 8
_PAGE_SIZE = 256
_MAX_RETAINED_BYTES = 768 * 1024 * 1024
_ORIGINALS_NAME = "old-observation-originals.jsonl"


def _redis_run_id(redis) -> str:
    run_id = redis.info("server").get("run_id")
    if not isinstance(run_id, str) or re.fullmatch(r"[a-f0-9]{40}", run_id) is None:
        raise CohortError("MARKET_SOURCE_INSTANCE_UNPROVEN")
    return run_id


def redis_instance(redis) -> str:
    return sha256(_redis_run_id(redis).encode("ascii")).hexdigest()


def _line(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _consumers(stream):
    prefix = f"live:observations:registered:{stream.kind}:"
    return tuple(sorted({_text(name)[len(prefix):] for name in stream.redis.scan_iter(match=prefix + "*")}))


def _journal_snapshot(
    stream, cutoff, consumers, *, retain, check_budget, terminals=None,
) -> dict:
    if _consumers(stream) != consumers:
        raise CohortError("MARKET_SOURCE_CONSUMER_SCOPE_CHANGED")
    days = stream.days()
    if len(days) > _MAX_DAYS or not days or days[-1] != cutoff:
        raise CohortError("MARKET_SOURCE_CUTOFF_UNPROVEN")
    if any(stream.registered_day(consumer) != cutoff for consumer in consumers):
        raise CohortError("MARKET_SOURCE_CONSUMER_DAY_UNPROVEN")

    result = {}
    for day in days:
        expected = terminals if day == cutoff and terminals is not None else {}
        verified_terminals = set()
        tail = stream.tail(day)
        cursors = {consumer: stream.cursor(consumer, day) for consumer in consumers}
        if any(cursor != tail for cursor in cursors.values()):
            raise CohortError("MARKET_SOURCE_OLD_BACKLOG")
        tally = 0
        frontier = "0-0"
        content = sha256()
        while frontier != tail:
            check_budget()
            rows = stream.redis.xrange(stream.key(day), min="(" + frontier, max=tail, count=_PAGE_SIZE)
            if not rows:
                raise CohortError("MARKET_SOURCE_RETENTION_GAP")
            events = [
                (_text(identifier), _text(fields.get("envelope", fields.get(b"envelope"))))
                for identifier, fields in rows
            ]
            parsed = [ObservationEnvelope.from_json(raw, stream_id=identifier) for identifier, raw in events]
            indices = stream.redis.hmget(stream.identity_key(day), [event.observation_id for event in parsed])
            for event, (_identifier, raw), index in zip(parsed, events, indices, strict=True):
                if event.trading_day != day or event.source_generation is not None or index is None:
                    raise CohortError("MARKET_SOURCE_OLD_IDENTITY_UNPROVEN")
                proof = json.loads(index)
                if proof.get("id") != event.stream_id or proof.get("payload") != raw:
                    raise CohortError("MARKET_SOURCE_OLD_IDENTITY_UNPROVEN")
                parts = event.channel.split(":")
                if (len(parts) == 4 and parts[:2] == ["live", "bar"] and parts[3] == "1m"
                        and parts[2] in expected and event.notification_eligible):
                    end = datetime.fromisoformat(event.data["bar_end"])
                    product = parts[2]
                    contract, terminal = expected[product]
                    if end.tzinfo is None or end > terminal:
                        raise CohortError("MARKET_SOURCE_OLD_TERMINAL_UNPROVEN")
                    if end == terminal:
                        if event.data["contract"] != contract or product in verified_terminals:
                            raise CohortError("MARKET_SOURCE_OLD_TERMINAL_UNPROVEN")
                        verified_terminals.add(product)
                record = _line([stream.kind, day.isoformat(), event.stream_id, event.observation_id, raw, _text(index)])
                content.update(record)
                retain(record)
                tally += 1
                if tally > DAILY_LIMIT:
                    raise CohortError("MARKET_SOURCE_RETENTION_LIMIT")
                frontier = event.stream_id
        meta = {"tail": tail, "cursors": cursors, "count": tally, "sha256": content.hexdigest()}
        info = stream.redis.xinfo_stream(stream.key(day)) if tail != "0-0" else None
        if (info is not None and (info.get("entries-added") != tally
                                  or _text(info.get("max-deleted-entry-id")) != "0-0")):
            raise CohortError("MARKET_SOURCE_RETENTION_GAP")
        if (stream.redis.xlen(stream.key(day)) != tally
                or stream.redis.hlen(stream.identity_key(day)) != tally
                or stream.tail(day) != tail
                or {name: stream.cursor(name, day) for name in consumers} != cursors
                or (day == cutoff and tally == 0)):
            raise CohortError("MARKET_SOURCE_RETENTION_DRIFT")
        if verified_terminals != expected.keys():
            raise CohortError("MARKET_SOURCE_OLD_TERMINAL_UNPROVEN")
        result[day.isoformat()] = meta
    if stream.days() != days or _consumers(stream) != consumers:
        raise CohortError("MARKET_SOURCE_RETENTION_DRIFT")
    return result


def old_observation_snapshot(redis, cutoff: date, *, alert_enabled: bool, check_budget,
                             original: BinaryIO | None = None, terminals=None) -> dict:
    require_bar_writer_namespace(redis)
    instance = redis_instance(redis)
    if alert_enabled:
        from app.alerts.composition import RedisAlertHeartbeatStore

        if RedisAlertHeartbeatStore(redis).read_unresolved():
            raise CohortError("MARKET_SOURCE_ALERT_RECOVERY_PENDING")
    size = 0

    def retain(record: bytes) -> None:
        nonlocal size
        size += len(record)
        if size > _MAX_RETAINED_BYTES:
            raise CohortError("MARKET_SOURCE_RETENTION_LIMIT")
        if original is not None:
            original.write(record)

    result = {
        "instance": instance,
        "source": _journal_snapshot(ObservationStream(redis, kind="source"), cutoff, ("live",),
                                    retain=retain, check_budget=check_budget, terminals=terminals),
        "completed": _journal_snapshot(
            ObservationStream(redis, kind="completed"), cutoff,
            ("alert", "reference") if alert_enabled else ("reference",),
            retain=retain, check_budget=check_budget, terminals=terminals,
        ),
    }
    if redis_instance(redis) != instance:
        raise CohortError("MARKET_SOURCE_INSTANCE_DRIFT")
    return result


def preserve_stopped_observations(redis, cutoff: date, *, alert_enabled: bool, attempt: Path,
                                  check_budget, terminals=None) -> dict:
    """Persist the old exact envelopes and indices once under the existing attempt."""
    marker = attempt / _ORIGINALS_NAME
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as original:
        result = old_observation_snapshot(
            redis, cutoff, alert_enabled=alert_enabled, original=original, check_budget=check_budget,
            terminals=terminals,
        )
        original.flush()
        os.fsync(original.fileno())
    directory = os.open(attempt, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    if old_observation_snapshot(redis, cutoff, alert_enabled=alert_enabled, check_budget=check_budget,
                                terminals=terminals) != result:
        raise CohortError("MARKET_SOURCE_STOPPED_FRONTIER_DRIFT")
    check_budget()
    with marker.open("rb") as retained:
        archive_sha256 = file_digest(retained, "sha256").hexdigest()
    check_budget()
    return {**result, "archive_sha256": archive_sha256}


def verify_preserved_observations(attempt: Path, expected: str, *, check_budget) -> None:
    fd = os.open(attempt / _ORIGINALS_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or info.st_mode & 0o077 or not 0 < info.st_size <= _MAX_RETAINED_BYTES):
            raise CohortError("MARKET_SOURCE_ORIGINALS_UNPROVEN")
        content = sha256()
        for page in iter(lambda: stream.read(1024 * 1024), b""):
            check_budget()
            content.update(page)
        if content.hexdigest() != expected:
            raise CohortError("MARKET_SOURCE_ORIGINALS_DRIFT")


def stage_new_observations(redis, database, canonical, *, expected_instance, old_instance,
                           day, subscriptions, alert_enabled) -> str:
    run_id = _redis_run_id(redis)
    if old_instance == expected_instance or sha256(run_id.encode("ascii")).hexdigest() != expected_instance:
        raise CohortError("MARKET_SOURCE_INSTANCE_CONFLICT")
    staged = stage_empty_formal_tick_namespace(
        redis, database, canonical, day=day, subscriptions=subscriptions, alert_enabled=alert_enabled,
        expected_run_id=run_id,
    )
    if read_staged_observations(
        redis, database, canonical, expected_instance=expected_instance,
        day=day, subscriptions=subscriptions, alert_enabled=alert_enabled,
    ) != staged:
        raise CohortError("MARKET_SOURCE_STAGED_BASELINE_UNPROVEN")
    return staged


def read_staged_observations(redis, database, canonical, *, expected_instance,
                             day, subscriptions, alert_enabled) -> str:
    """Readback for a known planned target, with no retry of the staging write."""
    run_id = _redis_run_id(redis)
    if sha256(run_id.encode("ascii")).hexdigest() != expected_instance:
        raise CohortError("MARKET_SOURCE_INSTANCE_DRIFT")
    binding = require_formal_tick_binding(redis, database, canonical)
    if not check_empty_formal_tick_baseline(
        redis, binding, day=day, subscriptions=subscriptions, alert_enabled=alert_enabled, run_id=run_id,
    ):
        raise CohortError("MARKET_SOURCE_STAGED_BASELINE_UNPROVEN")
    return binding



def _untrimmed_completed_frontier(stream, day):
    info = stream.redis.xinfo_stream(stream.key(day))
    if (
        info["length"] != info["entries-added"] or info["length"] > DAILY_LIMIT
        or _text(info["max-deleted-entry-id"]) != "0-0"
        or info["first-entry"] is None or info["last-entry"] is None
    ):
        raise CohortError("MARKET_SOURCE_TARGET_COMPLETED_PREFIX_UNPROVEN")
    return _text(info["first-entry"][0]), _text(info["last-entry"][0])


def read_first_completed_minutes(redis, day: date, *, sessions, now: datetime) -> dict:
    """Prove each product's first emitted completed minute and expose opening gaps."""
    if RedisLiveStore(redis).subscriptions(day) != {product: owner for product, (owner, _) in sessions.items()}:
        raise CohortError("MARKET_SOURCE_TARGET_SUBSCRIPTION_DRIFT")
    expected = {}
    products = {}
    for product, (contract, windows) in sessions.items():
        opening, *other_ends = expected_intraday_ends(windows, "1m")
        expected[live_bar_channel(product, "1m")] = (product, contract, {opening, *other_ends})
        products[product] = {
            "contract": contract,
            "opening_bar_end": opening.isoformat(),
            "status": "pending" if now < opening + LIVE_FINALIZATION_DELAY else "missing",
        }

    stream = ObservationStream(redis, kind="completed")
    if stream.tail(day) != "0-0":
        initial, tail = _untrimmed_completed_frontier(stream, day)
        frontier = "0-0"
        deadline = monotonic() + 20
        while expected and frontier != tail:
            if monotonic() >= deadline:
                raise CohortError("MARKET_SOURCE_TARGET_READBACK_TIMEOUT")
            rows = redis.xrange(stream.key(day), min="(" + frontier, max=tail, count=_PAGE_SIZE)
            if not rows:
                raise CohortError("MARKET_SOURCE_TARGET_COMPLETED_PREFIX_UNPROVEN")
            for identifier, fields in rows:
                frontier = _text(identifier)
                raw = _text(fields.get("envelope", fields.get(b"envelope")))
                event = ObservationEnvelope.from_json(raw, stream_id=frontier)
                if event.channel not in expected:
                    continue
                product, contract, endpoints = expected.pop(event.channel)
                try:
                    bar = _bar_observation_from_payload(
                        json.dumps(event.data), symbol=product, expected_contract=contract,
                    ).bar
                    end, confirmed = bar.bar_end, event.confirmed_at
                    if (
                        bar.trading_day != day or end not in endpoints or event.source_generation is None
                        or event.observation_id != completed_observation_id(day, contract, "1m", end)
                        or confirmed is None or not end + LIVE_FINALIZATION_DELAY <= confirmed <= now
                        or not end <= event.source_observed_at
                        or event.notification_eligible != event.timely_for_forward(end, confirmed)
                        or stream.read_original(day, event.observation_id) != event
                    ):
                        raise ValueError("MARKET_SOURCE_TARGET_FIRST_MINUTE_UNPROVEN")
                except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
                    raise CohortError("MARKET_SOURCE_TARGET_FIRST_MINUTE_UNPROVEN") from exc
                row = products[product]
                row.update(
                    status="verified" if event.notification_eligible else "late",
                    bar_end=end.isoformat(), opening_is_first=end.isoformat() == row["opening_bar_end"],
                    observation_id=event.observation_id, stream_id=event.stream_id,
                    source_generation=event.source_generation, confirmed_at=confirmed.isoformat(),
                )
            if frontier == tail:
                break
        if _untrimmed_completed_frontier(stream, day)[0] != initial:
            raise CohortError("MARKET_SOURCE_TARGET_COMPLETED_PREFIX_UNPROVEN")
    return {
        "status": "first_completed_verified" if all(row["status"] == "verified" for row in products.values())
        else "first_completed_incomplete",
        "trading_day": day.isoformat(),
        "products": products,
    }
