from fastapi.testclient import TestClient

from app.main import app


def test_legacy_research_signal_route_is_retired_without_writes() -> None:
    response = TestClient(app).post(
        "/api/signals/research/scan",
        json={
            "watchlist_code": "black",
            "profile_id": "intraday_research_v1",
            "periods": ["5m"],
            "research_only": True,
        },
    )

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "SIGNAL_LEGACY_EXECUTION_RETIRED"
