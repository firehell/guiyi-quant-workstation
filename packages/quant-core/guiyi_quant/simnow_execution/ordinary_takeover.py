"""Exact first-run takeover using the unchanged ordinary daily connection budget.

This grants no extra attempt and never removes a block. Durable per-attempt
claims precede SignalInbox.attempt and every native factory/login operation.
"""

from dataclasses import asdict, is_dataclass
from datetime import datetime, UTC, timedelta
from functools import wraps
import hashlib
from pathlib import Path
import os
import re
import sqlite3
from typing import NamedTuple
from . import deployment_connection as io

SCHEMA = "simnow_ordinary_takeover_v2"
INTENT_SCHEMA = "simnow_trade_switch_plan_v6"
POLICY = "simnow_ordinary_next_session_v2"
NAME = "ordinary-takeover-permit.private.json"
release_identity = io.release_identity
sdk_identity = io.sdk_identity
read = io.read


def account_anchor(settings):
    for name in (
        "account.sqlite",
        "dispatch.sqlite",
        "signals.sqlite",
        "native-evidence.sqlite",
    ):
        path = settings.state_root / settings.account_id / name
        if any(
            Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
        ):
            invalid()
    return io.account_anchor(settings)


class TakeoverError(ValueError):
    pass


def invalid():
    raise TakeoverError("ORDINARY_TAKEOVER_INVALID")


def fixed(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except TakeoverError:
            raise
        except (
            ValueError,
            TypeError,
            KeyError,
            OSError,
            ArithmeticError,
            sqlite3.Error,
        ):
            invalid()

    return call


def _new(path, value):
    try:
        return io._new(path, value)
    except io.PermitError as exc:
        if str(exc) == "DEPLOYMENT_CONNECTION_EXHAUSTED":
            raise TakeoverError("ORDINARY_TAKEOVER_CONSUMED") from None
        invalid()


def profile_binding(settings):
    from .account_binding import existing_account
    from ..htdy_account_execution.codec import digest

    obj = settings.account_profile
    profile = asdict(obj) if is_dataclass(obj) else dict(obj)
    state = existing_account(settings.state_root, settings.account_id)
    expected = dict(
        profile_id="original_anchor_v1",
        account_id=settings.account_id,
        initial_readback_sha256=digest(state.initial_readback),
    )
    if profile != expected:
        invalid()
    return expected


def _path(settings):
    path = Path(settings.ordinary_takeover_permit)
    if path.name != NAME or path.resolve() != path:
        invalid()
    io._private(path.parent, directory=True)
    return path


def _tables(conn, account):
    if conn.execute("SELECT account FROM identity").fetchall() != [(account,)]:
        invalid()
    return dict(
        attempts=[
            list(r) for r in conn.execute("SELECT day,count FROM attempts ORDER BY day")
        ],
        blocks=[
            list(r) for r in conn.execute("SELECT day,code FROM blocks ORDER BY day")
        ],
    )


def budget_binding(settings, day):
    datetime.strptime(day, "%Y%m%d")
    path = io._private(settings.state_root / settings.account_id / "signals.sqlite")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        value = _tables(conn, settings.account_id)
    attempts = dict(value["attempts"])
    count = attempts.get(day, 0)
    if type(count) is not int or not 0 <= count < 3 or day in dict(value["blocks"]):
        invalid()
    return dict(value, initial_count=count)


class ConnectionWindow(NamedTuple):
    opens_at: datetime
    expires_at: datetime
    facts_sha256: str
    trading_day: str


def _fact_hash(value):
    return hashlib.sha256(
        io._bytes(
            {k: value[k] for k in ("trading_day", "sessions", "session_facts_sha256")}
        )
    ).hexdigest()


def validate_connection(window, now, authority):
    if not isinstance(window, ConnectionWindow) or not callable(authority):
        invalid()
    actual = authority()
    if (
        actual.get("trading_day") != window.trading_day
        or _fact_hash(actual) != window.facts_sha256
    ):
        invalid()
    connection_time(window, now)


def connection_time(window, now):
    if now.tzinfo is None or not window[0] <= now < window[1]:
        invalid()


def _window(frozen):
    value = frozen["window"]
    start, lo, hi = (
        datetime.fromisoformat(value[k])
        for k in ("session_start", "connect_after", "connect_until")
    )
    if (
        value["policy"] != POLICY
        or any(t.tzinfo is None for t in (start, lo, hi))
        or lo != start - timedelta(seconds=120)
        or hi != start + timedelta(seconds=120)
    ):
        invalid()
    datetime.strptime(value["trading_day"], "%Y%m%d")
    sessions = value.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        invalid()
    parsed = [
        (datetime.fromisoformat(w["start"]), datetime.fromisoformat(w["end"]))
        for w in sessions
    ]
    if (
        any(a.tzinfo is None or b.tzinfo is None or not a < b for a, b in parsed)
        or start not in {a for a, b in parsed}
        or not re.fullmatch("[a-f0-9]{64}", value.get("session_facts_sha256", ""))
    ):
        invalid()
    return lo, hi


def _retry_window(frozen, now):
    for item in frozen["window"]["sessions"]:
        lo = datetime.fromisoformat(item["start"]) - timedelta(seconds=120)
        hi = datetime.fromisoformat(item["end"])
        if lo <= now < hi:
            return lo, hi
    invalid()


def _authority(frozen, authority):
    if not callable(authority):
        invalid()
    current = authority()
    if any(
        current.get(k) != frozen["window"][k]
        for k in ("trading_day", "sessions", "session_facts_sha256")
    ):
        invalid()


@fixed
def binding(settings, config, window, now):
    path = _path(settings)
    if (
        settings.schema != 2
        or settings.mode != "trade"
        or not settings.enabled
        or not settings.account_takeover_pending
        or getattr(settings, "deployment_connection_permit", None)
    ):
        invalid()
    actual = Path(settings.source_config_path)
    _, config_sha = read(actual, limit=4096)
    if actual != Path(config) or config_sha != settings.source_config_sha256:
        invalid()
    result = dict(
        schema=SCHEMA,
        account_id=settings.account_id,
        profile=profile_binding(settings),
        permit_path=str(path),
        state_dir=str(path.parent),
        config_path=str(actual),
        config_sha256=config_sha,
        release=release_identity(settings.project_root),
        sdk=sdk_identity(settings.sdk_python),
        window=window,
        budget=budget_binding(settings, window["trading_day"]),
        planned_at=now.isoformat(),
    )
    _window(result)
    if now.tzinfo is None or not now < datetime.fromisoformat(window["connect_until"]):
        invalid()
    return result


@fixed
def issue(settings, frozen, plan_hash, intent_path, now, *, clock=None):
    path = _path(settings)
    intent_path = Path(intent_path)
    intent, _ = read(intent_path)
    if (
        intent_path.parent != path.parent
        or intent_path.name
        not in {"switch-intent.private.json", "ordinary-recovery-intent.private.json"}
        or intent.get("schema") != INTENT_SCHEMA
        or intent.get("window_policy") != POLICY
        or intent.get("stage") != "INSTALLED"
        or intent.get("plan_hash") != plan_hash
        or not re.fullmatch("[a-f0-9]{64}", plan_hash)
        or intent["snapshot"].get("ordinary_permit") != frozen
        or binding(
            settings,
            settings.source_config_path,
            frozen["window"],
            datetime.fromisoformat(frozen["planned_at"]),
        )
        != frozen
        or account_anchor(settings) != intent["snapshot"].get("connection_anchor")
    ):
        invalid()
    fresh = clock() if clock else datetime.now(UTC)
    lo, hi = _window(frozen)
    start = datetime.fromisoformat(frozen["window"]["session_start"])
    if (
        not datetime.fromisoformat(frozen["planned_at"])
        <= fresh
        < start - timedelta(seconds=660)
    ):
        invalid()
    value = dict(
        schema=SCHEMA,
        binding=frozen,
        plan_hash=plan_hash,
        intent_path=str(intent_path),
        issued_at=fresh.isoformat(),
        account_anchor=intent["snapshot"]["connection_anchor"],
    )
    sha = _new(path, value)
    if not (clock() if clock else datetime.now(UTC)) < start - timedelta(seconds=660):
        invalid()
    return sha


@fixed
def _checked(settings, now, *, initial, timing=True):
    path = _path(settings)
    grant, sha = read(path)
    frozen = grant["binding"]
    intent_path = Path(grant["intent_path"])
    intent, _ = read(intent_path)
    if (
        intent_path.parent != path.parent
        or intent_path.name
        not in {"switch-intent.private.json", "ordinary-recovery-intent.private.json"}
        or grant.get("schema") != SCHEMA
        or intent.get("schema") != INTENT_SCHEMA
        or intent.get("window_policy") != POLICY
        or intent.get("stage") not in {"START_REQUESTED", "VERIFYING", "COMPLETE"}
        or intent.get("plan_hash") != grant.get("plan_hash")
        or intent.get("ordinary_grant_sha256") != sha
        or intent["snapshot"].get("ordinary_permit") != frozen
        or intent["snapshot"].get("connection_anchor") != grant.get("account_anchor")
    ):
        invalid()
    _, cfgsha = read(Path(settings.source_config_path), limit=4096)
    if (
        cfgsha != frozen["config_sha256"]
        or cfgsha != settings.source_config_sha256
        or profile_binding(settings) != frozen["profile"]
        or release_identity(settings.project_root) != frozen["release"]
        or sdk_identity(settings.sdk_python) != frozen["sdk"]
    ):
        invalid()
    issued = datetime.fromisoformat(grant["issued_at"])
    lo, hi = _window(frozen)
    if not initial:
        hi = max(datetime.fromisoformat(x["end"]) for x in frozen["window"]["sessions"])
    if timing and not issued <= now < hi:
        invalid()
    if initial and account_anchor(settings) != grant["account_anchor"]:
        invalid()
    return path, sha, frozen, issued


@fixed
def permit_required(settings, authority_day):
    """Retire only after the bound authoritative day, never by civil expiry.

    A completed deployed first run is required before a later day can use the
    ordinary base rule. No claim, block or budget row is edited here.
    """
    datetime.strptime(authority_day, "%Y%m%d")
    path, sha, frozen, _ = _checked(
        settings, datetime.now(UTC), initial=False, timing=False
    )
    target = frozen["window"]["trading_day"]
    if authority_day <= target:
        return True
    grant, _ = read(path)
    intent, _ = read(Path(grant["intent_path"]))
    claim, _ = read(path.with_name(path.name + ".run-claim"))
    if (
        intent.get("stage") != "COMPLETE"
        or claim.get("grant_sha256") != sha
        or claim.get("run_id") != intent.get("run_id")
        or claim.get("pid") != intent.get("pid")
    ):
        invalid()
    return False


@fixed
def activate(settings, inbox, run_id, now, *, clock=None):
    path, sha, frozen, issued = _checked(settings, now, initial=True)
    if not re.fullmatch("[a-f0-9]{32}", run_id) or _tables(
        inbox.conn, settings.account_id
    ) != {k: frozen["budget"][k] for k in ("attempts", "blocks")}:
        invalid()
    fresh = clock() if clock else datetime.now(UTC)
    lo, hi = _window(frozen)
    if not issued <= fresh < hi:
        invalid()
    _new(
        path.with_name(path.name + ".run-claim"),
        dict(grant_sha256=sha, run_id=run_id, pid=os.getpid(), at=fresh.isoformat()),
    )
    if not issued <= (clock() if clock else datetime.now(UTC)) < hi:
        invalid()


@fixed
def consume(settings, inbox, run_id, day, now, *, clock=None, authority=None):
    # A claim with an unconfirmed SQL budget change is never skipped or refunded.
    path = _path(settings)
    prior = []
    for number in range(1, 4):
        p = path.with_name(path.name + f".attempt-{number}.claim")
        if not p.exists():
            break
        claim, _ = read(p)
        prior.append(claim)
    path, sha, frozen, issued = _checked(settings, now, initial=not prior)
    if day != frozen["window"]["trading_day"]:
        invalid()
    _authority(frozen, authority)
    run, _ = read(path.with_name(path.name + ".run-claim"))
    owner = dict(grant_sha256=sha, run_id=run_id, pid=os.getpid())
    if any(run.get(k) != v for k, v in owner.items()):
        raise TakeoverError("ORDINARY_TAKEOVER_CONSUMED")
    base = frozen["budget"]["initial_count"]
    for index, claim in enumerate(prior, 1):
        if any(
            claim.get(k) != v
            for k, v in {**owner, "attempt": base + index, "day": day}.items()
        ):
            invalid()
    actual = _tables(inbox.conn, settings.account_id)
    expected = dict(frozen["budget"]["attempts"])
    if prior or day in expected:
        expected[day] = base + len(prior)
    if actual != dict(
        attempts=[list(r) for r in sorted(expected.items())],
        blocks=frozen["budget"]["blocks"],
    ):
        invalid()
    attempt = base + len(prior) + 1
    if attempt > 3 or day in dict(actual["blocks"]):
        invalid()
    fresh = clock() if clock else datetime.now(UTC)
    window = _window(frozen) if not prior else _retry_window(frozen, fresh)
    connection_time(window, fresh)
    _authority(frozen, authority)
    fresh = clock() if clock else datetime.now(UTC)
    connection_time(window, fresh)
    _new(
        path.with_name(path.name + f".attempt-{len(prior) + 1}.claim"),
        dict(**owner, attempt=attempt, day=day, at=fresh.isoformat()),
    )
    connection_time(window, clock() if clock else datetime.now(UTC))
    try:
        if inbox.attempt(day) != attempt:
            invalid()
    except Exception:
        invalid()
    connection_time(window, clock() if clock else datetime.now(UTC))
    return attempt, ConnectionWindow(
        window[0], window[1], _fact_hash(frozen["window"]), day
    )
