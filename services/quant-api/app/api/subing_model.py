"""Read-only development model projection; never creates or enables accounts."""
from datetime import UTC,datetime
import json
from fastapi import APIRouter,HTTPException
from sqlalchemy import select
from app.subing_model.worker import ACTIVE,HEARTBEAT,DB_PATH
from app.subing_model.store import ModelStore,runs
router=APIRouter(prefix='/api/v1/subing-model',tags=['subing-model'])

@router.get('/status')
def status():
    if not ACTIVE.exists():return dict(status='NOT_STARTED',products=[],account=None,auto_order=False)
    if ACTIVE.is_symlink() or DB_PATH.is_symlink():raise HTTPException(409,detail={'code':'MODEL_PATH_INVALID'})
    store=None
    try:
        active=json.loads(ACTIVE.read_text());store=ModelStore(DB_PATH.read_text())
        with store.engine.connect() as c:
            row=c.execute(select(runs.c.state).where(runs.c.run_id==active['run_id'])).one()
        heartbeat=json.loads(HEARTBEAT.read_text()) if HEARTBEAT.exists() else {}
        fresh=bool(heartbeat.get('run_id')==active['run_id'] and heartbeat.get('at') and 0<=(datetime.now(UTC)-datetime.fromisoformat(heartbeat['at'])).total_seconds()<15)
        return dict(row[0],worker_status=heartbeat.get('status') if fresh else 'STALE_OR_STOPPED',worker_code=heartbeat.get('code'),worker_observed_at=heartbeat.get('at'))
    except Exception:raise HTTPException(503,detail={'code':'MODEL_STATUS_UNAVAILABLE'}) from None
    finally:
        if store:store.engine.dispose()
