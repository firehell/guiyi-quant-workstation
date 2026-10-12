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
