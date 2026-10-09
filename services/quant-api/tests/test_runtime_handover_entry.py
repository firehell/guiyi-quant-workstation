from io import StringIO
from contextlib import contextmanager

from app import runtime_entry


def test_feed_entry_uses_factory_without_rqdata(monkeypatch):
    seen = []
    @contextmanager
    def session():
        yield object()
    class Feed:
        def run_forever(self, **kwargs):
            seen.append('run')
    monkeypatch.setattr(runtime_entry, 'build_market_feed_service', lambda s: Feed(), raising=False)
    result = runtime_entry.main(['market-feed'], session_factory=session,
                                stdout=StringIO(), stderr=StringIO())
    assert result == 0
    assert seen == ['run']


def test_alert_handover_entry_passes_ownership(monkeypatch):
    from app import runtime_handover
    monkeypatch.setenv('GUIYI_RUNTIME_HANDOVER_ENABLED', '1')
    seen = []
    class Owner:
        def assert_owned(self):
            seen.append('check')
        def should_drain(self):
            return True
        def mark_ready(self):
            pass
    owner = Owner()
    monkeypatch.setattr(runtime_handover, 'run_supervised', lambda service, run, **kw: run(owner))
    class Alert:
        def run_forever(self):
            assert self.stop_requested()
    def build(**kwargs):
        kwargs['assert_owned']()
        return Alert()
    assert runtime_entry.main(['alert'], alert_runtime_factory=build,
                              stdout=StringIO(), stderr=StringIO()) == 0
    assert seen == ['check']
