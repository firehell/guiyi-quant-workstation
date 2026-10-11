"""Lossless control storage never changes a frozen historical plan or its status."""
import base64
import copy
from hashlib import sha256
import json
import zlib

import pytest

from app.reference_trading.refresh_plan_codec import (
    RefreshPlanCodecError, decode_plan, encode_plan, validate_encoded_plan,
)
from app.reference_trading.historical_refresh import RefreshStateStore
from app.reference_trading.planning import plan_to_dict, plan_from_dict
from tests.reference_trading.test_historical_refresh import Planner, route, END, setup
from app.reference_trading.planning import HistoricalReferenceRequest, HistoricalStreamRequest
from app.reference_trading.historical_refresh import BUDGET


def plan():
    item = route()
    return plan_to_dict(Planner().plan(HistoricalReferenceRequest('advance', (
        HistoricalStreamRequest(item.identity, item.since, END.date(), END),), BUDGET)))


def test_roundtrip_full_frozen_plan_and_hash():
    original = plan()
    encoded = encode_plan(original)
    assert encoded != original
    assert decode_plan(encoded) == original
    assert plan_from_dict(decode_plan(encoded)).plan_hash == original['plan_hash']
    assert original == plan()


def test_legacy_plan_is_still_accepted():
    original = plan()
    assert decode_plan(original) == original


def test_storage_preserves_unknown_status_and_resume_without_decoding(tmp_path, monkeypatch):
    import app.reference_trading.refresh_plan_codec as codec
    value = {'version': 'newow_historical_refresh_v1', 'cursor': 'stream', 'routes': {
        'stream': {'status': 'blocked', 'reason': 'COMMIT_OUTCOME_UNKNOWN', 'plan': plan(),
                   'resume': {'identity': 'unchanged'}},
        'other': {'status': 'blocked', 'reason': 'REFRESH_STATE_BUDGET_EXCEEDED'}}}
    before = copy.deepcopy(value)
    store = RefreshStateStore(tmp_path / 'refresh.json')
    store.write(value)
    monkeypatch.setattr(codec, 'decode_plan', lambda _: pytest.fail('decode unselected plan'))
    stored = store.read()
    assert value == before
    assert stored['routes']['stream']['status'] == 'blocked'
    assert stored['routes']['stream']['reason'] == 'COMMIT_OUTCOME_UNKNOWN'
    assert stored['routes']['stream']['resume'] == {'identity': 'unchanged'}
    assert stored['routes']['other'] == value['routes']['other']
    validate_encoded_plan(stored['routes']['stream']['plan'])


@pytest.mark.parametrize('change', ['base64', 'digest', 'size', 'extra', 'bool_size', 'codec'])
def test_envelope_corruption_rejected(change):
    value = encode_plan(plan())
    if change == 'base64':
        value['payload'] = '!'
    elif change == 'digest':
        value['compressed_sha256'] = '0' * 64
    elif change == 'size':
        value['decoded_bytes'] -= 1
    elif change == 'extra':
        value['extra'] = True
    elif change == 'bool_size':
        value['decoded_bytes'] = True
    else:
        value['codec'] = 'unknown'
    with pytest.raises(RefreshPlanCodecError):
        decode_plan(value)


@pytest.mark.parametrize('suffix', [b'tail', zlib.compress(b'{}')])
def test_trailing_or_second_compressed_stream_rejected(suffix):
    value = encode_plan(plan())
    raw = base64.b64decode(value['payload']) + suffix
    value.update(payload=base64.b64encode(raw).decode(), compressed_sha256=sha256(raw).hexdigest())
    with pytest.raises(RefreshPlanCodecError):
        decode_plan(value)


def test_zipbomb_declared_short_length_rejected():
    value = encode_plan(plan())
    raw = zlib.compress(b'x' * 1_000_000)
    value.update(payload=base64.b64encode(raw).decode(), compressed_sha256=sha256(raw).hexdigest(), decoded_bytes=10)
    with pytest.raises(RefreshPlanCodecError):
        decode_plan(value)


def test_truncated_stream_and_plain_hash_drift_rejected():
    value = encode_plan(plan())
    value['decoded_sha256'] = '0' * 64
    with pytest.raises(RefreshPlanCodecError):
        decode_plan(value)
    value = encode_plan(plan())
    raw = base64.b64decode(value['payload'])[:-2]
    value.update(payload=base64.b64encode(raw).decode(), compressed_sha256=sha256(raw).hexdigest())
    with pytest.raises(RefreshPlanCodecError):
        decode_plan(value)


def test_frozen_manifest_tamper_cannot_bypass_plan_hash():
    value = plan()
    value['streams'][0]['source_token'] = 'different'
    with pytest.raises(ValueError, match='REFERENCE_PLAN_HASH_CONFLICT'):
        plan_from_dict(decode_plan(encode_plan(value)))


def test_selected_pending_plan_runs_and_blocked_capacity_does_not_retry(tmp_path):
    runner, planner, service = setup(tmp_path, [('blocked', 'REBUILD_REQUIRED', False), ('completed', None, False)])
    runner.tick(now=END)
    assert 'codec' in runner.state.read()['routes'][route().identity.stream_id]['plan']
    runner.tick(now=END)
    assert [call[0] for call in service.calls] == ['advance', 'rebuild']
    runner.state.write({'version': 'newow_historical_refresh_v1', 'cursor': '', 'routes': {
        route().identity.stream_id: {'status': 'blocked', 'reason': 'REFRESH_STATE_BUDGET_EXCEEDED'}}})
    runner.tick(now=END)
    assert len(service.calls) == 2


def test_many_large_plans_fit_existing_file_budget(tmp_path):
    value = plan()
    value['streams'][0]['input_manifest']['repeated'] = ['proof-' + str(i % 500) for i in range(5000)]
    store = RefreshStateStore(tmp_path / 'refresh.json')
    routes = {str(i): {'status': 'pending', 'reason': 'REBUILD_REQUIRED', 'plan': value} for i in range(720)}
    state = {'version': 'newow_historical_refresh_v1', 'cursor': '', 'routes': routes}
    assert len(json.dumps(state).encode()) > 40_000_000
    store.write(state)
    assert store.path.stat().st_size < 10_000_000
    assert len(store.read()['routes']) == 720


@pytest.mark.parametrize('failure', ['budget', 'temporary_open'])
def test_committed_callback_storage_failure_retains_durable_inflight_and_no_retry(tmp_path, monkeypatch, failure):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import os
    from app.reference_trading.historical_refresh import RefreshStateError
    from app.reference_trading.service import ResumeToken
    runner, planner, service = setup(tmp_path, [])
    committed = []
    real_write = runner.state.write
    real_open = os.open
    if failure == 'budget':
        def write(value):
            if any('resume' in item for item in value['routes'].values()):
                raise RefreshStateError('REFRESH_STATE_BUDGET_EXCEEDED')
            real_write(value)
        monkeypatch.setattr(runner.state, 'write', write)
    else:
        def open_file(path, *args, **kwargs):
            if committed and str(path).endswith('.tmp'):
                raise OSError('isolated write failure')
            return real_open(path, *args, **kwargs)
        monkeypatch.setattr(os, 'open', open_file)
    @contextmanager
    def components(**kwargs):
        def advance(plan, _expected):
            committed.append(plan.plan_hash)
            token = ResumeToken(plan.plan_hash, plan.streams[0].request.identity.stream_id,
                                'revision', 1, plan.streams[0].source_token, 'batch')
            kwargs['after_batch']('committed', {'resume_token': token})
            pytest.fail('callback storage failure must stop')
        yield planner, SimpleNamespace(advance=advance)
    runner._components = components
    with pytest.raises(RefreshStateError):
        runner.tick(now=END)
    saved = runner.state.read()['routes'][route().identity.stream_id]
    assert saved['status'] == 'inflight' and 'plan' in saved and 'resume' not in saved
    assert plan_from_dict(decode_plan(saved['plan'])).plan_hash == committed[0]
    # Only the existing readback-required transition occurs; service never retries.
    committed_before = list(committed)
    if failure == 'temporary_open':
        monkeypatch.setattr(os, 'open', real_open)
    runner.tick(now=END)
    assert committed == committed_before
    assert runner.state.read()['routes'][route().identity.stream_id]['reason'] == 'REFRESH_READBACK_REQUIRED'


def test_invalid_decoded_plan_retains_original_pending_evidence(tmp_path):
    runner, _, service = setup(tmp_path, [])
    value = plan()
    value['plan_hash'] = '0' * 64
    runner.state.write({'version': 'newow_historical_refresh_v1', 'cursor': '', 'routes': {
        route().identity.stream_id: {'status': 'pending', 'reason': 'REBUILD_REQUIRED', 'plan': value}}})
    before = runner.state.path.read_bytes()
    from app.reference_trading.historical_refresh import RefreshStateError
    with pytest.raises(RefreshStateError, match='REFRESH_PLAN_READBACK_REQUIRED'):
        runner.tick(now=END)
    saved = runner.state.read()['routes'][route().identity.stream_id]
    assert saved['status'] == 'pending' and decode_plan(saved['plan']) == value
    assert runner.state.path.read_bytes() == before
    assert not service.calls


@pytest.mark.parametrize('cleanup_failure', [False, True])
def test_real_service_failure_isolation_cannot_swallow_committed_storage_error(tmp_path, monkeypatch, cleanup_failure):
    from contextlib import contextmanager
    from app.reference_trading.historical_refresh import RefreshStateError
    from app.reference_trading.service import HistoricalReferenceService, ResumeToken
    runner, planner, _ = setup(tmp_path, [])
    writes_after_failure = []
    committed = []
    real_write = runner.state.write
    failed = False
    def write(value):
        nonlocal failed
        if any('resume' in item for item in value['routes'].values()) and not failed:
            failed = True
            raise RefreshStateError('REFRESH_STATE_BUDGET_EXCEEDED')
        if failed:
            writes_after_failure.append(value)
        real_write(value)
    monkeypatch.setattr(runner.state, 'write', write)
    @contextmanager
    def components(**kwargs):
        service = HistoricalReferenceService.__new__(HistoricalReferenceService)
        service._clock = lambda: 0
        def commit(plan, item, _deadline):
            committed.append(plan.plan_hash)
            token = ResumeToken(plan.plan_hash, item.request.identity.stream_id,
                                'revision', 1, item.source_token, 'batch')
            kwargs['after_batch']('committed', {'resume_token': token})
            pytest.fail('expected callback storage failure')
        service._advance_stream = commit
        try:
            yield planner, service
        finally:
            if cleanup_failure:
                raise OSError('isolated lease cleanup failure')
    runner._components = components
    with pytest.raises(RefreshStateError, match='REFRESH_STATE_BUDGET_EXCEEDED'):
        runner.tick(now=END)
    assert len(committed) == 1 and writes_after_failure == []
    assert runner.state.read()['routes'][route().identity.stream_id]['status'] == 'inflight'
