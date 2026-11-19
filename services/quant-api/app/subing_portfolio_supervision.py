"""Calendar selection and bounded facts refresh for the sole shared Paper worker."""
import json
import subprocess
import sys
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

from sqlalchemy.orm import Session
from app.db.readonly import readonly_transaction
from app.market_data.catalog import MarketCatalog
from app.market_data.market_data_service import MarketDataService
from app.market_data.storage import CanonicalMonthlyStore
from app.subing_model.worker import atomic, facts_for
from app.subing_model_service import capture_slot, fsync_directory
from guiyi_quant.trading_universe import TRADING_PRODUCTS


def trading_day(settings, sql, now):
    """Choose the first authoritative session envelope not yet closed (incl night)."""
    local_day = now.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date()
    root = Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
    with Session(sql, autoflush=False) as db, readonly_transaction(db, timeout_seconds=30):
        catalog = MarketCatalog(db, root)
        market = MarketDataService(catalog, CanonicalMonthlyStore(root))
        days = catalog.calendar_days('jm', local_day - timedelta(days=4), local_day + timedelta(days=14))
        for day, opened in days:
            if opened:
                windows = market.session_windows(symbol='jm', trading_day=day)
                if windows and now < max(w.end for w in windows):
                    return day, min(w.start for w in windows)
    raise ValueError('PORTFOLIO_CALENDAR_INCOMPLETE')


def refresh_facts(registry, day, contexts, now):
    """Reuse the existing six-call adapter; no retry after an unknown attempt.

    The same three Session slots as the previous current-facts service apply per
    product/day. Assets and intents survive checkout switches and restarts.
    """
    from app.subing_portfolio_journal import stamp
    registry.mkdir(mode=0o700, parents=True, exist_ok=True)
    for product in TRADING_PRODUCTS:
        index = registry / f'{product}.json'
        if product not in contexts:
            continue
        if facts_for(index, day):
            continue
        context = contexts[product]
        slot = capture_slot(now, stamp(context['first_open']), stamp(context['day_end']))
        if slot is None:
            continue
        attempts = registry / 'attempts'
        attempts.mkdir(mode=0o700, exist_ok=True)
        target = attempts / f'{day}-{product}-{slot}'
        asset = target / 'capture' / f'{product}.json'
        if not target.exists():
            target.mkdir(mode=0o700)
            fsync_directory(attempts)
            atomic(target / 'intent.json', dict(day=str(day), product=product,
                contract=context['contract'], slot=slot, max_calls=6))
            result = subprocess.run([sys.executable, '-m', 'scripts.research.subing_model_facts',
                '--contract', context['contract'], '--day', str(day), '--out', str(target / 'capture')],
                capture_output=True, timeout=180, check=False)
            atomic(target / 'result.json', dict(returncode=result.returncode,
                stdout_sha256=sha256(result.stdout).hexdigest()))
        if not asset.is_file() or asset.is_symlink():
            continue
        raw = asset.read_bytes()
        body = json.loads(raw)
        if body['contracts'][context['contract']]['start'] != str(day):
            raise ValueError('PORTFOLIO_FACTS_DAY_INVALID')
        registrations = json.loads(index.read_text()) if index.exists() else {}
        registrations[str(day)] = dict(path=str(asset), sha256=sha256(raw).hexdigest())
        atomic(index, registrations)
