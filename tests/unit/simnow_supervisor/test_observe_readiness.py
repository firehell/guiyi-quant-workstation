from dataclasses import replace
from datetime import timedelta
import json

import pytest

from test_supervisor import setup, Clock, FakeDriver, FakeMarket, ACCOUNT, digest
from guiyi_quant.simnow_execution.inventory import native_hash
from guiyi_quant.simnow_execution.journal import Journal
from guiyi_quant.simnow_execution.monitor import MonitorReader, MonitorPublisher
from guiyi_quant.simnow_execution.supervisor import Supervisor


def observing(tmp_path, *, cycles=1, capture=None):
    settings, original = setup(tmp_path)
    at = original.at + timedelta(seconds=2)
    source = 'ctp-inventory:' + original.trading_day + ':' + native_hash(
        (original.account_id, original.trading_day, original.data, at.isoformat()))
    snapshot = replace(original, started_at=original.at, at=at, source_id=source)
    clock = Clock()
    clock.at = at + timedelta(seconds=1)
    folder = settings.state_root / ACCOUNT
    Journal(folder / 'dispatch.sqlite', ACCOUNT).close()
    before = {n: digest(folder / n) for n in ['account.sqlite', 'dispatch.sqlite']}
    reader = MonitorReader(settings.state_root)
    captured = [] if capture is None else capture
    driver = FakeDriver(snapshot)
    def advance(_):
        clock.at += timedelta(seconds=5)
        at = clock.at - timedelta(seconds=1)
        source = 'ctp-inventory:' + snapshot.trading_day + ':' + native_hash((snapshot.account_id, snapshot.trading_day, snapshot.data, at.isoformat()))
        driver.fact = replace(snapshot, started_at=driver.fact.at, at=at, source_id=source)
    host = Supervisor(settings, ('JM', 'RB'), FakeMarket(), lambda *_: driver,
                      clock=clock.now, sleep=advance)
    original_status = host.status
    def status(code, **kwargs):
        original_status(code, **kwargs)
        if code == 'OBSERVING':
            captured.append((reader.overview(clock.now()), json.loads((settings.state_root / 'monitor.json').read_text())))
    host.status = status
    host.run(max_cycles=cycles)
    assert {n: digest(folder / n) for n in before} == before
    return settings, snapshot, clock, reader, *captured[0]


def test_observe_proves_native_readback_without_promoting_ledger(tmp_path):
    settings, snapshot, clock, reader, result, _index = observing(tmp_path)
    assert result['observe_reconciliation_ready'] is True
    assert result['observe_reconciliation_status'] == 'verified'
    assert result['readback_status'] == 'pending'
    assert result['position_projection_complete'] is False
    assert result['metrics']['margin_limit'] is None
    stopped = reader.overview(clock.now())
    assert stopped['observe_reconciliation_ready'] is False
    assert stopped['observer']['status'] == 'stopped'


def test_observe_projection_expiry_cannot_be_renewed_by_index(tmp_path):
    settings, snapshot, clock, reader, _, active_index = observing(tmp_path)
    # Keep the genuine in-flight index captured before final STOPPED publication.
    active_index['published_at'] = (snapshot.at + timedelta(seconds=30)).isoformat()
    (settings.state_root / 'monitor.json').write_text(json.dumps(active_index))
    result = reader.overview(snapshot.at + timedelta(seconds=30))
    assert result['observe_reconciliation_ready'] is False
    assert result['observe_reconciliation_status'] == 'stale'


def test_old_monitor_without_observe_proof_remains_compatible(tmp_path):
    settings, snapshot, clock, reader, _, active_index = observing(tmp_path)
    assert MonitorPublisher(settings.state_root, ACCOUNT, 'new-run').publish(
        'STARTING', clock.now(), mode='observe', host_status='WAITING_SESSION')
    result = reader.overview(clock.now())
    assert result['observe_reconciliation_ready'] is False
    assert result['readback_status'] == 'pending'


@pytest.mark.parametrize('field,value', [
    ('account_id', 'b' * 64), ('run_id', 'other-run'), ('products', ['RB']),
    ('native_source_id', 'ctp-inventory:20261027:' + 'b' * 64),
    ('ledger_hash', 'b' * 64), ('verified', False),
])
def test_mismatched_proof_never_falls_back_to_old_success(tmp_path, field, value):
    from guiyi_quant.htdy_account_execution.codec import digest as state_digest
    settings, snapshot, clock, reader, _, index = observing(tmp_path)
    proof = index['observe_reconciliation']
    proof[field] = value
    proof['proof_sha256'] = state_digest({k: v for k, v in proof.items() if k != 'proof_sha256'})
    (settings.state_root / 'monitor.json').write_text(json.dumps(index))
    result = reader.overview(clock.now())
    assert result['status'] == 'unavailable'
    assert result['observe_reconciliation_ready'] is False


@pytest.mark.parametrize('field,value', [('run_id','new-run'), ('mode','trade'), ('mode','manage')])
def test_proof_is_not_authority_for_another_run_or_mode(tmp_path, field, value):
    settings, snapshot, clock, reader, _, index = observing(tmp_path)
    index[field] = value
    (settings.state_root / 'monitor.json').write_text(json.dumps(index))
    assert reader.overview(clock.now())['observe_reconciliation_ready'] is False


def test_new_native_evidence_without_new_index_invalidates_old_proof(tmp_path):
    from guiyi_quant.simnow_execution.evidence import Evidence
    settings, snapshot, clock, reader, _, index = observing(tmp_path)
    later = snapshot.at + timedelta(seconds=1)
    source = 'ctp-inventory:' + snapshot.trading_day + ':' + native_hash(
        (snapshot.account_id, snapshot.trading_day, snapshot.data, later.isoformat()))
    fresh = replace(snapshot, started_at=snapshot.at, at=later, source_id=source)
    evidence = Evidence(settings.state_root / ACCOUNT / 'native-evidence.sqlite', ACCOUNT)
    evidence.append(fresh)
    evidence.close()
    (settings.state_root / 'monitor.json').write_text(json.dumps(index))
    assert reader.overview(clock.now())['status'] == 'unavailable'


def test_proof_must_match_current_ledger_not_a_historical_checkpoint(tmp_path):
    from guiyi_quant import htdy_account_execution as a
    settings, snapshot, clock, reader, _, index = observing(tmp_path)
    store = a.LocalStore(settings.state_root / ACCOUNT / 'account.sqlite')
    store.execute('new-disconnect', a.Disconnect(clock.now()))
    store.close()
    (settings.state_root / 'monitor.json').write_text(json.dumps(index))
    assert reader.overview(clock.now())['status'] == 'unavailable'


def test_two_observe_rounds_require_distinct_native_sources(tmp_path):
    rounds = []
    observing(tmp_path, cycles=2, capture=rounds)
    assert len(rounds) == 2
    assert all(result['observe_reconciliation_ready'] for result, _ in rounds)
    assert len({index['native_source_id'] for _, index in rounds}) == 2


@pytest.mark.parametrize('field,value', [('checked_at','2100-01-01T00:00:00+00:00'),
                                         ('valid_until','2100-01-01T00:00:00+00:00'),
                                         ('proof_sha256','0' * 64)])
def test_forged_time_or_hash_cannot_extend_observe_validity(tmp_path, field, value):
    from guiyi_quant.htdy_account_execution.codec import digest as state_digest
    settings, snapshot, clock, reader, _, index = observing(tmp_path)
    index['observe_reconciliation'][field] = value
    if field != 'proof_sha256':
        index['observe_reconciliation']['proof_sha256'] = state_digest({k:v for k,v in index['observe_reconciliation'].items() if k!='proof_sha256'})
    (settings.state_root / 'monitor.json').write_text(json.dumps(index))
    assert reader.overview(clock.now())['observe_reconciliation_ready'] is False
