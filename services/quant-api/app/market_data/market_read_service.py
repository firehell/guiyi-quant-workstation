"""MarketReadService：Canonical 历史与瞬态 Live overlay 的统一只读模型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol

from app.core.env import PROJECT_ROOT
from app.market_data.after_market import public_after_market_status
from app.market_data.domain import (
    CanonicalBar,
    BarFrequency,
    INTRADAY_FREQUENCIES,
    MarketSeriesPageResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
    normalize_contract_for_symbol,
)
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.live_market import LiveBarObservation


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

    def bars_between(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        start: datetime,
        end: datetime,
    ) -> tuple[CanonicalBar, ...]: ...

    def bar_observations(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        after: datetime | None,
        until: datetime,
        *,
        inclusive_after: bool,
        expected_contract: str,
    ) -> tuple[LiveBarObservation, ...]: ...


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


@dataclass(frozen=True, slots=True)
class MarketDisplaySnapshot:
    """同一次状态读取下的 Web 专用瞬态展示快照。"""

    state: MarketReadState
    source: Literal["none", "realtime", "post_close"]
    trading_day: date | None
    contract: str | None
    bars: tuple[CanonicalBar, ...]


@dataclass(frozen=True, slots=True)
class MarketObservationSnapshot:
    """One frozen read of completed Live observation identity and Bars."""

    state: MarketReadState
    source: Literal["none", "realtime", "unavailable"]
    trading_day: date | None
    contract: str | None
    bars: tuple[CanonicalBar, ...]


@dataclass(frozen=True, slots=True)
class MarketReadWindow:
    """以事件 Bar 为硬截止点的 Alert 只读窗口。"""

    symbol: str
    series_kind: str
    frequency: str
    trading_day: date
    contract: str
    cutoff: datetime
    bars: tuple[CanonicalBar, ...]
    bar_contracts: tuple[str, ...]


class MarketReadWindowError(RuntimeError):
    """Alert 窗口不能被唯一、完整解析时的稳定失败。"""


class MarketObservationSnapshotError(RuntimeError):
    """Live observation authority changed while its Bars were being read."""

    def __init__(self) -> None:
        super().__init__("MARKET_OBSERVATION_SNAPSHOT_CHANGED")


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

    def bars_until(
        self,
        identity: SeriesPageQuery,
        *,
        trading_day: date,
        end: datetime,
        limit: int = 32,
    ) -> MarketReadWindow:
        """合并 Canonical/Live，并严格停在指定 completed event Bar。"""
        if (
            identity.series_kind is not SeriesKind.ACTUAL_DOMINANT
            or identity.frequency not in INTRADAY_FREQUENCIES
            or identity.contract is not None
        ):
            raise MarketReadWindowError("MARKET_READ_IDENTITY_UNSUPPORTED")
        if end.tzinfo is None or end.utcoffset() is None:
            raise MarketReadWindowError("MARKET_READ_CUTOFF_TIMEZONE_REQUIRED")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2000:
            raise MarketReadWindowError("MARKET_READ_LIMIT_INVALID")
        cutoff = end.astimezone(UTC)

        try:
            subscriptions = self._live_store.subscriptions(trading_day)
        except Exception as exc:  # noqa: BLE001 - Alert must fail closed at the Redis seam
            raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE") from exc
        contract = normalize_contract_for_symbol(
            identity.symbol,
            subscriptions.get(identity.symbol) if subscriptions else None,
        )
        if contract is None:
            raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE")

        historical_page = self.history_page(
            replace(identity, before=cutoff + timedelta(microseconds=1), limit=limit)
        )
        historical = historical_page.bars
        try:
            live = self._live_store.bars_after(
                trading_day,
                identity.symbol,
                identity.frequency.value,
                None,
            )
        except Exception as exc:  # noqa: BLE001 - incomplete Alert input must not degrade
            raise MarketReadWindowError("MARKET_READ_LIVE_UNAVAILABLE") from exc

        deduped: dict[datetime, tuple[CanonicalBar, str]] = {}
        for bar in historical:
            if bar.bar_end > cutoff:
                continue
            owner = _resolved_contract_for_bar(
                identity.symbol,
                bar,
                historical_page.resolved_contract_segments,
            )
            deduped[bar.bar_end] = (bar, owner)
        for bar in live:
            if bar.bar_end <= cutoff:
                existing = deduped.get(bar.bar_end)
                if existing is not None:
                    historical_bar, historical_owner = existing
                    if historical_bar != bar:
                        raise MarketReadWindowError("MARKET_READ_LIVE_UNAVAILABLE")
                    if historical_owner != contract:
                        raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE")
                    continue
                deduped[bar.bar_end] = (bar, contract)
        aligned = tuple(deduped[key] for key in sorted(deduped))[-limit:]
        bars = tuple(bar for bar, _owner in aligned)
        bar_contracts = tuple(owner for _bar, owner in aligned)
        if not bars or bars[-1].bar_end != cutoff:
            raise MarketReadWindowError("MARKET_READ_CUTOFF_BAR_MISSING")
        if len(bar_contracts) != len(bars) or bar_contracts[-1] != contract:
            raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE")
        return MarketReadWindow(
            symbol=identity.symbol,
            series_kind=identity.series_kind.value,
            frequency=identity.frequency.value,
            trading_day=trading_day,
            contract=contract,
            cutoff=cutoff,
            bars=bars,
            bar_contracts=bar_contracts,
        )

    def latest_canonical_window(
        self,
        identity: SeriesPageQuery,
        *,
        trading_day: date,
        limit: int = 32,
    ) -> MarketReadWindow:
        """Read the latest eligible D1/W1 Alert window from Canonical only."""
        if (
            identity.series_kind is not SeriesKind.ACTUAL_DOMINANT
            or identity.frequency not in {BarFrequency.D1, BarFrequency.W1}
            or identity.contract is not None
        ):
            raise MarketReadWindowError("MARKET_READ_IDENTITY_UNSUPPORTED")
        page = self.history_page(replace(identity, before=None, limit=limit))
        if not page.bars:
            raise MarketReadWindowError("MARKET_READ_CUTOFF_BAR_MISSING")
        latest = page.bars[-1]
        if latest.trading_day != trading_day and (
            identity.frequency is BarFrequency.D1
            or latest.trading_day > trading_day
        ):
            raise MarketReadWindowError("MARKET_READ_CUTOFF_BAR_MISSING")
        bar_contracts = tuple(
            _resolved_contract_for_bar(
                identity.symbol,
                bar,
                page.resolved_contract_segments,
            )
            for bar in page.bars[-limit:]
        )
        contract = bar_contracts[-1]
        return MarketReadWindow(
            symbol=identity.symbol,
            series_kind=identity.series_kind.value,
            frequency=identity.frequency.value,
            trading_day=latest.trading_day,
            contract=contract,
            cutoff=latest.bar_end,
            bars=page.bars[-limit:],
            bar_contracts=bar_contracts,
        )

    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState:
        """返回统一展示状态；Redis 任意失败降级为 historical-only。"""
        canonical_end = self._canonical_end(identity)
        phase = self._phase_resolver.resolve(identity.symbol, now)
        operational = identity.symbol in self._operational_products
        live_phase = phase.phase in {MarketPhase.TRADING, MarketPhase.BREAK}
        live_contract, live_available = (
            self._live_status(
                symbol=identity.symbol,
                trading_day=phase.trading_day,
            )
            if live_phase
            else (None, False)
        )
        live_eligible = (
            live_phase
            and operational
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
        bars = self._snapshot_bars(identity, state, after=after)
        return () if bars is None else bars

    def observation_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
        *,
        inclusive_after: bool = False,
    ) -> MarketObservationSnapshot:
        """Freeze state, contract and completed Live Bars in one typed read."""

        if (
            (
                after is not None
                and (
                    not isinstance(after, datetime)
                    or after.tzinfo is None
                    or after.utcoffset() is None
                )
            )
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
            or type(inclusive_after) is not bool
        ):
            raise ValueError("MARKET_OBSERVATION_SNAPSHOT_INVALID")
        now_utc = now.astimezone(UTC)
        state = self.state(identity, now_utc)
        if (
            not state.live_eligible
            or not state.live_available
            or state.trading_day is None
            or state.live_contract is None
        ):
            return MarketObservationSnapshot(
                state=state,
                source="none",
                trading_day=state.trading_day,
                contract=state.live_contract,
                bars=(),
            )
        boundary = _later(
            after.astimezone(UTC) if after is not None else None,
            state.canonical_end,
        )
        try:
            observations = (
                self._live_store.bar_observations(
                    state.trading_day,
                    identity.symbol,
                    identity.frequency.value,
                    boundary,
                    now_utc,
                    inclusive_after=inclusive_after,
                    expected_contract=state.live_contract,
                )
                if boundary is None or boundary <= now_utc
                else ()
            )
            if any(
                type(item) is not LiveBarObservation
                or type(item.bar) is not CanonicalBar
                or item.contract != state.live_contract
                for item in observations
            ):
                raise ValueError("LIVE_BAR_PROVENANCE_INVALID")
            bars = tuple(item.bar for item in observations)
        except Exception:  # noqa: BLE001 - typed read failure, no write or fallback
            return MarketObservationSnapshot(
                state=state,
                source="unavailable",
                trading_day=state.trading_day,
                contract=state.live_contract,
                bars=(),
            )
        try:
            post_read_state = self.state(identity, now_utc)
        except Exception as exc:  # noqa: BLE001 - a stable snapshot cannot be proven
            raise MarketObservationSnapshotError() from exc
        if _observation_authority(state) != _observation_authority(post_read_state):
            raise MarketObservationSnapshotError()
        return MarketObservationSnapshot(
            state=post_read_state,
            source="realtime",
            trading_day=post_read_state.trading_day,
            contract=post_read_state.live_contract,
            bars=tuple(bars),
        )

    def display_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> MarketDisplaySnapshot:
        """读取 Web 展示快照；收盘快照不扩大严格实时消费者语义。"""
        state = self.state(identity, now)
        if (
            state.live_eligible
            and state.live_available
            and state.trading_day is not None
            and state.live_contract is not None
        ):
            bars = self._snapshot_bars(identity, state, after=after)
            if bars is None:
                return _empty_display_snapshot(state)
            return MarketDisplaySnapshot(
                state=state,
                source="realtime",
                trading_day=state.trading_day,
                contract=state.live_contract,
                bars=bars,
            )

        if (
            state.phase != MarketPhase.CLOSED.value
            or not state.operational
            or state.trading_day is None
            or identity.frequency not in INTRADAY_FREQUENCIES
        ):
            return _empty_display_snapshot(state)

        contract = self._subscription_contract(
            symbol=identity.symbol,
            trading_day=state.trading_day,
        )
        if contract is None or not (
            identity.series_kind is SeriesKind.ACTUAL_DOMINANT
            or (
                identity.series_kind is SeriesKind.CONTRACT
                and identity.contract == contract
            )
        ):
            return _empty_display_snapshot(state)

        bars = self._snapshot_bars(identity, state, after=after)
        if bars is None:
            return _empty_display_snapshot(state)
        return MarketDisplaySnapshot(
            state=state,
            source="post_close",
            trading_day=state.trading_day,
            contract=contract,
            bars=bars,
        )

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
        contract = normalize_contract_for_symbol(
            symbol, subscriptions.get(symbol) if subscriptions else None
        )
        return contract, bool(heartbeat and heartbeat.get("available") is True)

    def _subscription_contract(self, *, symbol: str, trading_day: date) -> str | None:
        try:
            subscriptions = self._live_store.subscriptions(trading_day)
        except Exception:  # noqa: BLE001 - Redis failure must preserve historical display
            return None
        return normalize_contract_for_symbol(
            symbol,
            subscriptions.get(symbol) if subscriptions else None,
        )

    def _snapshot_bars(
        self,
        identity: SeriesPageQuery,
        state: MarketReadState,
        *,
        after: datetime | None,
    ) -> tuple[CanonicalBar, ...] | None:
        assert state.trading_day is not None
        cutoff = _later(after, state.canonical_end)
        try:
            source = self._live_store.bars_after(
                state.trading_day,
                identity.symbol,
                identity.frequency.value,
                cutoff,
            )
        except Exception:  # noqa: BLE001 - transient Redis must not break historical display
            return None
        deduped = {
            bar.bar_end: bar
            for bar in source
            if bar.trading_day == state.trading_day
            and (cutoff is None or bar.bar_end > cutoff)
        }
        return tuple(deduped[key] for key in sorted(deduped))


def _resolved_contract_for_bar(
    symbol: str,
    bar: CanonicalBar,
    segments: tuple[ResolvedContractSegment, ...],
) -> str:
    owners = tuple(
        segment.contract
        for segment in segments
        if segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
    )
    if len(owners) != 1:
        raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE")
    contract = normalize_contract_for_symbol(symbol, owners[0])
    if contract is None:
        raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE")
    return contract


def _later(first: datetime | None, second: datetime | None) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def _observation_authority(state: MarketReadState) -> tuple[object, ...]:
    return (
        state.symbol,
        state.series_kind,
        state.frequency,
        state.operational,
        state.phase,
        state.trading_day,
        state.live_eligible,
        state.live_available,
        state.live_contract,
        state.canonical_end,
    )


def _empty_display_snapshot(state: MarketReadState) -> MarketDisplaySnapshot:
    return MarketDisplaySnapshot(
        state=state,
        source="none",
        trading_day=None,
        contract=None,
        bars=(),
    )


def _load_after_market_status(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        payload = {}
    return MappingProxyType(public_after_market_status(payload))
