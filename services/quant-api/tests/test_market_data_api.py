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


def test_market_bars_alias_requires_explicit_canonical_identity_and_window() -> None:
    response = TestClient(app).get(
        "/api/v1/market/bars",
        params={
            "symbol": "jm",
            "contract": "JM2609",
            "period": "15m",
            "profile_id": "intraday_research_v1",
        },
    )

    assert response.status_code == 422
    missing = {tuple(item["loc"]) for item in response.json()["detail"]}
    assert ("query", "dataset_kind") in missing
    assert ("query", "frequency") in missing
    assert ("query", "start") in missing
    assert ("query", "end") in missing


def test_public_historical_market_routes_have_no_legacy_selector() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/market/bars",
        "/api/v1/market/indicators",
        "/api/v1/market/indicators/macd",
        "/api/v1/market/workbench/coverage",
    ):
        names = {item["name"] for item in paths[path]["get"]["parameters"]}
        assert "profile_id" not in names
        assert "expected_market_data_file_id" not in names
        assert "expected_lineage_token" not in names
