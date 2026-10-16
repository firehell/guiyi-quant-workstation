"""One-shot bounded provider facts capture for approved New SuBing research.

No Canonical/Catalog/config writes, automatic retry, or credential output.
The separate offline replay CLI never calls this collector implicitly.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import re
from typing import Any

from app.market_data.new_subing_research import PRODUCTS, SINCE, THROUGH, payload_hash

EXCHANGE_FIELDS = ('settlement', 'prev_settlement')
LIMIT_FIELDS = ('limit_up', 'limit_down')


class FactsCaptureError(ValueError):
    def __init__(self,code: str):
        self.code=code
        super().__init__(code)


def normalize_rows(frame: Any, contract: str, expected_days: list[str], fields: list[str]) -> list[dict]:
    if frame is None or frame.empty:
        raise FactsCaptureError('EXECUTION_FACTS_MISSING')
    reset=frame.reset_index() if 'order_book_id' not in frame.columns else frame
    result=[]
    for row in reset.to_dict(orient='records'):
        if row.get('order_book_id')!=contract:
            raise FactsCaptureError('PROVIDER_CONTRACT_MISMATCH')
        key='trading_date' if 'trading_date' in row else ('date' if 'date' in row else 'datetime')
        day=date.fromisoformat(str(row[key])[:10]).isoformat()
        values={'date':day}
        for field in fields:
            value=row[field]
            if field in ('commission_type','trade_unit','price_unit'):
                if not isinstance(value,str) or not value.strip():
                    raise FactsCaptureError('EXECUTION_FACTS_MISSING')
                values[field]=value
            else:
                number=Decimal(str(value))
                if not number.is_finite() or number<0:
                    raise FactsCaptureError('EXECUTION_FACTS_MISSING')
                values[field]=str(number)
        result.append(values)
    days=[r['date'] for r in result]
    if len(days)!=len(set(days)) or sorted(days)!=expected_days:
        raise FactsCaptureError('PROVIDER_DATE_COVERAGE_MISMATCH')
    return sorted(result,key=lambda r:r['date'])


def merge_daily_rows(daily: list[dict], limits: list[dict]) -> list[dict]:
    if [r['date'] for r in daily] != [r['date'] for r in limits]:
        raise FactsCaptureError('PROVIDER_DATE_COVERAGE_MISMATCH')
    return [{**a, **b} for a, b in zip(daily, limits)]


def instrument_payload(instrument: Any, contract: str) -> dict:
    if instrument is None or instrument.order_book_id!=contract:
        raise FactsCaptureError('PROVIDER_CONTRACT_MISMATCH')
    tick=instrument.tick_size
    tick=tick() if callable(tick) else tick
    multiplier=instrument.contract_multiplier
    tick,multiplier=Decimal(str(tick)),Decimal(str(multiplier))
    if not tick.is_finite() or not multiplier.is_finite() or tick<=0 or multiplier<=0:
        raise FactsCaptureError('EXECUTION_FACTS_MISSING')
    return {'order_book_id':contract,'tick_size':str(tick),'contract_multiplier':str(multiplier)}


def _write(path: Path,value: object) -> None:
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>32*1024*1024:
        raise FactsCaptureError('PROVIDER_RESPONSE_BUDGET_EXCEEDED')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--project-env',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if not args.plan.is_absolute() or args.plan.is_symlink() or not args.out.is_absolute() or args.out.is_symlink():
        raise FactsCaptureError('FACTS_PATH_INVALID')
    plan=json.loads(args.plan.read_text())
    supplied=plan.pop('plan_hash',None)
    if supplied!=payload_hash(plan) or set(plan['products'])!=set(PRODUCTS) or plan['canonical_write'] or plan['catalog_write'] or plan['automatic_retry']:
        raise FactsCaptureError('FACTS_PLAN_INVALID')
    plan['plan_hash']=supplied
    count=sum(len(v) for v in plan['products'].values())
    if plan['max_logical_calls']!=count*4+2 or tuple(plan.get('exchange_fields', ())) != EXCHANGE_FIELDS or tuple(plan.get('limit_fields', ())) != LIMIT_FIELDS:
        raise FactsCaptureError('FACTS_PLAN_INVALID')
    for product,contracts in plan['products'].items():
        for contract,span in contracts.items():
            days=span['days']
            if not re.fullmatch(product.upper()+r'\d{3,4}',contract) or days!=sorted(set(days)) or not days:
                raise FactsCaptureError('FACTS_PLAN_INVALID')
            if span['start']!=days[0] or span['end']!=days[-1] or date.fromisoformat(days[0])<SINCE or date.fromisoformat(days[-1])>THROUGH:
                raise FactsCaptureError('FACTS_PLAN_INVALID')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.url import normalize_database_url
    from app.db.readonly import readonly_transaction
    from app.market_data.catalog import MarketCatalog
    from app.private_settings import load_private_execution_settings
    settings,_=load_private_execution_settings(args.project_env)
    engine=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    try:
        with Session(engine,autoflush=False) as session,readonly_transaction(session):
            catalog=MarketCatalog(session,Path(settings['GUIYI_CANONICAL_DATA_ROOT']))
            for product in PRODUCTS:
                current: dict[str, list[str]] = {}
                for mapping in catalog.main_map(product,SINCE,THROUGH):
                    current.setdefault(mapping.contract,[]).append(mapping.trade_date.isoformat())
                if current!={k:v['days'] for k,v in plan['products'][product].items()}:
                    raise FactsCaptureError('FACTS_PLAN_PREIMAGE_CHANGED')
    finally:
        engine.dispose()
    # New directory is the attempt boundary. Existing/failed attempts cannot be reused.
    args.out.mkdir(parents=True,exist_ok=False)
    _write(args.out/'provider-plan.json',plan)
    journal=args.out/'journal.jsonl'
    calls=0
    def record(state,method,contract=None,code=None):
        nonlocal calls
        if state=='started':
            calls+=1
            if calls>plan['max_logical_calls']:
                raise FactsCaptureError('PROVIDER_CALL_BUDGET_EXCEEDED')
        value={'sequence':calls,'state':state,'method':method,'contract':contract,
               'at':datetime.now(UTC).isoformat()}
        if code:
            value['code']=code
        fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a') as f:
            f.write(json.dumps(value,ensure_ascii=False)+'\n')
            f.flush()
            os.fsync(f.fileno())
    try:
        from app.market_data.rqdata_adapter import RQDataClient
        record('started','init')
        api=RQDataClient(settings=settings).api
        record('completed','init')
        record('started','user.get_quota')
        quota=api.user.get_quota()
        if not isinstance(quota,dict) or not all(k in quota for k in ('bytes_limit','bytes_used')):
            raise FactsCaptureError('PROVIDER_BUDGET_UNPROVEN')
        if Decimal(str(quota['bytes_limit']))-Decimal(str(quota['bytes_used']))<32*1024*1024:
            raise FactsCaptureError('PROVIDER_BUDGET_INSUFFICIENT')
        record('completed','user.get_quota')
        for product in PRODUCTS:
            captured={}
            for contract,span in plan['products'][product].items():
                record('started','instruments',contract)
                instrument=instrument_payload(api.instruments(contract),contract)
                record('completed','instruments',contract)
                record('started','futures.get_trading_parameters',contract)
                parameters=normalize_rows(api.futures.get_trading_parameters(contract,
                    start_date=span['start'],end_date=span['end'],fields=plan['parameters_fields']),
                    contract,span['days'],plan['parameters_fields'])
                record('completed','futures.get_trading_parameters',contract)
                record('started','futures.get_exchange_daily',contract)
                daily=normalize_rows(api.futures.get_exchange_daily(contract,start_date=span['start'],
                    end_date=span['end'],fields=list(EXCHANGE_FIELDS)),contract,span['days'],list(EXCHANGE_FIELDS))
                record('completed','futures.get_exchange_daily',contract)
                record('started','get_price:daily_limits_only',contract)
                limits=normalize_rows(api.get_price(contract,start_date=span['start'],end_date=span['end'],
                    frequency='1d',fields=list(LIMIT_FIELDS),adjust_type='none',expect_df=True),
                    contract,span['days'],list(LIMIT_FIELDS))
                record('completed','get_price:daily_limits_only',contract)
                daily=merge_daily_rows(daily,limits)
                body={'start':span['start'],'end':span['end'],'instrument':instrument,
                      'parameters':parameters,'daily':daily,
                      'field_sources':{'settlement':'futures.get_exchange_daily',
                          'prev_settlement':'futures.get_exchange_daily',
                          'limit_up':'get_price:1d:limit_up','limit_down':'get_price:1d:limit_down'}}
                _write(args.out/f'{contract}-provider.json',body)
                captured[contract]=body
                print(json.dumps({'product':product,'contract':contract,'status':'CAPTURED','days':len(span['days'])}),flush=True)
            _write(args.out/f'{product}.json',{'schema_version':1,'source':'rqdata',
                'captured_at':datetime.now(UTC).isoformat(),'plan_hash':supplied,'contracts':captured,
                'time_semantics':'retrospective_execution_facts'})
    except Exception as exc:
        code=getattr(exc,'code','PROVIDER_CAPTURE_FAILED')
        if not isinstance(code,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,100}',code):
            code='PROVIDER_CAPTURE_FAILED'
        record('failed','capture',code=code)
        raise FactsCaptureError(code) from None


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        code=getattr(exc,'code','PROVIDER_CAPTURE_FAILED')
        print(json.dumps({'status':'BLOCKED','code':code}),flush=True)
        raise SystemExit(1) from None
