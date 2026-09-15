"""Read-only baseline/candidate comparison; no data/config/source mutations."""
import datetime
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from sqlalchemy import event, text
from app.db.session import SessionLocal, engine
from app.market_data import composition

ROOT = Path('/Volumes/扩展盘/guiyi-quant-workstation')
OUT = ROOT / 'outputs/market-home-latency-20260914'
BASE = '4c891d8df24c4a5206cfcad50712012e3c564fcf'
source = subprocess.run(['git', '-C', str(ROOT), 'show', BASE + ':services/quant-api/app/market_data/market_data_service.py'], check=True, capture_output=True, text=True).stdout
module = importlib.util.module_from_spec(importlib.util.spec_from_loader('baseline_market_data', loader=None))
sys.modules[module.__name__] = module
exec(compile(source, '<baseline_market_data>', 'exec'), module.__dict__)
candidate = composition.MarketDataService
count = [0]
def counted(*args): count[0] += 1
event.listen(engine, 'after_cursor_execute', counted)
try:
    results = []
    with SessionLocal() as session:
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        session.execute(text("SET LOCAL statement_timeout='45s'"))
        assert session.execute(text('SHOW transaction_read_only')).scalar() == 'on'
        for label, cls in [('implemented', candidate)]:
            composition.MarketDataService = cls
            projection = composition.build_market_home_projection(session)
            identity = projection.service.authority_identity()
            assert projection.store.load(identity) is None, 'projection appeared; comparison must measure fallback'
            n = count[0]
            start = time.perf_counter()
            result = projection.read()
            row = {'mode': label, 'seconds': time.perf_counter() - start, 'sql_count': count[0] - n,
                   'participants': result.participant_count, 'target': str(result.target_as_of),
                   'response_sha256': hashlib.sha256(result.model_dump_json().encode()).hexdigest()}
            results.append(row)
            print(json.dumps(row), flush=True)
        same = results[0]['response_sha256'] == json.loads((OUT / 'implemented-read.json').read_text())['runs'][0]['response_sha256']
        assert same, 'response mismatch'
        session.rollback()
    (OUT / 'implemented-read-isolated.json').write_text(json.dumps({'checked_at': datetime.datetime.now().astimezone().isoformat(), 'transaction': 'repeatable read/read only', 'baseline': BASE, 'same_response': same, 'runs': results}, indent=2))
except Exception as exc:
    print(json.dumps({'error_type': type(exc).__name__}), flush=True)
    raise SystemExit(1)
finally:
    composition.MarketDataService = candidate
    engine.dispose()
