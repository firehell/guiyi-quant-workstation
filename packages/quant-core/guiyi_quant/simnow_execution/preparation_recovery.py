"""One held adapter-preparation recovery; existing blocks and the daily cap survive.

Only the controller's frozen original facts are admitted. Activation is run-bound;
any attempt claim, including an unknown SQL outcome, permanently spends this grant.
No broker operation, retry, order permission or account initialization lives here.
"""
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
INTENT_SCHEMA = "simnow_adapter_preparation_recovery_intent_v1"
NAME = "preparation-recovery-permit.private.json"
INTENT_NAME = "preparation-recovery-intent.private.json"
BLOCK = "CONTINUOUS_RECOVERY_REQUIRED"
sdk_identity = io.sdk_identity
read = io.read


class RecoveryError(ValueError):
    """Only fixed public codes cross this boundary."""


def invalid():
    raise RecoveryError("PREPARATION_RECOVERY_INVALID")


def fixed(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except RecoveryError:
            raise
        except Exception:
            invalid()
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
    return path


def _global(settings):
    from .supervisor import global_account_lock_directory

    directory = global_account_lock_directory()
    io._private(directory, directory=True)
    if not re.fullmatch(r"[a-f0-9]{64}", settings.account_id):
        invalid()
    return directory / (settings.account_id + "." + DAY + ".preparation-recovery.run-claim")


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
    for name in ("failure", "diagnostic", "release_receipt"):
        item = source[name]
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            invalid()
        _, sha = read(Path(item["path"]))
        if sha != _sha(item["sha256"]):
            invalid()


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
    issued = datetime.fromisoformat(grant["issued_at"])
    expires = datetime.fromisoformat(grant["expires_at"])
    if (now.tzinfo is None or issued.tzinfo is None or expires.tzinfo is None
        or not issued <= now < expires or not issued < expires <= issued + timedelta(seconds=300)):
        invalid()
    matching = [(lo, hi) for lo, hi in _sessions(grant["source"]["window"]) if lo <= issued < hi]
    if not matching or not expires <= min(hi for lo, hi in matching) or not all(lo <= now < hi for lo, hi in matching):
        invalid()
    return issued, expires


def _authority(source, authority):
    if not callable(authority):
        invalid()
    actual = authority()
    window = source["window"]
    if (actual.get("active") is not True
        or any(actual.get(k) != window[k] for k in window)):
        invalid()


def _intent(path, source, config, config_sha):
    value, sha = read(path)
    expected = {"schema", "stage", "source", "config_path", "config_sha256",
                "old_run_id", "old_pid", "old_pid_exited", "created_at"}
    if (path.name != INTENT_NAME or set(value) != expected
        or value["schema"] != INTENT_SCHEMA or value["stage"] != "START_REQUESTED"
        or value["source"] != source or value["config_path"] != str(config)
        or value["config_sha256"] != config_sha or value["old_pid_exited"] is not True
        or not isinstance(value["old_run_id"], str)
        or re.fullmatch(r"[a-f0-9]{32}", value["old_run_id"]) is None
        or type(value["old_pid"]) is not int or value["old_pid"] <= 1
        or value["old_pid"] == os.getpid()
        or datetime.fromisoformat(value["created_at"]).tzinfo is None):
        invalid()
    try:
        os.kill(value["old_pid"], 0)
    except ProcessLookupError:
        pass
    else:
        invalid()
    return value, sha


def _static(settings, config):
    path = _path(settings)
    config = Path(config)
    if config != Path(settings.source_config_path):
        invalid()
    _, sha = read(config, limit=4096)
    if sha != settings.source_config_sha256:
        invalid()
    return dict(account_id=settings.account_id, permit_path=str(path),
                config_path=str(config), config_sha256=sha,
                profile=profile_binding(settings), release=release_identity(settings.project_root),
                sdk=sdk_identity(settings.sdk_python), state_root=str(settings.state_root),
                account_recovery_hold=True)


@fixed
def issue(settings, config_path, *, intent_path, source, now, expires_at, clock=None):
    path = _path(settings)
    if type(source) is not dict or set(source) != {"account_anchor", "budget", "window", "failure", "diagnostic", "release_receipt"}:
        invalid()
    _budget_shape(source["budget"])
    if account_anchor(settings) != source["account_anchor"] or budget_binding(settings) != source["budget"]:
        invalid()
    _files(source)
    binding = _static(settings, config_path)
    intent_path = Path(intent_path)
    if intent_path.parent != path.parent:
        invalid()
    _, intent_sha = _intent(intent_path, source, Path(config_path), binding["config_sha256"])
    grant = dict(schema=SCHEMA, binding=binding, source=source, intent_path=str(intent_path),
                 intent_sha256=intent_sha, issued_at=now.isoformat(), expires_at=expires_at.isoformat())
    _time(grant, now)
    _time(grant, clock() if clock else datetime.now(UTC))
    if _global(settings).exists():
        raise RecoveryError("PREPARATION_RECOVERY_CONSUMED")
    sha = _new(path, grant)
    _time(grant, clock() if clock else datetime.now(UTC))
    return sha


@fixed
def _checked(settings, now, *, anchor=True):
    path = _path(settings)
    grant, sha = read(path)
    if grant.get("schema") != SCHEMA or _static(settings, settings.source_config_path) != grant["binding"]:
        invalid()
    intent_path = Path(grant["intent_path"])
    if intent_path.parent != path.parent:
        invalid()
    _, intent_sha = _intent(intent_path, grant["source"], Path(settings.source_config_path), grant["binding"]["config_sha256"])
    if intent_sha != grant["intent_sha256"]:
        invalid()
    _time(grant, now)
    _files(grant["source"])
    if anchor and account_anchor(settings) != grant["source"]["account_anchor"]:
        invalid()
    return path, sha, grant


def _owner(settings, path, sha, run_id):
    grant, _ = read(path)
    intent, _ = read(Path(grant["intent_path"]))
    if run_id == intent["old_run_id"]:
        invalid()
    expected = dict(grant_sha256=sha, run_id=run_id, pid=os.getpid())
    run, _ = read(path.with_name(path.name + ".run-claim"))
    global_run, _ = read(_global(settings))
    if run != global_run or any(run.get(k) != v for k, v in expected.items()):
        raise RecoveryError("PREPARATION_RECOVERY_CONSUMED")
    return expected


@fixed
def activate(settings, inbox, run_id, now, *, clock=None, authority=None):
    if _global(settings).exists():
        raise RecoveryError("PREPARATION_RECOVERY_CONSUMED")
    path, sha, grant = _checked(settings, now)
    intent, _ = read(Path(grant["intent_path"]))
    if type(run_id) is not str or re.fullmatch(r"[a-f0-9]{32}", run_id) is None or run_id == intent["old_run_id"]:
        invalid()
    if _tables(inbox.conn, settings.account_id) != grant["source"]["budget"]:
        invalid()
    _authority(grant["source"], authority)
    fresh = clock() if clock else datetime.now(UTC)
    _time(grant, fresh)
    claim = dict(grant_sha256=sha, run_id=run_id, pid=os.getpid(), at=fresh.isoformat(),
                 binding=grant["binding"], intent_sha256=grant["intent_sha256"],
                 account_anchor=grant["source"]["account_anchor"])
    # The global claim also spends restarts/recreated private grant directories.
    _new(_global(settings), claim)
    _new(path.with_name(path.name + ".run-claim"), claim)
    _time(grant, clock() if clock else datetime.now(UTC))
    _authority(grant["source"], authority)


@fixed
def available(settings, inbox, run_id, day, now, *, authority=None):
    if day != DAY:
        return False
    path = _path(settings)
    if path.with_name(path.name + ".attempt-claim").exists():
        return False
    path, sha, grant = _checked(settings, now)
    _owner(settings, path, sha, run_id)
    _authority(grant["source"], authority)
    return _tables(inbox.conn, settings.account_id) == grant["source"]["budget"]


class ConnectionWindow(NamedTuple):
    opens_at: datetime
    expires_at: datetime
    settings: object
    grant_sha256: str
    run_id: str


@fixed
def validate_connection(window, now, authority):
    if not isinstance(window, ConnectionWindow):
        invalid()
    path, sha, grant = _checked(window.settings, now, anchor=False)
    if sha != window.grant_sha256:
        invalid()
    _owner(window.settings, path, sha, window.run_id)
    _authority(grant["source"], authority)
    if not window.opens_at <= now < window.expires_at:
        invalid()


@fixed
def consume(settings, inbox, run_id, day, now, *, clock=None, authority=None):
    path = _path(settings)
    # Claim first: a guard failure, SQL failure or unknown commit is terminal too.
    # No controller may refund this immutable claim or the global activation claim.
    _, grant_sha = read(path)
    _new(path.with_name(path.name + ".attempt-claim"),
         dict(grant_sha256=grant_sha, run_id=run_id, pid=os.getpid(), day=day, at=now.isoformat()))
    path, sha, grant = _checked(settings, now)
    _owner(settings, path, sha, run_id)
    if day != DAY:
        invalid()
    _authority(grant["source"], authority)
    fresh = clock() if clock else datetime.now(UTC)
    _time(grant, fresh)
    _authority(grant["source"], authority)
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
    window = ConnectionWindow(*_time(grant, clock() if clock else datetime.now(UTC)), settings, sha, run_id)
    validate_connection(window, clock() if clock else datetime.now(UTC), authority)
    return 3, window
