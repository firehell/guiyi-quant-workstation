from copy import deepcopy
from datetime import UTC, datetime
import json

import pytest

from app.reference_trading.htdy_snapshot import SnapshotError, SnapshotStore


def payload(source='a' * 64):
    from dataclasses import replace
    from app.reference_trading.htdy_history import history_identity
    identity = replace(history_identity('jm','60m'), formula_versions=('v1',))
    return dict(schema_version='htdy_historical_reference_v1', recording_mode='historical_replay',
                product='jm', frequency='60m', source='canonical', source_token=source,
                reference_model_version='htdy_historical_window32_reverse_close_v1',
                formula_versions=['v1'], stream_id=identity.stream_id, since='2026-10-01', through='2026-10-30',
                computed_through='2026-10-30T07:00:00Z', trades=[], signals=[], actions=[], curve=[],
                summary=dict(total=0, closed=0, open=0, interrupted=0, wins=0, losses=0, flat=0, sum_return_percentage_points='0', mean_return_pct=None, win_rate_pct=None), page_parity=True, executable=False, auto_order=False)


def test_missing_read_never_creates_files(tmp_path):
    store = SnapshotStore(tmp_path / 'missing')
    with pytest.raises(SnapshotError, match='HTDY_SNAPSHOT_NOT_BUILT'):
        store.read('jm')
    assert not store.root.exists()


def test_snapshot_is_immutable_idempotent_and_restart_readable(tmp_path):
    store = SnapshotStore(tmp_path)
    first = store.publish(payload(), now=datetime(2026, 10, 30, tzinfo=UTC))
    same = store.publish(payload(), now=datetime(2026, 10, 31, tzinfo=UTC))
    assert first == same
    old_bytes = (tmp_path / f"{first['snapshot_id']}.json").read_bytes()
    second = store.publish(payload('b' * 64))
    assert first['snapshot_id'] != second['snapshot_id']
    restarted = SnapshotStore(tmp_path)
    assert restarted.read('jm')['snapshot_id'] == second['snapshot_id']
    assert restarted.read('jm', snapshot_id=first['snapshot_id'])['generated_at'] == first['generated_at']
    assert (tmp_path / f"{first['snapshot_id']}.json").read_bytes() == old_bytes


def test_hash_tamper_and_symlinks_are_rejected(tmp_path):
    store = SnapshotStore(tmp_path)
    first = store.publish(payload())
    path = tmp_path / f"{first['snapshot_id']}.json"
    value = json.loads(path.read_text())
    value['payload']['source_token'] = 'f' * 64
    path.write_text(json.dumps(value))
    with pytest.raises(SnapshotError, match='HTDY_SNAPSHOT_CORRUPT'):
        store.read('jm')
    path.unlink()
    path.symlink_to(tmp_path / 'target')
    with pytest.raises(SnapshotError):
        store.read('jm')


def test_symbol_scope_and_cursor_bind_snapshot(tmp_path):
    store = SnapshotStore(tmp_path)
    value = complete_payload()
    first = store.publish(value)
    page = store.read('jm', limit=1)
    assert [row['reference_trade_id'] for row in page['trades']] == ['t0']
    assert store.read('jm', snapshot_id=first['snapshot_id'], before=page['next_cursor'])['trades'] == [value['trades'][1]]
    other = deepcopy(value)
    other['source_token'] = 'b' * 64
    store.publish(other)
    with pytest.raises(SnapshotError, match='HTDY_SNAPSHOT_CURSOR_CONFLICT'):
        store.read('jm', before=page['next_cursor'])
    with pytest.raises(SnapshotError, match='HTDY_SNAPSHOT_SCOPE_MISMATCH'):
        store.read('i', snapshot_id=first['snapshot_id'])
    with pytest.raises(SnapshotError, match='HTDY_SNAPSHOT_INVALID_QUERY'):
        store.read('../jm')


def replay_packet():
    value = payload()
    value['summary'] = dict(total=2, closed=2, open=0, interrupted=0, wins=2, losses=0, flat=0, sum_return_percentage_points='30', mean_return_pct='15', win_rate_pct='100')
    from dataclasses import asdict, replace
    from app.reference_trading.htdy_history import history_identity
    stream = asdict(replace(history_identity('jm','60m'), formula_versions=('v1',)))
    stream['formula_versions'] = list(stream['formula_versions'])
    for index, result in enumerate(('10', '20')):
        start = f'2026-10-{index+1:02d}T01:00:00Z'
        end = f'2026-10-{index+1:02d}T02:00:00Z'
        value['trades'].append(dict(stream=deepcopy(stream), reference_trade_id=f't{index}', side='LONG', status='CLOSED',
            physical_contract='JM2701', owner_segment_id='owner', calculation_segment_id='calculation',
            entry_bar_end=start, exit_bar_end=end, entry_trading_day=start[:10], exit_trading_day=end[:10],
            entry_reference_price='100', exit_reference_price=str(100+int(result)),
            reference_return=result, entry_action_id=f'b{index}', exit_action_id=f'c{index}'))
        for instant, action, observation, price in ((start, f'b{index}', 'buy', '100'), (end, f'c{index}', 'sell', str(100+int(result)))):
            value['signals'].append(dict(bar_end=instant, trading_day=instant[:10], physical_contract='JM2701',
                segment_id='owner', calculation_segment_id='calculation', action_ids=[action],
                observation_types=[observation], reference_price=price))
    value['next_cursor'] = 'next'
    return value


def test_explicit_builder_freezes_full_paginated_replay_and_curve(tmp_path):
    from types import SimpleNamespace
    from app.market_data.subing_reference import SubingReferenceQuery
    from app.reference_trading.htdy_snapshot import build_snapshot
    complete = replay_packet()
    calls = []
    def query_history(_, query):
        calls.append(query)
        value = deepcopy(complete)
        value['trades'] = [complete['trades'][1 if query.before else 0]]
        value['next_cursor'] = None if query.before else 'next'
        return value
    service = SimpleNamespace(now=lambda: datetime(2026, 10, 31, tzinfo=UTC), check_cancelled=lambda: None)
    result = build_snapshot(service, SubingReferenceQuery('jm', frequency='60m'), store=SnapshotStore(tmp_path), query_history=query_history)
    assert len(calls) == 2 and calls[0].as_of == calls[1].as_of
    assert len(result['actions']) == 4
    assert [item['value'] for item in result['curve']] == ['10', '30']
    assert result['summary']['total'] == 2
    assert all(action['recording_mode'] == 'historical_replay' for action in result['actions'])


def test_changed_source_during_paging_does_not_publish(tmp_path):
    from types import SimpleNamespace
    from app.market_data.subing_reference import SubingReferenceQuery
    from app.reference_trading.htdy_snapshot import build_snapshot
    def query_history(_, query):
        value = replay_packet()
        value['trades'] = value['trades'][:1]
        if query.before:
            value['source_token'] = 'b' * 64
        return value
    service = SimpleNamespace(now=lambda: datetime(2026, 10, 31, tzinfo=UTC), check_cancelled=lambda: None)
    with pytest.raises(SnapshotError, match='HTDY_SNAPSHOT_SOURCE_CHANGED'):
        build_snapshot(service, SubingReferenceQuery('jm', frequency='60m'), store=SnapshotStore(tmp_path), query_history=query_history)
    assert not list(tmp_path.glob('*.json'))


def test_api_missing_snapshot_does_not_construct_market_service(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import market_subing_reference
    monkeypatch.setenv('GUIYI_HTDY_SNAPSHOT_ROOT', str(tmp_path / 'not-built'))
    monkeypatch.setattr(market_subing_reference, '_build_service', lambda *_: pytest.fail('GET invoked replay composition'))
    app = FastAPI()
    app.include_router(market_subing_reference.router)
    response = TestClient(app).get('/api/v1/market/jm/htdy/snapshot')
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'HTDY_SNAPSHOT_NOT_BUILT'
    assert not (tmp_path / 'not-built').exists()


def test_failed_latest_commit_preserves_old_snapshot_and_can_resume(tmp_path, monkeypatch):
    import os
    store = SnapshotStore(tmp_path)
    old = store.publish(payload())
    original = os.replace
    def fail(*args, **kwargs):
        raise OSError('private error is not returned')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(SnapshotError, match='HTDY_SNAPSHOT_CORRUPT'):
        store.publish(payload('b' * 64))
    assert store.read('jm')['snapshot_id'] == old['snapshot_id']
    assert not list(tmp_path.glob('*.tmp'))
    monkeypatch.setattr(os, 'replace', original)
    new = store.publish(payload('b' * 64))
    assert store.read('jm')['snapshot_id'] == new['snapshot_id']
    assert new['snapshot_id'] != old['snapshot_id']


def test_concurrent_publish_is_nonblocking_and_does_not_change_latest(tmp_path):
    import fcntl
    import os
    store = SnapshotStore(tmp_path)
    old = store.publish(payload())
    fd = os.open(tmp_path / 'jm.lock', os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SnapshotError, match='HTDY_SNAPSHOT_BUILD_BUSY'):
            store.publish(payload('b' * 64))
        assert store.read('jm')['snapshot_id'] == old['snapshot_id']
    finally:
        os.close(fd)


def complete_payload():
    from fastapi.encoders import jsonable_encoder
    from decimal import Decimal
    from app.reference_trading.htdy_snapshot import _expected_records
    value = replay_packet()
    actions, curve = _expected_records(value)
    value['actions'], value['curve'] = jsonable_encoder(actions, custom_encoder={Decimal:str}), curve
    return value


@pytest.mark.parametrize('field,value', [('sum_return_percentage_points','NaN'),('closed',99),('mean_return_pct','1')])
def test_snapshot_rejects_inconsistent_statistics(tmp_path, field, value):
    packet = complete_payload()
    packet['summary'][field] = value
    with pytest.raises(SnapshotError):
        SnapshotStore(tmp_path).publish(packet)


def test_snapshot_rejects_unpaired_actions_and_preserves_v1_curve(tmp_path):
    packet = complete_payload()
    assert 'segment' not in packet['curve'][0]
    assert SnapshotStore(tmp_path).publish(packet)['curve'] == packet['curve']
    packet['actions'][0]['reference_price'] = '999'
    with pytest.raises(SnapshotError):
        SnapshotStore(tmp_path).publish(packet)


@pytest.mark.parametrize('case', ['missing_entry', 'missing_exit', 'null_formula', 'empty_formula', 'wrong_direction'])
def test_rejects_missing_endpoint_signals_invalid_formula_and_wrong_direction(tmp_path, case):
    from app.reference_trading.htdy_snapshot import _validate
    packet = complete_payload()
    if case == 'missing_entry':
        packet['signals'] = packet['signals'][1:]
        packet['actions'] = packet['actions'][1:]
    elif case == 'missing_exit':
        packet['signals'] = packet['signals'][:-1]
        packet['actions'] = packet['actions'][:-1]
    elif case == 'null_formula':
        packet['formula_versions'] = [None]
    elif case == 'empty_formula':
        packet['formula_versions'] = [' ']
    else:
        packet['signals'][0]['observation_types'] = ['sell']
    with pytest.raises(SnapshotError):
        _validate(packet)


def test_publish_recovers_only_its_valid_same_inode_crash_temporary_link(tmp_path):
    import os
    from uuid import uuid4
    store = SnapshotStore(tmp_path)
    packet = complete_payload()
    original = store.publish(packet)
    final = tmp_path / f"{original['snapshot_id']}.json"
    before = final.read_bytes()
    temporary = tmp_path / f'.htdy-{uuid4().hex}.tmp'
    os.link(final, temporary)  # exact crash state after link(final), before unlink(temp)
    with pytest.raises(SnapshotError):
        store.read('jm')  # GET must never repair
    assert temporary.exists() and final.stat().st_nlink == 2
    unrelated = tmp_path / 'unrelated'
    unrelated.write_text('retain me')
    recovered = store.publish(packet)
    assert recovered == original and final.read_bytes() == before
    assert final.stat().st_nlink == 1 and not temporary.exists()
    assert unrelated.read_text() == 'retain me'
    assert store.read('jm')['snapshot_id'] == original['snapshot_id']


def test_recovery_refuses_unrecognized_link_name_and_invalid_content(tmp_path):
    import os
    store = SnapshotStore(tmp_path)
    packet = payload()
    original = store.publish(packet)
    final = tmp_path / f"{original['snapshot_id']}.json"
    unrelated = tmp_path / 'not-a-build-temp'
    os.link(final, unrelated)
    with pytest.raises(SnapshotError):
        store.publish(packet)
    assert unrelated.exists() and final.stat().st_nlink == 2


@pytest.mark.parametrize('field,value', [('formula_versions',['foreign']), ('frequency','15m'), ('product','I'), ('reference_model_version','foreign')])
def test_snapshot_trade_stream_cannot_be_wrapped_as_another_identity(tmp_path, field, value):
    packet = complete_payload()
    packet['trades'][0]['stream'][field] = value
    with pytest.raises(SnapshotError):
        SnapshotStore(tmp_path).publish(packet)


def test_unlink_failure_always_releases_lock_and_allows_explicit_recovery(tmp_path, monkeypatch):
    import os
    store = SnapshotStore(tmp_path)
    old = store.publish(payload())
    original = os.unlink
    def fail(name, *args, **kwargs):
        if str(name).startswith('.htdy-'):
            raise OSError('private cleanup failure')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(os, 'unlink', fail)
    with pytest.raises(SnapshotError, match='HTDY_SNAPSHOT_CORRUPT'):
        store.publish(payload('b' * 64))
    assert store.read('jm')['snapshot_id'] == old['snapshot_id']
    monkeypatch.setattr(os, 'unlink', original)
    new = store.publish(payload('b' * 64))  # must not leak a BUILD_BUSY lock
    assert new['snapshot_id'] != old['snapshot_id']
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('field,value', [('exit','2026-09-30'), ('exit','2026-10-31'), ('signal','2026-10-05'), ('signal','invalid')])
def test_rejects_exit_dates_outside_window_and_signal_trade_day_mismatch(tmp_path, field, value):
    packet = complete_payload()
    if field == 'exit':
        packet['trades'][0]['exit_trading_day'] = value
        packet['signals'][1]['trading_day'] = value
        packet['actions'][1]['trading_day'] = value
    else:
        packet['signals'][0]['trading_day'] = value
    with pytest.raises(SnapshotError):
        SnapshotStore(tmp_path).publish(packet)
