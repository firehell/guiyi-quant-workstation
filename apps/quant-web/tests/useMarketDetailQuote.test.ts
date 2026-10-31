import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref, shallowRef } from 'vue'
import { useMarketDetailQuote, projectMarketDetailQuoteHeader } from '../src/composables/useMarketDetailQuote.ts'
import type { MarketDetailHeaderModel, MarketDetailIdentity } from '../src/types/marketDetail.ts'
import type { MarketBarsPageResponse, MarketHomeLiveItem } from '../src/types/market.ts'
const item = (overrides = {}): MarketHomeLiveItem => ({ symbol:'rb', physicalContract:'RB2701', tradingDay:'2026-10-30', barEnd:'2026-10-30T02:00:00Z', price:105, previousClose:100, priceChange:5, source:'completed_1m', availability:'live', phase:'TRADING', reason:null, ...overrides })
const page = (request): MarketBarsPageResponse => ({ request:{...request,before:request.before??null,contract:request.contract??null},bars:[{bar_end:'2026-10-29T07:00:00Z',trading_day:'2026-10-29',open:95,high:102,low:93,close:100,volume:123,turnover:456,open_interest:789}],canonical_coverage:{start:'2026-10-29',end:'2026-10-29'},page:{has_more_before:false,next_before:null},resolved_contract_segments:[{contract:'RB2701',start_trading_day:'2026-10-01',end_trading_day:'2026-10-30'}]})
function liveFixture() { return { items:shallowRef(new Map([['rb',item()]])),connection:shallowRef<'connected'|'stale'>('connected'),stale:shallowRef(false),observedAt:shallowRef<string|null>(null),start(){},restart(){},dispose(){} } }
const tick = async () => { await nextTick(); await nextTick() }

test('shared quote uses home price and its own baseline, daily facts retain their actual date', async () => {
 const identity=ref<MarketDetailIdentity|null>({view:'newow',symbol:'rb',strategy:'trend',seriesKind:'actual_dominant',frequency:'1w'})
 const live=liveFixture(), requests=[]
 const q=useMarketDetailQuote({identity,live,fetchPage:async request=>{requests.push(request);return page(request)}})
 await tick()
 assert.equal(q.quote.value?.close,105);assert.equal(q.quote.value?.change,5);assert.equal(q.quote.value?.pct,5)
 assert.equal(q.quote.value?.daily?.tradingDay,'2026-10-29');assert.equal(q.quote.value?.tradingDay,'2026-10-30')
 assert.match(q.quote.value!.title,/2026-10-29/)
 identity.value={...identity.value!,view:'subing',frequency:'5m'};await tick()
 live.items.value=new Map([['rb',item({price:106,priceChange:6,barEnd:'2026-10-30T02:01:00Z'})]]);await tick()
 assert.equal(q.quote.value?.close,106);assert.equal(requests.length,1)
 live.items.value=new Map([['rb',item({tradingDay:'2026-11-02',barEnd:'2026-11-02T01:01:00Z'})]]);await tick()
 assert.equal(requests.length,2)
 q.dispose()
})
test('explicit different contract and focused history cannot borrow current dominant price', async () => {
 for (const overrides of [{seriesKind:'contract',contract:'RB2610'},{focusBarEnd:'2026-10-30T01:00:00Z'}]) {
 const identity=ref<any>({view:'free',symbol:'rb',seriesKind:'actual_dominant',frequency:'15m',...overrides})
 const q=useMarketDetailQuote({identity,live:liveFixture(),fetchPage:async request=>page(request)})
 await tick()
 assert.notEqual(q.quote.value?.close,105);assert.equal(q.quote.value?.freshness,'stale')
 q.dispose()
 }
})
test('daily failure leaves live price usable but never fills current day OHLC from chart', async () => {
 const identity=ref<any>({view:'free',symbol:'rb',seriesKind:'actual_dominant',frequency:'15m'})
 const live=liveFixture(),q=useMarketDetailQuote({identity,live,fetchPage:async()=>{throw new Error('unavailable')}})
 await tick();assert.equal(q.quote.value?.close,105);assert.equal(q.quote.value?.daily,null)
 const base={open:999,high:999,low:999,volume:999,openInterest:999,extendedSections:[]} as unknown as MarketDetailHeaderModel
 const header=projectMarketDetailQuoteHeader(base,q.quote.value)
 assert.equal(header.close,105);assert.equal(header.open,null);assert.equal(header.volume,null)
 live.stale.value=true;live.connection.value='stale';await tick();assert.equal(q.quote.value?.freshness,'stale')
 q.dispose()
})
test('late daily responses from another owner cannot overwrite current quote', async () => {
 const identity=ref<any>({view:'free',symbol:'rb',seriesKind:'actual_dominant',frequency:'15m'})
 const pending=[];const q=useMarketDetailQuote({identity,live:liveFixture(),fetchPage:(request,signal)=>new Promise(resolve=>pending.push({request,signal,resolve}))})
 identity.value={...identity.value,symbol:'ag'};await tick()
 pending[0].resolve(page(pending[0].request));await tick()
 assert.equal(pending[0].signal.aborted,true);assert.equal(q.quote.value,null)
 q.dispose()
})
test('missing live falls back to one dated daily snapshot and status stays historical', async () => {
 const live=liveFixture();live.items.value=new Map()
 const q=useMarketDetailQuote({identity:ref<any>({view:'free',symbol:'rb',seriesKind:'actual_dominant',frequency:'5m'}),live,fetchPage:async request=>page(request)})
 await tick();assert.equal(q.quote.value?.close,100);assert.equal(q.quote.value?.freshness,'stale');assert.equal(q.quote.value?.source,'completed_1d');assert.equal(q.quote.value?.daily?.close,100)
 q.dispose()
})

test('D1 response identity, coverage and ambiguous ownership fail closed without hiding valid home price', async () => {
 for (const mutate of [p=>{p.request.symbol='ag'},p=>{p.resolved_contract_segments.push({...p.resolved_contract_segments[0]})},p=>{p.canonical_coverage.end='2026-10-28'},p=>{p.bars[0].high=1},p=>{p.resolved_contract_segments[0].contract='AG2701'}]) {
  const q=useMarketDetailQuote({identity:ref<any>({view:'free',symbol:'rb',seriesKind:'actual_dominant',frequency:'5m'}),live:liveFixture(),fetchPage:async request=>{const p=page(request);mutate(p);return p}})
  await tick();assert.equal(q.state.value,'unavailable');assert.equal(q.quote.value?.close,105);assert.equal(q.quote.value?.daily,null)
  q.dispose()
 }
})

test('quote rejects a home item whose physical contract belongs to another product', async () => {
 const live=liveFixture();live.items.value=new Map([['rb',item({physicalContract:'AG2701'})]])
 const q=useMarketDetailQuote({identity:ref<any>({view:'free',symbol:'rb',seriesKind:'actual_dominant',frequency:'5m'}),live,fetchPage:async()=>{throw new Error('unavailable')}})
 await tick();assert.equal(q.quote.value,null);q.dispose()
})

test('missing independent quote cannot borrow numeric fields or owner from the selected chart', () => {
 for (const frequency of ['15m', '1w'] as const) {
  const base = { symbol:'rb', productName:'螺纹钢', exchange:'SHFE', sector:'黑色', seriesKind:'actual_dominant', frequency,
   displayContract:'RB2610',asOf:'2026-10-30T02:00:00Z',tradingDay:'2026-10-30',open:95,high:110,low:90,close:105,change:5,pct:5,volume:123,turnover:456,openInterest:789,
   phase:'TRADING',displaySource:'selected chart',freshness:'fresh',extendedSections:[] } as MarketDetailHeaderModel
  const header=projectMarketDetailQuoteHeader(base,null)
  for (const field of ['open','high','low','close','change','pct','volume','turnover','openInterest','displayContract','asOf','tradingDay'] as const) assert.equal(header[field],null,`${frequency}:${field}`)
  assert.equal(header.freshness,'unavailable');assert.equal(header.phase,'UNKNOWN');assert.equal(header.displaySource,'详情报价不可用')
  assert.equal(header.symbol,'rb');assert.equal(header.productName,'螺纹钢');assert.equal(header.frequency,'1d')
 }
})

test('fresh independent quote does not inherit selected-chart failure or disclosures', async () => {
 const q=useMarketDetailQuote({identity:ref<any>({view:'free',symbol:'rb',seriesKind:'actual_dominant',frequency:'15m'}),live:liveFixture(),fetchPage:async request=>page(request)})
 await tick()
 const base={afterMarketFailed:true,extendedSections:[{id:'chart',title:'图表快照',summary:'old',updatedAt:null,tone:'warning',rows:[]}]} as unknown as MarketDetailHeaderModel
 const header=projectMarketDetailQuoteHeader(base,q.quote.value)
 assert.equal(header.freshness,'fresh');assert.equal(header.afterMarketFailed,undefined);assert.deepEqual(header.extendedSections,[])
 q.dispose()
})
