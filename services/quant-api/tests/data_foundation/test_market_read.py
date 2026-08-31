from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import (
    CanonicalBar,
    MarketSeriesPageResult,
    ResolvedContractSegment,
    SeriesPageQuery,
)
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.market_read_service import MarketReadService, MarketReadWindowError


def _bar(minute: int) -> CanonicalBar:
    return CanonicalBar(
        bar_end=datetime(2025, 1, 2, 1, minute, tzinfo=UTC),
        trading_day=date(2025, 1, 2),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        open_interest=Decimal("20"),
    )


def _bar_at(bar_end: datetime, *, close: str = "100") -> CanonicalBar:
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=date(2025, 1, 2),
        open=Decimal(close),
        high=Decimal(close) + 1,
        low=Decimal(close) - 1,
        close=Decimal(close),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        open_interest=Decimal("20"),
    )


class FakeMarketDataService:
    def __init__(self, latest: CanonicalBar) -> None:
        self.latest = latest
        self.queries: list[SeriesPageQuery] = []

    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        self.queries.append(request)
        return MarketSeriesPageResult(
            request_identity={"symbol": request.symbol},
            bars=(self.latest,),
            canonical_coverage=(self.latest.bar_end, self.latest.bar_end),
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=(),
        )


class FakePhaseResolver:
    def __init__(self, phase: ProductMarketPhase) -> None:
        self.phase = phase

    def resolve(self, symbol: str, now: datetime) -> ProductMarketPhase:
        assert symbol == "j"
        assert now.tzinfo is not None
        return self.phase


class FakeLiveStore:
    def __init__(self, bars: tuple[CanonicalBar, ...], *, available: bool = True) -> None:
        self.bars = bars
        self.available = available
        self.snapshot = {"j": "J2505"}

    def subscriptions(self, trading_day: date) -> dict[str, str]:
        assert trading_day == date(2025, 1, 2)
        return self.snapshot

    def heartbeat(self) -> dict[str, object]:
        return {"available": self.available}

    def bars_after(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        after: datetime | None,
    ) -> tuple[CanonicalBar, ...]:
        assert (trading_day, symbol, frequency) == (date(2025, 1, 2), "j", "1m")
        return tuple(bar for bar in self.bars if after is None or bar.bar_end > after)


class WindowMarketDataService:
    def __init__(
        self,
        bars: tuple[CanonicalBar, ...],
        *,
        expected_frequency: str = "15m",
        segments: tuple[ResolvedContractSegment, ...] = (),
    ) -> None:
        self.bars = bars
        self.expected_frequency = expected_frequency
        self.segments = segments

    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        assert request.frequency.value == self.expected_frequency
        eligible = tuple(
            bar for bar in self.bars if request.before is None or bar.bar_end < request.before
        )[-request.limit :]
        return MarketSeriesPageResult(
            request_identity={"symbol": request.symbol},
            bars=eligible,
            canonical_coverage=None,
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=self.segments,
        )


class WindowLiveStore(FakeLiveStore):
    def __init__(
        self,
        bars: tuple[CanonicalBar, ...],
        *,
        subscription: object = "J2505",
        expected_frequency: str = "15m",
    ) -> None:
        super().__init__(bars)
        self.snapshot = {"j": subscription}
        self.expected_frequency = expected_frequency

    def bars_after(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        after: datetime | None,
    ) -> tuple[CanonicalBar, ...]:
        assert (trading_day, symbol, frequency) == (
            date(2025, 1, 2),
            "j",
            self.expected_frequency,
        )
        return tuple(bar for bar in self.bars if after is None or bar.bar_end > after)


class ForbiddenPhaseResolver:
    def resolve(self, symbol: str, now: datetime) -> ProductMarketPhase:
        raise AssertionError("bars_until must not depend on current market phase")


class ForbiddenLiveStore:
    def subscriptions(self, trading_day: date) -> dict[str, str]:
        raise AssertionError("canonical window must not read Live subscriptions")

    def heartbeat(self) -> dict[str, object]:
        raise AssertionError("canonical window must not read Live heartbeat")

    def bars_after(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        after: datetime | None,
    ) -> tuple[CanonicalBar, ...]:
        raise AssertionError("canonical window must not read Live bars")


def _window_service(
    canonical: tuple[CanonicalBar, ...],
    live: tuple[CanonicalBar, ...],
    *,
    subscription: object = "J2505",
    frequency: str = "15m",
    segments: tuple[ResolvedContractSegment, ...] = (),
) -> MarketReadService:
    return MarketReadService(
        market_data=WindowMarketDataService(
            canonical,
            expected_frequency=frequency,
            segments=segments,
        ),
        phase_resolver=ForbiddenPhaseResolver(),
        operational_products=("j",),
        live_store=WindowLiveStore(
            live,
            subscription=subscription,
            expected_frequency=frequency,
        ),
    )


def _canonical_window_service(
    canonical: tuple[CanonicalBar, ...],
    *,
    frequency: str,
    segments: tuple[ResolvedContractSegment, ...],
) -> MarketReadService:
    return MarketReadService(
        market_data=WindowMarketDataService(
            canonical,
            expected_frequency=frequency,
            segments=segments,
        ),
        phase_resolver=ForbiddenPhaseResolver(),
        operational_products=("j",),
        live_store=ForbiddenLiveStore(),
    )


def _service(
    *,
    live: FakeLiveStore | None = None,
    market_phase: MarketPhase = MarketPhase.TRADING,
) -> MarketReadService:
    phase = ProductMarketPhase(
        symbol="j",
        phase=market_phase,
        trading_day=date(2025, 1, 2),
        current_session=None,
        next_session_start=None,
    )
    return MarketReadService(
        market_data=FakeMarketDataService(_bar(2)),
        phase_resolver=FakePhaseResolver(phase),
        operational_products=("j",),
        live_store=live or FakeLiveStore(()),
    )


@pytest.mark.parametrize(
    ("identity", "expected"),
    (
        (SeriesPageQuery("actual_dominant", "j", "1m"), True),
        (SeriesPageQuery("contract", "j", "1m", contract="J2505"), True),
        (SeriesPageQuery("continuous", "j", "1m"), False),
        (SeriesPageQuery("contract", "j", "1m", contract="J2509"), False),
        (SeriesPageQuery("actual_dominant", "j", "1d"), False),
        (SeriesPageQuery("actual_dominant", "j", "1w"), False),
    ),
)
def test_state_live_eligibility_requires_operational_rank1_intraday(
    identity: SeriesPageQuery,
    expected: bool,
) -> None:
    """Catches accepting continuous/non-rank1/daily series into transient Live overlay."""
    state = _service().state(identity, now=datetime(2025, 1, 2, 1, 3, tzinfo=UTC))

    assert state.live_eligible is expected


def test_closed_product_never_exposes_live_overlay() -> None:
    """Catches stale subscriptions leaking Live into a product that is CLOSED."""
    state = _service(market_phase=MarketPhase.CLOSED).state(
        SeriesPageQuery("actual_dominant", "j", "1m"),
        now=datetime(2025, 1, 2, 1, 3, tzinfo=UTC),
    )

    assert state.live_eligible is False
    assert state.live_available is False


def test_closed_display_snapshot_reads_post_close_bars_without_heartbeat() -> None:
    """Catches CLOSED refreshes dropping completed Redis bars before Canonical takeover."""
    class HeartbeatForbiddenLiveStore(FakeLiveStore):
        def heartbeat(self) -> dict[str, object]:
            raise AssertionError("post-close display must not depend on heartbeat")

    result = _service(
        live=HeartbeatForbiddenLiveStore((_bar(1), _bar(2), _bar(3))),
        market_phase=MarketPhase.CLOSED,
    ).display_snapshot(
        SeriesPageQuery("actual_dominant", "j", "1m"),
        after=None,
        now=datetime(2025, 1, 2, 1, 4, tzinfo=UTC),
    )

    assert result.state.live_eligible is False
    assert result.state.live_available is False
    assert result.source == "post_close"
    assert result.trading_day == date(2025, 1, 2)
    assert result.contract == "J2505"
    assert tuple(bar.bar_end for bar in result.bars) == (
        datetime(2025, 1, 2, 1, 3, tzinfo=UTC),
    )


def test_closed_display_snapshot_returns_none_when_redis_bars_are_unreadable() -> None:
    """Catches a Redis read failure being mislabeled as a valid frozen snapshot."""
    class BrokenBarsLiveStore(FakeLiveStore):
        def bars_after(
            self,
            trading_day: date,
            symbol: str,
            frequency: str,
            after: datetime | None,
        ) -> tuple[CanonicalBar, ...]:
            raise RuntimeError("redis unavailable")

    result = _service(
        live=BrokenBarsLiveStore(()),
        market_phase=MarketPhase.CLOSED,
    ).display_snapshot(
        SeriesPageQuery("actual_dominant", "j", "1m"),
        after=None,
        now=datetime(2025, 1, 2, 1, 4, tzinfo=UTC),
    )

    assert result.source == "none"
    assert result.trading_day is None
    assert result.contract is None
    assert result.bars == ()


@pytest.mark.parametrize("frequency", ("1m", "5m", "15m", "30m", "60m"))
def test_closed_display_snapshot_supports_each_intraday_frequency(frequency: str) -> None:
    """Catches an allowed derived intraday period being omitted from the handoff."""
    class AnyFrequencyLiveStore(FakeLiveStore):
        def bars_after(
            self,
            trading_day: date,
            symbol: str,
            requested_frequency: str,
            after: datetime | None,
        ) -> tuple[CanonicalBar, ...]:
            assert (trading_day, symbol, requested_frequency) == (
                date(2025, 1, 2),
                "j",
                frequency,
            )
            return tuple(bar for bar in self.bars if after is None or bar.bar_end > after)

    result = _service(
        live=AnyFrequencyLiveStore((_bar(3),)),
        market_phase=MarketPhase.CLOSED,
    ).display_snapshot(
        SeriesPageQuery("actual_dominant", "j", frequency),
        after=None,
        now=datetime(2025, 1, 2, 1, 4, tzinfo=UTC),
    )

    assert result.source == "post_close"
    assert result.bars == (_bar(3),)


@pytest.mark.parametrize(
    "identity",
    (
        SeriesPageQuery("continuous", "j", "1m"),
        SeriesPageQuery("contract", "j", "1m", contract="J2509"),
        SeriesPageQuery("actual_dominant", "j", "1d"),
        SeriesPageQuery("actual_dominant", "j", "1w"),
    ),
)
def test_closed_display_snapshot_rejects_unsupported_identity(
    identity: SeriesPageQuery,
) -> None:
    """Catches post-close data escaping its exact Market Web identity boundary."""
    result = _service(
        live=FakeLiveStore((_bar(3),)),
        market_phase=MarketPhase.CLOSED,
    ).display_snapshot(
        identity,
        after=None,
        now=datetime(2025, 1, 2, 1, 4, tzinfo=UTC),
    )

    assert result.source == "none"
    assert result.bars == ()


def test_closed_display_snapshot_allows_only_the_subscribed_real_contract() -> None:
    result = _service(
        live=FakeLiveStore((_bar(3),)),
        market_phase=MarketPhase.CLOSED,
    ).display_snapshot(
        SeriesPageQuery("contract", "j", "1m", contract="J2505"),
        after=None,
        now=datetime(2025, 1, 2, 1, 4, tzinfo=UTC),
    )

    assert result.source == "post_close"
    assert result.contract == "J2505"
    assert result.bars == (_bar(3),)


def test_closed_display_snapshot_filters_day_seam_and_duplicate_bar_ends() -> None:
    duplicate_end = _bar(3).bar_end
    live = FakeLiveStore((
        replace(_bar(4), trading_day=date(2025, 1, 1)),
        _bar(2),
        _bar_at(duplicate_end, close="101"),
        _bar_at(duplicate_end, close="102"),
    ))

    result = _service(live=live, market_phase=MarketPhase.CLOSED).display_snapshot(
        SeriesPageQuery("actual_dominant", "j", "1m"),
        after=None,
        now=datetime(2025, 1, 2, 1, 4, tzinfo=UTC),
    )

    assert len(result.bars) == 1
    assert result.bars[0].bar_end == duplicate_end
    assert result.bars[0].close == Decimal("102")


@pytest.mark.parametrize(
    ("phase", "trading_day", "operational_products"),
    (
        (MarketPhase.CLOSED, date(2025, 1, 2), ()),
        (MarketPhase.UNKNOWN, None, ("j",)),
        (MarketPhase.CLOSED, None, ("j",)),
    ),
)
def test_display_snapshot_requires_operational_closed_resolved_day(
    phase: MarketPhase,
    trading_day: date | None,
    operational_products: tuple[str, ...],
) -> None:
    """Catches an unscoped or unresolved product reading a Redis snapshot."""
    service = MarketReadService(
        market_data=FakeMarketDataService(_bar(2)),
        phase_resolver=FakePhaseResolver(
            ProductMarketPhase("j", phase, trading_day, None, None)
        ),
        operational_products=operational_products,
        live_store=FakeLiveStore((_bar(3),)),
    )

    result = service.display_snapshot(
        SeriesPageQuery("actual_dominant", "j", "1m"),
        after=None,
        now=datetime(2025, 1, 2, 1, 4, tzinfo=UTC),
    )

    assert result.source == "none"
    assert result.bars == ()


def test_live_snapshot_excludes_canonical_seam_and_preserves_newer_bars() -> None:
    """Catches transient Redis bars replacing or duplicating canonical historical bars."""
    canonical = _bar(2)
    live = FakeLiveStore((
        _bar(1),
        canonical,
        _bar(3),
    ))

    result = _service(live=live).live_snapshot(
        SeriesPageQuery("actual_dominant", "j", "1m"),
        after=None,
        now=datetime(2025, 1, 2, 1, 3, tzinfo=UTC),
    )

    assert tuple(bar.bar_end for bar in result) == (datetime(2025, 1, 2, 1, 3, tzinfo=UTC),)


def test_history_page_delegates_to_market_data_service() -> None:
    """Catches the read facade bypassing the canonical MarketDataService boundary."""
    request = SeriesPageQuery("continuous", "j", "1m", before=_bar(4).bar_end + timedelta(minutes=1))
    service = _service()

    result = service.history_page(request)

    assert result.bars == (_bar(2),)


def test_state_rest_degrades_to_historical_only_when_live_is_unavailable(monkeypatch) -> None:
    """Catches a Redis outage turning the chart's state read into a failed HTTP request."""
    class HistoricalSafeRead:
        def state(self, identity: SeriesPageQuery, now: datetime):
            return _service(live=FakeLiveStore((), available=False)).state(identity, now)

    monkeypatch.setattr(
        "app.api.market_live.build_market_read_service",
        lambda _session: HistoricalSafeRead(),
    )

    response = TestClient(app).get(
        "/api/v1/market/state",
        params={"series_kind": "actual_dominant", "symbol": "j", "frequency": "1m"},
    )

    assert response.status_code == 200
    assert response.json()["live_available"] is False
    assert response.json()["canonical_end"] == "2025-01-02T01:02:00Z"


def test_state_exposes_only_whitelisted_after_market_status_fields(tmp_path) -> None:
    """Catches a tampered local status file leaking arbitrary fields through Market state."""
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            {
                "last_run": {
                    "trading_day": "2026-08-10",
                    "status": "failed",
                    "attempts": 2,
                    "started_at": "2026-08-10T17:00:00+08:00",
                    "finished_at": "2026-08-10T18:00:00+08:00",
                    "products": ["J", "jm", "ap", "ag"],
                    "error_code": "LIVE_DOMINANT_MISMATCH",
                    "provider_token": "must-not-leak",
                },
                "last_successful_trading_day": "2026-08-09",
                "last_failure": {
                    "trading_day": "2026-08-10",
                    "error_code": "LIVE_DOMINANT_MISMATCH",
                    "internal_path": "/private/runtime/secret",
                },
                "debug": {"sql": "select credential from private_table"},
            }
        ),
        encoding="utf-8",
    )
    phase = ProductMarketPhase(
        symbol="j",
        phase=MarketPhase.TRADING,
        trading_day=date(2025, 1, 2),
        current_session=None,
        next_session_start=None,
    )
    service = MarketReadService(
        market_data=FakeMarketDataService(_bar(2)),
        phase_resolver=FakePhaseResolver(phase),
        operational_products=("j",),
        live_store=FakeLiveStore(()),
        after_market_status_path=status_path,
    )

    state = service.state(
        SeriesPageQuery("actual_dominant", "j", "1m"),
        now=datetime(2025, 1, 2, 1, 3, tzinfo=UTC),
    )

    assert state.after_market == {
        "last_run": {
            "trading_day": "2026-08-10",
            "status": "failed",
            "attempts": 2,
            "started_at": "2026-08-10T17:00:00+08:00",
            "finished_at": "2026-08-10T18:00:00+08:00",
            "products": ["j", "jm", "ap", "ag"],
            "error_code": "LIVE_DOMINANT_MISMATCH",
        },
        "last_successful_trading_day": "2026-08-09",
        "last_failure": {
            "trading_day": "2026-08-10",
            "error_code": "LIVE_DOMINANT_MISMATCH",
        },
    }
    assert "must-not-leak" not in json.dumps(dict(state.after_market))


@pytest.mark.parametrize(
    ("frequency", "minutes"),
    (("1m", 1), ("5m", 5), ("15m", 15), ("30m", 30), ("60m", 60)),
)
def test_bars_until_hard_cutoff_dedup_limit_and_event_day_contract(
    frequency: str,
    minutes: int,
) -> None:
    """Catches future Live bars, seam duplicates, or phase-gated contract lookup leaking into Alert."""
    start = datetime(2025, 1, 1, 16, 0, tzinfo=UTC)
    canonical = tuple(_bar_at(start + timedelta(minutes=minutes * index)) for index in range(40))
    cutoff = canonical[-2].bar_end
    live = (
        _bar_at(canonical[-3].bar_end),
        _bar_at(cutoff),
        _bar_at(cutoff + timedelta(minutes=minutes), close="103"),
    )
    owner = ResolvedContractSegment(
        contract="J2505",
        start_trading_day=date(2025, 1, 2),
        end_trading_day=date(2025, 1, 2),
    )

    window = _window_service(
        canonical,
        live,
        frequency=frequency,
        segments=(owner,),
    ).bars_until(
        SeriesPageQuery("actual_dominant", "j", frequency),
        trading_day=date(2025, 1, 2),
        end=cutoff,
        limit=32,
    )

    assert window.contract == "J2505"
    assert window.frequency == frequency
    assert window.cutoff == cutoff
    assert len(window.bars) == 32
    assert window.bar_contracts == ("J2505",) * 32
    assert window.bars[-1].bar_end == cutoff
    assert len({bar.bar_end for bar in window.bars}) == 32
    assert all(bar.bar_end <= cutoff for bar in window.bars)


def test_bars_until_rejects_latest_historical_owner_mismatching_live_snapshot() -> None:
    """Catches assigning the trigger contract to a Historical Bar owned by another rank1."""
    cutoff = datetime(2025, 1, 2, 2, 45, tzinfo=UTC)
    historical_owner = ResolvedContractSegment(
        contract="J2509",
        start_trading_day=date(2025, 1, 2),
        end_trading_day=date(2025, 1, 2),
    )

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CONTRACT_UNAVAILABLE"):
        _window_service(
            (_bar_at(cutoff),),
            (),
            subscription="J2505",
            segments=(historical_owner,),
        ).bars_until(
            SeriesPageQuery("actual_dominant", "j", "15m"),
            trading_day=date(2025, 1, 2),
            end=cutoff,
        )


@pytest.mark.parametrize("subscription", (None, "", "AG2505", "J-INVALID"))
def test_bars_until_rejects_missing_invalid_or_cross_symbol_contract(subscription: object) -> None:
    cutoff = datetime(2025, 1, 2, 2, 45, tzinfo=UTC)

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CONTRACT_UNAVAILABLE"):
        _window_service((_bar_at(cutoff),), (), subscription=subscription).bars_until(
            SeriesPageQuery("actual_dominant", "j", "15m"),
            trading_day=date(2025, 1, 2),
            end=cutoff,
        )


def test_bars_until_requires_exact_event_bar_and_alert_identity() -> None:
    cutoff = datetime(2025, 1, 2, 2, 45, tzinfo=UTC)
    owner = ResolvedContractSegment("J2505", date(2025, 1, 2), date(2025, 1, 2))
    service = _window_service(
        (_bar_at(cutoff - timedelta(minutes=15)),),
        (),
        segments=(owner,),
    )

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CUTOFF_BAR_MISSING"):
        service.bars_until(
            SeriesPageQuery("actual_dominant", "j", "15m"),
            trading_day=date(2025, 1, 2),
            end=cutoff,
        )
    unsupported = (
        SeriesPageQuery("continuous", "j", "15m"),
        SeriesPageQuery("contract", "j", "15m", contract="J2505"),
        SeriesPageQuery("actual_dominant", "j", "1d"),
        SeriesPageQuery("actual_dominant", "j", "1w"),
    )
    for identity in unsupported:
        with pytest.raises(MarketReadWindowError, match="MARKET_READ_IDENTITY_UNSUPPORTED"):
            service.bars_until(
                identity,
                trading_day=date(2025, 1, 2),
                end=cutoff,
            )


@pytest.mark.parametrize("frequency", ("1d", "1w"))
def test_latest_canonical_window_reads_d1_w1_without_live(frequency: str) -> None:
    """Catches daily or weekly Alert windows consulting transient Live state."""
    target_day = date(2025, 1, 2)
    start = datetime(2024, 11, 24, 15, 0, tzinfo=UTC)
    canonical = tuple(
        replace(
            _bar_at(start + timedelta(days=index)),
            trading_day=(start + timedelta(days=index)).date(),
        )
        for index in range(40)
    )
    assert canonical[-1].trading_day == target_day
    owner = ResolvedContractSegment(
        contract="J2505",
        start_trading_day=canonical[0].trading_day,
        end_trading_day=target_day,
    )

    window = _canonical_window_service(
        canonical,
        frequency=frequency,
        segments=(owner,),
    ).latest_canonical_window(
        SeriesPageQuery("actual_dominant", "j", frequency),
        trading_day=target_day,
        limit=32,
    )

    assert window.frequency == frequency
    assert window.trading_day == target_day
    assert window.contract == "J2505"
    assert window.cutoff == canonical[-1].bar_end
    assert window.bars == canonical[-32:]


def test_latest_canonical_window_rejects_stale_daily_trading_day() -> None:
    latest = replace(_bar_at(datetime(2025, 1, 2, 15, 0, tzinfo=UTC)), trading_day=date(2025, 1, 1))
    owner = ResolvedContractSegment("J2505", date(2025, 1, 1), date(2025, 1, 2))
    service = _canonical_window_service((latest,), frequency="1d", segments=(owner,))

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CUTOFF_BAR_MISSING"):
        service.latest_canonical_window(
            SeriesPageQuery("actual_dominant", "j", "1d"),
            trading_day=date(2025, 1, 2),
        )


def test_latest_canonical_window_returns_latest_completed_week_before_trigger_day() -> None:
    """Catches treating an ordinary mid-week prior W1 bar as a processing failure."""
    completed_week = replace(
        _bar_at(datetime(2025, 1, 3, 15, 0, tzinfo=UTC)),
        trading_day=date(2025, 1, 3),
    )
    trigger_day = date(2025, 1, 7)
    owner = ResolvedContractSegment("J2505", completed_week.trading_day, trigger_day)
    service = _canonical_window_service(
        (completed_week,),
        frequency="1w",
        segments=(owner,),
    )

    window = service.latest_canonical_window(
        SeriesPageQuery("actual_dominant", "j", "1w"),
        trading_day=trigger_day,
    )

    assert window.trading_day == completed_week.trading_day
    assert window.cutoff == completed_week.bar_end
    assert window.bars == (completed_week,)


def test_latest_canonical_window_rejects_empty_weekly_window() -> None:
    service = _canonical_window_service((), frequency="1w", segments=())

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CUTOFF_BAR_MISSING"):
        service.latest_canonical_window(
            SeriesPageQuery("actual_dominant", "j", "1w"),
            trading_day=date(2025, 1, 7),
        )


def test_latest_canonical_window_rejects_future_weekly_trading_day() -> None:
    trigger_day = date(2025, 1, 7)
    future_week = replace(
        _bar_at(datetime(2025, 1, 10, 15, 0, tzinfo=UTC)),
        trading_day=date(2025, 1, 10),
    )
    owner = ResolvedContractSegment("J2505", trigger_day, future_week.trading_day)
    service = _canonical_window_service(
        (future_week,),
        frequency="1w",
        segments=(owner,),
    )

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CUTOFF_BAR_MISSING"):
        service.latest_canonical_window(
            SeriesPageQuery("actual_dominant", "j", "1w"),
            trading_day=trigger_day,
        )


@pytest.mark.parametrize(
    "segments",
    (
        (),
        (
            ResolvedContractSegment("J2505", date(2025, 1, 2), date(2025, 1, 2)),
            ResolvedContractSegment("J2509", date(2025, 1, 2), date(2025, 1, 2)),
        ),
    ),
)
@pytest.mark.parametrize("frequency", ("1d", "1w"))
def test_latest_canonical_window_requires_one_owner(
    segments: tuple[ResolvedContractSegment, ...],
    frequency: str,
) -> None:
    latest = _bar_at(datetime(2025, 1, 2, 15, 0, tzinfo=UTC))
    service = _canonical_window_service((latest,), frequency=frequency, segments=segments)

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CONTRACT_UNAVAILABLE"):
        service.latest_canonical_window(
            SeriesPageQuery("actual_dominant", "j", frequency),
            trading_day=date(2025, 1, 2),
        )


@pytest.mark.parametrize(
    "identity",
    (
        SeriesPageQuery("actual_dominant", "j", "15m"),
        SeriesPageQuery("continuous", "j", "1d"),
        SeriesPageQuery("contract", "j", "1d", contract="J2505"),
    ),
)
def test_latest_canonical_window_rejects_unsupported_identity(
    identity: SeriesPageQuery,
) -> None:
    latest = _bar_at(datetime(2025, 1, 2, 15, 0, tzinfo=UTC))
    owner = ResolvedContractSegment("J2505", date(2025, 1, 2), date(2025, 1, 2))
    service = _canonical_window_service(
        (latest,),
        frequency=identity.frequency.value,
        segments=(owner,),
    )

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_IDENTITY_UNSUPPORTED"):
        service.latest_canonical_window(identity, trading_day=date(2025, 1, 2))
