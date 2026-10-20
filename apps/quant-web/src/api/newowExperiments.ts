import request from './request'
import { classifyTransportError, NewowProductRequestError } from './newowProduct.ts'
import { newowSessionResources, newowResourceIdentity } from '../utils/newowSessionResources.ts'
import { READ_PRIORITY } from '../utils/readAdmission.ts'
import {normalizeExperiment,normalizeExperimentHistory,type ExperimentRequest,type ExperimentDetail} from '../utils/newowExperiments.ts'
function load<T>(params:ExperimentRequest,signal:AbortSignal,normalize:(raw:unknown)=>T):Promise<T>{
 const key=`newow:${params.product}:experiment:${JSON.stringify(Object.entries(params).sort(([a],[b])=>a.localeCompare(b)))}`
 return newowSessionResources.load(key,async sharedSignal=>{
  let raw:unknown;
  try {raw=await request.get<never,unknown>('/market/newow/experiments',{params,signal:sharedSignal,timeout:180_000,readPriority:params.reference_part==='history'?READ_PRIORITY.history:READ_PRIORITY.foreground})}
  catch(error){throw classifyTransportError(error)}
  try{return normalize(raw)}catch{throw new NewowProductRequestError('NEWOW_RESPONSE_INVALID','response_invalid')}
 },newowResourceIdentity,signal,true)
}
export function getNewowExperiment(params:ExperimentRequest,signal:AbortSignal){return load(params,signal,raw=>normalizeExperiment(raw,params))}
export function getNewowExperimentHistory(params:ExperimentRequest,panel:ExperimentDetail,signal:AbortSignal){return load(params,signal,raw=>normalizeExperimentHistory(raw,panel,params))}
