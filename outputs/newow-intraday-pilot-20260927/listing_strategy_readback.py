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

from app.market_data.newow.product_service import NewowProductService, ProductServiceQuery
rows=[]
try:
 with Session(engine) as session, readonly_transaction(session,timeout_seconds=300):
  def factory(context,cancelled):
   return NewowProductReader(build_market_data_service(session),coverage=build_database_coverage_source(session),active_products=('pd',),context_frequencies=context,cancelled=cancelled,now=lambda:cutoff)
  service=NewowProductService(factory,now=lambda:cutoff)
  for frequency in ('1m','15m','30m','60m'):
   for strategy in ('trend','oscillation'):
    result=service.query(ProductServiceQuery('pd',strategy,frequency,section='chart',since=date(2025,11,27),through=date(2025,11,27),as_of=cutoff))
    frames=[frame for frame in result.chart.value.replay.frames if frame.bar.bar.observation_eligible]
    print(json.dumps({'frequency':frequency,'strategy':strategy,'count':len(frames),'first_state':frames[0].availability.status.value if frames else None,'first_end':str(frames[0].bar.bar.bar_end) if frames else None,'all_frames':len(result.chart.value.replay.frames),'warming_count':sum(f.availability.status.value=='warming' for f in frames)}),flush=True)
    assert frames, 'LISTING_EMPTY'
    if strategy=='oscillation':
     assert frames[0].availability.status.value=='warming', 'OSC_LISTING_WARMUP_MISSING'
     if frequency in ('30m','60m'): assert all(f.availability.status.value=='warming' for f in frames), 'SHORT_HISTORY_FALSE_READY'
    else: assert frames[0].availability.status.value=='ready', 'TREND_FIRST_FRAME_CHANGED'
    assert all(frame.bar.bar.physical_contract==frames[0].bar.bar.physical_contract for frame in frames), 'LISTING_OWNER_MIXED'
    rows.append({'frequency':frequency,'strategy':strategy,'status':'PASS','first_state':frames[0].availability.status.value,'last_state':frames[-1].availability.status.value,'frames':len(frames),'physical_contract':frames[0].bar.bar.physical_contract})
 report={'status':'PASS','first_maintained_product_day':'2025-11-27','provider_calls':0,'writes':0,'rows':rows}
 Path('outputs/newow-intraday-pilot-20260927/listing-strategy-readback.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps({'status':'PASS','cases':len(rows)}))
except Exception as error:
 print(json.dumps({'status':'FAILED','code':getattr(error,'code',str(error) if str(error).replace('_','').isupper() and len(str(error))<100 else type(error).__name__)}));raise SystemExit(1)
