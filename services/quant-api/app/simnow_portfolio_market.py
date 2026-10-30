"""One read-only natural market inlet for a controlled multi-product SimNow host."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import text

from app.alerts.runtime import _parse_live_bar_trigger
from app.db.session import SessionLocal
from app.market_data.composition import build_market_read_service
from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery
from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
from app.market_data.operational_universe import load_operational_products
from app.redis_connections import get_redis_connection
from app.simnow_controlled_market import MarketBridge


@dataclass(frozen=True, slots=True)
class SessionPlan:
    trading_day: date | None
    active: bool
    connect_allowed: bool
    next_open_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuditWindow:
    products: tuple[str, ...]
    trading_day: date
    boundary: datetime


class PortfolioMarket:
    """Shares one Redis pubsub while retaining MarketBridge's proof per product."""

    def __init__(
        self, products, *, redis=None, session_factory=None, receipt_clock=None
    ):
        operational = set(load_operational_products())
        chosen = tuple(product.upper() for product in products)
        if (
            not chosen
            or len(set(chosen)) != len(chosen)
            or any(product.lower() not in operational for product in chosen)
        ):
            raise ValueError("PRODUCT_NOT_OPERATIONAL")
        self.products = chosen
        self._session_factory = session_factory or SessionLocal
        self._receipt_clock = receipt_clock or (lambda: datetime.now(UTC))
        self.redis = redis if redis is not None else get_redis_connection()
        self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe(
            *(f"live:bar:{product.lower()}:60m" for product in chosen)
        )
        self.started: datetime | None = None
        self.issues: dict[str, str] = {}
        # These views allocate no Redis clients or subscriptions. They only reuse
        # the existing single-product authority, recovery and signal proofs.
        self._views: dict[str, MarketBridge] = {}
        for product in chosen:
            view = object.__new__(MarketBridge)
            view.product = product
            view.identity = SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT, product.lower(), BarFrequency.H1, limit=32
            )
            view.reader = self.reader
            self._views[product] = view

    @contextmanager
    def reader(self):
        with self._session_factory() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            yield db, build_market_read_service(db, redis=self.redis)

    def activate(self, now: datetime) -> None:
        # Any queued message predating activation is recovery, not first-seen.
        while self.pubsub.get_message(timeout=0) is not None:
            pass
        self.started = now
        for view in self._views.values():
            view.started = now

    @staticmethod
    def _channel_product(channel: object) -> str | None:
        if isinstance(channel, bytes):
            try:
                channel = channel.decode("utf-8")
            except UnicodeError:
                return None
        if not isinstance(channel, str):
            return None
        parts = channel.split(":")
        if len(parts) != 4 or parts[:2] != ["live", "bar"] or parts[3] != "60m":
            return None
        return parts[2].upper()

    def poll(self, now: datetime, after: datetime | Mapping[str, datetime]):
        if self.started is None:
            raise ValueError("NATURAL_SOURCE_NOT_ACTIVATED")
        latest: dict[str, tuple[Any, datetime]] = {}
        while (message := self.pubsub.get_message(timeout=0)) is not None:
            received_at = self._receipt_clock()
            if message.get("type") != "message":
                continue
            product = self._channel_product(message.get("channel"))
            if product not in self._views:
                continue
            trigger = _parse_live_bar_trigger(
                message.get("channel"), message.get("data")
            )
            if (
                trigger is None
                or trigger.symbol != product.lower()
                or trigger.frequency != BarFrequency.H1
            ):
                latest.pop(product, None)
                self.issues[product] = "NATURAL_TRIGGER_INVALID"
                continue
            previous = latest.get(product)
            if previous is None or trigger.bar.bar_end > previous[0].bar.bar_end:
                latest[product] = (trigger, received_at)

        signals = []
        for product, (trigger, received_at) in latest.items():
            floor = (
                after.get(product, after.get(product.lower(), self.started))
                if isinstance(after, Mapping)
                else after
            )
            try:
                signal = self._views[product].signal_from_trigger(
                    trigger, received_at, floor
                )
            except ValueError as exc:
                # Public issue values are fixed codes; no DB or provider diagnostics.
                self.issues[product] = (
                    str(exc)
                    if str(exc)
                    in {
                        "NATURAL_BAR_NOT_COMPLETED",
                        "LATEST_NATURAL_OBSERVATION_UNPROVEN",
                        "NATURAL_TRIGGER_INVALID",
                        "HTDY_EXECUTION_REQUIRES_60M_WINDOW32",
                        "HTDY_EXECUTION_REQUIRES_FIRST_SEEN",
                    }
                    else "MARKET_INPUT_UNPROVEN"
                )
                continue
            except Exception:
                self.issues[product] = "MARKET_INPUT_UNPROVEN"
                continue
            if self.issues.get(product) in {
                "NATURAL_TRIGGER_INVALID",
                "NATURAL_BAR_NOT_COMPLETED",
                "LATEST_NATURAL_OBSERVATION_UNPROVEN",
                "MARKET_INPUT_UNPROVEN",
                "HTDY_EXECUTION_REQUIRES_60M_WINDOW32",
                "HTDY_EXECUTION_REQUIRES_FIRST_SEEN",
            }:
                self.issues.pop(product)
            if signal is not None:
                signals.append(signal)
        return tuple(
            sorted(
                signals,
                key=lambda item: (item.observed_at, item.product, item.source_id),
            )
        )

    def authority(self, product: str, day: date, now: datetime, contract=None):
        normalized = product.upper()
        if normalized not in self._views:
            raise ValueError("PRODUCT_NOT_OPERATIONAL")
        return self._views[normalized].authority(day, now, contract)

    def recovery(self, state, now: datetime):
        known = {item.product for item in state.products}
        result = []
        for product in self.products:
            if product not in known:
                self.issues[product] = "RECOVERY_STATE_MISSING"
                continue
            try:
                result.extend(self._views[product].recovery(state, now))
            except Exception:
                self.issues[product] = "RECOVERY_INPUT_UNPROVEN"
            else:
                if self.issues.get(product) in {
                    "RECOVERY_STATE_MISSING",
                    "RECOVERY_INPUT_UNPROVEN",
                }:
                    self.issues.pop(product)
        return tuple(result)

    def closed_observation_allowed(self, now: datetime) -> bool:
        """Fresh authority for account-only observation; never an execution permit."""
        from app.db.readonly import readonly_transaction
        if now.tzinfo is None or now.utcoffset() is None:
            return False
        try:
            with self._session_factory() as db, readonly_transaction(db, timeout_seconds=15):
                resolver = MarketPhaseResolver(db)
                for product in self.products:
                    phase = resolver.resolve(product.lower(), now)
                    if (phase.phase is not MarketPhase.CLOSED
                            or getattr(phase, 'current_session', None) is not None
                            or phase.next_session_start is None
                            or phase.next_session_start <= now):
                        return False
                return bool(self.products)
        except Exception:
            return False

    def next_audit_boundary(self, now: datetime) -> datetime | None:
        """Compatibility inlet for callers that only need the earliest boundary."""
        window = self.audit_window(now)
        return window.boundary if window is not None else None

    def audit_window(self, now: datetime) -> AuditWindow | None:
        """Prove the active scope and stop before any H1/Session transition."""
        from app.market_data.aggregation import expected_intraday_ends
        from app.market_data.composition import build_market_data_service

        if now.tzinfo is None or now.utcoffset() is None:
            return None
        try:
            with self._session_factory() as db:
                db.execute(text("SET TRANSACTION READ ONLY"))
                resolver = MarketPhaseResolver(db)
                market = build_market_data_service(db)
                boundaries = []
                active = []
                days = set()
                for product in self.products:
                    phase = resolver.resolve(product.lower(), now)
                    if phase.phase in {MarketPhase.CLOSED, MarketPhase.BREAK}:
                        if (
                            phase.current_session is not None
                            or phase.next_session_start is None
                            or phase.next_session_start <= now
                        ):
                            return None
                        # A resumed product can introduce an earlier decision;
                        # re-resolve the scope before crossing its next open.
                        boundaries.append(phase.next_session_start)
                        continue
                    if (
                        phase.phase is not MarketPhase.TRADING
                        or phase.trading_day is None
                        or phase.current_session is None
                        or not phase.current_session.start <= now < phase.current_session.end
                    ):
                        return None
                    ends = expected_intraday_ends(
                        market.session_windows(
                            symbol=product.lower(), trading_day=phase.trading_day
                        ),
                        BarFrequency.H1,
                    )
                    upcoming = [
                        end for end in ends if now < end <= phase.current_session.end
                    ]
                    if not upcoming:
                        return None
                    active.append(product)
                    days.add(phase.trading_day)
                    boundaries.append(min(upcoming))
                if not active or len(days) != 1:
                    return None
                return AuditWindow(tuple(active), days.pop(), min(boundaries))
        except Exception:
            return None

    def ordinary_takeover_window(self, day, now: datetime):
        from app.simnow_takeover_window import authoritative_window
        return authoritative_window(now, target_day=day)

    def plan(self, now: datetime) -> SessionPlan:
        if now.tzinfo is None or now.utcoffset() is None:
            return SessionPlan(None, False, False, None)
        phases = []
        try:
            with self._session_factory() as db:
                db.execute(text("SET TRANSACTION READ ONLY"))
                resolver = MarketPhaseResolver(db)
                for product in self.products:
                    try:
                        phase = resolver.resolve(product.lower(), now)
                        if phase.phase is MarketPhase.UNKNOWN:
                            self.issues[product] = "MARKET_PHASE_UNKNOWN"
                            continue
                        if self.issues.get(product) in {
                            "MARKET_PHASE_UNKNOWN",
                            "CALENDAR_UNPROVEN",
                        }:
                            self.issues.pop(product)
                        phases.append((product, phase))
                    except Exception:
                        self.issues[product] = "MARKET_PHASE_UNKNOWN"
                active_days = {
                    phase.trading_day
                    for _, phase in phases
                    if phase.phase is MarketPhase.TRADING
                }
                if None in active_days or len(active_days) > 1:
                    for product in self.products:
                        self.issues[product] = "CALENDAR_UNPROVEN"
                    return SessionPlan(None, False, False, None)
                active = bool(active_days)
                next_open = min(
                    (
                        phase.next_session_start
                        for _, phase in phases
                        if phase.next_session_start and phase.next_session_start > now
                    ),
                    default=None,
                )
                day = next(iter(active_days), None)
                if day is None and next_open is not None:
                    opening_days = set()
                    for product, phase in phases:
                        if phase.next_session_start != next_open:
                            continue
                        try:
                            opening = resolver.resolve(product.lower(), next_open)
                        except Exception:
                            self.issues[product] = "MARKET_PHASE_UNKNOWN"
                            continue
                        if opening.phase is MarketPhase.TRADING:
                            opening_days.add(opening.trading_day)
                        else:
                            self.issues[product] = "MARKET_PHASE_UNKNOWN"
                    if None not in opening_days and len(opening_days) == 1:
                        day = next(iter(opening_days))
                if day is None:
                    break_days = {
                        phase.trading_day
                        for _, phase in phases
                        if phase.phase is MarketPhase.BREAK
                    }
                    if None not in break_days and len(break_days) == 1:
                        day = next(iter(break_days))
                connect_allowed = active or bool(
                    day is not None
                    and next_open is not None
                    and timedelta(0) <= next_open - now <= timedelta(seconds=120)
                )
                if phases and not active and next_open is None:
                    for product in self.products:
                        self.issues[product] = "CALENDAR_UNPROVEN"
                return SessionPlan(day, active, connect_allowed, next_open)
        except Exception:
            for product in self.products:
                self.issues[product] = "CALENDAR_UNPROVEN"
            return SessionPlan(None, False, False, None)

    def close(self) -> None:
        try:
            self.pubsub.close()
        finally:
            self.redis.close()
