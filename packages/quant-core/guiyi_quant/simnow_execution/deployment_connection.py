"""Owner-scoped 20261030 midday deployment connection, never a daily cap change.

A private grant is issued before START_REQUESTED; the durable intent's grant hash
makes it usable only afterwards. Run activation and connection attempt are two
exclusive, fsynced claims. Any failure leaves the claim consumed.
"""

from datetime import datetime, UTC, timedelta
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from zoneinfo import ZoneInfo

DAY = "20261030"
POLICY = "simnow_midday_deployment_window_v1"
SCHEMA = "simnow_midday_one_connection_v1"
INTENT_SCHEMA = "simnow_trade_switch_plan_v3"
NAME = "deployment-connection-permit.private.json"
ZONE = ZoneInfo("Asia/Shanghai")


class PermitError(ValueError):
    """Fixed codes only."""


def invalid():
    raise PermitError("DEPLOYMENT_CONNECTION_INVALID")


def _fixed(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except PermitError:
            raise
        except (KeyError, TypeError, ValueError, OSError, ArithmeticError):
            invalid()

    return call


def _time(frozen, issued, now, *, connecting=False):
    pm = datetime.fromisoformat(frozen["pm_session_start"])
    if (
        now.tzinfo is None
        or now.astimezone(ZONE).strftime("%Y%m%d") != DAY
        or not issued <= now < datetime.fromisoformat(frozen["connection_expires_at"])
        or (connecting and now < pm - timedelta(seconds=120))
    ):
        invalid()
    return pm - timedelta(seconds=120), datetime.fromisoformat(
        frozen["connection_expires_at"]
    )


def connection_time(window, now):
    if not window[0] <= now < window[1]:
        invalid()


def _private(path, *, directory=False):
    path = Path(path)
    try:
        info = path.stat()
        if (
            not path.is_absolute()
            or path.resolve() != path
            or path.is_symlink()
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or not (
                stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
            )
            or (not directory and info.st_nlink != 1)
        ):
            invalid()
    except OSError:
        invalid()
    return path


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            invalid()
        value[key] = item
    return value


def read(path, *, limit=32 * 1024 * 1024):
    path = _private(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            raw = os.read(fd, limit + 1)
        finally:
            os.close(fd)
        if not raw or len(raw) > limit:
            invalid()
        value = json.loads(raw, object_pairs_hook=_pairs)
        if type(value) is not dict:
            invalid()
        return value, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, TypeError):
        invalid()


def _bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _new(path, value):
    _private(path.parent, directory=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except FileExistsError:
        raise PermitError("DEPLOYMENT_CONNECTION_EXHAUSTED") from None
    except OSError:
        # Never unlink a partially written or unconfirmed claim.
        invalid()
    return hashlib.sha256(_bytes(value)).hexdigest()


def release_identity(root):
    root = Path(root)
    tag = root.name.removeprefix("release-")
    if root.resolve() != root or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        invalid()

    def run(*args):
        try:
            result = subprocess.run(
                ["/usr/bin/git", "-c", "core.fsmonitor=false", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            invalid()
        if result.returncode:
            invalid()
        return result.stdout.strip()

    commit = run("rev-parse", tag + "^{}")
    if (
        not re.fullmatch(r"[a-f0-9]{40}", commit)
        or run("cat-file", "-t", tag) != "tag"
        or run("rev-parse", "HEAD") != commit
        or run("status", "--porcelain")
    ):
        invalid()
    return dict(root=str(root), tag=tag, commit=commit)


def sdk_identity(path):
    path = Path(path).resolve(strict=True)
    info = path.stat()
    return dict(
        device=info.st_dev,
        inode=info.st_ino,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _config(settings):
    config = Path(settings.source_config_path)
    _, sha = read(config, limit=4096)
    if sha != settings.source_config_sha256:
        invalid()
    return config, sha


def _path(settings):
    path = Path(settings.deployment_connection_permit)
    if path.name != NAME or path.resolve(strict=False) != path:
        invalid()
    _private(path.parent, directory=True)
    return path


@_fixed
def binding(settings, config, pm_start, now):
    if settings.schema != 2 or settings.mode != "trade" or not settings.enabled:
        invalid()
    path = _path(settings)
    actual, sha = _config(settings)
    if (
        actual != Path(config)
        or now.tzinfo is None
        or pm_start.tzinfo is None
        or pm_start.astimezone(ZONE).strftime("%Y%m%d") != DAY
        or not 12 <= pm_start.astimezone(ZONE).hour < 18
    ):
        invalid()
    return dict(
        schema=SCHEMA,
        account_id=settings.account_id,
        trading_day=DAY,
        permit_path=str(path),
        state_dir=str(path.parent),
        config_path=str(actual),
        config_sha256=sha,
        release=release_identity(settings.project_root),
        sdk=sdk_identity(settings.sdk_python),
        pm_session_start=pm_start.isoformat(),
        connection_expires_at=(pm_start + timedelta(seconds=120)).isoformat(),
        planned_at=now.isoformat(),
    )


@_fixed
def issue(settings, frozen, plan_hash, intent_path, now, *, clock=None):
    path = _path(settings)
    intent_path = Path(intent_path)
    pm = datetime.fromisoformat(frozen["pm_session_start"])
    current = binding(
        settings,
        settings.source_config_path,
        pm,
        datetime.fromisoformat(frozen["planned_at"]),
    )
    intent, _ = read(intent_path)
    if (
        current != frozen
        or path.parent != intent_path.parent
        or intent_path.name != "switch-intent.private.json"
        or intent.get("schema") != INTENT_SCHEMA
        or intent.get("stage") != "INSTALLED"
        or intent.get("plan_hash") != plan_hash
        or intent.get("window_policy") != POLICY
        or intent["snapshot"].get("connection_permit") != frozen
        or not re.fullmatch(r"[a-f0-9]{64}", plan_hash)
        or now.astimezone(ZONE).strftime("%Y%m%d") != DAY
        or not datetime.fromisoformat(frozen["planned_at"])
        <= now
        <= pm - timedelta(seconds=660)
    ):
        invalid()
    fresh = clock() if clock else datetime.now(UTC)
    if (
        not datetime.fromisoformat(frozen["planned_at"])
        <= fresh
        <= pm - timedelta(seconds=660)
    ):
        invalid()
    return _new(
        path,
        dict(
            schema=SCHEMA,
            binding=frozen,
            plan_hash=plan_hash,
            intent_path=str(intent_path),
            issued_at=fresh.isoformat(),
        ),
    )


@_fixed
def _checked(settings, now):
    if settings.schema != 2 or settings.mode != "trade" or not settings.enabled:
        invalid()
    path = _path(settings)
    grant, sha = read(path, limit=64 * 1024)
    frozen = grant["binding"]
    intent_path = Path(grant["intent_path"])
    if (
        intent_path.parent != path.parent
        or intent_path.name != "switch-intent.private.json"
    ):
        invalid()
    intent, _ = read(intent_path)
    pm = datetime.fromisoformat(frozen["pm_session_start"])
    if (
        grant.get("schema") != SCHEMA
        or intent.get("schema") != INTENT_SCHEMA
        or intent.get("stage") not in {"START_REQUESTED", "VERIFYING", "COMPLETE"}
        or intent.get("plan_hash") != grant.get("plan_hash")
        or intent.get("window_policy") != POLICY
        or intent.get("connection_grant_sha256") != sha
        or intent["snapshot"].get("connection_permit") != frozen
        or binding(
            settings,
            settings.source_config_path,
            pm,
            datetime.fromisoformat(frozen["planned_at"]),
        )
        != frozen
        or now.astimezone(ZONE).strftime("%Y%m%d") != DAY
        or not datetime.fromisoformat(grant["issued_at"])
        <= now
        < datetime.fromisoformat(frozen["connection_expires_at"])
    ):
        invalid()
    return path, sha, frozen, datetime.fromisoformat(grant["issued_at"])


def attempts(inbox, day):
    row = inbox.conn.execute(
        "SELECT count FROM attempts WHERE day=?", (day,)
    ).fetchone()
    count = row[0] if row else 0
    if type(count) is not int or not 0 <= count <= 3:
        invalid()
    return count


def _budget(inbox):
    if inbox.blocked(DAY) or attempts(inbox, DAY) != 3:
        invalid()


@_fixed
def activate(settings, inbox, run_id, now, *, clock=None):
    _budget(inbox)
    path, sha, frozen, issued = _checked(settings, now)
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        invalid()
    fresh = clock() if clock else datetime.now(UTC)
    _time(frozen, issued, fresh)
    _budget(inbox)
    _new(
        path.with_name(path.name + ".run-claim"),
        dict(grant_sha256=sha, run_id=run_id, pid=os.getpid(), at=fresh.isoformat()),
    )
    _time(frozen, issued, clock() if clock else datetime.now(UTC))


@_fixed
def consume(settings, inbox, run_id, day, now, *, clock=None):
    if day != DAY:
        invalid()
    _budget(inbox)
    path, sha, frozen, issued = _checked(settings, now)
    claim, _ = read(path.with_name(path.name + ".run-claim"))
    if (
        claim.get("grant_sha256") != sha
        or claim.get("run_id") != run_id
        or claim.get("pid") != os.getpid()
    ):
        raise PermitError("DEPLOYMENT_CONNECTION_EXHAUSTED")
    fresh = clock() if clock else datetime.now(UTC)
    window = _time(frozen, issued, fresh, connecting=True)
    _budget(inbox)
    _new(
        path.with_name(path.name + ".attempt-claim"),
        dict(grant_sha256=sha, run_id=run_id, pid=os.getpid(), at=fresh.isoformat()),
    )
    connection_time(window, clock() if clock else datetime.now(UTC))
    return window
