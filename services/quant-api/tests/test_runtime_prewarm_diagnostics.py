import json
import plistlib
import subprocess
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from app import runtime_cohort as cohort, runtime_cohort_host as adapter
from app.runtime_bindings import BindingRegistry
from tests.test_runtime_cohort import Host, plan


@pytest.mark.parametrize('failure,condition,code', [
    ('timeout', 'subprocess_timeout', None),
    ('blocked', 'candidate_blocked', 'REFERENCE_WARMUP_PREIMAGE_UNAVAILABLE'),
    ('private', 'candidate_blocked', 'COHORT_OPERATION_BLOCKED'),
    ('untyped', 'candidate_blocked', 'COHORT_OPERATION_BLOCKED'),
    ('invalid', 'output_invalid', None),
])
def test_native_prewarm_failure_retains_service_and_bounded_reason(tmp_path, monkeypatch, failure, condition, code):
    model = Host(tmp_path)
    old = BindingRegistry(1, {name: replace(value, enabled=name == 'api') for name, value in model.old.services.items()})
    host = object.__new__(adapter.CohortHost)
    def run(*_args, **_kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired('private-argv', 120, output='secret SQL')
        if failure == 'invalid':
            return SimpleNamespace(returncode=1, stdout='private-password SQL')
        value = 'REFERENCE_WARMUP_PREIMAGE_UNAVAILABLE' if failure == 'blocked' else 'private-password SQL'
        if failure == 'untyped':
            value = {'private': 'secret'}
        return SimpleNamespace(returncode=1, stdout=json.dumps({'status': 'blocked', 'code': value}))
    monkeypatch.setattr(adapter.subprocess, 'run', run)
    intent = {'old': asdict(old), 'new': asdict(old), 'installed': {'api': {'plist_hex': plistlib.dumps({'EnvironmentVariables': {}}).hex()}}}
    with pytest.raises(cohort.CohortError) as caught:
        host.prewarm(intent)
    assert caught.value.service == 'api'
    assert caught.value.warmup_condition == condition
    assert caught.value.warmup_code == code
    assert 'private' not in str(vars(caught.value)) and 'secret' not in str(vars(caught.value))


def test_cancelled_prewarm_persists_safe_diagnostic_without_service_effect(tmp_path):
    host = Host(tmp_path)
    frozen = plan(host)
    def fail(_):
        error = cohort.CohortError('COHORT_CANDIDATE_WARMUP_FAILED')
        error.service = 'reference-worker'
        error.warmup_condition = 'candidate_blocked'
        error.warmup_code = 'REFERENCE_WARMUP_PREIMAGE_UNAVAILABLE'
        raise error
    host.prewarm = fail
    with pytest.raises(cohort.CohortError, match='PRECONDITION_CANCELLED'):
        cohort.apply_cohort(host, frozen)
    result = json.loads((host.directory/'cohort-release.json').read_text())
    assert result['phase'] == 'cancelled' and result['effects'] == {}
    assert result['failed_service'] == 'reference-worker'
    assert result['warmup_diagnostic'] == {'condition': 'candidate_blocked', 'code': 'REFERENCE_WARMUP_PREIMAGE_UNAVAILABLE'}


@pytest.mark.parametrize('message,code', [
    ('REFERENCE_WARMUP_TIMEOUT', 'REFERENCE_WARMUP_TIMEOUT'),
    ('private-password SQL', 'COHORT_OPERATION_BLOCKED'),
])
def test_warmup_cli_preserves_only_explicit_public_codes(monkeypatch, capsys, message, code):
    from app import runtime_deployment
    def fail(_):
        raise RuntimeError(message)
    monkeypatch.setattr(runtime_deployment, 'warmup_service', fail)
    assert cohort.main(['warmup', 'api']) == 1
    assert json.loads(capsys.readouterr().out) == {'status': 'blocked', 'code': code}
