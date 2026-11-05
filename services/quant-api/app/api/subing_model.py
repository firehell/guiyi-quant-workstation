"""Read-only development model projection; never creates or enables accounts."""
from datetime import UTC,datetime,date
import json
from fastapi import APIRouter,HTTPException
from sqlalchemy import select
from app.subing_model.worker import ACTIVE,HEARTBEAT,DB_PATH,facts_for
from app.subing_model.store import ModelStore,runs,events
from app.market_data.new_subing_research import payload_hash
router=APIRouter(prefix='/api/v1/subing-model',tags=['subing-model'])
FACTS_INDEX=ACTIVE.parent/'subing-model-facts-index.json'

def cost_policy(raw,status):
    if not raw or not raw.get('fee_policy_version'):return None
    return dict(version=raw['fee_policy_version'],assumption=raw['fee_assumption'],captured_at=raw['captured_at'],
                input_hash=payload_hash(raw),status=status)

@router.get('/status')
def status():
    if not ACTIVE.exists():return dict(status='NOT_STARTED',products=[],account=None,auto_order=False)
    if ACTIVE.is_symlink() or DB_PATH.is_symlink():raise HTTPException(409,detail={'code':'MODEL_PATH_INVALID'})
    store=None
    try:
        active=json.loads(ACTIVE.read_text());store=ModelStore(DB_PATH.read_text())
        with store.engine.connect() as c:
            row=c.execute(select(runs.c.state,events.c.payload).select_from(runs.outerjoin(events,
                (runs.c.run_id==events.c.run_id)&(runs.c.sequence==events.c.sequence))).where(runs.c.run_id==active['run_id'])).one()
        applied=cost_policy(row[1].get('facts') if row[1] else None,'LAST_COMMITTED_MODEL_INPUT')
        registered=cost_policy(facts_for(FACTS_INDEX,date.fromisoformat(row[0]['source_day'])),'REGISTERED_WAIT_NEW_COMPLETED_BAR')
        heartbeat=json.loads(HEARTBEAT.read_text()) if HEARTBEAT.exists() else {}
        fresh=bool(heartbeat.get('run_id')==active['run_id'] and heartbeat.get('at') and 0<=(datetime.now(UTC)-datetime.fromisoformat(heartbeat['at'])).total_seconds()<15)
        return dict(row[0],cost_policy=applied,registered_cost_policy=registered,
                    worker_status=heartbeat.get('status') if fresh else 'STALE_OR_STOPPED',worker_code=heartbeat.get('code'),worker_observed_at=heartbeat.get('at'))
    except Exception:raise HTTPException(503,detail={'code':'MODEL_STATUS_UNAVAILABLE'}) from None
    finally:
        if store:store.engine.dispose()
