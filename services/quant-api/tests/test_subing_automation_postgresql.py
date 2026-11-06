"""Only a disposable opt-in database; never the original model database."""
import os
import uuid

import pytest
from sqlalchemy import select

from app.subing_model.store import ModelStore, events
from app.subing_model_recovery import apply_event
from test_subing_model_automation import empty_pipe, recovery_event

URL = os.environ.get('GUIYI_SUBING_AUTOMATION_PG_URL')
pytestmark = pytest.mark.skipif(not URL, reason='disposable PostgreSQL opt-in required')


def test_recovery_commit_duplicate_and_full_restart():
    store = ModelStore(URL, test_only=True)
    store.initialize()
    p = empty_pipe()
    run = 'automation-test-' + uuid.uuid4().hex
    p.identity['run_id'] = run
    store.create(run, p.identity, p.state())
    event = recovery_event(p)
    apply_event(p, event)
    event['outcome'] = p.last_outcome
    assert store.append(run, event, p.state(), 0)
    assert not store.append(run, event, p.state(), 0)
    record, journal = store.load(run)
    assert record['sequence'] == 1 and len(journal) == 1
    q = empty_pipe()
    q.identity['run_id'] = run
    for item in journal:
        apply_event(q, item)
    assert q.state() == record['state'] == p.state()
    assert q.last_outcome['model_fills'] == []
    with store.engine.connect() as conn:
        assert len(conn.execute(select(events).where(events.c.run_id == run)).all()) == 1
    store.engine.dispose()
