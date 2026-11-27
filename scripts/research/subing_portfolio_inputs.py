"""Offline input preparation shared by the SuBing portfolio replay."""
from bisect import bisect_left
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, time
from decimal import Decimal as D
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.research_inputs import (
    ResearchInputError,
    load_execution_facts,
    payload_hash,
    validate_series,
)
from guiyi_quant.subing_decision import _wire
from guiyi_quant.subing_inputs import StrategyBar
from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS
from scripts.research.subing_trend import load as load_factors

ROOT = Path(__file__).resolve().parents[2]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    if path.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    raw = json.dumps(
        _wire(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def hashes():
    core = ROOT / "packages/quant-core/guiyi_quant"
    paths = [
        *core.glob("subing*.py"),
        *core.glob("subing_one_lot/*.py"),
        *core.glob("indicators/*.py"),
        *core.glob("paper/*.py"),
        ROOT / "services/quant-api/app/market_data/research_inputs.py",
        ROOT / "scripts/research/subing_trend.py",
        ROOT / "services/quant-api/app/subing_model/account.py",
        Path(__file__),
    ]
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def select_facts(raw, bars):
    """Explicit exact-day projection, retaining source snapshot identity externally."""
    required = {}
    for b in bars:
        required.setdefault(b.physical_contract, set()).add(b.trading_day.isoformat())
    selected = {k: deepcopy(v) for k, v in raw.items() if k != 'contracts'}
    selected['contracts'] = {}
    for contract, days in required.items():
        try:
            body = deepcopy(raw['contracts'][contract])
            for key in ('parameters', 'daily'):
                rows = body[key]
                if len({r['date'] for r in rows}) != len(rows):
                    raise ValueError
                body[key] = [r for r in rows if r['date'] in days]
                if {r['date'] for r in body[key]} != days:
                    raise ValueError
            selected['contracts'][contract] = body
        except (KeyError, TypeError, ValueError):
            raise ResearchInputError('EXECUTION_FACTS_MISSING') from None
    return selected


def observations(bars, factor_rows, sessions, *, include_range=False):
    daily = [r for r in factor_rows if r['frequency'] == '1d']
    times = [datetime.fromisoformat(r['time']) for r in daily]
    m30 = {datetime.fromisoformat(r['time']): r for r in factor_rows if r['frequency'] == '30m' and r['owned']}
    if not set(m30).issubset({b.bar_end for b in bars}):
        raise ResearchInputError('M30_ENDPOINT_NOT_IN_EXECUTION_SERIES')
    result = {}
    for b in bars:
        i = bisect_left(times, b.bar_end) - 1
        d = daily[i] if i >= 0 else None
        r = m30.get(b.bar_end)
        frame = None
        if r is not None:
            p, x = r['price_factor'], r['joint']['exits']
            pullback, rebound = p['pullback'], p['rebound']
            frame = dict(high=str(r['high']), near_zero_death=r['macd']['near_zero_death'],
                low_golden=r['macd']['low_golden'], above_previous_high=x['above_previous_high'],
                qualified_rebound=rebound['qualified_hold'],
                rebound_low=str(rebound['armed_high']) if rebound['qualified_hold'] else None,
                rebound_invalidated=p['below_ema'] is not True or r['direction'] in ('UP', 'UNKNOWN'),
                ema21=None if p['ema21'] is None else str(p['ema21']), low=str(r['low']),
                near_zero_golden=r['macd']['near_zero_golden'],
                minute_angle=None if r['angle'] is None else str(r['angle']),
                above_ema=p['above_ema'], volume_tier=r['volume_factor']['tier'], volume_effective=r['volume_factor']['effective'],
                below_previous_low=x['below_previous_low'], high_death=x['high_death'],
                below_ema=p['below_ema'], qualified_pullback=pullback['qualified_hold'],
                pullback_high=str(pullback['armed_high']) if pullback['qualified_hold'] else None,
                pullback_invalidated=p['above_ema'] is not True or r['direction'] in ('DOWN', 'UNKNOWN'))
        if frame is not None and include_range:
            frame['regime'] = r['range_factor']['regime']
        local = b.bar_end.astimezone(SHANGHAI)
        day_end = max(w.end for w in sessions[b.trading_day])
        in_end = local.date() == b.trading_day and local.time() >= time(14, 50) and b.bar_end <= day_end
        result[b.bar_end] = dict(event_id=f'observe:{b.physical_contract}:{b.bar_end.isoformat()}',
            kind='observe', at=b.bar_end.isoformat(), contract=b.physical_contract,
            trading_day=b.trading_day.isoformat(), close=str(b.close),
            daily_direction=d['direction'] if d else 'UNKNOWN', daily_at=d['time'] if d else None,
            day_end_window=in_end, m30=frame)
    return result


def load(market, raw_facts, since, through, *, product):
    if product not in EXPANDED_PORTFOLIO_PRODUCTS:
        raise ResearchInputError('RESEARCH_PRODUCT_UNSUPPORTED')
    if since > through:
        raise ResearchInputError('REQUEST_WINDOW_INVALID')
    owners = ActualDominantResearchSegmentLoader(market).owner_segments(symbol=product, since=since, through=through)
    factors = load_factors(market, since, through, include_joint=True, product=product, include_range=True, portfolio=True)
    segments, sources, sessions = [], [], {}
    for owner in owners:
        start, end = max(since, owner.start_trading_day), min(through, owner.end_trading_day)
        cutoff = max(w.end for w in market.session_windows(symbol=product, trading_day=end))
        before = market.contract_source_evidence(symbol=product, contract=owner.contract, frequency=BarFrequency.M1, before=cutoff)
        expected = market.expected_contract_replay_endpoints(symbol=product, contract=owner.contract,
            frequency=BarFrequency.M1, trading_day=end, cutoff=cutoff, since=start)
        if not expected:
            raise ResearchInputError('EXECUTION_INPUT_EMPTY')
        result = market.query_contract_trading_days(ContractTradingDayQuery(product, owner.contract, BarFrequency.M1, expected[0][1], end))
        validate_series(result, product=product, contract=owner.contract, frequency=BarFrequency.M1, expected=expected)
        bars = []
        for b in result.bars:
            if not start <= b.trading_day <= end:
                raise ResearchInputError('EXECUTION_OWNER_CONFLICT')
            if b.trading_day not in sessions:
                ws = tuple(market.session_windows(symbol=product, trading_day=b.trading_day))
                if not ws or any(w.start >= w.end for w in ws) or any(a.end > z.start for a, z in zip(ws, ws[1:])):
                    raise ResearchInputError('SESSION_CONFLICT')
                sessions[b.trading_day] = ws
            ws = sessions[b.trading_day]
            containing = [w for w in ws if w.start < b.bar_end <= w.end]
            if len(containing) != 1:
                raise ResearchInputError('SESSION_CONFLICT')
            bars.append(StrategyBar(product=product, physical_contract=owner.contract, frequency='1m',
                source_identity=payload_hash([before, asdict(b)]), confirmed_at=b.bar_end,
                session_open_at=containing[0].start, session_close_at=max(w.end for w in ws),
                **{k:v for k,v in asdict(b).items() if k != 'turnover'}))
        selected = select_facts(raw_facts, bars)
        executions, facts_hash = load_execution_facts(selected, product=product, bars=bars)
        rows = [r for r in factors['rows'] if r['contract'] == owner.contract]
        segments.append(dict(contract=owner.contract, since=str(start), through=str(end), executions=executions,
            observations=observations(bars, rows, sessions, include_range=True), facts_hash=facts_hash))
        sources.append(dict(contract=owner.contract, frequency='1m', cutoff=cutoff, source=before,
            count=len(bars), bars_hash=payload_hash([asdict(b) for b in bars])))
    for s in [*factors['sources'], *sources]:
        if s['source'] != market.contract_source_evidence(symbol=product, contract=s['contract'],
                frequency=BarFrequency(s['frequency']), before=s['cutoff']):
            raise ResearchInputError('INPUT_SOURCE_CHANGED')
    if owners != ActualDominantResearchSegmentLoader(market).owner_segments(symbol=product, since=since, through=through):
        raise ResearchInputError('OWNER_MAPPING_CHANGED')
    evidence = dict(since=str(since), through=str(through), sources=[*factors['sources'], *sources],
        source_facts_hash=payload_hash(raw_facts), factors_input_hash=factors['input_hash'],
        factor_versions={k:v for k,v in factors.items() if k.endswith('version')},
        factor_code_hashes=factors['code_hashes'])
    if product != 'jm':
        evidence['transfer_product'] = product
    return segments, evidence


def build_context(rows, executions, contract, hourly):
    from guiyi_quant.subing_recent_structure import State, Bar, step

    state = State(contract)
    points = {}
    for r in rows:
        if r["contract"] != contract or r["frequency"] != "30m":
            continue
        at = datetime.fromisoformat(r["time"])
        state, point = step(
            state,
            Bar(at, *(D(str(r[k])) for k in ("high", "low", "close"))),
            contract=contract,
        )
        points[at] = dict(_wire(point), base_regime=r["range_factor"]["regime"])
    first = executions[0].bar.bar_end
    previous = [v for k, v in points.items() if k < first]
    hours = [v for k, v in hourly.items() if k < first]
    current = previous[-1] if previous else None
    hour = hours[-1] if hours else None
    contexts = {}
    for x in executions:
        at = x.bar.bar_end
        current = points.get(at, current)
        hour = hourly.get(at, hour)
        contexts[at.isoformat()] = dict(current or {}, hourly=hour)
    return contexts
