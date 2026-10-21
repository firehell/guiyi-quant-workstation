"""Run the frozen four-product, six-frequency, eight-variant futures research matrix."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import json
from pathlib import Path
import re
from typing import Iterator

from app.market_data.newow_futures_research import (
    NewowFuturesInputError, PRODUCTS, SINCE, THROUGH, load_execution_facts,
    load_newow_futures_inputs, load_reference_ticks, payload_hash, safe_diagnostic,
)
from app.market_data.new_subing_research import _wire
from guiyi_quant.newow_futures.contracts import (
    FREQUENCIES, MODEL, VERSIONS, Profile, Variant,
)
from scripts.research.newow_futures_execution_facts import (
    FactsCaptureError, frozen_code_revision, read_json, safe_path,
)

SCENARIOS = ('baseline','double_commission','double_slippage')
DIAGNOSTIC_WINDOWS = (
    ('first_year',date(2024,10,14),date(2025,10,10)),
    ('second_year',date(2025,10,13),THROUGH),
    ('quarter_1',date(2025,10,13),date(2025,12,31)),
    ('quarter_2',date(2026,1,1),date(2026,3,31)),
    ('quarter_3',date(2026,4,1),date(2026,6,30)),
    ('quarter_4',date(2026,7,1),THROUGH),
)


def blocked_summary(status: str) -> dict:
    return {'status':status,'initial_cash':'100000','final_equity':None,
            'account_return_pct':None,'annual_eligible':False}


def blocked_reference(status: str) -> dict:
    return {'summary':{'status':status,'executable':False},'snapshot':{'side':'UNAVAILABLE','reason':status,'executable':False},
            'actions':[],'trades':[],'equity':[],'chart':{'bars':[],'frames':[]}}


def build_packet(*, product: str, profile: Profile, scenario: str, code_revision: str,
                 status: str, source=None, facts_hash: str | None = None,
                 result: dict | None = None, reference: dict | None = None,
                 diagnostic: dict | None = None, as_of: str | None = None) -> dict:
    result = result or {'summary':blocked_summary(status)}
    reference = reference or result.get('reference') or blocked_reference(status)
    chart = result.get('chart') or reference.get('chart') or {'bars':[],'frames':[]}
    chart = {**chart,'bars':chart.get('bars',[])[-2000:], 'frames':chart.get('frames',[])[-2000:]}
    diagnostics = {**(dict(source.diagnostics) if source else {}), **result.get('diagnostics',{}),
                   'oos_status':'OOS_NOT_PROVEN','independent_account_per_window':True,
                   'chart_limit':2000,'summary_uses_full_window':True}
    if source:
        diagnostics['gaps_by_frequency'] = dict(source.gaps_by_frequency)
    if diagnostic:
        diagnostics['gap'] = diagnostic
    verified_times = [bar.confirmed_at for rows in source.bars_by_frequency.values()
                      for bar in rows if bar.observation_eligible] if source else []
    verified_input = bool(verified_times)
    if as_of is None and verified_times:
        as_of = max(verified_times).isoformat()
    return _wire({'schema_version':1,'metadata':{
        'strategy_model':MODEL,'strategy':profile.variant.value,'product':product.upper(),
        'frequency':profile.frequency,'scenario':scenario,'profile_id':profile.profile_id,
        'versions':dict(VERSIONS),'initial_cash':'100000','code_revision':code_revision,
        'requested_since':SINCE.isoformat(),'requested_through':THROUGH.isoformat(),
        'input_snapshot_hash':source.input_snapshot_hash if source else None,
        'execution_facts_hash':facts_hash,'source':'historical_replay','auto_order':False,
        'as_of':as_of or datetime.now(UTC).isoformat(),
        'as_of_kind':'verified_completed_input' if verified_input else 'publication_time_only',
        'generated_at':datetime.now(UTC).isoformat(),
        'status':status,'oos_status':'OOS_NOT_PROVEN'},
        'summary':result['summary'],'reference':{k:v for k,v in reference.items() if k != 'chart'},'chart':chart,
        'decisions':result.get('decisions',[]),'fills':result.get('fills',[]),
        'trades':result.get('trades',[]),'equity':result.get('equity',[]),'diagnostics':diagnostics})


def required_frequencies(profile: Profile) -> tuple[str,...]:
    # Higher inputs are explicit optional confirmation, never an invented base gate.
    # Their absence blocks the relevant upgrade/overnight/test3 entry in the kernel.
    return (profile.frequency,)


def read_product_facts(facts_dir: Path | None, product: str) -> tuple[dict | None,dict | None]:
    if facts_dir is None:
        return None,None
    raw = ticks = None
    try:
        raw = read_json(facts_dir/f'{product}.json')
    except FactsCaptureError:
        pass
    if raw is not None:
        ticks = raw
    else:
        try:
            ticks = read_json(facts_dir/f'{product}-ticks.json')
        except FactsCaptureError:
            pass
    return raw,ticks


def run_matrix(*, product: str, source, facts_dir: Path | None, code_revision: str,
               input_error: dict | None = None) -> Iterator[dict]:
    """Pure replay after the caller has released its read-only Catalog transaction."""
    # Missing implementation is a hard failure, never 144 plausible placeholder results.
    from guiyi_quant.newow_futures.engine import run_research
    from guiyi_quant.newow_futures.features import prepare_features
    from guiyi_quant.newow_futures.reference import run_reference

    known = [bar.confirmed_at for rows in source.bars_by_frequency.values() for bar in rows
             if bar.observation_eligible] if source else []
    as_of = max(known).isoformat() if known else datetime.now(UTC).isoformat()
    raw,tick_raw = read_product_facts(facts_dir,product)
    executions, facts_hash, execution_gap, ticks = (),None,None,{}
    if source is not None:
        try:
            executions,facts_hash = load_execution_facts(raw,product=product,bars=source.minute_bars)
        except NewowFuturesInputError as exc:
            execution_gap = {'code':exc.code, **exc.diagnostic}
        try:
            # Reference needs instrument ticks, not dated fees/margins.
            price_bars = tuple(b for f,rows in source.bars_by_frequency.items() if f != '1m'
                               for b in rows if b.observation_eligible)
            ticks = load_reference_ticks(tick_raw,product=product,bars=price_bars)
        except NewowFuturesInputError:
            ticks = {}
        # 1m is the execution clock, not a strategy period. Never materialize its
        # unused 20-field indicator history for each two-year source.
        prepared = prepare_features({f: rows for f, rows in source.bars_by_frequency.items() if f in FREQUENCIES})
    else:
        prepared = None
    for frequency in FREQUENCIES:
        for variant in Variant:
            profile = Profile(variant,frequency)
            gap = input_error
            status = None
            if source is None:
                status = 'DATA_INSUFFICIENT'
            elif any(source.gaps_by_frequency.get(f) for f in required_frequencies(profile)):
                status = 'DATA_INSUFFICIENT'
                gap = {'code':'DATA_INSUFFICIENT','required_frequencies':list(required_frequencies(profile))}
            if variant is Variant.TEST3 and frequency == '1w':
                status = 'NOT_APPLICABLE'
                gap = {'code':'NEXT_HOLDING_FREQUENCY_UNAVAILABLE'}
            if status is None and not source.diagnostics['minute_complete']:
                status, gap = 'DATA_INSUFFICIENT', {'code':'EXECUTION_CLOCK_INCOMPLETE'}
            if status is None and execution_gap:
                status, gap = 'EXECUTION_FACTS_MISSING', execution_gap
            reference_status = None
            if source is None or any(source.gaps_by_frequency.get(f) for f in required_frequencies(profile)):
                reference_status = 'DATA_INSUFFICIENT'
            elif variant is Variant.TEST3 and frequency == '1w':
                reference_status = 'NOT_APPLICABLE'
            elif not source.diagnostics['minute_complete']:
                reference_status = 'DATA_INSUFFICIENT'
            elif not ticks:
                reference_status = 'EXECUTION_FACTS_MISSING'
            if reference_status:
                reference = blocked_reference(reference_status)
                if source is not None:
                    from guiyi_quant.newow_futures.reference import chart_bar
                    reference['chart']['bars'] = [chart_bar(b) for b in
                        source.bars_by_frequency.get(frequency,()) if b.observation_eligible][-2000:]
            else:
                reference = run_reference(profile,source.bars_by_frequency,source.minute_bars,
                                          prepared=prepared,ticks=ticks)
            for scenario in SCENARIOS:
                if status:
                    yield build_packet(product=product,profile=profile,scenario=scenario,
                        code_revision=code_revision,status=status,source=source,facts_hash=facts_hash,
                        reference=reference,diagnostic=gap,as_of=as_of)
                    continue
                result = run_research(source.bars_by_frequency,executions,profile=profile,
                    since=SINCE,through=THROUGH,scenario=scenario,prepared=prepared,
                    reference=reference,ticks=ticks)
                windows = []
                for name,since,through in DIAGNOSTIC_WINDOWS:
                    selected = tuple(b for b in executions if since <= b.bar.trading_day <= through)
                    if not selected:
                        summary = blocked_summary('DATA_INSUFFICIENT')
                    else:
                        diagnostic = run_research(source.bars_by_frequency,selected,profile=profile,
                            since=since,through=through,scenario=scenario,prepared=prepared,
                            reference=reference,ticks=ticks)
                        summary = diagnostic['summary']
                    windows.append({'name':name,'since':since,'through':through,'summary':summary,
                                    'input_snapshot_hash':source.input_snapshot_hash,
                                    'independent_initial_cash':'100000','oos_status':'OOS_NOT_PROVEN'})
                result.setdefault('diagnostics',{})['independent_windows'] = windows
                owner_windows = []
                owner_keys = dict.fromkeys(item.bar.owner for item in executions)
                for owner in owner_keys:
                    selected = tuple(item for item in executions if item.bar.owner == owner)
                    owner_since = min(item.bar.trading_day for item in selected)
                    owner_through = max(item.bar.trading_day for item in selected)
                    owner_bars = {f:tuple(b for b in rows if b.owner == owner)
                                  for f,rows in source.bars_by_frequency.items()}
                    owner_result = run_research(owner_bars,selected,profile=profile,
                        since=owner_since,through=owner_through,scenario=scenario,
                        prepared=prepared,reference=reference,ticks=ticks)
                    owner_windows.append({'physical_contract':owner[0],
                        'owner_segment_id':owner[1],'calculation_segment_id':owner[2],
                        'since':owner_since,'through':owner_through,
                        'summary':owner_result['summary'],'independent_initial_cash':'100000',
                        'oos_status':'OOS_NOT_PROVEN','full_window_account_replacement':False})
                result['diagnostics']['independent_owners'] = owner_windows
                result['diagnostics']['reference_ticks_hash'] = payload_hash(
                    [[contract,day,tick] for (contract,day),tick in sorted(ticks.items())])
                yield build_packet(product=product,profile=profile,scenario=scenario,
                    code_revision=code_revision,status=result['summary']['status'],source=source,
                    facts_hash=facts_hash,result=result,reference=reference,as_of=as_of)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols',nargs='+',choices=PRODUCTS,default=list(PRODUCTS))
    parser.add_argument('--project-env',type=Path,required=True)
    parser.add_argument('--facts-dir',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    if len(args.symbols) != len(set(args.symbols)):
        parser.error('unique symbols are required')
    safe_path(args.out)
    safe_path(args.facts_dir)
    revision = frozen_code_revision()
    # Prove the engine/reference imports before opening DB or writing outputs.
    from guiyi_quant.newow_futures.engine import run_research
    from guiyi_quant.newow_futures.reference import run_reference
    assert callable(run_research) and callable(run_reference)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    from app.newow_futures_research.store import publish_packet
    from app.private_settings import load_private_readonly_settings
    settings,_ = load_private_readonly_settings(args.project_env)
    canonical = Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    statuses = []
    try:
        for product in args.symbols:
            source, gap = None,None
            try:
                with Session(engine,autoflush=False) as session,readonly_transaction(session,timeout_seconds=900):
                    market = MarketDataService(MarketCatalog(session,canonical),CanonicalMonthlyStore(canonical))
                    source = load_newow_futures_inputs(market,product=product)
            except NewowFuturesInputError as exc:
                gap = {'code':exc.code,**exc.diagnostic}
            except Exception as exc:
                gap = safe_diagnostic(exc,product=product,stage='readonly_input')
            # All numerical computation happens after the transaction above has ended.
            for packet in run_matrix(product=product,source=source,facts_dir=args.facts_dir,
                                     code_revision=revision,input_error=gap):
                frozen = publish_packet(args.out,packet)
                meta = frozen['metadata']
                statuses.append(meta['status'])
                print(json.dumps({key:meta[key] for key in
                    ('product','strategy','frequency','scenario','status','run_id')},ensure_ascii=False),flush=True)
    finally:
        engine.dispose()
    return 0 if all(s in ('COMPLETED','ROLLOVER_INTERRUPTED','NOT_APPLICABLE',
                          'INSUFFICIENT_CAPITAL','PENDING_UNFILLED') for s in statuses) else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        candidate = getattr(exc,'code',None)
        code = candidate if isinstance(candidate,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{2,100}',candidate) else 'NEWOW_FUTURES_RESEARCH_FAILED'
        print(json.dumps({'status':'BLOCKED','code':code}),flush=True)
        raise SystemExit(1) from None
