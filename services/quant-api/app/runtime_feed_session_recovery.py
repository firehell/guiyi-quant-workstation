"""One-shot same-version Feed recovery from externally verified empty retirement.

This does not promote code, retry close, reset journals, or operate SimNow.
"""

from __future__ import annotations

import argparse
import base64
import gzip
from dataclasses import asdict
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

VERSION = "feed_verified_empty_retirement_v1"
COMMIT = "3e8229fe8cf2da1bd9f14d5035a32136199c0025"
OLD_DAY = date(2026, 11, 2)
DAY = date(2026, 11, 3)


class RecoveryError(ValueError):
    pass


def require(value, code="FEED_RECOVERY_UNPROVEN"):
    if not value:
        raise RecoveryError(code)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def fsync_parent(path):
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write(path, value, *, exclusive=False):
    from app.runtime_handover import _write

    if exclusive:
        raw = json.dumps(value, sort_keys=True).encode()
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        fsync_parent(path)
    else:
        _write(path, value)


def safe_proof(value, *, pid, now):
    try:
        at = datetime.fromisoformat(value["proof_at"]).timestamp()
        return (
            value["status"] == "READ_ONLY_INSPECTED"
            and type(value["pid"]) is int
            and value["pid"] == pid
            and value["detached"] is True
            and value["runtime_frame_bound"] is True
            and value["target_calls"] == value["target_writes"] == 0
            and value["input_failure"] == "LIVE_PROVIDER_CLOSE_UNKNOWN"
            and value["retirement_failed"] is True
            and value["provider_type"] == "RQDataLiveProvider"
            and value["close_succeeded"] is True
            and value["close_failed"] is False
            and value["closed"] is True
            and value["raw_buffer_count"] == value["pending_count"] == 0
            and type(value["raw_buffer_count"]) is int
            and type(value["pending_count"]) is int
            and value["isolation_provider_matches"] is True
            and value["isolation_snapshot_matches"] is True
            and value["isolation_day"] == OLD_DAY.isoformat()
            and 0 <= now - at <= 90
            and bool(value["object_identity"])
            and bool(value["process_identity"])
            and all(
                not row["present"] or row["native_thread_alive"] is False
                for row in value["listeners"].values()
            )
            and set(value["listeners"]) == {"_listener", "_retired_listener"}
        )
    except (KeyError, TypeError, ValueError):
        return False


class Coordinator:
    def __init__(self, backend, directory, *, clock=time.time, sleep=time.sleep):
        self.backend, self.directory, self.clock, self.sleep = (
            backend,
            Path(directory),
            clock,
            sleep,
        )
        self.state_path = self.directory / "state.json"

    def plan(self):
        require(not self.state_path.exists(), "ATTEMPT_CONSUMED")
        baseline = self.backend.snapshot()
        pid = baseline["pid"]
        proofs = [self.backend.probe(pid, "plan-1"), self.backend.probe(pid, "plan-2")]
        require(
            all(safe_proof(p, pid=pid, now=self.clock()) for p in proofs),
            "READER_CLOSURE_UNPROVEN",
        )
        require(
            proofs[0]["object_identity"] == proofs[1]["object_identity"]
            and proofs[0]["process_identity"] == proofs[1]["process_identity"]
            and proofs[0]["process_identity"] == baseline["process_identity"]
        )
        require(self.backend.snapshot() == baseline, "SOURCE_DRIFT")
        result = dict(
            version=VERSION, created_at=self.clock(), baseline=baseline, proofs=proofs
        )
        result["plan_hash"] = digest(result)
        return result

    def apply(self, plan):
        require(
            plan.get("version") == VERSION
            and plan.get("plan_hash")
            == digest({k: v for k, v in plan.items() if k != "plan_hash"}),
            "PLAN_INVALID",
        )
        require(0 <= self.clock() - plan["created_at"] <= 300, "PLAN_EXPIRED")
        require(not self.state_path.exists(), "ATTEMPT_CONSUMED")
        with self.backend.guard():
            original = plan["baseline"]
            pid = original["pid"]
            require(self.backend.snapshot() == original, "SOURCE_DRIFT")
            proofs = [
                self.backend.probe(pid, "apply-1"),
                self.backend.probe(pid, "apply-2"),
            ]
            require(
                all(safe_proof(p, pid=pid, now=self.clock()) for p in proofs),
                "READER_CLOSURE_UNPROVEN",
            )
            require(
                all(
                    p["object_identity"] == plan["proofs"][0]["object_identity"]
                    and p["process_identity"] == plan["proofs"][0]["process_identity"]
                    and p["process_identity"] == original["process_identity"]
                    for p in proofs
                )
            )
            require(self.backend.snapshot() == original, "SOURCE_DRIFT")
            state = dict(
                version=VERSION,
                plan_hash=plan["plan_hash"],
                stage="DRAIN_INTENT",
                original_failure_preserved=True,
                proofs=proofs,
                at=self.clock(),
            )
            write(self.state_path, state, exclusive=True)
            try:
                require(0 <= self.clock() - plan["created_at"] <= 300, "PLAN_EXPIRED")
                request = self.backend.drain()
                state.update(stage="DRAIN_REQUESTED", request=request, at=self.clock())
                write(self.state_path, state)
                deadline = self.clock() + 120
                while not self.backend.parked(original, request):
                    require(self.clock() < deadline, "FEED_STOP_UNKNOWN")
                    self.sleep(1)
                self.backend.verify_frozen(original)
                self.sleep(1)
                require(self.backend.parked(original, request), "FEED_STOP_UNKNOWN")
                self.backend.verify_frozen(original)
                state.update(
                    stage="VERIFIED_STOPPED",
                    old_run_result="EXITED_AFTER_PREVIOUS_RETIREMENT_FAILURE",
                    at=self.clock(),
                )
                write(self.state_path, state)
                # The only cancel follows proven OS exit, a distinct parked owner,
                # two unchanged journal reads and the exact request-id check.
                state.update(stage="RESUME_INTENT", at=self.clock())
                write(self.state_path, state)
                self.backend.resume(original, request)
                state.update(stage="RESUME_REQUESTED", at=self.clock())
                write(self.state_path, state)
                deadline = self.clock() + 180
                while not (proof := self.backend.ready(original, request)):
                    require(self.clock() < deadline, "FEED_READY_UNKNOWN")
                    self.sleep(1)
                state.update(
                    stage="COMPLETE",
                    result="SAME_VERSION_FEED_RECOVERED",
                    readback=proof,
                    at=self.clock(),
                )
                write(self.state_path, state)
                return state
            except Exception:
                state.update(result="UNKNOWN", at=self.clock())
                write(self.state_path, state)
                raise


class Native:
    def __init__(self, directory):
        from app.core.env import PROJECT_ROOT
        from app.runtime_bindings import _git, verify_release, read_bindings
        from app.runtime_handover import runtime_directory

        self.code = PROJECT_ROOT
        self.home = Path.home()
        self.runtime = runtime_directory()
        self.directory = Path(directory)
        require(
            self.directory.is_absolute()
            and self.directory == self.directory.resolve()
            and self.directory.stat().st_uid == os.getuid()
            and not self.directory.stat().st_mode & 0o077
        )
        require(
            self.directory == self.runtime / "feed-session-recovery-20261103",
            "RECOVERY_DIRECTORY_INVALID",
        )
        tag = _git(self.code, "describe", "--exact-match", "--tags", "HEAD")
        commit = _git(self.code, "rev-parse", "HEAD")
        verify_release(self.code, tag, commit)
        self.controller = dict(root=str(self.code), tag=tag, commit=commit)
        registry = read_bindings()
        require(registry is not None)
        binding = registry.services["market-feed"]
        require(
            binding.tag == "v1.16.64"
            and binding.commit == COMMIT
            and binding.generation == 53
            and binding.enabled
        )
        self.active = Path(binding.root)
        verify_release(self.active, binding.tag, binding.commit)
        self.binding = asdict(binding)
        from app.redis_connections import get_redis_connection

        self.redis = get_redis_connection()

    def control(self):
        path = self.runtime / "market-feed.handover.json"
        if not path.exists():
            return dict(present=False)
        require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_uid == os.getuid()
            and not path.stat().st_mode & 0o077,
            "CONTROL_UNPROVEN",
        )
        raw = path.read_bytes()
        value = json.loads(raw)
        require(
            set(value)
            == {"schema_version", "service", "generation", "request_id", "phase"}
            and value["schema_version"] == 1
            and value["service"] == "market-feed"
            and value["generation"] == 53
            and value["phase"] == "cancelled"
            and re.fullmatch("[a-f0-9]{32}", value["request_id"]),
            "EXISTING_DRAIN_UNRESOLVED",
        )
        return dict(present=True, sha256=hashlib.sha256(raw).hexdigest(), value=value)

    def guard(self):
        from app.runtime_handover import deployment_lock

        return deployment_lock()

    def command(self, args, *, timeout=15):
        return subprocess.run(
            [str(x) for x in args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        ).stdout.strip()

    def loaded_pid(self):
        from app.runtime_identity import read_launchd_service, verify_loaded_service

        raw = read_launchd_service("com.guiyi.quant-market-feed", root=self.active)
        require(raw is not None)
        verify_loaded_service(raw, root=self.active, commit=COMMIT)
        match = re.search(r"^\s*pid = (\d+)", raw, re.M)
        require(match is not None)
        return int(match[1])

    def process_identity(self, pid):
        start = self.command(["/bin/ps", "-p", pid, "-o", "lstart="])
        command = self.command(["/bin/ps", "-p", pid, "-o", "command="])
        require(
            command
            == str(self.active / "services/quant-api/.venv/bin/python")
            + " -m app.runtime_entry market-feed"
        )
        return hashlib.sha256(f"{pid}:{start}".encode()).hexdigest()

    def processes(self):
        rows = []
        for line in self.command(
            ["/bin/ps", "-ww", "-axo", "pid=,ppid=,command="]
        ).splitlines():
            parts = line.strip().split(None, 2)
            require(len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit())
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
        return rows

    def unique_writer(self, pid):
        rows = self.processes()
        require(
            [
                p
                for p, _, cmd in rows
                if re.search(r"(?:^| )app\.runtime_entry market-feed$", cmd)
            ]
            == [pid],
            "OTHER_FEED_WRITER",
        )
        children = {p for p, parent, _ in rows if parent == pid}
        for _ in range(16):
            expanded = children | {p for p, parent, _ in rows if parent in children}
            if expanded == children:
                break
            children = expanded
        require(not children, "FEED_DESCENDANTS_UNPROVEN")

    def protected(self):
        paths = [
            self.runtime / "service-bindings.json",
            self.runtime / "run-local-service.sh",
            self.runtime / "project.env",
            self.active / ".run/after-market-status.json",
        ]
        paths += list(
            (self.home / "Library/LaunchAgents").glob("com.guiyi.quant-*.plist")
        )
        # The active original-account anchor is explicit and contains no secret.
        import plistlib

        sim_plist = self.home / "Library/LaunchAgents/com.guiyi.quant-simnow.plist"
        args = plistlib.loads(sim_plist.read_bytes())["ProgramArguments"]
        cfg_path = Path(args[args.index("--config") + 1])
        cfg = json.loads(cfg_path.read_text())
        folder = Path(cfg["state_root"]) / cfg["account_id"]
        paths += [
            cfg_path,
            self.runtime / "simnow-monitor.private.json",
            *[
                folder / n
                for n in (
                    "account.sqlite",
                    "dispatch.sqlite",
                    "native-evidence.sqlite",
                    "signals.sqlite",
                )
            ],
        ]
        for p in paths:
            require(
                p.is_absolute()
                and p == p.resolve(strict=True)
                and p.is_file()
                and not p.is_symlink()
            )
        return {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths))
        }

    def journals(self):
        from app.market_data.observation_stream import ObservationStream

        result = {}
        total = 0
        originals = {}
        for kind in ("source", "completed"):
            stream = ObservationStream(self.redis, kind=kind)
            prefix = f"live:observations:registered:{kind}:"
            consumers = sorted(
                k.decode() if isinstance(k, bytes) else k
                for k in self.redis.scan_iter(match=prefix + "*")
            )
            require(bool(consumers))
            for key in consumers:
                name = key[len(prefix) :]
                require(stream.registered_day(name) == OLD_DAY)
                require(
                    stream.cursor(name, OLD_DAY) == stream.tail(OLD_DAY),
                    "SOURCE_NOT_DRAINED",
                )
                result[key] = self.redis.get(key).decode()
            keys = [
                stream.key(OLD_DAY),
                stream.identity_key(OLD_DAY),
                *[stream.cursor_key(k[len(prefix) :], OLD_DAY) for k in consumers],
            ]
            for key in keys:
                raw = self.redis.dump(key)
                require(raw is not None, "SOURCE_ORIGINAL_MISSING")
                total += len(raw)
                require(total < 256 * 1024 * 1024)
                result[key] = hashlib.sha256(raw).hexdigest()
                originals[key] = base64.b64encode(raw).decode()
            require(
                not self.redis.exists(stream.key(DAY))
                and not self.redis.exists(stream.identity_key(DAY)),
                "TARGET_DAY_ALREADY_STARTED",
            )
        archive = self.directory / "source-originals.json.gz"
        if not archive.exists():
            payload = gzip.compress(json.dumps(originals, sort_keys=True).encode())
            fd = os.open(
                archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            fsync_parent(archive)
        frozen = json.loads(gzip.decompress(archive.read_bytes()))
        require(
            {
                k: hashlib.sha256(base64.b64decode(v, validate=True)).hexdigest()
                for k, v in frozen.items()
            }
            == {k: result[k] for k in originals},
            "SOURCE_ARCHIVE_DRIFT",
        )
        return result

    def verify_metadata(self):
        from app.db.session import SessionLocal
        from app.db.readonly import readonly_transaction
        from app.market_data.day_preparation import catalog_day_ready
        from app.market_data.operational_universe import load_operational_products

        with SessionLocal() as db, readonly_transaction(db, timeout_seconds=30):
            require(
                catalog_day_ready(db, tuple(sorted(load_operational_products())), DAY),
                "METADATA_NOT_READY",
            )

    def snapshot(self):
        from app.runtime_handover import read_service_state
        from app.runtime_bindings import read_bindings
        from app.market_data.after_market import public_after_market_status

        self.verify_metadata()
        require(asdict(read_bindings().services["market-feed"]) == self.binding)
        owner = read_service_state("market-feed")
        pid = self.loaded_pid()
        require(pid == 1772, "SOURCE_FEED_CHANGED")
        require(
            owner["phase"] == "active"
            and owner["pid"] == pid
            and owner["generation"] == 53
            and owner["ready"] is False
        )
        self.unique_writer(pid)
        status = public_after_market_status(
            json.loads((self.active / ".run/after-market-status.json").read_text())
        )
        require(
            status["last_run"]["status"] == "passed"
            and status["last_run"]["trading_day"] == OLD_DAY.isoformat()
            and status["last_run"]["live_evidence"]["cleanup_verified"] is True
        )
        require(self.redis.get("live:subscription:" + OLD_DAY.isoformat()) is None)
        require(
            not list(
                self.redis.scan_iter(match="live:bars:" + OLD_DAY.isoformat() + ":*")
            )
        )
        self.frozen_control = self.control()
        return dict(
            controller=self.controller,
            binding=self.binding,
            pid=pid,
            process_identity=self.process_identity(pid),
            control=self.frozen_control,
            protected=self.protected(),
            journals=self.journals(),
        )

    def probe(self, pid, label):
        path = self.directory / (label + ".json")
        require(not path.exists())
        self.command(
            [
                self.code / "services/quant-api/.venv/bin/python",
                "-B",
                self.code / "scripts/ops/macos/feed_runtime_diagnostic.py",
                "--pid",
                pid,
                "--runtime-root",
                self.active,
                "--output",
                path,
            ],
            timeout=90,
        )
        return json.loads(path.read_text())

    def drain(self):
        from app.runtime_handover import request_drain

        require(self.control() == self.frozen_control, "CONTROL_DRIFT")
        return request_drain("market-feed", generation=53)

    def verify_frozen(self, original):
        require(
            self.protected() == original["protected"]
            and self.journals() == original["journals"],
            "SOURCE_DRIFT",
        )

    def parked(self, original, request):
        from app.runtime_handover import read_service_state, owner_lock_available

        try:
            owner = read_service_state("market-feed")
            control = json.loads(
                (self.runtime / "market-feed.handover.json").read_text()
            )
            require(
                control["phase"] == "drain"
                and control["request_id"] == request
                and control["generation"] == 53
            )
            if self._alive(original["pid"]):
                return False
            if owner["phase"] != "parked":
                return False
            self.unique_writer(owner["pid"])
            self.process_identity(owner["pid"])
            return (
                owner["pid"] != original["pid"]
                and owner["pid"] == self.loaded_pid()
                and owner["generation"] == 53
                and 0
                < time.time() - datetime.fromisoformat(owner["at"]).timestamp()
                < 120
                and owner_lock_available("market-feed")
            )
        except (KeyError, subprocess.SubprocessError):
            return False

    def _alive(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    def resume(self, original, request):
        from app.runtime_handover import cancel_drain

        require(self.parked(original, request))
        self.verify_frozen(original)
        cancel_drain("market-feed", request_id=request)

    def ready(self, original, request):
        from app.runtime_handover import read_service_state

        owner = read_service_state("market-feed")
        raw = self.redis.get("live:feed:heartbeat")
        if not raw:
            return None
        heartbeat = json.loads(raw)
        stamp = datetime.fromisoformat(heartbeat["generated_at"]).timestamp()
        if (
            owner["phase"] != "active"
            or not owner["ready"]
            or owner["pid"] == original["pid"]
            or owner["pid"] != self.loaded_pid()
            or heartbeat.get("runtime_commit") != COMMIT
            or heartbeat.get("runtime_generation") != 53
            or not 0 <= time.time() - stamp <= 8
            or not heartbeat.get("available")
            or heartbeat.get("input_failure") is not None
        ):
            return None
        self.unique_writer(owner["pid"])
        self.process_identity(owner["pid"])
        require(self.protected() == original["protected"], "PROTECTED_DRIFT")
        # Registration advances normally; old payloads, identities and terminal
        # cursors must remain byte-for-byte equal. Never acknowledge them here.
        for key, value in original["journals"].items():
            if key.startswith("live:observations:registered:"):
                require(
                    self.redis.get(key).decode() == DAY.isoformat(), "NEW_DAY_NOT_READY"
                )
            else:
                raw = self.redis.dump(key)
                require(
                    raw and hashlib.sha256(raw).hexdigest() == value, "OLD_PREFIX_DRIFT"
                )
        self.verify_metadata()
        return dict(
            pid=owner["pid"],
            generation=53,
            commit=COMMIT,
            heartbeat_at=heartbeat["generated_at"],
            subscribed_count=heartbeat["subscribed_count"],
            operational_count=heartbeat["operational_count"],
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    try:
        if os.environ.get("GUIYI_FEED_SESSION_RECOVERY_READY") != "1":
            from app.core.env import PROJECT_ROOT
            from app.private_settings import private_dependency_settings
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "feed_recovery_environment",
                PROJECT_ROOT / "scripts/broker/simnow_supervisor.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            env, _ = private_dependency_settings(
                Path.home() / "Library/Application Support/GuiyiQuant/project.env"
            )
            os.environ.update(module.dependency_environment(env))
            os.environ["GUIYI_OBSERVATION_STREAM_ENABLED"] = "1"
            os.environ["GUIYI_FEED_SESSION_RECOVERY_READY"] = "1"
            os.execv(
                os.sys.executable,
                [
                    os.sys.executable,
                    "-B",
                    "-m",
                    "app.runtime_feed_session_recovery",
                    *os.sys.argv[1:],
                ],
            )
        native = Native(args.directory)
        require(args.plan == args.directory / "plan.private.json", "PLAN_PATH_INVALID")
        coordinator = Coordinator(native, args.directory)
        if args.action == "plan":
            result = coordinator.plan()
            write(args.plan, result, exclusive=True)
            print(json.dumps(dict(status="PLAN_READY", plan_hash=result["plan_hash"])))
        else:
            from app.runtime_identity import file_snapshot

            require(
                args.plan.is_file()
                and not args.plan.is_symlink()
                and args.plan.stat().st_uid == os.getuid()
                and args.plan.stat().st_mode & 0o777 == 0o600,
                "PLAN_PATH_INVALID",
            )
            raw, _ = file_snapshot(args.plan, limit=256 * 1024)
            result = coordinator.apply(json.loads(raw))
            print(json.dumps({k: v for k, v in result.items() if k != "proofs"}))
        return 0
    except Exception as error:
        print(
            json.dumps(
                dict(
                    status="BLOCKED",
                    code=str(error)
                    if isinstance(error, RecoveryError)
                    else "RECOVERY_UNPROVEN",
                )
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
