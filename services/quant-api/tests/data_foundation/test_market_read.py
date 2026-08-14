from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import CanonicalBar, MarketSeriesPageResult, SeriesPageQuery
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
    def __init__(self, bars: tuple[CanonicalBar, ...]) -> None:
        self.bars = bars

    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        eligible = tuple(
            bar for bar in self.bars if request.before is None or bar.bar_end < request.before
        )[-request.limit :]
        return MarketSeriesPageResult(
            request_identity={"symbol": request.symbol},
            bars=eligible,
            canonical_coverage=None,
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=(),
        )


class WindowLiveStore(FakeLiveStore):
    def __init__(
        self,
        bars: tuple[CanonicalBar, ...],
        *,
        subscription: object = "J2505",
    ) -> None:
        super().__init__(bars)
        self.snapshot = {"j": subscription}

    def bars_after(
        self,
        trading_day: date,
        symbol: str,
        frequency: str,
        after: datetime | None,
    ) -> tuple[CanonicalBar, ...]:
        assert (trading_day, symbol, frequency) == (date(2025, 1, 2), "j", "15m")
        return tuple(bar for bar in self.bars if after is None or bar.bar_end > after)


class ForbiddenPhaseResolver:
    def resolve(self, symbol: str, now: datetime) -> ProductMarketPhase:
        raise AssertionError("bars_until must not depend on current market phase")


def _window_service(
    canonical: tuple[CanonicalBar, ...],
    live: tuple[CanonicalBar, ...],
    *,
    subscription: object = "J2505",
) -> MarketReadService:
    return MarketReadService(
        market_data=WindowMarketDataService(canonical),
        phase_resolver=ForbiddenPhaseResolver(),
        operational_products=("j",),
        live_store=WindowLiveStore(live, subscription=subscription),
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


def test_bars_until_hard_cutoff_dedup_limit_and_event_day_contract() -> None:
    """Catches future Live bars, seam duplicates, or phase-gated contract lookup leaking into Alert."""
    start = datetime(2025, 1, 1, 16, 0, tzinfo=UTC)
    canonical = tuple(_bar_at(start + timedelta(minutes=15 * index)) for index in range(40))
    cutoff = canonical[-2].bar_end
    live = (
        _bar_at(canonical[-3].bar_end, close="101"),
        _bar_at(cutoff, close="102"),
        _bar_at(cutoff + timedelta(minutes=15), close="103"),
    )

    window = _window_service(canonical, live).bars_until(
        SeriesPageQuery("actual_dominant", "j", "15m"),
        trading_day=date(2025, 1, 2),
        end=cutoff,
        limit=32,
    )

    assert window.contract == "J2505"
    assert window.cutoff == cutoff
    assert len(window.bars) == 32
    assert window.bars[-1].bar_end == cutoff
    assert len({bar.bar_end for bar in window.bars}) == 32
    assert all(bar.bar_end <= cutoff for bar in window.bars)


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
    service = _window_service((_bar_at(cutoff - timedelta(minutes=15)),), ())

    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CUTOFF_BAR_MISSING"):
        service.bars_until(
            SeriesPageQuery("actual_dominant", "j", "15m"),
            trading_day=date(2025, 1, 2),
            end=cutoff,
        )
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_IDENTITY_UNSUPPORTED"):
        service.bars_until(
            SeriesPageQuery("continuous", "j", "15m"),
            trading_day=date(2025, 1, 2),
            end=cutoff,
        )
