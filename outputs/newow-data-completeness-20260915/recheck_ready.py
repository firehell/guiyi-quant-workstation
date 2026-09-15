"""Read-only recheck of the eight products reported ready by the latest audits."""
from datetime import datetime, UTC
from pathlib import Path
import json
import os
import sys
import time

ROOT = Path('/Volumes/扩展盘/guiyi-quant-workstation')
OUT = Path('/private/tmp/guiyi-newow-completeness-20260915')
sys.path[:0] = [str(ROOT), str(ROOT / 'services/quant-api'), str(ROOT / 'packages/quant-core')]

def main():
    from scripts.newow_weekly_recovery import load_private_execution_settings
    settings, identity = load_private_execution_settings(Path('/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env'))
    os.environ['GUIYI_CANONICAL_DATA_ROOT'] = settings['GUIYI_CANONICAL_DATA_ROOT']
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.url import normalize_database_url
    from app.db.readonly import readonly_transaction
    from app.market_data.newow.readiness import ReadinessRequest
    from app.market_data.newow.readiness_composition import build_newow_readiness
    from guiyi_quant.newow.product_contracts import ProductFrequency
    as_of = datetime.now(UTC)
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']), pool_pre_ping=True, connect_args={'connect_timeout': 10})
    summary = {'as_of': as_of.isoformat(), 'identity': identity, 'provider_requests': 0, 'writes': 0, 'products': []}
    started = time.monotonic()
    try:
        with Session(engine, autoflush=False) as session, readonly_transaction(session, timeout_seconds=900):
            for symbol in ('a', 'ag', 'al', 'ao', 'ap', 'au', 'pd', 'pt'):
                request = ReadinessRequest(products=(symbol,), as_of=as_of, matrix=False, max_work=10000, timeout_seconds=180, frequencies=(ProductFrequency.WEEKLY, ProductFrequency.DAILY))
                report = build_newow_readiness(session, request=request)
                (OUT / (symbol + '-current.json')).write_text(json.dumps(report, ensure_ascii=False, default=str))
                failed = [d for d in report['dependencies'] if d['status'] not in ('DATA_READY', 'NOT_APPLICABLE')]
                bad_enumerations = [e for e in report['enumerations'] if e['status'] not in ('ENUMERATED', 'UNOPENED')]
                row = {'symbol': symbol, 'complete': report['complete'], 'dependency_count': len(report['dependencies']), 'failed_dependencies': len(failed), 'repair_targets': len(report['repair_targets']), 'bad_enumerations': len(bad_enumerations), 'metadata_proposals': len(report['metadata_proposals']), 'elapsed_seconds': round(time.monotonic()-started, 2)}
                summary['products'].append(row)
                print(json.dumps(row), flush=True)
                if not report['complete']:
                    break
    finally:
        engine.dispose()
        (OUT / 'current-ready-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if len(summary['products']) == 8 and all(r['complete'] for r in summary['products']) else 2

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__,'code':'READONLY_RECHECK_FAILED'}), flush=True)
        sys.exit(1)
