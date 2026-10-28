"""GET-only local views; no broker/provider/filesystem mutation on reads."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import simnow_monitor as api
import pytest
from types import SimpleNamespace


@pytest.fixture(autouse=True)
def private_monitor_binding(monkeypatch, tmp_path):
    monkeypatch.setattr(api, 'MONITOR_SOURCE_CONFIG', tmp_path / 'binding.private.json')


def client(monkeypatch, tmp_path):
    monkeypatch.setenv("GUIYI_SIMNOW_MONITOR_ROOT", str(tmp_path / "missing"))
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_monitor_source_changes_only_when_private_binding_is_published(monkeypatch, tmp_path):
    client(monkeypatch, tmp_path)
    old = api.reader().root
    binding = tmp_path / 'binding.private.json'
    new = tmp_path / 'new-account-state'
    monkeypatch.setattr(api, 'load_settings', lambda path: SimpleNamespace(
        schema=2, mode='observe', enabled=True, state_root=new), raising=False)
    assert api.reader().root == old
    binding.write_text('private validated binding fixture')
    assert api.reader().root == new
    binding.unlink()
    assert api.reader().root == old


@pytest.mark.parametrize('mode,enabled,schema', [('trade', True, 2), ('observe', False, 2), ('observe', True, 3)])
def test_monitor_binding_cannot_adopt_wrong_mode_or_preparation(monkeypatch, tmp_path, mode, enabled, schema):
    c = client(monkeypatch, tmp_path)
    api.MONITOR_SOURCE_CONFIG.write_text('fixture')
    monkeypatch.setattr(api, 'load_settings', lambda path: SimpleNamespace(
        schema=schema, mode=mode, enabled=enabled, state_root=tmp_path), raising=False)
    response = c.get('/api/simnow/monitor/overview')
    assert response.status_code == 503
    assert response.json() == {'detail': {'code': 'MONITOR_SOURCE_UNAVAILABLE'}}


def test_invalid_private_binding_never_silently_reads_the_old_account(monkeypatch, tmp_path):
    c = client(monkeypatch, tmp_path)
    api.MONITOR_SOURCE_CONFIG.write_text('{')
    response = c.get('/api/simnow/monitor/overview')
    assert response.status_code == 503
    assert str(tmp_path) not in response.text


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
