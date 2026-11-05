import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.subing_model import projection_source as source
from app.api import subing_model, research_subing_decision


def test_explicit_roots_are_shared_by_both_readers_without_changing_worker(tmp_path, monkeypatch):
    from app.subing_model import worker
    original = worker.ACTIVE
    binding = tmp_path/'binding.json'
    model = tmp_path/'model'; model.mkdir()
    results = tmp_path/'results'; results.mkdir()
    binding.write_text(json.dumps(dict(model_root=str(model), results_root=str(results))))
    binding.chmod(0o600)
    monkeypatch.setattr(source, 'BINDING', binding)
    assert source.registered_source('model_root') == model
    assert source.registered_source('results_root') == results
    assert worker.ACTIVE == original
    (results/'index.json').write_text('[]')
    monkeypatch.setenv('GUIYI_SUBING_DECISION_RESULTS_ROOT', '/unused/old-location')
    app = FastAPI(); app.include_router(subing_model.router); app.include_router(research_subing_decision.router)
    client = TestClient(app)
    assert client.get('/api/v1/subing-model/status').json()['status'] == 'NOT_STARTED'
    assert client.get('/api/v1/research/subing-decision/runs').json() == {'runs': []}


@pytest.mark.parametrize('kind', ['bad_json', 'extra_key', 'relative', 'parent', 'symlink', 'public_mode'])
def test_present_invalid_binding_fails_closed_in_both_apis(tmp_path, monkeypatch, kind):
    binding = tmp_path/'binding.json'; model = tmp_path/'model'; model.mkdir()
    value = dict(model_root=str(model), results_root=str(model))
    if kind == 'extra_key': value['worker_start'] = True
    if kind == 'relative': value['model_root'] = 'relative'
    if kind == 'parent': value['model_root'] = str(model/'..'/'model')
    if kind == 'symlink':
        link=tmp_path/'link';link.symlink_to(model,target_is_directory=True);value['model_root']=str(link)
    binding.write_text('{' if kind == 'bad_json' else json.dumps(value))
    binding.chmod(0o644 if kind == 'public_mode' else 0o600)
    monkeypatch.setattr(source, 'BINDING', binding)
    app=FastAPI();app.include_router(subing_model.router);app.include_router(research_subing_decision.router)
    client=TestClient(app)
    assert client.get('/api/v1/subing-model/status').json() == {'detail': {'code':'MODEL_STATUS_UNAVAILABLE'}}
    assert client.get('/api/v1/research/subing-decision/runs').json() == {'detail': {'code':'RESULT_SOURCE_INVALID'}}
