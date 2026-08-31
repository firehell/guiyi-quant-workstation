from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "guiyi-quant-api"
    assert payload["version"] == "1.9.6"
    assert payload.get("readonly") is True


def test_api_health_endpoint_returns_full_payload() -> None:
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "guiyi-quant-api"
    assert payload["version"] == "1.9.6"
    assert payload.get("readonly") is True


def test_health_and_api_health_are_aliases() -> None:
    """`/health` and `/api/health` must stay identical liveness probes."""
    client = TestClient(app)
    left = client.get("/health")
    right = client.get("/api/health")
    assert left.status_code == 200
    assert right.status_code == 200
    assert left.json() == right.json()


def test_health_endpoints_reject_write_methods() -> None:
    client = TestClient(app)
    for path in ("/health", "/api/health", "/healthz"):
        response = client.post(path, json={"status": "ok"})
        assert response.status_code == 405


def test_health_payload_has_no_credential_looking_keys() -> None:
    client = TestClient(app)
    payload = client.get("/health").json()
    forbidden = {"password", "token", "secret", "webhook", "database_url", "api_key"}
    lowered = {str(k).lower() for k in payload}
    assert forbidden.isdisjoint(lowered)


def test_healthz_is_liveness_alias() -> None:
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == client.get("/health").json()
