"""One extra Live-only attempt for the 2026-11-03 dependency restart.

Not a reusable budget override. No notifications, journal publication, Canonical,
Signal, Event or execution writes. Unknown claims/fetch/commit outcomes stop.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime
from hashlib import sha256

from app.market_data.live_market import (
    _as_text,
    _compact_json,
    _epoch_millis,
    _LIVE_TTL_SECONDS,
)
from app.market_data.live_recovery import _recover_product, _validated_recovery_clock
from app.market_data.live_recovery_guard import (
    after_market_recovery_guard,
    recovery_guard,
)

SYMBOLS = ("ag", "al", "ao", "au", "cu", "ni", "pb", "sc", "sn", "ss", "zn")
DAY = date(2026, 11, 4)
INCIDENT = "dependency-update-20261103"
RUNTIME_IDENTITY = "v1.16.73:237d488ebed2b79705dc2b8bf28fd3d6c5da6915:56"
ORIGINAL_LAST_AT = 1793718892211
CLAIM_KEY = f"live:recovery:incident:{INCIDENT}"
CIRCUIT_KEY = f"live:recovery:circuit:{DAY.isoformat()}"

START_INCIDENT = r"""-- live-incident-start-20261103-v1
if redis.call('EXISTS',KEYS[1])~=0 or redis.call('EXISTS',KEYS[2])~=0 then return 0 end
if redis.call('GET',KEYS[3])~=ARGV[2] then return 0 end
for i=4,#KEYS do
 if redis.call('GET',KEYS[i])~=ARGV[i-1] then return 0 end
 local ok,v=pcall(cjson.decode,ARGV[i-1])
 if not ok or v.count~=3 or v.last_at~=1793718892211 then return 0 end
end
redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[#ARGV])
return 1
"""

CLAIM_EXTRA = r"""-- live-incident-extra-20261103-v1
if redis.call('GET',KEYS[3])~=ARGV[2] or redis.call('EXISTS',KEYS[2])~=0
 or redis.call('EXISTS',KEYS[4])~=0 or redis.call('GET',KEYS[1])~=ARGV[1]
 or redis.call('GET',KEYS[5])~=ARGV[3] then return 0 end
local ok,v=pcall(cjson.decode,ARGV[1])
if not ok or v.count~=3 or v.last_at~=1793718892211 then return 0 end
local at=tonumber(ARGV[4]);local ttl=tonumber(ARGV[5])
if not at or at<v.last_at+60000 or ttl~=259200 then return 0 end
redis.call('SET',KEYS[1],cjson.encode({count=4,last_at=at}),'EX',ttl)
redis.call('SET',KEYS[4],ARGV[2],'EX',ttl)
return 1
"""


def _require(condition, code="LIVE_INCIDENT_SCOPE_INVALID"):
    if not condition:
        raise ValueError(code)


def _scope(requests, now):
    _require(tuple(r.symbol for r in requests) == SYMBOLS)
    _require(now.tzinfo is not None and now.utcoffset() is not None)
    now = now.astimezone(UTC)
    _require(
        datetime(2026, 11, 3, 15, 15, tzinfo=UTC)
        <= now
        < datetime(2026, 11, 3, 16, tzinfo=UTC)
    )
    snapshot = dict(requests[0].snapshot)
    _require(len(snapshot) == len(requests[0].snapshot) == 60)
    sessions = {}
    identities = []
    for request in requests:
        _require(
            request.trading_day == DAY
            and dict(request.snapshot) == snapshot
            and len(request.snapshot) == 60
        )
        _validated_recovery_clock(now, request.cutoff)
        _require(bool(request.endpoints()))
        windows = request.sessions
        _require(
            all(
                w.start.tzinfo is not None
                and w.end.tzinfo is not None
                and w.start < w.end
                and not w.start.second
                and not w.start.microsecond
                and not w.end.second
                and not w.end.microsecond
                for w in windows
            )
        )
        _require(all(a.end <= b.start for a, b in zip(windows, windows[1:])))
        active = [w for w in windows if w.start <= request.cutoff < w.end]
        _require(len(active) == 1 and active[0].start <= now < active[0].end)
        sessions[request.symbol] = windows
        identities.append(
            {
                "symbol": request.symbol,
                "contract": request.contract,
                "sessions": [[w.start.isoformat(), w.end.isoformat()] for w in windows],
                "cutoff": request.cutoff.isoformat(),
            }
        )
    expected = {
        "runtime_identity": RUNTIME_IDENTITY,
        "trading_day": DAY.isoformat(),
        "snapshot": snapshot,
        "sessions": sessions,
    }
    claim = _compact_json(
        {
            "incident": INCIDENT,
            "runtime_identity": RUNTIME_IDENTITY,
            "trading_day": DAY.isoformat(),
            "snapshot": snapshot,
            "requests": identities,
        }
    )
    return expected, claim


def recover_incident(store, requests, fetch, *, clock, authority):
    """Run exactly this incident once, stopping on the first failed/unknown product.

    ``authority()`` must freshly read actual bindings, frozen subscriptions and
    Calendar/Session authority and return exactly the keys produced by _scope:
    runtime_identity, trading_day, snapshot(dict), sessions(dict of window tuples).
    Callers also hold the existing deployment lock. The module acquires the shared
    after-market and per-symbol kernel guards itself; never substitute fake guards
    in production. Construct RQData lazily inside ``fetch`` (after durable claim).
    """
    requests = tuple(requests)
    expected, claim = _scope(requests, clock())
    redis = store._redis
    subscription_key = store._subscription_key(DAY)
    before = {}
    budget_keys = []

    def revalidate():
        _scope(requests, clock())
        _require(authority() == expected, "LIVE_INCIDENT_AUTHORITY_DRIFT")
        _require(redis.get(CIRCUIT_KEY) is None, "LIVE_INCIDENT_CIRCUIT_STOPPED")

    with after_market_recovery_guard(wait=False):
        revalidate()
        _require(
            redis.get(CLAIM_KEY) is None, "LIVE_INCIDENT_ALREADY_CLAIMED_OR_DRIFTED"
        )
        subscription = redis.get(subscription_key)
        _require(
            subscription is not None
            and json.loads(_as_text(subscription)) == expected["snapshot"],
            "LIVE_INCIDENT_SNAPSHOT_DRIFT",
        )
        subscription = _as_text(subscription)
        for request in requests:
            active = next(
                w for w in request.sessions if w.start <= request.cutoff < w.end
            )
            key = f"{store._recovery_key(DAY, request.symbol, request.contract)}:attempt:{active.start.isoformat()}"
            raw = redis.get(key)
            _require(raw is not None, "LIVE_INCIDENT_BUDGET_INVALID")
            raw = _as_text(raw)
            value = json.loads(raw)
            _require(
                set(value) == {"count", "last_at"}
                and type(value["count"]) is int
                and value["count"] == 3
                and type(value["last_at"]) is int
                and value["last_at"] == ORIGINAL_LAST_AT,
                "LIVE_INCIDENT_BUDGET_INVALID",
            )
            before[request.symbol] = (key, raw)
            budget_keys.append(key)
        revalidate()
        _require(
            redis.eval(
                START_INCIDENT,
                3 + len(budget_keys),
                CLAIM_KEY,
                CIRCUIT_KEY,
                subscription_key,
                *budget_keys,
                claim,
                subscription,
                *(before[r.symbol][1] for r in requests),
                _LIVE_TTL_SECONDS,
            )
            == 1,
            "LIVE_INCIDENT_ALREADY_CLAIMED_OR_DRIFTED",
        )
        results = []
        for request in requests:
            revalidate()

            @contextmanager
            def guard():
                with recovery_guard(request.symbol, wait=False):
                    revalidate()
                    _require(
                        _as_text(redis.get(CLAIM_KEY)) == claim,
                        "LIVE_INCIDENT_CLAIM_DRIFT",
                    )
                    yield

            def claim_attempt(client, budget_key, circuit_key, cutoff):
                revalidate()
                key, raw = before[request.symbol]
                _require(
                    budget_key == key and circuit_key == CIRCUIT_KEY,
                    "LIVE_INCIDENT_BUDGET_INVALID",
                )
                return (
                    client.eval(
                        CLAIM_EXTRA,
                        5,
                        key,
                        circuit_key,
                        CLAIM_KEY,
                        f"{CLAIM_KEY}:{request.symbol}",
                        subscription_key,
                        raw,
                        claim,
                        subscription,
                        _epoch_millis(cutoff),
                        _LIVE_TTL_SECONDS,
                    )
                    == 1
                )

            def checked_fetch(value):
                revalidate()
                return fetch(value)

            outcome = _recover_product(
                store,
                request,
                checked_fetch,
                clock=clock,
                commit_guard=guard,
                claim_attempt=claim_attempt,
            )
            _require(
                outcome in {"RECOVERED", "NO_GAP"}, "LIVE_INCIDENT_PRODUCT_STOPPED"
            )
            results.append((request.symbol, outcome))
        revalidate()
        return {
            "status": "LIVE_INCIDENT_COMPLETE",
            "claim_sha256": sha256(claim.encode()).hexdigest(),
            "outcomes": tuple(results),
            "normal_attempt_limit_unchanged": True,
            "publishes": False,
            "execution_permitted": False,
        }
