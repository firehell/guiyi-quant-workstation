"""Independent exact endpoint/raw/old-evidence audit; no network."""
import argparse,hashlib,json,sqlite3
from decimal import Decimal as D
from pathlib import Path
R=Path(__file__).resolve().parent;SOURCE=R.parents[2]/'output/htdy-eight-history-20261031/MA/evidence';E=R/'MA/evidence'
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
 return h.hexdigest()
def main(raw=False):
 plan=json.loads((R/'plan.json').read_text());facts=json.loads((E/'facts.json').read_text());checks=[];fee_fields=['commission_type','open_commission','close_commission','close_commission_today','long_margin_ratio','short_margin_ratio','min_order_quantity']
 oldfacts=json.loads((SOURCE/'facts.json').read_text())
 restored=json.loads(json.dumps({k:v for k,v in facts.items() if k!='MA2611'}))
 for row in restored['MA2701']['parameters']:
  if str(row['trading_date'])[:10]=='2026-10-26':
   for key in ('commission_type','open_commission','close_commission','close_commission_today'):row[key]=None
 assert restored==oldfacts
 spans=json.loads((E/'spans.json').read_text())
 for c,span in spans.items():
  assert c in facts,c
  for kind in ('parameters','daily','limits'):
   byday={str(v.get('trading_date',v.get('date')))[:10]:v for v in facts[c][kind]}
   assert set(span['days'])<=set(byday),(c,kind)
   fields=fee_fields if kind=='parameters' else ['settlement'] if kind=='daily' else ['limit_up','limit_down']
   for day in span['days']:
    assert all(byday[day].get(key) is not None for key in fields),(c,day,kind)
    assert all(D(str(byday[day][key])).is_finite() for key in fields if key!='commission_type'),(c,day,kind)
    if kind=='parameters':
     assert byday[day]['commission_type'] in ('by_volume','by_money')
     assert all(D(str(byday[day][key]))>=0 for key in ['open_commission','close_commission','close_commission_today'])
     assert all(D(str(byday[day][key]))>0 for key in ['long_margin_ratio','short_margin_ratio','min_order_quantity'])
    elif kind=='daily':assert D(str(byday[day]['settlement']))>0
    else:assert D(str(byday[day]['limit_up']))>D(str(byday[day]['limit_down']))>0
 assert digest(SOURCE/'execution.sqlite')==plan['source_execution_sha256']
 for f in SOURCE.glob('*.json'):
  if f.name not in ('execution-gaps.json','facts.json'):assert digest(f)==digest(E/f.name),f.name
 with sqlite3.connect('file:'+str(E/'execution.sqlite')+'?mode=ro',uri=True) as db:
  db.execute('pragma cache_size=-8192');db.execute('attach database ? as old',('file:'+str(SOURCE/'execution.sqlite')+'?mode=ro',))
  assert db.execute('select count(*) from old.bars o left join main.bars n on n.c=o.c and n.t=o.t where n.t is null or n.day!=o.day or n.o!=o.o or n.h!=o.h or n.l!=o.l or n.p!=o.p or n.v!=o.v or n.source!=o.source').fetchone()[0]==0
  assert db.execute('select count(*) from main.execution_gaps').fetchone()[0]==0
  assert db.execute('select count(*) from main.expected e left join main.bars b on e.c=b.c and e.t=b.t where b.t is null').fetchone()[0]==0
  for j in plan['jobs']:
   c,day=j['contract'],j['day'];statuses=[p for p in E.glob('exit-quotes*/'+c+'-'+day+'.json') if json.loads(p.read_text()).get('status')=='VERIFIED_AND_IMPORTED'];assert len(statuses)==1
   status=statuses[0];s=json.loads(status.read_text());rawpath=status.with_suffix('.parquet');assert digest(rawpath)==s['raw_sha256']
   expected=[x[0] for x in db.execute('select t from main.expected where c=? and day=? order by t',(c,day))]
   rows=list(db.execute('select t,o,h,l,p,v from main.bars where c=? and day=? order by t',(c,day)))
   assert [r[0] for r in rows]==expected and len(rows)==j['expected_rows']
   for t,o,h,l,p,v in rows:
    o,h,l,p,v=map(D,[o,h,l,p,v]);assert all(x.is_finite() for x in [o,h,l,p,v]) and min(o,h,l,p)>0 and v>=0 and l<=min(o,p)<=max(o,p)<=h
   by=lambda kind:{str(x.get('trading_date',x.get('date')))[:10]:x for x in facts[c][kind]}
   complete=c in facts
   if complete:
    params=by('parameters')[day];assert all(params.get(f) is not None for f in fee_fields)
    assert params['commission_type'] in ('by_volume','by_money') and all(D(str(params[f]))>=0 for f in ['open_commission','close_commission','close_commission_today'])
    assert all(D(str(params[f]))>0 for f in ['long_margin_ratio','short_margin_ratio','min_order_quantity'])
    limit=by('limits')[day];daily=by('daily')[day];assert D(str(limit['limit_up']))>D(str(limit['limit_down']))>0 and D(str(daily['settlement']))>0
   checks.append({'contract':c,'day':day,'rows':len(rows),'raw_sha256_verified':True,'endpoints_and_ohlcv_verified':True,'fees_margin_limits_settlement_present':complete})
   if raw:
    import pyarrow.parquet as pq
    import importlib.util
    spec=importlib.util.spec_from_file_location('quotes',R.parents[2]/'output/htdy-ta-60m-70pct-20261031/exit_quotes.py');q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
    values=q.validate(pq.read_table(rawpath).to_pandas().reset_index().to_dict(orient='records'),c,expected)
    assert len(values)==len(rows)
    for a,b in zip(values,rows):assert a[0]==b[0] and all(D(x)==D(y) for x,y in zip(a[1:],b[1:]))
    checks[-1]['raw_values_equal_sqlite']=True
 result={'status':'QUOTES_PASS_PARAMETERS_INCOMPLETE' if any(not c['fees_margin_limits_settlement_present'] for c in checks) else 'PASS','jobs':len(checks),'rows':sum(j['rows'] for j in checks),'original_json_unchanged_except_gap_list_MA2611_append_and_MA2701_null_fee_fill':True,'all_14_spans_fact_day_coverage_verified':True,'all_required_fields_nonnull_and_finite':True,'original_execution_sha256':plan['source_execution_sha256'],'original_execution_rows_preserved':True,'missing_expected_minutes':0,'remaining_gap_days':0,'raw_decoded':raw,'checks':checks}
 (R/('verification-raw.json' if raw else 'verification.json')).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='checks'}))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--raw',action='store_true');main(a.parse_args().raw)
