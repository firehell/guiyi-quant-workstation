from fastapi.testclient import TestClient

from app.main import app


def test_legacy_data_center_klines_route_is_retired() -> None:
    response = TestClient(app).get(
        "/api/klines",
        params={
            "symbol": "jm",
            "contract": "JM2609",
            "period": "15m",
        },
    )

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "LEGACY_KLINE_ROUTE_RETIRED"


def test_market_bars_short_path_is_removed() -> None:
    response = TestClient(app).get(
        "/api/v1/market/bars",
        params={
            "symbol": "jm",
            "contract": "JM2609",
            "period": "15m",
        },
    )

    assert response.status_code == 404


def test_public_historical_market_routes_have_no_legacy_selector() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/market/bars/canonical",
        "/api/v1/market/indicators/canonical",
        "/api/v1/market/indicators/macd/canonical",
        "/api/v1/market/workbench/coverage",
    ):
        names = {item["name"] for item in paths[path]["get"]["parameters"]}
        assert "profile_id" not in names
        assert "expected_market_data_file_id" not in names
        assert "expected_lineage_token" not in names
