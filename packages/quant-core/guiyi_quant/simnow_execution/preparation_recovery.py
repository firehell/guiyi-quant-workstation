"""One held adapter-preparation recovery; existing blocks and the daily cap survive.

Only the controller's frozen original facts are admitted. Activation is run-bound;
any attempt claim, including an unknown SQL outcome, permanently spends this grant.
No broker operation, retry, order permission or account initialization lives here.
"""
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from functools import wraps
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import NamedTuple

from . import deployment_connection as io
from .ordinary_takeover import account_anchor, profile_binding

DAY = "20261103"
SCHEMA = "simnow_adapter_preparation_recovery_v1"
RESUME_SCHEMA = "simnow_adapter_preparation_pre_native_resume_v1"
RESUME_DIRECTORY = "pre-native-resume"
PARENT_STATE_SCHEMA = "simnow_adapter_preparation_recovery_plan_v1"
INTENT_SCHEMA = "simnow_adapter_preparation_recovery_intent_v1"
NAME = "preparation-recovery-permit.private.json"
INTENT_NAME = "preparation-recovery-intent.private.json"
BLOCK = "CONTINUOUS_RECOVERY_REQUIRED"
sdk_identity = io.sdk_identity
read = io.read


class RecoveryError(ValueError):
    """Only fixed public codes cross this boundary."""


_diagnostic = ContextVar("simnow_preparation_guard", default=None)
_depth = ContextVar("simnow_preparation_guard_depth", default=0)
_EXCEPTION_CATEGORIES = frozenset({
    "RecoveryError", "ValueError", "TypeError", "KeyError", "OSError",
    "PermissionError", "FileNotFoundError", "FileExistsError", "ProcessLookupError",
    "OperationalError", "IntegrityError", "DatabaseError", "TimeoutExpired",
    "CalledProcessError",
})


def guard_diagnostic():
    """A detached fixed-code/boolean fact; no private values or exception text."""
    value = _diagnostic.get()
    if value is None:
        return dict(schema="simnow_preparation_guard_diagnostic_v1", operation="NOT_STARTED",
                    stage="NOT_STARTED", code="NOT_STARTED", exception_category="NONE", checks={})
    return {**value, "checks": dict(value["checks"])}


def _stage(stage, **checks):
    value = _diagnostic.get()
    if value is not None:
        value["stage"] = stage
        value["checks"].update({k: bool(v) for k, v in checks.items()})


def _require(stage, **checks):
    _stage(stage, **checks)
    if not all(type(v) is bool and v for v in checks.values()):
        invalid()


def invalid():
    raise RecoveryError("PREPARATION_RECOVERY_INVALID")


def fixed(function):
    @wraps(function)
    def call(*args, **kwargs):
        outer = _depth.get() == 0
        if outer:
            _diagnostic.set(dict(schema="simnow_preparation_guard_diagnostic_v1",
                                 operation=function.__name__, stage="START",
                                 code="IN_PROGRESS", exception_category="NONE", checks={}))
        token = _depth.set(_depth.get() + 1)
        try:
            result = function(*args, **kwargs)
            if outer:
                _diagnostic.get()["code"] = "PASSED"
            return result
        except Exception as error:
            value = _diagnostic.get()
            if value["exception_category"] == "NONE":
                name = type(error).__name__
                value["exception_category"] = name if name in _EXCEPTION_CATEGORIES else "UNCLASSIFIED"
            value["code"] = (str(error) if isinstance(error, RecoveryError)
                             and str(error) in {"PREPARATION_RECOVERY_INVALID", "PREPARATION_RECOVERY_CONSUMED"}
                             else "PREPARATION_RECOVERY_INVALID")
            if isinstance(error, RecoveryError):
                raise
            raise RecoveryError("PREPARATION_RECOVERY_INVALID") from None
        finally:
            _depth.reset(token)
    return call


def _new(path, value):
    try:
        return io._new(path, value)
    except io.PermitError as exc:
        if str(exc) == "DEPLOYMENT_CONNECTION_EXHAUSTED":
            raise RecoveryError("PREPARATION_RECOVERY_CONSUMED") from None
        invalid()


def release_identity(root):
    """Annotated exact clean identity; directory names are not a release source."""
    root = Path(root)
    if root.resolve() != root:
        invalid()

    def git(*args):
        result = subprocess.run(
            ["/usr/bin/git", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if result.returncode:
            invalid()
        return result.stdout.strip()

    tag = git("describe", "--exact-match", "--tags", "HEAD")
    commit = git("rev-parse", "HEAD")
    if (not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag)
        or not re.fullmatch(r"[a-f0-9]{40}", commit)
        or git("cat-file", "-t", tag) != "tag"
        or git("rev-parse", tag + "^{}") != commit
        or git("status", "--porcelain")):
        invalid()
    return dict(root=str(root), tag=tag, commit=commit)


def _path(settings):
    _stage("SETTINGS")
    if (settings.schema != 2 or settings.mode != "trade" or not settings.enabled
        or not getattr(settings, "account_takeover_pending", False)
        or not getattr(settings, "account_recovery_hold", False)
        or getattr(settings, "account_profile", None) is None
        or getattr(settings, "ordinary_takeover_permit", None)
        or getattr(settings, "deployment_connection_permit", None)):
        invalid()
    path = Path(settings.preparation_recovery_permit)
    if path.name != NAME or path.resolve(strict=False) != path:
        invalid()
    io._private(path.parent, directory=True)
    if path.parent.name == RESUME_DIRECTORY:
        _require("RESUME_DIRECTORY", one_layer=path.parent.parent.name != RESUME_DIRECTORY)
        io._private(path.parent.parent, directory=True)
    return path


def _global(settings, *, original=False):
    from .supervisor import global_account_lock_directory

    directory = global_account_lock_directory()
    io._private(directory, directory=True)
    if not re.fullmatch(r"[a-f0-9]{64}", settings.account_id):
        invalid()
    suffix = ("preparation-recovery-prenative-resume.run-claim"
              if not original and Path(settings.preparation_recovery_permit).parent.name == RESUME_DIRECTORY
              else "preparation-recovery.run-claim")
    return directory / (settings.account_id + "." + DAY + "." + suffix)


def _tables(conn, account):
    value = dict(
        identity=[list(row) for row in conn.execute("SELECT account,scope FROM identity")],
        attempts=[list(row) for row in conn.execute("SELECT day,count FROM attempts ORDER BY day")],
        blocks=[list(row) for row in conn.execute("SELECT day,code FROM blocks ORDER BY day")],
    )
    if len(value["identity"]) != 1 or value["identity"][0][0] != account:
        invalid()
    return value


def _database_contents(conn):
    """Canonical schema and complete row multisets inside the caller's transaction."""
    schema = conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    ).fetchall()
    tables = {}
    for kind, name, _, _ in schema:
        if kind != "table":
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        rows = [
            [{"blob": cell.hex()} if isinstance(cell, bytes) else cell for cell in row]
            for row in conn.execute("SELECT * FROM " + quoted)
        ]
        rows.sort(key=io._bytes)
        tables[name] = hashlib.sha256(io._bytes(rows)).hexdigest()
    return dict(schema_sha256=hashlib.sha256(io._bytes(schema)).hexdigest(), tables=tables)


def _budget_authorizer(action, table, column, database, trigger):
    # No trigger, view, function, DDL or auxiliary database can gain a side effect.
    # The connection is reserved exclusively for the fixed UPDATE and verification.
    if trigger is not None:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_UPDATE:
        return (sqlite3.SQLITE_OK
                if table == "attempts" and column == "count" and database == "main"
                else sqlite3.SQLITE_DENY)
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_TRANSACTION):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def budget_binding(settings):
    path = io._private(settings.state_root / settings.account_id / "signals.sqlite")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        result = _tables(conn, settings.account_id)
    _budget_shape(result)
    return result


def _budget_shape(value):
    if (set(value) != {"identity", "attempts", "blocks"}
        or dict(value["attempts"]).get(DAY) != 2
        or type(dict(value["attempts"]).get(DAY)) is not int
        or dict(value["blocks"]).get(DAY) != BLOCK):
        invalid()


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        invalid()
    return value


def _files(source):
    _stage("SOURCE_FACTS")
    for name in ("failure", "diagnostic", "release_receipt"):
        item = source[name]
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            invalid()
        _, sha = read(Path(item["path"]))
        _require("SOURCE_FACTS", **{name + "_matches": sha == _sha(item["sha256"])})


def _sessions(window):
    if (set(window) != {"trading_day", "sessions", "session_facts_sha256"}
        or window["trading_day"] != DAY):
        invalid()
    _sha(window["session_facts_sha256"])
    if type(window["sessions"]) is not list or not window["sessions"]:
        invalid()
    result = []
    for item in window["sessions"]:
        if type(item) is not dict or set(item) != {"start", "end"}:
            invalid()
        lo, hi = (datetime.fromisoformat(item[key]) for key in ("start", "end"))
        if lo.tzinfo is None or hi.tzinfo is None or not lo < hi:
            invalid()
        result.append((lo, hi))
    if result != sorted(set(result)):
        invalid()
    return result


def _time(grant, now):
    _stage("TIME_WINDOW")
    issued = datetime.fromisoformat(grant["issued_at"])
    expires = datetime.fromisoformat(grant["expires_at"])
    _require("TIME_WINDOW", timestamps_aware=all(t.tzinfo is not None for t in (now, issued, expires)))
    _require("TIME_WINDOW", current_time_valid=issued <= now < expires,
             lifetime_valid=issued < expires <= issued + timedelta(seconds=300))
    matching = [(lo, hi) for lo, hi in _sessions(grant["source"]["window"]) if lo <= issued < hi]
    _require("TIME_WINDOW", issued_in_authoritative_session=bool(matching))
    _require("TIME_WINDOW", expires_in_original_session=expires <= min(hi for lo, hi in matching),
             current_in_original_session=all(lo <= now < hi for lo, hi in matching))
    return issued, expires


def _authority(source, authority):
    _stage("AUTHORITY")
    if not callable(authority):
        invalid()
    actual = authority()
    window = source["window"]
    _require("AUTHORITY", active=actual.get("active") is True,
             **{k + "_matches": actual.get(k) == window[k] for k in window})


def _process_identity(pid):
    result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "lstart="],
                            capture_output=True, text=True, timeout=5, check=False)
    birth = result.stdout.strip()
    if result.returncode or not birth or "\n" in birth:
        invalid()
    return hashlib.sha256(f"{pid}:{birth}".encode()).hexdigest()


def _exited(pid, identity=None):
    _stage("OLD_PROCESS_EXIT")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        _stage("OLD_PROCESS_EXIT", old_pid_absent=True)
        return
    if identity is None:
        _require("OLD_PROCESS_EXIT", old_identity_exited=False)
    current = _process_identity(pid)
    _require("OLD_PROCESS_EXIT", old_identity_exited=current != identity)


def _intent(path, source, config, config_sha):
    _stage("INTENT")
    value, sha = read(path)
    resume = "pre_native_parent" in source
    expected = {"schema", "stage", "source", "config_path", "config_sha256",
                "old_run_id", "old_pid", "old_pid_exited", "created_at"}
    if resume:
        expected.add("old_process_identity")
    if (path.name != INTENT_NAME or set(value) != expected
        or value["schema"] != INTENT_SCHEMA or value["stage"] != "START_REQUESTED"
        or value["source"] != source or value["config_path"] != str(config)
        or value["config_sha256"] != config_sha or value["old_pid_exited"] is not True
        or not isinstance(value["old_run_id"], str)
        or re.fullmatch(r"[a-f0-9]{32}", value["old_run_id"]) is None
        or type(value["old_pid"]) is not int or value["old_pid"] <= 1
        or not resume and value["old_pid"] == os.getpid()
        or datetime.fromisoformat(value["created_at"]).tzinfo is None):
        invalid()
    identity = _sha(value["old_process_identity"]) if resume else None
    if resume:
        parent = _parent(settings=None, source=source, root=path.parent.parent)
        _require("PARENT_PROCESS_BINDING", old_run_matches=value["old_run_id"] == parent["run_id"],
                 old_pid_matches=value["old_pid"] == parent["pid"])
    _exited(value["old_pid"], identity)
    return value, sha


def _static(settings, config):
    _stage("STATIC_IDENTITY")
    path = _path(settings)
    config = Path(config)
    if config != Path(settings.source_config_path):
        invalid()
    _stage("CONFIG_IDENTITY")
    _, sha = read(config, limit=4096)
    _require("CONFIG_IDENTITY", config_sha_matches=sha == settings.source_config_sha256)
    _stage("ACCOUNT_PROFILE")
    profile = profile_binding(settings)
    _stage("RELEASE_IDENTITY")
    release = release_identity(settings.project_root)
    _stage("SDK_IDENTITY")
    sdk = sdk_identity(settings.sdk_python)
    return dict(account_id=settings.account_id, permit_path=str(path),
                config_path=str(config), config_sha256=sha,
                profile=profile, release=release, sdk=sdk, state_root=str(settings.state_root),
                account_recovery_hold=True)


def _reference(item, expected):
    _require("PARENT_REFERENCE", reference_shape=type(item) is dict and set(item) == {"path", "sha256"})
    _require("PARENT_REFERENCE", reference_path_matches=Path(item["path"]) == expected)
    value, sha = read(expected)
    _require("PARENT_REFERENCE", reference_sha_matches=sha == _sha(item["sha256"]))
    return value, sha


def _parent(settings, source, root):
    """Validate one immutable v1 parent; its expiry never authorizes another try."""
    _stage("PRE_NATIVE_PARENT")
    refs = source["pre_native_parent"]
    _require("PRE_NATIVE_PARENT", parent_shape=type(refs) is dict and set(refs) == {
        "grant", "intent", "state", "run_claim", "global_claim", "failure"})
    parent, parent_sha = _reference(refs["grant"], root / NAME)
    _require("PARENT_GRANT", parent_grant_shape=set(parent) == {"schema", "binding", "source", "intent_path", "intent_sha256", "issued_at", "expires_at"},
             original_schema=parent.get("schema") == SCHEMA,
             no_recursive_parent=type(parent.get("source")) is dict and set(parent["source"]) == {"account_anchor", "budget", "window", "failure", "diagnostic", "release_receipt"},
             parent_permit_matches=parent.get("binding", {}).get("permit_path") == str(root / NAME),
             parent_intent_matches=parent.get("intent_path") == str(root / INTENT_NAME),
             tested_parent_release=parent.get("binding", {}).get("release", {}).get("tag") == "v1.16.68")
    _require("PARENT_ATTEMPT_ABSENT", parent_attempt_absent=not os.path.lexists(root / (NAME + ".attempt-claim")))
    intent, intent_sha = _reference(refs["intent"], root / INTENT_NAME)
    _require("PARENT_INTENT", parent_intent_shape=set(intent) == {"schema", "stage", "source", "config_path", "config_sha256", "old_run_id", "old_pid", "old_pid_exited", "created_at"},
             parent_intent_sha_matches=intent_sha == parent["intent_sha256"],
             parent_source_matches=intent.get("source") == parent["source"],
             parent_intent_schema=intent.get("schema") == INTENT_SCHEMA,
             parent_intent_stage=intent.get("stage") == "START_REQUESTED",
             parent_config_matches=intent.get("config_path") == parent["binding"].get("config_path"),
             parent_config_sha_matches=intent.get("config_sha256") == parent["binding"].get("config_sha256"))
    claim, claim_sha = _reference(refs["run_claim"], root / (NAME + ".run-claim"))
    from .supervisor import global_account_lock_directory
    account = parent["binding"]["account_id"]
    _require("PARENT_ACCOUNT", valid_account=type(account) is str and re.fullmatch(r"[a-f0-9]{64}", account) is not None)
    global_path = global_account_lock_directory() / (account + "." + DAY + ".preparation-recovery.run-claim")
    global_claim, global_sha = _reference(refs["global_claim"], global_path)
    _require("PARENT_OWNER", parent_claim_shape=set(claim) == {
        "grant_sha256", "run_id", "pid", "at", "binding", "intent_sha256", "account_anchor"},
        local_global_bytes_match=claim_sha == global_sha,
        local_global_content_match=claim == global_claim,
        parent_grant_sha_matches=claim.get("grant_sha256") == parent_sha,
        parent_binding_matches=claim.get("binding") == parent["binding"],
        parent_claim_intent_matches=claim.get("intent_sha256") == parent["intent_sha256"],
        parent_claim_anchor_matches=claim.get("account_anchor") == parent["source"]["account_anchor"],
        parent_run_valid=type(claim.get("run_id")) is str and re.fullmatch(r"[a-f0-9]{32}", claim["run_id"]) is not None,
        parent_pid_valid=type(claim.get("pid")) is int and claim["pid"] > 1)
    state, _ = _reference(refs["state"], root / "state.private.json")
    _require("PARENT_STATE", state_shape=set(state) == {"schema", "stage", "result", "plan_hash", "at", "grant"},
             parent_state_schema=state.get("schema") == PARENT_STATE_SCHEMA,
             parent_state_verifying=state.get("stage") == "VERIFYING",
             parent_state_unknown=state.get("result") == "UNKNOWN",
             parent_state_grant_matches=state.get("grant") == parent_sha)
    _sha(state["plan_hash"])
    folder = Path(parent["binding"]["state_root"]) / account
    failure, _ = _reference(refs["failure"], folder / ("failure-" + claim["run_id"] + "-0.json"))
    diagnostic = failure.get("diagnostic", {})
    _require("PARENT_PRE_NATIVE_FAILURE", failure_schema=failure.get("schema") == "simnow_continuous_failure_v1",
             parent_failure_code=failure.get("code") == BLOCK,
             driver_absent=diagnostic.get("stage") == "DRIVER_UNAVAILABLE",
             recovery_not_started=diagnostic.get("recovery_stage") == "NOT_STARTED",
             no_dispatch=diagnostic.get("dispatch") is None,
             historical_unknown_preserved=diagnostic.get("recovery_error_code") == "RECOVERY_ERROR_UNCLASSIFIED")
    _require("PARENT_SOURCE", **{
        key + "_matches_parent": source.get(key) == parent["source"].get(key)
        for key in ("account_anchor", "budget", "window", "diagnostic", "release_receipt")},
        source_failure_matches_parent_reference=source.get("failure") == refs["failure"])
    _files(parent["source"])
    if settings is not None:
        _stage("PARENT_CURRENT_IDENTITY")
        _require("PARENT_CURRENT_IDENTITY", account_matches=account == settings.account_id,
                 state_root_matches=parent["binding"]["state_root"] == str(settings.state_root),
                 profile_matches=parent["binding"]["profile"] == profile_binding(settings),
                 sdk_matches=parent["binding"]["sdk"] == sdk_identity(settings.sdk_python),
                 held_parent=parent["binding"].get("account_recovery_hold") is True)
    return claim


def _source(settings, source, now, expires_at, *, authority=None):
    path = _path(settings)
    resume = path.parent.name == RESUME_DIRECTORY
    fields = {"account_anchor", "budget", "window", "failure", "diagnostic", "release_receipt"}
    if resume:
        fields.add("pre_native_parent")
    _require("SOURCE_SHAPE", source_shape=type(source) is dict and set(source) == fields)
    _stage("BUDGET_SHAPE")
    _budget_shape(source["budget"])
    _stage("ACCOUNT_ANCHOR")
    _require("ACCOUNT_ANCHOR", account_anchor_matches=account_anchor(settings) == source["account_anchor"])
    _stage("BUDGET_IDENTITY")
    _require("BUDGET_IDENTITY", budget_matches=budget_binding(settings) == source["budget"])
    _files(source)
    if resume:
        _parent(settings, source, path.parent.parent)
    binding = _static(settings, settings.source_config_path)
    grant = dict(source=source, issued_at=now.isoformat(), expires_at=expires_at.isoformat())
    _time(grant, now)
    if resume or authority is not None:
        _authority(source, authority)
    return binding


@fixed
def preflight_source(settings, source, now, expires_at, authority):
    """Read-only current source check; it never requires a running old PID to exit."""
    _source(settings, source, now, expires_at, authority=authority)
    _stage("PREFLIGHT_PASSED")
    # The fixed wrapper marks PASSED on return; make this returned fact identical.
    return {**guard_diagnostic(), "code": "PASSED"}


@fixed
def issue(settings, config_path, *, intent_path, source, now, expires_at, clock=None, authority=None):
    path = _path(settings)
    _require("CONFIG_PATH", config_path_matches=Path(config_path) == Path(settings.source_config_path))
    binding = _source(settings, source, now, expires_at, authority=authority)
    intent_path = Path(intent_path)
    _require("INTENT_PATH", intent_parent_matches=intent_path.parent == path.parent)
    _, intent_sha = _intent(intent_path, source, Path(config_path), binding["config_sha256"])
    grant = dict(schema=RESUME_SCHEMA if path.parent.name == RESUME_DIRECTORY else SCHEMA,
                 binding=binding, source=source, intent_path=str(intent_path),
                 intent_sha256=intent_sha, issued_at=now.isoformat(), expires_at=expires_at.isoformat())
    _time(grant, now)
    _time(grant, clock() if clock else datetime.now(UTC))
    _stage("GLOBAL_UNUSED")
    if os.path.lexists(_global(settings)):
        raise RecoveryError("PREPARATION_RECOVERY_CONSUMED")
    _stage("GRANT_CREATE")
    sha = _new(path, grant)
    _time(grant, clock() if clock else datetime.now(UTC))
    return sha


@fixed
def _checked(settings, now, *, anchor=True):
    path = _path(settings)
    grant, sha = read(path)
    _require("GRANT_SCHEMA", grant_schema_matches=grant.get("schema") == (
        RESUME_SCHEMA if path.parent.name == RESUME_DIRECTORY else SCHEMA))
    actual_static = _static(settings, settings.source_config_path)
    _require("STATIC_IDENTITY", **{k + "_matches": actual_static.get(k) == grant["binding"].get(k) for k in actual_static})
    if "pre_native_parent" in grant["source"]:
        _parent(settings, grant["source"], path.parent.parent)
    intent_path = Path(grant["intent_path"])
    if intent_path.parent != path.parent:
        invalid()
    _, intent_sha = _intent(intent_path, grant["source"], Path(settings.source_config_path), grant["binding"]["config_sha256"])
    if intent_sha != grant["intent_sha256"]:
        invalid()
    _time(grant, now)
    _files(grant["source"])
    if anchor:
        _stage("ACCOUNT_ANCHOR")
        _require("ACCOUNT_ANCHOR", account_anchor_matches=account_anchor(settings) == grant["source"]["account_anchor"])
    return path, sha, grant


def _owner(settings, path, sha, run_id):
    _stage("RUN_OWNER")
    grant, _ = read(path)
    intent, _ = read(Path(grant["intent_path"]))
    if run_id == intent["old_run_id"]:
        invalid()
    expected = dict(grant_sha256=sha, run_id=run_id, pid=os.getpid())
    run, _ = read(path.with_name(path.name + ".run-claim"))
    global_run, _ = read(_global(settings))
    _stage("RUN_OWNER", local_global_match=run == global_run,
           **{k + "_matches": run.get(k) == v for k, v in expected.items()})
    if run != global_run or any(run.get(k) != v for k, v in expected.items()):
        raise RecoveryError("PREPARATION_RECOVERY_CONSUMED")
    if "pre_native_parent" in grant["source"]:
        _require("RUN_PROCESS_BINDING", old_process_identity_matches=run.get("old_process_identity") == intent["old_process_identity"])
    return expected


@fixed
def activate(settings, inbox, run_id, now, *, clock=None, authority=None):
    if os.path.lexists(_global(settings)):
        raise RecoveryError("PREPARATION_RECOVERY_CONSUMED")
    path, sha, grant = _checked(settings, now)
    intent, _ = read(Path(grant["intent_path"]))
    if type(run_id) is not str or re.fullmatch(r"[a-f0-9]{32}", run_id) is None or run_id == intent["old_run_id"]:
        invalid()
    _require("BUDGET_IDENTITY", budget_matches=_tables(inbox.conn, settings.account_id) == grant["source"]["budget"])
    _authority(grant["source"], authority)
    fresh = clock() if clock else datetime.now(UTC)
    _time(grant, fresh)
    claim = dict(grant_sha256=sha, run_id=run_id, pid=os.getpid(), at=fresh.isoformat(),
                 binding=grant["binding"], intent_sha256=grant["intent_sha256"],
                 account_anchor=grant["source"]["account_anchor"])
    if "pre_native_parent" in grant["source"]:
        claim["old_process_identity"] = intent["old_process_identity"]
    # The global claim also spends restarts/recreated private grant directories.
    _stage("RUN_CLAIM_CREATE")
    _new(_global(settings), claim)
    _new(path.with_name(path.name + ".run-claim"), claim)
    _time(grant, clock() if clock else datetime.now(UTC))
    _authority(grant["source"], authority)
    _stage("RUN_ACTIVATED")


@fixed
def available(settings, inbox, run_id, day, now, *, authority=None):
    if day != DAY:
        return False
    path = _path(settings)
    if os.path.lexists(path.with_name(path.name + ".attempt-claim")):
        return False
    path, sha, grant = _checked(settings, now)
    _owner(settings, path, sha, run_id)
    _authority(grant["source"], authority)
    matches = _tables(inbox.conn, settings.account_id) == grant["source"]["budget"]
    _stage("BUDGET_IDENTITY", budget_matches=matches)
    return matches


class ConnectionWindow(NamedTuple):
    opens_at: datetime
    expires_at: datetime
    settings: object
    grant_sha256: str
    run_id: str
    consumption: dict | None = None


def _consumed_state(window, path, grant):
    """Only the acknowledged budget update may differ before factory/login."""
    _stage("CONSUMED_IDENTITY")
    proof = window.consumption
    _require("CONSUMED_IDENTITY", consumption_proof_present=type(proof) is dict)
    actual = account_anchor(window.settings)
    original = grant["source"]["account_anchor"]
    _require("CONSUMED_IDENTITY", original_three_ledgers_unchanged=all(
        actual.get(name) == value for name, value in original.items() if name != "signals.sqlite"),
        signals_device_unchanged=actual["signals.sqlite"]["device"] == original["signals.sqlite"]["device"],
        signals_inode_unchanged=actual["signals.sqlite"]["inode"] == original["signals.sqlite"]["inode"])
    claim, claim_sha = read(path.with_name(path.name + ".attempt-claim"))
    _require("CONSUMED_CLAIM", attempt_claim_sha_matches=claim_sha == proof["attempt_claim_sha256"],
             **{key + "_matches": claim.get(key) == value for key, value in dict(
                 grant_sha256=window.grant_sha256, run_id=window.run_id, pid=os.getpid(), day=DAY).items()})
    signals = io._private(window.settings.state_root / window.settings.account_id / "signals.sqlite")
    with sqlite3.connect(signals.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        contents = _database_contents(conn)
        budget = _tables(conn, window.settings.account_id)
    expected_budget = {**grant["source"]["budget"], "attempts": [
        [day, 3 if day == DAY else count] for day, count in grant["source"]["budget"]["attempts"]]}
    _require("CONSUMED_STATE", proof_budget_matches_grant=proof["budget"] == expected_budget,
             budget_exactly_third=budget == expected_budget,
             signals_schema_unchanged=contents["schema_sha256"] == proof["contents"]["schema_sha256"],
             nonattempt_tables_unchanged={k: v for k, v in contents["tables"].items() if k != "attempts"}
                 == {k: v for k, v in proof["contents"]["tables"].items() if k != "attempts"})


@fixed
def validate_connection(window, now, authority, *, clock=None):
    if not isinstance(window, ConnectionWindow):
        invalid()
    path, sha, grant = _checked(window.settings, now, anchor=False)
    if sha != window.grant_sha256:
        invalid()
    _owner(window.settings, path, sha, window.run_id)
    _consumed_state(window, path, grant)
    _authority(grant["source"], authority)
    # Re-sample after all filesystem, SQL and authority work; an entry timestamp
    # cannot authorize a factory/login after those checks exhaust the grant TTL.
    fresh = clock() if clock else datetime.now(UTC)
    _time(grant, fresh)
    _require("FINAL_CONNECTION_TIME", connection_time_valid=window.opens_at <= fresh < window.expires_at)


@fixed
def consume(settings, inbox, run_id, day, now, *, clock=None, authority=None):
    path = _path(settings)
    # Claim first: a guard failure, SQL failure or unknown commit is terminal too.
    # No controller may refund this immutable claim or the global activation claim.
    _stage("ATTEMPT_CLAIM_CREATE")
    _, grant_sha = read(path)
    attempt_sha = _new(path.with_name(path.name + ".attempt-claim"),
         dict(grant_sha256=grant_sha, run_id=run_id, pid=os.getpid(), day=day, at=now.isoformat()))
    path, sha, grant = _checked(settings, now)
    _owner(settings, path, sha, run_id)
    if day != DAY:
        invalid()
    _authority(grant["source"], authority)
    fresh = clock() if clock else datetime.now(UTC)
    _time(grant, fresh)
    _authority(grant["source"], authority)
    _stage("BUDGET_TRANSACTION")
    conn = inbox.conn
    commit_started = False
    authorized = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Close the preflight/transaction gap before hashing logical contents.
        if account_anchor(settings) != grant["source"]["account_anchor"]:
            invalid()
        before_contents = _database_contents(conn)
        if _tables(conn, settings.account_id) != grant["source"]["budget"]:
            invalid()
        conn.set_authorizer(_budget_authorizer)
        authorized = True
        result = conn.execute("UPDATE attempts SET count=3 WHERE day=? AND count=2", (DAY,))
        if result.rowcount != 1:
            invalid()
        expected = {**grant["source"]["budget"], "attempts": [
            [d, 3 if d == DAY else n] for d, n in grant["source"]["budget"]["attempts"]]}
        if _tables(conn, settings.account_id) != expected:
            invalid()
        after_contents = _database_contents(conn)
        if (after_contents["schema_sha256"] != before_contents["schema_sha256"]
            or {k: v for k, v in after_contents["tables"].items() if k != "attempts"}
            != {k: v for k, v in before_contents["tables"].items() if k != "attempts"}):
            invalid()
        _time(grant, clock() if clock else datetime.now(UTC))
        _authority(grant["source"], authority)
        commit_started = True
        conn.execute("COMMIT")
    except Exception:
        if not commit_started and conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        invalid()
    finally:
        if authorized:
            conn.set_authorizer(None)
    window = ConnectionWindow(*_time(grant, clock() if clock else datetime.now(UTC)), settings, sha, run_id,
                              dict(attempt_claim_sha256=attempt_sha, budget=expected, contents=before_contents))
    validate_connection(window, clock() if clock else datetime.now(UTC), authority, clock=clock)
    return 3, window
