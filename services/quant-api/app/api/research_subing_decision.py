"""Read-only explicitly registered JM decision replays; no replay on request."""
import hashlib
import json
import os
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from app.new_subing_research.store import _read_file, _safe_root, ResultStoreError

router = APIRouter(prefix='/api/v1/research/subing-decision', tags=['subing-decision'])

def fail(code, status=409):
    raise HTTPException(status_code=status, detail={'code': code})

def registry():
    value = os.getenv('GUIYI_SUBING_DECISION_RESULTS_ROOT')
    if not value:
        fail('RESULTS_UNAVAILABLE', 404)
    try:
        root = _safe_root(Path(value))
        rows = json.loads(_read_file(root/'index.json'))
        if not isinstance(rows,list) or len({r['id'] for r in rows}) != len(rows):
            fail('RESULT_INDEX_INVALID')
        for r in rows:
            if not re.fullmatch('[a-f0-9]{64}',r['id']) or r['sha256']!=r['id']:
                fail('RESULT_INDEX_INVALID')
        return root, rows
    except (OSError, ValueError, KeyError, TypeError, ResultStoreError):
        fail('RESULT_INDEX_INVALID')

def packet(run_id):
    if not re.fullmatch('[a-f0-9]{64}',run_id):
        fail('RUN_ID_INVALID',422)
    root,rows=registry()
    row=next((r for r in rows if r['id']==run_id),None)
    if row is None:fail('RESULT_NOT_FOUND',404)
    try:
        raw=_read_file(root/(run_id+'.json'))
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:fail('RESULT_HASH_MISMATCH')
        data=json.loads(raw)
        if data['product']!='jm' or data['contract']!=row['contract'] or data['version']!='subing_unified_demand_candidate_v1' or data.get('projection_version')!='subing_demand_explanation_v2' or not data['chain']:
            fail('RESULT_IDENTITY_INVALID')
        return data
    except (OSError, ValueError, KeyError, TypeError, ResultStoreError):
        fail('RESULT_INVALID')

@router.get('/runs')
def runs():
    _,rows=registry()
    return {'runs':sorted(rows,key=lambda r:r['through'],reverse=True)}

@router.get('/runs/{run_id}')
def overview(run_id:str):
    d=packet(run_id)
    return {k:v for k,v in d.items() if k not in ('chain','chart','fills') } | {'times':[r['at'] for r in d['chain']]}

@router.get('/runs/{run_id}/decision')
def decision(run_id:str,index:int=Query(ge=0)):
    d=packet(run_id)
    if index>=len(d['chain']):fail('CURSOR_INVALID',422)
    row=d['chain'][index];at=row['at']
    return {'decision':row,'chart':[r for r in d['chart'] if r['at']<=at][-128:],
            'fills':[f for f in d['fills'] if f['fill_at']<=at]}

@router.get('/runs/{run_id}/history')
def history(run_id:str,index:int=Query(ge=0),offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100)):
    d=packet(run_id)
    if index>=len(d['chain']):fail('CURSOR_INVALID',422)
    rows=list(reversed(d['chain'][:index+1]))
    return {'items':rows[offset:offset+limit],'total':len(rows)}
