"""Local develop API with prepared derived homepage; no Runtime switch."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import logging
import threading
import os
from pathlib import Path

from app.services.newow_reference_mode import after_market_only, market_foundation_isolated
from app.private_settings import PrivateSettingsError, load_private_readonly_settings


def prepare_home_projection():
    # Startup work only. GET remains a read of the isolated developer asset.
    # The existing builder skips periods whose authoritative identity is unchanged.
    from app.market_data.newow.home_recovery import run_home_build
    return run_home_build()


def run_develop_recovery(stop, *, worker=None, wait=None, report=None):
    """Continue the existing isolated journal; never reset attempts or bypass budgets."""
    from app.market_data.newow.home_projection import ProjectionError
    report = report or (lambda status: None)
    try:
        if worker is None:
            from app.market_data.newow.home_projection_composition import build_home_projection
            from app.market_data.newow.home_recovery import HomeRecovery
            root = Path(__file__).resolve().parents[3]
            home = build_home_projection(output_path=root / '.run/develop-newow-home.json')
            worker = HomeRecovery(home, stop_requested=stop.is_set)
    except Exception:
        report('failed')
        logging.getLogger(__name__).error('DEVELOP_HOME_RECOVERY_FAILED')
        return
    wait = wait or stop.wait
    while not stop.is_set():
        try:
            report('running')
            worker.tick()
            report('waiting')
        except ProjectionError as exc:
            # Another ongoing build owns this exact journal. Do not cancel or steal it.
            if not isinstance(exc.__cause__, BlockingIOError):
                report('failed')
                logging.getLogger(__name__).error('DEVELOP_HOME_RECOVERY_FAILED')
                return
            report('waiting')
        except Exception:
            report('failed')
            logging.getLogger(__name__).error('DEVELOP_HOME_RECOVERY_FAILED')
            return
        wait(60)
    report('stopped')


def _validate_market_foundation_preview():
    from sqlalchemy.engine import make_url

    from app.db.url import normalize_database_url
    from app.market_data.market_archive import require_isolated_archive

    try:
        require_isolated_archive(
            make_url(normalize_database_url(os.environ["DATABASE_URL"])),
            os.environ["REDIS_URL"],
            Path(os.environ["GUIYI_CANONICAL_DATA_ROOT"]),
        )
    except (OSError, ValueError, KeyError):
        raise SystemExit("MARKET_FOUNDATION_ISOLATION_REQUIRED") from None


def create_develop_app():
    if market_foundation_isolated():
        _validate_market_foundation_preview()
    from app.main import app
    if after_market_only():
        return app
    previous_lifespan = app.router.lifespan_context
    from datetime import UTC, datetime
    app.state.develop_home_recovery = {'status': 'starting', 'updated_at': None}

    def report(status):
        app.state.develop_home_recovery = {'status': status, 'updated_at': datetime.now(UTC).isoformat()}

    @app.get('/api/v1/develop/home-recovery')
    def recovery_status():
        return {**app.state.develop_home_recovery, 'readonly': True}

    @asynccontextmanager
    async def lifespan(application):
        stop = threading.Event()
        worker = threading.Thread(target=run_develop_recovery, args=(stop,), kwargs={'report': report}, name='develop-home-recovery')
        async with previous_lifespan(application):
            worker.start()
            try:
                yield
            finally:
                stop.set()
                # Native isolated compute observes stop and reaps its own child.
                await asyncio.to_thread(worker.join)
    app.router.lifespan_context = lifespan
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('api', 'build'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    if market_foundation_isolated():
        if args.command != 'api':
            raise SystemExit("MARKET_FOUNDATION_AFTER_MARKET_ONLY")
        _validate_market_foundation_preview()
        import uvicorn
        uvicorn.run('app.develop_preview:create_develop_app', factory=True,
                    host='127.0.0.1', port=8002, workers=1)
        return
    if after_market_only():
        if args.command != 'api':
            raise SystemExit('NEWOW_AFTER_MARKET_ONLY')
        from app.services.newow_backtest_eod import _isolated_market_url
        from app.services.newow_reference_mode import require_isolated_redis

        require_isolated_redis(os.environ.get("REDIS_URL", ""))
        _isolated_market_url(os.environ.get("DATABASE_URL", ""))
        root_value = Path(os.environ["GUIYI_CANONICAL_DATA_ROOT"]).resolve(strict=True)
        if root_value != Path(os.environ["GUIYI_NEWOW_EOD_CANONICAL_ROOT"]).resolve(strict=True):
            raise SystemExit("BACKTEST_ISOLATED_CATALOG_REQUIRED")
        # Never load local Runtime provider credentials for this instance.
        import uvicorn
        uvicorn.run('app.develop_preview:create_develop_app', factory=True,
                    host='127.0.0.1', port=8002, workers=1)
        return
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
        result = prepare_home_projection()
        counts = {state: sum(item['projection_status'] == state for item in result['items'])
                  for state in ('ready', 'stale', 'failed', 'missing', 'updating')}
        print(counts)
    else:
        import uvicorn
        uvicorn.run('app.develop_preview:create_develop_app', factory=True,
                    host='127.0.0.1', port=8002, workers=1)


if __name__ == '__main__':
    main()
