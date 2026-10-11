import { detectNewowPublicPatterns } from '../utils/newowPublicPatterns'
import type { PatternJob, PatternResult } from '../utils/newowPatternDisplay'
self.onmessage = (event:MessageEvent<PatternJob>) => {
 const job=event.data
 let result:PatternResult
 try { result={key:job.key,results:job.groups.map(group=>({ownerKey:group.key,patterns:detectNewowPublicPatterns(group.bars,job.period)})),error:null} }
 catch { result={key:job.key,results:[],error:'PATTERN_COMPUTATION_FAILED'} }
 self.postMessage(result)
}
