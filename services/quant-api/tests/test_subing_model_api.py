"""Standalone JM is retired; no HTTP request may read its private state."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import subing_model as api

@pytest.mark.parametrize("suffix", ["status", "accounts", "history", "", "anything/nested"])
def test_retired_routes_never_read_database_or_registration(suffix, monkeypatch):
    from app import private_settings
    monkeypatch.setattr(private_settings, "read_private_settings_content",
        lambda *a, **k: pytest.fail("retired endpoint read private model state"))
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).get('/api/v1/subing-model/' + suffix)
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "SUBING_INDEPENDENT_MODEL_RETIRED"
