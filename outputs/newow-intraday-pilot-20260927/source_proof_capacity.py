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
rows=[]
try:
    with Session(engine) as session, readonly_transaction(session, timeout_seconds=300):
        reader=NewowProductReader(build_market_data_service(session), coverage=build_database_coverage_source(session), active_products=('rb',), now=lambda:cutoff)
        for frequency in ('1m','15m','30m','60m'):
            started=monotonic()
            proof=reader.historical_source_evidence(product='rb', frequency=frequency, since=date(2023,1,1), through=date(2026,9,24), as_of=cutoff)
            rows.append({'frequency':frequency,'elapsed_seconds':round(monotonic()-started,3),'source_evidence_sha256':sha256(_canonical(proof).encode()).hexdigest(),'source_bytes':len(_canonical(proof).encode()),'physical_dependencies':len(proof['physical']),'partitions':sum(len(item['partitions']) for item in proof['physical'])})
            print(json.dumps(rows[-1]),flush=True)
    report={'schema':'intraday_source_proof_capacity_v1','config_identity':config,'cutoff':cutoff.isoformat(),'rows':rows,'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    Path('outputs/newow-intraday-pilot-20260927/source-proof-capacity.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
except Exception as error:
    print(json.dumps({'status':'FAILED','code':getattr(error,'code',type(error).__name__)}),flush=True)
    raise SystemExit(1)
