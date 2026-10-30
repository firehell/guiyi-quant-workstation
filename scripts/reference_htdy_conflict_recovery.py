#!/usr/bin/env python3
"""Exact HTDY conflict recovery: default read-only; success leaves Reference parked."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from time import monotonic, sleep

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "services/quant-api"), str(ROOT / "packages/quant-core")]
VERSION = "reference_htdy_conflict_cli_v1"
FROZEN_INVENTORY_SHA256 = (
    "190ec36403d5fb0cb7617bd64ce88d117098acc628588b29b5b4258af0c19c16"
)
FROZEN_SCOPE_SHA256 = "839198f75e2e0b6fd3050f3b9f252645b83640d5faa9629342739eb6e3206704"
FROZEN_OPEN_SCOPE_SHA256 = (
    "bf7c5fcb5478fe17119435eee09190f2fa167b6a444a2bcba7ab9295e72ebc4a"
)


def fail(code):
    raise ValueError(code)


def digest(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def instant(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        fail("RECOVERY_TIME_INVALID")
    return result


def read_private(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
        fail("RECOVERY_PRIVATE_FILE_REQUIRED")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 16 * 1024 * 1024
        ):
            fail("RECOVERY_PRIVATE_FILE_REQUIRED")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) != info.st_size:
            fail("RECOVERY_FILE_CHANGED")
        return raw
    finally:
        os.close(fd)


def put(path, value):
    path = Path(path)
    if not path.is_absolute() or path.parent.resolve() != path.parent:
        fail("RECOVERY_PATH_INVALID")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def checked_scope(ids):
    result = tuple(sorted(ids))
    if (
        len(result) != 48
        or len(set(result)) != 48
        or digest(list(result)) != FROZEN_SCOPE_SHA256
    ):
        fail("RECOVERY_FROZEN_SCOPE_REQUIRED")
    return result


def frozen_scope(path):
    raw = read_private(path)
    if sha256(raw).hexdigest() != FROZEN_INVENTORY_SHA256:
        fail("RECOVERY_INVENTORY_DRIFT")
    value = json.loads(raw)
    rows = [r for r in value["items"] if r["pending"]]
    opened = sorted(r["stream_id"] for r in rows if r["reference_open"] is True)
    if len(opened) != 20 or digest(opened) != FROZEN_OPEN_SCOPE_SHA256:
        fail("RECOVERY_OPEN_SCOPE_DRIFT")
    if any(
        r.get("evaluation") != "OBSERVATION_GAP"
        or r.get("endpoint_shift_equal") is not True
        for r in rows
    ):
        fail("RECOVERY_FROZEN_SCOPE_REQUIRED")
    return checked_scope(r["stream_id"] for r in rows)


def frozen_open_trades(domain):
    result = []
    for item in domain["items"]:
        binding = item["binding"]
        opened = binding["checkpoint"]["reference_state"]["open_trade"]
        if opened is None:
            continue
        trade_id = opened["reference_trade_id"]
        if not isinstance(trade_id, str) or not trade_id:
            fail("RECOVERY_OPEN_ID_INVALID")
        result.append(
            dict(
                stream_id=binding["stream_id"],
                revision_id=binding["revision_id"],
                checkpoint_sha256=binding["checkpoint_sha256"],
                reference_trade_id=trade_id,
                open_trade_sha256=digest(opened),
            )
        )
    result.sort(key=lambda row: row["stream_id"])
    if (
        len(result) != 20
        or len({r["reference_trade_id"] for r in result}) != 20
        or digest([r["stream_id"] for r in result]) != FROZEN_OPEN_SCOPE_SHA256
    ):
        fail("RECOVERY_OPEN_SCOPE_DRIFT")
    return result


class Coordinator:
    def __init__(self, backend, directory, *, clock=lambda: datetime.now(UTC)):
        self.backend, self.directory, self.clock = backend, Path(directory), clock

    def _directory(self, *, create=False):
        p = self.directory
        if not p.is_absolute() or p.parent.resolve() != p.parent or p.is_symlink():
            fail("RECOVERY_ATTEMPT_INVALID")
        if create:
            p.mkdir(mode=0o700)
            put(
                p / "identity.json",
                dict(schema=VERSION, identity=self.backend.identity()),
            )
        info = p.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            fail("RECOVERY_ATTEMPT_INVALID")
        return json.loads(read_private(p / "identity.json"))

    def _ensure_attempt(self):
        if not self.directory.exists():
            self._directory(create=True)
        prior = self._directory()
        if prior != {"schema": VERSION, "identity": self.backend.identity()}:
            fail("RECOVERY_ATTEMPT_IDENTITY_DRIFT")

    def _fresh(self, p):
        now = self.clock()
        if (
            not instant(p["created_at"])
            <= now
            < instant(p["expires_at"])
            <= instant(p["recording_start"])
        ):
            fail("RECOVERY_PLAN_EXPIRED")
        self.backend.check_window()
        if not instant(p["created_at"]) <= self.clock() < instant(p["expires_at"]):
            fail("RECOVERY_PLAN_EXPIRED")

    def _load(self, path, expected=None, *, historical=False):
        p = json.loads(read_private(path))
        if p.get("schema") != VERSION or digest(
            {k: v for k, v in p.items() if k != "plan_hash"}
        ) != p.get("plan_hash"):
            fail("RECOVERY_PLAN_INVALID")
        if expected is not None and expected != p["plan_hash"]:
            fail("RECOVERY_PLAN_HASH_CONFLICT")
        checked_scope(p["stream_ids"])
        if p["inventory_sha256"] != FROZEN_INVENTORY_SHA256 or p["attempt_dir"] != str(
            self.directory
        ):
            fail("RECOVERY_PLAN_SCOPE_DRIFT")
        domain_ids = [v["binding"]["stream_id"] for v in p["domain_plan"]["items"]]
        if checked_scope(domain_ids) != checked_scope(p["stream_ids"]):
            fail("RECOVERY_PLAN_SCOPE_DRIFT")
        if p.get("open_trades") != frozen_open_trades(p["domain_plan"]):
            fail("RECOVERY_OPEN_SCOPE_DRIFT")
        current = self.backend.identity()
        keys = (
            ("root", "commit", "tag", "config_sha256") if historical else tuple(current)
        )
        if any(p["identity"].get(k) != current[k] for k in keys):
            fail("RECOVERY_CODE_OR_CONFIG_DRIFT")
        prior = self._directory()
        if prior["identity"] != p["identity"]:
            fail("RECOVERY_ATTEMPT_IDENTITY_DRIFT")
        bound = json.loads(read_private(self.directory / "plan-bound.json"))
        if bound != {"plan_hash": p["plan_hash"], "plan_path": str(Path(path))}:
            fail("RECOVERY_PLAN_BINDING_DRIFT")
        return p

    def plan(self, path, ids, *, inventory_sha256, recording_start, expires_at):
        ids = checked_scope(ids)
        now = self.clock()
        if (
            inventory_sha256 != FROZEN_INVENTORY_SHA256
            or not now < expires_at <= recording_start
        ):
            fail("RECOVERY_PLAN_INVALID")
        self.backend.check_window()
        with self.backend.fenced() as recovery:
            self.backend.check_window()
            domain = recovery.plan(
                ids,
                recording_start=recording_start,
                expires_at=expires_at,
                now=self.clock(),
            )
            if not self.clock() < expires_at <= recording_start:
                fail("RECOVERY_PLAN_EXPIRED")
            self.backend.check_window()
            if not self.clock() < expires_at <= recording_start:
                fail("RECOVERY_PLAN_EXPIRED")
            self._ensure_attempt()
            value = dict(
                schema=VERSION,
                identity=self.backend.identity(),
                stream_ids=list(ids),
                inventory_sha256=inventory_sha256,
                attempt_dir=str(self.directory),
                created_at=now.isoformat(),
                expires_at=expires_at.isoformat(),
                recording_start=recording_start.isoformat(),
                domain_plan=domain,
                open_trades=frozen_open_trades(domain),
            )
            result = {**value, "plan_hash": digest(value)}
            put(
                self.directory / "plan-bound.json",
                dict(plan_hash=result["plan_hash"], plan_path=str(Path(path))),
            )
            put(path, result)
            return result

    def apply(self, path, *, expected_plan_hash):
        p = self._load(path, expected_plan_hash)
        self._fresh(p)
        with self.backend.fenced() as recovery:
            self._fresh(p)
            put(
                self.directory / "apply-claim.json",
                dict(
                    schema=VERSION,
                    plan_hash=p["plan_hash"],
                    identity=p["identity"],
                    at=self.clock().isoformat(),
                ),
            )
            try:
                self._fresh(p)
                result = recovery.apply(
                    p["domain_plan"],
                    expected_plan_hash=p["domain_plan"]["plan_hash"],
                    now=self.clock(),
                )
                if recovery.readback(p["domain_plan"]) != result:
                    fail("RECOVERY_COMMIT_UNPROVEN")
                receipt = dict(
                    status="COMMITTED",
                    plan_hash=p["plan_hash"],
                    streams=len(result),
                    reference_must_remain_parked=True,
                )
                put(self.directory / "receipt.json", receipt)
                return receipt
            except Exception:
                # Claim is durable even if the DB result or final fsync is unknown.
                raise ValueError("RECOVERY_OUTCOME_UNKNOWN_READBACK_REQUIRED") from None

    def status(self, path, *, expected_plan_hash):
        p = self._load(path, expected_plan_hash, historical=True)
        claimed = (self.directory / "apply-claim.json").exists()
        if claimed:
            claim = json.loads(read_private(self.directory / "apply-claim.json"))
            if any(
                claim.get(k) != v
                for k, v in {
                    "schema": VERSION,
                    "plan_hash": p["plan_hash"],
                    "identity": p["identity"],
                }.items()
            ):
                fail("RECOVERY_CLAIM_DRIFT")
        result = self.backend.readback(p["domain_plan"])
        return dict(
            status="COMMITTED"
            if result is not None
            else "UNKNOWN_NO_COMMIT_PROVEN"
            if claimed
            else "NOT_APPLIED",
            plan_hash=p["plan_hash"],
            streams=len(result) if result is not None else 0,
            readonly=True,
            reference_must_remain_parked=True,
        )

    def park(self, expires_at):
        self.backend.check_window()
        if not self.clock() < expires_at:
            fail("RECOVERY_PLAN_EXPIRED")
        self._ensure_attempt()
        put(
            self.directory / "park-intent.json",
            dict(
                schema=VERSION,
                identity=self.backend.identity(),
                expires_at=expires_at.isoformat(),
            ),
        )
        proof = self.backend.park(expires_at)
        put(self.directory / "parked.json", proof)
        return dict(status="REFERENCE_PARKED", reference_must_remain_parked=True)


def verify_code(root, commit, tag):
    if (
        Path(root) != ROOT
        or ROOT.resolve() != ROOT
        or not re.fullmatch("[0-9a-f]{40}", commit)
        or not re.fullmatch(r"v\d+\.\d+\.\d+", tag)
    ):
        fail("RECOVERY_EXACT_CODE_INVALID")

    def git(*args):
        r = subprocess.run(
            ["/usr/bin/git", "-c", "core.fsmonitor=false", "-C", str(ROOT), *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode:
            fail("RECOVERY_EXACT_CODE_INVALID")
        return r.stdout.strip()

    if (
        git("rev-parse", "HEAD") != commit
        or git("rev-parse", tag + "^{}") != commit
        or git("cat-file", "-t", "refs/tags/" + tag) != "tag"
        or git("status", "--porcelain", "--untracked-files=all")
    ):
        fail("RECOVERY_EXACT_CODE_INVALID")


def load_dependencies():
    from app.private_settings import private_dependency_settings

    env, identity = private_dependency_settings(
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    )
    # Match the existing local-service controller context before API imports or
    # re-exec. Loading project.env alone can reset Redis to its unauthenticated
    # default. Keep the identity bound to the original private file bytes.
    from urllib.parse import quote

    env = dict(env)
    if env.get("REDIS_URL") in (None, "", "redis://127.0.0.1:6379/0"):
        password = env.get("REDIS_PASSWORD") or env.get("POSTGRES_PASSWORD")
        if not isinstance(password, str) or not password:
            fail("RECOVERY_DEPENDENCIES_INVALID")
        env["REDIS_PASSWORD"] = password
        env["REDIS_URL"] = "redis://:" + quote(password, safe="") + "@127.0.0.1:6379/0"
    env["GUIYI_RUNTIME_HANDOVER_ENABLED"] = "1"
    env["GUIYI_OBSERVATION_STREAM_ENABLED"] = "1"
    os.environ.update(env)
    del env
    if os.environ.get("GUIYI_HTDY_CONFLICT_CLI_READY") != "1":
        os.environ["GUIYI_HTDY_CONFLICT_CLI_READY"] = "1"
        os.execv(
            sys.executable,
            [sys.executable, "-B", str(Path(__file__).resolve()), *sys.argv[1:]],
        )
    return identity["config_sha256"]


class MacBackend:
    def __init__(self, args, config_sha):
        from app.runtime_bindings import resolve_service_binding, bindings_sha256
        from app.runtime_handover import runtime_directory

        self.args = args
        self.directory = runtime_directory()
        self.binding = resolve_service_binding("reference-worker")
        if self.binding is None or not self.binding.enabled:
            fail("REFERENCE_WORKER_NOT_ENABLED")
        self._identity = dict(
            root=str(ROOT),
            commit=args.exact_commit,
            tag=args.tag,
            config_sha256=config_sha,
            reference_binding=asdict(self.binding),
            registry_sha256=bindings_sha256(),
        )
        spec = importlib.util.spec_from_file_location(
            "conflict_existing_guard",
            ROOT / "scripts/reference_observation_recovery.py",
        )
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        self.guarded = old.parked_reference_guard

    def identity(self):
        return self._identity

    def check_window(self):
        from app.runtime_cohort_host import CohortHost
        from app.private_settings import read_private_settings_content
        from app.runtime_bindings import resolve_service_binding, bindings_sha256

        verify_code(ROOT, self.args.exact_commit, self.args.tag)
        content = read_private_settings_content(
            Path.home() / "Library/Application Support/GuiyiQuant/project.env"
        )
        if sha256(content).hexdigest() != self._identity["config_sha256"]:
            fail("RECOVERY_CODE_OR_CONFIG_DRIFT")
        binding = resolve_service_binding("reference-worker")
        if (
            binding is None
            or asdict(binding) != self._identity["reference_binding"]
            or bindings_sha256() != self._identity["registry_sha256"]
        ):
            fail("RECOVERY_RUNTIME_BINDING_DRIFT")

        proof = CohortHost().session_proof()
        if proof.get("mode") != "closed_idle" or len(proof.get("phases", {})) != 60:
            fail("RECOVERY_REST_WINDOW_REQUIRED")
        fresh_now = datetime.now(UTC)
        for phase in proof["phases"].values():
            if (
                phase.get("phase") not in {"CLOSED", "BREAK"}
                or phase.get("current_session") is not None
                or instant(phase["next_session_start"])
                <= fresh_now + timedelta(seconds=660)
            ):
                fail("RECOVERY_REST_WINDOW_REQUIRED")
        return proof

    @contextmanager
    def fenced(self):
        from app.db.session import SessionLocal
        from app.db.readonly import readonly_transaction
        from app.market_data.composition import build_market_data_service
        from app.reference_trading.forward_authority import ForwardMarketAuthority
        from app.reference_trading.htdy_conflict_source import HtdyConflictSource
        from app.reference_trading.htdy_conflict_recovery import HtdyConflictRecovery

        self.check_window()
        with self.guarded(
            directory=self.directory, expected_binding=asdict(self.binding)
        ) as (assert_guard, _):
            with SessionLocal() as db, readonly_transaction(db, timeout_seconds=300):
                mds = build_market_data_service(db)
                lease = mds.catalog.acquire_maintenance_lock()
                if lease is None:
                    fail("SOURCE_BUSY")

                def fenced():
                    assert_guard()
                    self.check_window()

                try:
                    fenced()
                    yield HtdyConflictRecovery(
                        SessionLocal,
                        verify_source=HtdyConflictSource(
                            mds, ForwardMarketAuthority(mds)
                        ),
                        assert_fenced=fenced,
                        clock=lambda: datetime.now(UTC),
                    )
                finally:
                    lease.release()

    def readback(self, plan):
        from app.db.session import SessionLocal
        from app.db.readonly import readonly_transaction
        from app.reference_trading.htdy_conflict_recovery import HtdyConflictRecovery

        @contextmanager
        def factory():
            with SessionLocal() as db, readonly_transaction(db, timeout_seconds=60):
                yield db

        def forbidden(*_):
            fail("READBACK_MUTATION_FORBIDDEN")

        return HtdyConflictRecovery(
            factory, verify_source=forbidden, assert_fenced=forbidden
        ).readback(plan)

    def park(self, expires_at):
        from app.runtime_handover import (
            read_service_state,
            request_drain,
            deployment_lock,
            _read,
        )

        self.check_window()
        with deployment_lock(runtime_dir=self.directory):
            owner = read_service_state("reference-worker", runtime_dir=self.directory)
            if owner is None or owner.get("generation") != self.binding.generation:
                fail("RECOVERY_OWNER_UNPROVEN")
            handover = _read(self.directory / "reference-worker.handover.json")
            if owner.get("phase") == "parked":
                if (
                    not handover
                    or handover.get("phase") != "drain"
                    or handover.get("generation") != self.binding.generation
                    or owner.get("ready") is not False
                ):
                    fail("RECOVERY_PARKED_OWNER_REQUIRED")
                return dict(status="PARKED_ALREADY", request_id=handover["request_id"])
            if handover and handover.get("phase") == "drain":
                fail("RECOVERY_EXISTING_DRAIN_UNPROVEN")
            self.check_window()
            if datetime.now(UTC) >= expires_at:
                fail("RECOVERY_PLAN_EXPIRED")
            request = request_drain(
                "reference-worker",
                generation=self.binding.generation,
                runtime_dir=self.directory,
            )
        deadline = monotonic() + 60
        while monotonic() < deadline:
            if datetime.now(UTC) >= expires_at:
                fail("RECOVERY_PARK_UNKNOWN")
            owner = read_service_state("reference-worker", runtime_dir=self.directory)
            if (
                owner
                and owner.get("phase") == "parked"
                and owner.get("generation") == self.binding.generation
                and owner.get("ready") is False
            ):
                return dict(status="PARKED", request_id=request, pid=owner.get("pid"))
            sleep(0.25)
        fail("RECOVERY_PARK_UNKNOWN")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    for action in ("plan", "apply", "status", "park"):
        modes.add_argument("--" + action, action="store_true")
    parser.add_argument("--exact-root", type=Path)
    parser.add_argument("--exact-commit")
    parser.add_argument("--tag")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--attempt-dir", type=Path)
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--expected-plan-hash")
    parser.add_argument("--recording-start")
    parser.add_argument("--expires-at")
    args = parser.parse_args(argv)
    if not any((args.plan, args.apply, args.status, args.park)):
        print(json.dumps(dict(status="READ_ONLY_NO_ACTION", readonly=True)))
        return 0
    try:
        if (
            not args.exact_root
            or not args.exact_commit
            or not args.tag
            or not args.attempt_dir
        ):
            fail("RECOVERY_ARGUMENTS_REQUIRED")
        verify_code(args.exact_root, args.exact_commit, args.tag)
        config_sha = load_dependencies()
        backend = MacBackend(args, config_sha)
        runner = Coordinator(backend, args.attempt_dir)
        if args.park:
            if not args.expires_at:
                fail("RECOVERY_ARGUMENTS_REQUIRED")
            result = runner.park(instant(args.expires_at))
        else:
            if not args.plan_file:
                fail("RECOVERY_ARGUMENTS_REQUIRED")
            if args.plan:
                if (
                    not args.inventory
                    or not args.recording_start
                    or not args.expires_at
                ):
                    fail("RECOVERY_ARGUMENTS_REQUIRED")
                result = runner.plan(
                    args.plan_file,
                    frozen_scope(args.inventory),
                    inventory_sha256=FROZEN_INVENTORY_SHA256,
                    recording_start=instant(args.recording_start),
                    expires_at=instant(args.expires_at),
                )
                result = dict(
                    status="PLANNED",
                    plan_hash=result["plan_hash"],
                    domain_plan_hash=result["domain_plan"]["plan_hash"],
                    readonly=True,
                )
            else:
                if not args.expected_plan_hash:
                    fail("RECOVERY_ARGUMENTS_REQUIRED")
                result = (runner.apply if args.apply else runner.status)(
                    args.plan_file, expected_plan_hash=args.expected_plan_hash
                )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps(dict(status="BLOCKED", code="HTDY_CONFLICT_CLI_UNPROVEN")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
