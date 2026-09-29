config => {
 if (globalThis.__p7XHR?.version === 'candidate_compact_v1') {if(globalThis.__p7XHR.task_key!==config.task_key)throw Error('XHR_TASK_CHANGED');return;}
 const nativeSend=XMLHttpRequest.prototype.send;
 // Document-local observation discriminator only; never a security or market identity.
 const state={task_key:config.task_key,version:'candidate_compact_v1',document_id:Date.now().toString(36)+'-'+Math.random().toString(36).slice(2),sequence:0,event_order:0,records:[]};
 const select=(value,keys)=>Object.fromEntries(keys.filter(k=>Object.prototype.hasOwnProperty.call(value??{},k)).map(k=>[k,value[k]]));
 const barKeys=['bar_end','physical_contract','segment_id','trading_day','open','high','low','close','volume','open_interest','calculation_segment_id','source_identity','completed','observation_eligible'];
 const summaryArray=value=>Array.isArray(value)?{count:value.length,first:value.length?value[0]:null,last:value.length?value[value.length-1]:null}:null;
 const curve=value=>{if(!value||typeof value!=='object')return value;const out={};for(const [k,v] of Object.entries(value))out[k]=Array.isArray(v)?summaryArray(v):v;return out};
 const reference=value=>{
  if(!value||typeof value!=='object')return value;
  const out=select(value,['product','frequency','reference_revision','reference_model_version','fusion_input_sha256','reference_input_sha256','reference_cutoff','source_profiles','source_formula_versions','performance_since','performance_through','actual_available_through','history_coverage','unavailable_days','coverage_intervals','summary','items','next_before','next_cursor','storage_mode','page_parity','executable','auto_order','allowed_uses','record_since','record_through','records_truncated','snapshot_schema']);
  if(Object.hasOwn(value,'curve')){out.curve_summary=summaryArray(value.curve);if(Array.isArray(value.curve)&&(value.curve.length===0||value.performance_since===config.since&&value.performance_through<=config.through))out.curve=value.curve;}
  if(Object.hasOwn(value,'curve_trades')){out.curve_trades_summary=summaryArray(value.curve_trades);if(Array.isArray(value.curve_trades)&&(value.curve_trades.length===0||value.performance_since===config.since&&value.performance_through<=config.through))out.curve_trades=value.curve_trades;}
  if(Object.hasOwn(value,'holding_curve'))out.holding_curve_summary=curve(value.holding_curve);
  if(Object.hasOwn(value,'groups'))out.groups=value.groups.map(g=>{const c=select(g,['model','summary','reference_model_version','curve_status','status','closed_count','open_count','interrupted_count','sum_return_percentage_points']);for(const [k,v] of Object.entries(g))if(Array.isArray(v))c[k+'_summary']=summaryArray(v);return c});
  if(Object.hasOwn(value,'fusion_comparison'))out.fusion_comparison=reference(value.fusion_comparison);
  return out;
 };
 const compact=value=>{
  const out=select(value,['meta','detail']);
  for(const section of ['chart','reference','auxiliary','explanation']){
   const part=value?.[section];if(!part)continue;const p=select(part,['delivery','status']);
   if(Object.hasOwn(part,'value')){
    if(part.value===null)p.value=null;
    else if(section==='chart'){p.value=select(part.value,['chart_from','chart_through','next_before']);if(Array.isArray(part.value.bars))p.value.bars=part.value.bars.map(b=>select(b,barKeys));}
    else if(section==='reference')p.value=reference(part.value);
    else if(section==='auxiliary'){p.value=select(part.value,['component','formula_version']);if(Array.isArray(part.value.segments))p.value.segments=part.value.segments.map(s=>({segment_id:s.segment_id,physical_contract:s.physical_contract,point_count:s.points?.length}));}
    else p.value={observed_non_null:true};
   }
   out[section]=p;
  }
  return out;
 };
 const allowed=url=>{try{const u=new URL(url);return [config.web_origin,config.api_origin].includes(u.origin)&&u.pathname==='/api/v1/market/newow/strategy-detail'&&u.searchParams.getAll('product').join(',')===config.product&&u.searchParams.getAll('frequency').length===1&&['5m','15m','30m','60m','1d','1w'].includes(u.searchParams.get('frequency'));}catch{return false}};
 XMLHttpRequest.prototype.send=function(...args){
  if(!(this instanceof XMLHttpRequest))return Reflect.apply(nativeSend,this,args);
  const xhr=this,sequence=++state.sequence,started_order=++state.event_order,started_at=Date.now();let observed=false;
  const load=()=>{observed=true;try{
   if(!allowed(xhr.responseURL))return;
   const row={sequence,started_order,completed_order:++state.event_order,url:xhr.responseURL,http:xhr.status,started_at,completed_at:Date.now(),evidence_kind:'xhr_response_text_compact'};
   if(!/^application\/(?:[\w.+-]*\+)?json(?:\s*;|$)/i.test(xhr.getResponseHeader('content-type')??''))row.error='XHR_CONTENT_TYPE_REJECTED';
   else if(xhr.responseType!==''&&xhr.responseType!=='text')row.error='XHR_RESPONSE_TYPE_REJECTED';
   else {try{const began=Date.now();row.response_text_chars=xhr.responseText.length;row.payload=compact(JSON.parse(xhr.responseText));row.observer_parse_ms=Date.now()-began;}catch{row.error='XHR_BODY_PARSE_OR_COMPACT_FAILED';}}
   state.records.push(row);
  }catch{state.records.push({sequence,started_at,error:'XHR_OBSERVER_FAILED'});}};
  const end=()=>{xhr.removeEventListener('load',load);xhr.removeEventListener('loadend',end);if(!observed&&allowed(xhr.responseURL))state.records.push({sequence,url:xhr.responseURL,http:xhr.status,started_at,completed_at:Date.now(),error:'XHR_NO_LOAD_EVENT'});};
  xhr.addEventListener('load',load,{once:true});xhr.addEventListener('loadend',end,{once:true});
  try{return Reflect.apply(nativeSend,xhr,args);}catch(error){xhr.removeEventListener('load',load);xhr.removeEventListener('loadend',end);throw error;}
 };
 Object.defineProperty(globalThis,'__p7XHR',{value:state,configurable:true});
}
