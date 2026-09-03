"""Read-only Market Runtime promotion preflight."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
from pathlib import Path
import sys
from typing import Any, Protocol, TextIO, cast


PROMOTION_LIVE_SNAPSHOT_REQUIRED = "MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_REQUIRED"
PROMOTION_LIVE_SNAPSHOT_INVALID = "MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_INVALID"
PROMOTION_STATE_UNAVAILABLE = "MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE"
_COMMAND = "runtime.market-promotion-preflight"
_INVALID = object()

class _InvalidTradingDay:
    pass


_INVALID_TRADING_DAY = _InvalidTradingDay()


class PhaseResolver(Protocol):
    def resolve(self, symbol: str, now: datetime) -> Any: ...


FirstSessionStartsLoader = Callable[
    [Any, tuple[str, ...], date], Mapping[str, datetime]
]


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    status: str
    reason: str
    trading_day: date | None
    operational_count: int
    snapshot_count: int

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": _COMMAND,
            "status": self.status,
            "reason": self.reason,
            "trading_day": (
                self.trading_day.isoformat() if self.trading_day is not None else None
            ),
            "operational_count": self.operational_count,
            "snapshot_count": self.snapshot_count,
        }


def evaluate_market_runtime_promotion(
    *,
    products: tuple[str, ...],
    phases: Mapping[str, Any] | None,
    now: datetime,
    snapshot: object,
    after_market_status: object,
    first_session_starts: Mapping[str, datetime] | None,
) -> PromotionDecision:
    """Classify a promotion only from existing runtime observations."""
    snapshot_count = len(snapshot) if isinstance(snapshot, Mapping) else 0
    def unavailable() -> PromotionDecision:
        return _blocked(
            PROMOTION_STATE_UNAVAILABLE, None, len(products), snapshot_count
        )
    if not products or len(set(products)) != len(products) or phases is None:
        return unavailable()
    if now.tzinfo is None or now.utcoffset() is None or set(phases) != set(products):
        return unavailable()
    ordered_phases = tuple(phases[product] for product in products)
    if any(
        getattr(item, "symbol", None) != product or _phase_name(item) == "UNKNOWN"
        for product, item in zip(products, ordered_phases, strict=True)
    ):
        return unavailable()

    trading_day = _resolved_trading_day(ordered_phases)
    if isinstance(trading_day, _InvalidTradingDay):
        return unavailable()
    status_decision = _after_market_status_decision(
        after_market_status,
        trading_day=trading_day,
        products=products,
        now=now,
    )
    if status_decision in {"unavailable", "running"}:
        return _blocked(
            PROMOTION_STATE_UNAVAILABLE,
            trading_day,
            len(products),
            snapshot_count,
        )
    if trading_day is None:
        if all(
            _phase_name(item) == "CLOSED"
            and getattr(item, "current_session", None) is None
            and getattr(item, "trading_day", None) is None
            for item in ordered_phases
        ):
            return _passed("non_trading_interval", None, len(products), snapshot_count)
        return unavailable()
    assert isinstance(trading_day, date)
    if not _valid_first_session_starts(first_session_starts, products):
        return unavailable()
    assert first_session_starts is not None
    if snapshot is not None:
        if not _valid_snapshot(snapshot, products):
            return _blocked(
                PROMOTION_LIVE_SNAPSHOT_INVALID,
                trading_day,
                len(products),
                snapshot_count,
            )
        return _passed("snapshot_ready", trading_day, len(products), snapshot_count)

    if _before_first_session(first_session_starts, now):
        return _passed("before_first_session", trading_day, len(products), 0)

    if status_decision == "passed":
        return _passed("after_market_complete", trading_day, len(products), 0)
    if status_decision == "unavailable":
        return _blocked(PROMOTION_STATE_UNAVAILABLE, trading_day, len(products), 0)
    return _blocked(PROMOTION_LIVE_SNAPSHOT_REQUIRED, trading_day, len(products), 0)


def run_market_runtime_promotion_preflight(
    *,
    session_factory: Callable[[], AbstractContextManager[Any]] | None = None,
    phase_resolver_factory: Callable[[Any], PhaseResolver] | None = None,
    live_store_factory: Callable[[], Any] | None = None,
    products_loader: Callable[[], tuple[str, ...]] | None = None,
    first_session_starts_loader: FirstSessionStartsLoader | None = None,
    status_path: Path | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PromotionDecision:
    """Read the existing runtime state and fail closed at every dependency edge."""
    try:
        if session_factory is None:
            from app.db.session import SessionLocal

            session_factory = SessionLocal
        if phase_resolver_factory is None:
            from app.market_data.market_phase import MarketPhaseResolver

            phase_resolver_factory = MarketPhaseResolver
        if products_loader is None:
            from app.market_data.operational_universe import load_operational_products

            products_loader = load_operational_products
        if status_path is None:
            from app.core.env import PROJECT_ROOT

            status_path = PROJECT_ROOT / ".run" / "after-market-status.json"
        products = products_loader()
        current_time = now()
        with session_factory() as session:
            resolver = phase_resolver_factory(session)
            phases = {product: resolver.resolve(product, current_time) for product in products}
            resolved_day = _resolved_trading_day(
                tuple(phases[product] for product in products)
            )
            first_session_starts = (
                (first_session_starts_loader or _first_session_starts_for_products)(
                    session, products, resolved_day
                )
                if isinstance(resolved_day, date)
                else None
            )
        store = (
            live_store_factory()
            if live_store_factory is not None
            else _default_live_store()
        )
        trading_day = _resolved_trading_day(tuple(phases[product] for product in products))
        snapshot: object = None
        if isinstance(trading_day, date):
            try:
                snapshot = store.subscriptions(trading_day)
            except (TypeError, ValueError):
                snapshot = _INVALID
        status = _load_after_market_status(status_path)
        return evaluate_market_runtime_promotion(
            products=products,
            phases=phases,
            now=current_time,
            snapshot=snapshot,
            after_market_status=status,
            first_session_starts=first_session_starts,
        )
    except Exception:  # noqa: BLE001 - process boundary must never disclose internals
        return _blocked(PROMOTION_STATE_UNAVAILABLE, None, 0, 0)


def main(stdout: TextIO = sys.stdout) -> int:
    """Emit exactly one bounded public JSON preflight payload."""
    decision = run_market_runtime_promotion_preflight()
    stdout.write(json.dumps(decision.payload(), separators=(",", ":")) + "\n")
    return 0 if decision.status == "passed" else 1


def _resolved_trading_day(
    phases: tuple[Any, ...],
) -> date | _InvalidTradingDay | None:
    if not phases:
        return _INVALID_TRADING_DAY
    active = tuple(
        item
        for item in phases
        if _phase_name(item) in {"TRADING", "BREAK"}
    )
    candidate = active if active else phases
    days = {
        getattr(item, "trading_day", None)
        for item in candidate
        if getattr(item, "trading_day", None) is not None
    }
    if active and (
        len(days) != 1 or any(getattr(item, "trading_day", None) is None for item in active)
    ):
        return _INVALID_TRADING_DAY
    if not active and days and any(getattr(item, "trading_day", None) is None for item in phases):
        return _INVALID_TRADING_DAY
    if not active and len(days) > 1:
        return _INVALID_TRADING_DAY
    return next(iter(days), None)


def _valid_snapshot(snapshot: object, products: tuple[str, ...]) -> bool:
    from app.market_data.domain import normalize_contract_for_symbol

    if not isinstance(snapshot, Mapping):
        return False
    normalized: dict[str, str] = {}
    for symbol, contract in snapshot.items():
        if not isinstance(symbol, str):
            return False
        normalized_symbol = symbol.strip().lower()
        if normalized_symbol in normalized:
            return False
        normalized_contract = normalize_contract_for_symbol(normalized_symbol, contract)
        if normalized_contract is None:
            return False
        normalized[normalized_symbol] = normalized_contract
    return set(normalized) == set(products)


def _valid_first_session_starts(
    starts: Mapping[str, datetime] | None, products: tuple[str, ...]
) -> bool:
    return (
        starts is not None
        and set(starts) == set(products)
        and all(
            value.tzinfo is not None and value.utcoffset() is not None
            for value in starts.values()
        )
    )


def _before_first_session(starts: Mapping[str, datetime], now: datetime) -> bool:
    return all(start > now for start in starts.values())


def _after_market_status_decision(
    value: object,
    *,
    trading_day: date | None,
    products: tuple[str, ...],
    now: datetime,
) -> str:
    if value is None:
        return "missing"
    try:
        from app.market_data.after_market import public_after_market_status

        public = public_after_market_status(value)
    except Exception:  # noqa: BLE001 - public status reader is a fail-closed edge
        return "unavailable"
    if not public:
        return "unavailable"
    if public.get("current_run") is not None:
        return "running"
    last_run = public.get("last_run")
    if not isinstance(last_run, Mapping):
        return "missing"
    if last_run.get("status") != "passed":
        return "missing"
    if trading_day is None:
        return "missing"
    if last_run.get("trading_day") != trading_day.isoformat():
        return "missing"
    started_at = _timestamp(last_run.get("started_at"))
    finished_at = _timestamp(last_run.get("finished_at"))
    if (
        started_at is None
        or finished_at is None
        or started_at > finished_at
        or finished_at > now.astimezone(UTC)
    ):
        return "unavailable"
    run_products = last_run.get("products")
    if not isinstance(run_products, list) or tuple(run_products) != products:
        return "unavailable"
    return "passed"


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _load_after_market_status(path: Path) -> object:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return _INVALID
    return payload


def _first_session_starts_for_products(
    session: Any,
    products: tuple[str, ...],
    trading_day: date,
) -> dict[str, datetime]:
    from sqlalchemy import select

    from app.market_data.session_clock import (
        SessionClockError,
        resolved_session_windows_for_trading_day,
    )
    from app.models import Instrument, TradingCalendar
    starts: dict[str, datetime] = {}
    for symbol in products:
        exchange = session.scalar(
            select(Instrument.exchange_code).where(
                Instrument.symbol == symbol,
                Instrument.is_active.is_(True),
            )
        )
        if not isinstance(exchange, str) or not exchange:
            raise ValueError("PROMOTION_SESSION_AUTHORITY_UNAVAILABLE")
        calendar = session.scalar(
            select(TradingCalendar).where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.trade_date == trading_day,
            )
        )
        if calendar is None or not calendar.is_trading_day:
            raise ValueError("PROMOTION_SESSION_AUTHORITY_UNAVAILABLE")
        try:
            windows = resolved_session_windows_for_trading_day(
                session,
                exchange=exchange,
                symbol=symbol,
                trading_day=trading_day,
            )
        except SessionClockError as exc:
            raise ValueError("PROMOTION_SESSION_AUTHORITY_UNAVAILABLE") from exc
        eligible = tuple(
            item
            for item in windows
            if not item.is_night or calendar.has_night_session
        )
        if not eligible:
            raise ValueError("PROMOTION_SESSION_AUTHORITY_UNAVAILABLE")
        starts[symbol] = min(item.window.start for item in eligible)
    return starts


def _default_live_store() -> Any:
    from app.market_data.live_market import RedisLiveStore
    from app.redis_connections import get_redis_connection

    return RedisLiveStore(cast(Any, get_redis_connection()))


def _phase_name(item: Any) -> str | None:
    phase = getattr(item, "phase", None)
    value = getattr(phase, "value", phase)
    return value if isinstance(value, str) else None


def _passed(
    reason: str, trading_day: date | None, operational_count: int, snapshot_count: int
) -> PromotionDecision:
    return PromotionDecision("passed", reason, trading_day, operational_count, snapshot_count)


def _blocked(
    reason: str, trading_day: date | None, operational_count: int, snapshot_count: int
) -> PromotionDecision:
    return PromotionDecision("blocked", reason, trading_day, operational_count, snapshot_count)


if __name__ == "__main__":
    raise SystemExit(main())
