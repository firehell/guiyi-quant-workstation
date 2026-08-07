from fastapi.testclient import TestClient

from app.main import app


def test_short_market_paths_are_retired() -> None:
    client = TestClient(app)
    for path in (
        "/api/v1/market/bars",
        "/api/v1/market/indicators",
        "/api/v1/market/indicators/macd",
    ):
        response = client.get(path)
        assert response.status_code == 410
        assert response.json()["detail"]["code"] == "MARKET_SHORT_PATH_RETIRED"


def test_historical_market_openapi_keeps_canonical_selection() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/market/bars/canonical",
        "/api/v1/market/indicators/canonical",
        "/api/v1/market/indicators/macd/canonical",
    ):
        names = {item["name"] for item in paths[path]["get"]["parameters"]}
        assert {"dataset_kind", "symbol", "frequency", "start", "end"} <= names
        assert {
            "profile_id",
            "market_data_file_id",
            "expected_market_data_file_id",
            "expected_lineage_token",
            "access_mode",
            "provider",
            "data_role",
        }.isdisjoint(names)
