import { previewInstant } from './candidatePreviewInstant.ts'
import type { HomePeriodFact } from './newowHomeCards.ts'
import type { NewowProductSectionResponse } from '../types/newowProduct.ts'
export interface NewowHomeContext { product:string;strategy:string;frequency:string;as_of:string;input_sha256:string;physical_contract:string;segment_id:string;calculation_segment_id:string }
export function homeContext(product:string,strategy:string,frequency:string,fact:HomePeriodFact|undefined):NewowHomeContext|undefined {
 if(fact?.status!=='ready')return undefined
 return parseHomeContext({product,strategy,frequency,as_of:fact.as_of,input_sha256:fact.input_sha256,physical_contract:fact.physical_contract,segment_id:fact.segment_id,calculation_segment_id:fact.calculation_segment_id},{symbol:product,strategy,frequency})??undefined
}
export function parseHomeContext(raw:unknown,identity:{symbol:string;strategy?:string;frequency:string}):NewowHomeContext|null {
 try {
  if(typeof raw==='string'){if(raw.length>2048)return null;raw=JSON.parse(raw)}
  const v=raw as NewowHomeContext
  if(!v || v.product!==identity.symbol || v.strategy!==identity.strategy || v.frequency!==identity.frequency
   || previewInstant(v.as_of)===null || !/^[a-f0-9]{64}$/.test(v.input_sha256)
   || ![v.physical_contract,v.segment_id,v.calculation_segment_id].every(x=>typeof x==='string'&&x.length>0&&x.length<=256))return null
  return {product:v.product,strategy:v.strategy,frequency:v.frequency,as_of:v.as_of,input_sha256:v.input_sha256,physical_contract:v.physical_contract,segment_id:v.segment_id,calculation_segment_id:v.calculation_segment_id}
 }catch{return null}
}
export function homeContextChanged(expected:NewowHomeContext,chart:NewowProductSectionResponse<'chart'>):boolean {
 const bar=chart.value?.bars.at(-1)
 return !bar || expected.product!==chart.meta.identity.product || expected.strategy!==chart.meta.identity.strategy || expected.frequency!==chart.meta.identity.frequency
  || previewInstant(expected.as_of)!==previewInstant(chart.meta.as_of) || expected.input_sha256!==chart.meta.input_content_sha256
  || expected.physical_contract!==bar.physical_contract || expected.segment_id!==bar.segment_id || expected.calculation_segment_id!==bar.calculation_segment_id
}
