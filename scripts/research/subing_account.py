"""Read-only JM30 development replay from MDS and dated RQData execution facts."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, time
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.research.subing_trend import load as load_factors
from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.new_subing_research import (
    NewSubingInputError, load_execution_facts, payload_hash, safe_diagnostic, validate_series,
)
from guiyi_quant.new_subing import StrategyBar

SHANGHAI = ZoneInfo('Asia/Shanghai')


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
            raise NewSubingInputError('EXECUTION_FACTS_MISSING') from None
    return selected


def observations(bars, factor_rows, sessions):
    daily = [r for r in factor_rows if r['frequency'] == '1d']
    times = [datetime.fromisoformat(r['time']) for r in daily]
    m30 = {datetime.fromisoformat(r['time']): r for r in factor_rows if r['frequency'] == '30m' and r['owned']}
    if not set(m30).issubset({b.bar_end for b in bars}):
        raise NewSubingInputError('M30_ENDPOINT_NOT_IN_EXECUTION_SERIES')
    result = {}
    for b in bars:
        i = bisect_left(times, b.bar_end) - 1
        d = daily[i] if i >= 0 else None
        r = m30.get(b.bar_end)
        frame = None
        if r is not None:
            p, x = r['price_factor'], r['joint']['exits']
            pullback = p['pullback']
            frame = dict(near_zero_golden=r['macd']['near_zero_golden'],
                minute_angle=None if r['angle'] is None else str(r['angle']),
                above_ema=p['above_ema'], volume_effective=r['volume_factor']['effective'],
                below_previous_low=x['below_previous_low'], high_death=x['high_death'],
                below_ema=p['below_ema'], qualified_pullback=pullback['qualified_hold'],
                pullback_high=str(pullback['armed_high']) if pullback['qualified_hold'] else None,
                pullback_invalidated=p['above_ema'] is not True or r['direction'] in ('DOWN', 'UNKNOWN'))
        local = b.bar_end.astimezone(SHANGHAI)
        day_end = max(w.end for w in sessions[b.trading_day])
        in_end = local.date() == b.trading_day and local.time() >= time(14, 50) and b.bar_end <= day_end
        result[b.bar_end] = dict(event_id=f'observe:{b.physical_contract}:{b.bar_end.isoformat()}',
            kind='observe', at=b.bar_end.isoformat(), contract=b.physical_contract,
            trading_day=b.trading_day.isoformat(), close=str(b.close),
            daily_direction=d['direction'] if d else 'UNKNOWN', daily_at=d['time'] if d else None,
            day_end_window=in_end, m30=frame)
    return result


def load(market, raw_facts, since, through):
    if since > through:
        raise NewSubingInputError('REQUEST_WINDOW_INVALID')
    owners = ActualDominantResearchSegmentLoader(market).owner_segments(symbol='jm', since=since, through=through)
    factors = load_factors(market, since, through, include_joint=True)
    segments, sources, sessions = [], [], {}
    for owner in owners:
        start, end = max(since, owner.start_trading_day), min(through, owner.end_trading_day)
        cutoff = max(w.end for w in market.session_windows(symbol='jm', trading_day=end))
        before = market.contract_source_evidence(symbol='jm', contract=owner.contract, frequency=BarFrequency.M1, before=cutoff)
        expected = market.expected_contract_replay_endpoints(symbol='jm', contract=owner.contract,
            frequency=BarFrequency.M1, trading_day=end, cutoff=cutoff, since=start)
        if not expected:
            raise NewSubingInputError('EXECUTION_INPUT_EMPTY')
        result = market.query_contract_trading_days(ContractTradingDayQuery('jm', owner.contract, BarFrequency.M1, expected[0][1], end))
        validate_series(result, product='jm', contract=owner.contract, frequency=BarFrequency.M1, expected=expected)
        bars = []
        for b in result.bars:
            if not start <= b.trading_day <= end:
                raise NewSubingInputError('EXECUTION_OWNER_CONFLICT')
            if b.trading_day not in sessions:
                ws = tuple(market.session_windows(symbol='jm', trading_day=b.trading_day))
                if not ws or any(w.start >= w.end for w in ws) or any(a.end > z.start for a, z in zip(ws, ws[1:])):
                    raise NewSubingInputError('SESSION_CONFLICT')
                sessions[b.trading_day] = ws
            ws = sessions[b.trading_day]
            containing = [w for w in ws if w.start < b.bar_end <= w.end]
            if len(containing) != 1:
                raise NewSubingInputError('SESSION_CONFLICT')
            bars.append(StrategyBar(product='jm', physical_contract=owner.contract, frequency='1m',
                source_identity=payload_hash([before, asdict(b)]), confirmed_at=b.bar_end,
                session_open_at=containing[0].start, session_close_at=max(w.end for w in ws),
                **{k:v for k,v in asdict(b).items() if k != 'turnover'}))
        selected = select_facts(raw_facts, bars)
        executions, facts_hash = load_execution_facts(selected, product='jm', bars=bars)
        rows = [r for r in factors['rows'] if r['contract'] == owner.contract]
        segments.append(dict(contract=owner.contract, since=str(start), through=str(end), executions=executions,
            observations=observations(bars, rows, sessions), facts_hash=facts_hash))
        sources.append(dict(contract=owner.contract, frequency='1m', cutoff=cutoff, source=before,
            count=len(bars), bars_hash=payload_hash([asdict(b) for b in bars])))
    for s in [*factors['sources'], *sources]:
        if s['source'] != market.contract_source_evidence(symbol='jm', contract=s['contract'],
                frequency=BarFrequency(s['frequency']), before=s['cutoff']):
            raise NewSubingInputError('INPUT_SOURCE_CHANGED')
    if owners != ActualDominantResearchSegmentLoader(market).owner_segments(symbol='jm', since=since, through=through):
        raise NewSubingInputError('OWNER_MAPPING_CHANGED')
    return segments, dict(since=str(since), through=str(through), sources=[*factors['sources'], *sources],
        source_facts_hash=payload_hash(raw_facts), factors_input_hash=factors['input_hash'],
        factor_versions={k:v for k,v in factors.items() if k.endswith('version')},
        factor_code_hashes=factors['code_hashes'])


def render(data):
    # JSON never becomes HTML; include a minimal inspection tool without network dependencies.
    payload = json.dumps(data, ensure_ascii=False, default=str, allow_nan=False).replace('<', '\\u003c')
    return '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>苏冰3.3账户回放</title>
<style>body{font:16px system-ui;margin:40px;background:#101923;color:#e7edf5}select{padding:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#192737;padding:20px}h1{font-size:26px}</style>
<h1>焦煤苏冰 · 历史账户回放 3.3</h1><p>开发核对样本，模型成交，非OOS。每个物理合约独立10万元账户，结果不拼接。</p>
<label>查看物理合约 <select id="segments"></select></label><pre id="summary"></pre>
<label>记录类型 <select id="kind"><option value="fills">成交</option><option value="trace">决策回放</option><option value="execution_events">取消与未成交</option><option value="closed_rounds">轮次</option><option value="daily_equity">每日权益</option><option value="all">完整记录（含检查点）</option></select></label><pre id="detail"></pre>
<script id="data" type="application/json">''' + payload + '''</script><script>
const data=JSON.parse(document.getElementById('data').textContent),sel=document.getElementById('segments'),kind=document.getElementById('kind');
data.segments.forEach((s,i)=>{let o=document.createElement('option');o.value=i;o.textContent=s.contract+' '+s.since+' — '+s.through;sel.appendChild(o)});
function show(){const s=data.segments[Number(sel.value)],r=s.result;document.getElementById('summary').textContent=JSON.stringify({contract:s.contract,boundary:s.boundary,summary:r.summary,open_layers:r.open_layers,pending:r.pending},null,2);document.getElementById('detail').textContent=JSON.stringify(kind.value==='all'?r:r[kind.value],null,2)}sel.onchange=kind.onchange=show;show();
</script></html>'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--since', type=date.fromisoformat, required=True)
    p.add_argument('--through', type=date.fromisoformat, required=True)
    p.add_argument('--facts', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--preflight', action='store_true', help='Validate all inputs without account simulation or output writes')
    args = p.parse_args()
    if args.output.exists():
        raise NewSubingInputError('OUTPUT_ALREADY_EXISTS')
    facts_bytes = args.facts.read_bytes()
    raw = json.loads(facts_bytes)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    from app.private_settings import load_private_readonly_settings
    settings, _ = load_private_readonly_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']), connect_args={'connect_timeout':5})
    try:
        with Session(engine, autoflush=False) as session, readonly_transaction(session, timeout_seconds=900):
            root = Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
            segments, evidence = load(MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root)), raw, args.since, args.through)
    finally:
        engine.dispose()
    if args.facts.read_bytes() != facts_bytes:
        raise NewSubingInputError('EXECUTION_FACTS_CHANGED')
    if args.preflight:
        print(json.dumps([dict(contract=s['contract'], minutes=len(s['executions']), since=s['since'], through=s['through']) for s in segments]))
        return
    from guiyi_quant import subing_account
    results = []
    for i, s in enumerate(segments):
        result = subing_account.replay(s['executions'], s['observations'], run_id=f'jm30:{s["contract"]}:{args.since}:{args.through}')
        results.append({k:v for k,v in s.items() if k not in ('executions', 'observations')} | dict(
            boundary='ROLLOVER_INTERRUPTED' if i < len(segments)-1 else 'WINDOW_ENDED', result=result))
    repo = Path(__file__).resolve().parents[2]
    files = [Path(__file__), Path(subing_account.__file__), repo/'packages/quant-core/guiyi_quant/subing_decision.py',
        repo/'services/quant-api/app/market_data/new_subing_research.py', repo/'packages/quant-core/guiyi_quant/paper/__init__.py']
    hashes = {str(f.relative_to(repo)):sha256(f.read_bytes()).hexdigest() for f in files}
    data = dict(kind='DEVELOPMENT_HISTORICAL_MODEL_REPLAY', evidence=evidence, code_hashes=hashes,
        facts_file_sha256=sha256(facts_bytes).hexdigest(), segments=results,
        time_model='retrospective completed bars; no provider-arrival evidence; strict-before D1; next completed 1m close +/- 1 tick model fill',
        account_model='independent 100000 per physical segment; no stitched equity; terminal holdings marked, never forcibly filled')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'replay.json').write_text(json.dumps(data, ensure_ascii=False, default=str, allow_nan=False))
    (args.output/'index.html').write_text(render(data))
    print(json.dumps([dict(contract=s['contract'], boundary=s['boundary'], summary=s['result'].get('summary')) for s in results], default=str))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        from sqlalchemy.exc import SQLAlchemyError
        detail = safe_diagnostic(exc, product='jm', stage='subing_account')
        if isinstance(exc, SQLAlchemyError):
            detail['code'] = 'LOCAL_DATABASE_UNAVAILABLE'
        elif not hasattr(exc, 'code'):
            detail['code'] = 'ACCOUNT_REPLAY_FAILED'
        print(json.dumps(detail))
        raise SystemExit(2) from None
