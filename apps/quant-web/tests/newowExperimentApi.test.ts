import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import ts from 'typescript'
const moduleUrl=(s:string)=>`data:text/javascript;base64,${Buffer.from(s).toString('base64')}`
const mockUrl=moduleUrl(`export const calls=[];export default {get(path,config){return new Promise((resolve,reject)=>calls.push({path,config,resolve,reject}))}}`)
const errorsUrl=moduleUrl(`export class NewowProductRequestError extends Error{constructor(code,classification){super(code);this.code=code;this.classification=classification}};export function classifyTransportError(error){return new NewowProductRequestError(error.response?.data?.detail?.code??'NEWOW_API_UNAVAILABLE',error.response?.status===409?'conflict':'unavailable')}`)
const source=readFileSync(new URL('../src/api/newowExperiments.ts',import.meta.url),'utf8')
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
 .replace(/from ['"]\.\/request['"]/g,`from '${mockUrl}'`)
 .replace(/from ['"]\.\/newowProduct.ts['"]/g,`from '${errorsUrl}'`)
 .replace(/from ['"]([^'"]+\.ts)['"]/g,(_m,path)=>path.startsWith('data:')?`from '${path}'`:`from '${new URL(path,new URL('../src/api/newowExperiments.ts',import.meta.url)).href}'`)
const api=await import(moduleUrl(compiled)),mock=await import(mockUrl)
const params={product:'rb',frequency:'1d',kind:'osc-test',as_of:'2026-10-08T07:00:00Z'} as const
function payload(){
 const formula_version='newow_osc_test_page_v3379_v1',profile_id='guiyi_newow_experiment_completed_physical_v1',input_policy_version='policy',bar={bar_end:'2026-10-07T07:00:00Z',trading_day:'2026-10-07',segment_id:'a',physical_contract:'RB2701',open:'100',high:'110',low:'90',close:'101',channel_high:'110',channel_low:'90'}
 return {...params,schema_version:'newow_experiment_detail_v2',formula_version,profile_id,input_policy_version,input_snapshot_hash:'a'.repeat(64),page_parity:true,executable:false,readiness:{status:'READY',reason_code:null},bars:[bar],markers:[],segments:[{segment_id:'a',physical_contract:'RB2701',status:'CURRENT',ordinary:null,theoretical:null}],meta:{identity:{...params,strategy:params.kind,series_kind:'actual_dominant',formula_version,profile_id,input_policy_version},as_of:params.as_of,read_at:params.as_of,input_content_sha256:'a'.repeat(64),data_revision_identity:'b'.repeat(64),snapshot_token:'token',result_hash:'c'.repeat(64),completed_only:true,executable:false,auto_order:false,last_completed_bar_end:bar.bar_end,last_trading_day:bar.trading_day}}
}
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve()}
test('experiment transport shares pending reads, isolates consumer cancellation and revalidates new visits',async()=>{
 const a=new AbortController(),b=new AbortController(),start=mock.calls.length
 const first=api.getNewowExperiment(params,a.signal);const rejected=assert.rejects(first,/Abort/)
 const second=api.getNewowExperiment({...params},b.signal);await flush()
 assert.equal(mock.calls.length,start+1);assert.equal(mock.calls.at(-1).config.readPriority,0)
 a.abort();await rejected;assert.equal(mock.calls.at(-1).config.signal.aborted,false)
 mock.calls.at(-1).resolve(payload());const panel=await second;assert.equal(panel.meta.snapshot_token,'token')
 const third=api.getNewowExperiment(params,b.signal);await flush();assert.equal(mock.calls.length,start+2);mock.calls.at(-1).resolve(payload());await third
 const history=api.getNewowExperimentHistory({...params,reference_part:'history',reference_mode:'ordinary',segment_id:'a',snapshot_token:'token'},panel,b.signal)
 const conflict=assert.rejects(history,(e:any)=>e.classification==='conflict');await flush();assert.equal(mock.calls.at(-1).config.readPriority,3)
 mock.calls.at(-1).reject({response:{status:409,data:{detail:{code:'NEWOW_SNAPSHOT_GENERATION_CONFLICT'}}}});await conflict
})
