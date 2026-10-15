import assert from 'node:assert/strict'
import test from 'node:test'
import { referenceReturnLayout, returnCurveLayout } from '../src/utils/returnCurveLayout.ts'
import { holdingCurvePlot } from '../src/utils/newowHoldingCurve.ts'
import { pagePerformanceLayout } from '../src/utils/newowPagePerformance.ts'
const policy = {headroom:1.1,areaBaseline:'zero' as const}
const point = (value:number|null,position=0,segment='one',date='2026-10-15') => ({value,position,segment,date})
test('single day, all zero and all loss plots have finite axes including zero',()=>{
 for(const values of [[0], [0,0,0],[-2,-4,-3]]) {
  const plot=returnCurveLayout(values.map((v,i)=>point(v,i)),policy)
  assert.equal(plot.points.length,values.length)
  assert.ok(plot.low<=0 && plot.high>=0 && plot.high>plot.low)
  assert.ok(plot.points.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)))
  assert.ok(plot.levels.every(p=>Number.isFinite(p.y)))
  if(values.length===1) assert.equal(plot.points[0]!.x,712)
  if(values.every(v=>v<0)) assert.equal(plot.high,0)
 }
})
test('segment changes and null interruptions break lines and filled areas',()=>{
 const plot=returnCurveLayout([point(0,0),point(2,1),point(null,2),point(3,3),point(4,4,'two')],policy)
 assert.equal(plot.segments.length,3)
 assert.equal(plot.areas.length,3)
 assert.deepEqual(plot.points.map(p=>p.value),[0,2,3,4])
 assert.equal(plot.areas[1]!.trim().split(' ').length,3)
 assert.equal(returnCurveLayout([point(Infinity)],policy).points.length,0)
 assert.equal(returnCurveLayout([point(1,NaN)],policy).points.length,0)
})
test('completed trade coordinates use supplied trading day across night-session civil dates',()=>{
 const trades=[{value:2,trade:{physical_contract:'AG2612',segment_id:'a',exit_trading_day:'2026-10-19',exit_bar_end:'2026-10-16T13:05:00Z'}}]
 const plot=referenceReturnLayout(trades,'2026-10-16','2026-10-19')
 assert.equal(plot.points[0]!.x,712)
 assert.equal(plot.points[0]!.trade,trades[0]!.trade)
 assert.equal(plot.ticks.at(-1)!.day,'2026-10-19')
 assert.equal(referenceReturnLayout([{...trades[0]!,trade:{...trades[0]!.trade,exit_trading_day:undefined}}],'2026-10-16','2026-10-19').points.length,0)
})
test('holding coordinates retain bar instants while date labels retain server trading days',()=>{
 const source=['2026-10-16T13:05:00Z','2026-10-18T16:05:00Z'].map(bar_end=>({bar_end,trading_day:'2026-10-19',physical_contract:'AG2612',segment_id:'one',calculation_segment_id:'one',closed_return_percentage_points:'0',floating_return_pct:'0',marked_return_percentage_points:'0',reference_trade_id:null,status:'FLAT'}))
 const plot=holdingCurvePlot({model_version:'newow_reference_marked_curve_v1',page_parity:true,executable:false,points:source},'2026-10-19','2026-10-19')
 assert.equal(plot.points.length,2)
 assert.deepEqual(plot.ticks.map(p=>p.day),['2026-10-19','2026-10-19'])
 assert.deepEqual(plot.points.map(p=>p.x),[0,712])
})
test('page policy retains index spacing, exact extrema, bottom area and trading-day labels',()=>{
 const mode={period:'5m',equity:['-2','-1','0'],dates:['2026-10-16T13:05:00Z','2026-10-18T16:05:00Z','2026-10-19T01:05:00Z'],trading_days:['2026-10-19','2026-10-19','2026-10-19'],segment_ids:['a','a','b'],trades:[],summary:{cumReturn:'0',accuracy:0,maxDrawdown:'2',tradeCount:0}}
 const before=JSON.stringify(mode),plot=pagePerformanceLayout(mode)
 assert.equal(JSON.stringify(mode),before)
 assert.equal(pagePerformanceLayout({...mode,equity:['0'],trading_days:['2026-10-19'],segment_ids:['a']}).points[0]!.x,0)
 assert.deepEqual(plot.points.map(p=>p.x),[0,356,712])
 assert.deepEqual([plot.low,plot.high],[-2,0])
 assert.equal(plot.segments.length,2)
 assert.equal(plot.ticks[0]!.day,'2026-10-19')
 assert.match(plot.areas[1]!,/^712,140 /)
})
