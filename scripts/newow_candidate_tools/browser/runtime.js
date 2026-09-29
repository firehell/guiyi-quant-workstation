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
