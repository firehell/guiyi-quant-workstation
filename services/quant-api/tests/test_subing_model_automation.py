from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.subing_model.store import digest
from app.subing_model_recovery import POLICY, apply_event, flat_without_obligations
from app.subing_model_service import capture_slot
from test_subing_model_pipeline import pipeline, row, AT


def recovery_event(p):
    bars = {}
    for freq in ('1m', '30m', '60m', '1d'):
        raw = row('jm', freq)['data']
        bars[freq] = [raw]
    return dict(event_id='recovery:1', recovery_policy=POLICY,
        observed_at=(AT + timedelta(hours=1)).isoformat(), source_day='2026-11-05',
        cursor='10-0', account_can_resume=True,
        products={'jm': dict(contract='JM2701', bars=bars,
            proofs={f: dict(hash=digest(v)) for f, v in bars.items()})})


def empty_pipe():
    p = pipeline()
    p.account = None
    p.sequence = 0
    p.source_day = '2026-11-04'
    p.source_cursor = '0-0'
    return p


def test_canonical_catchup_never_executes_and_replays_identically():
    p = empty_pipe()
    event = recovery_event(p)
    apply_event(p, event)
    assert p.account is None
    assert p.products['jm']['source_kind'] == 'CANONICAL_INDICATOR_RECOVERY'
    assert not p.products['jm']['execution_enabled']
    assert p.last_outcome['model_fills'] == p.last_outcome['model_decisions'] == []
    assert p.products['jm']['bar_end'] == AT.isoformat()
    q = empty_pipe()
    apply_event(q, dict(event, outcome=deepcopy(p.last_outcome)))
    assert q.state() == p.state()


def test_future_or_corrupt_catchup_rejected():
    p = empty_pipe()
    e = recovery_event(p)
    e['observed_at'] = (AT - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match='FUTURE_BAR'):
        apply_event(p, e)
    p = empty_pipe()
    e = recovery_event(p)
    e['products']['jm']['proofs']['1m']['hash'] = 'bad'
    with pytest.raises(ValueError, match='MINUTES_INVALID'):
        apply_event(p, e)


@pytest.mark.parametrize('attribute', ['layers', 'pending', 'clear_reasons', 'exit_layers', 'day_halted', 'pullback'])
def test_exposure_or_obligation_never_auto_resumes(attribute):
    m = SimpleNamespace(layers=[], pending=None, clear_reasons=[], exit_layers=[], day_halted=False, pullback=None)
    setattr(m, attribute, True)
    a = SimpleNamespace(halted=None, protection_observation=None, engine=SimpleNamespace(layers={}, model=m))
    assert not flat_without_obligations(a)


def test_latched_failure_does_not_clear_even_when_flat():
    a = SimpleNamespace(halted='DAILY_FACTS_INTERRUPTED_REVIEW_REQUIRED', protection_observation=None, engine=None)
    assert not flat_without_obligations(a)


def test_provider_slots_are_session_bounded_and_finite():
    first = datetime(2026, 11, 6, 13, tzinfo=UTC)
    end = first + timedelta(hours=6)
    assert capture_slot(first, first, end) is None
    assert capture_slot(first + timedelta(minutes=1), first, end) == 0
    assert capture_slot(first + timedelta(minutes=5), first, end) == 1
    assert capture_slot(first + timedelta(minutes=20), first, end) == 2
    assert capture_slot(end + timedelta(seconds=1), first, end) is None


def test_unknown_policy_or_account_state_drift_is_not_accepted():
    e = recovery_event(empty_pipe())
    e['recovery_policy'] = 'invented'
    with pytest.raises(ValueError, match='POLICY_UNKNOWN'):
        apply_event(empty_pipe(), e)
    e['recovery_policy'] = POLICY
    e['account_can_resume'] = False
    with pytest.raises(ValueError, match='ACCOUNT_DRIFT'):
        apply_event(empty_pipe(), e)


@pytest.mark.parametrize('frequency', ['1m', '30m', '60m', '1d'])
def test_entire_consumed_overlap_rejects_older_revision(frequency):
    from app.subing_model.pipeline import bar
    from app.subing_model_recovery import verify_overlap
    from dataclasses import replace
    from decimal import Decimal
    old = bar(row('jm', frequency, AT - timedelta(hours=1))['data'])
    last = bar(row('jm', frequency, AT)['data'])
    with pytest.raises(ValueError, match='PRIOR_CONFLICT'):
        verify_overlap({old.bar_end: old, last.bar_end: last},
                       [replace(old, volume=Decimal('11')), last])
    verify_overlap({old.bar_end: old, last.bar_end: last}, [old, last])


def test_processing_knowledge_time_is_after_fact_capture(monkeypatch):
    import app.subing_model_service as module
    from datetime import date
    times = iter([AT, AT + timedelta(minutes=2)])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    monkeypatch.setattr(module, 'datetime', Clock)
    day = date(2026, 11, 5)
    pipe = SimpleNamespace(source_day=str(day), source_cursor='0-0')
    service = module.Service.__new__(module.Service)
    service.pipe = pipe
    service.check_code = lambda: None
    service.stream = SimpleNamespace(days=lambda: [day])
    service.context = lambda d: {'jm': {'day_end': (AT + timedelta(hours=6)).isoformat()}}
    service.recovery = lambda *args: False
    captured = AT + timedelta(minutes=1)
    service.facts = lambda *args: {'captured_at': captured.isoformat()}
    service.daily_pending = service.daily_proofs = service.daily_errors = {}
    service.daily_inputs = lambda *args: None
    monkeypatch.setattr(module.worker, 'read_rows', lambda *args: ([{'confirmed_at': AT.isoformat()}], '1-0'))
    payloads = []
    service.commit = payloads.append
    assert service.tick() == 'RUNNING'
    assert datetime.fromisoformat(payloads[0]['observed_at']) > captured


def test_old_day_tail_is_recovered_before_attempting_new_session():
    from app.subing_model_service import Service
    from datetime import date
    old, latest = date(2026, 11, 5), date(2026, 11, 6)
    service = Service.__new__(Service)
    service.pipe = SimpleNamespace(source_day=str(old), source_cursor='tail')
    service.check_code = lambda: None
    service.stream = SimpleNamespace(days=lambda: [latest], tail=lambda d: 'tail')
    service.context = lambda d: {'jm': {'day_end': AT.isoformat()}}
    calls = []

    def recover(day, ctx, now):
        calls.append(day)
        if day == latest:
            raise RuntimeError('stop after proving old-day order')
        return False

    service.recovery = recover
    with pytest.raises(RuntimeError):
        service.tick()
    assert calls == [old, latest]


def test_failed_or_unknown_provider_slot_is_never_reused(tmp_path, monkeypatch):
    import app.subing_model_service as module
    from datetime import date
    s = module.Service.__new__(module.Service)
    s.root = tmp_path
    day = date(2026, 11, 6)
    first = AT
    ctx = {'jm': {'contract': 'JM2701', 'first_open': first.isoformat(),
                  'day_end': (first + timedelta(hours=6)).isoformat()}}
    calls = []
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=2, stdout=b'failed'))
    assert s.facts(day, ctx, first + timedelta(minutes=2)) is None
    assert s.facts(day, ctx, first + timedelta(minutes=3)) is None
    assert len(calls) == 1
    # A later explicit durable slot has its own bounded attempt.
    assert s.facts(day, ctx, first + timedelta(minutes=7)) is None
    assert len(calls) == 2
    assert s.facts(day, ctx, first + timedelta(hours=7)) is None
    assert len(calls) == 2


def test_success_saved_before_registration_is_recovered_without_provider(tmp_path, monkeypatch):
    import app.subing_model_service as module
    from datetime import date
    import json
    s = module.Service.__new__(module.Service)
    s.root = tmp_path
    day = date(2026, 11, 6)
    directory = tmp_path / 'subing-model-facts-attempts' / f'{day}-0' / 'capture'
    directory.mkdir(parents=True)
    body = {'contracts': {'JM2701': {'start': str(day)}}, 'captured_at': AT.isoformat()}
    (directory / 'jm.json').write_text(json.dumps(body))
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: pytest.fail('provider must not repeat saved success'))
    ctx = {'jm': {'contract': 'JM2701', 'first_open': AT.isoformat(),
                  'day_end': (AT + timedelta(hours=6)).isoformat()}}
    assert s.facts(day, ctx, AT + timedelta(minutes=2)) == body
    assert s.facts(day, ctx, AT + timedelta(minutes=2)) == body


def test_loaded_launcher_identity_requires_exact_arguments_and_home():
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[3] / 'scripts/ops/macos/install-subing-model.py'
    spec = importlib.util.spec_from_file_location('subing_installer', script)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    value = installer.render(Path('/stable/model'), Path('/home/owner'))
    args = '\n'.join(value['ProgramArguments'])
    good = 'job = {\n program = /bin/bash\n working directory = /home/owner\n arguments = {\n' + args + '\n }\n}\n'
    installer.verify_loaded(good, value)
    for bad in (good.replace('/stable/model', '/other/model'), good.replace('/home/owner', '/other/home')):
        with pytest.raises(ValueError):
            installer.verify_loaded(bad, value)
