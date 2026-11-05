"""Read-only development model projection; never creates or enables accounts."""
from datetime import UTC,datetime,date
import json
from fastapi import APIRouter,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.readonly import readonly_transaction
from app.private_settings import read_private_settings_content
from app.subing_model.worker import ACTIVE,HEARTBEAT,DB_PATH,facts_for
from app.subing_model.store import ModelStore,runs,events
from app.subing_projection_source import registered_source
from app.market_data.new_subing_research import payload_hash
router=APIRouter(prefix='/api/v1/subing-model',tags=['subing-model'])
FACTS_INDEX=ACTIVE.parent/'subing-model-facts-index.json'

def cost_policy(raw,status):
    if not raw or not raw.get('fee_policy_version'):return None
    return dict(version=raw['fee_policy_version'],assumption=raw['fee_assumption'],captured_at=raw['captured_at'],
                input_hash=payload_hash(raw),status=status)

@router.get('/status')
def status():
    store=None
    try:
        source=registered_source('model_root')
        active_path=source/'subing-model-active.json' if source else ACTIVE
        db_path=source/'subing-model-database.url' if source else DB_PATH
        heartbeat_path=source/'subing-model-heartbeat.json' if source else HEARTBEAT
        facts_index=source/'subing-model-facts-index.json' if source else FACTS_INDEX
        if not active_path.exists():return dict(status='NOT_STARTED',products=[],account=None,auto_order=False)
        if active_path.is_symlink() or db_path.is_symlink() or heartbeat_path.is_symlink():raise ValueError('MODEL_PATH_INVALID')
        active=json.loads(active_path.read_text());store=ModelStore(read_private_settings_content(db_path).decode())
        with Session(store.engine, autoflush=False) as session, readonly_transaction(session, timeout_seconds=5) as c:
            row=c.execute(select(runs.c.state,events.c.payload).select_from(runs.outerjoin(events,
                (runs.c.run_id==events.c.run_id)&(runs.c.sequence==events.c.sequence))).where(runs.c.run_id==active['run_id'])).one()
        applied=cost_policy(row[1].get('facts') if row[1] else None,'LAST_COMMITTED_MODEL_INPUT')
        registered=cost_policy(facts_for(facts_index,date.fromisoformat(row[0]['source_day'])),'REGISTERED_WAIT_NEW_COMPLETED_BAR')
        heartbeat=json.loads(heartbeat_path.read_text()) if heartbeat_path.exists() else {}
        fresh=bool(heartbeat.get('run_id')==active['run_id'] and heartbeat.get('at') and 0<=(datetime.now(UTC)-datetime.fromisoformat(heartbeat['at'])).total_seconds()<15)
        return dict(row[0],cost_policy=applied,registered_cost_policy=registered,
                    worker_status=heartbeat.get('status') if fresh else 'STALE_OR_STOPPED',worker_code=heartbeat.get('code'),worker_observed_at=heartbeat.get('at'))
    except Exception:raise HTTPException(503,detail={'code':'MODEL_STATUS_UNAVAILABLE'}) from None
    finally:
        if store:store.engine.dispose()
