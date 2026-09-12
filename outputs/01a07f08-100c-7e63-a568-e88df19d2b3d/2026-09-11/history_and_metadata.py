import collect as q
from app.models import TradingSession, MainContractMap
from collections import Counter

source=q.json.loads((q.OUT/'source.json').read_text())
conn=q.engine.connect().execution_options(isolation_level='REPEATABLE READ',postgresql_readonly=True)
try:
 with q.Session(bind=conn,autoflush=False) as s:
  op=q.load_operational_products()
  sessions=list(s.scalars(q.select(TradingSession).where(TradingSession.instrument_symbol.in_(op),TradingSession.is_active.is_(True),TradingSession.effective_from<=q.TODAY,q.or_(TradingSession.effective_to.is_(None),TradingSession.effective_to>=q.TODAY))))
  maps=list(s.scalars(q.select(MainContractMap).where(MainContractMap.symbol.in_(op),MainContractMap.trade_date==q.TODAY)))
  metadata={'day':q.TODAY,'operational_count':len(op),'active_session_products':sorted({x.instrument_symbol for x in sessions}),'missing_session_products':sorted(set(op)-{x.instrument_symbol for x in sessions}),'rank1_count':len(maps),'missing_rank1_products':sorted(set(op)-{x.symbol for x in maps})}
  q.save('metadata.json',metadata);print('METADATA',q.json.dumps(metadata,default=q.enc),flush=True)
  md=q.build_market_data_service(s);market={}
  for symbol,contract in sorted({(e['symbol'],e['contract']) for e in source['events']}):
   item={'symbol':symbol,'contract':contract,'bars':[],'expected':[],'errors':[],'current_day_endpoints_unavailable':True,'historical_through':q.TODAY-q.timedelta(days=1)};market[contract]=item
   since=min(q.date.fromisoformat(e['trading_day']) for e in source['events'] if e['contract']==contract)
   try:
    expected=md.expected_contract_replay_endpoints(symbol=symbol,contract=contract,frequency='1m',trading_day=q.TODAY-q.timedelta(days=1),cutoff=q.NOW,since=since)
    item['expected']=expected
    for day in sorted({d for t,d in expected}):
     try:item['bars'].extend(q.asdict(b) for b in md.query_contract_trading_days(q.ContractTradingDayQuery(symbol=symbol,contract=contract,frequency='1m',since=day,through=day)).bars)
     except Exception as exc:item['errors'].append({'part':'historical','day':day,'code':q.safe(exc),'reason':getattr(exc,'reason',None)})
    pairs={(b['bar_end'],b['trading_day']) for b in item['bars']}
    assert len(pairs)==len(item['bars']) and pairs<=set(expected),'BAR_IDENTITY_CONFLICT'
    item['missing_count']=len(set(expected)-pairs)
   except Exception as exc:item['errors'].append({'part':'expected','code':q.safe(exc),'reason':getattr(exc,'reason',None)})
   q.save('market_history.json',market)
  print('HISTORICAL_BARS',sum(len(m['bars']) for m in market.values()))
  print('HISTORICAL_ERRORS',dict(Counter((e['part'],str(e.get('day')),e['code']) for m in market.values() for e in m['errors'])))
finally:conn.close();q.engine.dispose()
