"""One exact SimNow recovery after the owner's 2026-11-03 dependency restart.

No block is removed. This incident can spend only the original day's second
connection, under a new exclusive run and attempt claim, before native I/O.
"""

from datetime import UTC, datetime, timedelta
from functools import wraps
import os
from pathlib import Path
import re
import sqlite3
from typing import NamedTuple

from . import deployment_connection as io
from .ordinary_takeover import account_anchor, profile_binding
from .account_binding import _snapshot_account_proof
from .preparation_recovery import (
    _tables,
    _database_contents,
    _budget_authorizer,
    _exited,
)

DAY = "20261104"
OLD_PID = 28396
OLD_RUN = "85f46da16ea54d14b0b1e5f6959e8d80"
FAILURE_NAME = "failure-" + OLD_RUN + "-3114.json"
SOURCE_COMMIT = "c54da1cea37945c40959142565bda7ed89b8a67c"
SCHEMA = "simnow_infrastructure_interruption_recovery_v1"
NAME = "infrastructure-recovery-permit.private.json"
INTENT_NAME = "infrastructure-recovery-intent.private.json"
BLOCK = "CONTINUOUS_RECOVERY_REQUIRED"


def invalid():
    raise ValueError("INFRASTRUCTURE_RECOVERY_INVALID")


def fixed(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (
            ValueError,
            TypeError,
            KeyError,
            OSError,
            sqlite3.Error,
            ArithmeticError,
        ):
            invalid()

    return call


def _require(value):
    if not value:
        invalid()


def permit_required(settings, day):
    _require(day is None or day >= DAY)
    return day == DAY


def _path(settings):
    _require(
        settings.schema == 2
        and settings.mode == "trade"
        and settings.enabled is True
        and settings.account_takeover_pending is True
        and settings.account_recovery_hold is False
        and settings.account_profile is not None
        and not settings.ordinary_takeover_permit
        and not settings.preparation_recovery_permit
        and not settings.deployment_connection_permit
    )
    path = Path(settings.infrastructure_recovery_permit)
    _require(path.name == NAME and path.resolve() == path)
    io._private(path.parent, directory=True)
    return path


def _reference(item):
    _require(type(item) is dict and set(item) == {"path", "sha256"})
    value, digest = io.read(Path(item["path"]))
    _require(digest == item["sha256"])
    return value


def budget_binding(settings):
    path = io._private(settings.state_root / settings.account_id / "signals.sqlite")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        value = _tables(conn, settings.account_id)
    _require(
        dict(value["attempts"]).get(DAY) == 1
        and type(dict(value["attempts"]).get(DAY)) is int
        and dict(value["blocks"]).get(DAY) == BLOCK
    )
    return value


def _binding(settings):
    config, config_sha = io._config(settings)
    return dict(
        account=settings.account_id,
        config=config_sha,
        config_path=str(config),
        profile=profile_binding(settings),
        release=io.release_identity(settings.project_root),
        sdk=io.sdk_identity(settings.sdk_python),
    )


def _authority(source, authority):
    _require(callable(authority))
    actual = authority()
    _require(
        actual.get("active") is True
        and all(actual.get(k) == v for k, v in source["window"].items())
    )
    _require(
        actual.get("runtime_registry_sha256")
        == _reference(source["outage"])["runtime_registry_sha256"]
    )


def _time(grant, now):
    lo, hi = (datetime.fromisoformat(grant[k]) for k in ("issued_at", "expires_at"))
    _require(
        lo.tzinfo is not None
        and hi.tzinfo is not None
        and now.tzinfo is not None
        and timedelta(0) < hi - lo <= timedelta(seconds=120)
        and lo <= now < hi
    )
    sessions = grant["source"]["window"]["sessions"]
    active = [
        (datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"]))
        for s in sessions
    ]
    active = [(a, b) for a, b in active if a <= lo < b]
    _require(active and all(a <= now < hi <= b for a, b in active))
    return lo, hi


def _source(settings, source, *, anchor, exited=True):
    _require(
        set(source)
        == {
            "account_anchor",
            "budget",
            "window",
            "failure",
            "outage",
            "old_config",
            "old_process_identity",
            "old_pid",
            "old_run_id",
        }
    )
    _require(
        source["old_pid"] == OLD_PID
        and source["old_run_id"] == OLD_RUN
        and re.fullmatch(r"[0-9a-f]{64}", source["old_process_identity"]) is not None
    )
    if exited:
        _exited(OLD_PID, source["old_process_identity"])
    old = _reference(source["old_config"])
    _require(
        old["mode"] == "trade"
        and old["enabled"] is True
        and old.get("account_recovery_hold", False) is False
        and io.release_identity(Path(old["project_root"]))["commit"] == SOURCE_COMMIT
    )
    for key in (
        "account_id",
        "state_root",
        "state_project_root",
        "sdk_python",
        "account_profile",
    ):
        actual = getattr(settings, key)
        if key == "account_profile":
            actual = profile_binding(settings)
        elif isinstance(actual, Path):
            actual = str(actual)
        _require(old.get(key) == actual)
    failure = _reference(source["failure"])
    _require(
        Path(source["failure"]["path"])
        == settings.state_root / settings.account_id / FAILURE_NAME
    )
    folder = io._private(settings.state_root / settings.account_id, directory=True)
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        with os.scandir(fd) as entries:
            names = [
                entry.name
                for entry in entries
                if entry.name.startswith("failure-" + OLD_RUN + "-")
            ]
        current = folder.lstat()
        _require(
            names == [FAILURE_NAME]
            and (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino)
        )
    finally:
        os.close(fd)
    d = failure["diagnostic"]
    _require(
        failure["schema"] == "simnow_continuous_failure_v1"
        and failure["code"] == BLOCK
        and d["stage"] == "ACCOUNT_SNAPSHOT"
        and d["recovery_stage"] == "READY"
        and d["recovery_error_code"] == "RECOVERY_ERROR_UNCLASSIFIED"
        and d["dispatch"] is None
        and d["settlement"]["status"] == "CONFIRMED"
        and d["inventory"]["status"] == "READ_ONLY_COMPLETE"
        and len(d["inventory"]["queries"]) == 8
        and all(
            q["complete"] is True and q["timed_out"] is False
            for q in d["inventory"]["queries"]
        )
    )
    outage = _reference(source["outage"])
    _require(
        outage["schema"] == "simnow_operator_infrastructure_interruption_v1"
        and outage["source_run_id"] == OLD_RUN
        and outage["trading_day"] == DAY
        and outage["operator_confirmed"] is True
        and outage["services"] == ["postgresql", "redis"]
    )
    start, ready, failed = (
        datetime.fromisoformat(v)
        for v in (outage["stopped_at"], outage["recovered_at"], failure["at"])
    )
    _require(start <= ready <= failed <= ready + timedelta(seconds=120))
    _require(
        source["window"]["trading_day"] == DAY
        and set(source["window"]) == {"trading_day", "sessions", "session_facts_sha256"}
    )
    _require(
        dict(source["budget"]["attempts"]).get(DAY) == 1
        and dict(source["budget"]["blocks"]).get(DAY) == BLOCK
    )
    if anchor:
        _require(
            account_anchor(settings) == source["account_anchor"]
            and budget_binding(settings) == source["budget"]
        )
    from .account_binding import existing_account
    from .evidence import Evidence
    from .inventory import native_hash, number, project_readback
    from .native_portfolio import ReadJournal

    state = existing_account(settings.state_root, settings.account_id)
    _require(
        not state.positions
        and not state.unresolved_fill_ids
        and all(
            o.reconciled
            and o.status in {"LOCAL_ABORTED", "CANCELLED", "REJECTED", "FILLED"}
            for o in state.orders
        )
        and all(r.released for r in state.reservations)
    )
    folder = settings.state_root / settings.account_id
    with sqlite3.connect(
        (folder / "dispatch.sqlite").as_uri() + "?mode=ro", uri=True
    ) as conn:
        conn.execute("PRAGMA query_only=ON")
        _require(
            conn.execute("SELECT COUNT(*) FROM actions").fetchone() == (0,)
            and conn.execute("SELECT COUNT(*) FROM results").fetchone() == (0,)
        )
        import json

        _require(
            all(
                json.loads(raw)["kind"] == "disconnect"
                for (raw,) in conn.execute("SELECT payload FROM events")
            )
        )
    with sqlite3.connect(
        (folder / "signals.sqlite").as_uri() + "?mode=ro", uri=True
    ) as conn:
        conn.execute("PRAGMA query_only=ON")
        _require(
            conn.execute(
                "SELECT COUNT(*) FROM signals WHERE status='QUEUED'"
            ).fetchone()
            == (0,)
        )
    with sqlite3.connect(
        (folder / "native-evidence.sqlite").as_uri() + "?mode=ro", uri=True
    ) as conn:
        conn.execute("PRAGMA query_only=ON")
        _require(
            conn.execute("SELECT account FROM owner").fetchall()
            == [(settings.account_id,)]
        )
        row = conn.execute(
            "SELECT source,payload FROM snapshots ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    _require(row is not None)
    native = Evidence._decode(row[1])
    data = native.data
    _require(
        native.account_id == settings.account_id
        and native.trading_day == DAY
        and row[0]
        == native.source_id
        == "ctp-inventory:"
        + DAY
        + ":"
        + native_hash((native.account_id, DAY, data, native.at.isoformat()))
        and set(data) == {"funds", "positions", "orders", "trades"}
        and len(data["funds"]) == 1
        and data["funds"][0]["CurrencyID"] == "CNY"
        and not any(data[k] for k in ("positions", "orders", "trades"))
        and all(
            number(data["funds"][0][k]) == 0
            for k in ("CurrMargin", "FrozenMargin", "FrozenCommission")
        )
        and native.started_at <= native.at <= failed
        and failed - native.at <= timedelta(seconds=30)
    )
    journal = ReadJournal(folder / "dispatch.sqlite", settings.account_id)
    try:
        readback, _ = project_readback(
            native, (), journal, state, native.at + timedelta(seconds=30)
        )
        _require(readback.complete)
    finally:
        journal.close()


@fixed
def preflight_source(settings, source, now, expiry, authority):
    with _snapshot_account_proof(settings.state_root, settings.account_id):
        _path(settings)
        _source(settings, source, anchor=True, exited=False)
        _authority(source, authority)
        _time(
            dict(
                source=source, issued_at=now.isoformat(), expires_at=expiry.isoformat()
            ),
            now,
        )


@fixed
def issue(settings, *, source, intent_path, now, expires_at, authority, clock=None):
    with _snapshot_account_proof(settings.state_root, settings.account_id):
        path = _path(settings)
        _source(settings, source, anchor=True)
        intent, intent_sha = io.read(intent_path)
        _require(
            intent
            == dict(
                schema=SCHEMA,
                stage="START_REQUESTED",
                source=source,
                config_path=str(settings.source_config_path),
                config_sha256=settings.source_config_sha256,
                old_pid_exited=True,
            )
        )
        grant = dict(
            schema=SCHEMA,
            binding=_binding(settings),
            source=source,
            intent_path=str(intent_path),
            intent_sha256=intent_sha,
            issued_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
        )
    _authority(source, authority)
    _time(grant, clock() if clock else datetime.now(UTC))
    return io._new(path, grant)


def _checked_inner(settings, now, *, anchor=True):
    path = _path(settings)
    grant, sha = io.read(path)
    _require(
        set(grant)
        == {
            "schema",
            "binding",
            "source",
            "intent_path",
            "intent_sha256",
            "issued_at",
            "expires_at",
        }
        and grant["schema"] == SCHEMA
        and grant["binding"] == _binding(settings)
    )
    _time(grant, now)
    intent, digest = io.read(Path(grant["intent_path"]))
    _require(
        digest == grant["intent_sha256"]
        and intent
        == dict(
            schema=SCHEMA,
            stage="START_REQUESTED",
            source=grant["source"],
            config_path=str(settings.source_config_path),
            config_sha256=settings.source_config_sha256,
            old_pid_exited=True,
        )
    )
    _source(settings, grant["source"], anchor=anchor)
    return path, sha, grant


def _checked(settings, now, *, anchor=True):
    with _snapshot_account_proof(settings.state_root, settings.account_id):
        return _checked_inner(settings, now, anchor=anchor)


def _global(settings):
    from .supervisor import global_account_lock_directory

    return global_account_lock_directory() / (
        settings.account_id + "." + DAY + ".infrastructure-recovery.run-claim"
    )


def _owner(settings, path, sha, run_id):
    expected = dict(grant_sha256=sha, run_id=run_id, pid=os.getpid())
    for p in (path.with_name(path.name + ".run-claim"), _global(settings)):
        value, _ = io.read(p)
        _require(all(value.get(k) == v for k, v in expected.items()))


@fixed
def activate(settings, inbox, run_id, now, *, authority, clock=None):
    path, sha, grant = _checked(settings, now)
    _require(re.fullmatch(r"[0-9a-f]{32}", run_id) is not None and run_id != OLD_RUN)
    _authority(grant["source"], authority)
    _require(_tables(inbox.conn, settings.account_id) == grant["source"]["budget"])
    value = dict(grant_sha256=sha, run_id=run_id, pid=os.getpid())
    _time(grant, clock() if clock else datetime.now(UTC))
    io._new(_global(settings), value)
    io._new(path.with_name(path.name + ".run-claim"), value)


@fixed
def available(settings, inbox, run_id, day, now, *, authority):
    path, sha, grant = _checked(settings, now)
    _owner(settings, path, sha, run_id)
    _require(day == DAY and not path.with_name(path.name + ".attempt-claim").exists())
    _authority(grant["source"], authority)
    _require(_tables(inbox.conn, settings.account_id) == grant["source"]["budget"])
    return True


class ConnectionWindow(NamedTuple):
    settings: object
    grant_sha256: str
    run_id: str
    proof: dict


@fixed
def validate_connection(window, now, authority, *, clock=None):
    _require(type(window) is ConnectionWindow)
    with _snapshot_account_proof(
        window.settings.state_root, window.settings.account_id
    ):
        return _validate_connection(window, now, authority, clock=clock)


def _validate_connection(window, now, authority, *, clock=None):
    _require(type(window) is ConnectionWindow)
    settings = window.settings
    path, sha, grant = _checked_inner(settings, now, anchor=False)
    _require(sha == window.grant_sha256)
    _owner(settings, path, sha, window.run_id)
    claim, claim_sha = io.read(path.with_name(path.name + ".attempt-claim"))
    _require(
        claim_sha == window.proof["claim_sha256"]
        and claim
        == dict(grant_sha256=sha, run_id=window.run_id, pid=os.getpid(), day=DAY)
    )
    actual = account_anchor(settings)
    _require(
        all(
            actual[n] == v
            for n, v in grant["source"]["account_anchor"].items()
            if n != "signals.sqlite"
        )
    )
    _require(
        all(
            actual["signals.sqlite"][k]
            == grant["source"]["account_anchor"]["signals.sqlite"][k]
            for k in ("device", "inode")
        )
    )
    with sqlite3.connect(
        (settings.state_root / settings.account_id / "signals.sqlite").as_uri()
        + "?mode=ro",
        uri=True,
    ) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        contents, budget = _database_contents(conn), _tables(conn, settings.account_id)
    expected = {
        **grant["source"]["budget"],
        "attempts": [
            [d, 2 if d == DAY else c] for d, c in grant["source"]["budget"]["attempts"]
        ],
    }
    before = window.proof["contents"]
    _require(
        budget == expected
        and contents["schema_sha256"] == before["schema_sha256"]
        and {k: v for k, v in contents["tables"].items() if k != "attempts"}
        == {k: v for k, v in before["tables"].items() if k != "attempts"}
    )
    _authority(grant["source"], authority)
    _time(grant, clock() if clock else datetime.now(UTC))


@fixed
def consume(settings, inbox, run_id, day, now, *, authority, clock=None):
    path = _path(settings)
    _, sha = io.read(path)
    claim_sha = io._new(
        path.with_name(path.name + ".attempt-claim"),
        dict(grant_sha256=sha, run_id=run_id, pid=os.getpid(), day=day),
    )
    path, actual_sha, grant = _checked(settings, now)
    _require(day == DAY and sha == actual_sha)
    _owner(settings, path, sha, run_id)
    _authority(grant["source"], authority)
    conn = inbox.conn
    commit_started = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        _require(
            account_anchor(settings) == grant["source"]["account_anchor"]
            and _tables(conn, settings.account_id) == grant["source"]["budget"]
        )
        before = _database_contents(conn)
        conn.set_authorizer(_budget_authorizer)
        _require(
            conn.execute(
                "UPDATE attempts SET count=2 WHERE day=? AND count=1", (DAY,)
            ).rowcount
            == 1
        )
        expected = {
            **grant["source"]["budget"],
            "attempts": [
                [d, 2 if d == DAY else c]
                for d, c in grant["source"]["budget"]["attempts"]
            ],
        }
        after = _database_contents(conn)
        _require(
            _tables(conn, settings.account_id) == expected
            and before["schema_sha256"] == after["schema_sha256"]
            and {k: v for k, v in before["tables"].items() if k != "attempts"}
            == {k: v for k, v in after["tables"].items() if k != "attempts"}
        )
        _authority(grant["source"], authority)
        _time(grant, clock() if clock else datetime.now(UTC))
        commit_started = True
        conn.execute("COMMIT")
    except Exception:
        if not commit_started and conn.in_transaction:
            conn.execute("ROLLBACK")
        invalid()
    finally:
        conn.set_authorizer(None)
    window = ConnectionWindow(
        settings, sha, run_id, dict(claim_sha256=claim_sha, contents=before)
    )
    validate_connection(
        window, clock() if clock else datetime.now(UTC), authority, clock=clock
    )
    return 2, window
