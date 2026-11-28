from datetime import UTC, datetime, timedelta
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.simulation_center import router
from app.simulation_center.config import ObserverConfig
from app.simulation_center.facts import normalize
from app.simulation_center.readback import ReadbackError
from app.simulation_center.store import Writer, read_workstation
from test_facts import sample


def test_api_is_read_only_and_distinguishes_unconfigured(monkeypatch):
    monkeypatch.delenv("GUIYI_SIMULATION_READER_DSN", raising=False)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/v1/simulations")
        assert (response.status_code, response.json()["status"]) == (200, "NOT_CONFIGURED")
        assert response.json()["readback"] is None
        assert client.post("/api/v1/simulations", json={}).status_code == 405
        assert client.get("/api/v1/simulations?account=../unsafe").status_code == 422
        assert client.get("/api/v1/simulations?before=2026-11-30:SHFE:1").status_code == 422


def config(alias, user):
    return ObserverConfig.from_dict({
        "alias": alias, "user": user, "password": "fixture-pass", "auth_code": "fixture-auth",
        "app_id": "fixture-app", "front": "tcp://180.168.146.187:10201", "environment": "simnow",
        "deployment": {"strategy_id": "htdy_60m", "formula_version": "test-formula",
                       "profile_id": "test-profile", "risk_policy_version": "test-risk",
                       "instruments": ["SHFE:RB2701"]},
    })


def test_config_rejects_unknown_endpoint_and_hides_credentials():
    value = config("case-a", "INV")
    assert value.deployment.instruments == ("SHFE:RB2701",)
    assert "fixture-pass" not in repr(value)
    with pytest.raises(ValueError, match="SIMNOW_CONFIGURATION_INVALID"):
        ObserverConfig.from_dict({
            "alias": "case-a", "user": "INV", "password": "fixture-pass", "auth_code": "fixture-auth",
            "app_id": "fixture-app", "front": "tcp://127.0.0.1:10201", "environment": "simnow",
        })


@pytest.mark.isolated_postgresql
def test_postgresql_retains_prior_round_and_isolates_accounts(monkeypatch):
    dsn = os.getenv("GUIYI_SIMULATION_ISOLATED_TEST_DSN")
    if not dsn:
        pytest.skip("isolated Simulation Center PostgreSQL required")
    first = config("case-a", "INV")
    second = config("case-b", "INV2")
    observed = datetime.now(UTC)
    original = {
        **normalize(sample(), first.user, "20261130"),
        "generation": 1, "watermark": 1,
        "observed_at": observed.isoformat(), "started_at": (observed - timedelta(seconds=4)).isoformat(),
    }

    with Writer.claim(dsn, first) as writer, Writer.claim(dsn, second) as other:
        with pytest.raises(ReadbackError, match="ACCOUNT_ALREADY_OWNED"):
            with Writer.claim(dsn, first):
                pytest.fail("duplicate writer")
        writer.publish(original)
        assert read_workstation(dsn, "case-b", None)["readback"] is None
        assert read_workstation(dsn, "case-a", None)["fills"] == original["fills"]
        assert read_workstation(dsn, "case-a", original["fills"][0]["id"])["fills"] == []
        assert read_workstation(dsn, "case-b", None)["equity"] == []
        duplicate = {**original, "observed_at": (observed + timedelta(seconds=1)).isoformat()}
        writer.publish(duplicate)
        assert len(read_workstation(dsn, "case-a", None)["fills"]) == 1
        omitted = {
            **duplicate, "orders": [], "fills": [], "observed_at": (observed + timedelta(seconds=2)).isoformat(),
        }
        with pytest.raises(ReadbackError, match="RETAINED_ORDER_REGRESSION"):
            writer.publish(omitted)
        conflicting = {**duplicate, "fills": [{**original["fills"][0], "price": "55.10"}],
                       "observed_at": (observed + timedelta(seconds=2)).isoformat()}
        with pytest.raises(ReadbackError, match="RETAINED_FILL_CONFLICT"):
            writer.publish(conflicting)
        writer.status("READBACK_FAILED")
        other.status("STOPPED")
        current = read_workstation(dsn, "case-a", None)
        assert current["readback"]["observed_at"] == duplicate["observed_at"]
        assert current["accounts"][0]["status"] == "READBACK_FAILED"
        assert len(current["equity"]) == 2

    with pytest.raises(ReadbackError, match="ACCOUNT_BINDING_CONFLICT"):
        with Writer.claim(dsn, config("case-b", "INV")):
            pytest.fail("cross-account alias")
    with Writer.claim(dsn, first) as restarted:
        restarted.status("RECONCILING")
        assert read_workstation(dsn, "case-a", None)["fills"] == original["fills"]
    monkeypatch.setenv("GUIYI_SIMULATION_READER_DSN", dsn)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        result = client.get("/api/v1/simulations?account=case-a").json()
        assert result["source"] == "SIMNOW_CTP"
        assert result["readback"]["account"]["equity"] == "100.01"
        assert "INV" not in str(result) and "fixture-pass" not in str(result)
        assert client.get("/api/v1/simulations?account=missing").status_code == 404
