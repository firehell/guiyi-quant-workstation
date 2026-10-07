async page=>{
    let full_capture=null,earlier_capture=null;
    let phase="seed";let seedIdentity={product:CONFIG.product,frequency:"60m"};const requestPhases=new WeakMap();const requestIds=new WeakMap();const requestRows=new WeakMap();let requestSerial=0;const inFlight=new Set();const navigationInFlight=new Set();let navigationBodyReads=0;const requestEvidence=[];const onRequest=r=>{if(!xhrReady)return;requestPhases.set(r,phase);if(r.url().includes("/newow/strategy-detail")){const entry={id:++requestSerial,url:r.url(),phase,method:r.method()};requestIds.set(r,entry.id);requestRows.set(r,entry);requestEvidence.push(entry);navigationInFlight.add(r);if(isObservedRequest(r.url()))inFlight.add(r)}};const onFinished=r=>{inFlight.delete(r);navigationInFlight.delete(r);const entry=requestRows.get(r);if(entry)entry.finished=true};page.on("request",onRequest);page.on("requestfinished",onFinished);const pageErrors=[]; const failures=[]; const onError=e=>pageErrors.push(e?.name??'PAGE_ERROR');const onFailed=r=>{if(!requestPhases.has(r))return;inFlight.delete(r);navigationInFlight.delete(r);const entry=requestRows.get(r);if(entry){entry.failed=true;entry.error=r.failure()?.errorText};if(r.url().includes("/newow/strategy-detail"))failures.push({url:r.url(),error:r.failure()?.errorText,phase,request_phase:requestPhases.get(r)??"unknown"})};page.on("pageerror",onError);page.on("requestfailed",onFailed);const safeBodyError=e=>{const names=["Error","SyntaxError","TypeError","TimeoutError","ProtocolError"];const known=["Request content was evicted from inspector cache","No resource with given identifier found","No data found for resource with given identifier","Response body is unavailable for redirect responses","Target page, context or browser has been closed","Target closed","Unexpected end of JSON input","Response has been disposed","Failed to load response data","XHR_REQUEST_IDENTITY_MISSING","XHR_OBSERVER_MISSING","XHR_REQUEST_BINDING_AMBIGUOUS","XHR_CONTENT_TYPE_REJECTED","XHR_RESPONSE_TYPE_REJECTED","XHR_BODY_PARSE_OR_COMPACT_FAILED","XHR_OBSERVER_FAILED","XHR_NO_LOAD_EVENT","XHR_RESPONSE_IDENTITY_MISMATCH","XHR_COMPACT_OBSERVATION_MISSING"];const message=known.find(x=>String(e?.message??"").includes(x))??"BODY_READ_MESSAGE_REDACTED";return {name:names.includes(e?.name)?e.name:"Error",message:message.slice(0,160)}};
const phaseRemaining=deadline=>{const remaining=deadline-Date.now();if(remaining<=0)throw new Error('PHASE_ACTION_DEADLINE');return remaining};
let lastSettle=null;
// Parse only query parameters of the task's observed API URLs; no Node URL global.
const apiParams=url=>{
 const text=(url.split('?',2)[1]??'').split('#',1)[0];
 const pairs=text.split('&').filter(Boolean).map(part=>{const i=part.indexOf('=');const decode=s=>decodeURIComponent(s.replace(/\+/g,' '));return [decode(i<0?part:part.slice(0,i)),decode(i<0?'':part.slice(i+1))]});
 const values=Object.fromEntries(pairs);return {get:key=>values[key]??null};
};
const isTargetRequest=(url,frequency=FREQUENCY)=>{if(!url.includes('/newow/strategy-detail'))return false;const q=apiParams(url);return q.get('product')===PRODUCT&&q.get('frequency')===frequency&&(MODE==='dual'?['trend','oscillation']:[MODE==='oscillation'?'oscillation':'trend']).includes(q.get('strategy'))};
const isObservedRequest=url=>{if(isTargetRequest(url)||isTargetRequest(url,FREQUENCY==='60m'?'30m':'60m'))return true;if(!url.includes('/newow/strategy-detail'))return false;const q=apiParams(url);return q.get('product')===PRODUCT&&['1d','1w'].includes(q.get('frequency'))&&q.get('section')==='explanation'};
const selectSupplementalPartner=({mode,frequency,after,config,responses,requests,inFlight,pendingReads,identityValid,bodyErrors=[]})=>{
 if(mode!=='dual'||!identityValid||inFlight!==0||pendingReads!==0||bodyErrors.length)return null;
 const charts=new Map(),missing=[];
 const same=(url,strategy,section)=>{const q=apiParams(url);return q.get('product')===config.product&&q.get('frequency')===frequency&&q.get('strategy')===strategy&&q.get('section')===section&&q.get('as_of')?.replace('Z','+00:00')===config.as_of;};
 for(const strategy of ['trend','oscillation']){
  const candidates=responses.filter(r=>r.row_request&&r.request_id>after&&same(r.url,strategy,'chart'));
  if(!candidates.length)return null;
  const chart=candidates.at(-1),m=chart.payload?.meta,c=chart.payload?.chart;
  if(chart.http!==200||!chart.xhr_binding||chart.xhr_binding.url!==chart.url||chart.xhr_binding.http!==200||chart.xhr_binding.evidence_kind!=='xhr_response_text_compact'||m?.identity?.product!==config.product||m?.identity?.frequency!==frequency||m?.identity?.strategy!==strategy||m?.as_of?.replace('Z','+00:00')!==config.as_of||!m.snapshot_token||!m.input_content_sha256||c?.delivery!=='delivered'||c?.status?.status!=='ready'||c.status.evidence_status!=='ACTIVE_CODE_VERIFIED'||!c.value)return null;
  charts.set(strategy,chart);
  // Any existing response, including an error or stale token, precludes automatic supplementation.
  if(!responses.some(r=>r.row_request&&r.request_id>after&&same(r.url,strategy,'reference')))missing.push(strategy);
 }
 if(missing.length!==1)return null;
 const strategy=missing[0],chart=charts.get(strategy),token=chart.payload.meta.snapshot_token;
 const aborted=requests.filter(r=>r.id>after&&r.failed===true&&r.error==='net::ERR_ABORTED'&&r.method==='GET'&&r.phase===chart.request_phase&&same(r.url,strategy,'reference'));
 if(aborted.length!==1)return null;
 const original=aborted[0],url=original.url;
 if(typeof url!=='string'||url.includes('#'))return null;
 const [path,query]=url.split('?');
 if(![config.web_origin,config.api_origin].some(origin=>path===origin+'/api/v1/market/newow/strategy-detail')||!query||url.split('?').length!==2)return null;
 const allowed=['product','strategy','frequency','series_kind','section','as_of','history_limit','snapshot_token'];
 let keys;
 try{keys=query.split('&').map(part=>decodeURIComponent(part.split('=',1)[0]));}catch{return null;}
 if(keys.length!==allowed.length||new Set(keys).size!==keys.length||keys.some(k=>!allowed.includes(k)))return null;
 const q=apiParams(url);
 if(q.get('series_kind')!=='actual_dominant'||q.get('history_limit')!=='200'||q.get('snapshot_token')!==token)return null;
 return {url,strategy,frequency,phase:'initial',request_floor:after,snapshot_token:token,aborted_request:{...original},chart_request_id:chart.request_id,chart_binding:{...chart.xhr_binding}};
};
const runSupplementalPartner=async(candidate,state,actions,send)=>{
 if(!candidate||state.attempted)return false;
 state.attempted=true;
 const action={kind:'supplemental_partner_reference',source:'collector_true_xhr',ui_composable_received:false,...candidate,status:'STARTED'};
 actions.push(action);
 try{action.response_readback=await send(candidate);action.status='RESPONSE_BOUND';return true;}catch{action.status='FAILED';throw Error('SUPPLEMENTAL_PARTNER_REFERENCE_FAILED');}
};
const sendSupplementalXHR=({url,timeout})=>new Promise((resolve,reject)=>{
 const xhr=new XMLHttpRequest();xhr.open('GET',url,true);xhr.timeout=timeout;
 xhr.onload=async()=>{
  if(xhr.status!==200){reject(Error('SUPPLEMENTAL_HTTP_FAILED'));return;}
  try{const text=xhr.responseText,payload=JSON.parse(text);const hash=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))).map(x=>x.toString(16).padStart(2,'0')).join('');resolve({evidence_kind:'same_xhr_full_response_readback',extra_get:false,http:xhr.status,url:xhr.responseURL,response_text_chars:text.length,response_text_sha256:await hash(text),payload_sha256:await hash(JSON.stringify(payload)),response_text:text,payload});}catch{reject(Error('SUPPLEMENTAL_FULL_BODY_FAILED'));}
 };
 xhr.onerror=()=>reject(Error('SUPPLEMENTAL_NETWORK_FAILED'));xhr.onabort=()=>reject(Error('SUPPLEMENTAL_ABORTED'));xhr.ontimeout=()=>reject(Error('SUPPLEMENTAL_TIMEOUT'));xhr.send();
});
const bindSupplementalResponse=({rows,evidence,config,frequency,readback})=>{
 const r=rows[0],m=r?.payload?.meta,part=r?.payload?.reference;
 if(rows.length!==1||r.http!==200||!r.row_request||!r.xhr_binding||r.url!==evidence.url||r.xhr_binding.url!==r.url||r.xhr_binding.http!==200||r.xhr_binding.evidence_kind!=='xhr_response_text_compact'||m?.identity?.product!==config.product||m?.identity?.frequency!==frequency||m?.identity?.strategy!==evidence.strategy||m?.as_of?.replace('Z','+00:00')!==config.as_of||m?.snapshot_token!==evidence.snapshot_token||!m.input_content_sha256||part?.delivery!=='delivered'||part?.status?.status!=='ready'||part.status.evidence_status!=='ACTIVE_CODE_VERIFIED'||!part.value)throw Error('SUPPLEMENTAL_REFERENCE_BINDING_FAILED');
 if(readback.http!==200||readback.url!==evidence.url||readback.response_text_chars!==r.xhr_binding.response_text_chars||JSON.stringify(readback.payload.meta)!==JSON.stringify(m)||JSON.stringify(readback.payload.reference?.status)!==JSON.stringify(part.status))throw Error('SUPPLEMENTAL_FULL_BODY_BINDING_FAILED');
 return {...readback,response_request_id:r.request_id,xhr_binding:{...r.xhr_binding}};
};
// End supplemental partner functions.
const targetTerminal=(after=0,frequency=FREQUENCY)=>{
 const wanted=MODE==='oscillation'?'oscillation':'trend';const strategies=MODE==='dual'?['trend','oscillation']:[wanted];
 const slots=new Map();
 for(const r of responses){
  if(!r.row_request||(r.request_id??1)<=after)continue;
  const q=apiParams(r.url),section=q.get('section'),strategy=q.get('strategy');
  if(q.get('product')!==PRODUCT||q.get('frequency')!==frequency||!strategies.includes(strategy)||!['chart','reference'].includes(section)||q.get('as_of')?.replace('Z','+00:00')!==CONFIG.as_of)continue;
  if(r.http>=400&&r.payload?.detail)return {kind:'blocked',url:r.url,http:r.http,detail:r.payload.detail};
  const meta=r.payload?.meta,part=r.payload?.[section],state=part?.status?.status;
  if(r.http!==200||meta?.identity?.product!==PRODUCT||meta?.identity?.frequency!==frequency||meta?.identity?.strategy!==strategy||meta?.as_of?.replace('Z','+00:00')!==CONFIG.as_of||part?.delivery!=='delivered')continue;
  if(['blocked','unavailable','warming','not_applicable'].includes(state)&&!part.value&&part.status.reason_code)return {kind:'blocked',url:r.url,state,reason:part.status.reason_code};
  if(['ready','warming','not_applicable'].includes(state)&&part.value&&meta.snapshot_token&&meta.input_content_sha256)slots.set(strategy+':'+section,r);
 }
 return strategies.every(s=>slots.has(s+':chart')&&slots.has(s+':reference')&&slots.get(s+':chart').payload.meta.snapshot_token===slots.get(s+':reference').payload.meta.snapshot_token)?{kind:'ready',strategies,snapshots:Object.fromEntries(strategies.map(s=>[s,slots.get(s+':chart').payload.meta.snapshot_token]))}:null;
};const responses=[];const bodyReadErrors=[];const pending=[];const errors=[];let identity=null;let identity_valid=false;
    const own=url=>url.includes('/market/newow/strategy-detail')&&url.includes('product='+PRODUCT+'&')&&url.includes('frequency='+FREQUENCY+'&');
    const listen=r=>{if(requestPhases.has(r.request())&&r.url().includes("/newow/strategy-detail")){navigationBodyReads++;pending.push(observedJSON(r).then(v=>responses.push({row_request:requestPhases.has(r.request()),request_id:requestIds.get(r.request()),request_phase:requestPhases.get(r.request())??"unknown",payload:v,xhr_binding:xhrBindings.get(r.request()),url:r.url(),http:r.status(),meta:v.meta,detail:v.detail,chartStatus:v.chart?.status,referenceStatus:v.reference?.status,bars:v.chart?.value?.bars?.map(b=>({bar_end:b.bar_end,physical_contract:b.physical_contract})),chartNext:v.chart?.value?.next_before,referenceInput:v.reference?.value?.reference_input_sha256,referenceRevision:v.reference?.value?.reference_revision,historyCoverage:v.reference?.value?.history_coverage,referenceWindow:v.reference?.value?{from:v.reference.value.performance_since,through:v.reference.value.performance_through}:null})).catch(e=>{bodyReadErrors.push({request_id:requestIds.get(r.request()),request_phase:requestPhases.get(r.request())??"unknown",http:r.status(),...safeBodyError(e)});errors.push("RESPONSE_BODY_READ_FAILED")}).finally(()=>{navigationBodyReads--}));}};
    page.on('response',listen);const start=Date.now();const actions=[];
const xhrRequests=[];let xhrSerial=0;let xhrWatermark=null;let xhrReady=false;let xhrDeadline=Date.now()+110000;
 const xhrOwn=url=>{try{const [path,query='']=url.split('?',2);if(![CONFIG.api_origin,CONFIG.web_origin].some(origin=>path===origin+'/api/v1/market/newow/strategy-detail'))return false;const products=query.split('&').map(part=>part.split('=',2)).filter(([key])=>decodeURIComponent(key)==='product').map(([,value=''])=>decodeURIComponent(value.replace(/\+/g,' ')));return products.length===1&&products[0]===CONFIG.product;}catch{return false}};
 const xhrOnRequest=r=>{if(xhrReady&&xhrOwn(r.url()))xhrRequests.push({request:r,id:++xhrSerial,url:r.url(),method:r.method(),done:false})};
 const xhrOnFinished=r=>{const item=xhrRequests.find(x=>x.request===r);if(item)item.done=true};
 page.on('request',xhrOnRequest);page.on('requestfinished',xhrOnFinished);page.on('requestfailed',xhrOnFinished);
 const installXHR=async()=>{xhrReady=false;await page.addInitScript(XHR_INIT,CONFIG);await page.evaluate(XHR_INIT,CONFIG);xhrWatermark=await page.evaluate(()=>{const s=globalThis.__p7XHR;s.records=[];return {document_id:s.document_id,sequence:s.sequence}});xhrReady=true;};
 const readXHR=async r=>{
  const item=xhrRequests.find(x=>x.request===r.request());if(!item||item.method!=='GET')throw new Error('XHR_REQUEST_IDENTITY_MISSING');

  while(Date.now()<xhrDeadline){
   // Aborted SPA requests can share a URL with the replacement request but
   // have no XHR response row. Bind only requests that produced a response.
   const peers=xhrRequests.filter(x=>x.url===item.url&&!requestRows.get(x.request)?.failed);
   if(peers.some(x=>!x.done)){await page.waitForTimeout(25);continue;}
   const found=await page.evaluate(({url,watermark})=>{const s=globalThis.__p7XHR;if(!s)return {missing:true};return {rows:s.records.filter(x=>x.url===url&&(s.document_id!==watermark.document_id||x.sequence>watermark.sequence)).sort((a,b)=>a.sequence-b.sequence)}},{url:item.url,watermark:xhrWatermark});
   if(found.missing)throw new Error('XHR_OBSERVER_MISSING');
   if(found.rows.length<peers.length){await page.waitForTimeout(25);continue;}
   if(found.rows.length!==peers.length||found.rows.some((x,i)=>!Number.isInteger(x.started_order)||!Number.isInteger(x.completed_order)||x.started_order>=x.completed_order||(i&&x.started_order<=found.rows[i-1].completed_order)))throw new Error('XHR_REQUEST_BINDING_AMBIGUOUS');
   const row=found.rows[peers.indexOf(item)];if(row.error||row.http!==r.status()||!row.payload)throw new Error(row.error??'XHR_RESPONSE_IDENTITY_MISMATCH');
   return {payload:row.payload,binding:{evidence_kind:row.evidence_kind,xhr_sequence:row.sequence,node_request_id:item.id,url:item.url,http:row.http,started_at:row.started_at,completed_at:row.completed_at,started_order:row.started_order,completed_order:row.completed_order,response_text_chars:row.response_text_chars,observer_parse_ms:row.observer_parse_ms}};
  }
  throw new Error('XHR_COMPACT_OBSERVATION_MISSING');
 };
 const xhrBindings=new WeakMap();
 const observedJSON=async r=>{if(r.status()<200||r.status()>=300)return r.json();const observed=await readXHR(r);xhrBindings.set(r.request(),observed.binding);return observed.payload;};
 const cleanupXHR=()=>{xhrReady=false;page.off('request',xhrOnRequest);page.off('requestfinished',xhrOnFinished);page.off('requestfailed',xhrOnFinished);};
let lastNavigation=null;
const settleNavigation=async(deadline,after=null,expected={})=>{
 let stable=0,last='';
 while(Date.now()<deadline){
  const dom=await page.evaluate(expected=>{const q=new URL(location.href).searchParams;const tab={trend:'趋势策略',oscillation:'震荡策略',dual:'双策略'}[expected.mode];const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0};return {url:location.href,matches:(!expected.product||q.get('symbol')===expected.product)&&(!expected.frequency||q.get('frequency')===expected.frequency)&&(!tab||[...document.querySelectorAll('[role=tab][aria-selected=true]')].some(e=>e.textContent?.trim()===tab)),loading:[...document.querySelectorAll('[role=status],.newow-product-workspace__loading,.newow-reference,.fusion-panel')].filter(visible).map(e=>e.textContent??'').filter(t=>/正在读取|读取中|正在加载|加载中/.test(t)).map(t=>t.slice(0,250))}},expected);
  const dispatched=after===null||requestEvidence.some(r=>{if(r.id<=after||!r.url?.includes('/newow/strategy-detail'))return false;const q=apiParams(r.url);return q.get('product')===expected.product&&q.get('frequency')===expected.frequency&&q.get('section')==='chart'&&(!expected.mode||(expected.mode==='dual'?['trend','oscillation']:[expected.mode]).includes(q.get('strategy')))});
  lastNavigation={request_floor:after,expected,dom,in_flight:navigationInFlight.size,pending_body_reads:navigationBodyReads,dispatched,stability_polls:stable};
  const signature=JSON.stringify([dom,requestEvidence.length]);
  if(dispatched&&dom.matches&&!dom.loading.length&&!navigationInFlight.size&&!navigationBodyReads){stable=signature===last?stable+1:1;last=signature;if(stable>=3)return lastNavigation;}else{stable=0;last='';}
  await page.waitForTimeout(50);
 }
 throw new Error('INITIAL_NAVIGATION_NOT_SETTLED');
};    try{
      const webResponse=await page.request.get(CONFIG.web_origin+'/api/preview/identity',{timeout:10000});const apiResponse=await page.request.get(CONFIG.api_origin+'/api/preview/identity',{timeout:10000});identity={web:await webResponse.json(),api:await apiResponse.json(),webHttp:webResponse.status(),apiHttp:apiResponse.status()};
      for(const [value,expected] of [[identity.web,EXPECTED_WEB_CODE],[identity.api,EXPECTED_CODE]])if(value.code_sha!==expected||value.as_of?.replace('Z','+00:00')!==CONFIG.as_of||value.mode!=='local_candidate_readonly'||value.realtime!==false)throw new Error('FINAL_IDENTITY_GATE_REJECTED');
      if(identity.webHttp!==200||identity.apiHttp!==200||identity.web.candidate_origin!==CONFIG.api_origin)throw new Error('FINAL_IDENTITY_GATE_REJECTED');
      identity_valid=true;const gateDeadline=Date.now()+110000;xhrDeadline=gateDeadline;const initialRemaining=()=>{const remaining=gateDeadline-Date.now();if(remaining<=0)throw new Error("INITIAL_NAVIGATION_DEADLINE");return remaining};await installXHR();
      // One direct visit per combination; all later actions use actual SPA controls.
      const navigationFloor=requestSerial;
      await page.goto(CONFIG.target_url,{timeout:initialRemaining()});
      await settleNavigation(gateDeadline,navigationFloor,{product:PRODUCT,frequency:FREQUENCY,mode:MODE});
      const supplementalState={attempted:false};
      const supplemental=selectSupplementalPartner({mode:MODE,frequency:FREQUENCY,after:navigationFloor,config:CONFIG,responses,requests:requestEvidence,inFlight:navigationInFlight.size,pendingReads:navigationBodyReads,identityValid:identity_valid,bodyErrors:bodyReadErrors});
      await runSupplementalPartner(supplemental,supplementalState,actions,async evidence=>{
       const floor=requestSerial;
       // A real browser XHR: existing Node listeners and XHRObserver bind the response naturally.
       const readback=await page.evaluate(sendSupplementalXHR,{url:evidence.url,timeout:initialRemaining()});
       while(navigationInFlight.size||navigationBodyReads){initialRemaining();await page.waitForTimeout(25);}
       await Promise.all(pending);
       const rows=responses.filter(r=>r.request_id>floor&&r.url===evidence.url);
       return bindSupplementalResponse({rows,evidence,config:CONFIG,frequency:FREQUENCY,readback});
      });
      seedIdentity={product:PRODUCT,frequency:FREQUENCY};
const recordsMatchDOM=(dom,terminal,after=0,frequency=FREQUENCY)=>{
 if(terminal?.kind!=='ready'||!dom.target||dom.busy||dom.explanationBusy||!dom.curves||!Array.isArray(dom.ids)||new Set(dom.ids).size!==dom.ids.length)return false;
 const wanted=MODE==='oscillation'?'oscillation':'trend',chains=new Map();
 for(const r of responses){
  if(!r.row_request||(r.request_id??1)<=after||r.http!==200)continue;
  const q=apiParams(r.url),meta=r.payload?.meta,ref=r.payload?.reference;
  if(!isTargetRequest(r.url,frequency)||q.get('strategy')!==wanted||ref?.delivery!=='delivered'||!['ready','warming'].includes(ref?.status?.status)||meta?.snapshot_token!==terminal.snapshots?.[wanted])continue;
  // The target selects 200 records. An away page may first request its default
  // 50 records and then request 200 for the visible panel. Bind the DOM to the
  // actual same-snapshot response; never accept an arbitrary history limit.
  if(MODE!=='dual'&&(frequency===FREQUENCY?q.get('history_limit')!=='200':![null,'200'].includes(q.get('history_limit'))))continue;
  const value=MODE==='dual'?ref.value?.fusion_comparison:ref.value;if(!Array.isArray(value?.items)||!value.reference_input_sha256)continue;
  const ids=value.items.map(x=>x.reference_trade_id);if(ids.some(x=>typeof x!=='string'||!x)||new Set(ids).size!==ids.length)continue;
  const key=JSON.stringify([meta.snapshot_token,value.reference_input_sha256,value.reference_revision,value.performance_since,value.performance_through]);
  const cursor=q.get(MODE==='dual'?'fusion_before':'history_before');const prior=chains.get(key);
  if(!cursor)chains.set(key,{ids,cursor:value[MODE==='dual'?'next_cursor':'next_before']});
  else if(prior&&prior.cursor===cursor&&!ids.some(x=>prior.ids.includes(x)))chains.set(key,{ids:[...prior.ids,...ids],cursor:value[MODE==='dual'?'next_cursor':'next_before']});
 }
 return [...chains.values()].some(({ids})=>(ids.length>0||frequency!==FREQUENCY)&&ids.length===dom.ids.length&&ids.every((id,i)=>dom.ids[i].endsWith(id)));
};
const settleTarget=async(deadline,after=0,frequency=FREQUENCY)=>{
 let stable=0,last='';
 while(Date.now()<deadline){
  if(inFlight.size){lastSettle={frequency,request_floor:after,waiting:'request_terminal',in_flight:inFlight.size,previous_dom:lastSettle?.frequency===frequency?lastSettle.dom??lastSettle.previous_dom:null};stable=0;await page.waitForTimeout(50);continue;}
  await Promise.all(pending);const terminal=targetTerminal(after,frequency);
  if(terminal?.kind==='blocked')throw new Error('TARGET_BECAME_BLOCKED');
  const dom=await page.evaluate(({product,frequency,mode})=>{const q=new URL(location.href).searchParams;const tab={trend:'趋势策略',oscillation:'震荡策略',dual:'双策略'}[mode];return {target:q.get('symbol')===product&&q.get('frequency')===frequency&&[...document.querySelectorAll('[role=tab][aria-selected=true]')].some(e=>e.textContent?.trim()===tab),ids:[...document.querySelectorAll('.newow-reference__cards > .newow-reference__card')].map(e=>e.id),waiting:{count:document.querySelectorAll('[data-testid="newow-reference-waiting"]').length,texts:[...document.querySelectorAll('[data-testid="newow-reference-waiting"]')].map(e=>e.textContent??'')},curves:document.querySelectorAll('.newow-reference__curve polyline').length,explanationBusy:[...document.querySelectorAll('[role=status]')].some(e=>/正在读取|读取中/.test(e.textContent??'')&&/日周策略|日线.*周线|同一快照/.test(e.textContent??'')),busy:[...document.querySelectorAll('.newow-reference,.fusion-panel')].some(e=>/正在读取|读取中/.test(e.textContent??''))}},{product:PRODUCT,frequency,mode:MODE});
  const targetRecords=frequency===FREQUENCY;
  const displayMatch=recordsMatchDOM(dom,terminal,after,frequency);
  lastSettle={frequency,request_floor:after,terminal,dom,in_flight:inFlight.size,response_count:responses.length,request_count:requestEvidence.length,records_match:targetRecords&&displayMatch,away_display_match:!targetRecords&&displayMatch,stability_polls:stable};
  const signature=JSON.stringify([dom.ids,terminal?.snapshots,requestEvidence.length]);
  if(!inFlight.size&&terminal?.kind==='ready'&&displayMatch){stable=signature===last?stable+1:1;last=signature;if(stable>=3)return {terminal,dom};}else stable=0;
  await page.waitForTimeout(50);
 }
 throw new Error('TARGET_REQUESTS_OR_RECORD_DOM_NOT_SETTLED');
};const captureBlocked=async()=>{
 const remaining=Math.min(5000,Math.max(1,gateDeadline-Date.now()));
 const matched=await page.waitForFunction(({product,frequency,mode})=>{
  const q=new URL(location.href).searchParams;const tab={trend:'趋势策略',oscillation:'震荡策略',dual:'双策略'}[mode];
  const selected=[...document.querySelectorAll('[role=tab][aria-selected=true]')].some(e=>e.textContent?.trim()===tab);
  const states=[...document.querySelectorAll('.newow-product-workspace__unavailable-chart,[role=status]')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0});
  return q.get('symbol')===product&&q.get('frequency')===frequency&&selected&&states.some(e=>/不可用|缺失|不足|预热|失败/.test(e.textContent??''));
 },{product:PRODUCT,frequency:FREQUENCY,mode:MODE},{timeout:remaining}).then(()=>true).catch(()=>false);
 const blockedDOM=await page.evaluate(()=>({url:location.href,body:document.body.innerText,selectedTabs:[...document.querySelectorAll('[role=tab][aria-selected=true]')].map(e=>e.textContent),statuses:[...document.querySelectorAll('.newow-product-workspace__unavailable-chart,[role=status]')].map(e=>e.textContent)}));
 blockedDOM.matches_target_terminal=matched;
 if(!matched)errors.push('TARGET_BLOCKED_DOM_NOT_OBSERVED');
 await page.screenshot({path:SHOTMAIN}).catch(()=>errors.push('TARGET_BLOCKED_SCREENSHOT_FAILED'));
 return blockedDOM;
};      phase='target';
      await page.evaluate(()=>Promise.resolve());
      const wanted=MODE==='oscillation'?'oscillation':'trend';
      // Initial controls have settled. If this row has no wanted chart request, obtain fresh evidence via a settled SPA round trip.
      if(!requestEvidence.some(r=>{const q=apiParams(r.url);return q.get('product')===PRODUCT&&q.get('frequency')===FREQUENCY&&q.get('strategy')===wanted&&q.get('section')==='chart'})){
       const bootstrapAway=FREQUENCY==='60m'?'30m':'60m';const bootstrapDeadline=Math.min(gateDeadline,Date.now()+65000);xhrDeadline=bootstrapDeadline;const bootstrapFloor=requestSerial;phase='away';
       await page.getByRole('button',{name:bootstrapAway,exact:true}).click({timeout:phaseRemaining(bootstrapDeadline)});
       await settleTarget(bootstrapDeadline,bootstrapFloor,bootstrapAway);
       xhrDeadline=gateDeadline;phase='return';await page.getByRole('button',{name:FREQUENCY,exact:true}).click({timeout:phaseRemaining(gateDeadline)});actions.push('initial_spa_away_and_return');phase='target';
      }
      const waitTargetTerminal=async()=>{while(Date.now()<gateDeadline){const terminal=targetTerminal();if(terminal)return terminal;await page.waitForTimeout(50)}throw new Error('ROW_TARGET_TERMINAL_TIMEOUT')};
      const initialTerminal=await waitTargetTerminal();
      if(initialTerminal.kind==='blocked'){const blockedDOM=await captureBlocked();return {identity,identity_valid,actions,initialTerminal,blockedDOM,responses,errors,pageErrors,failures,seedIdentity,requestEvidence,bodyReadErrors,lastSettle,lastNavigation,seconds:(Date.now()-start)/1000};}
      await settleTarget(gateDeadline);
      const read=async()=>({waiting:{count:await page.locator('[data-testid="newow-reference-waiting"]').count(),texts:await page.locator('[data-testid="newow-reference-waiting"]').allTextContents()},fusionCards:await page.locator('.fusion-panel .newow-reference__card').count(),fusionCurves:await page.locator('.fusion-panel .newow-reference__curve polyline').count(),url:page.url(),selectedTabs:await page.getByRole('tab',{selected:true}).allTextContents(),chartVisible:await page.getByTestId('newow-product-chart-stage').isVisible().catch(()=>false),cards:await page.locator('.newow-reference__cards > .newow-reference__card').count(),curveCount:await page.locator('.newow-reference__curve polyline').count(),cupControlCount:await page.getByRole('button',{name:'杯柄说明',exact:true}).count(),summary:await page.locator('.newow-reference__summary').innerText({timeout:1000}).catch(()=>null),statuses:await page.getByRole('status').allTextContents(),text:(await page.locator('body').innerText()).slice(-4500)});
      const initial=await read();const auxiliary=[];
      // Select the full statistics control; near-year remains the records window.
      const fullScope=MODE==='dual'?page.locator('.fusion-panel'):page.locator('.newow-reference').first();
      const all=fullScope.getByRole('button',{name:'全部',exact:true});
      const fullDeadline=Date.now()+65000;xhrDeadline=fullDeadline;let fullSelected=false;if(await all.count()&&!(await all.isDisabled())){await all.click({timeout:phaseRemaining(fullDeadline)});}
      await settleTarget(fullDeadline);fullSelected=await all.count()>0&&await all.getAttribute('aria-pressed')==='true';
      const closedMode=fullScope.getByRole('button',{name:'已完成累计',exact:true});await closedMode.click({timeout:phaseRemaining(fullDeadline)});await settleTarget(fullDeadline);
      await page.locator('.newow-reference__curve').first().scrollIntoViewIfNeeded({timeout:1000}).catch(()=>{});await page.screenshot({path:SHOTCURVE});
      const beforePaging=await read();
      const curvesBefore=await page.locator('.newow-reference__curve polyline').evaluateAll(es=>es.map(e=>e.getAttribute('points')));
      const idsBefore=await page.locator('.newow-reference__cards > .newow-reference__card').evaluateAll(es=>es.map(e=>e.id));
      const captureFull=async()=>{
       await Promise.all(pending);
       const wanted=MODE==='oscillation'?'oscillation':'trend';
       const target=responses.filter(r=>r.http===200&&r.payload?.meta?.identity?.product===PRODUCT&&r.payload.meta.identity.frequency===FREQUENCY&&r.payload.meta.identity.strategy===wanted);
       const reference=target.filter(r=>r.payload.reference?.status?.status==='ready'&&r.payload.reference.value?.performance_since===CONFIG.since&&r.payload.reference.value?.performance_through===CONFIG.through&&(MODE!=='dual'||r.payload.reference.value?.fusion_comparison)).at(-1);
       const chart=target.filter(r=>r.payload.chart?.status?.status==='ready'&&!apiParams(r.url).get('chart_before')&&!apiParams(r.url).get('chart_older_window')).at(-1);
       const records=target.filter(r=>r.payload.reference?.status?.status==='ready'&&!apiParams(r.url).get('history_before')&&!apiParams(r.url).get('fusion_before')&&(MODE==='dual'?r.payload.reference.value?.fusion_comparison:apiParams(r.url).get('history_limit')==='200')).at(-1);
       if(!reference||!chart||!records||reference.payload.meta.snapshot_token!==chart.payload.meta.snapshot_token||!reference.xhr_binding||!chart.xhr_binding||!records.xhr_binding)throw Error('FRESH_CHART_REFERENCE_IDENTITY_MISMATCH');
       const dom=await fullScope.evaluate(e=>{const q=new URL(location.href).searchParams;return {url:location.href,product:q.get('symbol'),frequency:q.get('frequency'),mode:[...document.querySelectorAll('[role=tab][aria-selected=true]')].map(x=>x.textContent.trim()),ids:[...e.querySelectorAll('.newow-reference__cards > .newow-reference__card')].map(x=>x.id),curves:[...e.querySelectorAll('.newow-reference__curve polyline')].map(x=>({points:x.getAttribute('points'),rect:{width:x.getBoundingClientRect().width,height:x.getBoundingClientRect().height}})),busy:e.getAttribute('aria-busy')==='true'||[...e.querySelectorAll('[role=status]')].some(x=>/正在读取|读取中/.test(x.textContent)),all:[...e.querySelectorAll('button')].find(x=>x.textContent.trim()==='全部')?.getAttribute('aria-pressed')==='true',closed:[...e.querySelectorAll('button')].find(x=>x.textContent.trim()==='已完成累计')?.getAttribute('aria-pressed')==='true'}});
       const frozenGET=async observed=>{
        const transport=await page.evaluate(({url,config})=>{const u=new URL(url);if(![config.web_origin,config.api_origin].includes(u.origin)||u.pathname!=='/api/v1/market/newow/strategy-detail'||u.searchParams.getAll('product').join(',')!==config.product||u.searchParams.getAll('section').join(',')!=='reference'||u.searchParams.getAll('frequency').join(',')!==config.frequency||u.searchParams.getAll('strategy').join(',')!==(config.mode==='oscillation'?'oscillation':'trend')||u.searchParams.getAll('as_of').join(',').replace('Z','+00:00')!==config.as_of||u.hash||u.username||u.password)throw Error('GET_OUTSIDE_ALLOWLIST');const api=new URL(config.api_origin);u.protocol=api.protocol;u.host=api.host;return u.href;},{url:observed.url,config:CONFIG});
        const response=await page.request.get(transport,{timeout:90000,maxRedirects:0});if(response.status()!==200)throw Error('FRESH_FROZEN_GET_NOT_200');
        return {observed_url:observed.url,transport_url:transport,http:response.status(),payload:await response.json()};
       };
       const fullReadback=await frozenGET(reference);const recordsReadback=records.url===reference.url?fullReadback:await frozenGET(records);
       const after=await fullScope.evaluate(e=>({ids:[...e.querySelectorAll('.newow-reference__cards > .newow-reference__card')].map(x=>x.id),curves:[...e.querySelectorAll('.newow-reference__curve polyline')].map(x=>x.getAttribute('points'))}));
       if(JSON.stringify(after.ids)!==JSON.stringify(dom.ids)||JSON.stringify(after.curves)!==JSON.stringify(dom.curves.map(x=>x.points)))throw Error('FRESH_GET_CHANGED_DOM');
       return {identity:identity.api,webIdentity:identity.web,frequency:FREQUENCY,mode:MODE,dom,chart,reference,records,fullReadback,recordsReadback,after,errors:[],status:'OBSERVED_NEEDS_VISUAL_REVIEW'};
      };
      full_capture=await captureFull();await page.getByTestId('newow-product-chart-stage').scrollIntoViewIfNeeded({timeout:1000});await page.screenshot({path:SHOTMAIN});
      if(initial.chartVisible&&initial.cards&&initial.curveCount){for(const [name,component] of [['MACD','macd'],['照妖镜','zhaoyao_mirror'],['涨跌动能','up_down_energy'],['主力控盘','main_force_control'],['趋势转折','trend_reversal']]){const b=page.getByRole('button',{name,exact:true});if(await b.count()){const auxDeadline=Date.now()+60000;xhrDeadline=auxDeadline;if(await b.getAttribute('aria-pressed')==='true')await b.click({timeout:phaseRemaining(auxDeadline)});if(await b.getAttribute('aria-pressed')!=='true'){const done=page.waitForResponse(r=>own(r.url())&&r.url().includes('component='+component),{timeout:phaseRemaining(auxDeadline)}).catch(()=>null);await b.click({timeout:phaseRemaining(auxDeadline)});await done;}await settleTarget(auxDeadline);auxiliary.push({component,pressed:await b.getAttribute('aria-pressed'),text:await page.locator('.newow-product-workspace__auxiliary').innerText({timeout:1000}).catch(()=>null)});}}
       await page.locator('.newow-reference__curve').first().scrollIntoViewIfNeeded({timeout:1000});
      }


      const pageActions=[];const older=page.getByRole('button',{name:'加载更早',exact:true});
      for(const name of [MODE==='dual'?'加载更多近一年记录':'加载更多参考历史','加载更早']){
       const button=page.getByRole('button',{name,exact:true}).first();const count=await button.count();
       const enabled=count>0&&!await button.isDisabled();
       if(enabled){const pageDeadline=Date.now()+65000;xhrDeadline=pageDeadline;const response=page.waitForResponse(r=>own(r.url())&&(name==='加载更早'?(r.url().includes('chart_before=')||r.url().includes('chart_older_window=')):r.url().includes(MODE==='dual'?'fusion_before=':'history_before=')),{timeout:phaseRemaining(pageDeadline)});await button.click({timeout:phaseRemaining(pageDeadline)});const value=await response;await settleTarget(pageDeadline);pageActions.push({name,clicked:true,url:value.url(),http:value.status()});}
       else pageActions.push({name,clicked:false,reason:count?'DISABLED':'ABSENT'});
      }
      await Promise.all(pending);
      const responseCountAfterPaging=responses.length;const idsAfter=await page.locator('.newow-reference__cards > .newow-reference__card').evaluateAll(es=>es.map(e=>e.id));
      const curvesAfter=await page.locator('.newow-reference__curve polyline').evaluateAll(es=>es.map(e=>e.getAttribute('points')));
      const visibleCurves=await page.locator('.newow-reference__curve polyline').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();const p=(e.getAttribute('points')??'').trim().split(/\s+/).map(x=>x.split(',').map(Number));return {width:r.width,height:r.height,pointCount:p.length,finite:p.length>=2&&p.every(x=>x.length===2&&x.every(Number.isFinite))}}));

      const captureEarlier=async()=>{
       const candidates=responses.filter(r=>r.http===200&&r.payload.chart?.status?.status==='ready'&&r.payload.meta?.identity?.product===PRODUCT&&r.payload.meta.identity.frequency===FREQUENCY&&r.payload.meta.identity.strategy===(MODE==='oscillation'?'oscillation':'trend'));
       const initial=candidates.find(r=>!apiParams(r.url).get('chart_before')&&!apiParams(r.url).get('chart_older_window'));if(!initial)throw Error('EARLIER_INITIAL_NOT_READY');
       const token=initial.payload.meta.snapshot_token;
       const pages=candidates.filter(r=>apiParams(r.url).get('chart_before')||apiParams(r.url).get('chart_older_window'));
       const topPriceBefore=await page.locator('.newow-product-chart-stage__reference-prices').innerText();
       for(let index=0;index<4&&!pages.some(r=>apiParams(r.url).get('chart_older_window'));index++){
        const deadline=Date.now()+65000;xhrDeadline=deadline;
        const waiting=page.waitForResponse(r=>isTargetRequest(r.url())&&apiParams(r.url()).get('section')==='chart'&&(apiParams(r.url()).get('chart_before')||apiParams(r.url()).get('chart_older_window')),{timeout:phaseRemaining(deadline)});
        await page.getByRole('button',{name:'加载更早',exact:true}).click({timeout:phaseRemaining(deadline)});
        const response=await waiting;await settleTarget(deadline);const item=responses.find(r=>r.url===response.url()&&r.request_id===requestIds.get(response.request()));
        if(!item||item.http!==200||item.payload.chart?.status?.status!=='ready'||item.payload.meta.snapshot_token!==token||!item.xhr_binding)throw Error('EARLIER_CURSOR_NOT_READY');pages.push(item);
       }
       if(!pages.some(r=>apiParams(r.url).get('chart_older_window')))throw Error('OLDER_WINDOW_NOT_OBSERVED');
       await page.getByTestId('newow-product-chart-stage').evaluate(e=>e.scrollIntoView({block:'start',behavior:'instant'}));
       const box=await page.locator('.newow-product-chart-stage__chart').boundingBox();if(!box)throw Error('EARLIER_CHART_NOT_VISIBLE');
       await page.mouse.move(box.x+box.width/2,box.y+Math.min(200,box.height/3));for(let i=0;i<60;i++){await page.mouse.wheel(0,300);await page.waitForTimeout(50);}await page.waitForTimeout(300);
       const settling=[];let stable=0,last='';const deadline=Date.now()+65000;xhrDeadline=deadline;
       while(Date.now()<deadline){await Promise.all(pending);const d=await page.evaluate(()=>({price:document.querySelector('.newow-product-chart-stage__reference-prices')?.textContent,disabled:document.querySelector('[data-testid=newow-load-earlier]')?.disabled,statuses:[...document.querySelectorAll('[role=status],[role=alert]')].map(e=>e.textContent)}));const ready=!navigationInFlight.size&&!d.disabled&&!d.statuses.some(x=>/正在读取|读取中|正在刷新/.test(x));const signature=JSON.stringify(d);stable=ready?(last===signature?stable+1:1):0;last=signature;settling.push({active:navigationInFlight.size,ready,price:d.price});if(stable>=5)break;await page.waitForTimeout(100)}if(stable<5)throw Error('ZOOM_AUTOPAGING_NOT_SETTLED');
       const visibleActions=await page.locator('.newow-product-chart-stage__action-label').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return {time:e.getAttribute('data-reference-time'),title:e.getAttribute('title'),text:e.textContent,rect:{x:r.x,y:r.y,width:r.width,height:r.height}}}).filter(x=>x.rect.width>0&&x.rect.height>0&&x.rect.x>=0&&x.rect.y>=0&&x.rect.x<innerWidth&&x.rect.y<innerHeight));
       const earlier=pages.find(r=>apiParams(r.url).get('chart_older_window'));const ends=new Set(earlier.payload.chart.value.bars.map(b=>Date.parse(b.bar_end)));
       if(!visibleActions.some(a=>ends.has(Date.parse(a.time??a.title?.match(/\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})/)?.[0]))))throw Error('OLDER_WINDOW_ACTION_NOT_VISIBLE');
       await page.mouse.move(10,10);await page.waitForTimeout(150);await page.screenshot({path:CONFIG.shot_earlier});
       const topPriceAfter=await page.locator('.newow-product-chart-stage__reference-prices').innerText();if(topPriceBefore!==topPriceAfter)throw Error('EARLIER_REFERENCE_PRICE_CHANGED');
       return {identities:{api:identity.api,web:identity.web},initial:initial.payload,pages:pages.map(r=>({url:r.url,http:r.http,payload:r.payload,binding:r.xhr_binding})),errors:[],settling,visibleActions,topPriceBefore,topPriceAfter,final:{url:page.url(),tabs:await page.getByRole('tab',{selected:true}).allTextContents(),chartVisible:await page.getByTestId('newow-product-chart-stage').isVisible()},status:'OBSERVED_NEEDS_VISUAL_REVIEW'};
      };
      earlier_capture=await captureEarlier();
      // A response-triggered return is required even for a row initially already selected.
      const responseCountBeforeReturn=responses.length;const away=FREQUENCY==='60m'?'30m':'60m';
      const awayDeadline=Date.now()+65000;xhrDeadline=awayDeadline;const awayRequestFloor=requestSerial;phase='away';
      await page.getByRole('button',{name:away,exact:true}).click({timeout:phaseRemaining(awayDeadline)});
      await settleTarget(awayDeadline,awayRequestFloor,away);
      const returnDeadline=Date.now()+65000;xhrDeadline=returnDeadline;const returnRequestFloor=requestSerial;const returnResponse=page.waitForResponse(r=>own(r.url())&&r.url().includes('section=chart'),{timeout:phaseRemaining(returnDeadline)});phase='return';await page.getByRole('button',{name:FREQUENCY,exact:true}).click({timeout:phaseRemaining(returnDeadline)});await returnResponse;actions.push('switch_away_and_return');
      await settleTarget(returnDeadline,returnRequestFloor);
      const final=await read();
      return {identity,identity_valid,actions,initial,final,beforePaging,fullSelected,full_capture,earlier_capture,pagingResponses:responses.slice(0,responseCountAfterPaging),responseCountBeforeReturn,returnResponses:responses.slice(responseCountBeforeReturn),pageActions,idsBefore,idsAfter,curvesBefore,curvesAfter,visibleCurves,pageErrors,failures,seedIdentity,requestEvidence,bodyReadErrors,lastSettle,lastNavigation,initialTerminal,auxiliary,responses,errors,seconds:(Date.now()-start)/1000};
    }catch(e){errors.push((e?.message&&/^[A-Z_]+$/.test(e.message)?e.message:'CAPTURE_PHASE_FAILED'));return {identity,identity_valid,actions,full_capture,earlier_capture,responses,errors,pageErrors,failures,seedIdentity,requestEvidence,bodyReadErrors,lastSettle,lastNavigation,seconds:(Date.now()-start)/1000,url:page.url()};}
    finally{cleanupXHR();page.off('response',listen);page.off('pageerror',onError);page.off('requestfailed',onFailed);page.off('request',onRequest);page.off('requestfinished',onFinished);}
   }
