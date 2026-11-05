"""Read-only physical warmup and fixed ATR-scale research; never enables accounts."""
from pathlib import Path
from datetime import date
from dataclasses import asdict
from decimal import Decimal as D
from statistics import median
import argparse,json
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.private_settings import load_private_readonly_settings
from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.market_data_service import MarketDataService
from app.market_data.new_subing_research import _wire
from app.subing_model.factors import Factors
PRODUCTS='jm lc rb sa fg ma ec v pr ta ur sh sc cj'.split()

from app.subing_model.market import prefix

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--through',type=date.fromisoformat,required=True);parser.add_argument('--out',type=Path,required=True);a=parser.parse_args()
    a.out.mkdir(parents=True,exist_ok=False)
    settings,_=load_private_readonly_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    engine=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5});results=[]
    try:
        with Session(engine,autoflush=False) as db,readonly_transaction(db,timeout_seconds=900):
            root=Path(settings['GUIYI_CANONICAL_DATA_ROOT']);cat=MarketCatalog(db,root);m=MarketDataService(cat,CanonicalMonthlyStore(root))
            for product in PRODUCTS:
                mappings=cat.main_map(product,a.through,a.through)
                if len(mappings)!=1:raise ValueError('MAPPING_MISSING')
                contract=mappings[0].contract;f=Factors(contract);warm={};sources={};atr=[];errors={}
                for freq in ('1d','30m','60m'):
                    try:
                        bars,proof=prefix(m,product,contract,freq,a.through);warm[freq]=[asdict(b) for b in bars];sources[freq]=proof
                        for b in bars:
                            r=f.step(freq,b)
                            if freq=='30m' and r and r['atr14'] is not None:atr.append(r['atr14'])
                    except Exception as exc:
                        errors[freq]=getattr(exc,'code',None) or type(exc).__name__
                sample=atr[-120:];scale=median(sample) if len(sample)==120 else None
                result=dict(product=product,contract=contract,through=a.through,status='OBSERVATION_READY' if not errors else 'WARMUP_INCOMPLETE',errors=errors,
                    sources=sources,warmup=warm,atr30_median120=scale,atr30_samples=len(sample),execution_enabled=False,execution_facts='NOT_VERIFIED',
                    observation=dict(regime=f.frame['regime'] if f.frame else 'UNKNOWN',daily=f.daily[-1] if f.daily else None,hourly=f.hourly,structure=f.structure_point))
                (a.out/(product+'.json')).write_text(json.dumps(_wire(result),ensure_ascii=False,separators=(',',':')))
                results.append({k:v for k,v in result.items() if k!='warmup'});print(product,result['status'],errors,flush=True)
    finally:engine.dispose()
    jm=next(r['atr30_median120'] for r in results if r['product']=='jm')
    for r in results:
        ratio=r['atr30_median120']/jm if jm and r['atr30_median120'] else None
        r['normalization_candidate']=dict(status='RESEARCH_ONLY_OWNER_REVIEW_REQUIRED',method='JM anchored median ATR14 / previous 120 completed 30m; fixed one snapshot, no optimization',ratio=ratio,
            near_axis=D(4)*ratio if ratio else None,extreme_macd=D(17)*ratio if ratio else None,stop_buffer=D(13)*ratio if ratio else None,
            tick_rounding='NOT_APPLIED_EXECUTION_FACTS_REQUIRED',account_risk='NOT_EQUALIZED',oos='NOT_PROVEN')
    (a.out/'readiness.json').write_text(json.dumps(_wire(results),ensure_ascii=False,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(dict(status='PREPARE_FAILED',error_type=type(exc).__name__)));raise SystemExit(2) from None
