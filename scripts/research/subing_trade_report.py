"""Print a registered SuBing comparison as one JSON line per simulated trade."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re


def direction_times(archive, contract):
    if not re.fullmatch(r'JM[0-9]{4}', contract['contract']):
        raise ValueError('焦煤合约身份无效')
    prepared = archive / 'prepared' / (contract['contract'] + '.json.gz')
    raw = prepared.read_bytes()
    if sha256(raw).hexdigest() != contract['prepared_sha256']:
        raise ValueError('登记的分钟输入哈希不一致')
    data = json.loads(gzip.decompress(raw))
    times = {}
    for observation in data['observations']:
        at = observation['at']
        hour = data['structures'][at].get('hourly') or {}
        times[at] = dict(daily_at=observation['daily_at'], daily_direction=observation['daily_direction'],
                         hourly_at=hour.get('at'), hourly_direction=hour.get('direction'))
    return times


def project(report, archive=None):
    contexts = {}
    kind = report['kind']
    if kind == 'SEEN_JM_DEVELOPMENT_FIXED_ENTRY_LEGACY_WITNESS':
        pairs = [p for c in report['contracts'] for p in c['pairs']]
        counts = Counter()
        for contract in report['contracts']:
            counts.update(contract['opportunities'])
            if archive is not None:
                contexts[contract['contract']] = direction_times(archive, contract)
        inputs = {c['contract']: dict(prepared_sha256=c['prepared_sha256'],
                                      archived_sha256=c['archived_sha256'], fee_multiplier=c['fee'],
                                      slippage_ticks=c['slip']) for c in report['contracts']}
        metadata = dict(hourly_sha256=report['hourly_sha256'], contracts=inputs,
                        opportunities=counts)
        unmatched = {}
    elif kind in ('THREE_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH',
                  'SEEN_14_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH'):
        pairs = report['matched_entries']
        unmatched = report['unmatched_entries']
        metadata = dict(input_id=report['input_id'], window=report['requested'],
                        fee_multiplier=report['fee_multiplier'], slippage_ticks=report['slippage_ticks'],
                        variant=report['exit_profile'], accounts={
                            label: {k: run[k] for k in ('net_pnl', 'drawdown', 'opportunities',
                                                        'execution_rejections', 'risk_records')}
                            for label, run in report['portfolio_runs'].items()})
    else:
        raise ValueError(report.get('execution_status') or '不支持的研究结果类型')

    yield dict(kind=kind, matched=len(pairs), trade_rows=2 * len(pairs) + sum(map(len, unmatched.values())),
               differences=sum(p['changed'] for p in pairs),
               code_hashes=report['code_hashes'], **metadata)
    for pair in pairs:
        for rule in ('A', 'B'):
            row = trade(rule, pair[rule], '同笔对照')
            if row['contract'] in contexts:
                row.update(contexts[row['contract']][row['decision_at']])
            yield row
    for rule, outcomes in unmatched.items():
        for outcome in outcomes:
            yield trade(rule, outcome, '单侧入场')


def trade(rule, outcome, match):
    opened = outcome['opening']
    closed = outcome['exit'] or {}
    return dict(rule=rule, match=match, contract=opened['contract'], side=opened['side'],
                decision_at=opened['decision_at'], fill_at=opened['fill_at'], price=opened['price'],
                entry_reasons=opened['reasons'], handoff_at=outcome['handoff'],
                exit_decision_at=closed.get('decision_at'), exit_at=closed.get('fill_at'),
                exit_price=closed.get('price'), exit_reasons=closed.get('reasons'),
                net=outcome.get('net'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--archive', type=Path, help='焦煤开发档案，附加信号时已知的日线和小时方向时刻')
    args = parser.parse_args()
    try:
        for row in project(json.loads(args.report.read_bytes()), args.archive):
            print(json.dumps(row, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'无法读取苏冰研究结果：{error}\n')
