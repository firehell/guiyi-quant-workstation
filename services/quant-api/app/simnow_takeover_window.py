"""Read-only ordinary takeover authority, shared by deployment and the host."""

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo
from hashlib import sha256
import json
from sqlalchemy import select
from app.db.session import SessionLocal
from app.db.readonly import readonly_transaction
from app.market_data.composition import build_market_data_service
from app.market_data.market_phase import MarketPhaseResolver, MarketPhase
from app.market_data.operational_universe import load_operational_products
from app.market_data.session_clock import resolved_session_windows_for_trading_day
from app.models import TradingCalendar


POLICY = "simnow_ordinary_next_session_v2"


def _require(ok):
    if not ok:
        raise ValueError("ORDINARY_TAKEOVER_WINDOW_UNPROVEN")


def _resolve(db, now, target_day, require_closed):
    products = tuple(sorted(load_operational_products()))
    _require(len(products) == len(set(products)) == 60)
    resolver = MarketPhaseResolver(db)
    phases = {p: resolver.resolve(p, now) for p in products}
    _require(all(p.phase is not MarketPhase.UNKNOWN for p in phases.values()))
    if target_day is None:
        days = set()
        for product, phase in phases.items():
            _require(phase.next_session_start is not None)
            upcoming = resolver.resolve(product, phase.next_session_start)
            _require(
                upcoming.phase is MarketPhase.TRADING
                and upcoming.current_session is not None
                and upcoming.current_session.start == phase.next_session_start
                and upcoming.trading_day is not None
            )
            days.add(upcoming.trading_day)
        _require(len(days) == 1)
        target_day = days.pop()
    if isinstance(target_day, str):
        target_day = datetime.strptime(target_day, "%Y%m%d").date()
    _require(type(target_day) is date)
    market = build_market_data_service(db)
    facts, spans, starts_by_product = [], set(), {}
    for product in products:
        exchange = market.catalog.exchange_for_symbol(product)
        calendar = db.scalar(
            select(TradingCalendar).where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.trade_date == target_day,
            )
        )
        _require(
            calendar is not None
            and calendar.is_trading_day
            and calendar.provider == "rqdata"
        )
        windows = resolved_session_windows_for_trading_day(
            db, exchange=exchange, symbol=product, trading_day=target_day
        )
        windows = tuple(
            w for w in windows if not w.is_night or calendar.has_night_session
        )
        _require(bool(windows) and all(w.window.start < w.window.end for w in windows))
        sessions = [
            dict(
                name=w.name,
                start=w.window.start.isoformat(),
                end=w.window.end.isoformat(),
                is_night=w.is_night,
            )
            for w in windows
        ]
        spans.update((w.window.start, w.window.end) for w in windows)
        starts_by_product[product] = {w.window.start for w in windows}
        facts.append(
            dict(
                product=product,
                exchange=exchange,
                calendar=dict(
                    day=target_day.isoformat(),
                    is_trading_day=True,
                    has_night_session=calendar.has_night_session,
                    provider=calendar.provider,
                ),
                sessions=sessions,
            )
        )
    absent = all(p.current_session is None for p in phases.values())
    closed = absent and all(
        p.phase in {MarketPhase.CLOSED, MarketPhase.BREAK} for p in phases.values()
    )
    nexts = [p.next_session_start for p in phases.values()]
    if require_closed:
        # Every product's actual upcoming Session must belong to the frozen day.
        for product, phase in phases.items():
            _require(phase.next_session_start in starts_by_product[product])
            upcoming = resolver.resolve(product, phase.next_session_start)
            _require(
                upcoming.trading_day == target_day
                and upcoming.phase is MarketPhase.TRADING
                and upcoming.current_session is not None
                and upcoming.current_session.start == phase.next_session_start
            )
    fresh = datetime.now(UTC) if require_closed else now
    gap = min(((n - fresh).total_seconds() for n in nexts if n is not None), default=-1)
    if require_closed:
        _require(
            closed
            and all(n is not None and n > fresh + timedelta(seconds=660) for n in nexts)
        )
    starts = [a for a, b in spans if a > now]
    start = min(starts) if starts else min(a for a, b in spans)
    sessions = [dict(start=a.isoformat(), end=b.isoformat()) for a, b in sorted(spans)]
    identity = sha256(
        json.dumps(
            facts, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
        ).encode()
    ).hexdigest()
    return dict(
        policy=POLICY,
        trading_day=target_day.strftime("%Y%m%d"),
        authoritative=True,
        product_count=60,
        current_session_absent=absent,
        window_open=closed and gap > 660,
        next_session_gap_seconds=gap,
        session_start=start.isoformat(),
        connect_after=(start - timedelta(seconds=120)).isoformat(),
        connect_until=(start + timedelta(seconds=120)).isoformat(),
        sessions=sessions,
        session_facts_sha256=identity,
    )


def authoritative_window(now, target_day=None, require_closed=False):
    try:
        _require(
            isinstance(now, datetime)
            and now.tzinfo is not None
            and now.utcoffset() is not None
        )
        _require(type(require_closed) is bool)
        with SessionLocal() as db, readonly_transaction(db, timeout_seconds=60):
            return _resolve(db, now, target_day, require_closed)
    except Exception:
        raise ValueError("ORDINARY_TAKEOVER_WINDOW_UNPROVEN") from None


def _historical(db, now):
    products = tuple(sorted(load_operational_products()))
    _require(len(products) == len(set(products)) == 60)
    market = build_market_data_service(db)
    days = tuple(
        db.scalars(
            select(TradingCalendar.trade_date)
            .where(
                TradingCalendar.trade_date
                <= now.astimezone(ZoneInfo("Asia/Shanghai")).date(),
                TradingCalendar.is_trading_day.is_(True),
                TradingCalendar.provider == "rqdata",
            )
            .distinct()
            .order_by(TradingCalendar.trade_date.desc())
            .limit(64)
        )
    )
    for day in days:
        entries = []
        ended = True
        for product in products:
            exchange = market.catalog.exchange_for_symbol(product)
            calendar = db.scalar(
                select(TradingCalendar).where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.trade_date == day,
                )
            )
            _require(
                calendar is not None
                and calendar.is_trading_day
                and calendar.provider == "rqdata"
            )
            windows = tuple(
                w
                for w in resolved_session_windows_for_trading_day(
                    db, exchange=exchange, symbol=product, trading_day=day
                )
                if not w.is_night or calendar.has_night_session
            )
            _require(
                bool(windows) and all(w.window.start < w.window.end for w in windows)
            )
            ended = ended and all(w.window.end <= now for w in windows)
            entries.append(
                dict(
                    product=product,
                    exchange=exchange,
                    calendar=dict(
                        day=day.isoformat(),
                        is_trading_day=True,
                        has_night_session=calendar.has_night_session,
                        provider=calendar.provider,
                    ),
                    sessions=[
                        dict(
                            name=w.name,
                            start=w.window.start.isoformat(),
                            end=w.window.end.isoformat(),
                            is_night=w.is_night,
                        )
                        for w in windows
                    ],
                )
            )
        if not ended:
            continue
        # Select the latest completed authoritative day before resolving maps.
        # A missing map on that day cannot silently fall back to an older day.
        for item in entries:
            owner = market.dominant_segment_for_day(item["product"], day)
            item["owner"] = json.loads(json.dumps(asdict(owner), default=str))
        digest = sha256(
            json.dumps(
                entries, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        return dict(
            policy="simnow_completed_contract_anchor_v1",
            trading_day=day.strftime("%Y%m%d"),
            product_count=60,
            sha256=digest,
            entries=entries,
        )
    raise ValueError("HISTORICAL_CONTRACT_ANCHOR_UNPROVEN")


def historical_contract_anchor(now):
    """History only; never supplies a future-day execution binding."""
    try:
        _require(
            isinstance(now, datetime)
            and now.tzinfo is not None
            and now.utcoffset() is not None
        )
        with SessionLocal() as db, readonly_transaction(db, timeout_seconds=60):
            return _historical(db, now)
    except Exception:
        raise ValueError("HISTORICAL_CONTRACT_ANCHOR_UNPROVEN") from None
