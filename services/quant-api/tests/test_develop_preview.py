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
    assert calls[0][1] == {'host': '127.0.0.1', 'port': 8002, 'workers': 1}
    assert 'test-only-placeholder' not in capsys.readouterr().out


def test_private_configuration_failure_is_sanitized(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['preview', 'api'])
    def fail(_):
        raise PrivateSettingsError()
    monkeypatch.setattr(develop_preview, 'load_private_readonly_settings', fail)
    with pytest.raises(SystemExit, match='DEVELOP_PRIVATE_SETTINGS_UNAVAILABLE'):
        develop_preview.main()
