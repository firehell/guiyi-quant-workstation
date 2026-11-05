"""Chronological whole-card development pilot; never sealed OOS or live inference."""
import argparse
from collections import Counter
from hashlib import sha256
import gzip
import json
from pathlib import Path

ROUNDS=[('regime-trend-lifecycle-20261102','regime-trend-owner-20261103-eb733ddf'),('regime-trend-fresh-20261103','regime-trend-fresh-owner-20261103-69a56196'),('regime-trend-support-20261103-final','regime-trend-support-owner-20261103-fd5b06cf')]
FEATURES=['close_ema10','close_ema21','close_ema60','ema10_21','ema21_60','slope10','slope21','slope60','progress6','progress10','progress14','efficiency14','range6','range14','age_high14','age_low14']


def digest(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def features(s,cut):
    end=cut-1;bars=s['bars'][:cut];emas=s['emas'];close=bars[-1]['close']
    atr=sum(max(bars[i]['high']-bars[i]['low'],abs(bars[i]['high']-bars[i-1]['close']),abs(bars[i]['low']-bars[i-1]['close'])) for i in range(cut-14,cut))/14
    if atr<=0:raise ValueError('INVALID_SCALE')
    values=[(close-emas[str(n)][end])/atr for n in (10,21,60)]
    values += [(emas['10'][end]-emas['21'][end])/atr,(emas['21'][end]-emas['60'][end])/atr]
    values += [(emas[str(n)][end]-emas[str(n)][end-3])/atr for n in (10,21,60)]
    values += [(close-bars[-1-n]['close'])/atr for n in (6,10,14)]
    travel=sum(abs(bars[i]['close']-bars[i-1]['close']) for i in range(cut-14,cut))
    values += [abs(close-bars[-15]['close'])/travel if travel else 0]
    values += [(max(b['high'] for b in bars[-n:])-min(b['low'] for b in bars[-n:]))/atr for n in (6,14)]
    values += [(13-max(range(14),key=lambda i:(bars[-14:][i]['high'],i)))/14,(13-min(range(14),key=lambda i:(bars[-14:][i]['low'],-i)))/14]
    return values


def prepare(root,output,include_plateau=False):
    from scripts.research.regime_trend_review import validate
    source=root/'regime-learning-20261102-final';snap=json.loads((source/'snapshot.json').read_text());run=json.loads((source/'run.json').read_text())
    if digest(snap)!=run['dataset_id']:raise ValueError('SOURCE_IDENTITY')
    cards=[];identities=[];wanted={}
    rounds=ROUNDS+([('regime-trend-plateau-20261103','regime-trend-plateau-owner-20261103-f9616891')] if include_plateau else [])
    for folder,archive in rounds:
        p=json.loads((root/folder/'boundary.json').read_text());raw=(root/archive/'owner-answers.json').read_bytes();a=json.loads(raw);validate(p,a)
        if digest({k:v for k,v in p.items() if k!='dataset_id'})!=p['dataset_id']:raise ValueError('CARD_IDENTITY')
        identities.append(dict(dataset=p['dataset_id'],answers_sha256=sha256(raw).hexdigest()))
        for s in p['samples']:
            if s['frequency']=='1d':continue
            rows=[]
            for event in a['answers'][s['id']]:
                choice=event['choice'];cut=event['cut'];bar=s['bars'][cut-1]
                if choice=='uncertain':continue
                if bar['day']>=snap['splits']['test_from']:raise ValueError('SEALED_FORBIDDEN')
                x=features(s,cut)
                # Prefix feature identity: removing every later bar/EMA must preserve features.
                prefix=dict(s,bars=s['bars'][:cut],emas={k:v[:cut] for k,v in s['emas'].items()})
                if x!=features(prefix,cut):raise ValueError('FUTURE_FEATURE_DEPENDENCY')
                r=dict(time=bar['time'],cut=cut,x=x,y=1 if choice.startswith('up_') else 2 if choice.startswith('down_') else 0,warning=int(choice.endswith('warning')),choice=choice)
                key=(s['symbol'],s['frequency'],s['contract'],bar['time'])
                if key in wanted:raise ValueError('DUPLICATE_QUERY')
                wanted[key]=(r,bar);rows.append(r)
            cards.append(dict(round=folder,id=s['id'],symbol=s['symbol'],frequency=s['frequency'],input_start=s['bars'][0]['time'],end=s['bars'][-1]['time'],rows=rows))
    for entry in snap['rows']:
        if not any(k[:2]==(entry['symbol'],entry['frequency']) for k in wanted):continue
        path=source/entry['file']
        if path.resolve().parent!=source.resolve() or sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('SOURCE_FILE_CHANGED')
        with gzip.open(path,'rt') as stream:
            for line in stream:
                b=json.loads(line);key=(b['symbol'],b['frequency'],b['contract'],b['time'])
                if b['owned'] and key in wanted:
                    row,bar=wanted[key]
                    if bar!={k:b[k] for k in bar}:raise ValueError('BAR_CHANGED')
                    if 'baseline' in row:raise ValueError('DUPLICATE_OWNER')
                    row['baseline']={'RANGE':0,'TREND_UP':1,'TREND_DOWN':2,'UNKNOWN':-1}[b['baseline']]
    if any('baseline' not in r for c in cards for r in c['rows']):raise ValueError('MISSING_BASELINE')
    payload=dict(role='SEEN_DEVELOPMENT_CHRONOLOGICAL_PILOT',sealed_test_evaluated=False,identities=identities,features=FEATURES,cards=cards)
    output.mkdir(parents=True,exist_ok=False);(output/'data.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2));print('PREPARED',len(cards),sum(len(c['rows']) for c in cards))


def train(output,exclude_plateau=False):
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import f1_score
    data=json.loads((output/'data.json').read_text());results=[];skips=[]
    for val in sorted(data['cards'],key=lambda c:c['input_start']):
        prior=[c for c in data['cards'] if c['frequency']==val['frequency'] and c['end']<val['input_start'] and not (exclude_plateau and c['round']=='regime-trend-plateau-20261103')]
        rows=[dict(r,product=c['symbol']) for c in prior for r in c['rows']]
        if len(prior)<2 or {r['y'] for r in rows}!={0,1,2}:
            skips.append(dict(card=val['id'],frequency=val['frequency'],symbol=val['symbol'],reason='INSUFFICIENT_PRIOR_PATHS_OR_DIRECTION_CLASSES',prior_paths=len(prior)));continue
        x=np.array([r['x'] for r in rows]);y=np.array([r['y'] for r in rows]);vx=np.array([r['x'] for r in val['rows']]);vy=np.array([r['y'] for r in val['rows']]);base=np.array([r['baseline'] for r in val['rows']])
        counts=Counter(r['product'] for r in rows);weights=np.array([1/counts[r['product']] for r in rows]);weights*=len(weights)/weights.sum()
        scaler=StandardScaler().fit(x,sample_weight=weights);x=scaler.transform(x);vx=scaler.transform(vx)
        models={'logistic':LogisticRegression(C=.1,max_iter=2000,random_state=17),'tree':HistGradientBoostingClassifier(max_iter=60,max_depth=2,min_samples_leaf=10,l2_regularization=3,random_state=17)}
        for name,model in models.items():
            model.fit(x,y,sample_weight=weights);pred=model.predict(vx)
            warning=None;mask=y!=0;wy=np.array([r['warning'] for r in rows])[mask]
            if len(set(wy))==2:
                health=LogisticRegression(C=.1,max_iter=2000,random_state=17);health.fit(x[mask],wy,sample_weight=weights[mask]);wp=health.predict(vx);valid=vy!=0
                warning=dict(correct=int((wp[valid]==np.array([r['warning'] for r in val['rows']])[valid]).sum()),n=int(valid.sum()),predictions=wp.tolist())
            results.append(dict(card=val['id'],symbol=val['symbol'],frequency=val['frequency'],model=name,train_paths=len(prior),train_end=max(c['end'] for c in prior),validation_input_start=val['input_start'],agreement=int((pred==vy).sum()),baseline_agreement=int((base==vy).sum()),macro_f1=float(f1_score(vy,pred,labels=[0,1,2],average='macro',zero_division=0)),baseline_macro_f1=float(f1_score(vy,base,labels=[0,1,2],average='macro',zero_division=0)),false_keep=int(((vy==0)&(pred!=0)).sum()),baseline_false_keep=int(((vy==0)&(base!=0)).sum()),predictions=pred.tolist(),truth=vy.tolist(),baseline=base.tolist(),warning=warning))
    report=dict(exclude_plateau_training=exclude_plateau,script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),role=data['role'],data_sha256=sha256((output/'data.json').read_bytes()).hexdigest(),sealed_test_evaluated=False,results=results,skips=skips,limitations=['All cards were already reviewed for development; chronological separation does not make them untouched OOS','No pooled Bar accuracy confidence interval','Health evaluated only where owner direction exists; not an execution decision','One fixed configuration per learner, seed17, no neural model or promotion'])
    target=output/'report.json'
    if target.exists():raise ValueError('OUTPUT_EXISTS')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(dict(evaluated=len(results),skipped=len(skips),rows=[{k:r[k] for k in ('symbol','frequency','model','agreement','baseline_agreement','false_keep','baseline_false_keep')} for r in results]),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','train']);p.add_argument('--output',type=Path,required=True);p.add_argument('--include-plateau',action='store_true');p.add_argument('--exclude-plateau-training',action='store_true');a=p.parse_args();prepare(Path('output'),a.output,a.include_plateau) if a.mode=='prepare' else train(a.output,a.exclude_plateau_training)
