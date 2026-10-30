"""Fail-closed one-shot SimNow switching coordinator.

The default CLI is read-only; --apply consumes a short-lived exact plan once.
All native operations use pinned paths and discrete subprocess arguments. No
credential store or broker adapter is constructed by this tool.
"""

from __future__ import annotations

import argparse
from collections import namedtuple
from dataclasses import replace
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import importlib.util
import plistlib
import re
import signal
import sqlite3
import subprocess
import sys

from datetime import datetime, UTC, date, timedelta

sys.dont_write_bytecode = True

SCHEMA = "simnow_trade_switch_plan_v7"
POLICY = "simnow_night_only_deployment_window_v1"
MIDDAY_POLICY = "simnow_midday_deployment_window_v1"
ORDINARY_POLICY = "simnow_ordinary_next_session_v2"
LABEL = "com.guiyi.quant-simnow"
CalendarFacts = namedtuple(
    "CalendarFacts", "trade_date is_trading_day has_night_session"
)
STAGES = frozenset(
    {
        "INTENT",
        "STOP_REQUESTED",
        "STOPPED",
        "INSTALLING",
        "INSTALLED",
        "START_REQUESTED",
        "VERIFYING",
        "COMPLETE",
        "RESTORE_REQUESTED",
        "RECOVERED",
    }
)


class SwitchError(Exception):
    """Only fixed codes, never provider exceptions or private values."""


CODES = frozenset(
    {
        "BACKEND_UNAVAILABLE",
        "SNAPSHOT_UNPROVEN",
        "WINDOW_UNPROVEN",
        "CANDIDATE_UNPROVEN",
        "ACCOUNT_UNPROVEN",
        "HOST_UNPROVEN",
        "PENDING_OBLIGATIONS",
        "PLAN_INVALID",
        "PLAN_EXPIRED",
        "PREIMAGE_CHANGED",
        "ATTEMPT_CONSUMED",
        "SWITCH_BUSY",
        "PRIVATE_PATH_INVALID",
        "STOP_TIMEOUT",
        "STOP_UNPROVEN",
        "WRITER_NOT_IDLE",
        "INSTALL_UNPROVEN",
        "START_UNPROVEN",
        "READBACK_UNPROVEN",
        "RESULT_UNKNOWN",
        "UNKNOWN_STAGE",
    }
)


def fail(code):
    raise SwitchError(code if code in CODES else "RESULT_UNKNOWN")


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def private(path, *, directory=False):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        fail("PRIVATE_PATH_INVALID")
    info = path.stat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        fail("PRIVATE_PATH_INVALID")
    if not directory and info.st_nlink != 1:
        fail("PRIVATE_PATH_INVALID")
    return path


def write_private(path, value, *, exclusive=False):
    """Atomic durable stage writes; initial intent is an exclusive creation."""
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    target = path if exclusive else path.with_name(path.name + ".pending")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if not exclusive:
            os.replace(target, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if not exclusive:
            target.unlink(missing_ok=True)


def validate_snapshot(s):
    if s.get("connection_permit"):
        fail("CANDIDATE_UNPROVEN")
    """Backend must obtain these from live read-only facts, not a saved receipt."""
    try:
        candidate = s["candidate"]
        if (
            not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", candidate["tag"])
            or not re.fullmatch(r"[0-9a-f]{40}", candidate["commit"])
            or candidate["annotated_exact"] is not True
            or candidate["clean"] is not True
            or candidate["sdk_check"] is not True
            or candidate["preflight_valid"] is not True
        ):
            fail("CANDIDATE_UNPROVEN")
        # Every file is represented by backend-verified content hash + device/inode;
        # SDK symlink identity includes resolved interpreter identity too.
        for name in (
            "code",
            "sdk",
            "config",
            "plist",
            "old_config",
            "old_plist",
            "monitor",
        ):
            if not candidate["identities"][name]:
                fail("CANDIDATE_UNPROVEN")
        a = s["account"]
        if (
            a["existing"] is not True
            or a["same_account_anchor"] is not True
            or a["scope_count"] != 60
            or len(a["databases"]) != 4
            or not a["scope_hash"]
            or not a["attempts_hash"]
            or not a["blocks_hash"]
            or not a["dispatch_hash"]
            or not a["account_id"]
        ):
            fail("ACCOUNT_UNPROVEN")
        ordinary = s.get("ordinary_permit")
        if ordinary:
            anchor = s.get("historical_contract_anchor", {})
            if (
                anchor.get("policy") != "simnow_completed_contract_anchor_v1"
                or anchor.get("product_count") != 60
                or not re.fullmatch("[a-f0-9]{64}", anchor.get("sha256", ""))
                or not isinstance(s.get("preimage"), dict)
                or anchor != s["preimage"].get("historical_contract_anchor")
            ):
                fail("ACCOUNT_UNPROVEN")
            if (
                ordinary.get("schema") != "simnow_ordinary_takeover_v3"
                or ordinary.get("account_id") != a["account_id"]
                or ordinary.get("profile") != a.get("account_profile")
                or a["budget_day"] != ordinary["window"]["trading_day"]
                or s["window"]["trading_day"] != a["budget_day"]
                or type(a["today_attempts"]) is not int
                or not 0 <= a["today_attempts"] < 3
                or a["remaining_attempts"] != 3 - a["today_attempts"]
                or a["day_blocked"] is not False
                or not a.get("account_takeover_pending")
                or a.get("native_account_verified") is not False
                or a.get("local_obligations_clear") is not True
            ):
                fail("ACCOUNT_UNPROVEN")
            h = s["host"]
            if (
                h["label"] != LABEL
                or h["mode"] not in {"trade", "observe"}
                or h["unique"] is not True
                or type(h["pid"]) is not int
                or h["pid"] <= 1
                or not h["run_id"]
                or h["dual_locks_held_by_pid"] is not True
                or not h["command_identity"]
            ):
                fail("HOST_UNPROVEN")
            validate_window(s["window"])
            return
        extra = s.get("connection_permit")
        if extra:
            fail("PLAN_INVALID")
        exception = bool(
            extra
            and extra.get("schema") == "simnow_midday_one_connection_v2"
            and extra.get("account_id") == a["account_id"]
            and extra.get("trading_day") == "20261030"
            and s["window"]["policy"] == MIDDAY_POLICY
            and a["today_attempts"] == 3
        )
        if (
            a["budget_day"] != "20261030"
            or type(a["today_attempts"]) is not int
            or not 0 <= a["today_attempts"] <= 3
            or a["remaining_attempts"] != 3 - a["today_attempts"]
            or (
                a["day_blocked"] is not False
                and not (
                    exception
                    and extra.get("account_takeover_pending") is True
                    and extra.get("budget", {}).get("blocked_code")
                    == "CONNECTION_BUDGET_EXHAUSTED"
                    and a.get("day_block_code") == "CONNECTION_BUDGET_EXHAUSTED"
                )
            )
            or (a["today_attempts"] == 3 and not exception)
        ):
            fail("ACCOUNT_UNPROVEN")
        pending = a.get("account_takeover_pending", False)
        if pending:
            if (
                a.get("native_account_verified") is not False
                or a.get("local_obligations_clear") is not True
                or not s.get("connection_permit")
                or s["connection_permit"].get("account_takeover_pending") is not True
            ):
                fail("ACCOUNT_UNPROVEN")
        if not pending and any(
            a[k] is not False
            for k in (
                "unknown_positions",
                "unknown_orders",
                "unknown_trades",
                "reservations",
            )
        ):
            fail("PENDING_OBLIGATIONS")
        h = s["host"]
        if (
            h["label"] != LABEL
            or h["mode"] != "observe"
            or h["unique"] is not True
            or type(h["pid"]) is not int
            or h["pid"] <= 1
            or not h["run_id"]
            or h["dual_locks_held_by_pid"] is not True
            or not h["command_identity"]
        ):
            fail("HOST_UNPROVEN")
        validate_window(s["window"])
    except (KeyError, TypeError, ValueError):
        fail("SNAPSHOT_UNPROVEN")


def window_facts(rows, now, mode):
    """Classify authoritative resolved sessions; civil noon only names day halves."""
    from zoneinfo import ZoneInfo

    shanghai = ZoneInfo("Asia/Shanghai")
    if (
        mode not in {"night", "midday"}
        or now.tzinfo is None
        or len(rows) != 60
        or len({r[0] for r in rows}) != 60
    ):
        fail("WINDOW_UNPROVEN")
    gaps, starts, ends, phases = [], [], [], {}
    night_count, excluded = 0, 0
    opened = True
    for product, calendar, windows, phase in rows:
        if not calendar.is_trading_day or calendar.trade_date != date(2026, 10, 30):
            fail("WINDOW_UNPROVEN")
        phases[product] = str(phase.phase)
        if mode == "night":
            nights = [
                x.window for x in windows if x.is_night and calendar.has_night_session
            ]
            if not nights:
                excluded += 1
                continue
            if phase.phase not in {"TRADING", "BREAK", "CLOSED"}:
                fail("WINDOW_UNPROVEN")
            night_count += 1
            start = max(w.end for w in nights)
            following = phase.next_session_start
            opened &= (
                phase.phase == "CLOSED"
                and phase.current_session is None
                and now >= start
            )
        else:
            if phase.phase not in {"TRADING", "BREAK", "CLOSED"}:
                fail("WINDOW_UNPROVEN")
            days = [x.window for x in windows if not x.is_night]
            if not days or any(
                w.start.tzinfo is None
                or w.end.tzinfo is None
                or w.start >= w.end
                or w.start.astimezone(shanghai).date() != date(2026, 10, 30)
                or w.end.astimezone(shanghai).date() != date(2026, 10, 30)
                for w in days
            ):
                fail("WINDOW_UNPROVEN")
            morning = [w for w in days if w.start.astimezone(shanghai).hour < 12]
            afternoon = [w for w in days if w.start.astimezone(shanghai).hour >= 12]
            if not morning or not afternoon:
                fail("WINDOW_UNPROVEN")
            start = max(w.end for w in morning)
            following = min(w.start for w in afternoon)
            if start >= following:
                fail("WINDOW_UNPROVEN")
            opened &= (
                phase.phase in {"BREAK", "CLOSED"}
                and phase.current_session is None
                and phase.trading_day == date(2026, 10, 30)
                and start <= now < following
                and phase.next_session_start == following
            )
        if following is None or following.tzinfo is None:
            fail("WINDOW_UNPROVEN")
        gap = (following - now).total_seconds()
        opened &= gap >= 660
        gaps.append(gap)
        starts.append(start)
        ends.append(following - timedelta(seconds=660))
    if not starts:
        fail("WINDOW_UNPROVEN")
    policy = POLICY if mode == "night" else MIDDAY_POLICY
    result = dict(
        policy=policy,
        trading_day="20261030",
        authoritative=True,
        product_count=60,
        current_session_absent=all(
            r[3].current_session is None
            for r in rows
            if mode == "midday"
            or any(x.is_night and r[1].has_night_session for x in r[2])
        ),
        next_session_gap_seconds=min(gaps),
        window_open=bool(opened),
        phases=phases,
        checked_at=now.isoformat(),
        eligible_from=max(starts).isoformat(),
        eligible_until=min(ends).isoformat(),
    )
    if mode == "night":
        result.update(
            night_count=night_count,
            excluded_no_night_count=excluded,
            all_closed=bool(opened),
        )
    else:
        result.update(
            morning_completed=all(now >= t for t in starts), next_is_afternoon=True
        )
    return result


def validate_window(w):
    if w.get("policy") == ORDINARY_POLICY:
        datetime.strptime(w["trading_day"], "%Y%m%d")
        if (
            w["authoritative"] is not True
            or w["product_count"] != 60
            or w["current_session_absent"] is not True
            or w["window_open"] is not True
            or w["next_session_gap_seconds"] <= 660
        ):
            fail("WINDOW_UNPROVEN")
        return
    if (
        w["trading_day"] != "20261030"
        or w["authoritative"] is not True
        or w["current_session_absent"] is not True
        or w["next_session_gap_seconds"] < 660
    ):
        fail("WINDOW_UNPROVEN")
    if w["policy"] == POLICY:
        if (
            w["night_count"] != 45
            or w["excluded_no_night_count"] != 15
            or w["all_closed"] is not True
        ):
            fail("WINDOW_UNPROVEN")
    elif w["policy"] == MIDDAY_POLICY:
        if (
            w["product_count"] != 60
            or w["window_open"] is not True
            or w["morning_completed"] is not True
            or w["next_is_afternoon"] is not True
        ):
            fail("WINDOW_UNPROVEN")
    else:
        fail("WINDOW_UNPROVEN")


def same_preimage(old, fresh):
    """Only verified native evidence append is allowed while observe is alive."""
    if not isinstance(old, dict) or not isinstance(fresh, dict):
        return old == fresh
    a, b = json.loads(json.dumps(old)), json.loads(json.dumps(fresh))
    try:
        prior = a["account"]["databases"]["native-evidence.sqlite"].pop("rows")
        current = b["account"]["databases"]["native-evidence.sqlite"].pop("rows")
    except (KeyError, TypeError):
        return old == fresh
    return bool(prior) and current[: len(prior)] == prior and a == b


class Coordinator:
    """Backend calls are sequential. Any exception freezes mutation permanently.

    Backend contract: snapshot() is freshly read-only; stop(pid) sends SIGTERM
    without forced kill; stopped(snapshot) proves PID gone, durable STOPPED and
    both locks released. offline_guard() owns both original account locks during
    preflight/install, without changing journals. install() atomically replaces
    only same-label plist and monitor binding, preserving verified preimages.
    start() loads only that label after guard release. readback() proves actual
    PID, command/config identity, both exclusive lock holders, new run ID/mode and
    monitoring binding. It must never report native account recovery from host
    startup. Unknown submission results must surface as an exception.
    """

    def __init__(self, backend, state_dir, *, clock=time.time, sleep=time.sleep):
        self.backend = backend
        self.root = private(Path(state_dir), directory=True)
        self.clock, self.sleep = clock, sleep
        self.intent = self.root / "switch-intent.private.json"
        self.mutex = self.root / "switch.lock"

    def plan(self):
        snapshot = self.backend.snapshot()
        validate_snapshot(snapshot)
        permit = snapshot.get("ordinary_permit") or snapshot.get("connection_permit")
        if permit and permit["state_dir"] != str(self.root):
            fail("PLAN_INVALID")
        now = self.clock()
        value = dict(
            schema=SCHEMA,
            window_policy=snapshot["window"]["policy"],
            created_at=now,
            expires_at=now + 60,
            snapshot=snapshot,
            execution_permitted=False,
            broker_io=False,
        )
        return dict(value, plan_hash=digest(value))

    @contextlib.contextmanager
    def _guard(self):
        fd = os.open(self.mutex, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            private(self.mutex)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail("SWITCH_BUSY")
            yield
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def _source_guard(self, source_path):
        # The original writer owns this exact existing inode throughout apply.
        path = private(Path(source_path).parent / "switch.lock")
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            observed, current = os.fstat(fd), os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(observed.st_mode) or (
                observed.st_dev,
                observed.st_ino,
            ) != (current.st_dev, current.st_ino):
                fail("SWITCH_BUSY")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail("SWITCH_BUSY")
            yield
        finally:
            os.close(fd)

    def readback(self):
        """Read persistent phase only. Never retries or resumes mutation."""
        if not self.intent.exists():
            return dict(status="NOT_ATTEMPTED", mutation_performed=False)
        private(self.intent)
        try:
            value = json.loads(self.intent.read_bytes())
        except (ValueError, OSError):
            fail("UNKNOWN_STAGE")
        if value.get("stage") not in STAGES:
            fail("UNKNOWN_STAGE")
        return dict(
            {k: v for k, v in value.items() if k != "snapshot"},
            mutation_performed=False,
            retry_permitted=False,
            recovery_required=value["stage"] not in {"COMPLETE", "RECOVERED"},
        )

    def _phase(self, stage, **fields):
        self.record.update(stage=stage, at=self.clock(), **fields)
        write_private(self.intent, self.record)

    def _fresh(self, plan):
        if not plan["created_at"] <= self.clock() <= plan["expires_at"]:
            fail("PLAN_EXPIRED")
        current = self.backend.snapshot()
        validate_snapshot(current)
        if (
            current["window"]["policy"] != plan["window_policy"]
            or plan["snapshot"]["window"]["policy"] != plan["window_policy"]
        ):
            fail("PLAN_INVALID")
        if not plan["created_at"] <= self.clock() <= plan["expires_at"]:
            fail("PLAN_EXPIRED")
        permit_key = (
            "ordinary_permit"
            if plan["snapshot"].get("ordinary_permit")
            else "connection_permit"
        )
        prior_permit = plan["snapshot"].get(permit_key)
        current_permit = current.get(permit_key)
        if bool(prior_permit) != bool(current_permit):
            fail("PLAN_INVALID")
        if prior_permit:
            if prior_permit["state_dir"] != str(self.root) or {
                k: v for k, v in prior_permit.items() if k != "planned_at"
            } != {k: v for k, v in current_permit.items() if k != "planned_at"}:
                fail("PLAN_INVALID")
            current[permit_key] = prior_permit
        # Dynamic checked_at and monotonically decreasing gap are excluded by
        # the backend's immutable preimage, never by accepting stale calendar.
        old = plan["snapshot"]["preimage"]
        fresh = current["preimage"]
        if not same_preimage(old, fresh):
            fail("PREIMAGE_CHANGED")
        if isinstance(plan["snapshot"].get("account", {}).get("databases"), dict):
            current["native_prefix"] = plan["snapshot"].get(
                "native_prefix",
                plan["snapshot"]["account"]["databases"]["native-evidence.sqlite"][
                    "rows"
                ],
            )
        return current

    def _recovery_source(self, path):
        path = private(Path(path))
        raw = path.read_bytes()
        value = json.loads(raw)
        if (
            value.get("schema") != SCHEMA
            or value.get("stage") not in {"STOPPED", "INSTALLING", "INSTALLED"}
            or value.get("operation") == "stopped_pending_recovery"
            or not value.get("snapshot", {}).get("ordinary_permit")
        ):
            fail("UNKNOWN_STAGE")
        if path.parent == self.root:
            fail("PLAN_INVALID")
        claim = path.parent / "pending-trade-recovery-claim.private.json"
        if claim.exists() or claim.is_symlink():
            fail("ATTEMPT_CONSUMED")
        return value, dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())

    def plan_recovery(self, source_path):
        self._recovery_source(source_path)
        with self._source_guard(source_path):
            source, identity = self._recovery_source(source_path)
            snapshot = self.backend.recovery_snapshot(source["snapshot"])
            validate_snapshot(snapshot)
            if snapshot["ordinary_permit"]["state_dir"] != str(self.root):
                fail("PLAN_INVALID")
            now = self.clock()
            value = dict(
                schema=SCHEMA,
                operation="stopped_pending_recovery",
                source_intent=identity,
                created_at=now,
                expires_at=now + 60,
                snapshot=snapshot,
                window_policy=snapshot["window"]["policy"],
                execution_permitted=False,
                broker_io=False,
            )
            return dict(value, plan_hash=digest(value))

    def recover_pending_trade(self, plan):
        self.intent = self.root / "ordinary-recovery-intent.private.json"
        with self._guard():
            if self.intent.exists():
                fail("ATTEMPT_CONSUMED")
            raw = {k: v for k, v in plan.items() if k != "plan_hash"}
            if (
                raw.get("schema") != SCHEMA
                or raw.get("operation") != "stopped_pending_recovery"
                or digest(raw) != plan.get("plan_hash")
                or raw["expires_at"] - raw["created_at"] != 60
            ):
                fail("PLAN_INVALID")
            if not plan["created_at"] <= self.clock() <= plan["expires_at"]:
                fail("PLAN_EXPIRED")
            with self._source_guard(plan["source_intent"]["path"]):
                source, identity = self._recovery_source(plan["source_intent"]["path"])
                if identity != plan["source_intent"]:
                    fail("PREIMAGE_CHANGED")
                fresh = self.backend.recovery_snapshot(source["snapshot"])
                validate_snapshot(fresh)
                old = plan["snapshot"]
                if (
                    not same_preimage(old["preimage"], fresh["preimage"])
                    or fresh["window"]["policy"] != plan["window_policy"]
                    or {
                        k: v
                        for k, v in fresh["ordinary_permit"].items()
                        if k != "planned_at"
                    }
                    != {
                        k: v
                        for k, v in old["ordinary_permit"].items()
                        if k != "planned_at"
                    }
                ):
                    fail("PREIMAGE_CHANGED")
                fresh["ordinary_permit"] = old["ordinary_permit"]
                if not plan["created_at"] <= self.clock() <= plan["expires_at"]:
                    fail("PLAN_EXPIRED")
                write_private(
                    Path(identity["path"]).parent
                    / "pending-trade-recovery-claim.private.json",
                    dict(
                        source_sha256=identity["sha256"],
                        plan_hash=plan["plan_hash"],
                        recovery_intent=str(self.intent),
                    ),
                    exclusive=True,
                )
                self.record = dict(
                    schema=SCHEMA,
                    operation="stopped_pending_recovery",
                    window_policy=plan["window_policy"],
                    stage="STOPPED",
                    source_intent=identity,
                    plan_hash=plan["plan_hash"],
                    snapshot=fresh,
                    at=self.clock(),
                    native_recovery_complete=False,
                    result="UNKNOWN",
                )
                write_private(self.intent, self.record, exclusive=True)
                try:
                    return self._finish(fresh, plan["plan_hash"])
                except Exception as exc:
                    code = (
                        str(exc)
                        if isinstance(exc, SwitchError) and str(exc) in CODES
                        else "RESULT_UNKNOWN"
                    )
                    self.record["error"] = code
                    write_private(self.intent, self.record)
                    fail(code)

    def recover(self):
        fail("UNKNOWN_STAGE")

    def apply(self, plan):
        with self._guard():
            if self.intent.exists():
                self.readback()  # Unknown stages remain explicitly unknown.
                fail("ATTEMPT_CONSUMED")
            try:
                if plan.get("operation"):
                    fail("PLAN_INVALID")
                raw = {k: v for k, v in plan.items() if k != "plan_hash"}
                if (
                    raw["schema"] != SCHEMA
                    or digest(raw) != plan["plan_hash"]
                    or raw["expires_at"] - raw["created_at"] != 60
                ):
                    fail("PLAN_INVALID")
                snapshot = self._fresh(plan)
            except (KeyError, TypeError, ValueError):
                fail("PLAN_INVALID")
            self.record = dict(
                stage="INTENT",
                schema=SCHEMA,
                window_policy=plan["window_policy"],
                plan_hash=plan["plan_hash"],
                at=self.clock(),
                result="UNKNOWN",
                native_recovery_complete=False,
                account_takeover_pending=snapshot["account"].get(
                    "account_takeover_pending", False
                ),
                snapshot=snapshot,
            )
            try:
                write_private(self.intent, self.record, exclusive=True)
            except FileExistsError:
                fail("ATTEMPT_CONSUMED")
            try:
                self._phase("STOP_REQUESTED")
                if not plan["created_at"] <= self.clock() <= plan["expires_at"]:
                    fail("PLAN_EXPIRED")
                self.backend.stop(snapshot["host"]["pid"])
                deadline = self.clock() + 35
                while not self.backend.stopped(snapshot):
                    if self.clock() >= deadline:
                        fail("STOP_TIMEOUT")
                    self.sleep(0.25)
                self._phase("STOPPED")
                return self._finish(snapshot, plan["plan_hash"])
            except Exception as exc:
                # Preserve last durable intent phase. Never automatic rollback:
                # a new trade journal event can make old observe code incompatible.
                code = str(exc) if isinstance(exc, SwitchError) else "RESULT_UNKNOWN"
                self.record.update(error=code if code in CODES else "RESULT_UNKNOWN")
                write_private(self.intent, self.record)
                fail(self.record["error"])

    def _finish(self, snapshot, plan_hash):
        with self.backend.offline_guard(snapshot):
            evidence = self.backend.offline_preflight(snapshot)
            if evidence.get("writer_idle") is not True:
                fail("WRITER_NOT_IDLE")
            if (
                evidence.get("preimage") != snapshot["preimage"]
                or evidence.get("protected_state_unchanged") is not True
            ):
                fail("PREIMAGE_CHANGED")
            if snapshot["account"].get("account_takeover_pending", False):
                snapshot["connection_anchor"] = evidence.get("connection_anchor")
                if not snapshot["connection_anchor"]:
                    fail("PREIMAGE_CHANGED")
            # Re-read authoritative calendar immediately before install.
            if self.backend.window_open() is not True:
                fail("WINDOW_UNPROVEN")
            self._phase("INSTALLING")
            if self.backend.install(snapshot) is not True:
                fail("INSTALL_UNPROVEN")
            self._phase("INSTALLED")
        if self.backend.window_open() is not True:
            fail("WINDOW_UNPROVEN")
        grant_fields = {}
        if snapshot.get("ordinary_permit"):
            grant_fields["ordinary_grant_sha256"] = self.backend.issue_ordinary_permit(
                snapshot, plan_hash, self.intent
            )
        elif snapshot.get("connection_permit"):
            grant_fields["connection_grant_sha256"] = (
                self.backend.issue_connection_permit(snapshot, plan_hash, self.intent)
            )
        self._phase("START_REQUESTED", **grant_fields)
        if self.backend.start(snapshot) is not True:
            fail("START_UNPROVEN")
        self._phase("VERIFYING")
        previous = None
        for _ in range(2):
            proof = self.backend.readback(snapshot)
            if (
                proof.get("verified") is not True
                or proof.get("mode") != "trade"
                or proof.get("pid") == snapshot["host"]["pid"]
                or type(proof.get("pid")) is not int
                or proof["pid"] <= 1
                or not proof.get("run_id")
                or proof["run_id"] == snapshot["host"]["run_id"]
                or proof.get("dual_locks_held_by_pid") is not True
                or proof.get("config_bound") is not True
                or proof.get("monitor_bound") is not True
            ):
                fail("READBACK_UNPROVEN")
            if snapshot["account"].get("account_takeover_pending", False) and (
                proof.get("account_takeover_pending") is not True
                or proof.get("opening_enabled") is not False
            ):
                fail("READBACK_UNPROVEN")
            if previous and (proof["pid"], proof["run_id"]) != previous:
                fail("READBACK_UNPROVEN")
            previous = proof["pid"], proof["run_id"]
            self.sleep(1)
        self._phase(
            "COMPLETE",
            result="HOST_SWITCH_VERIFIED",
            pid=previous[0],
            run_id=previous[1],
            native_recovery_complete=False,
        )
        return self.readback()


class MacBackend:
    """Pinned native LaunchAgent backend; no shell, credential or Broker calls."""

    def __init__(
        self, candidate, candidate_plist, *, tag, home=None, window="ordinary"
    ):
        if window not in {"night", "midday", "ordinary"}:
            fail("WINDOW_UNPROVEN")
        self.window = window
        self.home = Path.home() if home is None else Path(home)
        self.config = private(Path(candidate))
        self.candidate_plist = private(Path(candidate_plist))
        self.cfg = json.loads(self.config.read_bytes())
        if (
            self.cfg.get("schema") != 2
            or self.cfg.get("mode") != "trade"
            or self.cfg.get("enabled") is not True
        ):
            fail("CANDIDATE_UNPROVEN")
        self.code = Path(self.cfg["project_root"])
        self.tag = tag
        if (
            not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag)
            or self.code.name != "release-" + tag
            or self.code.resolve() != self.code
        ):
            fail("CANDIDATE_UNPROVEN")
        resolved = self.run(["/usr/bin/git", "-C", self.code, "rev-parse", tag + "^{}"])
        if resolved.returncode or not re.fullmatch(
            r"[0-9a-f]{40}", resolved.stdout.strip()
        ):
            fail("CANDIDATE_UNPROVEN")
        self.exact = resolved.stdout.strip()
        self.code_check()
        self.plist = self.home / "Library/LaunchAgents" / (LABEL + ".plist")
        self.monitor = (
            self.home
            / "Library/Application Support/GuiyiQuant/simnow-monitor.private.json"
        )
        sys.path[:0] = [
            str(self.code / "packages/quant-core"),
            str(self.code / "services/quant-api"),
        ]
        from guiyi_quant.simnow_execution.settings import load_settings
        from guiyi_quant.simnow_execution.supervisor import (
            global_account_lock_directory,
        )

        self.settings = load_settings(self.config)
        self.ordinary = bool(getattr(self.settings, "ordinary_takeover_permit", None))
        if (
            self.window != "ordinary"
            or not self.ordinary
            or not self.settings.account_takeover_pending
            or getattr(self.settings, "deployment_connection_permit", None)
        ):
            fail("CANDIDATE_UNPROVEN")
        self.folder = self.settings.state_root / self.settings.account_id
        self.locks = (
            global_account_lock_directory() / (self.settings.account_id + ".lock"),
            self.folder / "host.lock",
        )
        self.label = f"gui/{os.getuid()}/{LABEL}"
        spec = importlib.util.spec_from_file_location(
            "switch_service", self.code / "scripts/ops/macos/simnow-service.py"
        )
        self.service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.service)

    @staticmethod
    def run(args):
        return subprocess.run(
            [str(a) for a in args],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    def identity(self, path, *, interpreter=False):
        path = Path(path)
        if interpreter:
            path = path.resolve(strict=True)
        else:
            private(path)
        st = path.stat()
        return dict(
            device=st.st_dev,
            inode=st.st_ino,
            size=st.st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def _label_loaded(self):
        result = self.run(["/bin/launchctl", "print", self.label])
        if result.returncode == 0:
            return result
        output = result.stdout + result.stderr
        if (
            result.returncode == 113
            and "Could not find service" in output
            and LABEL in output
        ):
            return None
        fail("HOST_UNPROVEN")

    def _pid(self):
        r = self.run(["/bin/launchctl", "print", self.label])
        m = re.search(r"^\s*pid = (\d+)", r.stdout, re.M)
        if r.returncode or not m:
            fail("HOST_UNPROVEN")
        return int(m[1])

    def _prove(self, pid, mode, config):
        r = self.run(["/bin/ps", "-p", str(pid), "-o", "command="])
        cfg = json.loads(private(Path(config)).read_bytes())
        expected = [
            cfg["sdk_python"],
            "-I",
            str(Path(cfg["project_root"]) / "scripts/broker/simnow_supervisor.py"),
            "--config",
            str(config),
            "--trade" if mode == "trade" else "--observe-only",
        ]
        if r.returncode or r.stdout.strip() != " ".join(expected):
            fail("HOST_UNPROVEN")
        for path in self.locks:
            private(path)
            result = self.run(["/usr/sbin/lsof", "-nP", "-Fpn", "--", path])
            holders = {
                int(line[1:])
                for line in result.stdout.splitlines()
                if line.startswith("p")
            }
            if result.returncode or holders != {pid}:
                fail("HOST_UNPROVEN")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    fail("HOST_UNPROVEN")
            finally:
                os.close(fd)
        return expected

    def _window_rows(self, now):
        from app.db.session import SessionLocal
        from app.db.readonly import readonly_transaction
        from app.market_data.market_phase import MarketPhaseResolver
        from app.market_data.operational_universe import load_operational_products
        from app.market_data.session_clock import (
            resolved_session_windows_for_trading_day,
        )
        from app.models import Instrument, TradingCalendar
        from sqlalchemy import select

        rows = []
        with SessionLocal() as db, readonly_transaction(db, timeout_seconds=20):
            resolver = MarketPhaseResolver(db)
            products = load_operational_products()
            if len(products) != 60 or len(set(products)) != 60:
                fail("WINDOW_UNPROVEN")
            for product in products:
                exchange = db.scalar(
                    select(Instrument.exchange_code).where(
                        Instrument.symbol == product, Instrument.is_active.is_(True)
                    )
                )
                calendar = db.scalar(
                    select(TradingCalendar).where(
                        TradingCalendar.exchange_code == exchange,
                        TradingCalendar.trade_date == date(2026, 10, 30),
                    )
                )
                if not exchange or not calendar:
                    fail("WINDOW_UNPROVEN")
                windows = resolved_session_windows_for_trading_day(
                    db,
                    exchange=exchange,
                    symbol=product,
                    trading_day=date(2026, 10, 30),
                )
                rows.append(
                    (
                        product,
                        CalendarFacts(
                            calendar.trade_date,
                            calendar.is_trading_day,
                            calendar.has_night_session,
                        ),
                        windows,
                        resolver.resolve(product, now),
                    )
                )
            return tuple(rows)

    def _window(self):
        if getattr(self, "ordinary", False):
            from app.simnow_takeover_window import authoritative_window

            return authoritative_window(datetime.now(UTC), require_closed=True)
        now = datetime.now(UTC)
        rows = self._window_rows(now)
        return window_facts(rows, datetime.now(UTC), self.window)

    def window_open(self):
        try:
            validate_window(self._window())
            return True
        except SwitchError:
            return False

    def _native_readback(
        self, snapshot, projection, journal, *, previous=None, fresh=False
    ):
        """Validate a real durable Snapshot, never manufacture a native report."""
        from guiyi_quant.simnow_execution.inventory import (
            native_hash,
            project_readback,
            number,
        )
        from guiyi_quant.simnow_execution.supervisor import verify_recovery_ownership
        from guiyi_quant import htdy_account_execution as a

        try:
            now = datetime.now(UTC)
            data = snapshot.data
            expected = (
                "ctp-inventory:"
                + snapshot.trading_day
                + ":"
                + native_hash(
                    (
                        snapshot.account_id,
                        snapshot.trading_day,
                        data,
                        snapshot.at.isoformat(),
                    )
                )
            )
            if (
                snapshot.account_id != self.settings.account_id
                or snapshot.trading_day != "20261030"
                or snapshot.source_id != expected
                or not snapshot.started_at <= snapshot.at <= now
                or (
                    previous is not None
                    and (
                        snapshot.started_at < previous.at or snapshot.at <= previous.at
                    )
                )
                or (fresh and not 0 <= (now - snapshot.at).total_seconds() < 30)
                or set(data) != {"funds", "positions", "orders", "trades"}
                or any(type(rows) is not list for rows in data.values())
                or len(data["funds"]) != 1
                or data["funds"][0]["CurrencyID"] != "CNY"
                or any(
                    row["TradingDay"] != snapshot.trading_day
                    for rows in data.values()
                    for row in rows
                )
            ):
                fail("ACCOUNT_UNPROVEN")
            signed = {"Balance", "Available", "CloseProfit", "PositionProfit"}
            for field in (
                "Balance",
                "Available",
                "CurrMargin",
                "FrozenMargin",
                "FrozenCommission",
                "Commission",
                "Deposit",
                "Withdraw",
                "CloseProfit",
                "PositionProfit",
            ):
                value = number(data["funds"][0][field], signed=field in signed)
                if previous is not None and value != number(
                    previous.data["funds"][0][field], signed=field in signed
                ):
                    fail("ACCOUNT_UNPROVEN")
            if (
                data["positions"]
                or data["orders"]
                or data["trades"]
                or projection.positions
                or projection.orders
                or projection.fills
                or projection.reservations
                or projection.unresolved_fill_ids
            ):
                fail("PENDING_OBLIGATIONS")
            verify_recovery_ownership(snapshot, (), journal, projection)
            rb, inventory = project_readback(
                snapshot, (), journal, projection, snapshot.at + timedelta(seconds=30)
            )
            transition = a.apply(
                replace(projection, phase="RECOVERY_REQUIRED", readback_valid=False),
                "switch-check:" + snapshot.source_id,
                a.Recover(rb, ()),
            )
            if (
                inventory
                or transition.effects
                or transition.state.phase != "READY"
                or not transition.state.readback_valid
                or not rb.complete
                or rb.used_margin
                or rb.frozen_margin
                or rb.frozen_fee
                or rb.snapshot.balance != projection.readback.snapshot.balance
                or rb.snapshot.available != projection.readback.snapshot.available
            ):
                fail("ACCOUNT_UNPROVEN")
        except (KeyError, TypeError, ValueError, ArithmeticError):
            fail("ACCOUNT_UNPROVEN")

    def _stopped_native(
        self, snapshot, monitor, control, rows, prefix, projection, journal
    ):
        """Prove the unchanged prefix and every stop-boundary append while offline."""
        from guiyi_quant.simnow_execution.evidence import Evidence
        from guiyi_quant.htdy_account_execution.codec import digest as state_digest

        identities = [
            [n, source, hashlib.sha256(raw.encode()).hexdigest()]
            for n, source, raw in rows
        ]
        if not prefix or identities[: len(prefix)] != prefix:
            fail("PREIMAGE_CHANGED")
        if (
            control.get("status") != "STOPPED"
            or control.get("mode") != "observe"
            or control.get("opening_enabled") is not False
            or control.get("auto_order") is not False
            or monitor.get("status") != "STOPPED"
            or monitor.get("mode") != "observe"
            or monitor.get("host_status") != "STOPPED"
            or monitor.get("account_id") != self.settings.account_id
            or monitor.get("ledger_hash") != state_digest(projection)
            or monitor.get("native_source_id") != rows[-1][1]
            or snapshot.source_id != rows[-1][1]
        ):
            fail("ACCOUNT_UNPROVEN")
        previous = None
        previous_rowid = None
        # The final frozen row anchors time ordering; older prefix rows are hash-frozen.
        for n, source, raw in rows[len(prefix) - 1 :]:
            if previous_rowid is not None and n != previous_rowid + 1:
                fail("PREIMAGE_CHANGED")
            previous_rowid = n
            value = Evidence._decode(raw)
            if value.source_id != source:
                fail("ACCOUNT_UNPROVEN")
            self._native_readback(
                value, projection, journal, previous=previous, fresh=n == rows[-1][0]
            )
            previous = value
        now = datetime.now(UTC)
        if (
            not snapshot.at <= datetime.fromisoformat(control["at"]) <= now
            or not snapshot.at <= datetime.fromisoformat(monitor["published_at"]) <= now
        ):
            fail("ACCOUNT_UNPROVEN")

    def _pending_history(
        self, rows, projection, journal, control, monitor, stopped_snapshot
    ):
        """Immutable historical evidence only; no current-native-account assertion."""
        from guiyi_quant.simnow_execution.evidence import Evidence
        from guiyi_quant.simnow_execution.inventory import native_hash, number

        if (
            any(not order.reconciled for order in projection.orders)
            or any(not reservation.released for reservation in projection.reservations)
            or projection.unresolved_fill_ids
        ):
            fail("PENDING_OBLIGATIONS")
        known = {order.order_id: order for order in projection.orders}
        if any(
            identity not in known or not known[identity].reconciled
            for (identity,) in journal.conn.execute("SELECT order_id FROM actions")
        ):
            fail("PENDING_OBLIGATIONS")
        for (raw,) in journal.conn.execute("SELECT payload FROM events"):
            if json.loads(raw).get("kind") in {"fault", "quarantine"}:
                fail("PENDING_OBLIGATIONS")
        previous = None
        prior_id = None
        for rowid, source, raw in rows:
            value = Evidence._decode(raw)
            datetime.strptime(value.trading_day, "%Y%m%d")
            data = value.data
            if (
                rowid < 1
                or (prior_id is not None and rowid != prior_id + 1)
                or value.account_id != self.settings.account_id
                or value.source_id != source
                or not re.fullmatch(r"[0-9]{8}", value.trading_day)
                or not value.started_at <= value.at <= datetime.now(UTC)
                or (previous is not None and value.started_at < previous.at)
                or source
                != "ctp-inventory:"
                + value.trading_day
                + ":"
                + native_hash(
                    (value.account_id, value.trading_day, data, value.at.isoformat())
                )
                or set(data) != {"funds", "positions", "orders", "trades"}
                or any(type(v) is not list for v in data.values())
                or len(data["funds"]) != 1
                or data["funds"][0]["CurrencyID"] != "CNY"
                or any(
                    row["TradingDay"] != value.trading_day
                    for items in data.values()
                    for row in items
                )
            ):
                fail("ACCOUNT_UNPROVEN")
            for key in (
                "Balance",
                "Available",
                "CurrMargin",
                "FrozenMargin",
                "FrozenCommission",
                "Commission",
                "Deposit",
                "Withdraw",
                "CloseProfit",
                "PositionProfit",
            ):
                number(
                    data["funds"][0][key],
                    signed=key
                    in {"Balance", "Available", "CloseProfit", "PositionProfit"},
                )
            prior_id, previous = rowid, value
        if previous is None:
            fail("ACCOUNT_UNPROVEN")
        if stopped_snapshot is not None:
            prefix = stopped_snapshot.get(
                "native_prefix",
                stopped_snapshot["account"]["databases"]["native-evidence.sqlite"][
                    "rows"
                ],
            )
            current = [
                [n, source, hashlib.sha256(raw.encode()).hexdigest()]
                for n, source, raw in rows
            ]
            if current[: len(prefix)] != prefix:
                fail("PREIMAGE_CHANGED")
            if (
                control.get("status") != "STOPPED"
                or control.get("mode") != stopped_snapshot["host"]["mode"]
                or control.get("opening_enabled") is not False
                or control.get("run_id") != stopped_snapshot["host"]["run_id"]
                or monitor.get("run_id") != control["run_id"]
                or monitor.get("account_id") != self.settings.account_id
                or monitor.get("status") != "STOPPED"
            ):
                fail("ACCOUNT_UNPROVEN")

    def _account(self, *, restoring=False, frozen_index=None, stopped_snapshot=None):
        from guiyi_quant.simnow_execution.account_binding import existing_account
        from guiyi_quant.htdy_account_execution.store import LocalStore
        from guiyi_quant.simnow_execution.native_portfolio import ReadJournal
        from guiyi_quant.simnow_execution.evidence import Evidence
        from guiyi_quant.htdy_account_execution.codec import digest as state_digest

        pending = getattr(self.settings, "account_takeover_pending", False)
        budget_day = (
            self._window()["trading_day"]
            if getattr(self, "ordinary", False)
            else "20261030"
        )
        state = existing_account(self.settings.state_root, self.settings.account_id)
        projection = LocalStore.inspect(self.folder / "account.sqlite")
        journal = ReadJournal(self.folder / "dispatch.sqlite", self.settings.account_id)
        identities = {}
        for name in (
            "account.sqlite",
            "dispatch.sqlite",
            "signals.sqlite",
            "native-evidence.sqlite",
        ):
            path = self.folder / name
            for suffix in ("-wal", "-shm", "-journal"):
                if Path(str(path) + suffix).exists():
                    fail("ACCOUNT_UNPROVEN")
            identities[name] = self.identity(path)
            if name == "native-evidence.sqlite":
                identities[name] = {
                    k: v
                    for k, v in identities[name].items()
                    if k in {"device", "inode"}
                }
        db = sqlite3.connect(
            (self.folder / "native-evidence.sqlite").as_uri() + "?mode=ro", uri=True
        )
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("SELECT account FROM owner").fetchall() != [
                (self.settings.account_id,)
            ]:
                fail("ACCOUNT_UNPROVEN")
            control = json.loads(private(self.folder / "continuous.json").read_bytes())
            monitor = (
                frozen_index
                if frozen_index is not None
                else json.loads(
                    private(self.settings.state_root / "monitor.json").read_bytes()
                )
            )
            self.last_observe_index = monitor
            if monitor["run_id"] != control["run_id"] or (
                stopped_snapshot is not None
                and control["run_id"] != stopped_snapshot["host"]["run_id"]
            ):
                fail("ACCOUNT_UNPROVEN")
            row = (
                db.execute(
                    "SELECT payload FROM snapshots ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                if pending
                else db.execute(
                    "SELECT payload FROM snapshots WHERE source=?",
                    (monitor["native_source_id"],),
                ).fetchone()
            )
            if row is None:
                fail("ACCOUNT_UNPROVEN")
            snapshot = Evidence._decode(row[0])
            rows = db.execute(
                "SELECT rowid,source,payload FROM snapshots ORDER BY rowid LIMIT 100001"
            ).fetchall()
            if len(rows) > 100000:
                fail("ACCOUNT_UNPROVEN")
            identities["native-evidence.sqlite"]["schema_hash"] = digest(
                db.execute(
                    "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
                ).fetchall()
            )
            identities["native-evidence.sqlite"]["rows"] = [
                [n, source, hashlib.sha256(payload.encode()).hexdigest()]
                for n, source, payload in rows
            ]
        finally:
            db.close()
        try:
            if pending:
                self._pending_history(
                    rows, projection, journal, control, monitor, stopped_snapshot
                )
            elif stopped_snapshot is not None:
                prefix = stopped_snapshot.get(
                    "native_prefix",
                    stopped_snapshot["account"]["databases"]["native-evidence.sqlite"][
                        "rows"
                    ],
                )
                self._stopped_native(
                    snapshot, monitor, control, rows, prefix, projection, journal
                )
            else:
                from guiyi_quant.simnow_execution.observe_reconciliation import (
                    verify_proof,
                )

                proof = verify_proof(
                    monitor.get("observe_reconciliation"),
                    monitor,
                    projection,
                    snapshot,
                    datetime.now(UTC),
                )
                if proof is None or (not restoring and proof.get("fresh") is not True):
                    fail("ACCOUNT_UNPROVEN")
                self._native_readback(
                    snapshot, projection, journal, fresh=not restoring
                )
        finally:
            journal.close()
        native = snapshot.data
        values = {}
        db = sqlite3.connect(
            (self.folder / "signals.sqlite").as_uri() + "?mode=ro", uri=True
        )
        try:
            db.execute("PRAGMA query_only=ON")
            for table in ("attempts", "blocks"):
                values[table] = digest(
                    db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()
                )
            row = db.execute(
                "SELECT count FROM attempts WHERE day=?", (budget_day,)
            ).fetchone()
            attempts = row[0] if row else 0
            if type(attempts) is not int or not 0 <= attempts <= 3:
                fail("ACCOUNT_UNPROVEN")
            block_row = db.execute(
                "SELECT code FROM blocks WHERE day=?", (budget_day,)
            ).fetchone()
            block_code = block_row[0] if block_row else None
            blocked = block_row is not None
        finally:
            db.close()
        return dict(
            account_takeover_pending=pending,
            native_account_verified=not pending,
            local_obligations_clear=True,
            ledger_hash=state_digest(projection),
            day_block_code=block_code,
            today_attempts=attempts,
            remaining_attempts=3 - attempts,
            day_blocked=blocked,
            budget_day=budget_day,
            account_profile=self._profile()
            if getattr(self, "ordinary", False)
            else None,
            existing=True,
            same_account_anchor=True,
            scope_count=len(state.products),
            scope_hash=digest(sorted(p.product for p in state.products)),
            databases=identities,
            attempts_hash=values["attempts"],
            blocks_hash=values["blocks"],
            dispatch_hash=identities["dispatch.sqlite"]["sha256"],
            account_id=self.settings.account_id,
            unknown_positions=None
            if pending
            else bool(native["positions"]) or bool(projection.positions),
            unknown_orders=None
            if pending
            else bool(native["orders"]) or bool(projection.orders),
            unknown_trades=None
            if pending
            else bool(native["trades"]) or bool(projection.fills),
            reservations=bool(projection.reservations),
        )

    def release_identity(self, root):
        root = Path(root)
        tag = root.name.removeprefix("release-")
        if root.resolve() != root or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
            fail("CANDIDATE_UNPROVEN")
        result = self.run(["/usr/bin/git", "-C", root, "rev-parse", tag + "^{}"])
        if result.returncode or not re.fullmatch(
            r"[0-9a-f]{40}", result.stdout.strip()
        ):
            fail("CANDIDATE_UNPROVEN")
        view = MacBackend.__new__(MacBackend)
        view.code, view.tag, view.exact, view.run = (
            root,
            tag,
            result.stdout.strip(),
            self.run,
        )
        view.code_check()
        return dict(root=str(root), tag=tag, commit=view.exact)

    def monitor_source(self):
        value = {
            "schema": 2,
            "account_id": self.settings.account_id,
            "state_root": str(self.settings.state_root),
            "project_root": str(self.settings.project_root),
            "sdk_python": str(self.settings.sdk_python),
            "api_env": str(self.settings.api_env),
            "mode": "observe",
            "enabled": True,
            "state_project_root": str(self.settings.state_project_root),
        }
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    def _historical_anchor(self):
        from app.simnow_takeover_window import historical_contract_anchor

        return historical_contract_anchor(datetime.now(UTC))

    def _verify_historical_anchor(self, snapshot):
        if self._historical_anchor() != snapshot.get("historical_contract_anchor"):
            fail("PREIMAGE_CHANGED")

    def _preimage(self):
        p = plistlib.loads(private(self.plist).read_bytes())
        args = p["ProgramArguments"]
        old = private(Path(args[args.index("--config") + 1]))
        old_cfg = json.loads(old.read_bytes())
        monitor_cfg = json.loads(private(self.monitor).read_bytes())
        if (
            monitor_cfg.get("schema") != 2
            or monitor_cfg.get("mode") != "observe"
            or monitor_cfg.get("enabled") is not True
            or monitor_cfg.get("account_id") != self.settings.account_id
            or monitor_cfg.get("state_root") != str(self.settings.state_root)
            or monitor_cfg.get("state_project_root")
            != str(self.settings.state_project_root)
        ):
            fail("PREIMAGE_CHANGED")
        if (
            (
                not getattr(self.settings, "account_takeover_pending", False)
                and old_cfg != json.loads(private(self.monitor).read_bytes())
            )
            or old_cfg["mode"]
            not in (
                {"observe", "trade"}
                if getattr(self, "ordinary", False)
                else {"observe"}
            )
            or old_cfg["account_id"] != self.settings.account_id
            or old_cfg["state_root"] != str(self.settings.state_root)
            or old_cfg.get("state_project_root")
            != str(self.settings.state_project_root)
            or ("--trade" if old_cfg["mode"] == "trade" else "--observe-only")
            not in args
            or ("--observe-only" if old_cfg["mode"] == "trade" else "--trade") in args
            or p["Label"] != LABEL
        ):
            fail("PREIMAGE_CHANGED")
        self.old_config = old
        self.old_mode = old_cfg["mode"]
        return {
            "monitor_target_sha256": hashlib.sha256(self.monitor_source()).hexdigest()
            if getattr(self.settings, "account_takeover_pending", False)
            else None,
            "release": dict(tag=self.tag, commit=self.exact, root=str(self.code)),
            "old_release": self.release_identity(Path(old_cfg["project_root"])),
            "old_runner": self.identity(
                Path(old_cfg["project_root"]) / "scripts/broker/simnow_supervisor.py",
                interpreter=True,
            ),
            "old_sdk": self.identity(Path(old_cfg["sdk_python"]), interpreter=True),
            "sdk": self.identity(self.settings.sdk_python, interpreter=True),
            "runner": self.identity(
                self.code / "scripts/broker/simnow_supervisor.py", interpreter=True
            ),
            "config": self.identity(self.config),
            "plist": self.identity(self.candidate_plist),
            "old_config": self.identity(old),
            "old_plist": self.identity(self.plist),
            "monitor": self.identity(self.monitor),
        }

    def code_check(self):
        exact = self.exact
        tag_type = self.run(
            ["/usr/bin/git", "-C", self.code, "cat-file", "-t", self.tag]
        )
        if tag_type.returncode or tag_type.stdout.strip() != "tag":
            fail("CANDIDATE_UNPROVEN")
        for ref in ("HEAD", self.tag + "^{}"):
            r = self.run(["/usr/bin/git", "-C", self.code, "rev-parse", ref])
            if r.returncode or r.stdout.strip() != exact:
                fail("CANDIDATE_UNPROVEN")
        r = self.run(
            [
                "/usr/bin/git",
                "-c",
                "core.fsmonitor=false",
                "-C",
                self.code,
                "status",
                "--porcelain",
            ]
        )
        if r.returncode or r.stdout.strip():
            fail("CANDIDATE_UNPROVEN")
        return exact

    def _candidate(self):
        exact = self.code_check()
        runner = self.code / "scripts/broker/simnow_supervisor.py"
        r = self.run(
            [
                self.settings.sdk_python,
                "-I",
                "-B",
                runner,
                "--config",
                self.config,
                "--trade",
                "--check",
            ]
        )
        if (
            r.returncode
            or r.stdout.strip() != "CONTINUOUS_CONFIG_SDK_COMPATIBLE_NO_BROKER_IO"
        ):
            fail("CANDIDATE_UNPROVEN")
        if (
            self.service.render_trade_launch_agent(
                self.settings, self.config, home=self.home
            )
            != self.candidate_plist.read_bytes()
        ):
            fail("CANDIDATE_UNPROVEN")
        preflight = self.service.preflight_trade(self.settings, self.config)
        return exact, preflight

    def snapshot(self):
        exact, preflight = self._candidate()
        preimage = self._preimage()
        account = self._account()
        pid = self._pid()
        command = self._prove(
            pid, getattr(self, "old_mode", "observe"), self.old_config
        )
        control = json.loads(private(self.folder / "continuous.json").read_bytes())
        if (
            control["mode"] != getattr(self, "old_mode", "observe")
            or control["opening_enabled"]
        ):
            fail("HOST_UNPROVEN")
        preimage.update(
            account=account,
            host_pid=pid,
            host_run_id=control["run_id"],
            locks=[
                dict(path=str(p), device=p.stat().st_dev, inode=p.stat().st_ino)
                for p in self.locks
            ],
        )
        historical_anchor = (
            self._historical_anchor() if getattr(self, "ordinary", False) else None
        )
        if historical_anchor is not None:
            preimage["historical_contract_anchor"] = historical_anchor
        window = self._window()
        connection_permit = None
        ordinary_permit = None
        if getattr(self, "ordinary", False):
            from guiyi_quant.simnow_execution import ordinary_takeover as ordinary

            ordinary_permit = ordinary.binding(
                self.settings, self.config, window, datetime.now(UTC)
            )
            path = Path(self.settings.ordinary_takeover_permit)
            if (
                path.exists()
                or path.is_symlink()
                or Path(str(path) + ".run-claim").exists()
            ):
                fail("ATTEMPT_CONSUMED")
        path = getattr(self.settings, "deployment_connection_permit", None)
        if path and account["today_attempts"] == 3:
            from guiyi_quant.simnow_execution import deployment_connection as permit

            if (
                window["policy"] != MIDDAY_POLICY
                or (
                    account["day_blocked"]
                    and not (
                        getattr(self.settings, "account_takeover_pending", False)
                        and account.get("day_block_code")
                        == "CONNECTION_BUDGET_EXHAUSTED"
                    )
                )
                or Path(path).exists()
                or Path(str(path) + ".run-claim").exists()
                or Path(str(path) + ".attempt-claim").exists()
                or permit.global_marker(self.settings).exists()
                or permit.global_marker(self.settings).is_symlink()
            ):
                fail("ACCOUNT_UNPROVEN")
            pm = datetime.fromisoformat(window["eligible_until"]) + timedelta(
                seconds=660
            )
            connection_permit = permit.binding(
                self.settings, self.config, pm, datetime.now(UTC)
            )
        identities = dict(preimage, code=exact)
        self._stop_signals = account["databases"].get("signals.sqlite")
        self._stop_requires_permit = bool(connection_permit)
        self._stop_ordinary = ordinary_permit
        self._stop_historical_anchor = historical_anchor
        return dict(
            connection_permit=connection_permit,
            ordinary_permit=ordinary_permit,
            historical_contract_anchor=historical_anchor,
            old_config_path=str(self.old_config),
            observe_index=self.last_observe_index,
            candidate=dict(
                tag=self.tag,
                commit=exact,
                annotated_exact=True,
                clean=True,
                sdk_check=True,
                preflight_valid=preflight["candidate_valid"],
                identities=identities,
            ),
            account=account,
            host=dict(
                label=LABEL,
                mode=getattr(self, "old_mode", "observe"),
                unique=True,
                pid=pid,
                run_id=control["run_id"],
                dual_locks_held_by_pid=True,
                command_identity=digest(command),
            ),
            window=window,
            preimage=preimage,
        )

    def recovery_snapshot(self, source):
        from guiyi_quant.simnow_execution import ordinary_takeover as ordinary

        if not getattr(self, "ordinary", False):
            fail("CANDIDATE_UNPROVEN")
        self._recovery = True
        self._verify_historical_anchor(source)
        if (
            self.identity(self.settings.sdk_python, interpreter=True)
            != source["preimage"]["sdk"]
            or self.identity(private(Path(source["old_config_path"])))
            != source["preimage"]["old_config"]
        ):
            fail("PREIMAGE_CHANGED")
        if (
            source["candidate"]["commit"] != self.exact
            or source["candidate"]["tag"] != self.tag
            or source["preimage"]["release"]["root"] != str(self.code)
        ):
            fail("PREIMAGE_CHANGED")
        original_path = private(Path(source["ordinary_permit"]["config_path"]))
        original = json.loads(original_path.read_bytes())
        if (
            hashlib.sha256(original_path.read_bytes()).hexdigest()
            != source["preimage"]["config"]["sha256"]
        ):
            fail("PREIMAGE_CHANGED")
        if {k: v for k, v in original.items() if k != "ordinary_takeover_permit"} != {
            k: v for k, v in self.cfg.items() if k != "ordinary_takeover_permit"
        }:
            fail("PREIMAGE_CHANGED")
        if not self.stopped(source):
            fail("STOP_UNPROVEN")
        loaded = self._label_loaded()
        if loaded is not None and re.search(r"^\s*pid = (\d+)", loaded.stdout, re.M):
            fail("HOST_UNPROVEN")
        for path, allowed in (
            (
                self.plist,
                {
                    source["preimage"]["old_plist"]["sha256"],
                    source["preimage"]["plist"]["sha256"],
                },
            ),
            (
                self.monitor,
                {
                    source["preimage"]["monitor"]["sha256"],
                    source["preimage"].get("monitor_target_sha256"),
                },
            ),
        ):
            if hashlib.sha256(private(path).read_bytes()).hexdigest() not in allowed:
                fail("PREIMAGE_CHANGED")
        exact, preflight = self._candidate()
        with self.offline_guard(source):
            preimage = self._preimage()
            account = self._account(stopped_snapshot=source)
            if not same_preimage(
                dict(account=source["account"]), dict(account=account)
            ):
                fail("PREIMAGE_CHANGED")
            window = self._window()
            permit = ordinary.binding(
                self.settings, self.config, window, datetime.now(UTC)
            )
            if Path(self.settings.ordinary_takeover_permit).exists():
                fail("ATTEMPT_CONSUMED")
            preimage.update(
                historical_contract_anchor=source["historical_contract_anchor"],
                account=account,
                locks=source["preimage"]["locks"],
                host_pid=source["host"]["pid"],
                host_run_id=source["host"]["run_id"],
            )
            return dict(
                candidate=dict(
                    tag=self.tag,
                    commit=exact,
                    annotated_exact=True,
                    clean=True,
                    sdk_check=True,
                    preflight_valid=preflight["candidate_valid"],
                    identities=dict(preimage, code=exact),
                ),
                account=account,
                historical_contract_anchor=source["historical_contract_anchor"],
                ordinary_permit=permit,
                connection_permit=None,
                window=window,
                host=source["host"],
                preimage=preimage,
                old_config_path=str(self.old_config),
            )

    def stop(self, pid):
        self._prove(pid, getattr(self, "old_mode", "observe"), self.old_config)
        # Observe may reconnect while plan/preflight runs. A last budget/block or
        # queue change must be noticed before sending the cooperative stop.
        if self.identity(self.folder / "signals.sqlite") != self._stop_signals:
            fail("PREIMAGE_CHANGED")
        if getattr(self, "_stop_requires_permit", False):
            from guiyi_quant.simnow_execution import deployment_connection as permit

            marker = permit.global_marker(self.settings)
            if marker.exists() or marker.is_symlink():
                fail("ACCOUNT_UNPROVEN")
        if getattr(self, "_stop_ordinary", None):
            from guiyi_quant.simnow_execution import ordinary_takeover as ordinary

            fresh = ordinary.binding(
                self.settings,
                self.config,
                self._stop_ordinary["window"],
                datetime.fromisoformat(self._stop_ordinary["planned_at"]),
            )
            if fresh != self._stop_ordinary:
                fail("PREIMAGE_CHANGED")
        if (
            getattr(self, "_stop_historical_anchor", None) is not None
            and self._historical_anchor() != self._stop_historical_anchor
        ):
            fail("PREIMAGE_CHANGED")
        os.kill(pid, signal.SIGTERM)

    def stopped(self, snapshot):
        try:
            os.kill(snapshot["host"]["pid"], 0)
            return False
        except ProcessLookupError:
            pass
        status = json.loads(private(self.folder / "continuous.json").read_bytes())
        return (
            status["status"] == "STOPPED"
            and status["run_id"] == snapshot["host"]["run_id"]
        )

    @contextlib.contextmanager
    def offline_guard(self, snapshot):
        fds = []
        expected = snapshot["preimage"]["locks"]
        if len(self.locks) != 2 or [str(p) for p in self.locks] != [
            v["path"] for v in expected
        ]:
            fail("PREIMAGE_CHANGED")
        try:
            for path, identity in zip(self.locks, expected, strict=True):
                private(path)
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                fds.append(fd)
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino) != (
                    identity["device"],
                    identity["inode"],
                ):
                    fail("PREIMAGE_CHANGED")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    fail("WRITER_NOT_IDLE")
            if snapshot.get("ordinary_permit"):
                self._verify_historical_anchor(snapshot)
            self._offline_held = True
            yield
        finally:
            self._offline_held = False
            for fd in reversed(fds):
                os.close(fd)

    def offline_preflight(self, snapshot):
        # preflight_trade tests lock idleness itself, so call before holding the
        # guard would race. Guard proves idle and serializes this exact check.
        if not getattr(self, "_offline_held", False) or not self.stopped(snapshot):
            fail("STOP_UNPROVEN")
        self.code_check()
        current = self._preimage()
        if snapshot.get("ordinary_permit"):
            self._verify_historical_anchor(snapshot)
            current["historical_contract_anchor"] = snapshot[
                "historical_contract_anchor"
            ]
        account = self._account(stopped_snapshot=snapshot)
        p = snapshot["preimage"]
        unchanged = same_preimage(
            dict(account=p["account"]), dict(account=account)
        ) and all(current[k] == p[k] for k in current)
        connection_anchor = None
        if getattr(self.settings, "account_takeover_pending", False) and unchanged:
            from guiyi_quant.simnow_execution import deployment_connection as permit

            connection_anchor = permit.account_anchor(self.settings)
        return dict(
            connection_anchor=connection_anchor,
            writer_idle=True,
            protected_state_unchanged=unchanged,
            native_prefix_unchanged=unchanged,
            native_appended_count=len(
                account["databases"]["native-evidence.sqlite"]["rows"]
            )
            - len(p["account"]["databases"]["native-evidence.sqlite"]["rows"]),
            preimage=p if unchanged else None,
        )

    def install(self, snapshot):
        if getattr(self, "ordinary", False):
            loaded = self._label_loaded()
            if loaded is None and not getattr(self, "_recovery", False):
                fail("INSTALL_UNPROVEN")
            if loaded is not None:
                r = self.run(["/bin/launchctl", "bootout", self.label])
                if r.returncode or self._label_loaded() is not None:
                    fail("INSTALL_UNPROVEN")
        else:
            r = self.run(["/bin/launchctl", "bootout", self.label])
            if r.returncode or self._label_loaded() is not None:
                fail("INSTALL_UNPROVEN")
        # Private preimages are retained by the prepared deployment directory.
        # Durable intent makes any intermediate cross-file state non-retryable.
        for original in (self.plist, self.monitor, self.old_config):
            suffix = (
                ".ordinary-"
                + hashlib.sha256(self.config.read_bytes()).hexdigest()[:16]
                + ".preimage"
                if getattr(self, "ordinary", False)
                else ".trade-switch-preimage"
            )
            backup = original.with_name(original.name + suffix)
            raw = original.read_bytes()
            fd = os.open(
                backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        self._replace(self.plist, self.candidate_plist.read_bytes())
        if getattr(self.settings, "account_takeover_pending", False):
            raw = self.monitor_source()
            if (
                hashlib.sha256(raw).hexdigest()
                != snapshot["preimage"]["monitor_target_sha256"]
            ):
                fail("PREIMAGE_CHANGED")
            self._replace(self.monitor, raw)
        return True

    @staticmethod
    def _replace(path, raw):
        private(path)
        temporary = path.with_name(path.name + ".trade-switch-pending")
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _restore_source(self, original, identity):
        backup = original.with_name(original.name + ".trade-switch-preimage")
        source = backup if backup.exists() else original
        if self.identity(source)["sha256"] != identity["sha256"]:
            fail("PREIMAGE_CHANGED")
        return source

    def recovery_preflight(self, snapshot):
        if getattr(self, "ordinary", False):
            fail("UNKNOWN_STAGE")
        self.old_config = Path(snapshot["old_config_path"])
        self.code_check()
        old_cfg = json.loads(private(self.old_config).read_bytes())
        if (
            self.identity(
                Path(old_cfg["project_root"]) / "scripts/broker/simnow_supervisor.py",
                interpreter=True,
            )
            != snapshot["preimage"]["old_runner"]
            or self.identity(Path(old_cfg["sdk_python"]), interpreter=True)
            != snapshot["preimage"]["old_sdk"]
        ):
            fail("PREIMAGE_CHANGED")
        if (
            self.release_identity(Path(old_cfg["project_root"]))
            != snapshot["preimage"]["old_release"]
        ):
            fail("PREIMAGE_CHANGED")
        try:
            os.kill(snapshot["host"]["pid"], 0)
        except ProcessLookupError:
            pass
        else:
            fail("HOST_UNPROVEN")
        loaded = self._label_loaded()
        if loaded is not None and re.search(r"^\s*pid = (\d+)", loaded.stdout, re.M):
            fail("HOST_UNPROVEN")
        with self.offline_guard(snapshot):
            account = self._account(
                restoring=True, frozen_index=snapshot["observe_index"]
            )
            if account["remaining_attempts"] < 1 or account["day_blocked"]:
                fail("ACCOUNT_UNPROVEN")
            if not same_preimage(
                dict(account=snapshot["account"]), dict(account=account)
            ):
                fail("PREIMAGE_CHANGED")
            for original, identity in (
                (self.plist, snapshot["preimage"]["old_plist"]),
                (self.monitor, snapshot["preimage"]["monitor"]),
                (self.old_config, snapshot["preimage"]["old_config"]),
            ):
                self._restore_source(original, identity)

    def recover(self, snapshot):
        if getattr(self, "ordinary", False):
            fail("UNKNOWN_STAGE")
        self.recovery_preflight(snapshot)
        with self.offline_guard(snapshot):
            loaded = self._label_loaded()
            if loaded is not None:
                if self.run(["/bin/launchctl", "bootout", self.label]).returncode:
                    fail("INSTALL_UNPROVEN")
            if self._label_loaded() is not None:
                fail("HOST_UNPROVEN")
            for original, identity in (
                (self.plist, snapshot["preimage"]["old_plist"]),
                (self.monitor, snapshot["preimage"]["monitor"]),
            ):
                source = self._restore_source(original, identity)
                if source != original:
                    self._replace(original, source.read_bytes())
        started = time.time()
        if self.run(
            ["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", self.plist]
        ).returncode:
            fail("START_UNPROVEN")
        old_plist = plistlib.loads(self.plist.read_bytes())
        args = old_plist["ProgramArguments"]
        old_config = Path(args[args.index("--config") + 1])
        deadline = time.monotonic() + 35
        previous = None
        rounds = 0
        while time.monotonic() < deadline:
            try:
                pid = self._pid()
                self._prove(pid, "observe", old_config)
                status = json.loads(
                    private(self.folder / "continuous.json").read_bytes()
                )
                index = json.loads(
                    private(self.settings.state_root / "monitor.json").read_bytes()
                )
                pair = pid, status["run_id"]
                valid = (
                    status["mode"] == "observe"
                    and not status["opening_enabled"]
                    and status["run_id"] != snapshot["host"]["run_id"]
                    and index["run_id"] == status["run_id"]
                    and index["mode"] == "observe"
                    and datetime.fromisoformat(status["at"]).timestamp() >= started
                )
                rounds = (
                    rounds + 1
                    if valid and (previous is None or previous == pair)
                    else 0
                )
                previous = pair
                if rounds >= 2:
                    return dict(
                        verified=True, mode="observe", pid=pid, run_id=status["run_id"]
                    )
            except SwitchError:
                pass
            time.sleep(1)
        fail("READBACK_UNPROVEN")

    def _profile(self):
        from guiyi_quant.simnow_execution.ordinary_takeover import profile_binding

        return profile_binding(self.settings)

    def issue_ordinary_permit(self, snapshot, plan_hash, intent_path):
        self._verify_historical_anchor(snapshot)
        from guiyi_quant.simnow_execution import ordinary_takeover as ordinary

        return ordinary.issue(
            self.settings,
            snapshot["ordinary_permit"],
            plan_hash,
            intent_path,
            datetime.now(UTC),
            clock=lambda: datetime.now(UTC),
        )

    def issue_connection_permit(self, snapshot, plan_hash, intent_path):
        from guiyi_quant.simnow_execution import deployment_connection as permit

        return permit.issue(
            self.settings,
            snapshot["connection_permit"],
            plan_hash,
            intent_path,
            datetime.now(UTC),
            clock=lambda: datetime.now(UTC),
        )

    def start(self, snapshot):
        if snapshot.get("ordinary_permit"):
            self._verify_historical_anchor(snapshot)
        self.code_check()
        if (
            self.identity(self.settings.sdk_python, interpreter=True)
            != snapshot["preimage"]["sdk"]
        ):
            fail("PREIMAGE_CHANGED")
        if not self.window_open():
            fail("WINDOW_UNPROVEN")
        self.started_at = time.time()
        return (
            self.run(
                ["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", self.plist]
            ).returncode
            == 0
        )

    def monitor_bound(self, snapshot):
        if getattr(self.settings, "account_takeover_pending", False):
            return (
                hashlib.sha256(private(self.monitor).read_bytes()).hexdigest()
                == snapshot["preimage"]["monitor_target_sha256"]
                and self.monitor.read_bytes() == self.monitor_source()
            )
        return (
            self.identity(self.monitor) == snapshot["preimage"]["monitor"]
            and json.loads(self.monitor.read_bytes())["account_id"]
            == self.settings.account_id
            and json.loads(self.monitor.read_bytes())["state_root"]
            == str(self.settings.state_root)
            and json.loads(self.monitor.read_bytes())["mode"] == "observe"
        )

    def readback(self, snapshot):
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            try:
                pid = self._pid()
                self._prove(pid, "trade", self.config)
                status = json.loads(
                    private(self.folder / "continuous.json").read_bytes()
                )
                index = json.loads(
                    private(self.settings.state_root / "monitor.json").read_bytes()
                )
                if (
                    status["mode"] == "trade"
                    and status["run_id"] != snapshot["host"]["run_id"]
                    and status["run_id"] == index["run_id"]
                    and index["mode"] == "trade"
                    and index["account_id"] == self.settings.account_id
                    and index.get("host_status") == status["status"]
                    and datetime.fromisoformat(status["at"]).timestamp()
                    >= self.started_at
                ):
                    break
            except SwitchError:
                pass
            time.sleep(0.25)
        else:
            fail("READBACK_UNPROVEN")
        if getattr(self.settings, "account_takeover_pending", False):
            from guiyi_quant.simnow_execution import deployment_connection as permit

            ordinary_path = getattr(self.settings, "ordinary_takeover_permit", None)
            permit_path = ordinary_path or self.settings.deployment_connection_permit
            claim, _ = permit.read(Path(str(permit_path) + ".run-claim"))
            intent, _ = permit.read(
                Path(permit_path).parent
                / (
                    "ordinary-recovery-intent.private.json"
                    if getattr(self, "_recovery", False)
                    else "switch-intent.private.json"
                )
            )
            if (
                claim.get("run_id") != status["run_id"]
                or claim.get("pid") != pid
                or claim.get("grant_sha256")
                != intent.get(
                    "ordinary_grant_sha256"
                    if ordinary_path
                    else "connection_grant_sha256"
                )
                or status.get("account_takeover_pending") is not True
                or status.get("opening_enabled") is not False
            ):
                fail("READBACK_UNPROVEN")
        return dict(
            verified=True,
            account_takeover_pending=status.get("account_takeover_pending", False),
            opening_enabled=status.get("opening_enabled", False),
            mode=status["mode"],
            pid=pid,
            run_id=status["run_id"],
            dual_locks_held_by_pid=True,
            config_bound=self.plist.read_bytes() == self.candidate_plist.read_bytes(),
            monitor_bound=self.monitor_bound(snapshot),
        )


def dependency_environment(code):
    """Load only the runner's allowlisted dependency settings; never print them."""
    sys.path[:0] = [str(code / "services/quant-api"), str(code / "packages/quant-core")]
    from app.private_settings import private_dependency_settings

    spec = importlib.util.spec_from_file_location(
        "switch_runner", code / "scripts/broker/simnow_supervisor.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    env, _ = private_dependency_settings(
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    )
    os.environ.update(runner.dependency_environment(env))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="One-shot SimNow switch (default read-only plan)"
    )
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--tag")
    parser.add_argument(
        "--window", choices=("ordinary", "night", "midday"), default="ordinary"
    )
    parser.add_argument("--candidate-plist", type=Path)
    parser.add_argument("--plan", type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--readback", action="store_true")
    actions.add_argument("--apply", action="store_true")
    actions.add_argument("--recover-observe", action="store_true")
    actions.add_argument("--plan-stopped-recovery", action="store_true")
    actions.add_argument("--recover-pending-trade", action="store_true")
    parser.add_argument("--source-intent", type=Path)
    parser.add_argument("--recovery-intent", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.readback:
            print(
                json.dumps(Coordinator(None, args.state_dir).readback(), sort_keys=True)
            )
            return 0
        if not args.config or not args.candidate_plist or not args.tag:
            fail("PLAN_INVALID")
        backend = MacBackend(
            args.config, args.candidate_plist, tag=args.tag, window=args.window
        )
        if os.environ.get("GUIYI_SIMNOW_SWITCH_DEPENDENCIES_READY") != "1":
            dependency_environment(backend.code)
            os.environ["GUIYI_SIMNOW_SWITCH_DEPENDENCIES_READY"] = "1"
            os.execv(
                sys.executable,
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve()),
                    *(sys.argv[1:] if argv is None else argv),
                ],
            )
        coordinator = Coordinator(backend, args.state_dir)
        if args.plan_stopped_recovery:
            if not args.source_intent or not args.plan:
                fail("PLAN_INVALID")
            result = coordinator.plan_recovery(args.source_intent)
            write_private(args.plan, result, exclusive=True)
            print(
                json.dumps(
                    dict(
                        status="RECOVERY_PLAN_READY",
                        plan_hash=result["plan_hash"],
                        broker_io=False,
                    )
                )
            )
        elif args.recover_pending_trade:
            if not args.plan:
                fail("PLAN_INVALID")
            print(
                json.dumps(
                    coordinator.recover_pending_trade(
                        json.loads(private(args.plan).read_bytes())
                    ),
                    sort_keys=True,
                )
            )
        elif args.check:
            result = backend._window()
            print(
                json.dumps(
                    dict(
                        status="WINDOW_PREFLIGHT",
                        code="WINDOW_OPEN"
                        if result["window_open"]
                        else "WINDOW_UNPROVEN",
                        execution_permitted=False,
                        broker_io=False,
                        **result,
                    ),
                    sort_keys=True,
                )
            )
        elif args.recover_observe:
            print(json.dumps(coordinator.recover(), sort_keys=True))
        elif args.apply:
            if args.plan is None:
                fail("PLAN_INVALID")
            result = coordinator.apply(json.loads(private(args.plan).read_bytes()))
            print(json.dumps(result, sort_keys=True))
        else:
            result = coordinator.plan()
            if args.plan:
                private(args.plan.parent, directory=True)
                write_private(args.plan, result, exclusive=True)
            # No account IDs, paths, raw native facts or config enter stdout.
            print(
                json.dumps(
                    dict(
                        status="PLAN_READY",
                        schema=SCHEMA,
                        window_policy=result["window_policy"],
                        plan_hash=result["plan_hash"],
                        expires_at=result["expires_at"],
                        broker_io=False,
                    )
                )
            )
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, SwitchError) else "RESULT_UNKNOWN"
        print(json.dumps(dict(status="BLOCKED", code=code)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
