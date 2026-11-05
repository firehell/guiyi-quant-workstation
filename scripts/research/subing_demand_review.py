"""Build bounded causal decision cards from explicit previously verified research assets."""
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import argparse
import gzip
import json

ROOT = Path('output/subing-regime-add-20261103-001')
BARS = Path('output/regime-learning-20261102-final/jm-30m.jsonl.gz')
CONTRACTS = ('JM2501','JM2505','JM2509','JM2601','JM2605','JM2609','JM2701')
VERSION = 'subing_demand_review_v1'


def build(output):
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((ROOT/'summary.json').read_text())
    with gzip.open(BARS,'rt') as f:
        rows = [json.loads(line) for line in f]
    by_contract = {c: sorted((r for r in rows if r['contract']==c),key=lambda r:datetime.fromisoformat(r['time'])) for c in CONTRACTS}
    cards, keys, used, source_hashes = [], [], set(), {}
    selectors = [
        ('空仓观察', lambda x: x['before']['quantity']==0 and x['facts']['m30']['regime']=='RANGE' and x['facts']['m30']['near_zero_golden'] is True),
        ('已有多头仓位', lambda x: x['before']['side']=='LONG' and x['facts']['m30']['regime']=='RANGE' and Decimal(x['facts']['remaining_net'] or '0')>0 and not x['actions']),
        ('已有空头仓位', lambda x: x['before']['side']=='SHORT' and x['facts']['m30']['regime']=='RANGE' and not x['actions']),
        ('环境发生变化', lambda x: x['before']['quantity']>0 and x['before']['regime']=='RANGE' and x['facts']['m30']['regime'] in ('TREND_UP','TREND_DOWN')),
        ('持仓保护核对', lambda x: x['before']['quantity']>0 and any(a['kind']=='CLOSE' for a in x['actions'])),
        ('退出后的新机会', lambda x: x['before']['quantity']==0 and x['before']['last_flat_at'] is not None and any(a['kind']=='OPEN' for a in x['actions'])),
    ]
    candidates = []
    for c in CONTRACTS:
        p=ROOT/f'{c}-candidate-slip1.json';raw=p.read_bytes();h=sha256(raw).hexdigest()
        assert h==next(r['result_sha256'] for r in manifest if r['contract']==c and r['variant']=='candidate' and r['slip']==1)
        source_hashes[str(p)]=h
        data=json.loads(raw)['result']
        events=data['decision_checkpoint']['events']
        frames={datetime.fromisoformat(e['at']):e['m30'] for e in events if e['kind']=='observe' and e['m30'] is not None}
        for x in data['trace']:
            if x['facts'].get('m30') is not None:
                candidates.append((c,x,frames))
    for title, choose in selectors:
        found=False
        for c,x,frames in candidates:
            facts=x['facts'];at=datetime.fromisoformat(facts['at'])
            if any(previous[0]==c for previous in used) or not choose(x):continue
            visible=[r for r in by_contract[c] if datetime.fromisoformat(r['time'])<=at][-64:]
            if len(visible)<40 or datetime.fromisoformat(visible[-1]['time'])!=at:continue
            assert all(Decimal(str(visible[-1][k]))==Decimal(facts['m30'][k] if k!='close' else facts['close']) for k in ('high','low','close'))
            assert visible[-1]['baseline']==facts['m30']['regime']
            candles=[]
            for r in visible:
                t=datetime.fromisoformat(r['time']);frame=frames.get(t)
                if frame:
                    assert all(Decimal(str(r[k]))==Decimal(frame[k]) for k in ('high','low'))
                    assert r['baseline']==frame['regime']
                candles.append({**{k:r[k] for k in ('time','open','high','low','close')},'ema':frame['ema21'] if frame else None})
            before=x['before']
            position={k:before[k] for k in ('side','quantity','layers','initial_stop','profit_target','profit_taken','entry_volume_tier','pending','last_flat_at','pullback','completed_m30','entry_windows','reset_after')}
            card=dict(id=f'C{len(cards)+1:02}',kind='HISTORICAL_MODEL',title=title,contract=c,at=facts['at'],bars=candles,
                      position=position,facts=facts,question='只依据当前可见信息，你希望模型下一步做什么？若与已确认规则不同，请说明希望修改的规则。')
            cards.append(card);keys.append(dict(id=card['id'],source=str(ROOT/f'{c}-candidate-slip1.json'),event_id=x['event_id'],actions=x['actions']))
            used.add((c,facts['at']));found=True;break
        if not found:raise ValueError('SCENARIO_NOT_FOUND: '+title)
    cards += [
      dict(id='S01',kind='POLICY_SCENARIO',title='主力切换边界',question='工程情境，不对应真实交易：旧合约仍有盈利模型底仓，已收到权威主力切换信息。已确定不自动移仓。你希望何时安排旧合约退出？',options=['确认切换后，在旧合约下一可执行时点申请退出','提前退出，但只能基于当时已知的明确触发条件','其他／不确定'],note='不得回到切换信息尚未知晓的时刻成交。若旧合约未成交，退出义务应继续保留；新主力是否必须等旧仓退出后才开仓，请在理由中注明。'),
      dict(id='S02',kind='POLICY_SCENARIO',title='数据中断与恢复',question='工程情境，不对应真实交易：模型有仓，30m来源出现缺口；独立可信的完成1m仍可用。你希望哪些动作继续？恢复后，原加仓资格如何处理？',options=['暂停新增；仅执行数据仍充分的既有保护退出；恢复后等新资格','暂停全部决策并提示人工处理','其他／不确定'],note='没有足够数据的条件必须显示未知，不能推断未触发。请说明是否需要其他保护措施。')]
    payload=dict(version=VERSION,cards=cards,scope='Seen historical development examples, not OOS. Model positions are offline hypothetical fills; two policy scenarios are not real market events.')
    payload['dataset_id']=sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
    for card in cards[:6]:
        assert all(datetime.fromisoformat(b['time'])<=datetime.fromisoformat(card['at']) for b in card['bars'])
        assert datetime.fromisoformat(card['facts']['daily_at'])<datetime.fromisoformat(card['at'])
    template=Path(__file__).with_suffix('.html').read_text()
    html=template.replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c'))
    (output/'index.html').write_text(html)
    (output/'run.json').write_text(json.dumps(dict(status='WAIT_LABEL_REVIEW',version=VERSION,dataset_id=payload['dataset_id'],source_hashes=source_hashes,bars_sha256=sha256(BARS.read_bytes()).hexdigest()),ensure_ascii=False))
    (output/'review-key.json').write_text(json.dumps(keys,ensure_ascii=False))
    (output/'cards.json').write_text(json.dumps(payload,ensure_ascii=False))
    print(json.dumps(dict(cards=len(cards),historical=6,policy_scenarios=2,dataset_id=payload['dataset_id'])))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
