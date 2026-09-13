"""Bounded read model for the operational-universe homepage Live overlay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol

from app.market_data.domain import BarFrequency, CanonicalBar, normalize_contract_for_symbol
from app.market_data.live_market import LiveBarObservation
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.product_retirement import normalize_symbol


_FINALIZATION_DELAY = timedelta(seconds=2)
_HEARTBEAT_FRESHNESS = timedelta(seconds=30)
_HISTORICAL_CACHE_TTL = timedelta(minutes=5)


class HomeMarketData(Protocol):
    def list_latest_dominants(self): ...

    def latest_dominant_segment(self, symbol: str): ...

    def contract_daily_bars_as_of(
        self,
        *,
        symbol: str,
        contract: str,
        as_of: datetime,
        limit: int,
    ) -> tuple[CanonicalBar, ...]: ...

    def previous_trading_day(self, symbol: str, trading_day: date) -> date: ...


class HomePhaseReader(Protocol):
    def resolve(self, symbol: str, now: datetime) -> ProductMarketPhase: ...


class HomeLiveStore(Protocol):
    def heartbeat(self): ...

    def subscriptions(self, trading_day: date): ...

    def latest_observation(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        *,
        until: datetime,
        expected_contract: str,
    ) -> LiveBarObservation | None: ...


@dataclass(frozen=True, slots=True)
class MarketHomeLiveItem:
    symbol: str
    physical_contract: str | None
    trading_day: date | None
    bar_end: datetime | None
    price: Decimal | None
    previous_close: Decimal | None
    price_change: Decimal | None
    source: Literal["completed_1m", "completed_1d", "none"]
    availability: Literal["live", "historical", "unavailable"]
    phase: Literal["TRADING", "BREAK", "CLOSED", "UNKNOWN"]
    reason: str | None
    facts_observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MarketHomeLiveSnapshot:
    observed_at: datetime
    items: tuple[MarketHomeLiveItem, ...]


class MarketHomeLiveService:
    """Read one fixed-scope snapshot without starting a provider or Runtime."""

    def __init__(
        self,
        *,
        market_data: HomeMarketData,
        phase_resolver: HomePhaseReader,
        live_store: HomeLiveStore,
        operational_products: tuple[str, ...],
    ) -> None:
        self._market_data = market_data
        self._phase_resolver = phase_resolver
        self._live_store = live_store
        self._products = tuple(normalize_symbol(item) for item in operational_products)

    def snapshot(
        self,
        now: datetime,
        *,
        previous: MarketHomeLiveSnapshot | None = None,
    ) -> MarketHomeLiveSnapshot:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("MARKET_HOME_LIVE_TIMEZONE_REQUIRED")
        observed_at = now.astimezone(UTC)
        previous_by_symbol = {
            item.symbol: item for item in previous.items
        } if previous is not None else {}
        try:
            latest_dominants = {
                item.symbol: (item.actual_contract, item.dominant_mapping_date)
                for item in self._market_data.list_latest_dominants()
                if item.symbol in self._products
            }
        except Exception:  # noqa: BLE001 - historical authority is typed unavailable
            latest_dominants = {}
        try:
            heartbeat = self._live_store.heartbeat()
            live_available = _heartbeat_available(heartbeat, observed_at)
        except Exception:  # noqa: BLE001 - Redis can only remove the Live overlay
            live_available = False

        subscription_cache: dict[date, object] = {}
        items: list[MarketHomeLiveItem] = []
        for symbol in self._products:
            try:
                phase = self._phase_resolver.resolve(symbol, observed_at)
            except Exception:  # noqa: BLE001 - phase failures remain explicit
                phase = ProductMarketPhase(symbol, MarketPhase.UNKNOWN, None, None, None)
            dominant = latest_dominants.get(symbol)
            historical_contract = (
                normalize_contract_for_symbol(symbol, dominant[0])
                if dominant is not None
                else None
            )
            mapping_day = dominant[1] if dominant is not None else None
            authority_days = tuple(
                dict.fromkeys(
                    day for day in (phase.trading_day, mapping_day) if type(day) is date
                )
            )
            live_contract = None
            live_day = None
            for authority_day in authority_days:
                if authority_day not in subscription_cache:
                    try:
                        subscription_cache[authority_day] = (
                            self._live_store.subscriptions(authority_day) or {}
                        )
                    except Exception:  # noqa: BLE001 - historical fallback remains available
                        subscription_cache[authority_day] = {}
                mapping = subscription_cache[authority_day]
                candidate = mapping.get(symbol) if hasattr(mapping, "get") else None
                normalized = normalize_contract_for_symbol(symbol, candidate)
                if normalized is not None:
                    live_contract = normalized
                    live_day = authority_day
                    break
            previous_item = previous_by_symbol.get(symbol)
            items.append(
                self._item(
                    symbol=symbol,
                    live_contract=live_contract,
                    live_day=live_day,
                    historical_contract=historical_contract,
                    phase=phase,
                    live_available=live_available,
                    now=observed_at,
                    previous=previous_item,
                )
            )
        return MarketHomeLiveSnapshot(observed_at, tuple(items))

    def refresh_item(
        self,
        symbol: str,
        now: datetime,
        *,
        previous: MarketHomeLiveItem,
    ) -> MarketHomeLiveItem:
        """Re-read one Pub/Sub wakeup through Redis provenance and current authority."""

        normalized = normalize_symbol(symbol)
        if normalized not in self._products:
            raise ValueError("MARKET_HOME_LIVE_SYMBOL_INVALID")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("MARKET_HOME_LIVE_TIMEZONE_REQUIRED")
        observed_at = now.astimezone(UTC)
        try:
            segment = self._market_data.latest_dominant_segment(normalized)
            historical_contract = normalize_contract_for_symbol(
                normalized, segment.contract
            )
            mapping_day = segment.end_trading_day
        except Exception:  # noqa: BLE001 - authority failure is represented in the item
            historical_contract = None
            mapping_day = None
        try:
            phase = self._phase_resolver.resolve(normalized, observed_at)
        except Exception:  # noqa: BLE001 - phase failures remain explicit
            phase = ProductMarketPhase(normalized, MarketPhase.UNKNOWN, None, None, None)
        try:
            live_available = _heartbeat_available(
                self._live_store.heartbeat(), observed_at
            )
        except Exception:  # noqa: BLE001 - Redis can only remove the Live overlay
            live_available = False
        live_contract = None
        live_day = None
        for authority_day in tuple(
            dict.fromkeys(
                day for day in (phase.trading_day, mapping_day) if type(day) is date
            )
        ):
            try:
                mapping = self._live_store.subscriptions(authority_day) or {}
            except Exception:  # noqa: BLE001 - historical fallback remains available
                mapping = {}
            candidate = mapping.get(normalized) if hasattr(mapping, "get") else None
            contract = normalize_contract_for_symbol(normalized, candidate)
            if contract is not None:
                live_contract = contract
                live_day = authority_day
                break
        return self._item(
            symbol=normalized,
            live_contract=live_contract,
            live_day=live_day,
            historical_contract=historical_contract,
            phase=phase,
            live_available=live_available,
            now=observed_at,
            previous=previous,
        )

    def _item(
        self,
        *,
        symbol: str,
        live_contract: str | None,
        live_day: date | None,
        historical_contract: str | None,
        phase: ProductMarketPhase,
        live_available: bool,
        now: datetime,
        previous: MarketHomeLiveItem | None,
    ) -> MarketHomeLiveItem:
        live_phase_authorized = (
            phase.phase is MarketPhase.CLOSED
            or (
                live_available
                and phase.phase in {MarketPhase.TRADING, MarketPhase.BREAK}
                and phase.trading_day == live_day
            )
        )
        if live_phase_authorized and live_day is not None and live_contract is not None:
            observation = self._latest_live(
                symbol=symbol,
                contract=live_contract,
                trading_day=live_day,
                now=now,
            )
            if observation is not None:
                baseline = self._cached_baseline(previous, live_contract, live_day, now)
                if baseline is None and not self._cached_missing_baseline(
                    previous, live_contract, live_day, now
                ):
                    baseline = self._previous_close(
                        symbol, live_contract, before_day=observation.bar.trading_day, now=now
                    )
                return _priced_item(
                    symbol=symbol,
                    contract=live_contract,
                    quote=observation.bar,
                    previous_close=baseline,
                    source="completed_1m",
                    availability="live",
                    phase=phase.phase.value,
                    now=now,
                )

        if (
            previous is not None
            and previous.physical_contract == historical_contract
            and previous.source == "completed_1d"
            and previous.availability == "historical"
            and previous.phase == phase.phase.value
            and previous.facts_observed_at is not None
            and timedelta(0)
            <= now - previous.facts_observed_at
            <= _HISTORICAL_CACHE_TTL
        ):
            return previous
        historical = self._historical_pair(symbol, historical_contract, now=now)
        if historical is not None:
            assert historical_contract is not None
            quote, baseline = historical
            return _priced_item(
                symbol=symbol,
                contract=historical_contract,
                quote=quote,
                previous_close=baseline,
                source="completed_1d",
                availability="historical",
                phase=phase.phase.value,
                now=now,
            )
        return MarketHomeLiveItem(
            symbol=symbol,
            physical_contract=historical_contract or live_contract,
            trading_day=None,
            bar_end=None,
            price=None,
            previous_close=None,
            price_change=None,
            source="none",
            availability="unavailable",
            phase=phase.phase.value,
            reason="PRICE_UNAVAILABLE",
            facts_observed_at=now,
        )

    def _latest_live(
        self,
        *,
        symbol: str,
        contract: str,
        trading_day: date,
        now: datetime,
    ) -> LiveBarObservation | None:
        cutoff = now - _FINALIZATION_DELAY
        try:
            observation = self._live_store.latest_observation(
                trading_day,
                symbol,
                BarFrequency.M1.value,
                until=cutoff,
                expected_contract=contract,
            )
        except Exception:  # noqa: BLE001 - provenance or Redis failure removes Live only
            return None
        if (
            observation is None
            or observation.contract != contract
            or observation.bar.trading_day != trading_day
            or observation.bar.bar_end > cutoff
        ):
            return None
        return observation

    def _historical_pair(
        self,
        symbol: str,
        contract: str | None,
        *,
        now: datetime,
    ) -> tuple[CanonicalBar, Decimal | None] | None:
        bars = self._contract_daily_bars(symbol, contract, now=now)
        if not bars:
            return None
        quote = bars[-1]
        baseline = self._exact_previous_close(symbol, bars, quote.trading_day)
        return quote, baseline

    def _previous_close(
        self,
        symbol: str,
        contract: str,
        *,
        before_day: date,
        now: datetime,
    ) -> Decimal | None:
        bars = self._contract_daily_bars(symbol, contract, now=now)
        return self._exact_previous_close(symbol, bars, before_day)

    def _exact_previous_close(
        self,
        symbol: str,
        bars: tuple[CanonicalBar, ...],
        before_day: date,
    ) -> Decimal | None:
        try:
            expected_day = self._market_data.previous_trading_day(symbol, before_day)
        except Exception:  # noqa: BLE001 - missing Calendar authority fails closed
            return None
        return next(
            (item.close for item in reversed(bars) if item.trading_day == expected_day),
            None,
        )

    def _contract_daily_bars(
        self,
        symbol: str,
        contract: str | None,
        *,
        now: datetime,
    ) -> tuple[CanonicalBar, ...]:
        if contract is None:
            return ()
        try:
            bars = tuple(
                self._market_data.contract_daily_bars_as_of(
                    symbol=symbol,
                    contract=contract,
                    as_of=now,
                    limit=5,
                )
            )
            if any(type(item) is not CanonicalBar or item.bar_end > now for item in bars) or any(
                current.bar_end <= prior.bar_end
                or current.trading_day <= prior.trading_day
                for prior, current in zip(bars, bars[1:], strict=False)
            ):
                return ()
            return bars
        except Exception:  # noqa: BLE001 - missing Canonical facts stay unavailable
            return ()

    @staticmethod
    def _cached_baseline(
        previous: MarketHomeLiveItem | None,
        contract: str,
        trading_day: date,
        now: datetime,
    ) -> Decimal | None:
        if (
            previous is not None
            and previous.physical_contract == contract
            and previous.trading_day == trading_day
            and previous.source == "completed_1m"
            and previous.facts_observed_at is not None
            and timedelta(0)
            <= now - previous.facts_observed_at
            <= _HISTORICAL_CACHE_TTL
        ):
            return previous.previous_close
        return None

    @staticmethod
    def _cached_missing_baseline(
        previous: MarketHomeLiveItem | None,
        contract: str,
        trading_day: date,
        now: datetime,
    ) -> bool:
        return (
            previous is not None
            and previous.physical_contract == contract
            and previous.trading_day == trading_day
            and previous.source == "completed_1m"
            and previous.previous_close is None
            and previous.reason == "PREVIOUS_CLOSE_UNAVAILABLE"
            and previous.facts_observed_at is not None
            and timedelta(0)
            <= now - previous.facts_observed_at
            <= _HISTORICAL_CACHE_TTL
        )


def _priced_item(
    *,
    symbol: str,
    contract: str,
    quote: CanonicalBar,
    previous_close: Decimal | None,
    source: Literal["completed_1m", "completed_1d"],
    availability: Literal["live", "historical"],
    phase: Literal["TRADING", "BREAK", "CLOSED", "UNKNOWN"] | str,
    now: datetime,
) -> MarketHomeLiveItem:
    if previous_close is None:
        price_change = None
        reason = "PREVIOUS_CLOSE_UNAVAILABLE"
    elif previous_close == 0:
        price_change = None
        reason = "PREVIOUS_CLOSE_ZERO"
    else:
        price_change = quote.close / previous_close - Decimal(1)
        reason = None
    return MarketHomeLiveItem(
        symbol=symbol,
        physical_contract=contract,
        trading_day=quote.trading_day,
        bar_end=quote.bar_end,
        price=quote.close,
        previous_close=previous_close,
        price_change=price_change,
        source=source,
        availability=availability,
        phase=phase,  # type: ignore[arg-type]
        reason=reason,
        facts_observed_at=now,
    )


def _heartbeat_available(value: object, now: datetime) -> bool:
    if not hasattr(value, "get") or value.get("available") is not True:  # type: ignore[union-attr]
        return False
    generated_at = value.get("generated_at")  # type: ignore[union-attr]
    if not isinstance(generated_at, str):
        return False
    try:
        generated = datetime.fromisoformat(generated_at)
    except ValueError:
        return False
    if generated.tzinfo is None or generated.utcoffset() is None:
        return False
    age = now - generated.astimezone(UTC)
    return timedelta(0) <= age <= _HEARTBEAT_FRESHNESS
