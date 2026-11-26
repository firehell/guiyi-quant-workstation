"""Keep isolated and formally promoted Market Redis identities disjoint."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path

from sqlalchemy.engine import URL

_BINDING = "live:market-foundation:binding"
_SOURCE = "live:market-foundation:source"
_TICK_POLICY = "rqdata-tick-v1"
_FORMAL_BINDING = "live:market-foundation:formal-binding"
_LEGACY_REFERENCE = "live:observations:registered:completed:reference"


def bind_market_redis(redis, sandbox: Path, database: URL) -> None:
    identity = sha256(
        f"{sandbox}\0{database.host}\0{database.port}\0{database.database}".encode()
    ).hexdigest()
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



def stage_empty_formal_tick_namespace(
    redis, database: URL, canonical_root: Path, *,
    day: date, subscriptions: dict[str, str], alert_enabled: bool,
) -> str:
    """Create the complete baseline after the coordinator proves the old source stopped.

    Only the new dedicated Redis is touched. Existing data, even with the same
    owner fingerprint, must go through independent cutover or recovery readback.
    """
    from app.market_data.domain import normalize_contract_for_symbol
    from app.market_data.live_market import RedisLiveStore
    from app.market_data.observation_stream import ObservationStream, TTL_SECONDS
    from app.market_data.operational_universe import load_operational_products

    if (type(day) is not date or type(alert_enabled) is not bool
            or set(subscriptions) != set(load_operational_products())
            or any(normalize_contract_for_symbol(product, owner) != owner
                   for product, owner in subscriptions.items())):
        raise ValueError("MARKET_TICK_INITIAL_BASELINE_INVALID")
    fingerprint = formal_tick_fingerprint(redis, database, canonical_root)
    source = ObservationStream(redis, kind="source")
    completed = ObservationStream(redis, kind="completed")
    keys = [_FORMAL_BINDING, _SOURCE, RedisLiveStore._subscription_key(day),
            source.registration_key("live"), source.cursor_key("live", day)]
    if alert_enabled:
        keys += [completed.registration_key("alert"), completed.cursor_key("alert", day)]
    result = redis.eval(
        """
        if string.match(redis.call('INFO', 'keyspace'), 'db%d+:') then return 0 end
        redis.call('MSET', KEYS[1], ARGV[1], KEYS[2], ARGV[2], KEYS[4], ARGV[4])
        redis.call('SET', KEYS[3], ARGV[3], 'EX', ARGV[5])
        redis.call('SET', KEYS[5], '0-0', 'EX', ARGV[5])
        if #KEYS == 7 then
            redis.call('SET', KEYS[6], ARGV[4])
            redis.call('SET', KEYS[7], '0-0', 'EX', ARGV[5])
        end
        return 1
        """,
        len(keys), *keys, fingerprint, _TICK_POLICY,
        json.dumps(subscriptions, sort_keys=True, separators=(",", ":")), day.isoformat(), TTL_SECONDS,
    )
    if result != 1:
        raise ValueError("MARKET_TICK_INITIAL_NAMESPACE_NOT_EMPTY")
    return fingerprint
