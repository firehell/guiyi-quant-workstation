import push_review_20260909 as q
from app.alerts.evaluators import HtdyOriginalEvaluator,SubingThs15mEvaluator
from app.market_data.market_read_service import MarketReadWindow,_resolved_contract_for_bar
from datetime import datetime,date,timedelta
from collections import Counter
source=q.json.loads((q.OUT/'source.json').read_text())
results={};conn=q.engine.connect().execution_options(isolation_level='REPEATABLE READ',postgresql_readonly=True);redis=q.get_redis_connection()
try:
 with q.Session(bind=conn,autoflush=False) as s:
  mr=q.build_market_read_service(s,redis=redis);ht=HtdyOriginalEvaluator();su=SubingThs15mEvaluator()
  for e in sorted(source['events'],key=lambda e:e['bar_end']):
   try:
    t=datetime.fromisoformat(e['bar_end']);day=date.fromisoformat(e['trading_day']);identity=q.SeriesPageQuery('actual_dominant',e['symbol'],e['frequency'],limit=32)
    if e['trading_day']==source['today']:
     window=mr.bars_until(identity,trading_day=day,end=t,limit=32)
    elif e['rule_code']=='htdy_original_15m':
     page=mr.history_page(q.SeriesPageQuery('actual_dominant',e['symbol'],e['frequency'],before=t+timedelta(microseconds=1),limit=32))
     owners=tuple(_resolved_contract_for_bar(e['symbol'],b,page.resolved_contract_segments) for b in page.bars)
     window=MarketReadWindow(e['symbol'],'actual_dominant',e['frequency'],day,e['contract'],t,page.bars,owners)
    else:
     results[str(e['id'])]={'status':'前次复算一致，本次未重算'};continue
    assert window.contract==e['contract'],'FORMULA_CONTRACT_MISMATCH'
    evaluator=ht if e['rule_code']=='htdy_original_15m' else su
    candidates=evaluator.evaluate_candidates(mr,window)
    codes=tuple(candidates[-1].observation_types) if candidates else ()
    results[str(e['id'])]={'status':'当前输入复算一致' if codes==tuple(e['result_codes']) else '当前复算不一致','codes':codes,'basis':'Canonical前缀' if e['trading_day']!=source['today'] else '当前同合约前缀'}
   except Exception as exc:results[str(e['id'])]={'status':'公式复算数据不足','code':q.safe(exc)}
   q.save('formula.json',results)
  print(dict(Counter(r['status'] for r in results.values())))
  print([(i,r) for i,r in results.items() if r['status'] not in ('当前输入复算一致','前次复算一致，本次未重算')])
finally:redis.close();conn.close();q.engine.dispose()
