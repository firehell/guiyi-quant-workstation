"""Keep isolated and formally promoted Market Redis identities disjoint."""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import json
import os
import re
from pathlib import Path

from sqlalchemy.engine import URL

_BINDING = "live:market-foundation:binding"
_SOURCE = "live:market-foundation:source"
_TICK_POLICY = "rqdata-tick-v1"
_FORMAL_BINDING = "live:market-foundation:formal-binding"
_LEGACY_REFERENCE = "live:observations:registered:completed:reference"
LIVE_FINALIZATION_DELAY = timedelta(seconds=2)


def _isolated_market_fingerprint(sandbox: Path, database: URL) -> str:
    return sha256(
        f"{sandbox}\0{database.host}\0{database.port}\0{database.database}".encode()
    ).hexdigest()


def bind_market_redis(redis, sandbox: Path, database: URL) -> None:
    identity = _isolated_market_fingerprint(sandbox, database)
    result = redis.eval(
        """
        if redis.call('EXISTS', KEYS[2]) ~= 0 then return 0 end
        if ARGV[2] ~= '0' and string.find(redis.call('INFO', 'keyspace'), 'db0:') then return 0 end
        local current=redis.call('GET', KEYS[1])
        if current then return current==ARGV[1] and 1 or 0 end
        redis.call('SET', KEYS[1], ARGV[1])
        return 1
        """,
        2, _BINDING, _FORMAL_BINDING, identity,
        str(redis.connection_pool.connection_kwargs.get("db", 0)),
    )
    if result != 1:
        raise ValueError("MARKET_FOUNDATION_REDIS_BINDING_CONFLICT")


def require_isolated_market_tick(redis, sandbox: Path, database: URL) -> None:
    """Prove the candidate source without installing or changing Redis markers."""
    isolated, formal, source = redis.mget(_BINDING, _FORMAL_BINDING, _SOURCE)
    identity = _isolated_market_fingerprint(sandbox, database)
    if (isolated not in {identity, identity.encode()} or formal is not None
            or source not in {_TICK_POLICY, _TICK_POLICY.encode()}
            or redis.connection_pool.connection_kwargs.get("db", 0) != 0
            and "db0" in redis.info("keyspace")):
        raise ValueError("COMPUTE_LIVE_ISOLATION_REQUIRED")


def bind_tick_source(redis) -> None:
    # Never attach a Tick writer to a retained minute-provider frontier,
    # even if the local sandbox and Redis endpoints otherwise match.
    result = redis.eval(
        """
        local existing=redis.call('GET', KEYS[1])
        if existing then return existing==ARGV[1] and 1 or 0 end
        if redis.call('EXISTS', KEYS[2]) ~= 0 then return 0 end
        redis.call('SET', KEYS[1], ARGV[1])
        return 1
        """,
        2, _SOURCE, "live:observations:registered:source:live", _TICK_POLICY,
    )
    if result != 1:
        raise ValueError("MARKET_FOUNDATION_TICK_SOURCE_CONFLICT")


_BAR_SOURCE = "bar_1m"
_FORMAL_TICK_SOURCE = "rqdata_tick"


def formal_tick_requested() -> bool:
    mode = os.getenv("GUIYI_MARKET_SOURCE", _BAR_SOURCE)
    if mode not in {_BAR_SOURCE, _FORMAL_TICK_SOURCE}:
        raise ValueError("MARKET_SOURCE_MODE_INVALID")
    return mode == _FORMAL_TICK_SOURCE


def formal_tick_fingerprint(redis, database: URL, canonical_root: Path) -> str:
    endpoint = redis.connection_pool.connection_kwargs
    if (endpoint.get("host") not in {"127.0.0.1", "::1"}
            or type(endpoint.get("port")) is not int or endpoint["port"] == 6379
            or endpoint.get("db", 0) != 0
            or database.get_backend_name() != "postgresql" or database.database != "guiyi_quant"
            or database.host not in {"127.0.0.1", "localhost", "::1"}
            or not canonical_root.is_absolute() or canonical_root.resolve() != canonical_root):
        raise ValueError("MARKET_FORMAL_BINDING_INVALID")
    identity = (
        "formal-rqdata-tick-v1", str(canonical_root), database.host,
        str(database.port or 5432), database.database, endpoint["host"], str(endpoint["port"]),
    )
    return sha256("\0".join(identity).encode()).hexdigest()


def require_formal_tick_binding(redis, database: URL, canonical_root: Path) -> str:
    fingerprint = formal_tick_fingerprint(redis, database, canonical_root)
    _verify_formal_values(fingerprint, redis.mget(_FORMAL_BINDING, _BINDING, _SOURCE, _LEGACY_REFERENCE))
    return fingerprint


async def require_formal_tick_socket(redis, database: URL, canonical_root: Path) -> None:
    fingerprint = formal_tick_fingerprint(redis, database, canonical_root)
    _verify_formal_values(fingerprint, await redis.mget(_FORMAL_BINDING, _BINDING, _SOURCE, _LEGACY_REFERENCE))


def _verify_formal_values(fingerprint, values):
    formal, isolated, source, legacy_reference = values
    if (formal not in {fingerprint, fingerprint.encode()} or isolated is not None
            or source not in {_TICK_POLICY, _TICK_POLICY.encode()} or legacy_reference is not None):
        raise ValueError("MARKET_FORMAL_BINDING_UNPROVEN")


class FormalMarketReadRedis:
    """Fence completed/heartbeat reads as well as Tick previews."""

    def __init__(self, redis, database: URL, canonical_root: Path) -> None:
        self._redis = redis
        self._database = database
        self._canonical_root = canonical_root

    def __getattr__(self, name):
        require_formal_tick_binding(self._redis, self._database, self._canonical_root)
        return getattr(self._redis, name)


def require_bar_writer_namespace(redis) -> None:
    if any(value is not None for value in redis.mget(_FORMAL_BINDING, _SOURCE)):
        raise ValueError("MARKET_BAR_WRITER_NAMESPACE_CONFLICT")



def _formal_baseline(fingerprint, day, subscriptions, alert_enabled):
    from app.market_data.live_market import RedisLiveStore
    from app.market_data.observation_stream import ObservationStream, TTL_SECONDS

    source = ObservationStream(None, kind="source")
    completed = ObservationStream(None, kind="completed")
    baseline = {
        _FORMAL_BINDING: (fingerprint, -1),
        _SOURCE: (_TICK_POLICY, -1),
        RedisLiveStore._subscription_key(day): (
            json.dumps(subscriptions, sort_keys=True, separators=(",", ":")), TTL_SECONDS,
        ),
        source.registration_key("live"): (day.isoformat(), -1),
        source.cursor_key("live", day): ("0-0", TTL_SECONDS),
    }
    if alert_enabled:
        baseline[completed.registration_key("alert")] = (day.isoformat(), -1)
        baseline[completed.cursor_key("alert", day)] = ("0-0", TTL_SECONDS)
    return baseline


def stage_empty_formal_tick_namespace(
    redis, database: URL, canonical_root: Path, *,
    day: date, subscriptions: dict[str, str], alert_enabled: bool, expected_run_id: str | None = None,
) -> str:
    """Create the baseline after the coordinator proves the old source stopped."""
    from app.market_data.domain import normalize_contract_for_symbol
    from app.market_data.operational_universe import load_operational_products

    if (type(day) is not date or type(alert_enabled) is not bool
            or set(subscriptions) != set(load_operational_products())
            or any(normalize_contract_for_symbol(product, owner) != owner
                   for product, owner in subscriptions.items())
            or (expected_run_id is not None and not re.fullmatch(r"[0-9a-f]{40}", expected_run_id))):
        raise ValueError("MARKET_TICK_INITIAL_BASELINE_INVALID")
    retry = redis.connection_pool.connection_kwargs.get("retry")
    if retry is None or retry.get_retries() != 0:
        raise ValueError("MARKET_TICK_INITIAL_RETRY_FORBIDDEN")
    fingerprint = formal_tick_fingerprint(redis, database, canonical_root)
    baseline = _formal_baseline(fingerprint, day, subscriptions, alert_enabled)
    result = redis.eval(
        """
        if ARGV[1] ~= '' and string.match(redis.call('INFO', 'server'), 'run_id:([0-9a-f]+)') ~= ARGV[1] then
            return -1
        end
        if string.match(redis.call('INFO', 'keyspace'), 'db%d+:') then return 0 end
        for i, key in ipairs(KEYS) do
            local ttl = tonumber(ARGV[2 * i + 1])
            if ttl == -1 then
                redis.call('SET', key, ARGV[2 * i])
            else
                redis.call('SET', key, ARGV[2 * i], 'EX', ttl)
            end
        end
        return 1
        """,
        len(baseline), *baseline, expected_run_id or "",
        *(part for pair in baseline.values() for part in pair),
    )
    if result == -1:
        raise ValueError("MARKET_TICK_INITIAL_INSTANCE_DRIFT")
    if result != 1:
        raise ValueError("MARKET_TICK_INITIAL_NAMESPACE_NOT_EMPTY")
    return fingerprint


def check_empty_formal_tick_baseline(
    redis, fingerprint: str, *, day: date, subscriptions: dict[str, str], alert_enabled: bool, run_id: str,
) -> bool:
    """Use one read-only Redis operation to prove all keys on the dedicated instance."""
    baseline = _formal_baseline(fingerprint, day, subscriptions, alert_enabled)
    return redis.eval_ro(
        """
        if string.match(redis.call('INFO', 'server'), 'run_id:([0-9a-f]+)') ~= ARGV[1]
           or redis.call('DBSIZE') ~= #KEYS
           or string.match(redis.call('INFO', 'keyspace'), 'db[1-9]%d*:') then return 0 end
        for i, key in ipairs(KEYS) do
            local ttl = redis.call('PTTL', key)
            local bound = tonumber(ARGV[2 * i + 1])
            if redis.call('GET', key) ~= ARGV[2 * i] then return 0 end
            if bound == -1 then
                if ttl ~= -1 then return 0 end
            elseif ttl <= 0 or ttl > bound * 1000 then return 0 end
        end
        return 1
        """,
        len(baseline), *baseline, run_id,
        *(part for pair in baseline.values() for part in pair),
    ) == 1
