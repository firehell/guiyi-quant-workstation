from datetime import date, datetime
from hashlib import sha256
import json, os, resource
from pathlib import Path
from time import monotonic
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from scripts.newow_weekly_recovery import load_private_readonly_settings
from app.db.session import normalize_database_url
from app.db.readonly import readonly_transaction
from app.market_data.composition import build_market_data_service, build_database_coverage_source
from app.market_data.newow.product_reader import NewowProductReader
from app.reference_trading.inputs import _canonical
settings, config = load_private_readonly_settings(Path('/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env'))
os.environ.update(settings)
engine = create_engine(normalize_database_url(settings['DATABASE_URL']))
cutoff = datetime.fromisoformat('2026-09-24T07:00:00.000001+00:00')

from sqlalchemy.orm import sessionmaker
from app.reference_trading.query import HistoricalReferenceQuery
from app.reference_trading.persisted_newow import PersistedNewowReference
from app.market_data.newow.product_service import NewowProductService, ProductServiceQuery
schema='newow_intraday_pilot_20260927'
factory=sessionmaker(engine.execution_options(schema_translate_map={None:schema}),expire_on_commit=False)
query=HistoricalReferenceQuery(factory)
root=Path('outputs/newow-intraday-pilot-20260927')
prior=json.loads((root/'source-proof-capacity.json').read_text())
expected={r['frequency']:r['source_evidence_sha256'] for r in prior['rows']}

try:
    stream=query.streams(strategy='newow_trend',product='rb',frequency='1m')[0]
    before=query.summary(stream['stream_id'],since=date(2023,1,1),through=date(2026,9,24),cutoff=cutoff)
    checks=[0]
    def cancel_scan():
        checks[0]+=1
        if checks[0]>=8:
            raise RuntimeError('NEWOW_READ_CANCELLED')
    start=monotonic()
    try:
        query.presentation_facts(stream['stream_id'],snapshot_token=before['snapshot'],since=date(2023,1,1),through=date(2026,9,24),cutoff=cutoff,kinds=('availability','hint','action'),max_points=200000,check_cancelled=cancel_scan)
    except RuntimeError as error:
        assert str(error)=='NEWOW_READ_CANCELLED'
    else:
        raise AssertionError('CANCEL_IGNORED')
    elapsed=monotonic()-start
    after=query.summary(stream['stream_id'],since=date(2023,1,1),through=date(2026,9,24),cutoff=cutoff)
    assert before==after,'READ_CANCEL_CHANGED_GENERATION'
    report={'status':'PASS','cancel_after_batches':checks[0],'cancel_seconds':round(elapsed,3),'saved_generation_unchanged':True,'provider_calls':0,'writes':0}
    (root/'running-cancel-readback.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
except Exception as error:
    print(json.dumps({'status':'FAILED','code':getattr(error,'code',type(error).__name__)}));raise SystemExit(1)
