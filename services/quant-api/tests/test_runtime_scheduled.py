from contextlib import contextmanager

from dataclasses import dataclass
import pytest

from app.runtime_scheduled import execute_scheduled_update, ScheduledUpdateError


@dataclass
class Binding:
    service: str = 'weekly-audit'
    generation: int = 1
    enabled: bool = True
    root: str = '/fixture'


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
    monkeypatch.setattr('app.runtime_identity.read_launchd_service', unreadable)
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


@pytest.mark.parametrize('phase', ['prepared', 'binding_committed', 'outcome_unknown', None])
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


def test_archive_handoff_preserves_completed_history_and_consumed_late_claim(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    import json
    from types import SimpleNamespace

    from app.market_data.after_market_history import NAME, read_history
    from app.market_data.late_provider_recovery import _read as read_late_state
    from app.runtime_scheduled import ScheduledBackend

    products = ("rb",)
    for module in ("operational_universe", "late_provider_recovery"):
        monkeypatch.setattr(f"app.market_data.{module}.load_operational_products", lambda: products)
    old, new = tmp_path / "old", tmp_path / "new"
    source = old / ".run"
    source.mkdir(parents=True, mode=0o700)
    new.mkdir(mode=0o700)
    status = source / "after-market-status.json"
    status.write_text(json.dumps({
        "schema_version": 3, "current_run": None, "last_failure": None,
        "last_successful_trading_day": "2026-09-30",
        "last_run": {"trading_day": "2026-09-30", "status": "passed", "attempts": 1,
                     "started_at": "2026-09-30T18:05:00+08:00", "finished_at": "2026-09-30T18:11:00+08:00",
                     "products": ["rb"], "error_code": None},
    }))
    late = source / "late-provider-recovery-status.json"
    late.write_text(json.dumps({"schema_version": 1, "runs": {"2026-09-29": {
        "products": ["rb"], "due_at": "2026-10-01T19:05:00+08:00", "state": "claimed",
        "checks": 1, "error_code": "RQDATA_NOT_READY",
    }}}))
    late.chmod(0o600)
    before = status.read_bytes(), late.read_bytes()
    previous = SimpleNamespace(root=str(old), commit="a" * 40)
    candidate = SimpleNamespace(root=str(new))
    backend = ScheduledBackend()
    backend.preserve_after_market(previous, candidate)
    backend.preserve_after_market(previous, candidate)
    target = new / ".run"
    retained = read_history(target / NAME, products=products, now=datetime.now(UTC))
    assert retained["source_commit"] == previous.commit
    assert not (target / status.name).exists()
    assert read_late_state(target / late.name) == read_late_state(late)
    assert (status.read_bytes(), late.read_bytes()) == before

    failed = json.loads(before[0])
    failed["last_run"].update(status="failed", error_code="COMMIT_OUTCOME_UNKNOWN")
    status.write_text(json.dumps(failed))
    with pytest.raises(ScheduledUpdateError, match="SCHEDULED_ARCHIVE_COMMIT_READBACK_REQUIRED"):
        backend.preserve_after_market(previous, candidate)
