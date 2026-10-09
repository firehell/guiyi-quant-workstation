from contextlib import contextmanager

from dataclasses import dataclass
import pytest

from app.runtime_scheduled import execute_scheduled_update, ScheduledUpdateError


@dataclass
class Binding:
    service: str = 'weekly-audit'
    generation: int = 1
    enabled: bool = True


class Backend:
    def __init__(self):
        self.calls = []
        self.busy = False
        self.race = False
    def freeze(self, _binding):
        return {'plist_sha256': 'exact'}
    def journal(self, value):
        self.calls.append(('journal', value['phase']))
    @contextmanager
    def idle_guards(self, _binding):
        self.calls.append('guard')
        yield
    def idle(self, _binding):
        return not self.busy and not (self.race and 'disable' in self.calls)
    def disable(self, _binding):
        self.calls.append('disable')
    def unload(self, _binding):
        self.calls.append('unload')
    def install(self, *args):
        self.calls.append('install')
    def load(self, _binding):
        self.calls.append('calendar_register')
    def verify(self, _binding):
        return True


def test_idle_job_changes_binding_without_starting_business():
    backend = Backend()
    assert execute_scheduled_update('weekly-audit', Binding(), Binding(generation=2), backend=backend,
        commit_binding=lambda: backend.calls.append('commit')) == 'switched'
    assert [x for x in backend.calls if isinstance(x, str)] == ['guard', 'disable', 'unload', 'install', 'commit', 'calendar_register']


def test_running_job_does_not_disable_or_change_binding():
    backend = Backend()
    backend.busy = True
    assert execute_scheduled_update('weekly-audit', Binding(), Binding(generation=2), backend=backend,
        commit_binding=lambda: pytest.fail('no commit')) == 'scheduled_busy'
    assert 'disable' not in backend.calls


def test_schedule_race_after_disable_stops_without_commit():
    backend = Backend()
    backend.race = True
    with pytest.raises(ScheduledUpdateError, match='OUTCOME_UNKNOWN'):
        execute_scheduled_update('weekly-audit', Binding(), Binding(generation=2), backend=backend,
            commit_binding=lambda: pytest.fail('no commit'))
    assert 'calendar_register' not in backend.calls
    assert backend.calls[-1] == ('journal', 'outcome_unknown')


def test_launchctl_permission_failure_cannot_authorize_idle(monkeypatch):
    from types import SimpleNamespace
    from app.runtime_scheduled import ScheduledBackend
    def unreadable(*_args, **_kwargs):
        raise ValueError('IDENTITY_UNAVAILABLE')
    monkeypatch.setattr('app.market_data.captured_recovery_runtime._read_launchd_service', unreadable)
    with pytest.raises(ValueError, match='IDENTITY_UNAVAILABLE'):
        ScheduledBackend().idle(SimpleNamespace(label='com.guiyi.quant-weekly-audit', root='/tmp'))


def test_unknown_calendar_readback_disables_future_triggers_without_kill():
    backend = Backend()
    backend.verify = lambda _candidate: False
    backend.halt_unknown = lambda _candidate: backend.calls.append('disable_future') if 'commit' in backend.calls else None
    with pytest.raises(ScheduledUpdateError, match='OUTCOME_UNKNOWN'):
        execute_scheduled_update('weekly-audit', Binding(), Binding(generation=2), backend=backend,
            commit_binding=lambda: backend.calls.append('commit'))
    assert backend.calls.count('calendar_register') == 1
    assert backend.calls[-1] == 'disable_future'
    assert 'kill' not in backend.calls


@pytest.mark.parametrize('phase', ['prepared', 'binding_committed', 'outcome_unknown'])
def test_nonterminal_scheduled_journal_requires_readback(tmp_path, monkeypatch, phase):
    from app.runtime_scheduled import ScheduledBackend
    from app.runtime_handover import _write
    import app.runtime_scheduled
    monkeypatch.setattr(app.runtime_scheduled, 'runtime_directory', lambda: tmp_path)
    _write(tmp_path / 'weekly-audit.scheduled-update.json', {'phase': phase})
    with pytest.raises(ScheduledUpdateError, match='RECOVERY_READBACK_REQUIRED'):
        ScheduledBackend().freeze(Binding())


def test_unknown_journal_failure_keeps_binding_committed_gate(tmp_path, monkeypatch):
    from app.runtime_scheduled import ScheduledBackend
    from app.runtime_handover import _write
    import app.runtime_scheduled
    monkeypatch.setattr(app.runtime_scheduled, 'runtime_directory', lambda: tmp_path)
    backend = Backend()
    backend.verify = lambda _candidate: False
    def journal(value):
        if value['phase'] == 'outcome_unknown':
            raise OSError('control write unknown')
        _write(tmp_path / 'weekly-audit.scheduled-update.json', value)
    backend.journal = journal
    with pytest.raises(ScheduledUpdateError, match='OUTCOME_UNKNOWN'):
        execute_scheduled_update('weekly-audit', Binding(), Binding(generation=2), backend=backend,
            commit_binding=lambda: backend.calls.append('commit'))
    with pytest.raises(ScheduledUpdateError, match='RECOVERY_READBACK_REQUIRED'):
        ScheduledBackend().freeze(Binding())
    assert backend.calls.count('calendar_register') == 1
