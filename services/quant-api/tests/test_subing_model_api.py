import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import subing_model as api


def test_not_started_never_initializes_database(tmp_path, monkeypatch):
    monkeypatch.setattr(api, 'ACTIVE', tmp_path/'active.json')
    monkeypatch.setattr(api, 'ModelStore', lambda _: (_ for _ in ()).throw(AssertionError('database must stay closed')))
    app=FastAPI();app.include_router(api.router)
    assert TestClient(app).get('/api/v1/subing-model/status').json()['status']=='NOT_STARTED'


def test_real_projection_requires_fresh_matching_heartbeat_and_hides_errors(tmp_path, monkeypatch):
    active=tmp_path/'active.json';heartbeat=tmp_path/'heartbeat.json';db=tmp_path/'database.url'
    active.write_text(json.dumps(dict(run_id='dev')));db.write_text('private-settings')
    monkeypatch.setattr(api, 'ACTIVE', active);monkeypatch.setattr(api, 'HEARTBEAT', heartbeat);monkeypatch.setattr(api, 'DB_PATH', db)
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,_):return SimpleNamespace(one=lambda: [dict(run_id='dev',account=dict(open_quantity=0))])
    monkeypatch.setattr(api,'ModelStore',lambda _:SimpleNamespace(engine=SimpleNamespace(connect=Connection,dispose=lambda:None)))
    app=FastAPI();app.include_router(api.router);client=TestClient(app)
    for run,age,status in [('other',0,'STALE_OR_STOPPED'),('dev',30,'STALE_OR_STOPPED'),('dev',0,'RUNNING')]:
        heartbeat.write_text(json.dumps(dict(run_id=run,status='RUNNING',at=(datetime.now(UTC)-timedelta(seconds=age)).isoformat())))
        assert client.get('/api/v1/subing-model/status').json()['worker_status']==status
    monkeypatch.setattr(api,'ModelStore',lambda _: (_ for _ in ()).throw(ValueError('private-settings')))
    r=client.get('/api/v1/subing-model/status')
    assert r.status_code==503 and r.json()=={'detail':{'code':'MODEL_STATUS_UNAVAILABLE'}}
