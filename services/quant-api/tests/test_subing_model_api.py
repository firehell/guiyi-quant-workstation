import json
import pytest
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import subing_model as api


@pytest.fixture(autouse=True)
def isolate_private_binding(monkeypatch):
    monkeypatch.setattr(api, 'registered_source', lambda key: None)


def test_not_started_never_initializes_database(tmp_path, monkeypatch):
    monkeypatch.setattr(api, 'ACTIVE', tmp_path/'active.json')
    monkeypatch.setattr(api, 'ModelStore', lambda _: (_ for _ in ()).throw(AssertionError('database must stay closed')))
    app=FastAPI();app.include_router(api.router)
    assert TestClient(app).get('/api/v1/subing-model/status').json()['status']=='NOT_STARTED'


def test_real_projection_requires_fresh_matching_heartbeat_and_hides_errors(tmp_path, monkeypatch):
    active=tmp_path/'active.json';heartbeat=tmp_path/'heartbeat.json';db=tmp_path/'database.url'
    active.write_text(json.dumps(dict(run_id='dev')));db.write_text('private-settings');db.chmod(0o600)
    monkeypatch.setattr(api,'FACTS_INDEX',tmp_path/'facts-index.json');monkeypatch.setattr(api, 'ACTIVE', active);monkeypatch.setattr(api, 'HEARTBEAT', heartbeat);monkeypatch.setattr(api, 'DB_PATH', db)
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,_):return SimpleNamespace(one=lambda: [dict(run_id='dev',source_day='2026-11-05',account=dict(open_quantity=0)),None])
    monkeypatch.setattr(api,'ModelStore',lambda _:SimpleNamespace(engine=SimpleNamespace(dispose=lambda:None)))
    monkeypatch.setattr(api,'Session',lambda *a,**k:Connection())
    monkeypatch.setattr(api,'readonly_transaction',lambda session,timeout_seconds:nullcontext(session))
    app=FastAPI();app.include_router(api.router);client=TestClient(app)
    for run,age,status in [('other',0,'STALE_OR_STOPPED'),('dev',30,'STALE_OR_STOPPED'),('dev',0,'RUNNING')]:
        heartbeat.write_text(json.dumps(dict(run_id=run,status='RUNNING',at=(datetime.now(UTC)-timedelta(seconds=age)).isoformat())))
        assert client.get('/api/v1/subing-model/status').json()['worker_status']==status
    monkeypatch.setattr(api,'ModelStore',lambda _: (_ for _ in ()).throw(ValueError('private-settings')))
    r=client.get('/api/v1/subing-model/status')
    assert r.status_code==503 and r.json()=={'detail':{'code':'MODEL_STATUS_UNAVAILABLE'}}


def test_registered_cost_is_separate_from_already_committed_input():
    raw=dict(fee_policy_version='current_complete_else_previous_trading_day_v1',captured_at='2026-11-05T00:00:00+00:00',
             fee_assumption=dict(assumed=True,source_day='2026-11-04',target_day='2026-11-05'))
    registered=api.cost_policy(raw,'REGISTERED_WAIT_NEW_COMPLETED_BAR')
    applied=api.cost_policy(raw,'LAST_COMMITTED_MODEL_INPUT')
    assert registered['status']!=applied['status']
    assert registered['input_hash']==applied['input_hash']
    assert registered['assumption']['source_day']=='2026-11-04'
    assert api.cost_policy(None,'any') is None
