from fastapi.testclient import TestClient

from app.main import app


def test_legacy_browser_and_research_modes_are_not_public_data_selectors() -> None:
    response = TestClient(app).get(
        "/api/v1/market/bars",
        params={
            "symbol": "jm",
            "contract": "JM2609",
            "period": "15m",
            "profile_id": "intraday_research_v1",
            "access_mode": "research",
        },
    )

    assert response.status_code == 422
    missing = {tuple(item["loc"]) for item in response.json()["detail"]}
    assert ("query", "dataset_kind") in missing
    assert ("query", "frequency") in missing
    assert ("query", "start") in missing
    assert ("query", "end") in missing


def test_historical_market_openapi_exposes_only_canonical_selection() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/market/bars",
        "/api/v1/market/indicators",
        "/api/v1/market/indicators/macd",
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
