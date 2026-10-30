"""Offline SDK-admission timing; temporary journals and a fake native API only."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta

import pytest

from test_adapter import setup
from guiyi_quant.simnow_execution import adapter as module
from guiyi_quant.simnow_execution.host import Host
from guiyi_quant.simnow_execution.evidence import Evidence


@pytest.mark.parametrize('delay_at', ['guard', 'preflight', 'request', 'claim'])
def test_elapsed_work_cannot_admit_expired_quote(tmp_path, monkeypatch, delay_at):
    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)
    facts = replace(facts, quote=replace(facts.quote, valid_until=at + timedelta(seconds=3)))
    from guiyi_quant.simnow_execution.model import action_hash
    permit = replace(permit, action_hash=action_hash(adapter.store.current(), effect,
        adapter.session, binding, None, facts))
    elapsed = [0.0]
    monkeypatch.setattr(module, 'monotonic', lambda: elapsed[0])
    if delay_at == 'guard':
        original = adapter.store.dispatch_guard
        @contextmanager
        def slow_guard():
            with original() as state:
                elapsed[0] += 3.2
                yield state
        monkeypatch.setattr(adapter.store, 'dispatch_guard', slow_guard)
    elif delay_at == 'request':
        from types import SimpleNamespace
        def build():
            elapsed[0] += 3.2
            return SimpleNamespace()
        adapter.sdk.CThostFtdcInputOrderField = build
    else:
        name = '_preflight' if delay_at == 'preflight' else 'claim'
        owner = adapter if delay_at == 'preflight' else adapter.journal
        original = getattr(owner, name)
        def slow(*args):
            result = original(*args)
            elapsed[0] += 3.2
            return result
        monkeypatch.setattr(owner, name, slow)
    if delay_at == 'claim':
        with pytest.raises(ValueError, match='CLAIMED_NEVER_SENT_EXPIRED'):
            adapter.dispatch(effect, binding, None, facts, permit, at)
    else:
        with pytest.raises(ValueError, match='NATIVE_FACT_STALE'):
            adapter.dispatch(effect, binding, None, facts, permit, at)
    assert not api.calls
    assert adapter.journal.claimed(effect.order.order_id) == (delay_at == 'claim')
    if delay_at == 'claim':
        assert adapter.journal.conn.execute('SELECT outcome FROM results').fetchall() == [('CLAIMED_NEVER_SENT_EXPIRED',)]
        with pytest.raises(ValueError):
            adapter.abort_unsent(effect.order.order_id, 'LOCAL_PREFLIGHT_FAILED', at)
        assert adapter.journal.claimed(effect.order.order_id)


@pytest.mark.parametrize('gate', ['permit', 'native_session', 'session', 'binding', 'readback', 'instrument', 'close_cutoff'])
def test_postclaim_rechecks_each_time_bound(tmp_path, monkeypatch, gate):
    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)
    end = at + timedelta(seconds=1)
    state = adapter.store.current()
    if gate == 'permit':
        permit = replace(permit, expires_at=end)
    elif gate == 'native_session':
        adapter.session = replace(adapter.session, valid_until=end)
    elif gate == 'session':
        facts = replace(facts, session=replace(facts.session, valid_until=end))
    elif gate == 'binding':
        binding = replace(binding, valid_until=end)
    elif gate == 'readback':
        state = replace(state, readback=replace(state.readback, valid_until=end))
        original_guard = adapter.store.dispatch_guard
        @contextmanager
        def guarded():
            with original_guard():
                yield state
        monkeypatch.setattr(adapter.store, 'dispatch_guard', guarded)
    elif gate == 'instrument':
        facts = replace(facts, instrument=replace(facts.instrument, valid_until=end))
    else:
        facts = replace(facts, session=replace(facts.session, final_close_at=at + timedelta(seconds=61)))
    from guiyi_quant.simnow_execution.model import action_hash
    permit = replace(permit, action_hash=action_hash(state, effect, adapter.session, binding, None, facts))
    elapsed = [0.0]
    monkeypatch.setattr(module, 'monotonic', lambda: elapsed[0])
    original = adapter.journal.claim
    def claim(*args):
        result = original(*args)
        elapsed[0] += 1.1
        return result
    monkeypatch.setattr(adapter.journal, 'claim', claim)
    with pytest.raises(ValueError, match='CLAIMED_NEVER_SENT_EXPIRED'):
        adapter.dispatch(effect, binding, None, facts, permit, at)
    assert not api.calls and adapter.journal.claimed(effect.order.order_id)
    assert adapter.last_dispatch_diagnostic['stage'] == 'SDK_ADMISSION_FRESHNESS'
    assert adapter.last_dispatch_diagnostic['code'] == 'CLAIMED_NEVER_SENT_EXPIRED'


def test_clock_forward_jump_is_retained_after_rollback(monkeypatch):
    from test_adapter import T
    elapsed = [0.0]
    wall = [T]
    monkeypatch.setattr(module, 'monotonic', lambda: elapsed[0])
    fresh = module.dispatch_clock(T, lambda: wall[0])
    elapsed[0] = 1
    wall[0] = T - timedelta(hours=1)
    assert fresh() == T + timedelta(seconds=1)
    wall[0] = T + timedelta(hours=1)
    assert fresh() == wall[0]
    elapsed[0] = 2
    wall[0] = T
    assert fresh() == T + timedelta(hours=1)


@pytest.mark.parametrize('delay_at', ['host_projection', 'tick_commit', 'journal_scan'])
def test_host_cumulative_elapsed_time_cannot_refresh_old_input(tmp_path, monkeypatch, delay_at):
    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)
    elapsed = [0.0]
    monkeypatch.setattr(module, 'monotonic', lambda: elapsed[0])
    facts = replace(facts, quote=replace(facts.quote, valid_until=at + timedelta(seconds=3)))
    evidence = Evidence(tmp_path / 'evidence.db', adapter.session.account_id)
    host = Host(adapter.store, adapter.journal, evidence, adapter, 'RB',
        run_id='timing-fixture', deadline=at + timedelta(minutes=1))
    if delay_at == 'host_projection':
        original = adapter.store.current
        def current():
            result = original()
            elapsed[0] += 3.2
            return result
        monkeypatch.setattr(adapter.store, 'current', current)
    elif delay_at == 'tick_commit':
        original = adapter.store.execute
        def execute(*args, **kwargs):
            result = original(*args, **kwargs)
            elapsed[0] += 3.2
            # Existing fixture already persisted the proposal. Return its effect
            # so this tests Host.tick's commit-to-submit timing boundary.
            return replace(result, effects=(effect,))
        monkeypatch.setattr(adapter.store, 'execute', execute)
    else:
        original = adapter.journal.events
        def events():
            result = original()
            elapsed[0] += 3.2
            return result
        monkeypatch.setattr(adapter.journal, 'events', events)
    with pytest.raises(ValueError, match='NATIVE_FACT_STALE'):
        if delay_at == 'tick_commit':
            host.tick((facts,), (binding,), at)
        else:
            host.submit_effects((effect,), (binding,), (facts,), at)
    assert not api.calls and not adapter.journal.claimed(effect.order.order_id)
    assert adapter.store.current().orders[0].status == 'LOCAL_ABORTED'
    evidence.close()


def test_host_keeps_postclaim_never_sent_order_and_unique_claim(tmp_path, monkeypatch):
    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)
    elapsed = [0.0]
    monkeypatch.setattr(module, 'monotonic', lambda: elapsed[0])
    evidence = Evidence(tmp_path / 'evidence.db', adapter.session.account_id)
    host = Host(adapter.store, adapter.journal, evidence, adapter, 'RB',
        run_id='timing-fixture', deadline=at + timedelta(minutes=1))
    original = adapter.journal.claim
    def claim(*args):
        result = original(*args)
        elapsed[0] += 3.2
        return result
    monkeypatch.setattr(adapter.journal, 'claim', claim)
    with pytest.raises(ValueError, match='CLAIMED_NEVER_SENT_EXPIRED'):
        host.submit_effects((effect,), (binding,), (facts,), at)
    assert adapter.store.current().orders[0].status == 'PROPOSED'
    assert adapter.journal.claimed(effect.order.order_id) and not api.calls
    monkeypatch.setattr(adapter.journal, 'claim', original)
    # A later fresh retry still cannot take a second claim or enter the SDK.
    assert host.submit_effects((effect,), (binding,), (facts,), at) == ('ALREADY_CLAIMED_NO_SEND',)
    assert adapter.journal.conn.execute('SELECT COUNT(*) FROM actions').fetchone() == (1,)
    assert not api.calls
    evidence.close()


def test_production_clock_rejects_stale_caller_time(tmp_path):
    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)
    adapter.clock = lambda: at + timedelta(seconds=6)
    with pytest.raises(ValueError, match='NATIVE_FACT_STALE'):
        adapter.dispatch(effect, binding, None, facts, permit, at)
    assert not adapter.journal.claimed(effect.order.order_id) and not api.calls


def test_postclaim_result_write_failure_does_not_refund_claim(tmp_path, monkeypatch):
    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)
    elapsed = [0.0]
    monkeypatch.setattr(module, 'monotonic', lambda: elapsed[0])
    original = adapter.journal.claim
    def claim(*args):
        result = original(*args)
        elapsed[0] += 6
        return result
    def failed_result(*args):
        adapter.journal.uncertain = True
        raise ValueError('DISPATCH_RESULT_UNKNOWN')
    monkeypatch.setattr(adapter.journal, 'claim', claim)
    monkeypatch.setattr(adapter.journal, 'result', failed_result)
    with pytest.raises(ValueError, match='DISPATCH_RESULT_UNKNOWN'):
        adapter.dispatch(effect, binding, None, facts, permit, at)
    assert adapter.journal.claimed(effect.order.order_id) and not api.calls
    with pytest.raises(ValueError, match='NATIVE_CALLBACK_OR_COMMIT_REQUIRES_RECOVERY'):
        adapter.dispatch(effect, binding, None, facts, permit, at)
    assert adapter.journal.conn.execute('SELECT COUNT(*) FROM actions').fetchone() == (1,)
    assert not api.calls


def test_subttl_stages_accumulate_instead_of_resetting_clock(tmp_path, monkeypatch):
    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)
    elapsed = [0.0]
    wall = [at]
    monkeypatch.setattr(module, 'monotonic', lambda: elapsed[0])
    adapter.clock = lambda: wall[0]
    # Each individual stage takes less than the 3-second Host permit; their sum
    # expires it. The UTC clock also rolls backwards and cannot extend the TTL.
    original_guard = adapter.store.dispatch_guard
    @contextmanager
    def guard():
        with original_guard() as state:
            elapsed[0] += 1.1
            yield state
    original_preflight = adapter._preflight
    def preflight(*args):
        result = original_preflight(*args)
        elapsed[0] += 1.1
        return result
    original_claim = adapter.journal.claim
    def claim(*args):
        result = original_claim(*args)
        elapsed[0] += 1.1
        wall[0] = at - timedelta(hours=1)
        return result
    monkeypatch.setattr(adapter.store, 'dispatch_guard', guard)
    monkeypatch.setattr(adapter, '_preflight', preflight)
    monkeypatch.setattr(adapter.journal, 'claim', claim)
    evidence = Evidence(tmp_path / 'evidence.db', adapter.session.account_id)
    host = Host(adapter.store, adapter.journal, evidence, adapter, 'RB',
        run_id='timing-fixture', deadline=at + timedelta(minutes=1))
    with pytest.raises(ValueError, match='CLAIMED_NEVER_SENT_EXPIRED'):
        host.submit_effects((effect,), (binding,), (facts,), at)
    assert adapter.journal.claimed(effect.order.order_id) and not api.calls
    evidence.close()


def test_forward_clock_step_during_claim_blocks_sdk(tmp_path, monkeypatch):
    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)
    wall = [at]
    adapter.clock = lambda: wall[0]
    original = adapter.journal.claim
    def claim(*args):
        result = original(*args)
        wall[0] += timedelta(hours=1)
        return result
    monkeypatch.setattr(adapter.journal, 'claim', claim)
    with pytest.raises(ValueError, match='CLAIMED_NEVER_SENT_EXPIRED'):
        adapter.dispatch(effect, binding, None, facts, permit, at)
    assert adapter.journal.claimed(effect.order.order_id) and not api.calls


@pytest.mark.parametrize('offset', ['OPEN', 'CLOSE'])
@pytest.mark.parametrize('boundary_seconds', [0.5, 1.0])
def test_sdk_freshness_rejects_open_and_close_after_contiguous_session_end(
    tmp_path, offset, boundary_seconds
):
    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)
    # Authority caps its validity at the continuous span, independently of final
    # daily close. The same adapter fence protects OPEN and CLOSE at that point.
    boundary = at + timedelta(seconds=boundary_seconds)
    facts = replace(facts, session=replace(facts.session, valid_until=boundary))
    if offset == 'CLOSE':
        effect = replace(effect, order=replace(effect.order, offset='CLOSE', side='SELL'))
    with pytest.raises(ValueError, match='NATIVE_FACT_STALE'):
        adapter._freshness(adapter.store.current(), effect, binding, None, facts, permit, boundary)
    assert not adapter.journal.claimed(effect.order.order_id) and not api.calls
