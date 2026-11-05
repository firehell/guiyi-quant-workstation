import {test,expect} from '@playwright/test'
import {readFileSync} from 'node:fs'
import {installNewowProductFixtures,newowRoute,NEWOW_AS_OF} from './newow-product.helpers.mjs'
const referenceHtml=readFileSync(new URL('./fixtures/newow-composite-detail3449.html',import.meta.url),'utf8')
function fixture(strategy='oscillation') {
 const facts=['trend','oscillation'].flatMap(axis=>['week','day','m60'].map((period,i)=>({role:axis+'_'+period,state:period==='m60'?'sell':'hold',age:i,frequency:period==='week'?'1w':period==='day'?'1d':'60m',bar_end:'2026-09-03T07:00:00.000Z',physical_contract:'RB2605',segment_id:'rb:RB2605:2026-01-01T00:00:00+00:00',calculation_segment_id:'rb:RB2605:2026-01-01T00:00:00+00:00',status:'ready',reason:null,source_category:'canonical_strategy_replay',last_signal:{action_id:axis+'-'+period,kind:period==='m60'?'CLEAR':'BUILD',bar_end:'2026-09-02T07:00:00Z',price:String(105+i),calculation_segment_id:'rb:RB2605:2026-01-01T00:00:00+00:00'}})))
 return {cdv2:{formula_version:'newow_composite_decision_cdv2_1_2_0_v1',as_of:NEWOW_AS_OF,executable:false,explanation_only:true,is_probability:false,is_margin_ratio:false,total:78,action:'持有',action_code:'bullish-bullish',resonance:'R3',mismatch:null,mismatch_age:-1,trend_bias:'bullish',oscillation_bias:'bullish',trend_state:{week:'up',day:'up',m60:'down'},oscillation_state:{week:'holding',day:'holding',m60:'cleared'},scores:{trend:30,oscillation:30,resonance:14,direction:12,volatility:-8},deductions:{j_reduce:0,care:0,tent:0},cert_extra:0,certainty_cap:50,resonance_cap:60,reference_exposure_cap:50,reference_exposure_range:'20%–50%',volatility_pct:'9.00',volatility_level:'high',extra_sources:{},missing_roles:[],facts},prices:null}
}
async function setup(page,cd=fixture(),strategy='oscillation') {
 await installNewowProductFixtures(page,{weeklyCandidate:true,transformEnvelope:(raw,{section})=>{if(section==='explanation')raw.explanation.value.decision_v2=structuredClone(cd)}})
 await page.goto(newowRoute(strategy,'1d','&as_of='+encodeURIComponent(NEWOW_AS_OF)))
 const card=page.getByTestId('composite-card-surface')
 await expect(card.locator('.composite-tier-row')).toHaveCount(1)
 if(strategy==='oscillation')await expect(card.locator('.composite-action-word')).not.toBeEmpty()
 return card
}
const pairs=[['.composite-title','.composite-title'],['.composite-action-word','.composite-action-word'],['.composite-header','.composite-header'],['.composite-chain','.composite-chain'],['.composite-basis-switch','.composite-basis-switch'],['.composite-reason','.composite-reason'],['.composite-mismatch-row','.composite-mismatch-row'],['.composite-mm-detail-row','.composite-mm-detail-row'],['.composite-firstaction','.composite-firstaction'],['.composite-tier-row','.composite-tier-row'],['.composite-pos-row','.composite-pos-row'],['.composite-headtag-row','.composite-headtag-row'],['.composite-cert-row','.composite-cert-row'],['.composite-vol-row','.composite-vol-row'],['.composite-dual','.composite-dual'],['.composite-dir-row','.composite-dir-row'],['.composite-resonance-row','.composite-resonance-row'],['.composite-signal-price-row','.composite-signal-price-row'],['.composite-basis','.composite-basis'],['.compliance-row','.compliance-row']]
async function measure(page,selector){return page.locator(selector).evaluate(el=>{const card=el.closest('.composite-action-card'),r=el.getBoundingClientRect(),root=card.getBoundingClientRect(),s=getComputedStyle(el);return {text:el.innerText.replace(/\s+/g,' ').trim(),x:r.x-root.x,y:r.y-root.y,width:r.width,height:r.height,color:s.color,background:s.backgroundColor,fontSize:s.fontSize,fontWeight:s.fontWeight,borderRadius:s.borderRadius}})}
const scenarios=['R1','R2','R3','R4','MM1','MM2','MM3','MM4']
function scenario(code){const input=fixture(),cd=input.cdv2;if(code.startsWith('R'))cd.resonance=code;else{cd.mismatch=code;cd.resonance='R2';cd.mismatch_age=code==='MM1'||code==='MM2'?5:0;cd.reference_exposure_cap=30;cd.reference_exposure_range='10%–30%'}return input}
for(const code of scenarios)for(const theme of ['light','dark'])test(`public same-input card ${code} ${theme}: collapsed, body and evidence`,async({page,context},testInfo)=>{
 const differences=[];const input=scenario(code),card=await setup(page,input)
 await page.evaluate(t=>document.documentElement.dataset.theme=t,theme)
 const box=await card.boundingBox(),reference=await context.newPage()
 await reference.route('http://reference.test/**',r=>r.fulfill({contentType:'text/html',body:referenceHtml}))
 await reference.setViewportSize({width:Math.ceil(box.width),height:1314});await reference.goto('http://reference.test/card')
 await reference.evaluate(({width,theme})=>{document.body.style.width=width+'px';document.documentElement.dataset.theme=theme},{width:box.width,theme})
 for(const stage of ['collapsed','body','evidence']) {
  await reference.evaluate(({cd,stage})=>window.renderReference(cd,'oscillation','week',stage),{cd:input.cdv2,stage})
  if(stage==='body')await card.getByRole('button',{name:'展开综合决策',exact:true}).click()
  if(stage==='evidence')await card.getByRole('button',{name:'展开综合依据',exact:true}).click()
  const comparisons=[]
  for(const [a,b] of pairs) {
   const local=card.locator(a),original=reference.locator('#compositeActionCard').locator(b)
   if(!await local.isVisible()&&!await original.isVisible())continue
   await expect(local,a).toBeVisible();await expect(original,b).toBeVisible()
   const actual=await measure(page,'[data-testid="composite-card-surface"] '+a),expected=await measure(reference,'#compositeActionCard '+b)
   comparisons.push({selector:a,actual,expected})
   if(actual.text.replace(/\s+/g,'')!==expected.text.replace(/\s+/g,''))differences.push({stage,selector:a,key:'text',actual:actual.text,expected:expected.text})
   for(const key of ['color','background','fontSize','fontWeight','borderRadius'])if(actual[key]!==expected[key])differences.push({stage,selector:a,key,actual:actual[key],expected:expected[key]})
   for(const key of ['x','y','width','height'])if(Math.abs(actual[key]-expected[key])>1)differences.push({stage,selector:a,key,actual:actual[key],expected:expected[key]})
  }
  await card.screenshot({path:testInfo.outputPath(`local-${theme}-${stage}.png`)})
  await reference.locator('#compositeActionCard').screenshot({path:testInfo.outputPath(`source-${theme}-${stage}.png`)})
  await testInfo.attach(`metrics-${stage}`,{body:JSON.stringify(comparisons,null,2),contentType:'application/json'})
 }
 expect(differences).toEqual([]);await reference.close()
})
test('basis changes fold both levels, persist, keep signal rows and do not request new facts',async({page})=>{
 const card=await setup(page),requests=[];page.on('request',r=>{if(r.url().includes('decision_v2=true'))requests.push(r.url())})
 await card.getByRole('button',{name:'展开综合决策',exact:true}).click();await card.getByRole('button',{name:'展开综合依据',exact:true}).click()
 await expect(card.locator('.sp-line')).toHaveCount(3)
 await card.getByRole('button',{name:'日线口径',exact:true}).click()
 await expect(card.getByRole('button',{name:'展开综合决策',exact:true})).toHaveAttribute('aria-expanded','false')
 await card.getByRole('button',{name:'展开综合决策',exact:true}).click()
 await expect(card.locator('.cc-key')).toHaveText(['日线','60分','周线'])
 await expect(card.locator('.composite-conflict')).toBeVisible()
 await expect(card.locator('.composite-action-word')).toHaveText('等待');await expect(card.locator('.composite-action-word')).toHaveCSS('color','rgb(142, 142, 147)')
 await expect(card.getByRole('button',{name:'展开综合依据',exact:true})).toHaveAttribute('aria-expanded','false')
 expect(requests).toHaveLength(0)
 await page.reload();await card.getByRole('button',{name:'展开综合决策',exact:true}).click()
 await expect(card.getByRole('button',{name:'日线口径',exact:true})).toHaveAttribute('aria-pressed','true')
 await expect(card.locator('.cc-key')).toHaveText(['日线','60分','周线'])
})

test('main-rise uses the source no-bucket fallback without an extra header action',async({page})=>{
 const card=await setup(page,fixture(),'main_rise')
 await expect(card.locator('.composite-action-word')).toHaveCount(0)
 await card.getByRole('button',{name:'展开综合决策',exact:true}).click()
 await expect(card.locator('.composite-chain')).toHaveCount(0)
 await expect(card.locator('.composite-basis-switch')).toHaveCount(0)
 await expect(card.locator('.composite-decision-card')).toBeVisible()
 await expect(card.locator('.composite-decision-label')).toHaveText('持有')
})

test('R0 with unavailable facts stays explicit and does not invent a merged flat chain or prices',async({page})=>{
 const input=fixture(),cd=input.cdv2;cd.resonance='R0';cd.total=0;cd.scores={trend:0,oscillation:0,resonance:0,direction:0,volatility:0};cd.reference_exposure_cap=0;cd.reference_exposure_range='';cd.volatility_pct=null;cd.volatility_level=null;cd.trend_state={week:'unknown',day:'unknown',m60:'unknown'};cd.oscillation_state={week:'idle',day:'idle',m60:'idle'}
 cd.facts.forEach(f=>Object.assign(f,{status:'unavailable',state:null,age:-1,bar_end:null,last_signal:null}));cd.missing_roles=cd.facts.map(f=>f.role)
 const card=await setup(page,input);await card.getByRole('button',{name:'展开综合决策',exact:true}).click();await card.getByRole('button',{name:'展开综合依据',exact:true}).click()
 await expect(card.locator('.chain-single')).toHaveCount(0);await expect(card.locator('.composite-chain .st')).toHaveText(['状态不可用','状态不可用','状态不可用']);await expect(card.locator('.sp-line')).toHaveCount(0);await expect(card.locator('.composite-head-tag')).toContainText('数据不足 R0')
})
