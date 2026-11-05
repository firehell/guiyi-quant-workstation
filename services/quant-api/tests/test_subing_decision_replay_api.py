import hashlib
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.research_subing_decision import router

def setup(tmp_path,monkeypatch):
    chain=[dict(at=f'2025-01-06T09:0{i}:00+08:00',demand='WAIT') for i in range(3)]
    data=dict(projection_version='subing_demand_explanation_v2',product='jm',contract='JM2505',version='subing_unified_demand_candidate_v1',chain=chain,chart=[dict(at=r['at'],close='100') for r in chain],fills=[dict(fill_at=chain[2]['at'],price='100')])
    raw=json.dumps(data).encode();key=hashlib.sha256(raw).hexdigest()
    (tmp_path/(key+'.json')).write_bytes(raw)
    (tmp_path/'index.json').write_text(json.dumps([dict(id=key,sha256=key,contract='JM2505',through='2025-01-06')]))
    monkeypatch.setenv('GUIYI_SUBING_DECISION_RESULTS_ROOT',str(tmp_path))
    app=FastAPI();app.include_router(router)
    return TestClient(app),key

def test_cursor_filters_future_and_pages(tmp_path,monkeypatch):
    c,k=setup(tmp_path,monkeypatch);base='/api/v1/research/subing-decision/runs/'+k
    d=c.get(base+'/decision?index=1').json()
    assert len(d['chart'])==2 and d['fills']==[]
    assert c.get(base+'/history?index=1&limit=1&offset=1').json()['items'][0]['at'].endswith('09:00:00+08:00')
    assert c.get(base+'/decision?index=99').status_code==422
    assert c.get(base+'/history?index=1&limit=101').status_code==422

def test_tampering_unknown_and_unregistered(tmp_path,monkeypatch):
    c,k=setup(tmp_path,monkeypatch);base='/api/v1/research/subing-decision/runs/'
    assert c.get(base+'a'*64).status_code==404
    (tmp_path/(k+'.json')).write_text('{}')
    assert c.get(base+k).status_code==409
    monkeypatch.delenv('GUIYI_SUBING_DECISION_RESULTS_ROOT')
    assert c.get(base).status_code==404
