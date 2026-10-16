import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.research_new_subing import router
from app.new_subing_research.store import publish_result
from research.test_new_subing_store import packet, v2_packet


def test_profiles_include_v1_and_both_v2_accounts_for_all_products():
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/api/v1/research/new-subing/profiles")
    assert response.status_code == 200
    profiles = response.json()["profiles"]
    assert len(profiles) == 9
    assert {(item["strategy_code"], item["initial_cash"], item["product"]) for item in profiles} == {
        (version, cash, product)
        for version, cash in (("new_subing_v1", "100000"), ("new_subing_v2", "100000"), ("new_subing_v2", "1000000"))
        for product in ("AL", "RB", "TA")
    }
    assert all(item["rules"] for item in profiles)


def test_v2_read_only_detail_and_pages_keep_account_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("GUIYI_NEW_SUBING_RESULTS_ROOT", str(tmp_path))
    first = publish_result(tmp_path, v2_packet())
    second = publish_result(tmp_path, v2_packet("1000000"))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    runs = client.get("/api/v1/research/new-subing/runs").json()["runs"]
    assert {run["initial_cash"] for run in runs} == {"100000", "1000000"}
    for item in (first, second):
        run_id = item["metadata"]["run_id"]
        detail = client.get(f"/api/v1/research/new-subing/runs/{run_id}").json()
        assert detail["metadata"]["account_model_version"] == "new_subing_layers_v2"
        assert detail["metadata"]["initial_cash"] == item["metadata"]["initial_cash"]
        assert client.get(f"/api/v1/research/new-subing/runs/{run_id}/decisions").json()["items"] == item["decisions"]


def test_readonly_api_lists_detail_and_paginates(tmp_path, monkeypatch):
    monkeypatch.setenv("GUIYI_NEW_SUBING_RESULTS_ROOT", str(tmp_path))
    payload = packet()
    payload["decisions"] = payload["decisions"] * 2
    item = publish_result(tmp_path, payload)
    run_id = item["metadata"]["run_id"]
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/v1/research/new-subing/runs").json()["runs"][0]["run_id"] == run_id
    profile = client.get("/api/v1/research/new-subing/profiles").json()["profiles"][0]
    assert profile["rules"]["ma_window"] == 21
    detail = client.get(f"/api/v1/research/new-subing/runs/{run_id}").json()
    assert "decisions" not in detail
    assert detail["summary"]["final_equity"] == "100010"
    first = client.get(f"/api/v1/research/new-subing/runs/{run_id}/decisions?limit=1").json()
    assert detail["sha256"] == first["sha256"]
    assert first["next_cursor"]
    second = client.get(f"/api/v1/research/new-subing/runs/{run_id}/decisions", params={"cursor": first["next_cursor"], "limit": 1}).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    assert client.get(f"/api/v1/research/new-subing/runs/{run_id}/equity").json()["items"] == []
    assert client.get(f"/api/v1/research/new-subing/runs/{run_id}/trades?limit=201").status_code == 422
    assert client.get(f"/api/v1/research/new-subing/runs/{run_id}/trades?cursor=bad").status_code == 422
    assert client.get("/api/v1/research/new-subing/runs/../index.json").status_code in (404, 422)


def test_missing_root_means_no_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("GUIYI_NEW_SUBING_RESULTS_ROOT", str(tmp_path / "missing"))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/v1/research/new-subing/runs").json() == {"runs": []}
    assert client.get(f"/api/v1/research/new-subing/runs/{'a' * 64}").status_code == 404


@pytest.mark.parametrize("gap", ["DATA_INSUFFICIENT", "EXECUTION_FACTS_MISSING"])
def test_real_core_gap_traces_publish_read_and_api(tmp_path, monkeypatch, gap):
    import runpy
    from dataclasses import replace
    from datetime import date, timedelta
    from pathlib import Path
    from guiyi_quant.new_subing import run_research
    from app.new_subing_research.store import read_result
    from scripts.research.new_subing import build_packet

    root = Path(__file__).resolve().parents[4]
    fixture = runpy.run_path(str(root / 'tests/unit/new_subing/test_core.py'))
    histories, execution = fixture['scenario_bars']()
    t0 = fixture['T0']
    through = date(2025, 1, 2)
    if gap == 'DATA_INSUFFICIENT':
        histories['15m'] = [replace(bar, confirmed_at=t0 + timedelta(hours=5)) for bar in histories['15m']]
    else:
        old = histories['5m'][-1]
        later = t0 + timedelta(days=1, minutes=5)
        histories['5m'].append(replace(old, bar_end=later, confirmed_at=later,
            trading_day=later.date(), source_identity='next-day-5m',
            session_open_at=t0 + timedelta(days=1), session_close_at=t0 + timedelta(days=1, hours=4)))
        through = date(2025, 1, 3)
    result = run_research(histories, execution, since=date(2025, 1, 2), through=through)
    assert result['summary']['status'] == gap
    assert len(result['decisions']) > 0
    packet = build_packet(product='rb', scenario='baseline', code_revision='a' * 40,
                          status=gap, result=result)
    frozen = publish_result(tmp_path, packet)
    run_id = frozen['metadata']['run_id']
    assert read_result(tmp_path, run_id)['decisions'] == result['decisions']

    monkeypatch.setenv('GUIYI_NEW_SUBING_RESULTS_ROOT', str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    detail = client.get(f'/api/v1/research/new-subing/runs/{run_id}')
    assert detail.status_code == 200
    assert detail.json()['summary']['account_return_pct'] is None
    assert detail.json()['summary']['final_equity'] is None
    decisions = client.get(f'/api/v1/research/new-subing/runs/{run_id}/decisions')
    assert decisions.status_code == 200
    assert len(decisions.json()['items']) == len(result['decisions'])
    assert decisions.json()['items'][0]['reason'] == result['decisions'][0]['reason']
    equity = client.get(f'/api/v1/research/new-subing/runs/{run_id}/equity')
    assert equity.status_code == 200
    assert equity.json()['items'] == result['equity']


def test_full_equity_endpoint_is_hash_bound_and_independent_of_pages(tmp_path, monkeypatch):
    monkeypatch.setenv('GUIYI_NEW_SUBING_RESULTS_ROOT', str(tmp_path))
    payload = packet()
    payload['equity'] = [{'at': f'2025-01-01T{i // 60:02d}:{i % 60:02d}:00+00:00', 'equity': str(100000 + i), 'physical_contract': 'AL2501'} for i in range(120)]
    frozen = publish_result(tmp_path, payload)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    path = f"/api/v1/research/new-subing/runs/{frozen['metadata']['run_id']}"
    page = client.get(path + '/equity').json()
    curve = client.get(path + '/equity-curve', params={'sha256': page['sha256']})
    assert curve.status_code == 200
    assert len(page['items']) == 50 and len(curve.json()['items']) == 120
    assert curve.json()['items'][-1] == payload['equity'][-1]
    assert client.get(path + '/equity-curve', params={'sha256': '0' * 64}).status_code == 409
    assert client.get(path + '/equity-curve', params={'max_points': 2001}).status_code == 422
