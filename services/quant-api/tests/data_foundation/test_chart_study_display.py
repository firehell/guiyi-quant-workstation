"""Chart-only anchored study and native isolated Market Tick parity."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from types import SimpleNamespace

from fastapi.testclient import TestClient
import numpy as np
import pytest
from sqlalchemy.orm import Session
import talib

from app.market_data import chart_study_live
from app.market_data.aggregation import SessionWindow
from app.market_data.chart_study_live import _intraday_preview_proved
from app.market_data.market_display_preview import MarketActivity
from app.market_data.chart_indicators import load_chart_study_rows, project_chart_study_display
from app.market_data.domain import CanonicalBar, DatasetKey, MarketSeriesPageResult, SeriesPageQuery
from app.market_data.market_data_service import MarketDataError
from app.market_data.observation_stream import ObservationStream
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.market_data.catalog import MarketCatalog
from app.market_data.tick_runtime import build_isolated_tick_display, open_isolated_tick_market
from tests.data_foundation.test_tick_htdy_integration import (
    CONTRACT, DAY, MINUTE, OPEN, PRODUCT, _seed_history, disposable_market as native_market_fixture,
)

STUDIES = ("ema10", "ema21", "ema60", "boll", "macd")
HISTORY_API = "/api/v1/market/indicators/chart-window"
TAIL_API = "/api/v1/market/indicators/chart-tail"


@pytest.fixture
def disposable_market():
    yield from native_market_fixture.__wrapped__()


def _bar(end, value, *, trading_day=None):
    price = Decimal(value)
    return CanonicalBar(end, trading_day or end.date(), price, price, price, price, Decimal(1), None, None)


def _points(result):
    return {bar.bar_end: tuple(feature.points[index] for feature in segment.features)
            for segment in result.segments for index, bar in enumerate(segment.bars)}


def test_trading_month_anchor_is_independent_of_window_and_stops_at_quality_boundary():
    start = datetime(2026, 8, 31, 2, tzinfo=UTC)
    night = datetime(2026, 8, 31, 13, 1, tzinfo=UTC)
    prior = tuple(_bar(start + i * MINUTE, 100 + i % 13) for i in range(270))
    after = tuple(_bar(night + i * MINUTE, 90 + i % 17, trading_day=date(2026, 9, 1)) for i in range(75))
    invalid = replace(after[39], open=Decimal(0), high=Decimal(0), low=Decimal(0), close=Decimal(0),
                      volume=Decimal(0), turnover=Decimal(0))
    bars = prior + after[:39] + (invalid,) + after[40:]

    def page(end, limit, inclusive):
        selected = tuple(bar for bar in bars if bar.bar_end < end or inclusive and bar.bar_end == end)
        subset = selected[-limit:]
        return MarketSeriesPageResult({}, subset, (subset[0].bar_end, subset[-1].bar_end),
                                      len(selected) > limit, subset[0].bar_end, ())

    def projection(offset, prefix=True):
        first, last = bars[offset].bar_end, bars[-1].bar_end
        query = SeriesPageQuery("contract", PRODUCT, "1m", last, len(bars)-offset, CONTRACT)
        rows = load_chart_study_rows(
            query, page(last, query.limit, True), first=first, last=last,
            read_previous=(lambda cursor, required, head: page(cursor, 113 if head else min(113, required), False)) if prefix else None,
        )
        return project_chart_study_display(query, None, first=first, last=last, studies=STUDIES, rows=rows)

    full, clipped, reset = (projection(offset) for offset in (0, 290, 315))
    all_points = _points(full)
    for subset in (clipped, reset):
        assert _points(subset) == {at: all_points[at] for at in _points(subset)}
    assert full.segments[1].calculation_anchor == prior[-256].bar_end
    assert full.segments[1].bars[0].trading_day == date(2026, 9, 1)
    assert full.segments[2].features[0].points[0].status == "UNKNOWN"
    assert full.segments[3].features[0].points[0].status == "WARMING"
    sample = np.asarray([float(bar.close) for bar in prior[-256:] + after[:39]])
    assert full.segments[1].features[0].points[-1].values == {"value": talib.EMA(sample, timeperiod=10)[-1]}
    with pytest.raises(MarketDataError, match="MARKET_CHART_STUDY_ANCHOR_UNAVAILABLE"):
        projection(290, prefix=False)


def test_activity_requires_exact_session_bucket_and_ignores_break_phase():
    day = date(2026, 9, 1)
    night = datetime(2026, 8, 31, 13, tzinfo=UTC)
    afternoon = datetime(2026, 9, 1, 5, 30, tzinfo=UTC)
    windows = (
        SessionWindow(night, night + timedelta(hours=2)),
        SessionWindow(afternoon, afternoon + timedelta(hours=1, minutes=25)),
    )
    market = SimpleNamespace(session_windows=lambda **_: windows)
    def status(phase, available=True):
        return SimpleNamespace(state=SimpleNamespace(phase=phase, live_available=available))

    scope = SeriesPageQuery("contract", PRODUCT, "30m", contract=CONTRACT)
    night_tick = MarketActivity(
        CONTRACT, "night", _bar(night + timedelta(minutes=30), 100, trading_day=day),
        night + timedelta(seconds=1), night + timedelta(seconds=2),
    )
    lunchtime = MarketActivity(
        CONTRACT, "day", _bar(afternoon + timedelta(minutes=30), 100, trading_day=day),
        afternoon - timedelta(minutes=5), afternoon - timedelta(minutes=4),
    )
    assert _intraday_preview_proved(market, scope, status("TRADING"), night_tick)
    assert not _intraday_preview_proved(market, scope, status("TRADING", False), night_tick)
    assert not _intraday_preview_proved(market, scope, status("BREAK"), lunchtime)
    assert not _intraday_preview_proved(market, scope, status("TRADING"), lunchtime)


@pytest.mark.isolated_postgresql
def test_tick_tail_preview_is_repeatable_and_canonical_revision_replaces_it(
    disposable_market, tmp_path, monkeypatch,
):
    engine, redis = disposable_market
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    _seed_history(engine, canonical)
    redis_url = f"redis://127.0.0.1:{redis.connection_pool.connection_kwargs['port']}/12"
    monkeypatch.setenv("GUIYI_NEWOW_REFERENCE_MODE", "market_foundation_isolated")
    monkeypatch.setenv("GUIYI_MARKET_FOUNDATION_SANDBOX", str(tmp_path))
    monkeypatch.setenv("GUIYI_CANONICAL_DATA_ROOT", str(canonical))
    now = [OPEN]

    class TickSocket:
        _client = object()

        def subscribe(self, _channels):
            pass

        def listen(self, *, handler):
            self.handler = handler

        def close(self):
            pass

    socket = TickSocket()

    def tick(offset, price, quantity):
        observed = OPEN + timedelta(seconds=offset)
        now[0] = observed + timedelta(milliseconds=25)
        socket.handler({"action": "feed", "channel": f"tick_{CONTRACT}", "order_book_id": CONTRACT,
                        "datetime": observed, "last": price, "volume": quantity, "total_turnover": 100 * quantity})
        assert market.poll(now[0]) == (None, None)

    scope = {"series_kind": "contract", "frequency": "1m", "symbol": PRODUCT, "contract": CONTRACT}
    studies = {**scope, "profile": "free", "studies": ",".join(STUDIES)}
    advances = []
    advance = chart_study_live.advance

    def measured_advance(state, identity, bar):
        started = perf_counter()
        result = advance(state, identity, bar)
        advances.append((bar.bar_end, perf_counter() - started))
        return result

    monkeypatch.setattr(chart_study_live, "advance", measured_advance)
    with Session(engine) as session, open_isolated_tick_market(
        session=session, database_url=engine.url, redis_url=redis_url, canonical_root=canonical,
        products=(PRODUCT,), client_factory=lambda: socket, clock=lambda: now[0],
    ) as market:
        market.bind_day(DAY)
        assert market.poll(now[0]) == (None, None)
        tick(0, 100, 0)
        tick(1, 102, 2)
        tick(60, 103, 3)
        now[0] = OPEN + MINUTE + timedelta(seconds=3)
        assert market.poll(now[0]) == (None, None)
        tick(65, 106, 4)
        app = build_isolated_tick_display(
            market, redis_url=redis_url, canonical_root=canonical,
            after_market_status_path=tmp_path / "absent-status.json",
        )

        @app.middleware("http")
        async def freeze_display_clock(request, call_next):
            request.state.candidate_preview_as_of = now[0]
            return await call_next(request)

        with TestClient(app) as client:
            history = client.get("/api/v1/market/bars/page", params={**scope, "limit": 2000}).json()["bars"]
            page = {**studies, "first": history[-70]["bar_end"], "last": history[-1]["bar_end"], "count": 70}
            answered = client.get(HISTORY_API, params=page)
            assert answered.status_code == 200, answered.json()
            base = answered.json()
            tail = {**studies, "canonical_end": page["last"], "source_revision": base["source_revision"],
                    "completed_through": (OPEN + MINUTE).isoformat(), "include_preview": True}
            answered = client.get(TAIL_API, params=tail)
            assert answered.status_code == 200, answered.json()
            live = answered.json()
            assert live["tail_unavailable_reason"] is None, live
            done, = live["segments"]
            assert done["bars"][0]["source"] == "completed_live"
            first_preview = live["preview"]
            assert first_preview["segment"]["bars"][0]["source"] == "active_preview"
            tick(66, 115, 5)
            second = client.get(TAIL_API, params=tail).json()
            assert second["segments"] == live["segments"]
            assert second["preview"]["generation"] == first_preview["generation"]
            assert second["preview"]["observed_at"] != first_preview["observed_at"]
            assert second["preview"]["segment"]["features"] != first_preview["segment"]["features"]
            assert redis.xlen(ObservationStream(redis, kind="completed").key(DAY)) == 1

            # The repeated active read never commits or steps the same completed Bar again.
            timings = []
            for _ in range(40):
                started = perf_counter()
                again = client.get(TAIL_API, params=tail)
                timings.append(perf_counter() - started)
                assert again.json() == second
            assert sum(bar_end == OPEN + MINUTE for bar_end, _ in advances) == len(STUDIES)
            step_p95 = np.percentile([value for _, value in advances], 95) * 1000
            print(f"isolated chart-tail warm P50={np.median(timings)*1000:.2f}ms "
                  f"P95={np.percentile(timings, 95)*1000:.2f}ms n={len(timings)}, Core step P95={step_p95:.3f}ms")
            trading_clock = now[0]
            now[0] = OPEN + timedelta(hours=6, minutes=1)
            closed = client.get(TAIL_API, params=tail)
            assert closed.status_code == 200
            assert closed.json()["segments"] == [] and closed.json()["preview"] is None
            now[0] = trading_clock

            # The Canonical authority can revise a consumed warm-up Bar at the same endpoint.
            from app.market_data.market_data_service import MarketDataService

            with Session(engine) as writer:
                store = CanonicalMonthlyStore(canonical)
                catalog = MarketCatalog(writer, canonical)
                key = DatasetKey("contract", PRODUCT, CONTRACT, "1m")
                source = MarketDataService(catalog, store)
                prefix = source.query_page(SeriesPageQuery("contract", PRODUCT, "1m", limit=2000, contract=CONTRACT))
                older = source.query_page(SeriesPageQuery(
                    "contract", PRODUCT, "1m", before=prefix.bars[0].bar_end, limit=2000, contract=CONTRACT,
                ))
                revised = (*older.bars, *prefix.bars[:-3], _bar(prefix.bars[-3].bar_end, 150), *prefix.bars[-2:])
                catalog.register_partition(store.publish(PublishRequest(
                    key, DAY.year, DAY.month, revised, tuple(bar.bar_end for bar in revised),
                )))
                writer.commit()
            stale = client.get(TAIL_API, params=tail)
            assert stale.status_code == 409 and stale.json()["detail"]["code"] == "MARKET_CHART_STUDY_WINDOW_MISMATCH"
            changed = client.get(HISTORY_API, params=page).json()
            assert changed["source_revision"] != base["source_revision"]
            newest = client.get(TAIL_API, params={**tail, "source_revision": changed["source_revision"]}).json()
            assert newest["segments"][0]["features"] != done["features"]

            # A page with no earlier partition does not prove the declared rank-1
            # start. Retain Calendar and MainContractMap, but remove the first day.
            with Session(engine) as writer:
                catalog = MarketCatalog(writer, canonical)
                truncated = tuple(bar for bar in revised if bar.trading_day > revised[0].trading_day)
                catalog.register_partition(store.publish(PublishRequest(
                    key, DAY.year, DAY.month, truncated, tuple(bar.bar_end for bar in truncated),
                )))
                writer.commit()
            missing = client.get(HISTORY_API, params={
                **{name: value for name, value in page.items() if name != "contract"},
                "series_kind": "actual_dominant",
            })
            assert missing.status_code == 409
            assert missing.json()["detail"]["code"] == "MARKET_CHART_STUDY_ANCHOR_UNAVAILABLE"
