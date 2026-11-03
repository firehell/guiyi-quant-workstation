"""Paired label-increment report; fixed cards and chronological training."""
import json
from pathlib import Path
from collections import defaultdict
from sklearn.metrics import f1_score


def run(root):
    path=root/'regime-owner-increment-20261103';reports={name:json.loads((path/name/'report.json').read_text()) for name in ('control','augmented')}
    assert (path/'control/data.json').read_bytes()==(path/'augmented/data.json').read_bytes()
    data=json.loads((path/'control/data.json').read_text());cards={c['id']:c for c in data['cards']};indexed={name:{(r['card'],r['model']):r for r in report['results']} for name,report in reports.items()}
    assert indexed['control'].keys()==indexed['augmented'].keys()
    for name,rs in indexed.items():
        for (cid,model),r in rs.items():
            val=cards[cid];prior=[c for c in cards.values() if c['frequency']==val['frequency'] and c['end']<val['input_start'] and not (name=='control' and c['round']=='regime-trend-plateau-20261103')]
            assert len(prior)==r['train_paths'] and max(c['end'] for c in prior)==r['train_end']<val['input_start']
            assert r['truth']==[x['y'] for x in val['rows']]
            assert r['agreement']==sum(a==b for a,b in zip(r['predictions'],r['truth']))
    old=json.loads((root/'regime-owner-pilot-20261103/report.json').read_text())
    for r in old['results']:assert indexed['control'][r['card'],r['model']]['predictions']==r['predictions']
    results=[]
    for frequency in ('30m','60m'):
        for model in ('logistic','tree'):
            group=[k for k,r in indexed['control'].items() if r['frequency']==frequency and r['model']==model];row=dict(frequency=frequency,model=model,paths=len(group),events=sum(len(indexed['control'][k]['truth']) for k in group))
            for name in ('baseline','control','augmented'):
                byproduct=defaultdict(lambda:([],[]));agreement=0;false_keep=0
                for k in group:
                    r=indexed['control' if name=='baseline' else name][k];pred=r['baseline'] if name=='baseline' else r['predictions'];truth=r['truth'];t,p=byproduct[r['symbol']];t.extend(truth);p.extend(pred);agreement+=sum(a==b for a,b in zip(truth,pred));false_keep+=sum(a==0 and b!=0 for a,b in zip(truth,pred))
                row[name]=dict(agreement=agreement,false_keep=false_keep,product_equal_macro_f1=sum(f1_score(t,p,labels=[0,1,2],average='macro',zero_division=0) for t,p in byproduct.values())/len(byproduct),products=len(byproduct))
            row['changed_paths']=sum(indexed['control'][k]['predictions']!=indexed['augmented'][k]['predictions'] for k in group)
            results.append(row)
    result=dict(status='NO_CANDIDATE_PROMOTION',role='PAIRED_SEEN_DEVELOPMENT_NOT_OOS',results=results,checks=['same validation cards and truths','strict complete-card chronology','only eligible earlier plateau cards added','original control predictions reproduced'],limitations=['13 validation paths; correlated judgments','No significance or stable gain claim','Some past validation cards cannot use later added labels','Health submodel is conditional, not validated standalone alerts','Daily withheld for insufficient directional path diversity'])
    (path/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(results,indent=2))

if __name__=='__main__':run(Path('output'))
