import request from './request'
import {normalizeExperiment,type ExperimentRequest} from '../utils/newowExperiments.ts'
export function getNewowExperiment(params:ExperimentRequest,signal:AbortSignal){return request.get<never,unknown>('/market/newow/experiments',{params,signal,timeout:180_000}).then(raw=>normalizeExperiment(raw,params))}
