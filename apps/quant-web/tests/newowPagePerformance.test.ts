import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizePagePerformance, pagePerformancePlot } from '../src/utils/newowPagePerformance.ts'
function payload() {
  const mode = (pct:string,forceClose:boolean) => ({period:'day',drawdown_kind:forceClose?'peak_difference':'maximum_trade_loss',summary:{cumReturn:pct,accuracy:100,maxDrawdown:'0',tradeCount:1},dates:['2026-01-01','2026-01-02','2026-01-03'],trading_days:['2026-01-01','2026-01-02','2026-01-03'],segment_ids:['owner','owner','owner'],equity:['0','1',pct],trades:[{buyDate:'2026-01-01',buyPrice:'100',sellDate:'2026-01-03',sellPrice:String(100+Number(pct)),pct,forceClose,segment_id:'owner'}]})
  return {version:'newow_page_performance_v3379_v2',source_version:'3.3.79',source_sha256:'3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d',page_parity:true,executable:false,strategy:'trend',input_sha256:'a'.repeat(64),source_evidence_sha256:null,segment_count:1,ordinary_interrupted_count:0,ideal_open_count:0,ordinary:mode('2',true),ideal:mode('9',false)}
}
test('strict page projection rejects source identity and curve/trade contradictions',()=>{
  assert.equal(normalizePagePerformance(undefined,'trend'),null)
  const mutations=[(p:ReturnType<typeof payload>)=>{p.source_sha256='f'.repeat(64)},(p:ReturnType<typeof payload>)=>{p.executable=true},(p:ReturnType<typeof payload>)=>{p.ordinary.equity.pop()},(p:ReturnType<typeof payload>)=>{p.ordinary.summary.tradeCount=2},(p:ReturnType<typeof payload>)=>{p.ordinary.trades[0]!.buyPrice='0'}]
  for (const mutate of mutations){const p=payload();mutate(p);assert.throws(()=>normalizePagePerformance(p,'trend'),/page_performance/)}
  assert.throws(()=>normalizePagePerformance({...payload(),strategy:'fusion'},'trend'),/identity/)
  const parsed=normalizePagePerformance(payload(),'trend')!; assert.equal(parsed.ordinary!.trades[0]!.forceClose,true)
  const split={...parsed.ordinary!,segment_ids:['one','two','two']};assert.equal(pagePerformancePlot(split).length,2)
})
test('projection rejects cross-owner chronology, forged trades and invalid terminal while allowing prior-window entry',()=>{
  const bad=[(p:ReturnType<typeof payload>)=>{p.ordinary.segment_ids=['a','b','b'];p.ordinary.dates=['2026-01-03','2026-01-01','2026-01-02']},
    (p:ReturnType<typeof payload>)=>{p.ordinary.trades[0]!.segment_id='missing'},
    (p:ReturnType<typeof payload>)=>{p.ordinary.segment_ids=['a','b','a']},
    (p:ReturnType<typeof payload>)=>{p.segment_count=0},
    (p:ReturnType<typeof payload>)=>{p.ordinary.trades[0]!.sellDate='2026-01-02'},
    (p:ReturnType<typeof payload>)=>{p.ordinary.trades[0]!.buyDate='2026-01-01T12:00:00Z'}]
  for(const mutate of bad){const p=payload();mutate(p);assert.throws(()=>normalizePagePerformance(p,'trend'),/page_performance/)}
  const good=payload();good.ordinary.trades[0]!.buyDate='2025-12-30';assert.ok(normalizePagePerformance(good,'trend'))
})

test('full-history page curve accepts 200000 points and preserves owner breaks', () => {
 const parsed = normalizePagePerformance(payload(), 'trend')!
 const size = 200000
 const full = {...parsed.ordinary!, trading_days: Array.from({length:size}, () => '2026-01-01'), equity: Array.from({length:size}, (_,i) => String(i % 7 - 3)), segment_ids: Array.from({length:size}, (_,i) => i < size / 2 ? 'first' : 'second')}
 const parts = pagePerformancePlot(full)
 assert.equal(parts.length, 2)
 assert.equal(parts.map(part => part.trim().split(' ').length).reduce((a,b) => a+b, 0), size)
 assert.match(parts[0]!, /^0,140 /)
 assert.ok(parts[1]!.includes('712,'))
})
