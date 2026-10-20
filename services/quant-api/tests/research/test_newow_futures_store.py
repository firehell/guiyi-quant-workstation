import hashlib
import json
import os

import pytest

from guiyi_quant.newow_futures.contracts import Profile, Variant, profile_payload
from app.newow_futures_research.store import ResultStoreError, publish_packet, read_packet, list_results


def packet(status='COMPLETED'):
    meta = dict(profile_payload(Profile(Variant.TREND, '5m')))
    meta.update(product='JM', scenario='baseline', status=status, code_revision='a' * 40,
                requested_since='2024-10-14', requested_through='2026-10-19',
                input_snapshot_hash='b' * 64, execution_facts_hash='c' * 64,
                as_of='2026-10-20T10:00:00+08:00', source='historical_replay')
    return {'schema_version': 1, 'metadata': meta,
            'summary': {'status': status, 'initial_cash': '100000', 'final_equity': '100001',
                        'account_return_pct': '0.001', 'closed_trades': 0},
            'reference': {'summary': {'status': 'COMPLETED', 'executable': False},
                          'snapshot': {'state': 'FLAT'}, 'actions': [], 'trades': [], 'equity': []},
            'chart': {'bars': [], 'frames': []}, 'decisions': [], 'fills': [], 'trades': [],
            'equity': [], 'diagnostics': {}}


def test_publish_roundtrip_stable_identity_and_file_hash(tmp_path):
    result = publish_packet(tmp_path, packet())
    assert len(result['run_id']) == len(result['sha256']) == 64
    assert result['sha256'] == hashlib.sha256((tmp_path / f"{result['run_id']}.json").read_bytes()).hexdigest()
    assert read_packet(tmp_path, result['run_id'])['metadata']['product'] == 'JM'
    assert list_results(tmp_path)[0]['run_id'] == result['run_id']
    assert publish_packet(tmp_path, packet()) == result
    changed = packet()
    changed['summary']['final_equity'] = '100002'
    with pytest.raises(ResultStoreError, match='RESULT_CONFLICT'):
        publish_packet(tmp_path, changed)


@pytest.mark.parametrize('field,value', [('strategy_model', 'old'), ('initial_cash', '1000000'),
    ('profile_id', 'bad'), ('auto_order', True), ('as_of', '2026-01-01'), ('frequency', '1m'),
    ('product', 'CU'), ('oos_status', 'PROVEN'), ('requested_since', '2025-01-01'),
    ('execution_facts_hash', None), ('code_revision', ''), ('status', 'UNKNOWN')])
def test_reject_invalid_metadata(tmp_path, field, value):
    p = packet()
    p['metadata'][field] = value
    with pytest.raises(ResultStoreError):
        publish_packet(tmp_path, p)


def test_blocked_preserves_reference_without_claiming_account_success(tmp_path):
    p = packet('EXECUTION_FACTS_MISSING')
    p['metadata']['execution_facts_hash'] = None
    p['summary'].update(final_equity=None, account_return_pct=None)
    p['reference']['trades'] = [{'id': 'ref', 'side': 'LONG'}]
    stored = publish_packet(tmp_path, p)
    assert read_packet(tmp_path, stored['run_id'])['reference']['trades'][0]['id'] == 'ref'
    p['summary']['final_equity'] = '100001'
    with pytest.raises(ResultStoreError):
        publish_packet(tmp_path, p)


def test_no_higher_weekly_level_is_disclosed_without_fabricated_account_return(tmp_path):
    p = packet('NOT_APPLICABLE')
    p['metadata'].update(dict(profile_payload(Profile(Variant.TEST3, '1w'))))
    p['metadata'].update(input_snapshot_hash=None, execution_facts_hash=None)
    p['summary'].update(final_equity=None, account_return_pct=None)
    result = publish_packet(tmp_path, p)
    assert read_packet(tmp_path, result['run_id'])['metadata']['status'] == 'NOT_APPLICABLE'


@pytest.mark.parametrize('rows', [[{}], [{'at': '2026-10-19T00:00:00+00:00'}],
    [{'at': '2026-10-19T00:00:00+00:00', 'value': 'NaN'}],
    [{'at': '2026-10-19T00:00:00+00:00', 'value': '100'}, {'at': '2026-10-19T00:00:00+00:00', 'value': '101'}]])
@pytest.mark.parametrize('kind', ['equity', 'reference'])
def test_curve_requires_time_value_and_strict_source_order(tmp_path, rows, kind):
    p = packet()
    if kind == 'equity':
        p['equity'] = rows
    else:
        p['reference']['equity'] = rows
    with pytest.raises(ResultStoreError, match='RESULT_SCHEMA_INVALID'):
        publish_packet(tmp_path, p)


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'tamper', 'index_identity'])
def test_unsafe_or_corrupt_indexed_file_fails_closed(tmp_path, kind):
    result = publish_packet(tmp_path, packet())
    path = tmp_path / f"{result['run_id']}.json"
    if kind == 'symlink':
        raw = path.read_bytes()
        path.unlink()
        other = tmp_path / 'other.json'
        other.write_bytes(raw)
        path.symlink_to(other)
    elif kind == 'fifo':
        path.unlink()
        os.mkfifo(path)
    elif kind == 'tamper':
        path.write_text('{}')
    else:
        index = json.loads((tmp_path / 'index.json').read_text())
        index['runs'][0]['metadata']['product'] = 'RB'
        (tmp_path / 'index.json').write_text(json.dumps(index))
    with pytest.raises(ResultStoreError):
        read_packet(tmp_path, result['run_id'])
    with pytest.raises(ResultStoreError):
        list_results(tmp_path)


def test_reject_symlink_root_and_relative_root(tmp_path):
    root = tmp_path / 'link'
    root.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ResultStoreError):
        list_results(root)
    with pytest.raises(ResultStoreError):
        list_results(type(tmp_path)('relative'))


def test_strict_numbers_and_json_duplicate_keys(tmp_path):
    p = packet()
    p['summary']['final_equity'] = float('nan')
    with pytest.raises(ResultStoreError):
        publish_packet(tmp_path, p)
    p = packet()
    p['chart']['bars'] = [{'close': 1.5}]
    with pytest.raises(ResultStoreError):
        publish_packet(tmp_path, p)


@pytest.mark.parametrize('target,kind', [('index.json', 'symlink'), ('index.json', 'fifo'),
                                         ('.index.lock', 'symlink'), ('.index.lock', 'fifo')])
def test_unsafe_index_and_lock_rejected_without_blocking(tmp_path, target, kind):
    path = tmp_path / target
    if kind == 'fifo':
        os.mkfifo(path)
    else:
        other = tmp_path / 'other'
        other.write_text('{}')
        path.symlink_to(other)
    with pytest.raises(ResultStoreError):
        publish_packet(tmp_path, packet())


@pytest.mark.parametrize('round_number', range(20))
def test_concurrent_publications_retain_complete_index(tmp_path, round_number):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    packets = [packet() for _ in range(8)]
    barrier = Barrier(len(packets))
    for i, item in enumerate(packets):
        item['metadata']['as_of'] = f'2026-10-20T10:00:0{i}+08:00'

    def publish_together(item):
        # Exercise the first lock-file creation race, rather than only flock contention.
        barrier.wait(timeout=10)
        return publish_packet(tmp_path, item)

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(publish_together, packets))
    assert {item['run_id'] for item in list_results(tmp_path)} == {item['run_id'] for item in receipts}


def test_exact_orphan_recovery_and_no_glob_discovery(tmp_path):
    receipt = publish_packet(tmp_path, packet())
    (tmp_path / 'index.json').unlink()
    assert list_results(tmp_path) == []
    with pytest.raises(ResultStoreError, match='RESULT_NOT_FOUND'):
        read_packet(tmp_path, receipt['run_id'])
    assert publish_packet(tmp_path, packet()) == receipt


def test_max_file_and_index_sizes_are_enforced(tmp_path, monkeypatch):
    import app.newow_futures_research.store as store
    receipt = publish_packet(tmp_path, packet())
    monkeypatch.setattr(store, 'MAX_INDEX_BYTES', 10)
    with pytest.raises(ResultStoreError, match='RESULT_TOO_LARGE'):
        read_packet(tmp_path, receipt['run_id'])


@pytest.mark.parametrize('field,value', [('at', '2026-10-20T10:00:00'), ('price', 12),
                                         ('price', 'NaN'), ('price', 'Infinity')])
def test_record_times_and_money_are_typed(tmp_path, field, value):
    p = packet()
    p['fills'] = [{field: value}]
    with pytest.raises(ResultStoreError, match='RESULT_SCHEMA_INVALID'):
        publish_packet(tmp_path, p)


def test_cross_process_publications_retain_complete_index(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import subprocess
    import sys

    script = (
        'import json,sys; from pathlib import Path; '
        'from app.newow_futures_research.store import publish_packet; '
        'print(json.dumps(publish_packet(Path(sys.argv[1]), json.load(sys.stdin))))'
    )
    processes = [subprocess.Popen([sys.executable, '-c', script, str(tmp_path)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True) for _ in range(4)]
    packets = [packet() for _ in processes]
    for i, payload in enumerate(packets):
        payload['metadata']['as_of'] = f'2026-10-20T12:00:0{i}+08:00'

    def finish(pair):
        process, payload = pair
        stdout, stderr = process.communicate(json.dumps(payload), timeout=15)
        assert process.returncode == 0, stderr
        return json.loads(stdout)

    try:
        with ThreadPoolExecutor(max_workers=len(processes)) as pool:
            receipts = list(pool.map(finish, zip(processes, packets)))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()
    assert {item['run_id'] for item in list_results(tmp_path)} == {item['run_id'] for item in receipts}
