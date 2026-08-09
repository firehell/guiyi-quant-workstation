"""Market Web 的统一只读模型：Canonical 历史与瞬态 Live overlay 严格分层。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Protocol

from app.core.env import PROJECT_ROOT
from app.market_data.domain import (
    CanonicalBar,
    INTRADAY_FREQUENCIES,
    MarketSeriesPageResult,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.market_phase import ProductMarketPhase


_CONCRETE_CONTRACT = re.compile(r"(?P<symbol>[A-Z]+)(?P<month>\d{3,4})\Z")


class MarketPageReader(Protocol):
    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult: ...


class PhaseReader(Protocol):
    def resolve(self, symbol: str, now: datetime) -> ProductMarketPhase: ...


class LiveReadStore(Protocol):
    def subscriptions(self, trading_day: date) -> Mapping[str, object] | None: ...

    def heartbeat(self) -> Mapping[str, object] | None: ...

    def bars_after(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        after: datetime | None,
    ) -> tuple[CanonicalBar, ...]: ...


@dataclass(frozen=True, slots=True)
class MarketReadState:
    symbol: str
    series_kind: str
    frequency: str
    operational: bool
    phase: str
    trading_day: date | None
    live_eligible: bool
    live_available: bool
    live_contract: str | None
    canonical_end: datetime | None
    after_market: Mapping[str, object]


class MarketReadService:
    """展示查询 facade；历史始终经 ``MarketDataService``，Live 只读 Redis。"""

    def __init__(
        self,
        *,
        market_data: MarketPageReader,
        phase_resolver: PhaseReader,
        operational_products: tuple[str, ...],
        live_store: LiveReadStore,
        after_market_status_path: Path | None = None,
    ) -> None:
        self._market_data = market_data
        self._phase_resolver = phase_resolver
        self._operational_products = frozenset(item.strip().lower() for item in operational_products)
        self._live_store = live_store
        self._after_market_status_path = (
            after_market_status_path or PROJECT_ROOT / ".run" / "after-market-status.json"
        )

    def history_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        """读取正式历史页；不直接接触 Parquet 或 Live Redis。"""
        return self._market_data.query_page(request)

    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState:
        """返回统一展示状态；Redis 任意失败降级为 historical-only。"""
        canonical_end = self._canonical_end(identity)
        phase = self._phase_resolver.resolve(identity.symbol, now)
        operational = identity.symbol in self._operational_products
        live_contract, live_available = self._live_status(
            symbol=identity.symbol,
            trading_day=phase.trading_day,
        )
        live_eligible = (
            operational
            and identity.frequency in INTRADAY_FREQUENCIES
            and live_contract is not None
            and (
                identity.series_kind is SeriesKind.ACTUAL_DOMINANT
                or (
                    identity.series_kind is SeriesKind.CONTRACT
                    and identity.contract == live_contract
                )
            )
        )
        return MarketReadState(
            symbol=identity.symbol,
            series_kind=identity.series_kind.value,
            frequency=identity.frequency.value,
            operational=operational,
            phase=phase.phase.value,
            trading_day=phase.trading_day,
            live_eligible=live_eligible,
            live_available=live_eligible and live_available,
            live_contract=live_contract,
            canonical_end=canonical_end,
            after_market=_load_after_market_status(self._after_market_status_path),
        )

    def live_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> tuple[CanonicalBar, ...]:
        """读取 canonical seam 之后的 transient Live bars，Redis 失败返回空快照。"""
        state = self.state(identity, now)
        if not state.live_eligible or not state.live_available or state.trading_day is None:
            return ()
        cutoff = _later(after, state.canonical_end)
        try:
            source = self._live_store.bars_after(
                state.trading_day,
                identity.symbol,
                identity.frequency.value,
                cutoff,
            )
        except Exception:  # noqa: BLE001 - transient Redis must not break historical display
            return ()
        deduped = {bar.bar_end: bar for bar in source if state.canonical_end is None or bar.bar_end > state.canonical_end}
        return tuple(deduped[key] for key in sorted(deduped))

    def _canonical_end(self, identity: SeriesPageQuery) -> datetime | None:
        latest = self.history_page(replace(identity, before=None, limit=1))
        return latest.bars[0].bar_end if latest.bars else None

    def _live_status(self, *, symbol: str, trading_day: date | None) -> tuple[str | None, bool]:
        if trading_day is None:
            return None, False
        try:
            subscriptions = self._live_store.subscriptions(trading_day)
            heartbeat = self._live_store.heartbeat()
        except Exception:  # noqa: BLE001 - Redis is an explicit historical-safe boundary
            return None, False
        contract = _current_contract(symbol, subscriptions.get(symbol) if subscriptions else None)
        return contract, bool(heartbeat and heartbeat.get("available") is True)


def _current_contract(symbol: str, value: object) -> str | None:
    if not isinstance(value, str):
        return None
    contract = value.strip().upper()
    match = _CONCRETE_CONTRACT.fullmatch(contract)
    if match is None or match.group("symbol") != symbol.upper():
        return None
    month = int(match.group("month")[-2:])
    return contract if 1 <= month <= 12 else None


def _later(first: datetime | None, second: datetime | None) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def _load_after_market_status(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        payload = {}
    return MappingProxyType(payload if isinstance(payload, dict) else {})
