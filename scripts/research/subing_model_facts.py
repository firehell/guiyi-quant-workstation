"""Bounded current JM execution facts, separate from retrospective daily data."""
from pathlib import Path
from datetime import date,datetime,UTC,timedelta
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
import argparse,json,re
from scripts.research.new_subing_execution_facts import instrument_payload,normalize_rows,_write,FactsCaptureError
from app.market_data.new_subing_research import payload_hash

MARGIN_FIELDS=['long_margin_ratio','short_margin_ratio']
FEE_FIELDS=['commission_type','open_commission','close_commission','close_commission_today']
FIELDS=MARGIN_FIELDS+FEE_FIELDS
PRICE_FIELDS=['prev_settlement','limit_up','limit_down']
CAPTURE_VERSION='rqdata_current_constraints_model_fee_v2'
FEE_POLICY='current_complete_else_previous_trading_day_v1'


def previous_trading_day(calendar,day):
    facts=dict(calendar)
    if len(facts)!=len(calendar) or facts.get(day) is not True:raise FactsCaptureError('CALENDAR_COVERAGE_MISSING')
    candidates=[d for d,is_open in calendar if is_open and d<day]
    if not candidates:raise FactsCaptureError('CALENDAR_COVERAGE_MISSING')
    previous=max(candidates)
    required={previous+timedelta(days=i) for i in range((day-previous).days+1)}
    if not required<=facts.keys():raise FactsCaptureError('CALENDAR_COVERAGE_MISSING')
    return previous


def snapshot_daily(quote,contract,day,windows,captured_at,tick_size):
    """Bind quote constraints to the authoritative trading-day Session envelope.

    A snapshot may persist through an intraday break. It need not be executable;
    only its static limits/settlement are used. Never use its last/OHLC to fill.
    """
    if getattr(quote,'order_book_id',None)!=contract:raise FactsCaptureError('PROVIDER_CONTRACT_MISMATCH')
    try:
        at=datetime.fromisoformat(str(quote.datetime))
        if at.tzinfo is None:at=at.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        if not windows or not min(w.start for w in windows)<=at<=max(w.end for w in windows):raise ValueError
        if at>captured_at:raise ValueError
        supplied=getattr(quote,'trading_date',None)
        if supplied is not None and date.fromisoformat(str(supplied)[:10])!=day:raise ValueError
        values={k:Decimal(str(getattr(quote,k))) for k in PRICE_FIELDS}
        if any(not v.is_finite() or v<=0 for v in values.values()):raise ValueError
        if not values['limit_down']<=values['prev_settlement']<=values['limit_up'] or values['limit_down']>=values['limit_up']:raise ValueError
        tick=Decimal(tick_size)
        if any(values[k]%tick for k in ('limit_up','limit_down')):raise ValueError
        return dict(date=str(day),**{k:str(v) for k,v in values.items()}),at.isoformat()
    except (AttributeError,TypeError,ValueError,InvalidOperation):raise FactsCaptureError('CURRENT_SNAPSHOT_FACTS_INVALID') from None


def public_value(v):
    if v is None:return None
    if hasattr(v,'isoformat'):return v.isoformat()
    if isinstance(v,str):return v
    try:return str(v) if Decimal(str(v)).is_finite() else None
    except InvalidOperation:return None


def current_parameter_evidence(frame,contract,day,fields=FIELDS):
    rows=[] if frame is None else frame.reset_index().to_dict('records')
    selected=[{k:public_value(r.get(k)) for k in ['order_book_id','trading_date','date',*fields]} for r in rows]
    matching=[r for r in selected if r['order_book_id']==contract and str(r['trading_date'] or r['date'])[:10]==str(day)]
    missing=[k for k in fields if len(matching)!=1 or matching[0][k] is None]
    return dict(rows=selected,missing_fields=missing)


def collect(api,call,contract,day,windows,out,previous_day):
    instrument=instrument_payload(call('instruments',lambda:api.instruments(contract)),contract)
    # Omit both dates intentionally: provider's current-effective branch differs
    # from its historical date-range branch. Validate the returned date exactly.
    raw=call('current_parameters',lambda:api.futures.get_trading_parameters(contract,fields=FIELDS))
    evidence=current_parameter_evidence(raw,contract,day)
    _write(out/'current-parameters.json',evidence)
    quote=call('current_snapshot',lambda:api.current_snapshot(contract))
    _write(out/'current-snapshot.json',{k:public_value(getattr(quote,k,None)) for k in ['order_book_id','datetime','trading_date',*PRICE_FIELDS]})
    margins=normalize_rows(raw,contract,[str(day)],MARGIN_FIELDS)
    if any(not 0<Decimal(margins[0][k])<=1 for k in MARGIN_FIELDS):raise FactsCaptureError('CURRENT_MARGIN_INVALID')
    current=evidence['rows'][0]
    if current['commission_type'] is not None and current['commission_type'] not in ('by_money','by_volume'):raise FactsCaptureError('CURRENT_FEE_INVALID')
    if any(current[k] is not None and Decimal(current[k])<0 for k in FEE_FIELDS[1:]):raise FactsCaptureError('CURRENT_FEE_INVALID')
    assumed=bool(set(evidence['missing_fields'])&set(FEE_FIELDS))
    if assumed:
        if previous_day>=day:raise FactsCaptureError('PREVIOUS_TRADING_DAY_INVALID')
        previous_raw=call('previous_trading_day_fees',lambda:api.futures.get_trading_parameters(contract,start_date=str(previous_day),end_date=str(previous_day),fields=FEE_FIELDS))
        _write(out/'previous-fees.json',current_parameter_evidence(previous_raw,contract,previous_day,FEE_FIELDS))
        fees=normalize_rows(previous_raw,contract,[str(previous_day)],FEE_FIELDS)
    else:fees=normalize_rows(raw,contract,[str(day)],FEE_FIELDS)
    if fees[0]['commission_type'] not in ('by_money','by_volume'):raise FactsCaptureError('FEE_TYPE_INVALID')
    parameters=[dict(margins[0],**{k:fees[0][k] for k in FEE_FIELDS})]
    captured=datetime.now(UTC)
    daily,source_at=snapshot_daily(quote,contract,day,windows,captured,instrument['tick_size'])
    return dict(schema_version=1,source='rqdata',capture_version=CAPTURE_VERSION,captured_at=captured.isoformat(),time_semantics='current_effective_execution_facts',
        fee_policy_version=FEE_POLICY,fee_assumption=dict(assumed=assumed,source_day=str(previous_day if assumed else day),target_day=str(day),contract=contract,source_parameters=fees,reason='CURRENT_FEES_MISSING' if assumed else 'CURRENT_FEES_COMPLETE'),
        contracts={contract:dict(start=str(day),end=str(day),instrument=instrument,parameters=parameters,daily=[daily],
            field_sources={**{k:'current_snapshot' for k in PRICE_FIELDS},'margin':'futures.get_trading_parameters:current','fees':'futures.get_trading_parameters:'+str(previous_day if assumed else day),
                          'snapshot_at':source_at,'trading_day':'authoritative_session_envelope'})})


def main():
    p=argparse.ArgumentParser();p.add_argument('--contract',required=True);p.add_argument('--day',type=date.fromisoformat,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if not re.fullmatch(r'JM[0-9]{4}',a.contract):raise ValueError('CONTRACT_INVALID')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.private_settings import load_private_execution_settings
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    settings,_=load_private_execution_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    engine=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    def metadata():
        with Session(engine,autoflush=False) as s,readonly_transaction(s):
            root=Path(settings['GUIYI_CANONICAL_DATA_ROOT']);catalog=MarketCatalog(s,root);maps=catalog.main_map('jm',a.day,a.day)
            if len(maps)!=1 or maps[0].contract!=a.contract:raise ValueError('OWNER_MAPPING_INVALID')
            calendar=catalog.calendar_days('jm',a.day-timedelta(days=14),a.day)
            previous=previous_trading_day(calendar,a.day)
            windows=MarketDataService(catalog,CanonicalMonthlyStore(root)).session_windows(symbol='jm',trading_day=a.day)
            return windows,previous
    try:
        windows,previous=metadata();a.out.mkdir(parents=True,exist_ok=False)
        plan=dict(capture_version=CAPTURE_VERSION,contract=a.contract,day=str(a.day),max_calls=6,fee_policy_version=FEE_POLICY,previous_trading_day=str(previous),parameters='current_without_dates',price_constraints='current_snapshot',canonical_write=False,catalog_write=False,automatic_retry=False)
        _write(a.out/'plan.json',dict(plan,plan_hash=payload_hash(plan)))
        calls=0
        def call(name,fn):
            nonlocal calls
            calls+=1
            if calls>6:raise ValueError('CALL_BUDGET')
            with (a.out/'journal.jsonl').open('a') as f:f.write(json.dumps(dict(sequence=calls,method=name,status='STARTED',at=datetime.now(UTC).isoformat()))+'\n')
            result=fn()
            with (a.out/'journal.jsonl').open('a') as f:f.write(json.dumps(dict(sequence=calls,method=name,status='COMPLETED'))+'\n')
            return result
        from app.market_data.rqdata_adapter import RQDataClient
        api=call('init',lambda:RQDataClient(settings=settings).api);quota=call('quota',api.user.get_quota)
        if quota['bytes_limit']-quota['bytes_used']<1024*1024:raise ValueError('PROVIDER_BUDGET_INSUFFICIENT')
        result=collect(api,call,a.contract,a.day,windows,a.out,previous)
        if (windows,previous)!=metadata():raise ValueError('SESSION_CHANGED_DURING_CAPTURE')
        _write(a.out/'jm.json',dict(result,plan_hash=payload_hash(plan)))
        print(json.dumps(dict(status='CAPTURED',contract=a.contract,day=str(a.day),calls=calls)))
    finally:engine.dispose()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(dict(status='FACTS_UNAVAILABLE',error_type=type(exc).__name__,code=getattr(exc,'code',None))));raise SystemExit(2) from None
