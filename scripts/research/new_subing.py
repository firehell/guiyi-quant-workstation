"""Read-only AL/RB/TA research; publish task-local frozen packets, never repair data."""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, cast

from app.market_data.new_subing_research import (
    NewSubingInputError, PRODUCTS, SINCE, THROUGH, load_execution_facts,
    load_new_subing_inputs, safe_diagnostic,
)

DIAGNOSTIC_WINDOWS = (
    ('development',date(2024,10,14),date(2025,10,10)),
    ('historical_validation',date(2025,10,13),date(2026,10,9)),
    ('quarter_1',date(2025,10,13),date(2025,12,31)),
    ('quarter_2',date(2026,1,1),date(2026,3,31)),
    ('quarter_3',date(2026,4,1),date(2026,6,30)),
    ('quarter_4',date(2026,7,1),date(2026,10,9)),
)


def build_packet(*, product: str, scenario: str, code_revision: str,
                 status: str, diagnostic: dict | None = None, source=None,
                 facts_hash: str | None = None, result: dict | None = None) -> dict:
    from guiyi_quant.new_subing import Profile
    p=Profile()
    result=result or {'summary':{'status':status},'decisions':[],'trades':[],'equity':[],'diagnostics':{}}
    diagnostics={**result.get('diagnostics',{}),**(dict(source.diagnostics) if source else {})}
    if diagnostic:
        diagnostics['gap']=diagnostic
    diagnostics.update({'case_parity':'PENDING','original_case_fixture':False,
                        'oos_status':'NOT_PROVEN','independent_account_per_window':True})
    return {'schema_version':1,'metadata':{
        'product':product.upper(),'scenario':scenario,'status':status,
        'strategy_code':p.strategy_code,'formula_version':p.formula_version,
        'profile_id':p.profile_id,'risk_profile_version':p.risk_profile_version,
        'execution_profile_version':p.execution_profile_version,'code_revision':code_revision,
        'requested_since':SINCE.isoformat(),'requested_through':THROUGH.isoformat(),
        'input_snapshot_hash':source.input_snapshot_hash if source else None,
        'execution_facts_hash':facts_hash,'source':'historical_replay','auto_order':False,
        'case_parity':'PENDING','oos_status':'NOT_PROVEN'},
        'summary':result['summary'],'decisions':result.get('decisions',[]),
        'trades':result.get('trades',[]),'equity':result.get('equity',[]),
        'diagnostics':diagnostics,'fills':result.get('fills',[])}


def read_facts(path: Path) -> dict:
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size>32*1024*1024:
                raise ValueError
            raw=os.read(fd,32*1024*1024+1)
        finally:
            os.close(fd)
        value=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value,dict):
            raise ValueError
        return value
    except (OSError,ValueError,UnicodeError):
        raise NewSubingInputError('EXECUTION_FACTS_MISSING') from None


def run_product(market, *, product: str, facts_dir: Path | None, code_revision: str) -> list[dict]:
    from guiyi_quant.new_subing import run_research
    source=None
    try:
        source=load_new_subing_inputs(market,product=product)
        raw=read_facts(facts_dir/f'{product}.json') if facts_dir else None
        executions,facts_hash=load_execution_facts(raw,product=product,bars=source.minute_bars)
    except NewSubingInputError as exc:
        status='EXECUTION_FACTS_MISSING' if exc.code=='EXECUTION_FACTS_MISSING' else 'DATA_INSUFFICIENT'
        return [build_packet(product=product,scenario='baseline',code_revision=code_revision,
            status=status,source=source,diagnostic={'code':exc.code,**exc.diagnostic})]
    packets=[]
    for scenario in ('baseline','double_commission','double_slippage'):
        result=cast(dict[str, Any], run_research(source.bars_by_frequency,executions,scenario=scenario,since=SINCE,through=THROUGH))
        windows: list[dict[str, object]] = []
        for name,since,through in DIAGNOSTIC_WINDOWS:
            selected=tuple(b for b in executions if since<=b.bar.trading_day<=through)
            if not selected:
                windows.append({'name':name,'since':since.isoformat(),'through':through.isoformat(),
                    'summary':{'status':'DATA_INSUFFICIENT'}})
                continue
            diagnostic=cast(dict[str, Any], run_research(source.bars_by_frequency,selected,scenario=scenario,since=since,through=through))
            windows.append({'name':name,'since':since.isoformat(),'through':through.isoformat(),
                'input_snapshot_hash':source.input_snapshot_hash,'summary':diagnostic['summary'],
                'independent_initial_cash':'100000','oos_status':'NOT_PROVEN'})
        result.setdefault('diagnostics',{})['independent_windows']=windows
        packets.append(build_packet(product=product,scenario=scenario,code_revision=code_revision,
            status=result['summary']['status'],source=source,facts_hash=facts_hash,result=result))
    return packets


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols',nargs='+',choices=PRODUCTS,default=list(PRODUCTS))
    parser.add_argument('--project-env',type=Path,required=True)
    parser.add_argument('--facts-dir',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if len(args.symbols)!=len(set(args.symbols)) or not args.out.is_absolute():
        parser.error('exact unique symbols and an absolute task output root are required')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    from app.new_subing_research.store import publish_result
    from app.private_settings import load_private_readonly_settings

    settings,_=load_private_readonly_settings(args.project_env)
    canonical=Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
    code_revision=subprocess.run(['git','rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
    changed=subprocess.run(['git','status','--porcelain','--',
        'packages/quant-core/guiyi_quant/new_subing','services/quant-api/app/market_data/new_subing_research.py',
        'scripts/research/new_subing.py'],check=True,capture_output=True,text=True).stdout
    if changed.strip():
        raise NewSubingInputError('CODE_IDENTITY_UNCOMMITTED')
    engine=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    statuses=[]
    try:
        for product in args.symbols:
            try:
                with Session(engine,autoflush=False) as session,readonly_transaction(session,timeout_seconds=900):
                    market=MarketDataService(MarketCatalog(session,canonical),CanonicalMonthlyStore(canonical))
                    packets=run_product(market,product=product,facts_dir=args.facts_dir,code_revision=code_revision)
            except Exception as exc:
                packets=[build_packet(product=product,scenario='baseline',code_revision=code_revision,
                    status='DATA_INSUFFICIENT',diagnostic=safe_diagnostic(exc,product=product,stage='readonly_input'))]
            for packet in packets:
                frozen=publish_result(args.out,packet)
                meta=frozen['metadata']
                statuses.append(meta['status'])
                print(json.dumps({'product':meta['product'],'scenario':meta['scenario'],
                    'status':meta['status'],'run_id':meta['run_id'],
                    'gap':frozen['diagnostics'].get('gap')},ensure_ascii=False),flush=True)
    finally:
        engine.dispose()
    return 0 if all(s in ('COMPLETED','ROLLOVER_INTERRUPTED') for s in statuses) else 2


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        candidate=getattr(exc,'code',None)
        code=candidate if isinstance(candidate,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{2,100}',candidate) else 'NEW_SUBING_RESEARCH_FAILED'
        print(json.dumps({'status':'BLOCKED','code':code}),flush=True)
        raise SystemExit(1) from None
