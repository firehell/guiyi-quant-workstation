from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace

import pytest

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.subing_research import (
    SubingDirection,
    SubingSignalEvaluation,
    SubingSignalStatus,
)
from app.market_data import subing_historical_signal_service as service_module
from app.market_data.subing_historical_signal_service import (
    SubingHistoricalSignalRequest,
    SubingHistoricalSignalSegmentIdentityError,
    SubingHistoricalSignalService,
    SubingHistoricalSignalSourceUnavailableError,
)


_DAY = date(2026, 8, 3)
_NEXT_DAY = date(2026, 8, 4)
_SEGMENT = ResolvedContractSegment("JM2609", _DAY, _NEXT_DAY)


def _bar(minutes: int, *, trading_day: date = _DAY) -> CanonicalBar:
    close = Decimal("100") + Decimal(minutes)
    return CanonicalBar(
        bar_end=datetime(2026, 8, trading_day.day, 1, tzinfo=UTC)
        + timedelta(minutes=minutes),
        trading_day=trading_day,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=Decimal("10"),
        turnover=None,
        open_interest=None,
    )


def _market_result(
    bars: tuple[CanonicalBar, ...],
) -> MarketSeriesResult:
    return MarketSeriesResult(
        request_identity=MappingProxyType({}),
        bars=bars,
        coverage=(bars[0].bar_end, bars[-1].bar_end),
        resolved_contract_segments=(_SEGMENT,),
    )


def _loaded(
    bars_5m: tuple[CanonicalBar, ...],
    bars_15m: tuple[CanonicalBar, ...],
) -> ActualDominantResearchSeries:
    return ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M5: _market_result(bars_5m),
                BarFrequency.M15: _market_result(bars_15m),
            }
        ),
        segments=(_SEGMENT,),
    )


class _Loader:
    def __init__(self, loaded: ActualDominantResearchSeries | Exception) -> None:
        self.loaded = loaded
        self.calls: list[dict[str, object]] = []

    def load(self, **kwargs: object) -> ActualDominantResearchSeries:
        self.calls.append(kwargs)
        if isinstance(self.loaded, Exception):
            raise self.loaded
        return self.loaded


def _request(
    frequency: BarFrequency = BarFrequency.M5,
    *,
    through: date = _DAY,
) -> SubingHistoricalSignalRequest:
    return SubingHistoricalSignalRequest(
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        symbol="jm",
        frequency=frequency,
        since=_DAY,
        through=through,
    )


def _fake_factor_series(
    bars: tuple[CanonicalBar, ...],
    *,
    timeframe: BarFrequency,
    **_kwargs: object,
) -> tuple[SimpleNamespace, ...]:
    return tuple(
        SimpleNamespace(
            snapshot=SimpleNamespace(
                timeframe=timeframe,
                bar_end=bar.bar_end,
                trading_day=bar.trading_day,
                contract="JM2609",
                segment_start_trading_day=_DAY,
            )
        )
        for bar in bars
    )


def _matched(
    primary: SimpleNamespace,
    _companion: SimpleNamespace | None = None,
    **_kwargs: object,
) -> SubingSignalEvaluation:
    return SubingSignalEvaluation(
        status=SubingSignalStatus.MATCHED,
        direction=SubingDirection.LONG,
        trigger_timeframe=primary.snapshot.timeframe,
        bar_end=primary.snapshot.bar_end,
        lower_tf_confirmation=False,
        resolution=None,
        conditions=(),
    )


def test_non_boundary_5m_uses_latest_strict_prior_confirmed_15m(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars_5m = (_bar(0), _bar(5), _bar(10))
    bars_15m = (_bar(0),)
    loader = _Loader(_loaded(bars_5m, bars_15m))
    calls: list[tuple[datetime, datetime | None]] = []
    monkeypatch.setattr(service_module, "calculate_subing_factor_series", _fake_factor_series)

    def capture(primary: SimpleNamespace, companion: SimpleNamespace | None, **_kwargs: object):
        calls.append(
            (
                primary.snapshot.bar_end,
                companion.snapshot.bar_end if companion is not None else None,
            )
        )
        return _matched(primary)

    monkeypatch.setattr(service_module, "resolve_subing_matched_signal", capture)

    result = SubingHistoricalSignalService(loader, products=("jm",), calibration=object()).history(_request())

    assert loader.calls == [
        {
            "symbol": "jm",
            "frequencies": (BarFrequency.M5, BarFrequency.M15),
            "since": _DAY,
            "through": _DAY,
        }
    ]
    assert calls == [
        (bars_5m[0].bar_end, bars_5m[0].bar_end),
        (bars_5m[1].bar_end, bars_15m[0].bar_end),
        (bars_5m[2].bar_end, bars_15m[0].bar_end),
    ]
    assert tuple(event.bar_end for event in result.events) == tuple(
        bar.bar_end for bar in bars_5m[1:]
    )


def test_same_15m_boundary_is_resolved_once_with_15m_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars_5m = (_bar(5), _bar(15))
    bars_15m = (_bar(15),)
    loader = _Loader(_loaded(bars_5m, bars_15m))
    primary_timeframes: list[BarFrequency] = []
    monkeypatch.setattr(service_module, "calculate_subing_factor_series", _fake_factor_series)

    def capture(primary: SimpleNamespace, _companion: SimpleNamespace | None, **_kwargs: object):
        primary_timeframes.append(primary.snapshot.timeframe)
        return _matched(primary)

    monkeypatch.setattr(service_module, "resolve_subing_matched_signal", capture)

    result = SubingHistoricalSignalService(loader, products=("jm",), calibration=object()).history(
        _request(BarFrequency.M15)
    )

    assert primary_timeframes == [BarFrequency.M5, BarFrequency.M15]
    assert len(result.events) == 1
    assert result.events[0].bar_end == bars_15m[0].bar_end
    assert result.events[0].trigger_timeframe is BarFrequency.M15


def test_future_prefix_cannot_change_events_before_requested_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix_5m = (_bar(0), _bar(5), _bar(10))
    prefix_15m = (_bar(0),)
    future_5m = _bar(0, trading_day=_NEXT_DAY)
    future_15m = _bar(0, trading_day=_NEXT_DAY)
    monkeypatch.setattr(service_module, "calculate_subing_factor_series", _fake_factor_series)
    monkeypatch.setattr(service_module, "resolve_subing_matched_signal", _matched)
    service_prefix = SubingHistoricalSignalService(
        _Loader(_loaded(prefix_5m, prefix_15m)),
        products=("jm",),
        calibration=object(),
    )
    service_future = SubingHistoricalSignalService(
        _Loader(_loaded((*prefix_5m, future_5m), (*prefix_15m, future_15m))),
        products=("jm",),
        calibration=object(),
    )

    expected = service_prefix.history(_request()).events
    actual = service_future.history(_request()).events

    assert actual == expected


@pytest.mark.parametrize(
    "source_error",
    (
        ActualDominantResearchSegmentIdentityError("identity"),
        MarketDataError("source"),
    ),
)
def test_source_and_segment_failures_are_typed_without_internal_details(
    source_error: Exception,
) -> None:
    service = SubingHistoricalSignalService(
        _Loader(source_error),
        products=("jm",),
        calibration=object(),
    )
    expected = (
        SubingHistoricalSignalSegmentIdentityError
        if isinstance(source_error, ActualDominantResearchSegmentIdentityError)
        else SubingHistoricalSignalSourceUnavailableError
    )

    with pytest.raises(expected) as captured:
        service.history(_request())

    assert "identity" not in str(captured.value)
    assert "source" not in str(captured.value)


@pytest.mark.parametrize(
    ("series_kind", "frequency"),
    (
        (SeriesKind.CONTINUOUS, BarFrequency.M5),
        (SeriesKind.CONTRACT, BarFrequency.M15),
        (SeriesKind.ACTUAL_DOMINANT, BarFrequency.M1),
    ),
)
def test_request_rejects_unsupported_series_and_frequency(
    series_kind: SeriesKind,
    frequency: BarFrequency,
) -> None:
    with pytest.raises(ValueError):
        SubingHistoricalSignalRequest(
            series_kind=series_kind,
            symbol="jm",
            frequency=frequency,
            since=_DAY,
            through=_DAY,
        )
