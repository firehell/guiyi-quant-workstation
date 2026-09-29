"""Bounded Playwright result transport with exact ordering and byte integrity."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import subprocess

from .context import need
from .evidence import EvidenceStore

CHUNK_LIMIT = 4 * 1024 * 1024  # UTF-8 bytes; JS emits at most 1 Mi UTF-16 units.
MAX_CHUNKS = 512
MAX_BYTES = 512 * 1024 * 1024


def parse_result(stdout: str) -> dict:
    try:
        body = json.loads(stdout.split("### Result\n", 1)[1].split("\n### ", 1)[0])
    except (ValueError, IndexError, TypeError) as exc:
        raise ValueError("CLI_RESULT_UNAVAILABLE") from exc
    need(isinstance(body, dict), "CLI_RESULT_NOT_OBJECT")
    return body


def _call(executable: Path, session: str, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(executable), "-s=" + session, "run-code", code],
        capture_output=True, text=True, timeout=900, check=False,
    )


def _text(value: str | bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def store_script(code: str, nonce: str) -> str:
    return (
        "async page=>{if(page.__p7ChunkedCapture?.done===true)delete page.__p7ChunkedCapture;"
        "if(page.__p7ChunkedCapture)throw Error('CHUNK_STATE_OCCUPIED');"
        "const result=await (" + code + ")(page);"
        "page.__p7ChunkedCapture={nonce:" + json.dumps(nonce) + ",result};"
        "return {kind:'stored',nonce:" + json.dumps(nonce) + "};}"
    )


def decode_chunk(body: dict, nonce: str, expected_seq: int) -> bytes:
    need(body.get("kind") == "chunked_json_v1" and body.get("nonce") == nonce,
         "CHUNK_IDENTITY_MISMATCH")
    need(type(body.get("seq")) is int and body["seq"] == expected_seq,
         "CHUNK_SEQUENCE_MISMATCH")
    need(type(body.get("done")) is bool, "CHUNK_COMPLETION_INVALID")
    need(type(body.get("bytes")) is int and 0 < body["bytes"] <= CHUNK_LIMIT,
         "CHUNK_SIZE_INVALID")
    encoded = body.get("base64")
    need(isinstance(encoded, str) and len(encoded) <= (CHUNK_LIMIT * 4 // 3 + 8),
         "CHUNK_ENCODING_INVALID")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("CHUNK_ENCODING_INVALID") from exc
    need(len(data) == body["bytes"], "CHUNK_BYTE_LENGTH_MISMATCH")
    need(hashlib.sha256(data).hexdigest() == body.get("sha256"),
         "CHUNK_HASH_MISMATCH")
    return data


def collect_result(store: EvidenceStore, label: str, executable: Path,
                   session: str, code: str, transport_source: str) -> tuple[dict, dict, dict]:
    """Run a scene once, then stream its result. Any error keeps partial evidence."""
    nonce = hashlib.sha256((label + "\0" + code).encode()).hexdigest()
    wrapped = store_script(code, nonce)
    initial = _call(executable, session, wrapped)
    initial_ref = store.write("browser/" + label + "-cli.json", dict(
        stdout=initial.stdout, stderr=initial.stderr, exit_code=initial.returncode,
        failure=None if initial.returncode == 0 else "SCENE_INVOCATION_FAILED_NO_REPLAY",
        browser_script=code, browser_script_sha256=hashlib.sha256(code.encode()).hexdigest(),
        transport_script_sha256=hashlib.sha256(wrapped.encode()).hexdigest(),
    ))
    need(initial.returncode == 0, "SCENE_INVOCATION_FAILED_NO_REPLAY")
    start = parse_result(initial.stdout)
    need(start == {"kind": "stored", "nonce": nonce}, "CHUNK_STORE_ACK_INVALID")
    spool_name = "browser/" + label + "-transport.json"
    spool_path = store.path(spool_name)
    descriptor = os.open(spool_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    refs = []
    full = hashlib.sha256()
    total = 0
    done = False
    with os.fdopen(descriptor, "wb") as spool:
        for seq in range(1, MAX_CHUNKS + 1):
            request = transport_source.replace("__NONCE__", json.dumps(nonce))
            try:
                response = _call(executable, session, request)
            except subprocess.TimeoutExpired as exc:
                store.write("browser/" + label + f"-chunk-{seq:04d}.json", dict(
                    stdout=_text(exc.stdout), stderr=_text(exc.stderr), exit_code=None,
                    failure="CLI_TIMEOUT_NO_REPLAY",
                    transport_script_sha256=hashlib.sha256(request.encode()).hexdigest(),
                ))
                raise
            ref = store.write("browser/" + label + f"-chunk-{seq:04d}.json", dict(
                stdout=response.stdout, stderr=response.stderr, exit_code=response.returncode,
                transport_script_sha256=hashlib.sha256(request.encode()).hexdigest(),
            ))
            refs.append(ref)
            need(response.returncode == 0, "CHUNK_CALL_FAILED_NO_REPLAY")
            chunk = parse_result(response.stdout)
            data = decode_chunk(chunk, nonce, seq)
            total += len(data)
            need(total <= MAX_BYTES, "TRANSPORT_TOTAL_LIMIT")
            spool.write(data)
            full.update(data)
            done = chunk["done"]
            if done:
                break
        need(done, "TRANSPORT_CHUNK_LIMIT")
        spool.flush()
        os.fsync(spool.fileno())
    transport = dict(kind="chunked_json_v1", nonce=nonce, chunks=refs,
                     chunk_count=len(refs), bytes=total, sha256=full.hexdigest(),
                     spool=store.reference(spool_name))
    transport_ref = store.write("browser/" + label + "-transport-manifest.json", transport)
    with spool_path.open("r", encoding="utf-8") as source:
        observed = json.load(source)
    need(isinstance(observed, dict), "CLI_RESULT_NOT_OBJECT")
    return observed, initial_ref, transport_ref


def verify_transport(store: EvidenceStore, label: str, expected: dict,
                     observed: dict, expected_nonce: str) -> list[dict]:
    manifest = store.read(expected["path"])
    need(store.reference(expected["path"]) == expected, "TRANSPORT_MANIFEST_CHANGED")
    nonce = manifest["nonce"]
    need(nonce == expected_nonce, "TRANSPORT_NONCE_MISMATCH")
    refs = manifest["chunks"]
    need(len(refs) == manifest["chunk_count"] and 1 <= len(refs) <= MAX_CHUNKS,
         "TRANSPORT_CHUNK_COUNT")
    full = hashlib.sha256()
    total = 0
    for seq, ref in enumerate(refs, 1):
        need(ref["path"] == f"browser/{label}-chunk-{seq:04d}.json"
             and store.reference(ref["path"]) == ref, "TRANSPORT_CHUNK_CHANGED")
        row = store.read(ref["path"])
        need(row["exit_code"] == 0, "CHUNK_CALL_FAILED_NO_REPLAY")
        body = parse_result(row["stdout"])
        data = decode_chunk(body, nonce, seq)
        need(body["done"] == (seq == len(refs)), "CHUNK_COMPLETION_INVALID")
        total += len(data)
        full.update(data)
    spool = manifest["spool"]
    need(spool["path"] == f"browser/{label}-transport.json"
         and store.reference(spool["path"]) == spool
         and total == manifest["bytes"] == spool["bytes"]
         and full.hexdigest() == manifest["sha256"] == spool["sha256"],
         "TRANSPORT_FULL_HASH_MISMATCH")
    with store.path(spool["path"]).open("r", encoding="utf-8") as source:
        need(json.load(source) == observed, "TRANSPORT_OBSERVED_MISMATCH")
    return [expected, spool, *refs]
