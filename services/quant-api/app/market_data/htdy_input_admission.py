"""Read-only HTDY 60m input diagnostics; never a first-seen signal source.

Historical completeness, retained Live continuity and eligibility for a future
natural observation are deliberately separate. Callers own the read-only DB
transaction and the lifetime of the injected MarketReadService/Redis client.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import re

from app.alerts.evaluators import HtdyOriginalEvaluator
from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery, SeriesQuery
from app.market_data.market_read_service import MarketReadService, MarketReadWindow
from app.market_data.operational_universe import load_operational_products


def safe_error(error: Exception) -> list[dict[str, str]]:
    """Return diagnostic codes, without connection details or source payloads."""
    result = []
    seen = set()
    while error is not None and id(error) not in seen and len(result) < 6:
        seen.add(id(error))
        code = str(getattr(error, "code", None) or str(error))
        result.append({
            "type": type(error).__name__,
            "code": code if re.fullmatch(r"[A-Z][A-Z0-9_]{1,120}", code) else "DETAIL_REDACTED",
        })
        error = error.__cause__
    return result


def _owned_source(mds, product, contract, day, cutoff):
    pairs = mds.expected_contract_replay_endpoints(
        symbol=product, contract=contract, frequency=BarFrequency.M1,
        trading_day=day, cutoff=cutoff, since=day,
    )
    ends = tuple(end for end, owner in pairs)
    if not ends or any(owner != day or end > cutoff for end, owner in pairs):
        raise ValueError("HTDY_SOURCE_ENDPOINT_INVALID")
    result = mds.query_maintenance_expected(
        SeriesQuery(SeriesKind.CONTRACT, product, BarFrequency.M1,
                    ends[0] - timedelta(microseconds=1), ends[-1], contract=contract),
        ends,
    )
    if (tuple(bar.bar_end for bar in result.bars) != ends
            or any(bar.trading_day != day for bar in result.bars)):
        raise ValueError("HTDY_SOURCE_ENDPOINT_INVALID")
    return result.bars


def _sessions_through(mds, product, day, cutoff):
    return tuple(
        SessionWindow(window.start, min(window.end, cutoff))
        for window in mds.session_windows(symbol=product, trading_day=day)
        if window.start < cutoff
    )


def _calculation_source(market_read, product, contract, day, cutoff, observation_day):
    """Use the same physical Canonical + retained-original distinction as H1.

    The MDS published-prefix seam supplies quality-verified Canonical facts;
    Live is independently provenance-checked. This is an explicit union, not
    a fallback after a failed Canonical query. Shared values must agree.
    """
    mds = market_read._market_data
    if day != observation_day:
        return _owned_source(mds, product, contract, day, cutoff)
    pairs = mds.expected_contract_replay_endpoints(
        symbol=product, contract=contract, frequency=BarFrequency.M1,
        trading_day=day, cutoff=cutoff, since=day,
    )
    expected = tuple(end for end, owner in pairs)
    if not expected or any(owner != day for end, owner in pairs):
        raise ValueError("HTDY_SOURCE_ENDPOINT_INVALID")
    page = mds.query_alert_history_prefix(SeriesPageQuery(
        SeriesKind.ACTUAL_DOMINANT, product, BarFrequency.M1,
        before=cutoff + timedelta(microseconds=1), limit=2000,
    ))
    source = {bar.bar_end: bar for bar in page.bars if bar.trading_day == day}
    original = market_read._verified_live_bars(
        trading_day=day, symbol=product, frequency=BarFrequency.M1,
        cutoff=cutoff, contract=contract,
    )
    for bar in original:
        if bar.bar_end in source and source[bar.bar_end] != bar:
            raise ValueError("HTDY_SOURCE_ORIGINAL_CANONICAL_CONFLICT")
        source[bar.bar_end] = bar
    if tuple(sorted(source)) != expected or any(bar.trading_day != day for bar in source.values()):
        raise ValueError("HTDY_SOURCE_ENDPOINT_INVALID")
    return tuple(source[end] for end in expected)


def _verify_window(market_read, product, bars, contracts, *, observation_day=None):
    mds = market_read._market_data
    if len(bars) != 32 or len(contracts) != len(bars):
        raise ValueError("HTDY_WARMUP_WINDOW_INSUFFICIENT")
    current = bars[-1]
    mds.validate_actual_dominant_alert_window(
        symbol=product, frequency=BarFrequency.H1, trading_day=current.trading_day,
        current_contract=contracts[-1], cutoff=current.bar_end, bars=bars, bar_contracts=contracts,
    )
    checked, minute_count = [], 0
    for source_day in dict.fromkeys(bar.trading_day for bar in bars):
        selected = tuple(bar for bar in bars if bar.trading_day == source_day)
        owner = mds.dominant_segment_for_day(product, source_day).contract
        cutoff = selected[-1].bar_end
        source = (_owned_source(mds, product, owner, source_day, cutoff)
                  if observation_day is None else _calculation_source(
                      market_read, product, owner, source_day, cutoff, observation_day))
        sessions = _sessions_through(mds, product, source_day, cutoff)
        derived = aggregate_from_1m(source, target_frequency=BarFrequency.H1, sessions=sessions)
        by_end = {bar.bar_end: bar for bar in derived}
        if any(by_end.get(bar.bar_end) != bar for bar in selected):
            raise ValueError("H1_SOURCE_1M_AGGREGATION_MISMATCH")
        minute_count += len(source)
        checked.append({"day": source_day, "contract": owner, "source_1m": len(source),
                        "selected_h1": len(selected), "session_count": len(sessions)})
    window = MarketReadWindow(product, "actual_dominant", "60m", current.trading_day,
                              contracts[-1], current.bar_end, bars, contracts)
    # Historical calculation only, never evaluate_first_seen/candidates.
    result = HtdyOriginalEvaluator().evaluate(window)
    return dict(
        status="WINDOW32_VERIFIED", bars=len(bars), first=bars[0].bar_end,
        last=current.bar_end, trading_day=current.trading_day, contract=contracts[-1],
        kernel_result=result.observation_types, source_1m_status="VERIFIED",
        source_1m_count=minute_count, source_days=checked, aggregation_parity="EXACT",
        source_hash=sha256(repr((bars, contracts)).encode()).hexdigest(),
    )


def audit_product(
    market_read: MarketReadService, coverage, product: str, at: datetime,
) -> dict:
    """Check one operational product without fetching, changing state or trading.

    ``at`` is an explicit snapshot cutoff. The caller must use a read-only
    transaction; this function calls only the existing MDS and Live read seams.
    All latest endpoints are resolved from Calendar/Session, never Redis keys.
    """
    if (not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None
            or at > datetime.now(UTC)):
        raise ValueError("HTDY_ADMISSION_TIME_INVALID")
    if product not in load_operational_products():
        raise ValueError("HTDY_ADMISSION_PRODUCT_INVALID")
    at = at.astimezone(UTC)
    row = {
        "product": product, "at": at, "readonly": True,
        "provider_requests": 0, "production_writes": 0,
        "history": {"status": "UNVERIFIED"},
        "live": {"status": "UNVERIFIED"},
        "calculation_input": {"status": "UNVERIFIED"},
        "future_signal": {
            "status": "BLOCKED", "eligible_now": False,
            "first_seen_proven": False,
            "reason": "AUDIT_IS_NOT_FIRST_SEEN_EVIDENCE",
        },
    }
    try:
        mds = market_read._market_data
        phase = market_read._phase_resolver.resolve(product, at)
        row["phase"] = {
            "phase": phase.phase.value, "trading_day": phase.trading_day,
            "next_session_start": phase.next_session_start,
        }
        if phase.phase.value == "UNKNOWN":
            raise ValueError("HTDY_ADMISSION_SESSION_UNKNOWN")
        row["latest_complete_trading_day"] = coverage.latest_complete_day((product,))
        query = SeriesPageQuery(SeriesKind.ACTUAL_DOMINANT, product, BarFrequency.H1,
                                before=at + timedelta(microseconds=1), limit=32)
        end, day, contract = market_read.newow_completed_observation_endpoint(query, at)
        # No H1 is due yet in a newly started Session: inspect the prior complete
        # day as a baseline, without treating it as the current day's signal.
        due = end is not None
        if not due:
            day = row["latest_complete_trading_day"]
            contract = mds.dominant_segment_for_day(product, day).contract
            completed = tuple(window.end for window in mds.session_windows(
                symbol=product, trading_day=day) if window.end <= at)
            if not completed:
                raise ValueError("HTDY_ADMISSION_COMPLETED_ENDPOINT_MISSING")
            end = max(completed)
        if end > at:
            raise ValueError("HTDY_ADMISSION_ENDPOINT_IN_FUTURE")
        row["expected_endpoint"] = end
        row["expected_trading_day"] = day
        row["expected_contract"] = contract
        row["endpoint_age_seconds"] = (at - end).total_seconds()
    except Exception as error:
        row.update(status="BLOCKED", errors=safe_error(error))
        return row

    try:
        historical_query = SeriesPageQuery(
            SeriesKind.ACTUAL_DOMINANT, product, BarFrequency.H1,
            before=end + timedelta(microseconds=1), limit=32,
        )
        page = mds.query_alert_history_prefix(historical_query)
        bars = page.bars
        if len(bars) != 32:
            raise ValueError("HTDY_WARMUP_WINDOW_INSUFFICIENT")
        contracts = tuple(mds.dominant_segment_for_day(product, bar.trading_day).contract for bar in bars)
        row["history"].update(_verify_window(market_read, product, bars, contracts))
        row["history"]["covers_latest_endpoint"] = bars[-1].bar_end == end
    except Exception as error:
        row["history"].update(status="BLOCKED", errors=safe_error(error))

    try:
        if not due:
            row["live"].update(status="NOT_DUE", reason="NO_CURRENT_COMPLETED_ENDPOINT_YET")
        else:
            row["live"].update(expected_endpoint=end, trading_day=day, contract=contract)
            actual = {}
            for frequency, label in ((BarFrequency.M1, "source_1m"), (BarFrequency.H1, "h1")):
                pairs = mds.expected_contract_replay_endpoints(
                    symbol=product, contract=contract, frequency=frequency,
                    trading_day=day, cutoff=end, since=day,
                )
                expected = tuple(point for point, owner in pairs)
                if any(owner != day for point, owner in pairs):
                    raise ValueError("HTDY_LIVE_ENDPOINT_INVALID")
                source = market_read._verified_live_bars(
                    trading_day=day, symbol=product, frequency=frequency, cutoff=end, contract=contract,
                )
                actual[frequency] = source
                observed = tuple(bar.bar_end for bar in source)
                missing = tuple(sorted(set(expected) - set(observed)))
                extras = tuple(sorted(set(observed) - set(expected)))
                row["live"][label] = {
                    "expected": len(expected), "actual": len(observed),
                    "missing_count": len(missing), "missing_ends": missing,
                    "extra_count": len(extras), "extra_ends": extras,
                    "ordered_unique": observed == tuple(sorted(set(observed))),
                    "source_hash": sha256(repr(source).encode()).hexdigest(),
                }
            if any(row["live"][label]["missing_count"] or row["live"][label]["extra_count"]
                   or not row["live"][label]["ordered_unique"] for label in ("source_1m", "h1")):
                raise ValueError("LIVE_SOURCE_INCOMPLETE")
            derived = aggregate_from_1m(
                actual[BarFrequency.M1], target_frequency=BarFrequency.H1,
                sessions=_sessions_through(mds, product, day, end),
            )
            if derived != actual[BarFrequency.H1]:
                raise ValueError("LIVE_H1_SOURCE_1M_AGGREGATION_MISMATCH")
            # This shared seam retains original-vs-Canonical conflicts and
            # recovery fences. Historical publication cannot make it pass by
            # replacing the separately verified raw Live set above.
            live_window = market_read.bars_until(query, trading_day=day, end=end, limit=32)
            row["live"].update(
                status="CONTINUITY_VERIFIED", source_aggregation_parity="EXACT",
                recovery_fenced=not live_window.notification_eligible,
            )
    except Exception as error:
        row["live"].update(status="BLOCKED", errors=safe_error(error))

    try:
        if due:
            # Always use the native merged reader. Even a full Canonical repair
            # must not hide an original/Canonical conflict or owner/recovery drift.
            current = market_read.bars_until(query, trading_day=day, end=end, limit=32)
            if (current.cutoff != end or current.trading_day != day or current.contract != contract
                    or not current.bars or current.bars[-1].bar_end != end):
                raise ValueError("HTDY_CALCULATION_ENDPOINT_INVALID")
            row["calculation_input"].update(_verify_window(
                market_read, product, current.bars, current.bar_contracts, observation_day=day))
            row["calculation_input"].update(
                source="canonical_and_retained_live", recovery_fenced=not current.notification_eligible,
            )
        elif (row["history"]["status"] == "WINDOW32_VERIFIED"
              and row["history"]["covers_latest_endpoint"]
              and row["history"]["trading_day"] == day
              and row["history"]["contract"] == contract):
            row["calculation_input"].update(row["history"], source="canonical_baseline")
        else:
            raise ValueError("HTDY_CALCULATION_BASELINE_UNAVAILABLE")
    except Exception as error:
        row["calculation_input"].update(status="BLOCKED", errors=safe_error(error))

    calculation_ready = row["calculation_input"]["status"] == "WINDOW32_VERIFIED"
    live_ready = row["live"]["status"] in {"CONTINUITY_VERIFIED", "NOT_DUE"}
    row["status"] = ("HISTORICAL_READY_LIVE_BLOCKED" if calculation_ready and not live_ready else
                     "INPUTS_VERIFIED_WAIT_NEW_OBSERVATION" if calculation_ready else "BLOCKED")
    if calculation_ready:
        row["future_signal"].update(
            status="WAIT_NEW_COMPLETED_OBSERVATION", session_state=phase.phase.value,
            prior_live_blocked=not live_ready,
            required="NEW_ORIGINAL_OBSERVATION_WITH_NATIVE_FRESHNESS_AND_RECOVERY_CHECKS",
        )
    if (row["status"] == "BLOCKED" and row["history"].get("status") == "WINDOW32_VERIFIED"
            and phase.phase.value == "CLOSED" and row["latest_complete_trading_day"] >= day):
        from app.market_data.htdy_source_conflicts import classify_closed_difference

        try:
            row["source_conflict"] = classify_closed_difference(
                market_read, coverage, product=product, day=day, contract=contract,
                end=end, at=at, history=row["history"],
            )
            row["status"] = "CLOSED_SOURCE_REVISION_WAIT_NEW_OBSERVATION"
            row["future_signal"].update(
                status="WAIT_NEW_TRADING_DAY_OBSERVATION",
                next_trading_day=row["source_conflict"]["next_trading_day"],
                required="NEW_ORIGINAL_OBSERVATION_WITH_NATIVE_FRESHNESS_AND_RECOVERY_CHECKS",
            )
        except Exception as error:
            row["source_conflict"] = {"status": "BLOCKED", "errors": safe_error(error)}
    return row


def summarize(rows: list[dict], at: datetime) -> dict:
    """Produce an inspectable snapshot, retaining all three independent axes."""
    return {
        "schema_version": "htdy_60m_input_admission_v2", "at": at,
        "readonly": True, "provider_requests": 0, "production_writes": 0,
        "product_count": len(rows), "operational_product_count": len(load_operational_products()),
        "counts": dict(Counter(row["status"] for row in rows)),
        "history_counts": dict(Counter(row["history"]["status"] for row in rows)),
        "calculation_counts": dict(Counter(row["calculation_input"]["status"] for row in rows)),
        "live_counts": dict(Counter(row["live"]["status"] for row in rows)),
        "closed_source_difference_count": sum(row.get("source_conflict", {}).get("status") == "CLOSED_DAY_DIFFERENCE_VERIFIED" for row in rows),
        "first_seen_proven": False, "rows": rows,
    }
