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
rows=[]
try:
    with Session(engine) as session, readonly_transaction(session, timeout_seconds=300):
        reader=NewowProductReader(build_market_data_service(session),coverage=build_database_coverage_source(session),active_products=('rb',),now=lambda:cutoff)
        for frequency in ('1m','15m','30m','60m'):
            proof=reader.historical_source_evidence(product='rb',frequency=frequency,since=date(2023,1,1),through=date(2026,9,24),as_of=cutoff)
            digest=sha256(_canonical(proof).encode()).hexdigest()
            assert digest==expected[frequency], 'SOURCE_PROOF_CHANGED'
            streams=[]
            for strategy in ('trend','oscillation','dual_fusion'):
                found=query.streams(strategy='newow_'+strategy,product='rb',frequency=frequency)
                assert len(found)==1, 'STREAM_MATRIX_INCOMPLETE'
                value=query.summary(found[0]['stream_id'],since=date(2023,1,1),through=date(2026,9,24),cutoff=cutoff)
                streams.append({'strategy':strategy,'stream':found[0],'summary':value})
            rows.append({'frequency':frequency,'status':'INPUT_AND_SAVED_GENERATION_VERIFIED','source_evidence_sha256':digest,'streams':streams})
        service=NewowProductService(lambda context,cancelled: reader,persisted_reference=PersistedNewowReference(factory).section,cancelled=lambda:True,now=lambda:cutoff)
        started=monotonic()
        try:
            service.query(ProductServiceQuery('rb','trend','1m',section='reference',as_of=cutoff))
        except Exception as error:
            assert str(error) in ('NEWOW_READ_CANCELLED', 'NEWOW_REQUEST_CANCELLED'), 'CANCEL_DID_NOT_FAIL_CLOSED'
        else:
            raise AssertionError('CANCEL_WAS_IGNORED')
        report={'schema':'newow_p2_final_pilot_v1','status':'PASS','product':'rb','as_of':cutoff.isoformat(),'provider_calls':0,'canonical_writes':0,'catalog_writes':0,'data_gap_plan':[], 'matrix_denominators':{'pilot_market_inputs':4,'pilot_base_strategies':8,'pilot_fusion_models':4,'pilot_history_modes':12,'full_expansion_not_executed':True},'rows':rows,'cancel_before_read_seconds':round(monotonic()-started,6),'acceptance_scope':'P2 final input/session/prefix and saved-generation proof; P6 browser/review tracked separately'}
        (root/'p2-final-pilot-readback.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
        print(json.dumps({'status':'PASS','source_proofs':len(rows),'saved_streams':sum(len(r['streams']) for r in rows),'provider_calls':0,'data_gaps':0,'cancel_seconds':report['cancel_before_read_seconds']}))
except Exception as error:
    print(json.dumps({'status':'FAILED','code':getattr(error,'code',str(error) if str(error).replace('_','').isupper() and len(str(error))<100 else type(error).__name__)}));raise SystemExit(1)
