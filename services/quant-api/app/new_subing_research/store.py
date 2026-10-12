"""Immutable local research packets, addressed only through an explicit SHA index."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

import fcntl

MAX_BYTES = 128 * 1024 * 1024
RUN_ID = re.compile(r"[0-9a-f]{64}\Z")
BLOCKED = {"DATA_INSUFFICIENT", "EXECUTION_FACTS_MISSING"}
STATUSES = {"COMPLETED", "DATA_INSUFFICIENT", "EXECUTION_FACTS_MISSING", "PENDING_UNFILLED", "SEGMENTED", "ROLLOVER_INTERRUPTED"}
DECIMAL_FIELDS = {"initial_cash", "final_equity", "account_return_pct", "max_drawdown_pct", "total_fees"}
COUNT_FIELDS = {"closed_trades", "ending_qty"}
REQUIRED_METADATA = {
    "product", "scenario", "status", "strategy_code", "formula_version", "profile_id",
    "risk_profile_version", "execution_profile_version", "code_revision", "requested_since",
    "requested_through", "input_snapshot_hash", "execution_facts_hash", "source",
    "auto_order", "case_parity", "oos_status",
}


class ResultStoreError(ValueError):
    """Frozen result is absent, malformed, unsafe, or inconsistent."""


def _safe_root(root: Path, *, create: bool = False) -> Path:
    root = Path(root)
    if not root.is_absolute():
        raise ResultStoreError("RESULT_ROOT_UNSAFE")
    # Inspect each component without resolving it: resolve() would conceal a link.
    for component in reversed((root, *root.parents)):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ResultStoreError("RESULT_ROOT_UNSAFE") from exc
        if not stat.S_ISDIR(mode):
            raise ResultStoreError("RESULT_ROOT_UNSAFE")
    if create:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ResultStoreError("RESULT_ROOT_UNSAFE") from exc
    return root


def _json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResultStoreError("RESULT_SCHEMA_INVALID") from exc
    if len(encoded) > MAX_BYTES:
        raise ResultStoreError("RESULT_TOO_LARGE")
    return encoded


def _parse(raw: bytes) -> dict[str, Any]:
    try:
        result = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError) as exc:
        raise ResultStoreError("RESULT_CORRUPT") from exc
    if not isinstance(result, dict):
        raise ResultStoreError("RESULT_CORRUPT")
    return result


def _read_file(path: Path) -> bytes:
    if path.is_symlink():
        raise ResultStoreError("RESULT_PATH_UNSAFE")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except (OSError, ValueError) as exc:
        raise ResultStoreError("RESULT_UNAVAILABLE") from exc
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ResultStoreError("RESULT_PATH_UNSAFE")
        if file_stat.st_size > MAX_BYTES:
            raise ResultStoreError("RESULT_TOO_LARGE")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read(MAX_BYTES + 1)
    finally:
        os.close(fd)


def _validate_packet(payload: dict[str, Any], *, published: bool) -> None:
    if payload.get("schema_version") != 1 or not isinstance(payload.get("metadata"), dict):
        raise ResultStoreError("RESULT_SCHEMA_INVALID")
    meta = payload["metadata"]
    if not REQUIRED_METADATA <= meta.keys() or meta["strategy_code"] != "new_subing_v1":
        raise ResultStoreError("RESULT_SCHEMA_INVALID")
    if meta["status"] not in STATUSES or meta["source"] != "historical_replay" or meta["auto_order"] is not False:
        raise ResultStoreError("RESULT_SCHEMA_INVALID")
    if meta["product"] not in {"AL", "RB", "TA"} or meta["scenario"] not in {"baseline", "double_commission", "double_slippage"}:
        raise ResultStoreError("RESULT_SCHEMA_INVALID")
    for key in ("formula_version", "profile_id", "risk_profile_version", "execution_profile_version", "code_revision", "requested_since", "requested_through"):
        if not isinstance(meta[key], str) or not meta[key]:
            raise ResultStoreError("RESULT_SCHEMA_INVALID")
    for key in ("input_snapshot_hash", "execution_facts_hash"):
        value = meta[key]
        if value is None and meta["status"] in BLOCKED:
            continue
        if not isinstance(value, str) or not RUN_ID.fullmatch(value):
            raise ResultStoreError("RESULT_SCHEMA_INVALID")
    if published and (not isinstance(meta.get("run_id"), str) or not RUN_ID.fullmatch(meta["run_id"])):
        raise ResultStoreError("RESULT_SCHEMA_INVALID")
    if not isinstance(payload.get("summary"), dict) or payload["summary"].get("status") != meta["status"]:
        raise ResultStoreError("RESULT_SCHEMA_INVALID")
    for key in ("decisions", "trades", "equity"):
        if not isinstance(payload.get(key), list) or not all(isinstance(item, dict) for item in payload[key]):
            raise ResultStoreError("RESULT_SCHEMA_INVALID")
    if not isinstance(payload.get("diagnostics"), dict):
        raise ResultStoreError("RESULT_SCHEMA_INVALID")
    summary = payload["summary"]
    if meta["status"] == "COMPLETED":
        required = DECIMAL_FIELDS | COUNT_FIELDS | {"annual_eligible"}
        if not required <= summary.keys():
            raise ResultStoreError("RESULT_SCHEMA_INVALID")
    for key in DECIMAL_FIELDS & summary.keys():
        value = summary[key]
        if value is None and meta["status"] != "COMPLETED":
            continue
        if not isinstance(value, str):
            raise ResultStoreError("RESULT_SCHEMA_INVALID")
        try:
            if not Decimal(value).is_finite():
                raise ResultStoreError("RESULT_SCHEMA_INVALID")
        except InvalidOperation as exc:
            raise ResultStoreError("RESULT_SCHEMA_INVALID") from exc
    for key in COUNT_FIELDS & summary.keys():
        if type(summary[key]) is not int or (key == "closed_trades" and summary[key] < 0):
            raise ResultStoreError("RESULT_SCHEMA_INVALID")
    if "annual_eligible" in summary and type(summary["annual_eligible"]) is not bool:
        raise ResultStoreError("RESULT_SCHEMA_INVALID")
    if meta["status"] in BLOCKED:
        if any(summary.get(key) is not None for key in ("final_equity", "account_return_pct", "max_drawdown_pct", "total_fees")):
            raise ResultStoreError("RESULT_SCHEMA_INVALID")
        if summary.get("annual_eligible", False) is not False:
            raise ResultStoreError("RESULT_SCHEMA_INVALID")
    _json_bytes(payload)


def _run_id(payload: dict[str, Any]) -> str:
    # Stable run identity fixes code, rule versions, product/window, and input facts.
    # A different calculation for the same identity must conflict at publication.
    metadata = payload["metadata"]
    identity: dict[str, Any] = {key: metadata[key] for key in sorted(REQUIRED_METADATA)}
    if metadata["status"] in BLOCKED:
        diagnostic = payload["diagnostics"]
        identity["gap"] = {key: diagnostic.get(key) for key in ("gap", "reason", "stage", "context", "status") if key in diagnostic}
    return hashlib.sha256(_json_bytes(identity)).hexdigest()


def _index(root: Path) -> dict[str, Any]:
    path = root / "index.json"
    if not path.exists() and not path.is_symlink():
        return {"schema_version": 1, "runs": []}
    doc = _parse(_read_file(path))
    if doc.get("schema_version") != 1 or not isinstance(doc.get("runs"), list):
        raise ResultStoreError("INDEX_CORRUPT")
    seen: set[str] = set()
    for entry in doc["runs"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("metadata"), dict):
            raise ResultStoreError("INDEX_CORRUPT")
        run_id = entry["metadata"].get("run_id")
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id) or run_id in seen or entry.get("file") != f"{run_id}.json" or not isinstance(entry.get("sha256"), str) or not RUN_ID.fullmatch(entry["sha256"]):
            raise ResultStoreError("INDEX_CORRUPT")
        seen.add(run_id)
    return doc


@contextmanager
def _writer_lock(root: Path) -> Iterator[None]:
    lock = root / ".index.lock"
    if lock.is_symlink():
        raise ResultStoreError("RESULT_PATH_UNSAFE")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise ResultStoreError("RESULT_PATH_UNSAFE") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ResultStoreError("RESULT_PATH_UNSAFE")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def publish_result(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Task-output writer only; exclusive packet plus atomic indexed publication."""
    if not isinstance(payload, dict):
        raise ResultStoreError("RESULT_SCHEMA_INVALID")
    _validate_packet(payload, published=False)
    run_id = _run_id(payload)
    if payload["metadata"].get("run_id") not in (None, run_id):
        raise ResultStoreError("RESULT_ID_MISMATCH")
    frozen = {**payload, "metadata": {**payload["metadata"], "run_id": run_id}}
    _validate_packet(frozen, published=True)
    raw = _json_bytes(frozen)
    root = _safe_root(root, create=True)
    with _writer_lock(root):
        index = _index(root)
        if any(e["metadata"]["run_id"] == run_id for e in index["runs"]):
            raise ResultStoreError("RESULT_EXISTS")
        dest = root / f"{run_id}.json"
        try:
            fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError as exc:
            raise ResultStoreError("RESULT_EXISTS") from exc
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        index["runs"].append({"metadata": frozen["metadata"], "file": dest.name, "sha256": hashlib.sha256(raw).hexdigest()})
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=root, prefix=".index-", delete=False) as stream:
                temp_name = stream.name
                stream.write(_json_bytes(index))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, root / "index.json")
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
    return frozen


def list_results(root: Path) -> list[dict[str, Any]]:
    root = _safe_root(root)
    if not root.exists():
        return []
    index = _index(root)
    # Verify listed packet before exposing even its summary metadata.
    return [read_result(root, entry["metadata"]["run_id"])["metadata"] for entry in index["runs"]]


def _read_entry(root: Path, run_id: str) -> tuple[dict[str, Any], str]:
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ResultStoreError("RUN_ID_INVALID")
    root = _safe_root(root)
    if not root.exists():
        raise ResultStoreError("RESULT_NOT_FOUND")
    entry = next((e for e in _index(root)["runs"] if e["metadata"]["run_id"] == run_id), None)
    if entry is None:
        raise ResultStoreError("RESULT_NOT_FOUND")
    raw = _read_file(root / entry["file"])
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ResultStoreError("RESULT_CORRUPT")
    payload = _parse(raw)
    _validate_packet(payload, published=True)
    if payload["metadata"] != entry["metadata"] or _run_id(payload) != run_id:
        raise ResultStoreError("RESULT_CORRUPT")
    return payload, entry["sha256"]


def read_result(root: Path, run_id: str) -> dict[str, Any]:
    return _read_entry(root, run_id)[0]


def page_result(root: Path, run_id: str, kind: str, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    if kind not in {"decisions", "trades", "equity"} or type(limit) is not int or not 1 <= limit <= 200:
        raise ResultStoreError("PAGE_INVALID")
    packet, sha = _read_entry(root, run_id)
    offset = 0
    if cursor is not None:
        if len(cursor) > 512:
            raise ResultStoreError("CURSOR_INVALID")
        try:
            doc = _parse(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if doc != {"run_id": run_id, "sha256": sha, "kind": kind, "offset": doc.get("offset")} or type(doc["offset"]) is not int or not 0 < doc["offset"] <= len(packet[kind]):
                raise ValueError()
            offset = doc["offset"]
        except (ValueError, KeyError, TypeError, binascii.Error, ResultStoreError) as exc:
            raise ResultStoreError("CURSOR_INVALID") from exc
    items = packet[kind][offset:offset + limit]
    next_offset = offset + len(items)
    next_cursor = None
    if next_offset < len(packet[kind]):
        next_cursor = base64.urlsafe_b64encode(_json_bytes({"run_id": run_id, "sha256": sha, "kind": kind, "offset": next_offset})).decode("ascii").rstrip("=")
    return {"items": items, "next_cursor": next_cursor, "run_id": run_id, "sha256": sha}
