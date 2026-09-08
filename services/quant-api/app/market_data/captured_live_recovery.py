"""Manual, same-day recovery from bounded captured bytes; no provider capability.

Plans are immutable content bindings, not authority. The trusted caller supplies
fresh session/runtime authority and the existing OS commit guard on every apply.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ContextManager
from zoneinfo import ZoneInfo

from app.market_data.live_market import (
    RedisLiveStore,
    _LIVE_TTL_SECONDS,
    _as_text,
    _bar_observation_from_payload,
    _bar_payload,
    _compact_json,
    _epoch_millis,
)
from app.market_data.live_recovery import (
    LiveRecoveryRequest,
    _FREQUENCIES,
    _recovery_additions,
)
from app.market_data.live_recovery_scripts import COMMIT_RECOVERY
from app.market_data.rqdata_adapter import normalize_live_recovery_rows

MAX_SOURCE_BYTES = 512 * 1024
MAX_SOURCE_ROWS = 225
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _now(request, clock):
    now = clock()
    if now.tzinfo is None or request.cutoff.tzinfo is None:
        raise ValueError("LIVE_RECOVERY_CLOCK_INVALID")
    if (
        now.astimezone(_SHANGHAI).date() != request.trading_day
        or now < request.cutoff
        or now - request.cutoff > timedelta(seconds=60)
    ):
        raise ValueError("LIVE_RECOVERY_CLOCK_INVALID")
    return now.astimezone(UTC)


def _identity(request, runtime_identity):
    if (
        not isinstance(runtime_identity, str)
        or not runtime_identity
        or len(runtime_identity) > 8192
    ):
        raise ValueError("LIVE_RECOVERY_RUNTIME_INVALID")
    ends = request.endpoints()
    if (
        not ends
        or len(ends) > MAX_SOURCE_ROWS
        or len(dict(request.snapshot)) != len(request.snapshot)
        or request.sessions[-1].end + timedelta(seconds=2) > request.cutoff
        or any(
            w.start.tzinfo is None
            or w.end.tzinfo is None
            or w.start >= w.end
            or w.start.second
            or w.end.second
            or w.start.microsecond
            or w.end.microsecond
            or w.start.astimezone(_SHANGHAI).date() != request.trading_day
            or w.end.astimezone(_SHANGHAI).date() != request.trading_day
            for w in request.sessions
        )
    ):
        raise ValueError("LIVE_RECOVERY_SESSION_INVALID")
    return dict(
        trading_day=request.trading_day.isoformat(),
        symbol=request.symbol,
        contract=request.contract,
        snapshot=[list(v) for v in request.snapshot],
        sessions=[[w.start.isoformat(), w.end.isoformat()] for w in request.sessions],
        runtime_identity=runtime_identity,
    )


def _reject_json_constant(_):
    raise ValueError("LIVE_RECOVERY_SOURCE_INVALID")


def _unique_mapping(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("LIVE_RECOVERY_SOURCE_INVALID")
        result[key] = value
    return result


def _source(request, source):
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise ValueError("LIVE_RECOVERY_SOURCE_INVALID")
    try:
        rows = json.loads(
            source,
            parse_constant=_reject_json_constant,
            parse_float=Decimal,
            object_pairs_hook=_unique_mapping,
        )
        if not isinstance(rows, list) or not 0 < len(rows) <= MAX_SOURCE_ROWS:
            raise ValueError("LIVE_RECOVERY_SOURCE_INVALID")
        if any(
            not isinstance(row, dict)
            or any(k not in row for k in ("datetime", "trading_date", "order_book_id"))
            for row in rows
        ):
            raise ValueError("LIVE_RECOVERY_SOURCE_INVALID")
        bars = normalize_live_recovery_rows(request, rows, strict=True)
        if (
            len(bars) != len(request.endpoints())
            or tuple(v.bar_end for v in bars) != request.endpoints()
        ):
            raise ValueError("LIVE_RECOVERY_COVERAGE_INVALID")
        return bars
    except (TypeError, KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("LIVE_RECOVERY_SOURCE_INVALID") from exc


def _keys(store, request):
    state = store._recovery_key(request.trading_day, request.symbol, request.contract)
    return [
        store._subscription_key(request.trading_day),
        state,
        *(
            store._bars_key(request.trading_day, request.symbol, f)
            for f in _FREQUENCIES
        ),
        *(f"{state}:attempt:{w.start.isoformat()}" for w in request.sessions),
        f"live:recovery:circuit:{request.trading_day.isoformat()}",
    ]


def _key_type(redis, key, allowed):
    kind = _as_text(redis.type(key))
    ttl = redis.ttl(key)
    if (
        kind not in allowed
        or (kind == "none" and ttl != -2)
        or (kind != "none" and not 0 < ttl <= _LIVE_TTL_SECONDS)
    ):
        raise ValueError("LIVE_RECOVERY_KEY_INVALID")
    return kind


def _read(store, request):
    redis = store._redis
    keys = _keys(store, request)
    types = []
    values = []
    for index, key in enumerate(keys):
        allowed = (
            ("zset",)
            if 2 <= index < 7
            else ("string",)
            if index == 0
            else ("string", "none")
        )
        types.append(_key_type(redis, key, allowed))
        if 2 <= index < 7:
            sequence = redis.zrange(key, 0, MAX_SOURCE_ROWS, withscores=True)
            if len(sequence) > MAX_SOURCE_ROWS:
                raise ValueError("LIVE_RECOVERY_COVERAGE_INVALID")
            values.append([[_as_text(v), score] for v, score in sequence])
        else:
            raw = redis.get(key)
            values.append(None if raw is None else _as_text(raw))
    if json.loads(values[0]) != dict(request.snapshot):
        raise ValueError("LIVE_RECOVERY_SNAPSHOT_DRIFT")
    if values[-1] is not None:
        raise ValueError("LIVE_RECOVERY_CIRCUIT_BLOCKED")
    for raw in values[7:-1]:
        if raw is not None:
            try:
                budget = json.loads(raw)
                if (
                    set(budget) != {"count", "last_at"}
                    or type(budget["count"]) is not int
                    or not 1 <= budget["count"] <= 3
                    or type(budget["last_at"]) is not int
                    or budget["last_at"] < 0
                ):
                    raise ValueError("LIVE_RECOVERY_BUDGET_INVALID")
            except (TypeError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError("LIVE_RECOVERY_BUDGET_INVALID") from exc
    return {"types": types, "values": values}


def _existing(request, series):
    result = []
    for sequence in series:
        current = {}
        for raw, score in sequence:
            bar = _bar_observation_from_payload(
                raw, symbol=request.symbol, expected_contract=request.contract
            ).bar
            if bar.bar_end in current or score != _epoch_millis(bar.bar_end):
                raise ValueError("LIVE_RECOVERY_DUPLICATE_OR_SCORE_INVALID")
            if bar.trading_day != request.trading_day:
                raise ValueError("LIVE_RECOVERY_TRADING_DAY_INVALID")
            current[bar.bar_end] = bar
        result.append(current)
    if any(end not in set(request.endpoints()) for end in result[0]):
        raise ValueError("LIVE_RECOVERY_SESSION_INVALID")
    return result


def _targets(request, source, baseline):
    if baseline["values"][1] is not None:
        raise ValueError("LIVE_RECOVERY_STATE_INVALID")
    existing = _existing(request, baseline["values"][2:7])
    additions = _recovery_additions(request, source, existing)
    if any(len(bars) != 1 for bars in additions):
        raise ValueError("LIVE_RECOVERY_TARGET_BUDGET_INVALID")
    targets = []
    for frequency, bars in zip(_FREQUENCIES, additions, strict=True):
        bar = bars[0]
        payload = _compact_json(_bar_payload(bar, contract=request.contract))
        targets.append(
            dict(
                frequency=str(frequency),
                score=_epoch_millis(bar.bar_end),
                payload=payload,
                payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),
            )
        )
    return targets


def plan_captured_recovery(
    store: RedisLiveStore,
    request: LiveRecoveryRequest,
    source: bytes,
    *,
    runtime_identity: str,
    clock: Callable[[], datetime],
) -> dict:
    """GET/ZRANGE/TYPE/TTL only; output binds all raw values and exact five additions."""
    now = _now(request, clock)
    identity = _identity(request, runtime_identity)
    bars = _source(request, source)
    baseline = _read(store, request)
    plan = dict(
        schema_version=1,
        identity=identity,
        source_sha256=hashlib.sha256(source).hexdigest(),
        planned_at=now.isoformat(),
        baseline=baseline,
        targets=_targets(request, bars, baseline),
        provider_requests=0,
        ttl_seconds=_LIVE_TTL_SECONDS,
    )
    plan["plan_sha256"] = _digest(plan)
    return plan


def _validated_plan(request, source, plan, runtime_identity):
    try:
        unsigned = {k: v for k, v in plan.items() if k != "plan_sha256"}
        planned_at = datetime.fromisoformat(plan["planned_at"])
        if (
            set(plan)
            != {
                "schema_version",
                "identity",
                "source_sha256",
                "planned_at",
                "baseline",
                "targets",
                "provider_requests",
                "ttl_seconds",
                "plan_sha256",
            }
            or planned_at.tzinfo is None
            or planned_at.astimezone(_SHANGHAI).date() != request.trading_day
            or planned_at > request.cutoff
            or type(plan["schema_version"]) is not int
            or plan["schema_version"] != 1
            or plan["plan_sha256"] != _digest(unsigned)
            or plan["identity"] != _identity(request, runtime_identity)
            or plan["source_sha256"] != hashlib.sha256(source).hexdigest()
            or plan["ttl_seconds"] != _LIVE_TTL_SECONDS
            or plan["provider_requests"] != 0
        ):
            raise ValueError("LIVE_RECOVERY_PLAN_INVALID")
        bars = _source(request, source)
        if plan["targets"] != _targets(request, bars, plan["baseline"]):
            raise ValueError("LIVE_RECOVERY_PLAN_INVALID")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("LIVE_RECOVERY_PLAN_INVALID") from exc


def _noop(request, plan, current):
    baseline = plan["baseline"]
    if current["values"][1] is None:
        return False
    expected = json.loads(json.dumps(baseline))
    for index, target in enumerate(plan["targets"], 2):
        expected["values"][index].append([target["payload"], target["score"]])
        expected["values"][index].sort(key=lambda row: (row[1], row[0]))
    expected["types"][1] = "string"
    expected["values"][1] = current["values"][1]
    if current != expected:
        return False
    try:
        state = json.loads(current["values"][1])
        through = datetime.fromisoformat(state["recovered_through"])
        planned_at = datetime.fromisoformat(plan["planned_at"])
        return (
            set(state)
            == {
                "revision",
                "recovered_through",
                "captured_plan_sha256",
                "captured_source_sha256",
            }
            and type(state["revision"]) is int
            and state["revision"] == 1
            and state["captured_plan_sha256"] == plan["plan_sha256"]
            and state["captured_source_sha256"] == plan["source_sha256"]
            and through.tzinfo is not None
            and planned_at.tzinfo is not None
            and planned_at <= through <= request.cutoff
            and through.astimezone(_SHANGHAI).date() == request.trading_day
        )
    except (ValueError, TypeError, KeyError):
        return False


def apply_captured_recovery(
    store: RedisLiveStore,
    request: LiveRecoveryRequest,
    source: bytes,
    plan: dict,
    *,
    runtime_identity: str,
    clock: Callable[[], datetime],
    commit_guard: Callable[[], ContextManager],
) -> dict:
    """Single apply attempt; unknown Redis outcome propagates without retry."""
    _now(request, clock)
    _validated_plan(request, source, plan, runtime_identity)
    current = _read(store, request)
    result = dict(plan_sha256=plan["plan_sha256"], provider_requests=0)
    if _noop(request, plan, current):
        return dict(result, status="NOOP", recovery=json.loads(current["values"][1]))
    if current != plan["baseline"]:
        raise ValueError("LIVE_RECOVERY_SNAPSHOT_DRIFT")
    with commit_guard():
        committed_at = _now(request, clock)
        if committed_at < datetime.fromisoformat(plan["planned_at"]):
            raise ValueError("LIVE_RECOVERY_CLOCK_INVALID")
        state = dict(
            revision=1,
            recovered_through=committed_at.isoformat(),
            captured_plan_sha256=plan["plan_sha256"],
            captured_source_sha256=plan["source_sha256"],
        )
        series = [
            dict(
                before=[row[0] for row in values],
                before_scores=[row[1] for row in values],
                add=[dict(score=target["score"], payload=target["payload"])],
            )
            for values, target in zip(
                current["values"][2:7], plan["targets"], strict=True
            )
        ]
        keys = _keys(store, request)
        outcome = store._redis.eval(
            COMMIT_RECOVERY,
            len(keys),
            *keys,
            current["values"][0],
            "",
            json.dumps(series),
            "+inf",
            _compact_json(state),
            _LIVE_TTL_SECONDS,
            json.dumps(current),
        )
        if outcome != 1:
            raise ValueError("LIVE_RECOVERY_SNAPSHOT_DRIFT")
    return dict(result, status="RECOVERED", recovery=state)
