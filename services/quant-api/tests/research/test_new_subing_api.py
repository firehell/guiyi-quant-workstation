import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.research_new_subing import router
from app.new_subing_research.store import publish_result
from research.test_new_subing_store import packet


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
