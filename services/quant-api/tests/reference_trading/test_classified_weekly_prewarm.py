"""A proved source interruption is not a computed Reference result."""
from contextlib import contextmanager
from datetime import UTC, datetime
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.market_data.domain import ResolvedContractSegment
from app.market_data.weekly_quality import WeeklySourceInterruption
from app.reference_trading import worker_entry
from app.reference_trading.forward_inputs import ForwardInputUnavailable
from tests.reference_trading.test_subing_six_period_capture import identity as base_identity

END = datetime(2026, 10, 30, 7, tzinfo=UTC)


def identity(period):
    return replace(base_identity(period), observation_policy_version='subing_physical_prefix_forward_v2')


def source(*, fault=None):
    gap = WeeklySourceInterruption('rb', 'RB2701', 2026, 44, END,
        ((END, END.date()),), (END.date(),), (('quality', 'a'*64),), 'b'*64,
        'source', 'weekly-d1-quality-v2', ('PRICE_UNAVAILABLE',))
    if fault == 'identity':
        gap = replace(gap, physical_contract='RB2601')
    gaps = () if fault == 'missing' else (gap,)
    owner = ResolvedContractSegment('RB2701', END.date(), END.date())
    market = SimpleNamespace(
        actual_dominant_segments=lambda *_: (owner,),
        expected_contract_replay_endpoints=lambda **_: ((END, END.date()),),
        query_contract_weekly_replay_quality=lambda **_: ((), gaps),
        query_actual_dominant_trading_days_quality=lambda *a, **k: (
            SimpleNamespace(bars=(), request_identity={'symbol':'rb','series_kind':'actual_dominant','contract':None,'frequency':'1w'},
                requested_trading_day_window=(END.date(), END.date())), (('RB2701', gap),)),
    )
    return SimpleNamespace(market_data=market,
        _session_windows=lambda *_: (SimpleNamespace(end=END),))


def test_complete_quality_union_proves_unavailable_without_a_price_or_trade():
    from app.reference_trading.prewarm_quality import prove_weekly_unavailable
    proof = prove_weekly_unavailable(source(), identity('1w'),
        since=END.date(), through=END.date(), cutoff=END)
    assert proof['status'] == 'DATA_UNAVAILABLE'
    assert proof['stream_id'] == identity('1w').stream_id
    assert proof['quality_interruptions'] == 1
    assert proof['contracts'][0]['expected_count'] == 1
    assert len(proof['source_sha256']) == 64


@pytest.mark.parametrize('fault', ['missing', 'identity'])
def test_incomplete_or_wrong_contract_quality_union_still_blocks(fault):
    from app.reference_trading.prewarm_quality import prove_weekly_unavailable
    with pytest.raises(ValueError, match='REFERENCE_WEEKLY_QUALITY_UNPROVEN'):
        prove_weekly_unavailable(source(fault=fault), identity('1w'),
            since=END.date(), through=END.date(), cutoff=END)


def test_quality_preflight_rejects_nonweekly_or_non_subing_identity():
    from app.reference_trading.prewarm_quality import prove_weekly_unavailable
    with pytest.raises(ValueError, match='REFERENCE_WEEKLY_QUALITY_UNPROVEN'):
        prove_weekly_unavailable(source(), identity('1d'),
            since=END.date(), through=END.date(), cutoff=END)


def test_rank1_conflict_is_not_exempted():
    from app.reference_trading.prewarm_quality import prove_weekly_unavailable
    s = source()
    s.market_data.query_actual_dominant_trading_days_quality = lambda *a, **k: (
        SimpleNamespace(bars=(), request_identity={'symbol': 'cu'},
            requested_trading_day_window=(END.date(), END.date())), ())
    with pytest.raises(ValueError, match='REFERENCE_WEEKLY_QUALITY_UNPROVEN'):
        prove_weekly_unavailable(s, identity('1w'), since=END.date(), through=END.date(), cutoff=END)


@pytest.mark.parametrize('enabled', [False, True])
def test_capture_proves_only_explicit_weekly_data_unavailable(enabled):
    from app.market_data.subing_reference import SubingReferenceError
    from app.reference_trading.forward_inputs import capture_subing_canonical
    from app.reference_trading.prewarm_quality import ClassifiedWeeklyUnavailable
    s = source()
    s.resolve_forward_read_window = lambda _: (END.date(), END.date(), END, END)
    def unavailable(**_):
        raise SubingReferenceError('SUBING_REFERENCE_DATA_UNAVAILABLE')
    s.load_historical_inputs = unavailable
    with pytest.raises(ForwardInputUnavailable) as caught:
        capture_subing_canonical(s, identity('1w'), revision_id='r', generation=1,
            after=None, recording_start=END, now=END, prove_classified_weekly_unavailable=enabled)
    assert isinstance(caught.value, ClassifiedWeeklyUnavailable) is enabled


@pytest.mark.parametrize('pending', [False, True])
def test_unknown_or_pending_original_failure_still_blocks(monkeypatch, pending):
    stream = identity('1w')
    def fail(*_):
        raise ForwardInputUnavailable('SUBING_REFERENCE_DATA_UNAVAILABLE')
    repo = SimpleNamespace(read_pending_capture=lambda _: ('original', {}) if pending else None,
        forward_source_context=lambda _: (stream,), load_checkpoint=lambda _: ('token', 'checkpoint'))
    worker = SimpleNamespace(_repository=repo, scan_live=False,
        _enabled_keys=lambda **k: ('key',) if k['after'] is None else (),
        _work_routes=lambda _: (stream.stream_id,), _begin_unit=lambda: None, _end_unit=lambda: None,
        _service_for=lambda _: SimpleNamespace(_evaluator=fail), _read_input=fail)
    @contextmanager
    def opened(**_):
        yield worker, None, None
    monkeypatch.setattr(worker_entry, 'open_forward_worker', opened)
    with pytest.raises(ForwardInputUnavailable):
        worker_entry.warmup_reference_worker(allow_classified_weekly_unavailable=True)


@pytest.mark.parametrize('enabled', [False, True])
def test_only_explicit_deployment_warmup_records_classified_route(monkeypatch, enabled):
    from app.reference_trading.prewarm_quality import ClassifiedWeeklyUnavailable, prove_weekly_unavailable
    stream = identity('1w')
    proof = prove_weekly_unavailable(source(), stream, since=END.date(), through=END.date(), cutoff=END)
    reads, evaluated = [], []
    repository = SimpleNamespace(read_pending_capture=lambda _: None,
        forward_source_context=lambda _: (stream,), load_checkpoint=lambda _: ('token', 'checkpoint'))
    def read(*_):
        reads.append(True)
        raise ClassifiedWeeklyUnavailable(proof)
    worker = SimpleNamespace(_repository=repository, scan_live=False,
        _enabled_keys=lambda **k: ('key',) if k['after'] is None else (),
        _work_routes=lambda _: (stream.stream_id,), _begin_unit=lambda: None, _end_unit=lambda: None,
        _service_for=lambda _: SimpleNamespace(_evaluator=lambda *a: evaluated.append(a)), _read_input=read)
    @contextmanager
    def opened(**_):
        yield worker, None, None
    monkeypatch.setattr(worker_entry, 'open_forward_worker', opened)
    monkeypatch.setattr(worker_entry, '_warmup_saved_capture', lambda *a: 'initialized')
    if not enabled:
        with pytest.raises(ForwardInputUnavailable):
            worker_entry.warmup_reference_worker()
    else:
        result = worker_entry.warmup_reference_worker(allow_classified_weekly_unavailable=True)
        assert result['calculated'] == 0
        assert result['unavailable'] == [proof]
    assert not evaluated and len(reads) == 1


def test_classified_source_does_not_exempt_corrupt_saved_original(monkeypatch):
    from app.reference_trading.prewarm_quality import ClassifiedWeeklyUnavailable, prove_weekly_unavailable
    stream = identity('1w')
    proof = prove_weekly_unavailable(source(), stream, since=END.date(), through=END.date(), cutoff=END)
    def fail_read(*_):
        raise ClassifiedWeeklyUnavailable(proof)
    def corrupt(*_):
        raise RuntimeError('REFERENCE_WARMUP_CAPTURE_CONFLICT')
    repo = SimpleNamespace(read_pending_capture=lambda _: None,
        forward_source_context=lambda _: (stream,), load_checkpoint=lambda _: ('token', 'checkpoint'))
    worker = SimpleNamespace(_repository=repo, scan_live=False,
        _enabled_keys=lambda **k: ('key',) if k['after'] is None else (),
        _work_routes=lambda _: (stream.stream_id,), _begin_unit=lambda: None, _end_unit=lambda: None,
        _service_for=lambda _: object(), _read_input=fail_read)
    @contextmanager
    def opened(**_):
        yield worker, None, None
    monkeypatch.setattr(worker_entry, 'open_forward_worker', opened)
    monkeypatch.setattr(worker_entry, '_warmup_saved_capture', corrupt)
    with pytest.raises(RuntimeError, match='REFERENCE_WARMUP_CAPTURE_CONFLICT'):
        worker_entry.warmup_reference_worker(allow_classified_weekly_unavailable=True)
