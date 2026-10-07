"""Execute the collector's extracted supplement functions, without browser/network."""
import json
from pathlib import Path
import shutil
import subprocess


def test_supplement_exact_aborted_partner_once():
    node = shutil.which('node')
    assert node
    source = (Path(__file__).resolve().parents[2] / 'scripts/newow_candidate_tools/browser/minute.js').read_text()
    start = source.index('const selectSupplementalPartner=')
    functions = source[start:source.index('// End supplemental partner functions.', start)]
    driver = r'''
const apiParams=url=>{const q=new URL(url).searchParams;return {get:k=>q.get(k)}};
__FUNCTIONS__
const config={product:'sc',as_of:'2026-09-24T07:00:00+00:00',web_origin:'http://127.0.0.1:5178',api_origin:'http://127.0.0.1:8012'};
const url=(s,part,extra={})=>config.web_origin+'/api/v1/market/newow/strategy-detail?'+new URLSearchParams({product:'sc',frequency:'5m',strategy:s,series_kind:'actual_dominant',section:part,as_of:config.as_of,...extra});
const chart=s=>({row_request:true,request_phase:'seed',request_id:s==='trend'?1:2,http:200,url:url(s,'chart'),xhr_binding:{url:url(s,'chart'),http:200,evidence_kind:'xhr_response_text_compact'},payload:{meta:{identity:{product:'sc',frequency:'5m',strategy:s},as_of:config.as_of,snapshot_token:s+'-token',input_content_sha256:'hash'},chart:{delivery:'delivered',status:{status:'ready',evidence_status:'ACTIVE_CODE_VERIFIED'},value:{bars:[{}]}}}});
const ref={row_request:true,request_id:3,http:200,url:url('trend','reference'),payload:{}};
const abort={id:4,url:url('oscillation','reference',{history_limit:'200',snapshot_token:'oscillation-token'}),phase:'seed',method:'GET',failed:true,error:'net::ERR_ABORTED'};
const base=()=>({mode:'dual',frequency:'5m',after:0,config,responses:[chart('trend'),chart('oscillation'),ref],requests:[abort],inFlight:0,pendingReads:0,identityValid:true});
const select=o=>selectSupplementalPartner({...base(),...o});
const assert=(x,m)=>{if(!x)throw Error(m)};
assert(select({})?.url===abort.url,'positive exact url');
for(const key of ['product','frequency','strategy','section','as_of','snapshot_token','history_limit']){const bad=new URL(abort.url);bad.searchParams.set(key,'wrong');assert(!select({requests:[{...abort,url:bad.href}]}),key);}
for(const bad of [abort.url.replace(config.web_origin,'http://other'),abort.url.replace('/api/v1/market/','/other/'),abort.url+'&snapshot_token=oscillation-token',abort.url+'#fragment',abort.url+'&include_fusion=true'])assert(!select({requests:[{...abort,url:bad}]}),'url allowlist');
assert(!select({requests:[{...abort,method:'POST'}]}),'method');assert(!select({requests:[{...abort,phase:'away'}]}),'phase');assert(!select({bodyErrors:[{}]}),'body errors');assert(!select({mode:'trend'}),'single mode');assert(!select({inFlight:1}),'inflight');assert(!select({pendingReads:1}),'body pending');assert(!select({identityValid:false}),'identity');assert(!select({after:4}),'floor');
assert(!select({requests:[{...abort,failed:false}]}),'not aborted');assert(!select({requests:[{...abort,error:'net::ERR_FAILED'}]}),'unknown fail');assert(!select({requests:[abort,{...abort,id:5}]}),'ambiguous abort');
assert(!select({responses:[...base().responses,{...ref,url:abort.url,request_id:5}]}),'reference already exists');
for(const mutate of [c=>c.payload.meta.snapshot_token='other',c=>c.payload.meta.identity.product='oi',c=>c.payload.chart.status.status='warming',c=>c.xhr_binding=null]){const c=chart('oscillation');mutate(c);assert(!select({responses:[chart('trend'),c,ref]}),'chart reject');}
(async()=>{let sent=[];let event='load';let http=200;global.XMLHttpRequest=class{open(method,url,async){sent.push({method,url,async})}send(){this.status=http;this.responseText=''+JSON.stringify({meta:{snapshot_token:'oscillation-token'},reference:{value:{curve_trades:[{id:'full-row'}]}}});this.responseURL=abort.url;this['on'+event]();}};const full=await sendSupplementalXHR({url:abort.url,timeout:30});assert(full.payload.reference.value.curve_trades[0].id==='full-row'&&full.response_text===JSON.stringify(full.payload)&&full.response_text_chars===full.response_text.length&&full.response_text_sha256.length===64&&full.payload_sha256.length===64&&!full.extra_get,'complete raw preserved');assert(sent[0].method==='GET'&&sent[0].url===abort.url&&sent[0].async,'true XHR');for(const outcome of ['load','error','abort','timeout']){event=outcome;http=409;let rejected=false;try{await sendSupplementalXHR({url:abort.url,timeout:30})}catch{rejected=true}assert(rejected,'XHR stop '+outcome)}const evidence=select({});const meta={identity:{product:'sc',frequency:'5m',strategy:'oscillation'},as_of:config.as_of,snapshot_token:evidence.snapshot_token,input_content_sha256:'source'};const part={delivery:'delivered',status:{status:'ready',evidence_status:'ACTIVE_CODE_VERIFIED'},value:full.payload.reference.value};const boundFull={...full,payload:{meta,reference:part}};const row={row_request:true,http:200,url:abort.url,xhr_binding:{url:abort.url,http:200,evidence_kind:'xhr_response_text_compact',response_text_chars:full.response_text_chars},payload:{meta,reference:part}};assert(bindSupplementalResponse({rows:[row],evidence,config,frequency:'5m',readback:boundFull}).xhr_binding,'full bound');for(const mutate of [r=>r.http=409,r=>r.payload.meta.snapshot_token='wrong',r=>r.payload.meta.identity.frequency='15m',r=>r.xhr_binding=null]){const bad=JSON.parse(JSON.stringify(row));mutate(bad);let rejected=false;try{bindSupplementalResponse({rows:[bad],evidence,config,frequency:'5m',readback:boundFull})}catch{rejected=true}assert(rejected,'native binding rejected')}const stale=JSON.parse(JSON.stringify(boundFull));stale.payload.meta.snapshot_token='wrong';let staleRejected=false;try{bindSupplementalResponse({rows:[row],evidence,config,frequency:'5m',readback:stale})}catch{staleRejected=true}assert(staleRejected,'full/native mismatch');const state={attempted:false};const actions=[];let calls=0;const candidate=select({});await runSupplementalPartner(candidate,state,actions,async()=>{calls++;return full});await runSupplementalPartner(candidate,state,actions,async()=>{calls++});assert(calls===1&&actions.length===1&&state.attempted,'once');assert(actions[0].kind==='supplemental_partner_reference'&&actions[0].aborted_request.id===4&&actions[0].chart_binding&&actions[0].response_readback===full,'evidence action');const failed={attempted:false};let failures=0;let stopped=false;try{await runSupplementalPartner(candidate,failed,[],async()=>{failures++;throw Error('409')})}catch(e){stopped=e.message==='SUPPLEMENTAL_PARTNER_REFERENCE_FAILED'}await runSupplementalPartner(candidate,failed,[],async()=>{failures++});assert(stopped&&failures===1,'failed once stop');console.log(JSON.stringify({passed:true,calls,failures}));})().catch(e=>{console.error(e.message);process.exit(1)});
'''.replace('__FUNCTIONS__', functions)
    result = subprocess.run([node, '-e', driver], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'passed': True, 'calls': 1, 'failures': 1}


def test_native_failed_scene_status_fields_bind_without_alias():
    """Use finalized actual capture DTO fields, not a mirrored fake evidence alias."""
    import copy
    import pytest

    work = Path(__file__).resolve().parents[2]
    raw = work / 'outputs/sc-candidate-closeout-20261005/recovery/acceptance/browser/minute-5m-dual.json'
    if not raw.exists():
        pytest.skip('Historical failure fixture is task-local')
    observed = json.loads(raw.read_text())['observed']
    native = next(r for r in observed['responses'] if ((r['payload'].get('reference') or {}).get('status') or {}).get('status') == 'ready')
    assert native['payload']['reference']['status']['evidence_status'] == 'ACTIVE_CODE_VERIFIED'
    assert 'evidence' not in native['payload']['reference']['status']
    row = copy.deepcopy(native)
    # Only scalar native DTO identity/status fields are needed by this binding test.
    row['payload']['reference']['value'] = {'native_ready_value_present': True}
    readback = dict(http=200, url=row['url'], payload=row['payload'], response_text_chars=row['xhr_binding']['response_text_chars'])
    evidence = dict(url=row['url'], strategy=row['payload']['meta']['identity']['strategy'], snapshot_token=row['payload']['meta']['snapshot_token'])
    config = json.loads((raw.parents[1] / 'candidate.json').read_text())
    source = (work / 'scripts/newow_candidate_tools/browser/minute.js').read_text()
    functions = source[source.index('const selectSupplementalPartner='):source.index('// End supplemental partner functions.')]
    driver = "const apiParams=url=>{const q=new URL(url).searchParams;return {get:k=>q.get(k)}};" + functions + r'''
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const args={rows:[input.row],evidence:input.evidence,config:input.config,frequency:'5m',readback:input.readback};
bindSupplementalResponse(args);
for(const value of [undefined,'UNKNOWN']){const bad=JSON.parse(JSON.stringify(args));bad.rows[0].payload.reference.status.evidence_status=value;let reject=false;try{bindSupplementalResponse(bad)}catch{reject=true}if(!reject)throw Error('native evidence_status gate absent');}
console.log(JSON.stringify({native_status_fields_pass:true}));
'''
    result = subprocess.run([shutil.which('node'), '-e', driver], input=json.dumps(dict(row=row,readback=readback,evidence=evidence,config=config)),text=True,capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'native_status_fields_pass': True}
