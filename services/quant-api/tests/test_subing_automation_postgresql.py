"""Only a disposable opt-in database; never the original model database."""
import os
import uuid

import pytest
from sqlalchemy import select

from app.subing_model.store import ModelStore, events
from app.subing_model_recovery import apply_event, model_state, consumed_bars
from test_subing_model_automation import empty_pipe, recovery_event, conflict_event, AT

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
    assert store.append(run, event, model_state(p), 0)
    assert not store.append(run, event, model_state(p), 0)
    record, journal = store.load(run)
    assert record['sequence'] == 1 and len(journal) == 1
    q = empty_pipe()
    q.identity['run_id'] = run
    for item in journal:
        apply_event(q, item)
    assert model_state(q) == record['state'] == model_state(p)
    assert q.last_outcome['model_fills'] == []
    with store.engine.connect() as conn:
        assert len(conn.execute(select(events).where(events.c.run_id == run)).all()) == 1
    store.engine.dispose()



def test_conflict_append_preserves_old_event_and_restarts():
    store = ModelStore(URL, test_only=True)
    store.initialize()
    p = empty_pipe()
    run = 'conflict-test-' + uuid.uuid4().hex
    event, old = conflict_event(p)
    p.identity.update(run_id=run, prepared={'jm': {'warmup': {}}},
                      bootstrap=[dict(channel='live:bar:jm:1m', data=old)])
    store.create(run, p.identity, p.state())
    seed = dict(event_id='seed', observed_at=AT.isoformat(), observations=[],
                contexts={}, cursor='0-0', source_day='2026-11-04')
    apply_event(p, seed)
    seed['outcome'] = p.last_outcome
    store.append(run, seed, model_state(p), 0)
    with store.engine.connect() as conn:
        original = dict(conn.execute(select(events).where(events.c.run_id == run)).mappings().one())
    consumed_bars(p.identity, [seed, event])
    apply_event(p, event)
    event['outcome'] = p.last_outcome
    store.append(run, event, model_state(p), 1)
    record, journal = store.load(run)
    with store.engine.connect() as conn:
        retained = dict(conn.execute(select(events).where(events.c.run_id == run, events.c.sequence == 1)).mappings().one())
    assert retained == original
    q = empty_pipe()
    q.identity = p.identity
    for item in journal:
        apply_event(q, item)
    assert model_state(q) == record['state'] == model_state(p)
    assert model_state(q)['recovery']['conflict_count'] == 1
    assert q.last_outcome['model_fills'] == []
    store.engine.dispose()


def test_backlog_resume_commits_and_replays_without_account_execution():
    from test_subing_model_automation import backlog_event
    store = ModelStore(URL, test_only=True)
    store.initialize()
    p = empty_pipe()
    run = 'resume-test-' + uuid.uuid4().hex
    p.identity['run_id'] = run
    store.create(run, p.identity, model_state(p))
    event = backlog_event()
    apply_event(p, event)
    event['outcome'] = p.last_outcome
    store.append(run, event, model_state(p), 0)
    record, journal = store.load(run)
    q = empty_pipe()
    q.identity['run_id'] = run
    for item in journal:
        apply_event(q, item)
    assert model_state(q) == record['state']
    assert q.last_outcome['model_fills'] == []
    store.engine.dispose()
