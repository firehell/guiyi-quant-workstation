"""Deterministic fresh development cards; no model-based selection or test access."""
from collections import deque
import gzip
from hashlib import sha256
import json
from pathlib import Path
from app.market_data.new_subing_research import payload_hash
from guiyi_quant.indicators.ema import initial_ema_state, step_ema
from scripts.research.regime_trend_review import VERSION


def build(root, output, batch="first"):
    if batch not in ("first", "support", "plateau"):
        raise ValueError("BATCH_INVALID")
    source = root / 'regime-learning-20261102-final'
    snapshot = json.loads((source / 'snapshot.json').read_text())
    run = json.loads((source / 'run.json').read_text())
    if payload_hash(snapshot) != run['dataset_id']:
        raise ValueError('SOURCE_CHANGED')
    seen = []
    for directory in (source, root / 'regime-calibration-20261102-final'):
        html = (directory / 'index.html').read_text()
        data = json.loads(html.split('const DATA=', 1)[1].split(';\nconst $=', 1)[0])
        if data['dataset_id'] == '':
            raise ValueError('IDENTITY_MISSING')
        seen.extend(data['samples'])
    if batch in ('support', 'plateau'):
        for folder in ('regime-trend-lifecycle-20261102', 'regime-trend-fresh-20261103'):
            seen.extend(json.loads((root / folder / 'boundary.json').read_text())['samples'])
    if batch == 'plateau':
        seen.extend(json.loads((root / 'regime-trend-support-20261103-final' / 'boundary.json').read_text())['samples'])
    # Fixed product/frequency pairs chosen before examining new owner labels.
    pairs = [('cf','30m'), ('sa','30m'), ('cu','60m'), ('m','60m'), ('rb','1d'), ('a','1d')]
    if batch in ('support', 'plateau'):
        pairs = [('i','30m'), ('p','30m'), ('cf','60m'), ('sa','60m'), ('rb','60m'), ('a','60m'), ('m','1d'), ('y','1d')]
    if batch == 'plateau':
        pairs = [('cf','30m'), ('sa','30m'), ('p','30m'), ('cf','60m'), ('sa','60m'), ('rb','60m')]
    samples = []
    for symbol, frequency in pairs:
        entry = next(e for e in snapshot['rows'] if (e['symbol'],e['frequency']) == (symbol,frequency))
        path = source / entry['file']
        if path.resolve().parent != source.resolve() or sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('FILE_CHANGED')
        excluded = [(s['bars'][0]['time'],s['bars'][-1]['time']) for s in seen
                    if s['symbol'] == symbol and s['frequency'] == frequency]
        segment = None
        best = None
        with gzip.open(path, 'rt') as stream:
            for line in stream:
                b = json.loads(line)
                if b['day'] >= snapshot['splits']['test_from']:
                    continue
                if b['segment'] != segment:
                    segment = b['segment']
                    states = {n:initial_ema_state(n) for n in (10,21,60)}
                    window = deque(maxlen=64)
                    count = 0
                values = {}
                for n in states:
                    states[n], point = step_ema(states[n],b['close'],bar_end=b['time'])
                    values[str(n)] = point.value if point.ready and point.valid else None
                window.append((b,values)); count += 1
                if len(window) != 64 or count % 16 or not all(x['owned'] for x,_ in window):
                    continue
                if any(v is None for _,vs in window for v in vs.values()):
                    continue
                if batch == 'support' and frequency == '60m' and symbol in ('cf', 'sa'):
                    # Selection uses only the initially visible prefix; no model/owner answers.
                    initial = list(window)[39][1]
                    earlier = list(window)[36][1]
                    if not (initial['21'] < initial['60'] and initial['60'] < earlier['60']):
                        continue
                if batch == 'plateau':
                    initial_bars=[x for x,_ in list(window)[:40]]
                    if initial_bars[0]['day'] < '2025-07-01':
                        continue
                    travel=sum(abs(initial_bars[i]['close']-initial_bars[i-1]['close']) for i in range(26,40))
                    if travel <= 0 or abs(initial_bars[39]['close']-initial_bars[25]['close'])/travel > .3:
                        continue
                start,end = window[0][0]['time'],window[-1][0]['time']
                if any(start <= hi and end >= lo for lo,hi in excluded):
                    continue
                seed = 'trend-fresh-v1' if batch == 'first' else ('trend-support-v1' if batch == 'support' else 'trend-plateau-v1')
                identity = sha256(f'{seed}:{symbol}:{frequency}:{segment}:{end}'.encode()).hexdigest()
                if best is None or identity < best['id']:
                    best = dict(id=identity,symbol=symbol,frequency=frequency,contract=b['contract'],
                        bars=[{k:x[k] for k in ('time','day','open','high','low','close')} for x,_ in window],
                        emas={str(n):[vs[str(n)] for _,vs in window] for n in states})
        if best is None:
            raise ValueError(f'INSUFFICIENT:{symbol}:{frequency}')
        samples.append(best)
    template = Path('scripts/research/regime_trend_review.html').read_text()
    template = template.replace('4个已见片段','6个新开发片段').replace('4个片段','6个片段').replace('这4段','这6段')
    template = template.replace('这是已见开发案例的语义校准，不是未见测试', '这些片段未出现在此前复核卡片中，属于开发区语义验证，不是封存测试')
    template = template.replace('${current+1}/4','${current+1}/${DATA.samples.length}').replace('${Object.values(answers).filter(done).length}/4','${Object.values(answers).filter(done).length}/${DATA.samples.length}').replace('current===3','current===DATA.samples.length-1')
    template = template.replace('表示原方向还在，但已开始衰减','表示该方向已经成立，但存在走弱或失败风险；不表示尚未确认')
    if batch in ('support', 'plateau'):
        template = template.replace('6个新开发片段', '8个补充开发片段').replace('这6段', '这8段')
    if batch == 'plateau':
        template = template.replace('8个补充开发片段', '6个整理边界片段').replace('这8段', '这6段')
    payload = dict(label_version=VERSION,source_dataset_id=run['dataset_id'],samples=samples,start=40,
        role='FRESH_DEVELOPMENT_SEMANTICS_NOT_SEALED_TEST',batch=batch,sampling='fixed pairs; minimum SHA256 over eligible stride16 windows; excludes all prior displayed cards; support CF/SA60m initial cut40 downward EMA context; plateau initial14 ER<=0.3 and input starts after 2025-07-01',template_hash=sha256(template.encode()).hexdigest())
    public = dict(payload,dataset_id=payload_hash(payload))
    output.mkdir(parents=True,exist_ok=False)
    (output/'boundary.json').write_text(json.dumps(public,ensure_ascii=False,indent=2))
    (output/'index.html').write_text(template.replace('__DATA__',json.dumps(public,ensure_ascii=False).replace('<','\\u003c')))
    (output/'run.json').write_text(json.dumps(dict(status='WAIT_LABEL_REVIEW',dataset_id=public['dataset_id'],label_version=VERSION,training_permitted=False)))
    print(json.dumps(dict(dataset_id=public['dataset_id'],cards=len(samples))))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('output'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--batch',choices=('first','support','plateau'),default='first')
    args = parser.parse_args()
    build(args.root,args.output,args.batch)
