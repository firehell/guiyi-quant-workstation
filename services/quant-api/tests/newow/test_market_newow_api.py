from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import market_newow
from app.db.session import get_db
from app.main import app
from app.market_data.newow.trend_detail_service import NewowTrendDetailError


def _result() -> SimpleNamespace:
    stamp = datetime(2026, 1, 5, 7, tzinfo=UTC)
    bar = SimpleNamespace(
        bar_end=stamp,
        trading_day=date(2026, 1, 5),
        open=Decimal("10.10"),
        high=Decimal("11.20"),
        low=Decimal("9.90"),
        close=Decimal("10.50"),
        volume=100,
        open_interest=200,
        physical_contract="RB2605",
        segment_id="RB2605:2026-01-05:2026-01-05",
        source_identity="calculation",
        observation_eligible=True,
    )
    markers = (
        SimpleNamespace(
            marker_type=SimpleNamespace(value="BUILD"),
            marker_id="build",
            bar_end=stamp,
            price=Decimal("10.50"),
            label="BUILD",
            color_token="yellow",
            priority=1,
            related_marker_ids=(),
            trigger_facts={},
            formula_version="trend",
        ),
        SimpleNamespace(
            marker_type=SimpleNamespace(value="NEWOW_ESCAPE_D1"),
            marker_id="d1",
            bar_end=stamp,
            price=Decimal("10.50"),
            label="D1",
            color_token="red",
            priority=2,
            related_marker_ids=(),
            trigger_facts={},
            formula_version="escape",
        ),
        SimpleNamespace(
            marker_type=SimpleNamespace(value="NEWOW_ESCAPE_D2"),
            marker_id="d2",
            bar_end=stamp,
            price=Decimal("10.50"),
            label="D2",
            color_token="red",
            priority=2,
            related_marker_ids=(),
            trigger_facts={},
            formula_version="escape",
        ),
        SimpleNamespace(
            marker_type=SimpleNamespace(value="NEWOW_ESCAPE_D3"),
            marker_id="d3",
            bar_end=stamp,
            price=Decimal("10.50"),
            label="D3",
            color_token="red",
            priority=2,
            related_marker_ids=(),
            trigger_facts={},
            formula_version="escape",
        ),
    )
    frame = SimpleNamespace(
        bar=bar,
        trend_band=SimpleNamespace(
            b_value=1.2,
            c_value=1.1,
            state=SimpleNamespace(value="YELLOW"),
            state_before=None,
            transition=None,
        ),
        markers=markers,
        cup_handle=None,
    )
    cup = SimpleNamespace(
        candidate_id="cup-1",
        direction=SimpleNamespace(value="BULLISH"),
        state=SimpleNamespace(value="READY"),
        left_rim=SimpleNamespace(
            pivot_at=stamp, confirmed_at=stamp, price=Decimal("11.20")
        ),
        bottom=SimpleNamespace(
            pivot_at=stamp, confirmed_at=stamp, price=Decimal("9.90")
        ),
        right_rim=SimpleNamespace(
            pivot_at=stamp, confirmed_at=stamp, price=Decimal("11.00")
        ),
        handle_start_at=stamp,
        handle_extreme=None,
        pivot_price=Decimal("11.30"),
        pivot_frozen_at=stamp,
        confirmed_at=stamp,
        first_seen_at=stamp,
        state_changed_at=stamp,
        score=88.0,
        score_breakdown={"shape": 42.0},
        hard_failures=(),
        diagnostics=("formed",),
        volume_facts={"ratio": 1.25},
        formula_version="cup",
    )
    return SimpleNamespace(
        calculation_identity="calculation",
        request_identity="request",
        instrument=SimpleNamespace(
            product="rb",
            display_name=None,
            latest_physical_contract=None,
            frequency="1d",
            series_kind="actual_dominant",
            profile_id="newow_trend_d1_v1",
            formula_versions=("trend", "escape", "cup"),
        ),
        bars=(bar,),
        frames=(frame,),
        markers=markers,
        cup_handles=(cup,),
        rollover_seams=(
            SimpleNamespace(
                trading_day=date(2026, 1, 5),
                previous_contract="RB2605",
                next_contract="RB2610",
                previous_bar_end=stamp,
                next_bar_end=stamp,
                previous_segment_id="a",
                next_segment_id="b",
            ),
        ),
        warnings=("NEWOW_TREND_WARMUP_INSUFFICIENT",),
    )


def _client(monkeypatch, result: object = None) -> TestClient:
    value = _result() if result is None else result
    monkeypatch.setattr(
        market_newow,
        "NewowTrendDetailService",
        lambda _market: SimpleNamespace(query=lambda _query: value),
    )
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


def test_get_newow_trend_detail_maps_safe_typed_facts(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        response = client.get(
            "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {
        "strategy_code": "newow_trend_v1",
        "profile_id": "newow_trend_d1_v1",
        "frequency": "1d",
        "series_kind": "actual_dominant",
        "calculation_identity": "calculation",
        "request_identity": "request",
    }
    assert body["bars"][0]["close"] == "10.50"
    assert body["bars"][0]["bar_end"].endswith("Z")
    assert [marker["marker_type"] for marker in body["escape_markers"]] == [
        "NEWOW_ESCAPE_D1",
        "NEWOW_ESCAPE_D2",
        "NEWOW_ESCAPE_D3",
    ]
    assert body["cup_handles"][0]["confirmed_at"].endswith("Z")
    assert body["cup_handles"][0]["score_breakdown"] == {"shape": 42.0}
    assert body["cup_handles"][0]["hard_failures"] == []
    assert body["cup_handles"][0]["diagnostics"] == ["formed"]
    assert body["cup_handles"][0]["volume_facts"] == {"ratio": 1.25}
    assert body["bar_policy"] == "completed_only"


def test_newow_route_rejects_nonfixed_params_and_is_get_only(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        assert (
            client.get(
                "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05&frequency=5m"
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05&series_kind=continuous"
            ).status_code
            == 422
        )
        assert client.post("/api/v1/market/newow/trend-detail").status_code == 405
        assert client.get("/api/v1/market/bars/page").status_code == 422
    app.dependency_overrides.clear()


def test_newow_public_error_never_leaks_core_reason(monkeypatch) -> None:
    monkeypatch.setattr(
        market_newow,
        "NewowTrendDetailService",
        lambda _market: SimpleNamespace(
            query=lambda _query: (_ for _ in ()).throw(
                NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
            )
        ),
    )
    app.dependency_overrides[get_db] = lambda: object()
    response = TestClient(app).get(
        "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
    )
    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NEWOW_DATA_IDENTITY_INVALID"}}


def test_newow_invalid_product_and_range_are_public_422_codes(monkeypatch) -> None:
    errors = iter(
        (
            NewowTrendDetailError("NEWOW_INVALID_PRODUCT"),
            NewowTrendDetailError("NEWOW_INVALID_RANGE"),
        )
    )
    monkeypatch.setattr(
        market_newow,
        "NewowTrendDetailService",
        lambda _market: SimpleNamespace(
            query=lambda _query: (_ for _ in ()).throw(next(errors))
        ),
    )
    app.dependency_overrides[get_db] = lambda: object()
    client = TestClient(app)
    product = client.get(
        "/api/v1/market/newow/trend-detail?product=bad&from=2026-01-05&through=2026-01-05"
    )
    window = client.get(
        "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-06&through=2026-01-05"
    )
    app.dependency_overrides.clear()

    assert product.json() == {"detail": {"code": "NEWOW_INVALID_PRODUCT"}}
    assert window.json() == {"detail": {"code": "NEWOW_INVALID_RANGE"}}


def test_newow_marker_facts_recursively_serialize_safe_values(monkeypatch) -> None:
    result = _result()
    stamp = datetime(2026, 1, 5, 7, tzinfo=UTC)
    result.markers[0].trigger_facts = {
        "decimal": Decimal("1.2300"),
        "day": date(2026, 1, 5),
        "at": stamp,
        "nested": [True, {"price": Decimal("2.50")}],
    }

    with _client(monkeypatch, result) as client:
        response = client.get(
            "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["trend_markers"][0]["trigger_facts"] == {
        "decimal": "1.2300",
        "day": "2026-01-05",
        "at": "2026-01-05T07:00:00Z",
        "nested": [True, {"price": "2.50"}],
    }


def test_newow_rejects_unsafe_marker_facts_without_repr_or_path_leak(
    monkeypatch,
) -> None:
    result = _result()

    class _Unsafe:
        def __repr__(self) -> str:
            return "Unsafe(/private/secret)"

    result.markers[0].trigger_facts = {"unsafe": _Unsafe()}
    with _client(monkeypatch, result) as client:
        response = client.get(
            "/api/v1/market/newow/trend-detail?product=rb&from=2026-01-05&through=2026-01-05"
        )
    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "NEWOW_DATA_IDENTITY_INVALID"}}
    assert "/private/secret" not in response.text
