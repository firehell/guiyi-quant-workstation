"""Stage 1: local, read-only 60-product audit, causal rows and blind review pack.

No learner is trained until the owner reviews the label examples. Does not
fetch provider data, repair gaps, modify Canonical or enable any Runtime.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from collections import Counter
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
from time import monotonic

from scripts.research.regime_learning_core import (
    BlindPool, FREQUENCIES, LABEL_VERSION, blind_payload, reference_label, temporal_split, sample_partition,
)
from guiyi_quant.indicators import subing_range, subing_trend

ROOT = Path(__file__).resolve().parents[2]


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, default=str, allow_nan=False, indent=2))


def raw_bar(bar):
    return dict(time=bar.bar_end.isoformat(), day=bar.trading_day.isoformat(),
                open=float(bar.open), high=float(bar.high), low=float(bar.low), close=float(bar.close))


def physical_rows(market, symbol, owner, frequency, since, through):
    """Full physical lifecycle, exact endpoints; no consumer-local data resolver."""
    from app.market_data.domain import BarFrequency, ContractTradingDayQuery
    from app.market_data.new_subing_research import validate_series, payload_hash
    start, end = max(since, owner.start_trading_day), min(through, owner.end_trading_day)
    freq = BarFrequency(frequency)
    cutoff = max(w.end for w in market.session_windows(symbol=symbol, trading_day=end))
    proof = market.contract_source_evidence(symbol=symbol, contract=owner.contract, frequency=freq, before=cutoff)
    expected = market.expected_contract_replay_endpoints(symbol=symbol, contract=owner.contract,
        frequency=freq, trading_day=end, cutoff=cutoff)
    if not expected:
        raise ValueError('RESEARCH_PREFIX_EMPTY')
    result = market.query_contract_trading_days(ContractTradingDayQuery(symbol, owner.contract, freq, expected[0][1], end))
    # Never evaluate a later bar read from the same physical partition.
    bars = tuple(b for b in result.bars if b.bar_end <= cutoff)
    result = replace(result, bars=bars, coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None)
    validate_series(result, product=symbol, contract=owner.contract, frequency=freq, expected=expected)
    if proof != market.contract_source_evidence(symbol=symbol, contract=owner.contract, frequency=freq, before=cutoff):
        raise ValueError('RESEARCH_SOURCE_CHANGED')
    return bars, dict(contract=owner.contract, frequency=frequency, owner_start=start, owner_end=end,
                     prefix_start=expected[0][0], cutoff=cutoff, source=proof,
                     bars_hash=payload_hash([asdict(b) for b in bars]))


def observe(bars, symbol, frequency, source, sector, pool, splits):
    contract = source['contract']
    trend = subing_trend.initial_state(contract, frequency)
    state = subing_range.initial_state(contract, frequency)
    recent = []
    segment = f"{contract}:{source['owner_start']}:{source['owner_end']}"
    for bar in bars:
        trend, tp = subing_trend.step(trend, contract=contract, frequency=frequency,
            bar_end=bar.bar_end, high=float(bar.high), low=float(bar.low), close=float(bar.close))
        state, rp = subing_range.step(state, contract=contract, frequency=frequency,
            bar_end=bar.bar_end, high=bar.high, low=bar.low, close=bar.close,
            atr=Decimal(str(tp.atr14)) if tp.atr14 is not None else None, trend_direction=tp.direction)
        raw = raw_bar(bar)
        recent = (*recent, raw)[-64:]
        label = reference_label([b['close'] for b in recent], tp.atr14)
        owned = source['owner_start'] <= bar.trading_day <= source['owner_end']
        partition = sample_partition(symbol=symbol,days=[b['day'] for b in recent],splits=splits)
        if owned and partition == 'DEVELOPMENT':
            pool.offer(symbol=symbol, frequency=frequency, contract=contract, sector=sector,
                       label=label['label'], bars=list(recent))
        # Numerical features are causal and dimensionless; preprocessing is fitted later on training only.
        features = None
        if tp.atr14 and tp.atr14 > 0 and tp.ema21 and len(recent) >= 21 and rp.er is not None and tp.normalized_slope is not None:
            atr = tp.atr14
            returns = [(b['close']-a['close'])/a['close'] for a,b in zip(recent, recent[1:])]
            def vol(n):
                xs = returns[-n:]
                avg = sum(xs)/len(xs)
                return (sum((x-avg)**2 for x in xs)/len(xs))**.5
            features = dict(return_1=returns[-1], body_atr=(raw['close']-raw['open'])/atr,
                range_atr=(raw['high']-raw['low'])/atr,
                close_ema_atr=(raw['close']-tp.ema21)/atr,
                ema_slope_atr=tp.normalized_slope, er=float(rp.er), chop=rp.chop/100,
                atr_close=atr/raw['close'], volatility_5=vol(5), volatility_20=vol(20))
        yield dict(symbol=symbol, sector=sector, frequency=frequency, contract=contract, segment=segment,
                   **raw, owned=owned, reference=label, features=features, baseline=rp.regime,
                   partition=partition,
                   trend_direction=tp.direction)


def run(output: Path, through: date):
    import csv
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.private_settings import load_private_readonly_settings
    from app.models.market_tables import MainContractMap
    from app.market_data.catalog import MarketCatalog
    from app.market_data.storage import CanonicalMonthlyStore
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
    from app.market_data.domain import DatasetKind
    from app.market_data.new_subing_research import payload_hash, safe_diagnostic

    code_paths = (Path(__file__),Path(__file__).with_name('regime_learning_core.py'),
                  Path(__file__).with_suffix('.html'),Path(subing_trend.__file__),Path(subing_range.__file__))
    code_hashes = {str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in code_paths}
    output.mkdir(parents=True, exist_ok=False)
    products_path = ROOT/'data/universe/operational_products.txt'
    products = [s.strip() for s in products_path.read_text().splitlines() if s.strip() and not s.startswith('#')]
    if len(products) != 60 or len(set(products)) != 60:
        raise ValueError('RESEARCH_UNIVERSE_INVALID')
    sectors = {r['product']: r['sector'] for r in csv.DictReader((ROOT/'data/universe/product_sectors.csv').open())}
    settings,_ = load_private_readonly_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    start_clock = monotonic()
    reports, sources, row_files = [], [], []
    try:
        with Session(engine, autoflush=False) as db, readonly_transaction(db):
            root = Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
            catalog = MarketCatalog(db, root)
            floor = date.fromisoformat((ROOT/'data/universe/active_history_floor.txt').read_text().strip())
            product_starts = {r['product']:date.fromisoformat(r['window_start']) for r in csv.DictReader(
                (ROOT/'data/universe/product_window_starts.csv').open())}
            starts = {symbol:max(floor,product_starts[symbol]) for symbol in products}
            dates = sorted({d for symbol in products for d in catalog.trading_days(symbol,starts[symbol],through)})
            splits = temporal_split([d.isoformat() for d in dates])
            bounds = {s:(lo,hi) for s,lo,hi in db.execute(select(MainContractMap.symbol,func.min(MainContractMap.trade_date),
                func.max(MainContractMap.trade_date)).where(MainContractMap.symbol.in_(products), MainContractMap.rank == 1,
                MainContractMap.trade_date <= through).group_by(MainContractMap.symbol))}
        pool = BlindPool(splits['test_from'])
        dump(output/'split.json',splits)
        dump(output/'run.json',dict(status='AUDITING',products=products,through=through,label_version=LABEL_VERSION,
            baseline=subing_range.VERSION,universe_sha256=sha256(products_path.read_bytes()).hexdigest(),
            architecture=platform.machine(),training_status='WAIT_LABEL_REVIEW'))
        for symbol in products:
            with Session(engine,autoflush=False) as db,readonly_transaction(db,timeout_seconds=900):
                root = Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
                catalog = MarketCatalog(db,root)
                market = MarketDataService(catalog,CanonicalMonthlyStore(root))
                mapped_start, mapped_end = bounds.get(symbol,(None,None))
                since, last = starts[symbol], through
                partitions = catalog.product_partitions(symbol)
                mapping_error = None
                owners = ()
                try:
                    if mapped_start is None:
                        raise ValueError('RESEARCH_MAPPING_MISSING')
                    owners = ActualDominantResearchSegmentLoader(market).owner_segments(symbol=symbol,since=since,through=last)
                except Exception as exc:
                    mapping_error = safe_diagnostic(exc,product=symbol,stage='mapping')
                symbol_sources, symbol_pools = [], deepcopy(pool.pools)
                for frequency in FREQUENCIES:
                    parts = [p for p in partitions if p.dataset.kind == DatasetKind.CONTRACT and p.dataset.frequency.value == frequency]
                    report = dict(symbol=symbol,frequency=frequency,requested_start=since,requested_end=last,mapping_start=mapped_start,mapping_end=mapped_end,
                        partition_count=len(parts),catalog_start=min((p.coverage_start for p in parts if p.coverage_start),default=None),
                        catalog_end=max((p.coverage_end for p in parts if p.coverage_end),default=None),
                        status='UNAVAILABLE',segments=[],owned_bars=0,labels=Counter(),development_labels=Counter())
                    filename = f'{symbol}-{frequency}.jsonl.gz'
                    with gzip.open(output/filename,'wt',encoding='utf-8') as handle:
                        for owner in owners:
                            try:
                                bars, source = physical_rows(market,symbol,owner,frequency,since,last)
                                # Complete the segment in isolation: failure admits no rows or blind samples.
                                staged_pool = BlindPool(splits['test_from'])
                                staged_rows = list(observe(bars,symbol,frequency,source,sectors.get(symbol,'unknown'),staged_pool,splits))
                                counts = Counter(row['reference']['label'] for row in staged_rows if row['owned'])
                                encoded = ''.join(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n' for row in staged_rows)
                            except Exception as exc:
                                report['segments'].append(dict(contract=owner.contract,start=owner.start_trading_day,end=owner.end_trading_day,
                                    status='UNAVAILABLE',diagnostic=safe_diagnostic(exc,product=symbol,stage='physical_prefix')))
                                continue
                            finally:
                                market.release_decoded_read_caches()
                            handle.write(encoded)
                            for key, candidates in staged_pool.pools.items():
                                combined = {sample['id']:sample for sample in pool.pools.get(key,[])+candidates}
                                pool.pools[key] = sorted(combined.values(),key=lambda sample:sample['rank'])[:12]
                            report['development_labels'].update(row['reference']['label'] for row in staged_rows
                                if row['owned'] and row['partition']=='DEVELOPMENT')
                            source.update(symbol=symbol)
                            symbol_sources.append(source)
                            report['owned_bars']+=sum(counts.values())
                            report['labels'].update(counts)
                            report['segments'].append(dict(contract=owner.contract,start=source['owner_start'],end=source['owner_end'],
                                status='VERIFIED',prefix_bars=len(bars),owned_bars=sum(counts.values()),bars_hash=source['bars_hash']))

                    success = sum(s['status']=='VERIFIED' for s in report['segments'])
                    if success:
                        report['status']='VERIFIED' if success == len(owners) else 'PARTIAL'
                    if mapping_error:
                        report['diagnostic']=mapping_error
                    reports.append(report)
                    row_files.append(dict(symbol=symbol,frequency=frequency,file=filename,sha256=sha256((output/filename).read_bytes()).hexdigest()))
                    print(json.dumps({k:report[k] for k in ('symbol','frequency','status','owned_bars')}),flush=True)
                # Recheck all physical source proofs and rank1 ownership before admitting this product.
                try:
                    from app.market_data.domain import BarFrequency
                    for s in symbol_sources:
                        if s['source'] != market.contract_source_evidence(symbol=symbol,contract=s['contract'],frequency=BarFrequency(s['frequency']),before=s['cutoff']):
                            raise ValueError('RESEARCH_SOURCE_CHANGED')
                    if owners and owners != ActualDominantResearchSegmentLoader(market).owner_segments(symbol=symbol,since=since,through=last):
                        raise ValueError('RESEARCH_MAPPING_CHANGED')
                except Exception:
                    pool.pools = symbol_pools
                    for r in reports[-3:]:
                        r['status']='SOURCE_CHANGED'
                    raise ValueError('RESEARCH_SOURCE_CHANGED') from None
                sources.extend(symbol_sources)
            dump(output/'coverage.json',reports)
        selected, deficits = pool.select()
        if code_hashes != {str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in code_paths}:
            raise ValueError('RESEARCH_CODE_CHANGED')
        snapshot = dict(products=products,splits=splits,sources=sources,rows=row_files,label_version=LABEL_VERSION,
                        baseline=subing_range.VERSION,code_hashes=code_hashes)
        dataset_id = payload_hash(snapshot)
        dump(output/'snapshot.json',snapshot)
        dump(output/'review-key.json',{'dataset_id':dataset_id,'references':[{k:s[k] for k in ('id','reference','sector','symbol','frequency')} for s in selected]})
        public = blind_payload(selected,dataset_id)
        template = Path(__file__).with_suffix('.html').read_text()
        (output/'index.html').write_text(template.replace('__DATA__',json.dumps(public,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')))
        dump(output/'run.json',dict(status='WAIT_LABEL_REVIEW' if not deficits else 'REVIEW_SAMPLES_INSUFFICIENT',
            dataset_id=dataset_id,products=products,through=through,split=splits,
            label_version=LABEL_VERSION,baseline=subing_range.VERSION,samples=len(selected),deficits=deficits,
            coverage=dict(Counter(r['status'] for r in reports)),elapsed_seconds=round(monotonic()-start_clock,2),
            training_status='NOT_STARTED_WAIT_LABEL_REVIEW',production_writes=False))
        print(json.dumps({'status':'WAIT_LABEL_REVIEW' if not deficits else 'REVIEW_SAMPLES_INSUFFICIENT','samples':len(selected),'deficits':deficits,'dataset_id':dataset_id}),flush=True)
    finally:
        engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--through',type=date.fromisoformat,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        run(args.output,args.through)
    except Exception as exc:
        # Never include raw database errors, paths, SQL or credentials.
        print(json.dumps({'status':'FAILED','error_type':type(exc).__name__}),flush=True)
        raise SystemExit(2) from None


if __name__=='__main__':
    main()
