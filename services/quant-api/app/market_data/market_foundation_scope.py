"""Bind an isolated Market sandbox to exactly one disposable Redis namespace."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from sqlalchemy.engine import URL

_BINDING = "live:market-foundation:binding"
_SOURCE = "live:market-foundation:source"
_TICK_POLICY = "rqdata-tick-v1"


def bind_market_redis(redis, sandbox: Path, database: URL) -> None:
    identity = sha256(
        f"{sandbox}\0{database.host}\0{database.port}\0{database.database}".encode()
    ).hexdigest()
    redis.set(_BINDING, identity, nx=True)
    current = redis.get(_BINDING)
    if current not in {identity, identity.encode()}:
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
