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
        schema=2, mode='observe', enabled=True, state_root=new, account_id='a' * 64), raising=False)
    assert api.reader().root == old
    binding.write_text('private validated binding fixture')
    assert api.reader().root == new
    assert api.reader().expected_account_id == 'a' * 64
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


def test_observe_source_binding_reads_actual_trade_mode_without_api_upgrade(tmp_path, monkeypatch):
    """The unchanged v35 reader accepts its source anchor and projects real mode."""
    import hashlib
    import importlib.util
    import json
    from datetime import timedelta
    from pathlib import Path
    import sys

    from guiyi_quant.htdy_account_execution import LocalStore
    from guiyi_quant.simnow_execution.inbox import SignalInbox
    from guiyi_quant.simnow_execution.monitor import MonitorPublisher

    root = Path(__file__).resolve().parents[3]
    helper = root / 'tests/unit/simnow_monitor/test_monitor.py'
    spec = importlib.util.spec_from_file_location('trade_monitor_compat_fixture', helper)
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    project = tmp_path / 'old-code-and-anchor'
    (project / 'scripts/broker').mkdir(parents=True)
    (project / 'scripts/broker/simnow_controlled.py').touch()
    state_root = project / 'output/simnow-controlled'
    state_root.mkdir(parents=True, mode=0o700)
    reader, now, folder = fixture_module.fixture_root(state_root)
    state = LocalStore.inspect(folder / 'account.sqlite')
    SignalInbox(folder / 'signals.sqlite', state.account_id,
                tuple(p.product for p in state.products)).close()
    api_env = tmp_path / 'api-env'
    api_env.mkdir()
    source = api.MONITOR_SOURCE_CONFIG
    source.write_text(json.dumps(dict(schema=2, account_id=state.account_id,
        state_root=str(state_root), project_root=str(project), state_project_root=str(project),
        sdk_python=sys.executable, api_env=str(api_env), mode='observe', enabled=True)))
    source.chmod(0o600)
    old_source = source.read_bytes()
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    assert MonitorPublisher(state_root, state.account_id, 'new-trade-run').publish(
        'STARTING', now + timedelta(seconds=1), mode='trade', opening_enabled=False,
        host_status='WAITING_SESSION')
    result = api.reader().overview(now + timedelta(seconds=2))
    assert result['observer']['mode'] == 'trade'
    assert result['observer']['host_status'] == 'WAITING_SESSION'
    assert result['observer']['opening_enabled'] is False
    assert source.read_bytes() == old_source
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
