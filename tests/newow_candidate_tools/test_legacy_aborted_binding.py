"""Exercise actual legacy XHR binding with an explicitly aborted earlier node peer."""
import json,shutil,subprocess
from pathlib import Path


def test_explicit_aborted_peer_does_not_consume_return_binding_budget():
    src=(Path(__file__).resolve().parents[2]/'scripts/newow_candidate_tools/browser/legacy.js').read_text()
    binding=src[src.index(' const readXHR=async r=>{'):src.index(' const xhrBindings=')]
    js=r'''
const url='http://127.0.0.1:5178/api/v1/market/newow/strategy-detail?product=sc&strategy=trend&frequency=1w&section=explanation&snapshot_token=token';
const first={},current={};const xhrRequests=[{request:first,id:4,url,method:'GET',done:true,failed_error:'net::ERR_ABORTED'},{request:current,id:16,url,method:'GET',done:true}];
const xhrWatermark={document_id:'same',sequence:0};const row={url,sequence:1,started_order:1,completed_order:2,http:200,payload:{meta:{snapshot_token:'token'}}};globalThis.__p7XHR={document_id:'same',records:[row]};
let now=0;const Date={now:()=>now};let xhrDeadline=30;const page={evaluate:async(fn,arg)=>fn(arg),waitForTimeout:async ms=>{now+=ms}};
const assert=(ok,msg)=>{if(!ok)throw Error(msg)};
__BINDING__
const response={request:()=>current,status:()=>200};
const rejected=async(code)=>{now=0;xhrDeadline=30;try{await readXHR(response);throw Error('unexpected success')}catch(e){assert(e.message===code,e.message)}};
(async()=>{
 const observed=await readXHR(response);assert(observed.binding.node_request_id===16&&now===0,'real return row exact');
 assert(xhrRequests[0].failed_error==='net::ERR_ABORTED','abort preserved');
 globalThis.__p7XHR.records=[];await rejected('XHR_COMPACT_OBSERVATION_MISSING');
 globalThis.__p7XHR.records=[{...row,http:409}];await rejected('XHR_RESPONSE_IDENTITY_MISMATCH');
 globalThis.__p7XHR.records=[row,row];await rejected('XHR_REQUEST_BINDING_AMBIGUOUS');
 globalThis.__p7XHR.records=[row];xhrRequests[0].failed_error='net::ERR_TIMED_OUT';await rejected('XHR_COMPACT_OBSERVATION_MISSING');
 xhrRequests[0].failed_error='net::ERR_ABORTED';xhrRequests[0].done=false;await rejected('XHR_COMPACT_OBSERVATION_MISSING');
 xhrRequests[0].done=true;globalThis.__p7XHR.records=[{...row,url:url+'&wrong=1'}];await rejected('XHR_COMPACT_OBSERVATION_MISSING');
 globalThis.__p7XHR.records=[{...row,started_order:3,completed_order:2}];await rejected('XHR_REQUEST_BINDING_AMBIGUOUS');
 globalThis.__p7XHR.records=[row];xhrRequests[1].failed_error='net::ERR_ABORTED';await rejected('XHR_REQUEST_IDENTITY_MISSING');
 console.log(JSON.stringify({passed:true,cases:10}));
})().catch(e=>{console.error(e.message);process.exit(1)});
'''.replace('__BINDING__',binding)
    result=subprocess.run([shutil.which('node'),'-e',js],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'passed':True,'cases':10}


def test_actual_failed_listener_retains_initial_failure_and_marks_only_exact_error():
    src=(Path(__file__).resolve().parents[2]/'scripts/newow_candidate_tools/browser/legacy.js').read_text()
    callbacks=src[src.index(" const xhrOnFinished="):src.index(" page.on('request',xhrOnRequest)")]
    failed=src[src.index(' const failed='):src.index(" page.on('request',dispatched)")]
    js=r'''
const url='http://127.0.0.1:5178/api/v1/market/newow/strategy-detail?product=sc&section=explanation';let error='net::ERR_ABORTED';const request={url:()=>url,failure:()=>({errorText:error})};const xhrRequests=[{request,id:4,done:false}],failures=[],pageErrors=[];const phase='initial',own=()=>true;
__CALLBACKS__
__FAILED__
xhrOnFailed(request);failed(request);const explicit={...xhrRequests[0]};error='net::ERR_TIMED_OUT';xhrOnFailed(request);failed(request);console.log(JSON.stringify({explicit:explicit.failed_error,done:explicit.done,unknown:xhrRequests[0].failed_error,failures}));
'''.replace('__CALLBACKS__',callbacks).replace('__FAILED__',failed)
    result=subprocess.run([shutil.which('node'),'-e',js],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    observed=json.loads(result.stdout)
    assert observed['explicit']=='net::ERR_ABORTED' and observed['done'] is True
    assert observed['unknown']=='net::ERR_TIMED_OUT'
    assert [x['error'] for x in observed['failures']]==['net::ERR_ABORTED','net::ERR_TIMED_OUT']
    assert all(x['phase']=='initial' for x in observed['failures'])
