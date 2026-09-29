import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

import pytest

from scripts.newow_candidate_tools.evidence import EvidenceStore
from scripts.newow_candidate_tools.transport import (
    collect_result, decode_chunk, verify_transport, store_script,
)


def _wire(body):
    return "### Result\n" + json.dumps(body) + "\n### End"


def _chunk(nonce, seq, data, done):
    return dict(kind="chunked_json_v1", nonce=nonce, seq=seq, done=done,
                bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                base64=base64.b64encode(data).decode())


def test_large_payload_preserves_exact_bytes_and_native_409(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    script = Path(__file__).resolve().parents[2] / "scripts/newow_candidate_tools/browser/transport.js"
    driver = r'''const fs=require('fs'); const crypto=require('crypto');
const source=fs.readFileSync(process.argv[1],'utf8').replace('__NONCE__',JSON.stringify('nonce'));
const fn=eval('('+source+')');
const result={responses:Array.from({length:90000},(_,i)=>({i,closed:Array.from({length:5},(_,j)=>({time:i*5+j,price:'测试😀'+j}))})),
older:{http:409,code:'NEWOW_FREQUENCY_NOT_OPEN',product:'m',frequency:'5m'}};
const page={__p7ChunkedCapture:{nonce:'nonce',result}};
(async()=>{let parts=[],chunks=[];let item;do{item=await fn(page);const bytes=Buffer.from(item.base64,'base64');
if(bytes.length!==item.bytes||crypto.createHash('sha256').update(bytes).digest('hex')!==item.sha256)throw Error('chunk');
parts.push(bytes);chunks.push(item.seq)}while(!item.done);
const actual=Buffer.concat(parts);const expected=Buffer.from(JSON.stringify(result));
if(!actual.equals(expected))throw Error('full mismatch');
process.stdout.write(JSON.stringify({chunks:chunks.length,bytes:actual.length,closed:result.responses.length*5,older:result.older}));})().catch(e=>{console.error(e);process.exit(1)});
'''
    result = subprocess.run([node, "-e", driver, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["chunks"] > 2 and body["closed"] == 450000
    assert body["older"] == {"http": 409, "code": "NEWOW_FREQUENCY_NOT_OPEN",
                             "product": "m", "frequency": "5m"}


@pytest.mark.parametrize("change,code", [
    ({"seq": 2}, "CHUNK_SEQUENCE_MISMATCH"),
    ({"sha256": "0" * 64}, "CHUNK_HASH_MISMATCH"),
    ({"base64": "!"}, "CHUNK_ENCODING_INVALID"),
    ({"bytes": 99}, "CHUNK_BYTE_LENGTH_MISMATCH"),
])
def test_bad_chunk_fails_closed(change, code):
    body = dict(_chunk("n", 1, b"{}", True), **change)
    with pytest.raises(ValueError, match=code):
        decode_chunk(body, "n", 1)


def test_full_manifest_detects_missing_chunk_and_spool_change(tmp_path):
    store = EvidenceStore(tmp_path)
    label = "minute-5m-dual"
    code = "async page=>({identity:{},responses:[1]})"
    nonce = hashlib.sha256((label + "\0" + code).encode()).hexdigest()
    observed = {"identity": {}, "responses": [1]}
    payload = json.dumps(observed, separators=(",", ":")).encode()
    chunks = [payload[:15], payload[15:]]
    calls = [subprocess.CompletedProcess([], 0, _wire({"kind": "stored", "nonce": nonce}), "")]
    calls += [subprocess.CompletedProcess([], 0, _wire(_chunk(nonce, i, part, i == 2)), "")
              for i, part in enumerate(chunks, 1)]
    with patch("scripts.newow_candidate_tools.transport._call", side_effect=calls):
        actual, _, manifest = collect_result(store, label, Path("/unused"), "s", code, "__NONCE__")
    assert actual == observed
    assert len(verify_transport(store, label, manifest, actual, nonce)) == 4
    with pytest.raises(ValueError, match="TRANSPORT_NONCE_MISMATCH"):
        verify_transport(store, label, manifest, actual, "0" * 64)
    (tmp_path / f"browser/{label}-chunk-0002.json").unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        verify_transport(store, label, manifest, actual, nonce)


def test_incomplete_chunk_stream_is_not_scene_success(tmp_path):
    store = EvidenceStore(tmp_path)
    label = "minute-5m-dual"
    code = "async page=>({})"
    nonce = hashlib.sha256((label + "\0" + code).encode()).hexdigest()
    first = subprocess.CompletedProcess([], 0, _wire({"kind": "stored", "nonce": nonce}), "")
    partial = subprocess.CompletedProcess([], 0, "partial output", "")
    with patch("scripts.newow_candidate_tools.transport._call", side_effect=[first, partial]):
        with pytest.raises(ValueError, match="CLI_RESULT_UNAVAILABLE"):
            collect_result(store, label, Path("/unused"), "s", code, "__NONCE__")
    assert (tmp_path / f"browser/{label}-chunk-0001.json").exists()
    assert not (tmp_path / f"browser/{label}-transport-manifest.json").exists()


def test_exact_chunk_boundary_and_next_scene_state(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    script = Path(__file__).resolve().parents[2] / "scripts/newow_candidate_tools/browser/transport.js"
    first = store_script("async page=>({x:'a'.repeat(1048576-8)})", "first")
    second = store_script("async page=>({x:'next'})", "second")
    driver = r'''const fs=require('fs'); const source=fs.readFileSync(process.argv[1],'utf8');
const first=eval('('+process.argv[2]+')'); const second=eval('('+process.argv[3]+')');
const page={};(async()=>{const a=await first(page);const chunk=await eval('('+source.replace('__NONCE__',JSON.stringify('first'))+')')(page);
if(!chunk.done||chunk.bytes!==1048576)throw Error('exact boundary');
const b=await second(page);if(b.nonce!=='second')throw Error('next scene');
const end=await eval('('+source.replace('__NONCE__',JSON.stringify('second'))+')')(page);
if(!end.done||JSON.parse(Buffer.from(end.base64,'base64').toString()).x!=='next')throw Error('next result');
process.stdout.write('PASS');})().catch(e=>{console.error(e);process.exit(1)});
'''
    result = subprocess.run([node, "-e", driver, str(script), first, second],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS"


def test_pending_state_blocks_next_scene_before_execution(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    second = store_script("async page=>{page.executed=true;return {x:1}}", "second")
    driver = r'''const next=eval('('+process.argv[1]+')');
const page={__p7ChunkedCapture:{nonce:'first',done:false},executed:false};
next(page).then(()=>{throw Error('unexpected success')}).catch(e=>{
if(e.message!=='CHUNK_STATE_OCCUPIED'||page.executed)process.exit(1);
process.stdout.write('PASS')});'''
    result = subprocess.run([node, "-e", driver, second], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS"
