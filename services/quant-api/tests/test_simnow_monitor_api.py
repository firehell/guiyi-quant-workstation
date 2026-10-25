"""GET-only local views; no broker/provider/filesystem mutation on reads."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import simnow_monitor as api


def client(monkeypatch, tmp_path):
    monkeypatch.setenv("GUIYI_SIMNOW_MONITOR_ROOT", str(tmp_path / "missing"))
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_absent_account_api_is_explicit_and_readonly(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    response = c.get("/api/simnow/monitor/overview")
    assert response.status_code == 200
    assert response.json()["status"] == "not_connected"
    assert response.json()["metrics"]["equity"] is None
    assert not (tmp_path / "missing").exists()
    assert c.post("/api/simnow/monitor/overview").status_code == 405
    assert c.get("/api/simnow/monitor/records").json()["coverage"] == "unavailable"


def test_query_bounds_and_identity_cannot_be_paths(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    for suffix in (
        "/overview?account=../other",
        "/records?kind=bad",
        "/records?kind=all&kind=order",
        "/records?start_day=2026-01-01&end_day=2026-10-01",
        "/records/not-a-hash",
    ):
        assert c.get("/api/simnow/monitor" + suffix).status_code == 422


def test_source_errors_are_fixed_codes_not_raw_paths(monkeypatch, tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "monitor.json").write_text("{")
    monkeypatch.setenv("GUIYI_SIMNOW_MONITOR_ROOT", str(root))
    app = FastAPI()
    app.include_router(api.router)
    c = TestClient(app)
    r = c.get("/api/simnow/monitor/records")
    assert r.status_code == 503 and r.json() == {
        "detail": {"code": "MONITOR_SOURCE_UNAVAILABLE"}
    }
    assert str(root) not in r.text
