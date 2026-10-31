"""Local develop API and explicit derived homepage build; no Runtime switch."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.private_settings import PrivateSettingsError, load_private_readonly_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('api', 'build'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    try:
        settings, _ = load_private_readonly_settings(
            Path.home() / 'Library/Application Support/GuiyiQuant/project.env')
    except PrivateSettingsError:
        raise SystemExit('DEVELOP_PRIVATE_SETTINGS_UNAVAILABLE') from None
    # Same dependency URL normalization as the existing local service launcher.
    redis_url = settings.get('REDIS_URL', '')
    if not redis_url or redis_url == 'redis://127.0.0.1:6379/0':
        password = settings.get('REDIS_PASSWORD') or settings.get('POSTGRES_PASSWORD')
        if not password:
            raise SystemExit('DEVELOP_REDIS_SETTINGS_UNAVAILABLE')
        redis_url = f'redis://:{password}@127.0.0.1:6379/0'
    os.environ.update({key: settings[key] for key in (
        'DATABASE_URL', 'GUIYI_CANONICAL_DATA_ROOT')})
    os.environ['REDIS_URL'] = redis_url
    os.environ['GUIYI_HOME_PROJECTION_PATH'] = str(root / '.run/develop-newow-home.json')
    if args.command == 'build':
        from app.market_data.newow.home_projection_composition import build_home_projection
        result = build_home_projection().build()
        counts = {state: sum(item['projection_status'] == state for item in result['items'])
                  for state in ('ready', 'stale', 'failed', 'missing', 'updating')}
        print(counts)
    else:
        import uvicorn
        uvicorn.run('app.main:app', host='127.0.0.1', port=8002, workers=1)


if __name__ == '__main__':
    main()
