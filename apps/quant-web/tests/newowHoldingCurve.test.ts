import assert from 'node:assert/strict'
import test from 'node:test'
import { holdingCurvePlot, fusionTheoreticalCurve } from '../src/utils/newowHoldingCurve.ts'
const points = [
  { bar_end:'2026-01-02T07:00:00Z', trading_day:'2026-01-02', physical_contract:'JM2605', segment_id:'a', calculation_segment_id:'a', closed_return_percentage_points:'0', floating_return_pct:'10', marked_return_percentage_points:'10', reference_trade_id:'x', status:'HOLD' },
  { bar_end:'2026-01-03T07:00:00Z', trading_day:'2026-01-03', physical_contract:'JM2605', segment_id:'a', calculation_segment_id:'a', closed_return_percentage_points:'5', floating_return_pct:null, marked_return_percentage_points:'5', reference_trade_id:'x', status:'CLOSED' },
  { bar_end:'2026-01-04T07:00:00Z', trading_day:'2026-01-04', physical_contract:'JM2609', segment_id:'b', calculation_segment_id:'b', closed_return_percentage_points:'5', floating_return_pct:null, marked_return_percentage_points:'5', reference_trade_id:null, status:'FLAT' },
]
test('holding plot keeps every bar, separates owner gaps, and exposes authoritative readouts', () => {
  const curve = {model_version:'newow_reference_marked_curve_v1',page_parity:true,executable:false,points}
  const plot = holdingCurvePlot(curve, '2026-01-01', '2026-01-04')
  assert.equal(plot.message, null)
  assert.equal(plot.points.length, 3)
  assert.equal(plot.segments.length, 2)
  assert.equal(plot.points[0]!.marked_return_percentage_points, '10')
  assert.equal(plot.points[1]!.closed_return_percentage_points, '5')
  assert.equal(holdingCurvePlot({...curve, model_version:'unknown'}, '2026-01-01','2026-01-04').points.length,0)
  assert.equal(holdingCurvePlot({...curve,points:[{...points[0],marked_return_percentage_points:'NaN'}]},'2026-01-01','2026-01-04').points.length,0)
})
test('fusion theory requires a complete one-to-one set and preserves ordinary records', () => {
  const trade = {reference_trade_id:'x', status:'CLOSED',statistics_membership:'entry_in_window_v1',reference_return_pct:'5',exit_bar_end:'2026-01-03T07:00:00Z'}
  const data = {curve:[trade],items:[trade],records_truncated:false,groups:[{model:'fusion',closed_count:1,sum_return_percentage_points:'5'}],theoretical:{model_version:'newow_dual_fusion_hindsight_peak_high_v1',hindsight:true,executable:false,returns:[{reference_trade_id:'x',return_pct:'10',ideal_exit_price:'110'}],sum_return_percentage_points:'10'}}
  const display = fusionTheoreticalCurve(data)
  assert.equal(display.message,null)
  assert.equal(display.points[0]!.trade.reference_return_pct,'10')
  assert.equal(data.items[0]!.reference_return_pct,'5')
  assert.equal(fusionTheoreticalCurve({...data,theoretical:{...data.theoretical,returns:[]}}).points.length,0)
  assert.equal(fusionTheoreticalCurve({...data,theoretical:{...data.theoretical,model_version:'bad'}}).points.length,0)
})

test('fusion local date window rebases completed sums and excludes earlier floating entries', async () => {
  const { holdingCurveWindow } = await import('../src/utils/newowHoldingCurve.ts')
  const curve = {model_version:'newow_reference_marked_curve_v1',page_parity:true,executable:false,points:points.map((p,i)=>({...p,entry_trading_day:i===0?'2025-12-01':null,closed_return_percentage_points:'50',marked_return_percentage_points:i===2?null:'60'}))}
  const next = holdingCurveWindow(curve,[], '2026-01-01','2026-01-04')!
  assert.equal(next.points[0]!.closed_return_percentage_points,'0')
  assert.equal(next.points[0]!.floating_return_pct,'0')
  assert.equal(next.points[2]!.marked_return_percentage_points,null)
  assert.equal(holdingCurvePlot(next,'2026-01-01','2026-01-04').points.length,2)
})

test('same-owner null interruption splits the line before the next valid bar', () => {
  const a = {...points[0]!,bar_end:'2026-01-01T07:00:00Z',trading_day:'2026-01-01'}
  const gap = {...a,bar_end:'2026-01-02T07:00:00Z',trading_day:'2026-01-02',marked_return_percentage_points:null,status:'INTERRUPTED'}
  const b = {...a,bar_end:'2026-01-03T07:00:00Z',trading_day:'2026-01-03'}
  assert.equal(holdingCurvePlot({model_version:'newow_reference_marked_curve_v1',page_parity:true,executable:false,points:[a,gap,b]},'2026-01-01','2026-01-04').segments.length,2)
})
