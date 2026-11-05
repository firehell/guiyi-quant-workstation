"""Actual isolated PostgreSQL tests; never connect unless explicitly requested."""
import os,uuid
from pathlib import Path
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.subing_model.store import ModelStore
from app.subing_model.account import ContinuousAccount
from tests.unit.subing_account.test_account import BASE
from test_subing_continuous_account import packets
from datetime import timedelta

pytestmark=pytest.mark.skipif(os.getenv('GUIYI_SUBING_MODEL_PG_TEST')!='1',reason='explicit isolated PostgreSQL opt-in required')

def test_real_commit_duplicate_restore_and_immutability():
    store=ModelStore(Path('.run/subing-model-test-database.url').read_text(),test_only=True)
    run='isolated-test-'+uuid.uuid4().hex;a=ContinuousAccount('JM2609',run,BASE-timedelta(minutes=1))
    try:
        store.create(run,dict(kind='ISOLATED_TEST'),a.state())
        for i,p in enumerate(packets()):
            a.apply(p);assert store.append(run,p,a.state(),i)
        record,rows=store.load(run);b=ContinuousAccount('JM2609',run,BASE-timedelta(minutes=1))
        for row in rows:b.apply(row)
        assert b.state()==record['state']==a.state()
        assert not store.append(run,rows[-1],a.state(),0)
        with pytest.raises(DBAPIError):
            with store.engine.begin() as c:c.execute(text('UPDATE subing_development_events SET event_hash=event_hash WHERE run_id=:run'),dict(run=run))
        with pytest.raises(DBAPIError):
            with store.engine.begin() as c:c.execute(text("UPDATE subing_development_runs SET identity='{}' WHERE run_id=:run"),dict(run=run))
        with pytest.raises(ValueError,match='MODEL_EVENT_CONFLICT'):
            store.append(run,dict(rows[-1],observed_at='conflict'),a.state(),len(rows))
        store.load(run)
    finally:store.engine.dispose()
