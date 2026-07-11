from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "guiyi-quant-api"
    version = payload.get("version")
    assert isinstance(version, str) and version != ""


def test_api_health_endpoint_returns_full_payload() -> None:
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "guiyi-quant-api"
    version = payload.get("version")
    assert isinstance(version, str) and version != ""


def test_healthz_endpoint_returns_local_workstation_payload() -> None:
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "local-workstation",
    }
