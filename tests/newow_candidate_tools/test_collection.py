import json
from pathlib import Path
import subprocess
from unittest.mock import patch
import pytest
from scripts.newow_candidate_tools.collection import (
    render_capture,
    render_scenario,
    capture,
    _parse_result,
)
from scripts.newow_candidate_tools.context import Candidate
from scripts.newow_candidate_tools.evidence import EvidenceStore

C = {
    "product": "cj",
    "code_sha": "a" * 40,
    "web_code_sha": "b" * 40,
    "worktree": str(Path(__file__).resolve().parents[2]),
    "since": "2023-01-01",
    "through": "2026-09-24",
    "as_of": "2026-09-24T07:00:00.000001+00:00",
    "schema": "newow_intraday_pilot_20260927",
    "api_origin": "http://127.0.0.1:8012",
    "web_origin": "http://127.0.0.1:5178",
}


def test_capture_contains_functional_full_and_earlier_once(tmp_path):
    js = render_capture(C, "5m", "dual", tmp_path)
    assert js.count("page.goto(") == 1
    assert "fullReadback" in js and "recordsReadback" in js
    assert "switch_away_and_return" in js
    assert "RESPONSE_BODY_READ_FAILED" in js
    assert "OLDER_WINDOW_ACTION_NOT_VISIBLE" in js
    assert "topPriceBefore" in js and "topPriceAfter" in js
    assert "history_limit" in js and "fusion_before" in js
    assert "NOT_RUN" in js or "blocked" in js


def test_configuration_injected_without_global_replacement(tmp_path):
    odd = dict(
        C,
        product="sm",
        api_origin="http://127.0.0.1:8013",
        web_origin="http://127.0.0.1:5179",
    )
    js = render_capture(odd, "60m", "trend", tmp_path)
    config = json.loads(js.split("const CONFIG = ", 1)[1].split(";\n", 1)[0])
    assert config["product"] == "sm"
    assert config["api_origin"] == odd["api_origin"]
    assert "product=cj" not in js and "symbol=cj" not in js
    assert "final_read96.py" not in js


def test_legacy_and_cancellation_are_separate(tmp_path):
    legacy = render_scenario(C, "legacy", "1w", "dual", tmp_path)
    cancel = render_scenario(C, "cancel", "5m", "trend", tmp_path)
    assert "NEWOW_REFERENCE_WEEKLY_WINDOW_PARTIAL" in legacy
    assert "ZERO_CLOSED" in legacy
    assert "AbortController" in cancel and "250" in cancel
    assert "pendingAtSwitch" in cancel
    assert "ACTUAL_CLIENT_TIMEOUT" in cancel


@pytest.mark.parametrize(
    "field,value",
    [
        ("product", "cj&x=1"),
        ("api_origin", "https://evil.test"),
        ("web_origin", "http://127.0.0.1:5178/x"),
        ("code_sha", "oops"),
    ],
)
def test_invalid_context_does_not_invoke_browser(tmp_path, field, value):
    candidate = dict(C, **{field: value})
    with patch("scripts.newow_candidate_tools.collection.subprocess.run") as run:
        with pytest.raises(ValueError):
            render_capture(candidate, "5m", "trend", tmp_path)
        run.assert_not_called()


def test_existing_output_refuses_before_browser(tmp_path):
    (tmp_path / "collection-observations.json").write_text("{}")
    with patch("scripts.newow_candidate_tools.collection.subprocess.run") as run:
        with pytest.raises(FileExistsError):
            capture(C, tmp_path, Path("/tmp/cli"), "candidate")
        run.assert_not_called()


def prepared(tmp_path):
    candidate = Candidate.from_mapping(C)
    proof = candidate.proof()
    checks = {key: dict(proof) for key in ("context", "assets", "preview")}
    checks["legacy"] = candidate.proof(
        rows={
            f: dict(
                source_profiles=["one", "two"],
                source_formula_versions=["v1"],
                reference_model_version="v1",
            )
            for f in ("1d", "1w")
        }
    )
    store = EvidenceStore(tmp_path)
    store.write("preflight-check.json", candidate.proof(checks=checks))
    store.write("legacy-expected-identities.json", checks["legacy"])
    executable = tmp_path / "cli.sh"
    executable.write_text("#!/bin/sh\nexit 99\n")
    executable.chmod(0o700)
    return candidate, executable


def test_capture_missing_preflight_blocks_before_cli(tmp_path):
    with patch("scripts.newow_candidate_tools.collection.subprocess.run") as run:
        with pytest.raises(FileNotFoundError):
            capture(C, tmp_path, Path("/tmp/cli"), "candidate")
        run.assert_not_called()


@pytest.mark.parametrize("gate", ["context", "assets", "preview", "legacy"])
def test_stage_identity_gate_rejects_stale_proof(tmp_path, gate):
    candidate, executable = prepared(tmp_path)
    path = tmp_path / "preflight-check.json"
    body = json.loads(path.read_text())
    body["checks"][gate]["task_sha256"] = "0" * 64
    path.write_text(json.dumps(body))
    with (
        patch.object(
            Candidate, "frozen_check", return_value=candidate.proof()
        ) as frozen,
        patch("scripts.newow_candidate_tools.collection.subprocess.run") as run,
    ):
        # context is replaced by fresh frozen_check, and must reject if *fresh* wrong.
        if gate == "context":
            frozen.return_value = dict(candidate.proof(), task_sha256="0" * 64)
        with pytest.raises(ValueError):
            capture(candidate, tmp_path, executable, "candidate")
        run.assert_not_called()


def test_cli_timeout_saved_and_never_replayed(tmp_path):
    candidate, executable = prepared(tmp_path)
    with (
        patch.object(Candidate, "frozen_check", return_value=candidate.proof()),
        patch(
            "scripts.newow_candidate_tools.collection.subprocess.run",
            side_effect=subprocess.TimeoutExpired("cli", 900, output=b"partial wire"),
        ) as run,
    ):
        result = capture(candidate, tmp_path, executable, "candidate")
        assert result["status"] == "BLOCKED" and result["completed_scene_count"] == 1
        run.assert_called_once()
    raw = json.loads((tmp_path / "browser/minute-5m-trend-cli.json").read_text())
    assert raw["failure"] == "CLI_TIMEOUT_NO_REPLAY" and raw["stdout"] == "partial wire"
    start = json.loads((tmp_path / "collection-start.json").read_text())
    assert set(start["tool_resource_sha256"]) == {
        "minute.js",
        "legacy.js",
        "cancel.js",
        "observer.js",
        "runtime.js",
        "transport.js",
        "collection.py",
        "transport.py",
    }
    assert all(len(value) == 64 for value in start["tool_resource_sha256"].values())
    with patch("scripts.newow_candidate_tools.collection.subprocess.run") as run:
        with pytest.raises(FileExistsError):
            capture(candidate, tmp_path, executable, "candidate")
        run.assert_not_called()


def test_bad_cli_wire_saved_and_stops_after_one_scene(tmp_path):
    candidate, executable = prepared(tmp_path)
    with (
        patch.object(Candidate, "frozen_check", return_value=candidate.proof()),
        patch(
            "scripts.newow_candidate_tools.collection.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "not-json", ""),
        ) as run,
    ):
        result = capture(candidate, tmp_path, executable, "candidate")
        assert result["status"] == "BLOCKED"
        run.assert_called_once()
    row = json.loads((tmp_path / "browser/minute-5m-trend.json").read_text())
    assert row["observed"]["code"] == "CLI_RESULT_UNAVAILABLE"
    assert row["visual_review"] == "NOT_RUN"


def test_nonzero_cli_saved_even_with_success_body(tmp_path):
    candidate, executable = prepared(tmp_path)
    with (
        patch.object(Candidate, "frozen_check", return_value=candidate.proof()),
        patch(
            "scripts.newow_candidate_tools.collection.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 7, "### Result\n{}\n### End", "redacted"
            ),
        ) as run,
    ):
        result = capture(candidate, tmp_path, executable, "candidate")
        assert result["status"] == "BLOCKED"
        run.assert_called_once()


@pytest.mark.parametrize(
    "text",
    [
        "### Result\n[]\n### End",
        '### Result\n"a"\n### End',
        "nothing",
        "### Result\nnull\n### End",
    ],
)
def test_nonobject_cli_result_rejected(text):
    assert _parse_result(text)["status"] == "BLOCKED"


def test_rendered_resources_parse_and_do_not_use_shell_or_old_outputs(tmp_path):
    # JavaScript parser only; no Playwright/app/network is instantiated.
    import shutil

    node = shutil.which("node")
    if not node:
        pytest.skip("Node parser unavailable")
    for scenario, frequency, mode in [
        ("minute", "5m", "dual"),
        ("legacy", "1w", "dual"),
        ("cancel", "5m", "trend"),
    ]:
        js = render_scenario(C, scenario, frequency, mode, tmp_path)
        result = subprocess.run(
            [node, "-e", 'new Function("return ("+process.argv[1]+")");', js],
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        assert "spec_from_file_location" not in js
        assert "outputs/" not in js
        assert "page.route(" not in js


def test_observer_keeps_full_array_and_still_rejects_other_product(tmp_path):
    import shutil

    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    observer = (
        Path(__file__).resolve().parents[2]
        / "scripts/newow_candidate_tools/browser/observer.js"
    ).read_text()
    config = dict(C, task_key="test")
    payload = {
        "meta": {"snapshot_token": "same"},
        "reference": {
            "delivery": "delivered",
            "status": {"status": "ready"},
            "value": {
                "performance_since": C["since"],
                "performance_through": C["through"],
                "curve_trades": [
                    {
                        "reference_trade_id": "trade1",
                        "reference_return_pct": "1.0000001",
                    },
                    {"reference_trade_id": "trade2", "reference_return_pct": "2"},
                ],
            },
        },
    }
    payload["auxiliary"] = {
        "delivery": "delivered",
        "status": {"status": "ready"},
        "value": {
            "component": "macd",
            "formula_version": "native",
            "segments": [
                {
                    "segment_id": "segment",
                    "physical_contract": "CJ2701",
                    "points": [1, 2],
                }
            ],
        },
    }
    # This is an isolated unit fixture, not market/browser acceptance evidence.
    script = (
        """class FixtureXHR {constructor(){this.events={};this.responseType="";this.status=200;} send(){} addEventListener(name,listener){this.events[name]=listener;} removeEventListener(){} getResponseHeader(){return "application/json";}}
    globalThis.XMLHttpRequest=FixtureXHR;
    const init=OBS;
    init(CONFIG);
    const xhr=new FixtureXHR();xhr.responseURL=CONFIG.web_origin+"/api/v1/market/newow/strategy-detail?product="+CONFIG.product+"&frequency=5m";xhr.responseText=JSON.stringify(PAYLOAD);xhr.send();xhr.events.load();
    const other=new FixtureXHR();other.responseURL=CONFIG.web_origin+"/api/v1/market/newow/strategy-detail?product=zz&frequency=5m";other.responseText=JSON.stringify(PAYLOAD);other.send();other.events.load();
    console.log(JSON.stringify(globalThis.__p7XHR.records));""".replace("OBS", observer)
        .replace("CONFIG", json.dumps(config))
        .replace("PAYLOAD", json.dumps(payload))
    )
    result = subprocess.run([node, "-e", script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert len(rows) == 1
    assert (
        rows[0]["payload"]["reference"]["value"]["curve_trades"]
        == payload["reference"]["value"]["curve_trades"]
    )
    assert rows[0]["payload"]["auxiliary"]["value"]["component"] == "macd"
    assert rows[0]["payload"]["auxiliary"]["value"]["segments"][0]["point_count"] == 2


def test_runtime_uses_no_node_url_global(tmp_path):
    js = render_capture(C, "5m", "trend", tmp_path)
    own = js.split("const xhrOwn=", 1)[1].split("const xhrOnRequest", 1)[0]
    assert "new URL(" not in own
    assert "products.length===1" in own


def test_snapshot_conflict_probes_bind_native_code_field(tmp_path):
    js = render_scenario(C, "cancel", "5m", "trend", tmp_path)
    assert "conflict.payload.detail?.code!=='NEWOW_SNAPSHOT_GENERATION_CONFLICT'" in js
    assert "snapshotCalls" in js and "maxRedirects:0" in js
    assert "snapshot_token=old" in js and "delete params.snapshot_token" in js


def test_asof_normalizes_instant_preserving_microseconds(tmp_path):
    candidate = dict(C, as_of="2026-09-24T15:00:00.000001+08:00")
    js = render_capture(candidate, "5m", "trend", tmp_path)
    config = json.loads(js.split("const CONFIG = ", 1)[1].split(";\n", 1)[0])
    assert config["as_of"] == "2026-09-24T07:00:00.000001+00:00"


def test_incomplete_success_object_is_stored_as_blocked(tmp_path):
    candidate, executable = prepared(tmp_path)
    with (
        patch.object(Candidate, "frozen_check", return_value=candidate.proof()),
        patch(
            "scripts.newow_candidate_tools.collection.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 0, "### Result\n{}\n### End", ""
            ),
        ) as run,
    ):
        result = capture(candidate, tmp_path, executable, "candidate")
        assert result["status"] == "BLOCKED"
        run.assert_called_once()


@pytest.fixture(autouse=True)
def no_actual_preview_get():
    # Unit tests never query a live service. validate_preview behavior has its
    # own real-shaped fixtures; production capture uses read_preview directly.
    with patch(
        "scripts.newow_candidate_tools.collection.read_preview",
        return_value=Candidate.from_mapping(C).proof(),
    ):
        yield


def test_capture_rechecks_actual_preview_identity_before_browser(tmp_path):
    candidate, executable = prepared(tmp_path)
    with (
        patch.object(Candidate, "frozen_check", return_value=candidate.proof()),
        patch(
            "scripts.newow_candidate_tools.collection.read_preview",
            return_value=dict(candidate.proof(), task_sha256="0" * 64),
        ),
        patch("scripts.newow_candidate_tools.collection.subprocess.run") as run,
    ):
        with pytest.raises(ValueError):
            capture(candidate, tmp_path, executable, "candidate")
        run.assert_not_called()


def test_actual_observer_legacy_listener_native_zero_and_aux_pipeline():
    """Execute the actual new static JS transforms in Node with isolated XHR fixtures."""
    import shutil

    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    resources = (
        Path(__file__).resolve().parents[2] / "scripts/newow_candidate_tools/browser"
    )
    observer = resources.joinpath("observer.js").read_text()
    legacy = resources.joinpath("legacy.js").read_text()
    # Source extraction is test-only; production uses reviewed static resources.
    listener = legacy[legacy.index(" const listen=") : legacy.index(" const failed=")]
    zero = legacy[
        legacy.index(" const nativeZero=") : legacy.index(" const waitStable=")
    ]
    config = dict(C, task_key="test-pipeline")
    script = r"""
    class FixtureXHR {constructor(){this.events={};this.responseType="";this.status=200;} send(){} addEventListener(name,listener){this.events[name]=listener;} removeEventListener(){} getResponseHeader(){return "application/json";}}
    globalThis.XMLHttpRequest=FixtureXHR;
    const CONFIG=__CONFIG__,FREQUENCY='1w',ASOF=CONFIG.as_of;let MODE='trend';
    const init=(__OBSERVER__);init(CONFIG);
    const pending=[],responses=[],bodyErrors=[];const phase='initial';const own=()=>true;const xhrBindings=new WeakMap();
    const observedJSON=async r=>globalThis.__p7XHR.records.find(x=>x.sequence===r.sequence).payload;
    __LISTENER__
    __ZERO__
    const response=async(payload,number)=>{
      const url=CONFIG.web_origin+'/api/v1/market/newow/strategy-detail?product='+CONFIG.product+'&frequency=1w&strategy=trend&section=reference';
      const xhr=new FixtureXHR();xhr.responseURL=url;xhr.responseText=JSON.stringify(payload);xhr.send();xhr.events.load();
      const request={number};const r={sequence:globalThis.__p7XHR.records.at(-1).sequence,url:()=>url,status:()=>200,request:()=>request};xhrBindings.set(request,{fixture:true});listen(r);await Promise.all(pending);return responses.at(-1);
    };
    const value={performance_since:'2025-09-24',performance_through:'2026-09-24',reference_input_sha256:'b'.repeat(64),executable:false,auto_order:false,summary:{closed_count:0},curve_trades:[],items:[]};
    const meta={identity:{product:CONFIG.product,frequency:'1w',strategy:'trend'},as_of:ASOF,snapshot_token:'native-token',input_content_sha256:'b'.repeat(64)};
    (async()=>{
      const first=await response({meta,reference:{delivery:'delivered',status:{status:'ready'},value}},1);
      const initialEmpty=nativeZero(first);
      MODE='dual';const dual=await response({meta,reference:{delivery:'delivered',status:{status:'ready'},value:{...value,fusion_comparison:{...value,groups:[{model:'fusion',closed_count:0}],curve:[]}}}},4);const dualEmpty=nativeZero(dual);MODE='trend';
      const aux=await response({meta,auxiliary:{delivery:'delivered',status:{status:'ready'},value:{component:'macd',formula_version:'native',segments:[{segment_id:'s',physical_contract:'CJ2701',points:[11,12]}]}}},2);
      const trade={reference_trade_id:'closed',status:'CLOSED',reference_return_pct:'1.1'};
      const partial=await response({meta,reference:{delivery:'delivered',status:{status:'warming',reason_code:'NEWOW_REFERENCE_WEEKLY_WINDOW_PARTIAL'},value:{...value,performance_since:CONFIG.since,performance_through:'2026-09-18',curve_trades:[trade],summary:{closed_count:1}}}},3);
      console.log(JSON.stringify({initialEmpty,dualEmpty,dualCurve:dual.reference.value.fusion.curve,initialCurve:first.reference.value.curve_trades,auxComponent:aux.auxiliary.value.component,auxPoints:aux.auxiliary.value.segments[0].points,partialCurve:partial.reference.value.curve_trades,bodyErrors}));
    })().catch(error=>{console.error(error);process.exit(1)});
    """
    replacements = {
        "__CONFIG__": json.dumps(config),
        "__OBSERVER__": observer,
        "__LISTENER__": listener,
        "__ZERO__": zero,
    }
    for key, value in replacements.items():
        script = script.replace(key, value)
    result = subprocess.run([node, "-e", script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["initialEmpty"] is True
    assert observed["dualEmpty"] is True and observed["dualCurve"] == []
    assert observed["initialCurve"] == []
    assert observed["auxComponent"] == "macd" and observed["auxPoints"] == 2
    assert observed["partialCurve"][0]["reference_trade_id"] == "closed"
    assert observed["bodyErrors"] == []


def test_minute_xhr_binding_excludes_aborted_peer_but_rejects_missing_or_wrong_response():
    """Exercise the actual minute binding code for the LH cancelled-then-refreshed URL."""
    import shutil

    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    minute = (
        Path(__file__).resolve().parents[2]
        / "scripts/newow_candidate_tools/browser/minute.js"
    ).read_text()
    binding = minute[minute.index(" const readXHR=async r=>{") : minute.index(" const xhrBindings=")]
    script = r"""
    const url='http://127.0.0.1:5178/api/v1/market/newow/strategy-detail?product=lh&frequency=1d&section=explanation';
    const cancelled={},replacement={};
    const xhrRequests=[{request:cancelled,id:1,url,method:'GET',done:true},{request:replacement,id:2,url,method:'GET',done:true}];
    const requestRows=new WeakMap([[cancelled,{failed:true}],[replacement,{finished:true}]]);
    const xhrWatermark={document_id:'same',sequence:0};
    globalThis.__p7XHR={document_id:'same',records:[]};
    const page={evaluate:async(fn,arg)=>fn(arg),waitForTimeout:async()=>new Promise(resolve=>setTimeout(resolve,1))};
    let xhrDeadline=Date.now()+40;
    __BINDING__
    const response={request:()=>replacement,status:()=>200};
    const row={url,sequence:1,started_order:1,completed_order:2,http:200,payload:{meta:{identity:{product:'lh'}}}};
    (async()=>{
      globalThis.__p7XHR.records=[row];
      const success=await readXHR(response);
      globalThis.__p7XHR.records=[];xhrDeadline=Date.now()+30;
      let missing=false;try{await readXHR(response)}catch(e){missing=e.message==='XHR_COMPACT_OBSERVATION_MISSING'}
      globalThis.__p7XHR.records=[{...row,http:201}];xhrDeadline=Date.now()+30;
      let mismatch=false;try{await readXHR(response)}catch(e){mismatch=e.message==='XHR_RESPONSE_IDENTITY_MISMATCH'}
      console.log(JSON.stringify({success:success.binding.node_request_id,missing,mismatch}));
    })().catch(e=>{console.error(e);process.exit(1)});
    """.replace("__BINDING__", binding)
    result = subprocess.run([node, "-e", script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"success": 2, "missing": True, "mismatch": True}


def test_minute_away_default_records_match_actual_dom_and_keep_target_200_gate():
    """Exercise the collector's real terminal and record matching functions."""
    import shutil

    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    minute = (
        Path(__file__).resolve().parents[2]
        / "scripts/newow_candidate_tools/browser/minute.js"
    ).read_text()
    terminal = minute[minute.index("const targetTerminal=") : minute.index(";const responses=[]")] + ";"
    matching = minute[minute.index("const recordsMatchDOM=") : minute.index("const settleTarget=")]
    script = r"""
    const PRODUCT='oi',FREQUENCY='5m',MODE='trend',CONFIG={as_of:'2026-09-24T07:00:00.000001+00:00'};
    const apiParams=url=>{const q=new URL(url).searchParams;return {get:key=>q.get(key)}};
    const isTargetRequest=(url,frequency=FREQUENCY)=>{const q=apiParams(url);return q.get('product')===PRODUCT&&q.get('frequency')===frequency&&q.get('strategy')==='trend'};
    let responses=[];
    __TERMINAL__
    __MATCHING__
    const base=(frequency,section,items,token='snapshot',extra={})=>({row_request:true,request_id:1,http:200,url:'http://127.0.0.1:5178/api/v1/market/newow/strategy-detail?'+new URLSearchParams({product:'oi',frequency,strategy:'trend',section,as_of:CONFIG.as_of,...extra}),payload:{meta:{identity:{product:'oi',frequency,strategy:'trend'},as_of:CONFIG.as_of,snapshot_token:token,input_content_sha256:'digest'},[section]:{delivery:'delivered',status:{status:'ready'},value:section==='reference'?{items:items.map(reference_trade_id=>({reference_trade_id})),reference_input_sha256:'source',reference_revision:'revision',performance_since:'2023-01-01',performance_through:'2026-09-24',next_before:null}:{}}}});
    const dom=ids=>({target:true,busy:false,explanationBusy:false,curves:1,ids:ids.map(id=>'card-'+id)});
    const run=(frequency,ids,items,options={})=>{
      const chart=base(frequency,'chart',[]),reference=base(frequency,'reference',items,options.referenceToken??'snapshot',options.extra??{});
      chart.request_id=1;reference.request_id=2;responses=[chart,reference,...(options.additional??[])];
      const resolved=targetTerminal(0,frequency);
      return {terminal:resolved?.kind??null,match:recordsMatchDOM(dom(ids),resolved,0,frequency)};
    };
    const away=run('60m',['a','b'],['a','b']);
    const emptyAway=run('60m',[],[]);
    const target=run('5m',['a','b'],['a','b'],{extra:{history_limit:'200'}});
    const emptyTarget=run('5m',[],[],{extra:{history_limit:'200'}});
    const defaultTarget=run('5m',['a'],['a']);
    const wrongToken=run('60m',['a'],['a'],{referenceToken:'other'});
    const duplicate=run('60m',['a','a'],['a','a']);
    const missing=run('60m',['a'],['a','b']);
    const reversed=run('60m',['b','a'],['a','b']);
    const first=base('60m','reference',['a']);first.request_id=2;first.payload.reference.value.next_before='cursor-a';
    const page=base('60m','reference',['b'],'snapshot',{history_before:'wrong-cursor'});page.request_id=3;
    responses=[base('60m','chart',[]),first,page];
    const cursorTerminal=targetTerminal(0,'60m');
    const wrongCursor={terminal:cursorTerminal?.kind??null,match:recordsMatchDOM(dom(['a','b']),cursorTerminal,0,'60m')};
    console.log(JSON.stringify({away,emptyAway,target,emptyTarget,defaultTarget,wrongToken,duplicate,missing,reversed,wrongCursor}));
    """.replace("__TERMINAL__", terminal).replace("__MATCHING__", matching)
    result = subprocess.run([node, "-e", script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual["away"] == {"terminal": "ready", "match": True}
    assert actual["emptyAway"] == {"terminal": "ready", "match": True}
    assert actual["target"] == {"terminal": "ready", "match": True}
    assert actual["emptyTarget"] == {"terminal": "ready", "match": False}
    assert actual["defaultTarget"] == {"terminal": "ready", "match": False}
    assert actual["wrongToken"] == {"terminal": None, "match": False}
    for name in ("duplicate", "missing", "reversed", "wrongCursor"):
        assert actual[name] == {"terminal": "ready", "match": False}
