"""Read-only MDS export and standalone phase-2.1 trend inspection page."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
from bisect import bisect_left
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from types import MappingProxyType

from guiyi_quant.indicators.subing_trend import VERSION, initial_state, step


# Explicit single-parameter research variants; default formulas remain unchanged.
PERIOD_PROFILES = MappingProxyType({
    'daily_ema19': (19, 21, (12, 26, 9)),
    'daily_ema23': (23, 21, (12, 26, 9)),
    'minute_ema19': (21, 19, (12, 26, 9)),
    'minute_ema23': (21, 23, (12, 26, 9)),
    'macd_fast10': (21, 21, (10, 26, 9)),
    'macd_fast14': (21, 21, (14, 26, 9)),
    'macd_slow24': (21, 21, (12, 24, 9)),
    'macd_slow28': (21, 21, (12, 28, 9)),
    'macd_signal7': (21, 21, (12, 26, 7)),
    'macd_signal11': (21, 21, (12, 26, 11)),
})

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


def load(market, since, through, *, include_macd=False, include_volume=False, include_price=False, include_joint=False, research_profile=None, product="jm"):
    if product not in ('jm', 'ma', 'ta'):
        raise TrendExportError('RESEARCH_PRODUCT_UNSUPPORTED')
    if product != 'jm' and research_profile is not None:
        raise TrendExportError('CROSS_PRODUCT_PARAMETER_SEARCH_UNSUPPORTED')
    from guiyi_quant.indicators import subing_macd, subing_volume, subing_price, subing_conditions
    if research_profile is not None and (type(research_profile) is not str or research_profile not in PERIOD_PROFILES):
        raise TrendExportError('FACTOR_RESEARCH_PROFILE_INVALID')
    daily_period, minute_period, macd_periods = PERIOD_PROFILES.get(research_profile, (21, 21, (12, 26, 9)))
    if research_profile is not None and not include_joint:
        raise TrendExportError('FACTOR_RESEARCH_REQUIRES_JOINT')
    if include_joint:
        include_macd = include_volume = include_price = True
    from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
    from app.market_data.domain import BarFrequency, ContractTradingDayQuery
    from app.market_data.new_subing_research import payload_hash, validate_series
    owners = ActualDominantResearchSegmentLoader(market).owner_segments(symbol=product, since=since, through=through)
    if len({o.contract for o in owners}) != len(owners):
        raise TrendExportError('TREND_REPEATED_OWNER_UNSUPPORTED')
    rows, sources = [], []
    for owner in owners:
        start, end = max(since, owner.start_trading_day), min(through, owner.end_trading_day)
        cutoff = max(w.end for w in market.session_windows(symbol=product, trading_day=end))
        for frequency in (BarFrequency.D1, BarFrequency.M30):
            before = market.contract_source_evidence(symbol=product, contract=owner.contract, frequency=frequency, before=cutoff)
            expected = market.expected_contract_replay_endpoints(symbol=product, contract=owner.contract,
                frequency=frequency, trading_day=end, cutoff=cutoff)
            if not expected:
                raise TrendExportError('TREND_INPUT_EMPTY')
            result = market.query_contract_trading_days(ContractTradingDayQuery(
                product, owner.contract, frequency, expected[0][1], end))
            validate_series(result, product=product, contract=owner.contract, frequency=frequency, expected=expected)
            state = initial_state(owner.contract, frequency.value, ema_period=daily_period if frequency is BarFrequency.D1 else minute_period)
            cross_state = subing_macd.initial_state(owner.contract, frequency.value, periods=macd_periods) if include_macd and frequency is BarFrequency.M30 else None
            volume_state = subing_volume.initial_state(owner.contract, frequency.value) if include_volume else None
            price_state = subing_price.PullbackState(owner.contract)
            rebound_state = subing_price.PullbackState(owner.contract, side="SHORT")
            entry_state = subing_conditions.EntryWindow(owner.contract)
            previous_bar = None
            daily_rows = [r for r in rows if r['contract'] == owner.contract and r['frequency'] == '1d']
            daily_times = [datetime.fromisoformat(r['time']) for r in daily_rows]
            for bar in result.bars:
                state, point = step(state, contract=owner.contract, frequency=frequency.value,
                    bar_end=bar.bar_end, high=float(bar.high), low=float(bar.low), close=float(bar.close))
                cross_fields = {}
                if cross_state is not None:
                    cross_state, cross = subing_macd.step(cross_state, contract=owner.contract, frequency=frequency.value,
                        bar_end=bar.bar_end, close=float(bar.close))
                    cross_fields['macd'] = asdict(cross)
                if volume_state is not None:
                    volume_state, volume_point = subing_volume.observe(volume_state, contract=owner.contract, frequency=frequency.value,
                        bar_end=bar.bar_end, volume=bar.volume)
                    cross_fields['volume_factor'] = asdict(volume_point)
                if include_price and frequency is BarFrequency.M30:
                    from decimal import Decimal
                    price = subing_price.price_point(bar.close, Decimal(str(point.ema21)) if point.ema21 is not None else None)
                    price_state, pullback = subing_price.observe(price_state, contract=owner.contract,
                        bar_end=bar.bar_end, high=bar.high, low=bar.low, close=bar.close,
                        ema21=price.ema21, trend_direction=point.direction, atr14=Decimal(str(point.atr14)) if point.atr14 is not None else None)
                    rebound_state, rebound = subing_price.observe(rebound_state, contract=owner.contract,
                        bar_end=bar.bar_end, high=bar.high, low=bar.low, close=bar.close,
                        ema21=price.ema21, trend_direction=point.direction,
                        atr14=Decimal(str(point.atr14)) if point.atr14 is not None else None, side='SHORT')
                    cross_fields['price_factor'] = {**asdict(price), 'pullback': pullback, 'rebound': rebound}
                if include_joint and frequency is BarFrequency.M30:
                    daily_index = bisect_left(daily_times, bar.bar_end) - 1
                    daily = daily_rows[daily_index] if daily_index >= 0 else None
                    exits = subing_conditions.exit_facts(close=bar.close,
                        previous_low=previous_bar.low if previous_bar else None,
                        ema21=price.ema21, high_death=cross.high_death)
                    exits['above_previous_high'] = bar.close > previous_bar.high if previous_bar else None
                    exits['previous_end'] = previous_bar.bar_end if previous_bar else None
                    entry_state, entry = subing_conditions.observe_entry(entry_state,
                        contract=owner.contract, bar_end=bar.bar_end,
                        daily_direction=daily['direction'] if daily else None,
                        minute_angle=Decimal(str(point.angle)) if point.angle is not None else None, above_ema=price.above_ema,
                        near_zero_golden=cross.near_zero_golden, volume_effective=volume_point.effective)
                    cross_fields['joint'] = dict(entry=entry, exits=exits,
                        daily_time=daily['time'] if daily else None,
                        daily_direction=daily['direction'] if daily else 'UNKNOWN')
                previous_bar = bar
                # D1 pre-owner data is visible only as physical warm-up context, never as an owned signal.
                if bar.trading_day >= start or frequency is BarFrequency.D1:
                    rows.append(dict(contract=owner.contract, frequency=frequency.value,
                        time=bar.bar_end.isoformat(), label=bar.bar_end.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M'),
                        day=bar.trading_day.isoformat(), owned=start <= bar.trading_day <= end,
                        open=float(bar.open),high=float(bar.high),low=float(bar.low),close=float(bar.close), **asdict(point), **cross_fields))
            after = market.contract_source_evidence(symbol=product, contract=owner.contract, frequency=frequency, before=cutoff)
            if before != after:
                raise TrendExportError('TREND_SOURCE_CHANGED')
            sources.append(dict(contract=owner.contract,frequency=frequency.value,cutoff=cutoff,
                owner_start=start,owner_end=end,count=len(result.bars),source=before,
                bars_hash=payload_hash([asdict(b) for b in result.bars])))
    # Recheck earlier reads after the entire export, not only after each frequency.
    for source in sources:
        if source['source'] != market.contract_source_evidence(symbol=product,contract=source['contract'],
                frequency=BarFrequency(source['frequency']),before=source['cutoff']):
            raise TrendExportError('TREND_SOURCE_CHANGED')
    if owners != ActualDominantResearchSegmentLoader(market).owner_segments(symbol=product, since=since, through=through):
        raise TrendExportError('TREND_MAPPING_CHANGED')
    from hashlib import sha256
    from guiyi_quant.indicators import subing_trend
    repo_root = Path(__file__).resolve().parents[2]
    code_hashes = {p.resolve().relative_to(repo_root).as_posix(): sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), Path(__file__).with_suffix('.html'), Path(subing_trend.__file__))}
    if include_macd:
        for p in (Path(subing_macd.__file__), Path(__file__).with_name('subing_macd.html')):
            code_hashes[p.resolve().relative_to(repo_root).as_posix()] = sha256(p.read_bytes()).hexdigest()
    if include_volume:
        for p in (Path(subing_volume.__file__), Path(__file__).with_name('subing_volume.html')):
            code_hashes[p.resolve().relative_to(repo_root).as_posix()] = sha256(p.read_bytes()).hexdigest()
    if include_price:
        for p in (Path(subing_price.__file__), Path(__file__).with_name('subing_price.html')):
            code_hashes[p.resolve().relative_to(repo_root).as_posix()] = sha256(p.read_bytes()).hexdigest()
    if include_joint:
        for p in (Path(subing_conditions.__file__), Path(__file__).with_name('subing_joint.html')):
            code_hashes[p.resolve().relative_to(repo_root).as_posix()] = sha256(p.read_bytes()).hexdigest()
    payload = dict(joint_version=subing_conditions.VERSION if include_joint else None, price_version=subing_price.VERSION if include_price else None, volume_version=subing_volume.VERSION if include_volume else None, volume_enabled=include_volume, macd_version=subing_macd.VERSION if include_macd else None, code_hashes=code_hashes, version=VERSION, since=str(since),through=str(through),rows=rows,sources=sources,
        input_hash=payload_hash(sources), time_model='retrospective completed bars; D1 strictly earlier than selected 30m',
        source_note='Full same-contract lifecycle prefix, EMA SMA seed and Wilder ATR SMA seed, both rounded to 6 decimals.')
    if research_profile is not None:
        payload.update(research_profile=research_profile, research_parameters=dict(daily_ema=daily_period, minute_ema=minute_period, macd=macd_periods),
                       research_version='subing_factor_period_stability_v1',
                       research_field_note='ema21 field carries the selected research EMA; original OHLCV unchanged')
    if product != 'jm':
        payload['transfer_product'] = product
    return payload


def render(data):
    template = Path(__file__).with_suffix('.html').read_text()
    fragment = Path(__file__).with_name('subing_macd.html').read_text() if data.get('macd_version') else ''
    if fragment:
        template = template.replace('焦煤 · 苏冰趋势因子核对', '焦煤 · 苏冰趋势与MACD因子核对').replace('<small>2.1</small>', '<small>2.1 + 2.2</small>')
    template = template.replace('__MACD_PANEL__', fragment)
    volume_fragment = Path(__file__).with_name('subing_volume.html').read_text() if data.get('volume_enabled') else ''
    if volume_fragment:
        template = template.replace('<small>2.1 + 2.2</small>', '<small>2.1 + 2.2 + 2.3</small>').replace('<small>2.1</small>', '<small>2.1 + 2.3</small>')
        template = template.replace('焦煤 · 苏冰趋势与MACD因子核对', '焦煤 · 苏冰因子核对').replace('焦煤 · 苏冰趋势因子核对', '焦煤 · 苏冰因子核对')
    template = template.replace('__VOLUME_PANEL__', volume_fragment)
    price_fragment = Path(__file__).with_name('subing_price.html').read_text() if data.get('price_version') else ''
    if price_fragment:
        template = template.replace('</small>', ' + 2.4</small>', 1)
        template = template.replace('焦煤 · 苏冰趋势与MACD因子核对', '焦煤 · 苏冰因子核对').replace('焦煤 · 苏冰趋势因子核对', '焦煤 · 苏冰因子核对')
    template = template.replace('__PRICE_PANEL__', price_fragment)
    joint_fragment = Path(__file__).with_name('subing_joint.html').read_text() if data.get('joint_version') else ''
    template = template.replace('__JOINT_PANEL__', joint_fragment)
    return template.replace('__DATA__', json.dumps(data, ensure_ascii=False, default=str, allow_nan=False).replace('<', '\\u003c'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', type=date.fromisoformat, required=True)
    parser.add_argument('--through', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--macd', action='store_true', help='Include phase 2.2 completed 30m MACD cross inspection')
    parser.add_argument('--volume', action='store_true', help='Include phase 2.3 completed volume inspection')
    parser.add_argument('--price', action='store_true', help='Include phase 2.4 completed price/EMA facts')
    parser.add_argument('--joint', action='store_true', help='Include all factors, entry checks and exit facts (no trades)')
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
            data = load(MarketDataService(MarketCatalog(session,root),CanonicalMonthlyStore(root)),args.since,args.through,include_macd=args.macd,include_volume=args.volume,include_price=args.price,include_joint=args.joint)
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
