"""Read-only diagnostics of frozen SuBing research, never a strategy replay."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo

from app.new_subing_research.store import _read_file, list_results, read_result, read_result_detail

SHANGHAI = ZoneInfo('Asia/Shanghai')
# Frozen engines round arithmetic to 28 significant digits. Retain residuals;
# only sub-1e-18 yuan reconciliation differences are tolerated, never cents.
RECONCILIATION_TOLERANCE = Decimal('1e-18')


class AuditError(ValueError):
    pass


def _money(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise AuditError('MONEY_MUST_BE_DECIMAL_STRING')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise AuditError('INVALID_MONEY') from None
    if not number.is_finite():
        raise AuditError('INVALID_MONEY')
    return number


def _time(value: str) -> datetime:
    at = datetime.fromisoformat(value)
    if at.tzinfo is None or at.utcoffset() is None:
        raise AuditError('TIMEZONE_REQUIRED')
    return at


def _equal(left: Decimal, right: Decimal, code: str) -> Decimal:
    residual = left - right
    if abs(residual) > RECONCILIATION_TOLERANCE:
        raise AuditError(code)
    return residual


def _trade_key(row: dict[str, Any]) -> tuple:
    return (row['physical_contract'], row['side'], _time(row['entry_at']), _time(row['exit_at']))


def analyze_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Attribute recorded round PnL; no counterfactual or entry-link guessing."""
    with localcontext() as context:
        context.prec = 80
        return _analyze(packet)


def _analyze(packet: dict[str, Any]) -> dict[str, Any]:
    meta, summary = packet['metadata'], packet['summary']
    trades = {_trade_key(t): t for t in packet['trades']}
    if len(trades) != len(packet['trades']) or len({t['trade_id'] for t in trades.values()}) != len(trades):
        raise AuditError('DUPLICATE_TRADE')
    rounds: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    total_fees = gross = Decimal(0)
    previous_at: datetime | None = None
    fill_reasons: Counter = Counter()
    for index, fill in enumerate(packet.get('fills', [])):
        at, qty, fee = _time(fill['at']), fill['qty'], _money(fill['fee'])
        if previous_at is not None and at < previous_at:
            raise AuditError('FILLS_NOT_ORDERED')
        previous_at = at
        if type(qty) is not int or qty < 1 or fee < 0 or fill['side'] not in ('LONG', 'SHORT'):
            raise AuditError('INVALID_FILL')
        total_fees += fee
        if fill['action'] == 'OPEN':
            if active is None:
                active = {'physical_contract': fill['physical_contract'], 'side': fill['side'],
                          'entry_at': fill['at'], 'entry_fill_index': index, 'remaining_qty': 0,
                          'fees_value': Decimal(0), 'gross_value': Decimal(0), 'open_count': 0,
                          'max_qty': 0, 'partial_closes': 0, 'entry_decision_link': 'NOT_RECORDED'}
            if (active['physical_contract'], active['side']) != (fill['physical_contract'], fill['side']):
                raise AuditError('POSITION_IDENTITY_CHANGED')
            active['remaining_qty'] += qty
            active['max_qty'] = max(active['max_qty'], active['remaining_qty'])
            active['open_count'] += 1
            active['fees_value'] += fee
        elif fill['action'] == 'CLOSE':
            if active is None or (active['physical_contract'], active['side']) != (fill['physical_contract'], fill['side']):
                raise AuditError('CLOSE_WITHOUT_MATCHING_POSITION')
            if qty > active['remaining_qty']:
                raise AuditError('OVERCLOSE')
            realized = _money(fill['realized_pnl'])
            gross += realized
            active['gross_value'] += realized
            active['fees_value'] += fee
            active['remaining_qty'] -= qty
            fill_reasons[fill['reason']] += 1
            if active['remaining_qty']:
                active['partial_closes'] += 1
                continue
            active.update(exit_at=fill['at'], exit_fill_index=index, exit_reason=fill['reason'])
            trade = trades.pop(_trade_key(active), None)
            if trade is None or trade.get('status') != 'CLOSED':
                raise AuditError('EXACT_TRADE_LINK_MISSING')
            net = active['gross_value'] - active['fees_value']
            residual = _equal(net, _money(trade['net_pnl']), 'ROUND_PNL_MISMATCH')
            row = {k: v for k, v in active.items() if not k.endswith('_value')}
            row.update(trade_id=trade['trade_id'], net_pnl=trade['net_pnl'],
                       net_from_fills=str(net), pnl_residual=str(residual),
                       fees=str(active['fees_value']), gross_pnl=str(active['gross_value']),
                       entry_at_china=_time(active['entry_at']).astimezone(SHANGHAI).isoformat(),
                       exit_at_china=at.astimezone(SHANGHAI).isoformat())
            rounds.append(row)
            active = None
        else:
            raise AuditError('UNKNOWN_FILL_ACTION')
    if trades or len(rounds) != summary['closed_trades']:
        raise AuditError('CLOSED_TRADE_COUNT_MISMATCH')
    ending_qty = active['remaining_qty'] * (1 if active['side'] == 'LONG' else -1) if active else 0
    if ending_qty != summary['ending_qty']:
        raise AuditError('ENDING_POSITION_MISMATCH')
    cash = _money(summary['initial_cash']) + gross - total_fees
    cash_residual = None
    if meta['status'] == 'COMPLETED':
        _equal(total_fees, _money(summary['total_fees']), 'TOTAL_FEES_MISMATCH')
        if not ending_qty:
            cash_residual = str(_equal(cash, _money(summary['final_equity']), 'FINAL_CASH_MISMATCH'))
        elif packet['equity']:
            cash_residual = str(_equal(cash, _money(packet['equity'][-1]['cash']), 'FINAL_CASH_MISMATCH'))
    elif any(summary.get(k) is not None for k in ('final_equity', 'account_return_pct', 'max_drawdown_pct')):
        raise AuditError('INCOMPLETE_ACCOUNT_HAS_FULL_RESULT')
    by_exit: dict[str, Any] = {}
    for row in rounds:
        group = by_exit.setdefault(row['exit_reason'], {'count': 0, 'wins': 0, 'losses': 0,
                                                       'net_pnl': Decimal(0), 'fees': Decimal(0)})
        net = _money(row['net_pnl'])
        group['count'] += 1
        group['wins'] += net > 0
        group['losses'] += net < 0
        group['net_pnl'] += net
        group['fees'] += _money(row['fees'])
    for group in by_exit.values():
        group['net_pnl'], group['fees'] = str(group['net_pnl']), str(group['fees'])
    decisions = packet['decisions']
    if len({d['decision_id'] for d in decisions}) != len(decisions):
        raise AuditError('DUPLICATE_DECISION')
    intents = [d for d in decisions if d['action'] == 'OPEN']
    intent_triggers = Counter(d.get('facts', {}).get('setup_trigger', 'UNKNOWN') for d in intents)
    vote_sets = Counter('+'.join(sorted(k for k, v in d.get('facts', {}).get('votes', {}).items() if v is True))
                        or 'UNKNOWN' for d in intents)
    skipped = [d for d in decisions if d['action'] == 'REDUCE_SKIPPED']
    for row in rounds:
        row['one_lot_skips'] = sum(d['reason'] == 'UNSPLITTABLE_ONE_LOT' and
                                  d.get('physical_contract') == row['physical_contract'] and
                                  _time(row['entry_at']) <= _time(d['at']) <= _time(row['exit_at']) for d in skipped)
        row['daily_upgrades'] = sum(s['stage'] == 'TREND' and
                                   _time(row['entry_at']) <= _time(s['at']) <= _time(row['exit_at'])
                                   for s in packet.get('stages', []))
    open_round = None
    if active:
        open_round = {k: v for k, v in active.items() if not k.endswith('_value')}
        open_round['realized_net_to_date'] = str(active['gross_value'] - active['fees_value'])
    return {
        'metadata': meta, 'status': meta['status'], 'account_return_pct': summary.get('account_return_pct'),
        'frozen_summary': summary, 'closed_rounds': rounds, 'open_round': open_round,
        'closed_round_net': str(sum((_money(r['net_pnl']) for r in rounds), Decimal(0))),
        'recorded_gross_pnl': str(gross), 'recorded_fees': str(total_fees),
        'cash_from_fills': str(cash), 'cash_reconciliation_residual': cash_residual,
        'by_exit_reason': by_exit, 'close_fill_reasons': dict(sorted(fill_reasons.items())),
        'entry_intents': dict(sorted(intent_triggers.items())), 'entry_intent_vote_sets': dict(sorted(vote_sets.items())),
        'entry_intents_without_macd_vote': sum(d.get('facts', {}).get('votes', {}).get('macd') is False for d in intents),
        'decision_counts': dict(sorted(Counter(d['action'] for d in decisions).items())),
        'rejection_events': dict(sorted(Counter(d['reason'] for d in decisions if d['action'] == 'REJECT').items())),
        'one_lot_skip_events': len([d for d in skipped if d['reason'] == 'UNSPLITTABLE_ONE_LOT']),
        'stage_events': dict(sorted(Counter(s['stage'] for s in packet.get('stages', [])).items())),
        'diagnostic_scope': 'recorded facts only; exit groups are not causal attribution; intents are not fills',
        'oos_status': meta.get('oos_status', 'UNKNOWN'), 'case_parity': 'PENDING',
    }


def audit_roots(roots: list[Path]) -> dict[str, Any]:
    """Use the sole frozen-result reader; explicit roots and indexed runs only."""
    runs, sources, seen = [], [], set()
    for root in roots:
        root = root.absolute()
        metadata = list_results(root)
        if not metadata:
            raise AuditError('EMPTY_RESULT_ROOT')
        # Reuse the store's bounded O_NOFOLLOW regular-file reader for hashes too.
        index_before = _read_file(root/'index.json')
        for meta in metadata:
            run_id = meta['run_id']
            if run_id in seen:
                raise AuditError('DUPLICATE_RUN')
            seen.add(run_id)
            packet = read_result(root, run_id)
            if packet['metadata'] != meta:
                raise AuditError('SOURCE_INDEX_CHANGED')
            detail = read_result_detail(root, run_id)
            result = analyze_packet(packet)
            result.update(result_sha256=detail['sha256'], result_root=str(root))
            runs.append(result)
        for result in runs:
            if result['result_root'] == str(root) and read_result_detail(root, result['metadata']['run_id'])['sha256'] != result['result_sha256']:
                raise AuditError('SOURCE_PACKET_CHANGED')
        if _read_file(root/'index.json') != index_before:
            raise AuditError('SOURCE_INDEX_CHANGED')
        sources.append({'root': str(root), 'index_sha256': sha256(index_before).hexdigest(),
                        'run_count': len(metadata)})
    identities: dict[tuple, tuple] = {}
    for run in runs:
        meta = run['metadata']
        key = (meta['product'], meta['requested_since'], meta['requested_through'])
        value = (meta['input_snapshot_hash'], meta['execution_facts_hash'])
        if key in identities and identities[key] != value:
            raise AuditError('COMPARISON_INPUTS_DIFFER')
        identities[key] = value
    return {'schema_version': 1, 'sources': sources, 'runs': runs,
            'reconciliation_tolerance_yuan': str(RECONCILIATION_TOLERANCE),
            'limitations': ['No OHLC replay or counterfactual backtest', 'No unique rejected opportunity denominator',
                            'Entry fills have no recorded decision_id; no nearest-decision guessing',
                            'Completed and interrupted accounts remain separate', 'No original-case or owner-case parity proven']}


def render_casebook(report: dict[str, Any]) -> str:
    lines = ['# 苏冰模型案例核对材料', '',
             '本材料为事后选样，只用于发现方法差异，不是盲测、OOS或你的真实交易。',
             '选择顺序：首笔、最大亏损、最大盈利、时间退出、升级日线、一手无法减仓；去重。',
             '真实行情前缀未附入，冻结Fill/Stage不等于当时完整图形；不能据此作出案例一致性结论。', '']
    for run in report['runs']:
        meta = run['metadata']
        if meta['strategy_code'] != 'new_subing_v2' or meta['scenario'] != 'baseline' or meta.get('initial_cash') != '100000':
            continue
        rows = run['closed_rounds']
        if not rows:
            continue
        candidates = [('首笔', rows[0]), ('最大亏损', min(rows, key=lambda r: _money(r['net_pnl']))),
                      ('最大盈利', max(rows, key=lambda r: _money(r['net_pnl'])))]
        for label, condition in [('时间退出', lambda r: r['exit_reason'] == 'FIVE_BARS_NO_PROFIT'),
                                 ('升级日线', lambda r: r['daily_upgrades'] > 0),
                                 ('一手无法减仓', lambda r: r['one_lot_skips'] > 0)]:
            match = next((r for r in rows if condition(r)), None)
            if match:
                candidates.append((label, match))
        selected: dict[str, tuple[dict, list[str]]] = {}
        for label, row in candidates:
            if row['trade_id'] not in selected:
                selected[row['trade_id']] = (row, [])
            selected[row['trade_id']][1].append(label)
        for row, labels in selected.values():
            lines += [f"## {meta['product']} / {row['physical_contract']} / {'、'.join(labels)}", '',
                      f"- run_id：`{meta.get('run_id', 'TEST_FIXTURE')}`；trade_id：`{row['trade_id']}`。",
                      f"- 结果SHA：`{run.get('result_sha256', 'TEST_FIXTURE')}`；Fill行：{row['entry_fill_index']}–{row['exit_fill_index']}（零起始）。",
                      f"- 模型入场：{row['entry_at_china']}；方向：{row['side']}；最高持仓：{row['max_qty']}手。",
                      f"- 模型退出：{row['exit_at_china']}；原因：{row['exit_reason']}；净损益：{row['net_pnl']}元。",
                      f"- 部分平仓{row['partial_closes']}次；TREND记录{row['daily_upgrades']}次；一手跳过{row['one_lot_skips']}次。",
                      '- 你的入场/放弃判断：UNKNOWN；依据：UNKNOWN。',
                      '- 你的持仓周期/升级条件：UNKNOWN；减仓/清仓判断：UNKNOWN。',
                      '- 判断记录性质：UNKNOWN（同期记录 / 事后回忆 / 遮挡未来后的重判）。',
                      '- 当时可知行情证据：MISSING；原始成交证据：MISSING；一致性：PENDING。', '']
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results-root', type=Path, action='append', required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = args.output_root.resolve()
        roots = [p.absolute() for p in args.results_root]
        if any(output == r.resolve() or output.is_relative_to(r.resolve()) or r.resolve().is_relative_to(output) for r in roots):
            raise AuditError('OUTPUT_OVERLAPS_SOURCE')
        report = audit_roots(roots)
        output.mkdir(parents=True, exist_ok=False)
        (output/'diagnostics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        (output/'casebook.md').write_text(render_casebook(report)+'\n')
        print(json.dumps({'status': 'AUDIT_GENERATED', 'runs': len(report['runs']), 'output_root': str(output)}))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # No exception text: paths and upstream data are not public errors.
        print(json.dumps({'status': 'FAILED', 'error_type': type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
