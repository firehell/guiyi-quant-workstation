from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.operational_universe import ActiveUniverseError
from app.market_data.subing_calibration import SubingCalibrationError
from app.market_data.subing_historical_signal_service import (
    SubingHistoricalSignalDirection,
    SubingHistoricalSignalEvent,
    SubingHistoricalSignalRequest,
    SubingHistoricalSignalResult,
    SubingHistoricalSignalSegmentIdentityError,
    SubingHistoricalSignalSourceUnavailableError,
)


def test_subing_historical_overlay_route_exposes_exact_read_only_query_contract() -> None:
    path = "/api/v1/market/research/subing/history"

    assert path in app.openapi()["paths"]
    operation = app.openapi()["paths"][path]["get"]
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "series_kind",
        "symbol",
        "frequency",
        "since",
        "through",
    ]


class _Service:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    def history(self, request: SubingHistoricalSignalRequest):
        if self.failure is not None:
            raise self.failure
        return SubingHistoricalSignalResult(
            request=request,
            events=(
                SubingHistoricalSignalEvent(
                    event_id=(
                        "subing_entry_signal_v1|jm|JM2609|2026-08-03|"
                        "2026-08-03T02:15:00+00:00|15m|buy"
                    ),
                    bar_end=datetime(2026, 8, 3, 2, 15, tzinfo=UTC),
                    trading_day=date(2026, 8, 3),
                    contract="JM2609",
                    segment_start_trading_day=date(2026, 8, 3),
                    direction=SubingHistoricalSignalDirection.BUY,
                    trigger_timeframe=BarFrequency.M15,
                    lower_tf_confirmation=True,
                ),
            ),
        )


def test_subing_historical_overlay_returns_normalized_request_and_source_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_historical_signal_service",
        lambda _session: _Service(),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "JM",
            "frequency": "15m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "request": {
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "15m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
        "events": [
            {
                "event_id": (
                    "subing_entry_signal_v1|jm|JM2609|2026-08-03|"
                    "2026-08-03T02:15:00+00:00|15m|buy"
                ),
                "bar_end": "2026-08-03T02:15:00Z",
                "trading_day": "2026-08-03",
                "contract": "JM2609",
                "segment_start_trading_day": "2026-08-03",
                "direction": "buy",
                "trigger_timeframe": "15m",
                "lower_tf_confirmation": True,
            }
        ],
    }


@pytest.mark.parametrize(
    "params",
    (
        {"series_kind": "continuous", "frequency": "5m"},
        {"series_kind": "contract", "frequency": "15m"},
        {"series_kind": "actual_dominant", "frequency": "1m"},
    ),
)
def test_subing_historical_overlay_rejects_unsupported_identity(
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, str],
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_historical_signal_service",
        lambda _session: pytest.fail("invalid request must not execute service"),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing/history",
        params={
            **params,
            "symbol": "jm",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "INVALID_SUBING_HISTORICAL_REQUEST"}
    }


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (
            SubingHistoricalSignalSegmentIdentityError(),
            "SUBING_HISTORICAL_SEGMENT_IDENTITY_INVALID",
        ),
        (
            SubingHistoricalSignalSourceUnavailableError(),
            "SUBING_HISTORICAL_SOURCE_UNAVAILABLE",
        ),
    ),
)
def test_subing_historical_overlay_maps_source_identity_failures_to_409(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_historical_signal_service",
        lambda _session: _Service(failure),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": expected_code}}


def test_subing_historical_overlay_maps_invalid_calibration_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_historical_signal_service",
        lambda _session: (_ for _ in ()).throw(SubingCalibrationError()),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing/history",
        params={
            "series_kind": SeriesKind.ACTUAL_DOMINANT.value,
            "symbol": "jm",
            "frequency": BarFrequency.M5.value,
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "SUBING_CALIBRATION_INVALID"}}


def test_subing_historical_overlay_maps_invalid_active_universe_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_session: object):
        raise ActiveUniverseError()

    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_historical_signal_service",
        fail,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "ACTIVE_UNIVERSE_INVALID"}}
