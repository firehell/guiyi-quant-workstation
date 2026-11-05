"""Fixed JM v6 versus approved v2 add filter; read-only development comparison."""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.market_data_service import MarketDataService
from app.market_data.storage import CanonicalMonthlyStore
from app.private_settings import load_private_readonly_settings
from guiyi_quant.subing_account import replay
from guiyi_quant.subing_decision import DecisionModel, REGIME_PROFILE
from scripts.research.subing_account import load

SOURCE = Path('output/subing-stage4-tier1-exit-20261101/replay.json')
FACTS = Path('output/worktree-archive-20261101/subing-jm30-notion-spec/source-evidence/newow-futures-bidir-v1-20261020-evidence/facts-attempt-001/jm.json')
BASE = Path('output/subing-stage5-20261101/theoretical-open-event-001')


def dump(path, value):
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, default=str, allow_nan=False)


def wire(value):
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def baseline_observations(observations):
    result = deepcopy(observations)
    for event in result.values():
        if event['m30'] is not None:
            del event['m30']['regime']
    return result


def measure(executions, result):
    """Reconcile per-layer fees, cash, MTM, and event-order completed-close DD."""
    by_source = {x.bar.source_identity: x for x in executions}
    assert len(by_source) == len(executions)
    fills = {f['bar_source']: f for f in result['fills']}
    assert len(fills) == len(result['fills'])
    layers, completed = {}, []
    cash = peak = D('100000')
    drawdown = D(0)
    total_fee = D(0)
    for x in executions:
        b, facts = x.bar, x.facts
        f = fills.get(b.source_identity)
        if f:
            assert datetime.fromisoformat(f['fill_at']) > datetime.fromisoformat(f['decision_at'])
            price = D(f['price'])
            gross = fee = D(0)
            if f['action'] in ('OPEN', 'ADD'):
                fee = price * facts.multiplier * facts.fees.open_rate + facts.fees.open_per_contract
                assert f['quantity'] == 1
                layers[f['decision_id']] = dict(entry=f, fee=fee)
            else:
                assert f['quantity'] == len(f['layer_ids'])
                for identity in f['layer_ids']:
                    layer = layers.pop(identity)
                    entry = layer['entry']
                    same_day = entry['trading_day'] == f['trading_day']
                    rate = facts.fees.close_today_rate if same_day else facts.fees.close_rate
                    fixed = facts.fees.close_today_per_contract if same_day else facts.fees.close_per_contract
                    cost = price * facts.multiplier * rate + fixed
                    pnl = (price - D(entry['price'])) * facts.multiplier * (1 if entry['side'] == 'LONG' else -1)
                    gross += pnl
                    fee += cost
                    completed.append(dict(kind=entry['action'], side=entry['side'], decision_at=entry['decision_at'],
                                          fill_at=entry['fill_at'], exit_at=f['fill_at'], net=pnl-layer['fee']-cost))
            assert gross == D(f['gross_realized']) and fee == D(f['fee'])
            total_fee += fee
            cash += gross-fee
        equity = cash + sum(((b.close-D(v['entry']['price'])) * facts.multiplier *
                            (1 if v['entry']['side'] == 'LONG' else -1) for v in layers.values()), D(0))
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak-equity)/peak)
    assert cash == D(result['cash']) and equity == D(result['equity']) and total_fee == D(result['fees'])
    assert len(layers) == result['summary']['open_quantity']
    assert sum((v['net'] for v in completed), D(0)) == D(result['net_pnl']) if not layers else True
    adds = [v for v in completed if v['kind'] == 'ADD']
    return dict(net_pnl=result['net_pnl'], fees=result['fees'], rounds=len(result['closed_rounds']),
                add_fills=sum(f['action'] == 'ADD' for f in result['fills']), closed_add_net=sum((v['net'] for v in adds), D(0)),
                losing_adds=sum(v['net'] < 0 for v in adds), completed_close_drawdown_pct=drawdown*100,
                open_quantity=len(layers), pending=result['pending'] is not None,
                long_net=sum((D(v['net_pnl']) for v in result['closed_rounds'] if v['side'] == 'LONG'), D(0)),
                short_net=sum((D(v['net_pnl']) for v in result['closed_rounds'] if v['side'] == 'SHORT'), D(0))), completed


def context_index(rows):
    indexed = {}
    for frequency in ('1d', '30m'):
        items = sorted((r for r in rows if r['frequency'] == frequency), key=lambda r: datetime.fromisoformat(r['time']))
        indexed[frequency] = ([datetime.fromisoformat(r['time']) for r in items], items)
    return indexed


def context_at(indexed, at):
    at = datetime.fromisoformat(at)
    result = {}
    for frequency, (times, rows) in indexed.items():
        i = (bisect_left(times, at) if frequency == '1d' else bisect_right(times, at)) - 1
        result[frequency] = rows[i] if i >= 0 else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('OUTPUT_ALREADY_EXISTS')
    raw, facts = SOURCE.read_bytes(), FACTS.read_bytes()
    old = json.loads(raw)
    assert sha256(facts).hexdigest() == old['facts_file_sha256']
    code_paths = set(old['code_hashes']) | set(old['evidence']['factor_code_hashes']) | {
        str(Path(__file__).relative_to(Path.cwd())) if Path(__file__).is_absolute() else __file__,
        'packages/quant-core/guiyi_quant/indicators/subing_range.py'}
    code = {p: sha256(Path(p).read_bytes()).hexdigest() for p in sorted(code_paths)}
    settings, _ = load_private_readonly_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']), connect_args={'connect_timeout': 5})
    try:
        with Session(engine, autoflush=False) as db, readonly_transaction(db, timeout_seconds=900):
            root = Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
            segments, evidence = load(MarketDataService(MarketCatalog(db, root), CanonicalMonthlyStore(root)),
                                      json.loads(facts), date(2024, 10, 14), date(2026, 10, 19), include_range=True)
    finally:
        engine.dispose()
    assert wire(evidence['sources']) == old['evidence']['sources']
    assert len(segments) == len(old['segments']) == 7
    args.output.mkdir()
    dump(args.output/'experiment.json', dict(code_hashes=code, evidence=evidence,
         source_path=str(SOURCE), source_sha256=sha256(raw).hexdigest(), facts_path=str(FACTS), facts_sha256=sha256(facts).hexdigest(),
         profile=REGIME_PROFILE, sample='Seen development data, not OOS',
         scope='7 independent physical accounts, 100000 each; unchanged costs, theoretical next-open 1/2/3 tick; unverified liquidity; no continuous rollover return',
         policy='Entry unchanged; adds require same-direction completed30m regime and a new pullback strictly after trend resumed; pending ADD cancelled when disallowed; exits unchanged; daily/boxes annotations only'))
    summaries, comparisons, parity = [], [], []
    for seg, previous in zip(segments, old['segments']):
        contract = seg['contract']
        assert contract == previous['contract'] and seg['facts_hash'] == previous['facts_hash']
        obs = baseline_observations(seg['observations'])
        # Exact old completed-close output, including every event and checkpoint.
        assert replay(seg['executions'], obs, previous['result']['run_id']) == previous['result']
        indexed = context_index(seg['range_context'])
        dump(args.output/f'{contract}-environment.json', seg['range_context'])
        for slip in (1, 2, 3):
            prior_path = BASE/f'{contract}-slip{slip}.json'
            prior_raw = prior_path.read_bytes()
            historical = json.loads(prior_raw)['result']
            base = replay(seg['executions'], obs, historical['run_id'], execution_model='theoretical_open', slippage_ticks=slip)
            assert base == historical
            parity.append(dict(contract=contract, slip=slip, old_path=str(prior_path), sha256=sha256(prior_raw).hexdigest(), exact_equal=True))
            candidate = replay(seg['executions'], seg['observations'], historical['run_id']+':regime_add_v1',
                               execution_model='theoretical_open', slippage_ticks=slip, regime_research_profile=REGIME_PROFILE)
            restored = DecisionModel.restore(candidate['decision_checkpoint'])
            assert restored.state() == candidate['decision_state'] and restored.checkpoint() == candidate['decision_checkpoint']
            measurements = {}
            for name, result in (('baseline', base), ('candidate', candidate)):
                metrics, layers = measure(seg['executions'], result)
                path = args.output/f'{contract}-{name}-slip{slip}.json'
                dump(path, dict(contract=contract, since=seg['since'], through=seg['through'], facts_hash=seg['facts_hash'], result=result))
                summaries.append(dict(contract=contract, variant=name, slip=slip, result_sha256=sha256(path.read_bytes()).hexdigest(), **metrics))
                measurements[name] = (metrics, layers)
            base_metrics, base_layers = measurements['baseline']
            new_metrics, new_layers = measurements['candidate']
            added_keys = {(f['side'], f['decision_at']) for f in candidate['fills'] if f['action'] == 'ADD'}
            unmatched = [dict(v, context=context_at(indexed, v['decision_at'])) for v in base_layers
                         if v['kind'] == 'ADD' and (v['side'], v['decision_at']) not in added_keys]
            comparisons.append(dict(contract=contract, slip=slip, net_delta=D(new_metrics['net_pnl'])-D(base_metrics['net_pnl']),
                baseline_adds_absent_in_candidate=unmatched,
                caveat='Unmatched fills are path differences, not isolated causal profit saved/lost',
                baseline_entry_context=[dict(decision_at=f['decision_at'], side=f['side'], context=context_at(indexed, f['decision_at']))
                                        for f in base['fills'] if f['action'] == 'OPEN']))
            print(json.dumps(dict(contract=contract, slip=slip, baseline=base_metrics['net_pnl'], candidate=new_metrics['net_pnl'],
                                 adds=[base_metrics['add_fills'], new_metrics['add_fills']]), default=str), flush=True)
    assert FACTS.read_bytes() == facts and SOURCE.read_bytes() == raw
    assert all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in code.items())
    dump(args.output/'summary.json', summaries)
    dump(args.output/'comparisons.json', comparisons)
    dump(args.output/'verification.json', dict(exact_prior_open_parity=parity, exact_prior_close_parity=7,
         restored_checkpoints=21, independently_reconciled_results=42, source_and_code_unchanged=True))
    lines = ['# 苏冰 v2 加仓过滤对照', '', '已见开发样本；7个独立物理账户，每段10万元；不是连续换月收益或OOS。', '',
             '|合约|滑点|原净损益|候选净损益|差额|原/候选加仓数|原/候选最大收盘盯市回撤%|', '|---|---:|---:|---:|---:|---|---|']
    for pair in comparisons:
        bs, cs = [next(s for s in summaries if s['contract'] == pair['contract'] and s['slip'] == pair['slip'] and s['variant'] == v) for v in ('baseline', 'candidate')]
        lines.append(f"|{pair['contract']}|{pair['slip']}|{D(bs['net_pnl']):.3f}|{D(cs['net_pnl']):.3f}|{pair['net_delta']:.3f}|{bs['add_fills']}/{cs['add_fills']}|{bs['completed_close_drawdown_pct']:.3f}/{cs['completed_close_drawdown_pct']:.3f}|")
    lines += ['', '首仓规则未改变不保证后续首仓时刻相同：加仓改变账户路径、退出和风险资格。被过滤历史层的原损益仅作归因，不等于删除该层的独立收益。',
              '不修改固定 v2，不自动晋升；真正未见样本、实时来源连续性和实际成交均未由本轮证明。']
    (args.output/'report.md').write_text('\n'.join(lines)+'\n')
    print('PASS 42 full-path replays, 28 exact old baselines, 21 restored checkpoints', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # No private DSN, SQL or exception text in diagnostics.
        print(json.dumps(dict(status='FAILED', error_type=type(exc).__name__)), flush=True)
        raise SystemExit(2) from None
