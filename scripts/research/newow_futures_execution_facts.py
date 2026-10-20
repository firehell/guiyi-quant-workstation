"""Explicit plan/apply for one-shot bounded provider execution facts, never Canonical writes."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from app.market_data.newow_futures_research import PRODUCTS, SINCE, THROUGH, payload_hash
from scripts.research.new_subing_execution_facts import (
    EXCHANGE_FIELDS, LIMIT_FIELDS, FactsCaptureError, instrument_payload,
    merge_daily_rows, normalize_rows, _write,
)

PARAMETERS_FIELDS = ('long_margin_ratio', 'short_margin_ratio', 'commission_type',
                     'open_commission', 'close_commission', 'close_commission_today')
CODE_PATHS = ('packages/quant-core/guiyi_quant/newow_futures',
              'services/quant-api/app/market_data/newow_futures_research.py',
              'services/quant-api/app/newow_futures_research',
              'scripts/research/newow_futures.py',
              'scripts/research/newow_futures_execution_facts.py',
              'docs/NEWOW_FUTURES_STRATEGY.md')
MAX_BYTES = 32 * 1024 * 1024


def frozen_code_revision() -> str:
    changed = subprocess.run(['git','status','--porcelain','--untracked-files=all','--',*CODE_PATHS],
                             check=True,capture_output=True,text=True).stdout
    if changed.strip():
        raise FactsCaptureError('CODE_IDENTITY_UNCOMMITTED')
    return subprocess.run(['git','rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()


def safe_path(path: Path) -> Path:
    if not path.is_absolute() or '..' in path.parts:
        raise FactsCaptureError('FACTS_PATH_INVALID')
    for part in (path,*path.parents):
        if part.is_symlink():
            raise FactsCaptureError('FACTS_PATH_INVALID')
    return path


def read_json(path: Path) -> dict:
    safe_path(path)
    try:
        descriptor = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise ValueError()
            with os.fdopen(descriptor,'rb',closefd=False) as stream:
                raw = stream.read(MAX_BYTES+1)
            if len(raw) > MAX_BYTES:
                raise ValueError()
        finally:
            os.close(descriptor)
        def pairs(items):
            result = {}
            for key,value in items:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        value = json.loads(raw,object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value,dict):
            raise ValueError()
        return value
    except (OSError,ValueError,UnicodeError):
        raise FactsCaptureError('FACTS_FILE_INVALID') from None


def catalog_preimage(catalog) -> dict:
    products = {}
    for product in PRODUCTS:
        calendar = tuple(catalog.calendar_days(product,SINCE,THROUGH))
        expected_calendar = tuple(SINCE + timedelta(days=i) for i in range((THROUGH-SINCE).days+1))
        if tuple(day for day,_ in calendar) != expected_calendar:
            raise FactsCaptureError('FACTS_PLAN_PREIMAGE_INVALID')
        rows = tuple(catalog.main_map(product,SINCE,THROUGH))
        days = [item.trade_date for item in rows]
        if not rows or days != sorted(set(days)) or tuple(days) != tuple(day for day,trades in calendar if trades):
            raise FactsCaptureError('FACTS_PLAN_PREIMAGE_INVALID')
        contracts = {}
        for item in rows:
            if not re.fullmatch(product.upper()+r'\d{3,4}',item.contract):
                raise FactsCaptureError('FACTS_PLAN_PREIMAGE_INVALID')
            contracts.setdefault(item.contract,[]).append(item.trade_date.isoformat())
        products[product] = {contract:{'start':days[0], 'end':days[-1], 'days':days,
            'requested_days':[day.isoformat() for day,trades in calendar
                              if trades and days[0] <= day.isoformat() <= days[-1]]}
                             for contract,days in sorted(contracts.items())}
    return products


def make_plan(products: dict, *, code_revision: str) -> dict:
    body = {'schema_version':1,'strategy_model':'futures_bidir_v1','source':'rqdata',
            'requested_since':SINCE.isoformat(),'requested_through':THROUGH.isoformat(),
            'code_revision':code_revision,'products':products,
            'parameters_fields':list(PARAMETERS_FIELDS),'exchange_fields':list(EXCHANGE_FIELDS),
            'limit_fields':list(LIMIT_FIELDS),'canonical_write':False,'catalog_write':False,
            'automatic_retry':False,'max_logical_calls':sum(len(v) for v in products.values())*4+2,
            'minimum_quota_bytes':MAX_BYTES,'max_response_bytes':MAX_BYTES,
            'time_semantics':'retrospective_execution_facts'}
    plan = {**body,'plan_hash':payload_hash(body)}
    validate_plan(plan)
    return plan


def validate_plan(plan: dict) -> None:
    try:
        body = {key:value for key,value in plan.items() if key != 'plan_hash'}
        valid = (plan['plan_hash'] == payload_hash(body) and plan['schema_version'] == 1
                 and plan['strategy_model'] == 'futures_bidir_v1' and plan['source'] == 'rqdata'
                 and plan['requested_since'] == SINCE.isoformat()
                 and plan['requested_through'] == THROUGH.isoformat()
                 and re.fullmatch(r'[0-9a-f]{40}',plan['code_revision'])
                 and set(plan['products']) == set(PRODUCTS)
                 and plan['canonical_write'] is False and plan['catalog_write'] is False
                 and plan['automatic_retry'] is False
                 and plan['parameters_fields'] == list(PARAMETERS_FIELDS)
                 and plan['exchange_fields'] == list(EXCHANGE_FIELDS)
                 and plan['limit_fields'] == list(LIMIT_FIELDS)
                 and plan['minimum_quota_bytes'] == MAX_BYTES and plan['max_response_bytes'] == MAX_BYTES
                 and plan['max_logical_calls'] == sum(len(v) for v in plan['products'].values())*4+2)
        if not valid:
            raise ValueError()
        for product,contracts in plan['products'].items():
            if not contracts:
                raise ValueError()
            all_days = []
            for contract,span in contracts.items():
                days = span['days']
                requested_days = span['requested_days']
                if (not re.fullmatch(product.upper()+r'\d{3,4}',contract)
                        or not days or days != sorted(set(days))
                        or span['start'] != days[0] or span['end'] != days[-1]
                        or not requested_days or requested_days != sorted(set(requested_days))
                        or not set(days) <= set(requested_days)
                        or requested_days[0] != span['start'] or requested_days[-1] != span['end']
                        or any(not SINCE <= date.fromisoformat(d) <= THROUGH for d in requested_days)):
                    raise ValueError()
                all_days.extend(days)
            if len(all_days) != len(set(all_days)):
                raise ValueError()
            for span in contracts.values():
                if span['requested_days'] != sorted(day for day in all_days
                                                    if span['start'] <= day <= span['end']):
                    raise ValueError()
    except (ValueError,KeyError,TypeError,AttributeError):
        raise FactsCaptureError('FACTS_PLAN_INVALID') from None


def _catalog_snapshot(settings: dict) -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.market_data.catalog import MarketCatalog
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    try:
        with Session(engine,autoflush=False) as session,readonly_transaction(session):
            return catalog_preimage(MarketCatalog(session,Path(settings['GUIYI_CANONICAL_DATA_ROOT'])))
    finally:
        engine.dispose()


def capture(plan: dict, *, settings: dict, out: Path, api_factory=None) -> None:
    """A new attempt directory and durable started journal enforce no implicit retries."""
    validate_plan(plan)
    safe_path(out)
    out.mkdir(parents=True,exist_ok=False)
    _write(out/'provider-plan.json',plan)
    calls = 0
    def record(state,method,contract=None,code=None):
        nonlocal calls
        if state == 'started':
            calls += 1
            if calls > plan['max_logical_calls']:
                raise FactsCaptureError('PROVIDER_CALL_BUDGET_EXCEEDED')
        value = {'sequence':calls,'state':state,'method':method,'contract':contract,
                 'at':datetime.now(UTC).isoformat()}
        if code:
            value['code'] = code
        descriptor = os.open(out/'journal.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        with os.fdopen(descriptor,'a') as stream:
            stream.write(json.dumps(value)+'\n')
            stream.flush()
            os.fsync(stream.fileno())
    def call(method, function, contract=None):
        record('started',method,contract)
        response = function()
        record('completed',method,contract)
        return response
    def snapshot(contracts):
        return {'schema_version':1,'source':'rqdata','captured_at':datetime.now(UTC).isoformat(),
                'plan_hash':plan['plan_hash'],'contracts':contracts,
                'time_semantics':'retrospective_execution_facts'}
    try:
        if api_factory is None:
            from app.market_data.rqdata_adapter import RQDataClient
            def api_factory():
                return RQDataClient(settings=settings).api
        api = call('init',api_factory)
        quota = call('user.get_quota',api.user.get_quota)
        if not isinstance(quota,dict) or not all(k in quota for k in ('bytes_limit','bytes_used')):
            raise FactsCaptureError('PROVIDER_BUDGET_UNPROVEN')
        remaining = Decimal(str(quota['bytes_limit']))-Decimal(str(quota['bytes_used']))
        if not remaining.is_finite() or remaining < MAX_BYTES:
            raise FactsCaptureError('PROVIDER_BUDGET_INSUFFICIENT')
        instruments = {}
        # Capture every instrument first so later partial fee failures preserve ticks.
        for product,contracts in plan['products'].items():
            instruments[product] = {}
            for contract in contracts:
                instrument = instrument_payload(call('instruments',lambda:api.instruments(contract),contract),contract)
                instruments[product][contract] = {'instrument':instrument}
                _write(out/f'{contract}-instrument.json',instrument)
            _write(out/f'{product}-ticks.json',snapshot(instruments[product]))
        for product,contracts in plan['products'].items():
            captured = {}
            for contract,span in contracts.items():
                parameters = normalize_rows(call('futures.get_trading_parameters',lambda:
                    api.futures.get_trading_parameters(contract,start_date=span['start'],end_date=span['end'],
                                                       fields=list(PARAMETERS_FIELDS)),contract),
                    contract,span['requested_days'],list(PARAMETERS_FIELDS))
                daily = normalize_rows(call('futures.get_exchange_daily',lambda:
                    api.futures.get_exchange_daily(contract,start_date=span['start'],end_date=span['end'],
                                                   fields=list(EXCHANGE_FIELDS)),contract),
                    contract,span['requested_days'],list(EXCHANGE_FIELDS))
                limits = normalize_rows(call('get_price:daily_limits_only',lambda:
                    api.get_price(contract,start_date=span['start'],end_date=span['end'],frequency='1d',
                                  fields=list(LIMIT_FIELDS),adjust_type='none',expect_df=True),contract),
                    contract,span['requested_days'],list(LIMIT_FIELDS))
                provider_daily = merge_daily_rows(daily,limits)
                needed = set(span['days'])
                body = {'start':span['start'],'end':span['end'],**instruments[product][contract],
                        'parameters':[row for row in parameters if row['date'] in needed],
                        'daily':[row for row in provider_daily if row['date'] in needed],
                        'field_sources':{'settlement':'futures.get_exchange_daily',
                            'prev_settlement':'futures.get_exchange_daily',
                            'limit_up':'get_price:1d:limit_up','limit_down':'get_price:1d:limit_down'}}
                _write(out/f'{contract}-provider.json',{**body,
                    'provider_response':{'parameters':parameters,'daily':provider_daily},
                    'selection':{'owner_days':span['days'],'requested_days':span['requested_days']}})
                captured[contract] = body
            _write(out/f'{product}.json',snapshot(captured))
    except Exception as exc:
        code = getattr(exc,'code','PROVIDER_CAPTURE_FAILED')
        if not isinstance(code,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,100}',code):
            code = 'PROVIDER_CAPTURE_FAILED'
        record('failed','capture',code=code)
        raise FactsCaptureError(code) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command',required=True)
    planning = subparsers.add_parser('plan')
    planning.add_argument('--project-env',type=Path,required=True)
    planning.add_argument('--out',type=Path,required=True,help='new immutable plan JSON file')
    applying = subparsers.add_parser('apply')
    applying.add_argument('--project-env',type=Path,required=True)
    applying.add_argument('--plan',type=Path,required=True)
    applying.add_argument('--out',type=Path,required=True,help='fresh attempt directory')
    args = parser.parse_args()
    safe_path(args.out)
    revision = frozen_code_revision()
    if args.command == 'plan':
        from app.private_settings import load_private_readonly_settings
        settings,_ = load_private_readonly_settings(args.project_env)
        plan = make_plan(_catalog_snapshot(settings),code_revision=revision)
        _write(args.out,plan)
        print(json.dumps({'status':'PLANNED','plan_hash':plan['plan_hash'],
                          'max_logical_calls':plan['max_logical_calls']}))
    else:
        plan = read_json(args.plan)
        validate_plan(plan)
        if plan['code_revision'] != revision:
            raise FactsCaptureError('FACTS_PLAN_CODE_CHANGED')
        from app.private_settings import load_private_execution_settings
        settings,_ = load_private_execution_settings(args.project_env)
        if _catalog_snapshot(settings) != plan['products']:
            raise FactsCaptureError('FACTS_PLAN_PREIMAGE_CHANGED')
        capture(plan,settings=settings,out=args.out)
        print(json.dumps({'status':'CAPTURED','plan_hash':plan['plan_hash']}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        candidate = getattr(exc,'code',None)
        code = candidate if isinstance(candidate,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{2,100}',candidate) else 'PROVIDER_CAPTURE_FAILED'
        print(json.dumps({'status':'BLOCKED','code':code}),flush=True)
        raise SystemExit(1) from None
