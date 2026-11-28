from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
from threading import Event
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import statistics_research
from app.db.session import get_db
from app.research_center.store import Store

BASE = "/api/v1/statistics-research"
RUN = "a39fae9c070d46188f0abdf55358c75f"


@pytest.fixture
def client(isolated_postgres_engine, tmp_path, monkeypatch):
    schema = "stats_test_" + uuid4().hex
    engine = isolated_postgres_engine
    migration_path = Path(__file__).resolve().parents[2] / "alembic/versions/20261128_0058_research_tasks.py"
    spec = importlib.util.spec_from_file_location("research_test_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET LOCAL search_path TO {schema}"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
    def sessions():
        with Session(engine) as session:
            session.execute(text(f"SET search_path TO {schema}"))
            session.commit()
            yield session
    monkeypatch.setenv("GUIYI_RESEARCH_ARTIFACT_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(statistics_research.router)
    app.dependency_overrides[get_db] = sessions
    try:
        with TestClient(app) as browser:
            yield browser
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))


def test_published_fu_settlement_and_reload(client, monkeypatch, tmp_path):
    path = os.getenv("GUIYI_RESEARCH_TEST_BACKTEST_STORE")
    if not path or not os.getenv("GUIYI_RESEARCH_WORKER_PYTHON"):
        pytest.skip("real publication store and independently locked worker required")
    monkeypatch.setenv("GUIYI_BACKTEST_STORE", path)
    assert client.get(BASE + "/backtests", params={"product": "fu", "limit": 1}).json()["total"] >= 4
    body = {"id": str(uuid4()), "source": {"kind": "backtest", "run_id": RUN}}
    url = BASE + "/tasks/" + body["id"]
    response = client.post(BASE + "/tasks", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "SUCCEEDED", result
    assert result["result"]["trades"]["closed"] == 78
    assert result["result"]["performance"]["cumulative"] == pytest.approx(.005203375)
    assert result["result"]["performance"]["annualized"] == pytest.approx(.097920478)
    assert result["result"]["source"]["qualification"] == "TRIAL"

    def forbidden(*args):
        raise AssertionError("a read or idempotent repeat scheduled a worker")

    monkeypatch.setattr(statistics_research, "compute", forbidden)
    assert client.post(BASE + "/tasks", json=body).json() == result
    assert client.get(url).json() == result
    evidence = client.get(url + "/samples", params={"month": "2026-01", "offset": 13, "limit": 1}).json()
    assert evidence["total"] == 14
    assert evidence["items"][0]["native_equity"] == "100520.33749999994"
    artifact = tmp_path / (body["id"] + ".parquet")
    with artifact.open("ab") as stream:
        stream.write(b"altered")
    assert client.get(url).json()["detail"]["code"] == "RESEARCH_ARTIFACT_UNAVAILABLE"


def test_cancel_wins_over_late_result_and_duplicate_is_idempotent(client, monkeypatch):
    started, release = Event(), Event()

    def payload(*args):
        return {"source": {"kind": "backtest"}, "samples": []}

    def delayed(*args):
        started.set()
        assert release.wait(5)
        return {"performance": None}

    monkeypatch.setattr(statistics_research, "prepare", payload)
    monkeypatch.setattr(statistics_research, "compute", delayed)
    body = {"id": str(uuid4()), "source": {"kind": "backtest", "run_id": RUN}}
    url = BASE + "/tasks/" + body["id"]
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(client.post, BASE + "/tasks", json=body)
        try:
            assert started.wait(5)
            assert client.post(BASE + "/tasks", json=body).json()["status"] == "RUNNING"
            conflict = client.post(BASE + "/tasks", json={**body, "source": {"kind": "backtest", "run_id": "other"}})
            assert conflict.status_code == 409
            assert client.post(url + "/cancel").json()["status"] == "CANCELING"
            busy = client.post(BASE + "/tasks", json={**body, "id": str(uuid4())})
            assert busy.json()["detail"]["code"] == "RESEARCH_WORKER_BUSY"
        finally:
            release.set()
        assert future.result(6).json()["status"] == "CANCELED"
    assert client.get(url + "/samples").status_code == 409


def test_expired_claim_is_read_only_and_can_be_replaced(client):
    generator = client.app.dependency_overrides[get_db]()
    with_session = next(generator)
    task_id, next_id = uuid4(), uuid4()
    source = {"source": {"kind": "case", "case_id": str(uuid4())}, "rerun_of": None}
    try:
        store = Store(with_session)
        assert store.claim(task_id, source, "digest", None) is None
        with_session.execute(text("UPDATE statistics_research_tasks SET deadline=now() WHERE id=:id"), {"id": task_id})
        with_session.commit()
        assert client.get(BASE + "/tasks/" + str(task_id)).json()["reason"] == "WORKER_LEASE_EXPIRED"
        assert with_session.execute(text("SELECT status FROM statistics_research_tasks WHERE id=:id"),
                                    {"id": task_id}).scalar_one() == "RUNNING"
        assert store.claim(next_id, {**source, "rerun_of": str(task_id)}, "digest", task_id) is None
    finally:
        generator.close()


def test_index_digest_survives_postgresql_numeric_canonicalization(client, monkeypatch):
    monkeypatch.setattr(statistics_research, "prepare", lambda *_: {"source": {"kind": "backtest"}, "samples": []})
    monkeypatch.setattr(statistics_research, "compute", lambda *_: {"score": -0.0, "annualized": 1e20})
    body = {"id": str(uuid4()), "source": {"kind": "backtest", "run_id": RUN}}
    published = client.post(BASE + "/tasks", json=body)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "SUCCEEDED"
    readback = client.get(BASE + "/tasks/" + body["id"])
    assert readback.json()["result"]["annualized"] == 10**20


def test_frozen_input_is_used_when_original_publication_unavailable(client, monkeypatch):
    payload = {"source": {"kind": "case"}, "samples": [{"remaining": "0"}], "trade_path": {"closed": True}}
    monkeypatch.setattr(statistics_research, "prepare", lambda *_: payload)
    request = {"id": str(uuid4()), "source": {"kind": "case", "case_id": str(uuid4())}}
    initial = client.post(BASE + "/tasks", json=request).json()

    def unavailable(*_):
        raise FileNotFoundError

    monkeypatch.setattr(statistics_research, "prepare", unavailable)
    replay = client.post(BASE + "/tasks", json={**request, "id": str(uuid4()), "rerun_of": request["id"]}).json()
    assert replay["status"] == "SUCCEEDED"
    assert replay["input_digest"] == initial["input_digest"]
    assert replay["rerun_of"] == request["id"]
    assert client.get(BASE + "/tasks/" + replay["id"] + "/samples").json()["items"] == payload["samples"]
