from pathlib import Path
import sys

import pytest

from app import develop_preview
from app.private_settings import PrivateSettingsError


def test_api_uses_private_dependencies_and_isolated_projection(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(sys, 'argv', ['preview', 'api'])
    monkeypatch.setattr(develop_preview, 'load_private_readonly_settings', lambda _: ({
        'DATABASE_URL': 'postgresql://example', 'GUIYI_CANONICAL_DATA_ROOT': '/tmp/canonical',
        'REDIS_URL': 'redis://127.0.0.1:6379/0', 'REDIS_PASSWORD': 'test-only-placeholder',
        'GUIYI_LIVE_RECOVERY_ENABLED': '1',
    }, {}))
    monkeypatch.setattr(develop_preview, 'prepare_home_projection', lambda: calls.append('projection-ready'))
    import uvicorn
    monkeypatch.setattr(uvicorn, 'run', lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.delenv('GUIYI_LIVE_RECOVERY_ENABLED', raising=False)
    for key in ('DATABASE_URL', 'GUIYI_CANONICAL_DATA_ROOT', 'REDIS_URL', 'GUIYI_HOME_PROJECTION_PATH'):
        monkeypatch.delenv(key, raising=False)
    develop_preview.main()
    import os
    assert os.environ['REDIS_URL'] == 'redis://:test-only-placeholder@127.0.0.1:6379/0'
    assert 'GUIYI_LIVE_RECOVERY_ENABLED' not in os.environ
    path = Path(os.environ['GUIYI_HOME_PROJECTION_PATH'])
    assert path.name == 'develop-newow-home.json' and path.parent.name == '.run'
    assert len(calls) == 1  # API startup never waits for a full 60-product rebuild.
    assert calls[0][0] == ('app.develop_preview:create_develop_app',)
    assert calls[0][1] == {'factory': True, 'host': '127.0.0.1', 'port': 8002, 'workers': 1}
    assert 'test-only-placeholder' not in capsys.readouterr().out


def test_private_configuration_failure_is_sanitized(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['preview', 'api'])
    def fail(_):
        raise PrivateSettingsError()
    monkeypatch.setattr(develop_preview, 'load_private_readonly_settings', fail)
    with pytest.raises(SystemExit, match='DEVELOP_PRIVATE_SETTINGS_UNAVAILABLE'):
        develop_preview.main()


def test_home_projection_preparation_uses_existing_idempotent_builder(monkeypatch):
    from app.market_data.newow import home_recovery
    calls = []
    expected = {"items": [{"projection_status": "ready"}]}
    def build():
        calls.append("build")
        return expected
    monkeypatch.setattr(home_recovery, "run_home_build", build)
    assert develop_preview.prepare_home_projection() == expected
    assert calls == ["build"]


def test_continuous_recovery_yields_to_existing_writer_and_continues_same_worker():
    import threading
    from app.market_data.newow.home_projection import ProjectionError
    stop=threading.Event()
    calls=[]
    statuses=[]
    class Worker:
        def tick(self):
            calls.append('tick')
            if len(calls)==1:
                raise ProjectionError() from BlockingIOError()
    def wait(seconds):
        assert seconds==60
        if len(calls)==3:
            stop.set()
    develop_preview.run_develop_recovery(stop,worker=Worker(),wait=wait,report=statuses.append)
    assert calls==['tick']*3
    assert statuses[:2]==['running','waiting']
    assert statuses[-1]=='stopped'


def test_recovery_unknown_error_stops_and_does_not_log_private_exception(caplog):
    import threading
    class Worker:
        def tick(self):raise RuntimeError('private-config-must-not-log')
    develop_preview.run_develop_recovery(threading.Event(),worker=Worker())
    assert 'DEVELOP_HOME_RECOVERY_FAILED' in caplog.text
    assert 'private-config-must-not-log' not in caplog.text


def test_lifespan_starts_background_without_blocking_and_stops_same_worker(monkeypatch):
    import asyncio
    import threading
    from fastapi import FastAPI
    import app.main
    fake=FastAPI()
    monkeypatch.setattr(app.main,'app',fake)
    started=threading.Event()
    finished=threading.Event()
    def run(stop, **_):
        started.set()
        stop.wait()
        finished.set()
    monkeypatch.setattr(develop_preview,'run_develop_recovery',run)
    app=develop_preview.create_develop_app()
    async def check():
        async with app.router.lifespan_context(app):
            assert started.wait(2)
            assert not finished.is_set()
        assert finished.is_set()
    asyncio.run(check())


def test_recovery_initialization_failure_is_readable_and_sanitized(monkeypatch, caplog):
    import threading
    from app.market_data.newow import home_projection_composition
    def fail(**_):
        raise RuntimeError('private-initialization-details')
    monkeypatch.setattr(home_projection_composition,'build_home_projection',fail)
    statuses=[]
    develop_preview.run_develop_recovery(threading.Event(),report=statuses.append)
    assert statuses==['failed']
    assert 'DEVELOP_HOME_RECOVERY_FAILED' in caplog.text
    assert 'private-initialization-details' not in caplog.text
