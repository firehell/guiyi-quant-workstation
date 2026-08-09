from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import CanonicalBar, MarketSeriesPageResult, SeriesPageQuery
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.market_read import MarketReadService


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


def _service(*, live: FakeLiveStore | None = None) -> MarketReadService:
    phase = ProductMarketPhase(
        symbol="j",
        phase=MarketPhase.TRADING,
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
