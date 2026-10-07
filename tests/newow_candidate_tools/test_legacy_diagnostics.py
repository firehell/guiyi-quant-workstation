"""Execute extracted bounded diagnostics and wait; no browser/network."""
import json,shutil,subprocess
from pathlib import Path


def test_legacy_wait_diagnostics_deadline_and_predicates_unchanged():
    src=(Path(__file__).resolve().parents[2]/'scripts/newow_candidate_tools/browser/legacy.js').read_text()
    begin=src.index('const safeDiagnosticError=')
    funcs=src[begin:src.index('// End bounded wait diagnostics.',begin)]
    wait=src[src.index(' const waitStable='):src.index(' const selectClosed=')]
    js=r'''
const CONFIG={product:'sc',web_origin:'http://127.0.0.1:5178',api_origin:'http://127.0.0.1:8012'};
const assert=(x,m)=>{if(!x)throw Error(m)};
let time=0;const Date={now:()=>time};let xhrDeadline=0;const FREQUENCY='1w',MODE='trend';let phase='return';
const inFlight=new Set(),xhrRequests=[],pending=[],responses=[];let pendingBodyReads=0,completedBodyReads=0;
let polls=0;const d={url:'http://127.0.0.1:5178/market/chart?symbol=sc&frequency=1w',mode:['趋势策略'],cards:['id'],curves:[{points:'0,0 1,1'}],statuses:['解释尚未读取。'],scopeBusy:false};const dom=async()=>{polls++;return d};
const page={waitForTimeout:async ms=>{time+=ms}};const nativeZero=()=>false;
__FUNCTIONS__
__WAIT__
(async()=>{
 await waitStable('returned');assert(waitStages[0].wait_label==='returned'&&waitStages[0].last.stable===3,'per wait retained');assert(polls===3&&time===200,'original 3 polls');assert(lastWaitDiagnostic.ready===true&&lastWaitDiagnostic.stable===3,'settled');assert(lastWaitDiagnostic.phase==='return'&&lastWaitDiagnostic.deadline_ms===65000,'original budget');
 phase='blocked';time=1000;inFlight.add({url:()=> 'http://127.0.0.1:5178/api/v1/market/newow/strategy-detail?product=sc&section=explanation',method:()=> 'GET'});pendingBodyReads=1;polls=0;let stopped=false;try{await waitStable()}catch(e){stopped=e.message==='LEGACY_DOM_NOT_SETTLED_ZERO_CLOSED_REQUIRES_NATIVE_PROOF'}assert(stopped,'same stop');assert(lastWaitDiagnostic.ready===false&&lastWaitDiagnostic.in_flight.count===1&&lastWaitDiagnostic.pending_body_reads===1,'hidden facts');assert(lastWaitDiagnostic.in_flight.requests[0].method==='GET'&&lastWaitDiagnostic.in_flight.requests[0].url.includes('section=explanation'),'safe request');assert(waitDiagnostics.length<=64,'bounded');assert(lastWaitDiagnostic.elapsed_ms===65000&&lastWaitDiagnostic.event==='TIMEOUT','same limit');assert(waitStages.length===2&&waitStages[0].last.stable===3,'earlier stage preserved');
 inFlight.clear();pendingBodyReads=0;time=0;pending.push({then(resolve){time=65001;resolve()}});let pendingStopped=false;try{await waitStable('pending_budget')}catch(e){pendingStopped=e.message==='LEGACY_DOM_NOT_SETTLED_ZERO_CLOSED_REQUIRES_NATIVE_PROOF'}assert(pendingStopped&&lastWaitDiagnostic.elapsed_ms===65101&&lastWaitDiagnostic.stable===1,'pending budget unchanged');pending.length=0;
 assert(safeDiagnosticError({name:'Error',message:'XHR_COMPACT_OBSERVATION_MISSING'}).code==='XHR_COMPACT_OBSERVATION_MISSING','safe known');assert(safeDiagnosticError({name:'Error',message:'secret SQL password'}).code==='BODY_READ_MESSAGE_REDACTED','no secret');
 const request={url:()=> 'https://evil.invalid/?password=secret',method:()=> 'POST'};inFlight.clear();inFlight.add(request);const compact=diagnosticInFlight();assert(compact.requests[0].url==='REQUEST_URL_REDACTED','foreign URL');
 console.log(JSON.stringify({passed:true,original_polls:3,max_samples:waitDiagnostics.length}));
})().catch(e=>{console.error(e.message);process.exit(1)});
'''.replace('__FUNCTIONS__',funcs).replace('__WAIT__',wait)
    result=subprocess.run([shutil.which('node'),'-e',js],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'passed':True,'original_polls':3,'max_samples':64}
