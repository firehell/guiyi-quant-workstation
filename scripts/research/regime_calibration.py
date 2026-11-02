"""Prepare fresh development cards for the owner's structural labeling rubric.

No new automatic label, parameter fitting, sealed-test evaluation or promotion.
"""
import argparse
from collections import Counter, deque
from hashlib import sha256
import gzip
import json
from pathlib import Path

from app.market_data.new_subing_research import payload_hash
from guiyi_quant.indicators.ema import initial_ema_state, step_ema
from scripts.research.regime_learning_core import BlindPool, FREQUENCIES, blind_payload, sample_partition

VERSION = 'owner_structure_calibration_v1'
LABELS = ('TREND_UP', 'TREND_DOWN', 'RANGE', 'DISPUTED')
RUBRIC = ('判断右侧最后一根收盘时的状态，不预测未来。上涨：沿均线向上推进，回撤未破坏支撑结构；'
          '下跌：沿均线向下推进，反弹未破坏阻力结构。短暂整理保留趋势；'
          '持续横向往返、失去方向推进时可判震荡，不必等待原趋势结构被突破。'
          '看不清请选择不确定。紫线为共享 EMA21，只作看图辅助，不是分类答案。'
          '请在备注说明：沿线推进／短暂整理／持续横盘／结构破坏／证据不足，并可写大约持续几根。')


def overlaps(a, b):
    # Conservative cross-frequency exclusion: the same product's calendar interval is seen.
    return a['symbol'] == b['symbol'] and not (
        a['bars'][-1]['time'] < b['bars'][0]['time'] or b['bars'][-1]['time'] < a['bars'][0]['time'])


def select(pool, prior, quota=2):
    selected, deficits = [], {}
    sectors, products = Counter(), Counter()
    for frequency in FREQUENCIES:
        for label in LABELS:
            available = [s for (f, c, _), xs in pool.pools.items() if (f, c) == (frequency, label) for s in xs]
            count = 0
            while available and count < quota:
                available.sort(key=lambda s: (products[s['symbol']], sectors[s['sector']], s['rank']))
                s = available.pop(0)
                if any(overlaps(s, p) for p in (*prior, *selected)):
                    continue
                selected.append(s)
                products[s['symbol']] += 1
                sectors[s['sector']] += 1
                count += 1
            if count < quota:
                deficits[f'{frequency}:{label}'] = quota-count
    return sorted(selected, key=lambda s: s['rank']), deficits


def validate_prior(pool, public, identity):
    samples, deficits = pool.select()
    if deficits or blind_payload(samples, identity) != public:
        raise ValueError('CALIBRATION_PRIOR_CONTENT_CHANGED')


def content_hash(samples):
    return payload_hash([{k:s[k] for k in ('id','symbol','frequency','contract','bars','ema21')} for s in samples])


def build(dataset, output):
    code_hash = sha256(Path(__file__).read_bytes()).hexdigest()
    snapshot = json.loads((dataset/'snapshot.json').read_text())
    run = json.loads((dataset/'run.json').read_text())
    if payload_hash(snapshot) != run['dataset_id'] or run['status'] != 'WAIT_LABEL_REVIEW':
        raise ValueError('CALIBRATION_SOURCE_INVALID')
    public_old = json.loads((dataset/'index.html').read_text().split('const DATA=', 1)[1].split(';\nconst $=', 1)[0])
    if public_old['dataset_id'] != run['dataset_id']:
        raise ValueError('CALIBRATION_PRIOR_INVALID')
    prior = public_old['samples']
    pool = BlindPool(snapshot['splits']['test_from'])
    original_pool = BlindPool(snapshot['splits']['test_from'])
    for entry in snapshot['rows']:
        source = dataset/entry['file']
        if source.resolve().parent != dataset.resolve() or sha256(source.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('CALIBRATION_SOURCE_CHANGED')
        window, segment = deque(maxlen=64), None
        with gzip.open(source, 'rt') as stream:
            for line in stream:
                b = json.loads(line)
                # Files contain multiple physical segments, so do not break at one segment's cutoff.
                if b['day'] >= snapshot['splits']['test_from']:
                    continue
                if b['segment'] != segment:
                    segment, window = b['segment'], deque(maxlen=64)
                window.append({k: b[k] for k in ('time', 'day', 'open', 'high', 'low', 'close')})
                if not b['owned'] or b['partition'] != 'DEVELOPMENT':
                    continue
                bars = list(window)
                if sample_partition(symbol=b['symbol'], days=[x['day'] for x in bars], splits=snapshot['splits']) != 'DEVELOPMENT':
                    continue
                original_pool.offer(symbol=b['symbol'], frequency=b['frequency'], contract=b['contract'],
                                    sector=b['sector'], label=b['reference']['label'], bars=bars)
                s = dict(symbol=b['symbol'], bars=bars)
                if any(overlaps(s, p) for p in prior):
                    continue
                pool.offer(symbol=b['symbol'], frequency=b['frequency'], contract=b['contract'],
                           sector=b['sector'], label=b['reference']['label'], bars=bars)
    validate_prior(original_pool, public_old, run['dataset_id'])
    samples, deficits = select(pool, prior)
    if deficits:
        raise ValueError('CALIBRATION_SAMPLES_INSUFFICIENT')
    # Compute the display-only EMA from the complete same-physical archived prefix.
    for entry in snapshot['rows']:
        targets = [s for s in samples if (s['symbol'], s['frequency']) == (entry['symbol'], entry['frequency'])]
        if not targets:
            continue
        needed = {(s['contract'], s['bars'][-1]['time']): s for s in targets}
        found, segment, window = set(), None, deque(maxlen=64)
        with gzip.open(dataset/entry['file'], 'rt') as stream:
            for line in stream:
                b = json.loads(line)
                if b['day'] >= snapshot['splits']['test_from']:
                    continue
                if b['segment'] != segment:
                    segment, window, ema = b['segment'], deque(maxlen=64), initial_ema_state(21)
                ema, point = step_ema(ema, b['close'], bar_end=b['time'])
                window.append((b['time'], point.value if point.ready and point.valid else None))
                key = (b['contract'], b['time'])
                if key in needed and b['owned']:
                    s = needed[key]
                    if [t for t, _ in window] != [x['time'] for x in s['bars']]:
                        raise ValueError('CALIBRATION_EMA_ALIGNMENT')
                    s['ema21'] = [v for _, v in window]
                    found.add(key)
                    if found == set(needed):
                        break
        if found != set(needed):
            raise ValueError('CALIBRATION_EMA_MISSING')
    # Reject drift between sampling and display-prefix reads.
    for entry in snapshot['rows']:
        if sha256((dataset/entry['file']).read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('CALIBRATION_SOURCE_CHANGED')
    template = Path(__file__).with_name('regime_learning.html').read_text()
    spec = dict(version=VERSION, source_dataset_id=run['dataset_id'], rubric=RUBRIC,
                selected=[s['id'] for s in samples],
                public_content_hash=content_hash(samples),
                template_sha256=sha256(template.encode()).hexdigest(), ema_policy='shared EMA21 sma_window, full physical prefix',
                exclusion='all original 90 calendar windows, same product across frequencies',
                purpose='development semantic calibration, NOT OOS', per_frequency=8,
                source_code_sha256=code_hash)
    identity = payload_hash(spec)
    public = blind_payload(samples, identity)
    public['label_version'] = VERSION
    for s, raw in zip(public['samples'], samples):
        s['ema21'] = raw['ema21']
    template = Path(__file__).with_name('regime_learning.html').read_text()
    template = template.replace('图中没有模型答案、均线或未来K线。趋势允许回撤；看不清方向可选“不确定”。本轮只使用开发区间，未使用封存测试区。', RUBRIC+' 本轮24张新开发片段，非未见测试。')
    template = template.replace("ctx.fillStyle='#687991';ctx.fillText(bars[0]", "ctx.strokeStyle='#7956b5';ctx.lineWidth=1.5;ctx.beginPath();let started=false;s.ema21.forEach((v,i)=>{if(v===null){started=false;return}const x=10+(i+.5)*dx;if(started)ctx.lineTo(x,y(v));else ctx.moveTo(x,y(v));started=true});ctx.stroke();ctx.lineWidth=1;\nctx.fillStyle='#687991';ctx.fillText(bars[0]")
    if sha256(Path(__file__).read_bytes()).hexdigest() != code_hash:
        raise ValueError('CALIBRATION_CODE_CHANGED')
    output.mkdir(parents=True, exist_ok=False)
    (output/'index.html').write_text(template.replace('__DATA__', json.dumps(public, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')))
    (output/'run.json').write_text(json.dumps(dict(status='WAIT_LABEL_REVIEW', dataset_id=identity, label_version=VERSION, training_permitted=False), indent=2))
    (output/'calibration.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    (output/'review-key.json').write_text(json.dumps(dict(dataset_id=identity, references=[{k: s[k] for k in ('id', 'symbol', 'frequency', 'reference')} for s in samples]), indent=2))
    print(json.dumps(dict(status='WAIT_LABEL_REVIEW', samples=len(samples), dataset_id=identity)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.dataset, args.output)
