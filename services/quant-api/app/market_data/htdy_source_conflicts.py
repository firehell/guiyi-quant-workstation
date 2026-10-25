"""Read-only disposition of complete closed-day Live/history differences.

This proves retained facts and a later Calendar boundary, not the cause/time of
provider revisions, a restored observation, or permission to execute a signal.
"""

from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re

from app.market_data.aggregation import aggregate_from_1m, expected_intraday_ends
from app.market_data.domain import BarFrequency, CanonicalBar, SeriesKind, SeriesQuery

FIELDS = ("open", "high", "low", "close", "volume", "turnover", "open_interest")
POLICY = "htdy_closed_day_source_difference_v1"


def _require(value, code="HTDY_SOURCE_DIFFERENCE_UNPROVED"):
    if not value:
        raise ValueError(code)


def _hash(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _series(bars, expected, day):
    _require(tuple(b.bar_end for b in bars) == expected)
    for bar in bars:
        _require(type(bar) is CanonicalBar and bar.trading_day == day)
        _require(
            all(
                v is None or isinstance(v, Decimal) and v.is_finite()
                for v in (getattr(bar, f) for f in FIELDS)
            )
        )
        _require(
            min(bar.open, bar.high, bar.low, bar.close) > 0
            and bar.low
            <= min(bar.open, bar.close)
            <= max(bar.open, bar.close)
            <= bar.high
        )
        _require(
            all(
                getattr(bar, f) is None or getattr(bar, f) >= 0
                for f in ("volume", "turnover", "open_interest")
            )
        )
        _require(bar.volume is not None)
        _require(
            all(
                v is None or v == v.to_integral_value()
                for v in (bar.volume, bar.open_interest)
            )
        )


def _differences(original, canonical):
    result = []
    for left, right in zip(original, canonical, strict=True):
        _require(
            left.bar_end == right.bar_end and left.trading_day == right.trading_day
        )
        delta = {}
        for field in FIELDS:
            a, b = getattr(left, field), getattr(right, field)
            _require(
                (a is None) == (b is None), "HTDY_SOURCE_DIFFERENCE_OPTIONAL_UNKNOWN"
            )
            if a != b:
                delta[field] = {"original": str(a), "canonical": str(b)}
        if delta:
            result.append(
                {
                    "bar_end": left.bar_end,
                    "trading_day": left.trading_day,
                    "fields": delta,
                }
            )
    return result


def classify_closed_difference(
    market_read, coverage, *, product, day, contract, end, at, history
):
    """Explain old closed-day differences; leave the original reader blocked."""
    mds = market_read._market_data
    phase = market_read._phase_resolver.resolve(product, at)
    _require(
        phase.phase.value == "CLOSED"
        and coverage.latest_complete_day((product,)) >= day
    )
    _require(
        history.get("status") == "WINDOW32_VERIFIED"
        and history.get("covers_latest_endpoint")
        and history.get("last") == end
        and history.get("trading_day") == day
        and history.get("contract") == contract
    )
    sessions = mds.session_windows(symbol=product, trading_day=day)
    _require(sessions and max(s.end for s in sessions) == end and end < at)
    _require(mds.dominant_segment_for_day(product, day).contract == contract)
    _require(mds.catalog.contract_fact(product, contract).provider == "rqdata")
    _require(market_read._live_store.subscriptions(day).get(product) == contract)
    recovery = market_read._read_recovery_state(day, product, contract)
    next_start = phase.next_session_start
    _require(
        next_start is not None and next_start > at,
        "HTDY_SOURCE_DIFFERENCE_NEXT_SESSION_UNPROVED",
    )
    upcoming = market_read._phase_resolver.resolve(product, next_start)
    _require(
        upcoming.phase.value == "TRADING"
        and upcoming.trading_day is not None
        and upcoming.trading_day > day
        and upcoming.current_session is not None
        and upcoming.current_session.start == next_start,
        "HTDY_SOURCE_DIFFERENCE_NEXT_SESSION_UNPROVED",
    )
    next_owner = mds.dominant_segment_for_day(product, upcoming.trading_day).contract
    _require(next_owner, "HTDY_SOURCE_DIFFERENCE_NEXT_OWNER_UNPROVED")
    next_fact = mds.catalog.contract_fact(product, next_owner)
    _require(
        next_fact.provider == "rqdata"
        and next_fact.symbol == product
        and next_fact.contract == next_owner
        and next_fact.listed_date <= upcoming.trading_day < next_fact.expired_date,
        "HTDY_SOURCE_DIFFERENCE_NEXT_OWNER_UNPROVED",
    )
    next_recovery = market_read._read_recovery_state(
        upcoming.trading_day, product, next_owner
    )
    _require(
        next_recovery is None or next_recovery.recovered_through < next_start,
        "HTDY_SOURCE_DIFFERENCE_NEXT_RECOVERY_FENCED",
    )
    next_sessions = mds.session_windows(
        symbol=product, trading_day=upcoming.trading_day
    )
    next_ends = expected_intraday_ends(next_sessions, BarFrequency.H1)
    _require(next_ends and next_ends[0] > at and next_sessions[0].start == next_start)
    _require(
        mds.expected_contract_replay_endpoints(
            symbol=product,
            contract=next_owner,
            frequency=BarFrequency.H1,
            trading_day=upcoming.trading_day,
            cutoff=next_ends[0],
            since=upcoming.trading_day,
        )
        == ((next_ends[0], upcoming.trading_day),),
        "HTDY_SOURCE_DIFFERENCE_NEXT_OWNER_UNPROVED",
    )
    _require(
        recovery is None or recovery.recovered_through < next_start,
        "HTDY_SOURCE_DIFFERENCE_RECOVERY_FENCED",
    )

    original, canonical, proof = {}, {}, {}
    for frequency in (BarFrequency.M1, BarFrequency.H1):
        pairs = mds.expected_contract_replay_endpoints(
            symbol=product,
            contract=contract,
            frequency=frequency,
            trading_day=day,
            cutoff=end,
            since=day,
        )
        expected = tuple(point for point, owner in pairs)
        _require(expected and all(owner == day for point, owner in pairs))
        _require(expected == expected_intraday_ends(sessions, frequency))
        canonical[frequency] = mds.query_maintenance_expected(
            SeriesQuery(
                SeriesKind.CONTRACT,
                product,
                frequency,
                expected[0] - timedelta(microseconds=1),
                end,
                contract=contract,
            ),
            expected,
        ).bars
        original[frequency] = market_read._verified_live_bars(
            trading_day=day,
            symbol=product,
            frequency=frequency,
            cutoff=end,
            contract=contract,
        )
        _series(canonical[frequency], expected, day)
        _series(original[frequency], expected, day)
        manifest = mds.contract_source_evidence(
            symbol=product,
            contract=contract,
            frequency=frequency,
            before=end + timedelta(microseconds=1),
        )
        _require(
            manifest.get("contract") == contract
            and manifest.get("frequency") == frequency.value
            and manifest.get("partitions")
        )
        _require(
            all(
                re.fullmatch("[0-9a-f]{64}", p.get("content_sha256", ""))
                and "quality_sha256" in p
                for p in manifest["partitions"]
            )
        )
        delta = _differences(original[frequency], canonical[frequency])
        proof[frequency.value] = {
            "bar_count": len(expected),
            "different_bar_count": len(delta),
            "differences": delta,
            "original_sha256": _hash([b.as_record() for b in original[frequency]]),
            "canonical_sha256": _hash([b.as_record() for b in canonical[frequency]]),
            "canonical_source": manifest,
        }
    for source in (original, canonical):
        _require(
            aggregate_from_1m(
                source[BarFrequency.M1],
                target_frequency=BarFrequency.H1,
                sessions=sessions,
            )
            == source[BarFrequency.H1],
            "HTDY_SOURCE_DIFFERENCE_AGGREGATION_INVALID",
        )
    _require(
        any(p["different_bar_count"] for p in proof.values()),
        "HTDY_SOURCE_DIFFERENCE_NOT_FOUND",
    )
    _require(
        recovery == market_read._read_recovery_state(day, product, contract)
        and market_read._live_store.subscriptions(day).get(product) == contract
    )
    for frequency in (BarFrequency.M1, BarFrequency.H1):
        _require(
            original[frequency]
            == market_read._verified_live_bars(
                trading_day=day,
                symbol=product,
                frequency=frequency,
                cutoff=end,
                contract=contract,
            ),
            "HTDY_SOURCE_DIFFERENCE_ORIGINAL_CHANGED",
        )
    _require(
        next_recovery
        == market_read._read_recovery_state(upcoming.trading_day, product, next_owner),
        "HTDY_SOURCE_DIFFERENCE_NEXT_RECOVERY_CHANGED",
    )
    # Only a diagnostic. No MarketReadWindow or replayable Signal is returned.
    result = {
        "policy_version": POLICY,
        "status": "CLOSED_DAY_DIFFERENCE_VERIFIED",
        "product": product,
        "contract": contract,
        "trading_day": day,
        "through": end,
        "verified_at": at,
        "frequencies": proof,
        "next_trading_day": upcoming.trading_day,
        "next_contract": next_owner,
        "next_session_start": next_start,
        "next_expected_h1": next_ends[0],
        "next_recovery_state": None
        if next_recovery is None
        else {
            "revision": next_recovery.revision,
            "recovered_through": next_recovery.recovered_through,
        },
        "next_contract_fact": {
            "contract": next_owner,
            "provider": next_fact.provider,
            "listed_date": next_fact.listed_date,
            "expired_date": next_fact.expired_date,
        },
        "next_owner_warmup_and_natural_input_pending": True,
        "recovery_state": None
        if recovery is None
        else {
            "revision": recovery.revision,
            "recovered_through": recovery.recovered_through,
        },
        "historical_authority": "QUALITY_VERIFIED_CANONICAL",
        "disposition": "PRESERVE_ORIGINAL_WAIT_NEW_TRADING_DAY",
        "cause_of_difference": "NOT_INFERRED",
        "original_input_still_blocked": True,
        "natural_acceptance_pending": True,
        "provider_requests": 0,
        "production_writes": 0,
        "first_seen_proven": False,
    }
    return {**result, "evidence_sha256": _hash(result)}
