from fastapi.testclient import TestClient

from app.main import app


def test_legacy_indicator_alias_requires_canonical_dataset_contract() -> None:
    response = TestClient(app).get(
        "/api/v1/market/indicators",
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


def test_public_indicator_alias_has_no_profile_selector() -> None:
    operation = TestClient(app).get("/openapi.json").json()["paths"][
        "/api/v1/market/indicators"
    ]["get"]
    names = {item["name"] for item in operation["parameters"]}

    assert "profile_id" not in names
    assert "expected_market_data_file_id" not in names
