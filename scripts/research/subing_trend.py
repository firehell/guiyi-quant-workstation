"""Read-only MDS export and standalone phase-2.1 trend inspection page."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from guiyi_quant.indicators.subing_trend import VERSION, initial_state, step


class TrendExportError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def diagnostic(exc):
    from app.market_data.new_subing_research import safe_diagnostic
    from sqlalchemy.exc import SQLAlchemyError
    if isinstance(exc, SQLAlchemyError):
        return {'symbol': 'jm', 'stage': 'trend_factor', 'code': 'LOCAL_DATABASE_UNAVAILABLE'}
    if not hasattr(exc, 'code'):
        return {'symbol': 'jm', 'stage': 'trend_factor', 'code': 'TREND_EXPORT_FAILED'}
    return safe_diagnostic(exc, product='jm', stage='trend_factor')


def load(market, since, through):
    from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
    from app.market_data.domain import BarFrequency, ContractTradingDayQuery
    from app.market_data.new_subing_research import payload_hash, validate_series
    owners = ActualDominantResearchSegmentLoader(market).owner_segments(symbol='jm', since=since, through=through)
    if len({o.contract for o in owners}) != len(owners):
        raise TrendExportError('TREND_REPEATED_OWNER_UNSUPPORTED')
    rows, sources = [], []
    for owner in owners:
        start, end = max(since, owner.start_trading_day), min(through, owner.end_trading_day)
        cutoff = max(w.end for w in market.session_windows(symbol='jm', trading_day=end))
        for frequency in (BarFrequency.D1, BarFrequency.M30):
            before = market.contract_source_evidence(symbol='jm', contract=owner.contract, frequency=frequency, before=cutoff)
            expected = market.expected_contract_replay_endpoints(symbol='jm', contract=owner.contract,
                frequency=frequency, trading_day=end, cutoff=cutoff)
            if not expected:
                raise TrendExportError('TREND_INPUT_EMPTY')
            result = market.query_contract_trading_days(ContractTradingDayQuery(
                'jm', owner.contract, frequency, expected[0][1], end))
            validate_series(result, product='jm', contract=owner.contract, frequency=frequency, expected=expected)
            state = initial_state(owner.contract, frequency.value)
            for bar in result.bars:
                state, point = step(state, contract=owner.contract, frequency=frequency.value,
                    bar_end=bar.bar_end, high=float(bar.high), low=float(bar.low), close=float(bar.close))
                # D1 pre-owner data is visible only as physical warm-up context, never as an owned signal.
                if bar.trading_day >= start or frequency is BarFrequency.D1:
                    rows.append(dict(contract=owner.contract, frequency=frequency.value,
                        time=bar.bar_end.isoformat(), label=bar.bar_end.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M'),
                        day=bar.trading_day.isoformat(), owned=start <= bar.trading_day <= end,
                        open=float(bar.open),high=float(bar.high),low=float(bar.low),close=float(bar.close), **asdict(point)))
            after = market.contract_source_evidence(symbol='jm', contract=owner.contract, frequency=frequency, before=cutoff)
            if before != after:
                raise TrendExportError('TREND_SOURCE_CHANGED')
            sources.append(dict(contract=owner.contract,frequency=frequency.value,cutoff=cutoff,
                owner_start=start,owner_end=end,count=len(result.bars),source=before,
                bars_hash=payload_hash([asdict(b) for b in result.bars])))
    # Recheck earlier reads after the entire export, not only after each frequency.
    for source in sources:
        if source['source'] != market.contract_source_evidence(symbol='jm',contract=source['contract'],
                frequency=BarFrequency(source['frequency']),before=source['cutoff']):
            raise TrendExportError('TREND_SOURCE_CHANGED')
    if owners != ActualDominantResearchSegmentLoader(market).owner_segments(symbol='jm', since=since, through=through):
        raise TrendExportError('TREND_MAPPING_CHANGED')
    from hashlib import sha256
    from guiyi_quant.indicators import subing_trend
    code_hashes = {p.name: sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), Path(__file__).with_suffix('.html'), Path(subing_trend.__file__))}
    return dict(code_hashes=code_hashes, version=VERSION, since=str(since),through=str(through),rows=rows,sources=sources,
        input_hash=payload_hash(sources), time_model='retrospective completed bars; D1 strictly earlier than selected 30m',
        source_note='Full same-contract lifecycle prefix, EMA SMA seed and Wilder ATR SMA seed, both rounded to 6 decimals.')


def render(data):
    template = Path(__file__).with_suffix('.html').read_text()
    return template.replace('__DATA__', json.dumps(data, ensure_ascii=False, default=str, allow_nan=False).replace('<', '\\u003c'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', type=date.fromisoformat, required=True)
    parser.add_argument('--through', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.since > args.through or args.output.exists():
        raise TrendExportError('TREND_REQUEST_INVALID')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    from app.private_settings import load_private_readonly_settings
    settings, _ = load_private_readonly_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    try:
        with Session(engine,autoflush=False) as session, readonly_transaction(session,timeout_seconds=900):
            root = Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
            data = load(MarketDataService(MarketCatalog(session,root),CanonicalMonthlyStore(root)),args.since,args.through)
    finally:
        engine.dispose()
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'data.json').write_text(json.dumps(data,ensure_ascii=False,default=str,allow_nan=False))
    (args.output/'index.html').write_text(render(data))
    for freq in ('1d','30m'):
        rows = [r for r in data['rows'] if r['frequency']==freq and r['owned']]
        print(json.dumps(dict(frequency=freq,count=len(rows),directions={s:sum(r['direction']==s for r in rows)
            for s in ('UP','NEUTRAL','DOWN','UNKNOWN')},angle_min=min((r['angle'] for r in rows if r['angle'] is not None),default=None),
            angle_max=max((r['angle'] for r in rows if r['angle'] is not None),default=None))))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps(diagnostic(exc)))
        raise SystemExit(2) from None
