"""GET-only monitor cannot connect TqSdk or mutate an account."""

from datetime import datetime, UTC, timedelta
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


def equity_history(path):
    from guiyi_quant.tq_simulation.journal import Journal
    from guiyi_quant.tq_simulation.runtime import read_private
    now = datetime.now(UTC)
    folder = path / "accounts" / ("a" * 64)
    folder.mkdir(parents=True, mode=0o700)
    journal = Journal(folder / "dispatch.sqlite", "a" * 64)
    points = []
    for i in range(201):
        at = now - timedelta(days=40) + timedelta(hours=i * 4)
        p = dict(at=at.isoformat(), equity=str(100000 + i), trading_day="20261107")
        journal.event("equity", p, at)
        points.append(dict(**p, net_profit=None))
    journal.close()
    value = read_private(path / "monitor.json")
    value["overview"]["curve"] = points[-169:-1]
    write_private(path / "monitor.json", value)
    return points


def test_full_equity_history_is_account_bound_and_ends_at_published_snapshot(client):
    from hashlib import sha256
    c, path = client
    populated(path)
    points = equity_history(path)
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in path.rglob("*") if p.is_file()}
    response = c.get("/api/simulation/monitor/overview")
    assert response.status_code == 200
    assert response.json()["curve_history_status"] == "complete"
    assert response.json()["curve"] == points[:-1]  # no 168 cap or unpublished tail
    assert {str(p): sha256(p.read_bytes()).hexdigest() for p in path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("failure", ["missing", "identity", "endpoint", "symlink", "parent_symlink", "traversal", "wal"])
def test_unproven_history_is_unavailable_without_losing_account_monitor(client, failure):
    from guiyi_quant.tq_simulation.runtime import read_private
    import sqlite3
    c, path = client
    populated(path)
    equity_history(path)
    db_path = path / "accounts" / ("a" * 64) / "dispatch.sqlite"
    if failure == "missing":
        db_path.unlink()
    elif failure == "identity":
        value = read_private(path / "monitor.json")
        value["overview"]["account"]["key"] = "b" * 64
        write_private(path / "monitor.json", value)
        other = path / "accounts" / ("b" * 64)
        other.mkdir(mode=0o700)
        db_path.rename(other / "dispatch.sqlite")
    elif failure == "endpoint":
        value = read_private(path / "monitor.json")
        value["overview"]["curve"][-1]["equity"] = "1"
        write_private(path / "monitor.json", value)
    elif failure == "symlink":
        db_path.rename(path / "other.sqlite")
        db_path.symlink_to(path / "other.sqlite")
    elif failure == "parent_symlink":
        db_path.parent.rename(path / "other")
        db_path.parent.symlink_to(path / "other", target_is_directory=True)
    elif failure == "traversal":
        value = read_private(path / "monitor.json")
        value["overview"]["account"]["key"] = "../.."
        write_private(path / "monitor.json", value)
    else:
        db = sqlite3.connect(db_path)
        db.execute("PRAGMA journal_mode=WAL")
        db.close()
    response = c.get("/api/simulation/monitor/overview")
    assert response.status_code == 200
    assert response.json()["curve_history_status"] == "unavailable"
    assert response.json()["curve"] == []
    assert response.json()["account"]
