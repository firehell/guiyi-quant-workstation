"""GET-only monitor cannot connect TqSdk or mutate an account."""

from datetime import datetime, UTC, timedelta
import json
import sys
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import simulation_monitor as api
from guiyi_quant.tq_simulation.runtime import write_private
from guiyi_quant.tq_simulation.monitor import blank


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "directory", lambda: tmp_path)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app), tmp_path


def test_not_connected_never_imports_or_starts_sdk(client):
    c, _ = client
    prior = "tqsdk" in sys.modules
    response = c.get("/api/simulation/monitor/overview")
    assert response.status_code == 200
    assert response.json()["status"] == "not_connected"
    assert response.json()["version"] == "simulation_monitor_v1"
    assert ("tqsdk" in sys.modules) == prior
    assert c.post("/api/simulation/monitor/overview").status_code == 405


def populated(path, age=0, count=1):
    now = datetime.now(UTC) - timedelta(seconds=age)
    overview = blank(now)
    overview.update(
        status="available",
        account={"key": "a" * 64},
        observer={"status": "running", "opening_enabled": True},
    )
    rows = [
        dict(
            id="signal:" + str(i),
            kind="signal",
            at=now.isoformat(),
            product="RB",
            contract="RB2701",
            status="OBSERVED",
            label="fixture",
            signal_id="s",
            order_id=None,
            facts={},
        )
        for i in range(count)
    ]
    write_private(path / "monitor.json", {"overview": overview, "records": rows})


def test_stale_status_revokes_opening_without_fabricating_funds(client):
    c, path = client
    populated(path, age=60)
    d = c.get("/api/simulation/monitor/overview").json()
    assert (
        d["observer"]["status"] == "stale" and d["observer"]["opening_enabled"] is False
    )
    assert d["metrics"]["equity"] is None


def test_readonly_paging_snapshot_binding_and_chain(client):
    c, path = client
    populated(path, count=101)
    page = c.get("/api/simulation/monitor/records").json()
    assert len(page["items"]) == 100 and page["next_cursor"]
    assert (
        len(
            c.get(
                "/api/simulation/monitor/records",
                params={"cursor": page["next_cursor"]},
            ).json()["items"]
        )
        == 1
    )
    assert (
        c.get("/api/simulation/monitor/records/signal:0").json()["selected"]["id"]
        == "signal:0"
    )
    populated(path, count=102)
    assert (
        c.get(
            "/api/simulation/monitor/records", params={"cursor": page["next_cursor"]}
        ).status_code
        == 409
    )
    assert (
        c.get(
            "/api/simulation/monitor/records", params={"start_day": "2020-01-01"}
        ).status_code
        == 422
    )
    assert c.get("/api/simulation/monitor/overview?send=true").status_code == 422
