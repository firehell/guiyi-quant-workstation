async page=>{
 const events=[];const ids=new WeakMap();let nextId=0;const pending=new Set();const start=Date.now();const owns=r=>r.url().includes('/api/v1/market/newow/strategy-detail');
 const request=r=>{if(owns(r)){pending.add(r);ids.set(r,++nextId);events.push({id:ids.get(r),event:'request',url:r.url(),at:Date.now()-start});}};
 const response=r=>{if(owns(r.request()))events.push({id:ids.get(r.request()),event:'response',url:r.url(),http:r.status(),at:Date.now()-start});};
 const finished=r=>{pending.delete(r);if(owns(r))events.push({id:ids.get(r),event:'finished',url:r.url(),at:Date.now()-start});};
 const failed=r=>{pending.delete(r);if(owns(r))events.push({id:ids.get(r),event:'failed',url:r.url(),error:r.failure()?.errorText,at:Date.now()-start});};
 page.on('request',request);page.on('response',response);page.on('requestfinished',finished);page.on('requestfailed',failed);
const xhrRequests=[];let xhrSerial=0;let xhrWatermark=null;let xhrReady=false;let xhrDeadline=Date.now()+110000;
 const xhrOwn=url=>{try{const [path,query='']=url.split('?',2);if(![CONFIG.api_origin,CONFIG.web_origin].some(origin=>path===origin+'/api/v1/market/newow/strategy-detail'))return false;const products=query.split('&').map(part=>part.split('=',2)).filter(([key])=>decodeURIComponent(key)==='product').map(([,value=''])=>decodeURIComponent(value.replace(/\+/g,' ')));return products.length===1&&products[0]===CONFIG.product;}catch{return false}};
 const xhrOnRequest=r=>{if(xhrReady&&xhrOwn(r.url()))xhrRequests.push({request:r,id:++xhrSerial,url:r.url(),method:r.method(),done:false})};
 const xhrOnFinished=r=>{const item=xhrRequests.find(x=>x.request===r);if(item)item.done=true};
 page.on('request',xhrOnRequest);page.on('requestfinished',xhrOnFinished);page.on('requestfailed',xhrOnFinished);
 const installXHR=async()=>{xhrReady=false;await page.addInitScript(XHR_INIT,CONFIG);await page.evaluate(XHR_INIT,CONFIG);xhrWatermark=await page.evaluate(()=>{const s=globalThis.__p7XHR;s.records=[];return {document_id:s.document_id,sequence:s.sequence}});xhrReady=true;};
 const readXHR=async r=>{
  const item=xhrRequests.find(x=>x.request===r.request());if(!item||item.method!=='GET')throw new Error('XHR_REQUEST_IDENTITY_MISSING');

  while(Date.now()<xhrDeadline){
   const peers=xhrRequests.filter(x=>x.url===item.url);
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
 try{
  const web=await page.request.get(CONFIG.web_origin+'/api/preview/identity',{timeout:10000});const api=await page.request.get(CONFIG.api_origin+'/api/preview/identity',{timeout:10000});const identities={web:await web.json(),api:await api.json(),webHttp:web.status(),apiHttp:api.status()};
  for(const [v,expected] of [[identities.web,WEB_CODE],[identities.api,CODE]])if(v.code_sha!==expected||v.as_of?.replace('Z','+00:00')!==ASOF||v.mode!=='local_candidate_readonly'||v.realtime!==false)throw Error('CANDIDATE_IDENTITY_REJECTED');
  if(web.status()!==200||api.status()!==200||identities.web.candidate_origin!==CONFIG.api_origin)throw Error('CANDIDATE_ORIGIN_REJECTED');
  await installXHR();
  const targetWait=page.waitForRequest(r=>owns(r)&&r.url().includes('product='+CONFIG.product+'&')&&r.url().includes('frequency=5m&')&&r.url().includes('section=reference'),{timeout:60000}).catch(()=>null);
  await page.goto(CONFIG.target_url);const target=await targetWait;const pendingAtSwitch=target!==null&&pending.has(target);
  if(!pendingAtSwitch)return {identity:identities,identity_valid:true,identities,pendingAtSwitch,status:'NOT_RUN',reason:'NO_ACTUAL_PENDING_REFERENCE',events};
  await page.getByRole('button',{name:'60m',exact:true}).click({timeout:1000});
  await page.waitForFunction(()=>{const body=document.body.innerText;return new URL(location.href).searchParams.get('frequency')==='60m'&&document.querySelector('.newow-reference__card')&&document.querySelector('.newow-reference__curve polyline')&&!body.includes('正在读取')},null,{timeout:110000});
  const recovery=await page.evaluate(()=>({url:location.href,cards:document.querySelectorAll('.newow-reference__card').length,curves:document.querySelectorAll('.newow-reference__curve polyline').length,statuses:[...document.querySelectorAll('[role=status]')].map(e=>e.textContent)}));
  // An actual bounded read aborted client-side; no mocked response or injected failure.
  const timeout=await page.evaluate(async url=>{const controller=new AbortController();let timer=null;const began=performance.now();try{timer=setTimeout(()=>controller.abort(),250);const r=await fetch(url,{signal:controller.signal});const body=await r.json();return {outcome:r.status===200?'COMPLETED_BEFORE_DEADLINE':'HTTP_ERROR',http:r.status,meta:body.meta,seconds:(performance.now()-began)/1000};}catch(e){return {outcome:e.name==='AbortError'?'ACTUAL_CLIENT_TIMEOUT':'ERROR',error:e.name,seconds:(performance.now()-began)/1000};}finally{clearTimeout(timer);}},target.url());
  await installXHR();xhrRequests.length=0;xhrDeadline=Date.now()+65000;
  const chartReturn=page.waitForResponse(r=>owns(r.request())&&r.url().includes('product='+CONFIG.product+'&')&&r.url().includes('frequency=5m&')&&r.url().includes('section=chart'),{timeout:65000});await page.getByRole('button',{name:'5m',exact:true}).click({timeout:1000});const returned=await chartReturn;const returnedBody=await observedJSON(returned);
  await page.waitForFunction(()=>{const b=document.body.innerText;return new URL(location.href).searchParams.get('frequency')==='5m'&&document.querySelector('.newow-reference__card')&&document.querySelector('.newow-reference__curve polyline')&&!b.includes('正在读取')},null,{timeout:110000});
  const final=await page.evaluate(()=>({url:location.href,cards:document.querySelectorAll('.newow-reference__card').length,curves:document.querySelectorAll('.newow-reference__curve polyline').length,statuses:[...document.querySelectorAll('[role=status]')].map(e=>e.textContent)}));
  await page.getByTestId('newow-product-chart-stage').scrollIntoViewIfNeeded({timeout:1000});await page.screenshot({path:SHOT});

  const snapshotCalls=[];
  const snapGET=async input=>{const params={...input};const url=await page.evaluate(({origin,params})=>{const u=new URL('/api/v1/market/newow/strategy-detail',origin);for(const [k,v] of Object.entries(params))u.searchParams.set(k,v);return u.href;},{origin:CONFIG.api_origin,params});const response=await page.request.get(url,{timeout:90000,maxRedirects:0});const payload=await response.json();const item={url,params,http:response.status(),payload};snapshotCalls.push(item);return item;};
  const params={product:CONFIG.product,strategy:'trend',frequency:'5m',series_kind:'actual_dominant',section:'chart',as_of:CONFIG.as_of};
  const seed=await snapGET(params);if(seed.http!==200||seed.payload.chart?.status?.status!=='ready'||!seed.payload.meta?.snapshot_token)throw Error('SNAPSHOT_SEED_NOT_READY');
  const old=seed.payload.meta.snapshot_token;params.frequency='15m';params.snapshot_token=old;
  for(const section of ['chart','reference']){params.section=section;const conflict=await snapGET({...params});if(conflict.http!==409||conflict.payload.detail?.code!=='NEWOW_SNAPSHOT_GENERATION_CONFLICT')throw Error('WRONG_FREQUENCY_SNAPSHOT_NOT_REJECTED');}
  delete params.snapshot_token;params.section='chart';const freshChart=await snapGET({...params});if(freshChart.http!==200||freshChart.payload.chart?.status?.status!=='ready'||!freshChart.payload.meta?.snapshot_token)throw Error('FRESH_RECOVERY_CHART_NOT_READY');
  params.snapshot_token=freshChart.payload.meta.snapshot_token;params.section='reference';const freshReference=await snapGET({...params});if(freshReference.http!==200||freshReference.payload.reference?.status?.status!=='ready'||freshReference.payload.meta?.snapshot_token!==params.snapshot_token)throw Error('FRESH_RECOVERY_REFERENCE_NOT_READY');
  const snapshot_recovery={status:'OBSERVED_NEEDS_REVIEW',old_snapshot_token:old,http_calls:snapshotCalls};
  return {snapshot_recovery,identity:identities,identity_valid:true,identities,pendingAtSwitch,targetId:ids.get(target),targetUrl:target.url(),recovery,timeout,returnedChart:{xhr_binding:xhrBindings.get(returned.request()),http:returned.status(),meta:returnedBody.meta,chart:returnedBody.chart},final,events,seconds:(Date.now()-start)/1000,status:'OBSERVED_NEEDS_REVIEW'};
 }catch(e){return {status:'BLOCKED',reason:e?.message&&/^[A-Z_]+$/.test(e.message)?e.message:'CANCEL_CAPTURE_FAILED',events};}
 finally{cleanupXHR();page.off('request',request);page.off('response',response);page.off('requestfinished',finished);page.off('requestfailed',failed);}
}
