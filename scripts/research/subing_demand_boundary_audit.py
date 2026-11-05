"""Read-only case boundary audit; illustrative intervals are not inferred labels."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
CARDS = ROOT / 'output/subing-demand-review-20261103-final/cards.json'
ENV = ROOT / 'output/subing-regime-add-20261103-001'
OUT = ROOT / 'output/subing-demand-boundary-audit-20261104'


def audit():
    sources = {str(CARDS.relative_to(ROOT)): hashlib.sha256(CARDS.read_bytes()).hexdigest()}
    results = []
    for card in json.loads(CARDS.read_text())['cards']:
        if card['id'] not in ('C03', 'C04'):
            continue
        end = datetime.fromisoformat(card['at'])
        bars = card['bars']
        assert all(datetime.fromisoformat(b['time']) <= end for b in bars)
        source = ENV / (card['contract'] + '-environment.json')
        sources[str(source.relative_to(ROOT))] = hashlib.sha256(source.read_bytes()).hexdigest()
        observations = [r for r in json.loads(source.read_text())
                        if r['frequency'] == '30m' and datetime.fromisoformat(r['time']) <= end]
        assert observations and datetime.fromisoformat(observations[-1]['time']) == end
        results.append({'case': card['id'], 'at': card['at'],
                        'current_existing_factor': observations[-1]['range_factor'],
                        'last_12_box_count': sum(r['range_factor']['box'] is not None for r in observations[-12:])})
    card = next(c for c in json.loads(CARDS.read_text())['cards'] if c['id'] == 'C04')
    # Explicit illustrative windows, chosen for owner comparison only. No tuning or production policy.
    hypotheses = []
    for name, start in [('recent_local', '2025-09-10T03:00:00+00:00'),
                        ('including_earlier_high', '2025-09-09T03:00:00+00:00')]:
        before = [b for b in card['bars'] if start <= b['time'] < '2025-09-10T15:00:00+00:00']
        upper = max(Decimal(str(b['high'])) for b in before)
        lower = min(Decimal(str(b['low'])) for b in before)
        remaining = [b for b in card['bars'] if b['time'] >= '2025-09-10T15:00:00+00:00']
        closes = [Decimal(str(b['close'])) for b in remaining]
        hypotheses.append({'illustrative_only': True, 'name': name, 'interval_start': start,
                           'interval_last_bar': before[-1]['time'], 'upper': str(upper), 'lower': str(lower),
                           'close_sequence': [str(c) for c in closes],
                           'b0_plus_three_above_upper': len(closes) == 4 and all(c > upper for c in closes)})
    return {'sources_sha256': sources, 'cases': results, 'c04_hypotheses': hypotheses,
            'limitation': 'Archived development observations; not new MDS replay, OOS, or an approved range detector.'}


if __name__ == '__main__':
    result = audit()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    lines = ['# C03/C04 区间核对', '',
             '使用原开发案例和归档环境输出；只读取截至原截止时刻的信息。不是新行情回放或OOS。', '',
             '两个案例末根及各自最后12个归档30m观察均无现有算法箱体。不可将无箱体解释成没有横盘。', '',
             '|C04示例区间（尚未确认）|下沿|上沿|突破当根及后续三根收盘|符合向上确认|', '|---|---|---|---|---|']
    for h in result['c04_hypotheses']:
        lines.append(f"|{h['name']}|{h['lower']}|{h['upper']}|{', '.join(h['close_sequence'])}|{h['b0_plus_three_above_upper']}|")
    lines += ['', '示例窗口仅为定位人工区间差异，不能作为自动选窗规则或交易信号。',
              '需要owner指出C04实际参考区间；若指最近小区间，则三根规则和该案例判断存在冲突，需要保留并解释。']
    (OUT / 'report.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
