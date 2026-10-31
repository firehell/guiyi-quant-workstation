"""Read-only MDS feature capture, completed same-owner 60m; no provider calls."""
import sys,json,hashlib,gc,os
from pathlib import Path
from collections import deque
from datetime import date,datetime,UTC
from decimal import Decimal as D
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.private_settings import load_private_execution_settings
from app.db.session import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.market_data_service import MarketDataService
from app.market_data.coverage_source import DatabaseCoverageSource
from app.market_data.subing_reference import SubingReferenceService
from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import BarFrequency
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.trend_band import initial_trend_band_state,step_trend_band
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2
from guiyi_quant.newow.oscillation_channel import OscillationState,step_oscillation
R=Path(__file__).resolve().parent; OLD=R.parent/'htdy-ta-60m-70pct-20261031';CUT=datetime(2026,10,30,7,tzinfo=UTC)
def main(symbol):
 out=R/(symbol+'-features.json');assert not out.exists()
 symbol=symbol.lower()
 settings,_=load_private_execution_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env');root=Path(settings['GUIYI_CANONICAL_DATA_ROOT']);engine=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'options':'-c default_transaction_read_only=on -c statement_timeout=30000'})
 rows=[];proofs=[]
 with Session(engine) as s:
  catalog=MarketCatalog(s,root);mds=MarketDataService(catalog,CanonicalMonthlyStore(root));coverage=DatabaseCoverageSource(s,OLD/'source/data/universe/product_window_starts.csv',history_floor_path=OLD/'source/data/universe/active_history_floor.txt',reuse_session_windows=True);mds.replay_coverage=coverage
  reader=SubingReferenceService(mds,coverage=coverage,active_products=[symbol],historical_window_days=None,physical_context_bars=32)
  owners=ActualDominantResearchSegmentLoader(mds).owner_segments(symbol=symbol,since=date(2023,1,1),through=CUT.date())
  for owner in owners:
   a=max(date(2023,1,1),owner.start_trading_day);b=min(CUT.date(),owner.end_trading_day)
   before=reader.historical_metadata_evidence(symbol=symbol,since=a,through=b);_,raw,_,_=reader.load_historical_inputs(symbol=symbol,frequency=BarFrequency.H1,since=a,through=b,as_of=CUT);after=reader.historical_metadata_evidence(symbol=symbol,since=a,through=b);assert before==after
   proofs.append({'contract':owner.contract,'since':str(a),'through':str(b),'bars':sum(len(b['bars']) for b in raw),'sha256':hashlib.sha256(json.dumps({'raw':raw,'metadata':before},sort_keys=True,default=str).encode()).hexdigest()})
   for block in raw:
    trend=initial_trend_band_state();osc=OscillationState();trs=deque(maxlen=20);prev=None
    count=0
    for x in block['bars']:
     count+=1
     dt=datetime.fromisoformat(str(x['bar_end']));day=date.fromisoformat(str(x['trading_day']));c=D(str(x['close']));h=D(str(x['high']));l=D(str(x['low']))
     if prev is not None:trs.append(max(h-l,abs(h-prev),abs(l-prev)))
     prev=c
     bar=NewowDailyBar(symbol,block['contract'],block['segment_id'],day,dt,D(str(x['open'])),h,l,c,int(D(str(x['volume']))),None,'mds_frozen_features',True,True)
     tr=step_trend_band(trend,bar,profile=NEWOW_TREND_D1_PAGE_V2);trend=tr.state;oscres=step_oscillation(osc,bar);osc=oscres.state
     if a<=day<=b and dt<=CUT:
      rows.append({'contract':block['contract'],'segment':block['segment_id'],'t':int(dt.timestamp()*1e6),'day':str(day),'close':str(c),'atr':str(sum(trs)/20) if len(trs)==20 else None,'trend':str(tr.point.state) if count>=32 else 'UNAVAILABLE','trend_action':str(tr.marker.marker_type) if tr.marker and count>=32 else None,'osc_actions':[str(z.action) for z in oscres.signals] if count>=32 else []})
   print(symbol,owner.contract,len(rows),flush=True);del raw;gc.collect()
 engine.dispose();rows.sort(key=lambda r:r['t']);assert len({(r['contract'],r['t'],r['segment']) for r in rows})==len(rows)
 frozen=(OLD if symbol.upper()=='TA' else R/'ma_data')/symbol.upper()/'evidence/source-proofs.json'
 assert frozen.exists(),'FROZEN_FEATURE_PROOF_MISSING'
 if frozen.exists():
  old=json.loads(frozen.read_text());oldmap={(p['contract'],p['since'],p['through']):p for p in old}
  for p in proofs:
   prior=oldmap[(p['contract'],p['since'],p['through'])];assert prior['input_sha256']==p['sha256'],'FROZEN_FEATURE_INPUT_CHANGED'
 out.write_text(json.dumps({'symbol':symbol,'cutoff':str(CUT),'proofs':proofs,'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path('packages/quant-core/guiyi_quant/newow/trend_band.py'),Path('packages/quant-core/guiyi_quant/newow/oscillation_channel.py'),Path('packages/quant-core/guiyi_quant/newow/profile.py'),Path('packages/quant-core/guiyi_quant/newow/models.py')]},'trend_profile':str(NEWOW_TREND_D1_PAGE_V2),'rows':rows},ensure_ascii=False));print('CAPTURED',len(rows),flush=True)
if __name__=='__main__':main(sys.argv[1].upper())
