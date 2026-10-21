import assert from 'node:assert/strict'
import test from 'node:test'
import { futuresStrategyLabel, futuresStateLabel, futuresReason, futuresAction, futuresTradeColumns, futuresTableValue, validateFuturesCurve, futuresCurvePoints } from '../src/utils/newowFuturesPresentation.ts'

test('primary strategy state and decision text use familiar Chinese names',()=>{
  assert.equal(futuresStrategyLabel('dual_fusion'),'双策略');assert.equal(futuresStrategyLabel('osc-test'),'测试')
  assert.equal(futuresStateLabel('LONG'),'多头');assert.equal(futuresStateLabel('UNAVAILABLE'),'未知')
  assert.equal(futuresAction('OPEN_SHORT'),'开空');assert.equal(futuresReason('MIN_LOT_BUDGET'),'资金或风险预算不足，无法开出最小一手')
  assert.equal(futuresReason('NEW_UNKNOWN_REASON'),'未识别原因')
})
test('reference and account trade columns preserve separate price and return fields',()=>{
  const reference=futuresTradeColumns('reference-trades'),account=futuresTradeColumns('trades')
  assert.equal(reference.find(c=>c.key==='qty')?.label,'累计参考单位层');assert.equal(account.find(c=>c.key==='qty')?.label,'手数')
  assert.equal(futuresTableValue({qty:3},reference.find(c=>c.key==='qty')!),'3','累计开立层数直接展示后端事实，不扣减或换算账户手数')
  assert.ok(reference.some(c=>c.label==='参考收益（百分点）'));assert.ok(account.some(c=>c.label==='净盈亏（元）'))
  const row={side:'SHORT',entry_reference_price:'1250.125',net_pnl:'15.25',reference_return_pct:'1.25',status:'OPEN'}
  assert.equal(futuresTableValue(row,reference.find(c=>c.key==='entry_reference_price')!),'1250.13')
  assert.equal(futuresTableValue(row,reference.find(c=>c.key==='side')!),'空头')
  assert.equal(futuresTableValue(row,reference.find(c=>c.key==='status')!),'持有中')
})
test('curve accepts complete-window hash-pinned sampled source and rejects mismatches or false completeness',()=>{
  const curve={run_id:'run',sha256:'a'.repeat(64),kind:'equity' as const,total_points:20,sampled:true,status:'COMPLETED' as const,points:[{at:'2026-10-18T15:00:00+08:00',value:'100000'},{at:'2026-10-19T15:00:00+08:00',value:'101000'}]}
  assert.equal(validateFuturesCurve(curve,'run','a'.repeat(64),'equity','2026-10-19T15:00:00+08:00'),curve)
  assert.equal(futuresCurvePoints(curve)[1]?.value,101000)
  for(const change of [{run_id:'other'},{kind:'reference-equity'},{total_points:1},{sampled:false},{points:[{at:'2026-10-20T15:00:00+08:00',value:'100000'}]}])assert.throws(()=>validateFuturesCurve({...curve,...change} as any,'run','a'.repeat(64),'equity','2026-10-19T15:00:00+08:00'))
})

test('publication time without known inputs is not labeled as a market cutoff',async()=>{
  const { futuresAsOfLabel }=await import('../src/utils/newowFuturesPresentation.ts')
  assert.equal(futuresAsOfLabel('publication_time_only'),'生成时间')
  assert.equal(futuresAsOfLabel('verified_completed_input'),'截至')
})

test('explicit frozen curve gaps stay null and split geometry instead of becoming zero',async()=>{
  const {returnCurveLayout}=await import('../src/utils/returnCurveLayout.ts')
  const curve={run_id:'run',sha256:'a'.repeat(64),kind:'equity' as const,total_points:3,sampled:false,status:'COMPLETED' as const,points:[{at:'2026-10-17T15:00:00+08:00',value:'100000'},{at:'2026-10-18T15:00:00+08:00',value:null},{at:'2026-10-19T15:00:00+08:00',value:'101000'}]}
  validateFuturesCurve(curve,'run','a'.repeat(64),'equity','2026-10-19T15:00:00+08:00')
  const points=futuresCurvePoints(curve);assert.equal(points[1]!.value,null)
  assert.equal(returnCurveLayout(points,{headroom:1.05,areaBaseline:'bottom',valueUnit:'currency'}).segments.length,2)
  for(const value of ['',false,0,'NaN','Infinity'])assert.throws(()=>validateFuturesCurve({...curve,points:[{...curve.points[0]!,value}]} as any,'run','a'.repeat(64),'equity','2026-10-19T15:00:00+08:00'))
})
