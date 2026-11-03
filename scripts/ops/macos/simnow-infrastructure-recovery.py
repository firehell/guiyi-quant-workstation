"""Exact, one-shot same-day SimNow recovery after an operator dependency restart."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def backend_type(switch, preparation):
    class Backend(preparation.backend_type(switch)):
        def __init__(self, config, plist, directory, probe, outage):
            from app.core.env import PROJECT_ROOT
            from guiyi_quant.simnow_execution import infrastructure_recovery as permit
            from guiyi_quant.simnow_execution.settings import load_settings
            from guiyi_quant.simnow_execution.supervisor import (
                global_account_lock_directory,
            )

            self.home, self.code = Path.home(), PROJECT_ROOT
            self.config, self.candidate_plist = (
                switch.private(config),
                switch.private(plist),
            )
            self.settings = load_settings(self.config)
            self.cfg = json.loads(self.config.read_bytes())
            identity = self.release_identity(self.code)
            self.tag, self.exact = identity["tag"], identity["commit"]
            self.directory = switch.private(directory, directory=True)
            if (
                self.settings.project_root != self.code
                or self.settings.infrastructure_recovery_permit
                != self.directory / permit.NAME
                or self.settings.account_recovery_hold
                or not self.settings.account_takeover_pending
            ):
                switch.fail("CANDIDATE_UNPROVEN")
            self.probe, self.outage = probe, outage
            self.old_pid, self.old_run, self.resume = (
                permit.OLD_PID,
                permit.OLD_RUN,
                False,
            )
            self.ordinary, self.window = True, "infrastructure-interruption"
            self.enable_auto_order = self.recover_held_readonly_source = False
            self.folder = self.settings.state_root / self.settings.account_id
            self.locks = (
                global_account_lock_directory() / (self.settings.account_id + ".lock"),
                self.folder / "host.lock",
            )
            self.label = f"gui/{os.getuid()}/{switch.LABEL}"
            self.plist = self.home / "Library/LaunchAgents" / (switch.LABEL + ".plist")
            self.monitor = (
                self.home
                / "Library/Application Support/GuiyiQuant/simnow-monitor.private.json"
            )
            self.service = module(
                self.code / "scripts/ops/macos/simnow-service.py", "infra_service"
            )

        def _window(self):
            from app.simnow_infrastructure_readiness import recovery_window
            from guiyi_quant.simnow_execution.infrastructure_recovery import DAY

            return recovery_window(DAY, datetime.now(UTC))

        def _source(self):
            from guiyi_quant.simnow_execution import infrastructure_recovery as permit
            from guiyi_quant.simnow_execution import deployment_connection as io

            value = self._window()
            failure = self.folder / permit.FAILURE_NAME
            return dict(
                account_anchor=io.account_anchor(self.settings),
                budget=permit.budget_binding(self.settings),
                window={
                    k: value[k]
                    for k in ("trading_day", "sessions", "session_facts_sha256")
                },
                failure=dict(
                    path=str(failure),
                    sha256=hashlib.sha256(
                        switch.private(failure).read_bytes()
                    ).hexdigest(),
                ),
                outage=dict(
                    path=str(self.outage),
                    sha256=hashlib.sha256(
                        switch.private(self.outage).read_bytes()
                    ).hexdigest(),
                ),
                old_config=dict(
                    path=str(self.old_config),
                    sha256=hashlib.sha256(self.old_config.read_bytes()).hexdigest(),
                ),
                old_pid=self.old_pid,
                old_run_id=self.old_run,
                old_process_identity=self._stop_process_identity,
            )

        def _prefixes(self, frozen=None):
            import sqlite3

            result = {}
            for name, tables in (
                ("account.sqlite", ("metadata", "commands")),
                ("signals.sqlite", ("identity", "signals")),
                ("dispatch.sqlite", ("identity", "events")),
                ("native-evidence.sqlite", ("owner", "snapshots")),
            ):
                identity = switch.private(self.folder / name).stat()
                with sqlite3.connect(
                    (self.folder / name).as_uri() + "?mode=ro", uri=True
                ) as db:
                    db.execute("PRAGMA query_only=ON")
                    db.execute("BEGIN")
                    result[name] = {
                        "device": identity.st_dev,
                        "inode": identity.st_ino,
                        "schema": switch.digest(
                            db.execute(
                                "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
                            ).fetchall()
                        ),
                    }
                    for table in tables:
                        count = (
                            frozen[name][table]["count"]
                            if frozen
                            else db.execute("SELECT COUNT(*) FROM " + table).fetchone()[
                                0
                            ]
                        )
                        rows = db.execute(
                            "SELECT rowid,* FROM " + table + " ORDER BY rowid LIMIT ?",
                            (count,),
                        ).fetchall()
                        result[name][table] = dict(
                            count=len(rows), sha256=switch.digest(rows)
                        )
                current = (self.folder / name).stat()
                if (current.st_dev, current.st_ino) != (
                    identity.st_dev,
                    identity.st_ino,
                ):
                    switch.fail("PREIMAGE_CHANGED")
            return result

        def snapshot(self):
            from guiyi_quant.simnow_execution.account_binding import (
                _snapshot_account_proof,
                existing_account,
            )
            from guiyi_quant.simnow_execution import infrastructure_recovery as permit

            self._window()  # No signed plan while the signal source is unavailable.
            with _snapshot_account_proof(
                self.settings.state_root, self.settings.account_id
            ):
                exact, _ = self._candidate()
                preimage = self._preimage()
                if preimage["old_release"]["commit"] != permit.SOURCE_COMMIT:
                    switch.fail("PREIMAGE_CHANGED")
                account = self._account()
                state = existing_account(
                    self.settings.state_root, self.settings.account_id
                )
                if (
                    not preparation.obligations_clear(state)
                    or account["today_attempts"] != 1
                    or account["day_block_code"] != permit.BLOCK
                ):
                    switch.fail("PENDING_OBLIGATIONS")
                pid = self._pid()
                if pid != self.old_pid:
                    switch.fail("HOST_UNPROVEN")
                command = self._prove(pid, "trade", self.old_config)
                birth = (
                    self._probe()
                )  # Same bounded read-only GC proof used by the native controller.
                self._stop_process_identity = birth
                source = self._source()
                anchor = self._historical_anchor()
                self._stop_signals = self.identity(self.folder / "signals.sqlite")
                self._stop_requires_permit, self._stop_ordinary = False, None
                self._stop_historical_anchor = anchor
                control = json.loads(
                    switch.private(self.folder / "continuous.json").read_bytes()
                )
                if (
                    control.get("run_id") != self.old_run
                    or control.get("status") != "RECOVERY_BLOCKED"
                    or control.get("account_takeover_pending") is not True
                    or control.get("account_recovery_hold") is not False
                    or control.get("auto_order") is not True
                    or control.get("opening_enabled") is not False
                    or control.get("trading_day") != permit.DAY
                    or not 0
                    <= time.time() - datetime.fromisoformat(control["at"]).timestamp()
                    <= 8
                ):
                    switch.fail("HOST_UNPROVEN")
                preimage.update(
                    account=account,
                    host_pid=pid,
                    host_run_id=self.old_run,
                    locks=[
                        dict(path=str(p), device=p.stat().st_dev, inode=p.stat().st_ino)
                        for p in self.locks
                    ],
                )
                return dict(
                    candidate=dict(tag=self.tag, commit=exact),
                    preimage=preimage,
                    account=account,
                    host=preparation.host_fact(
                        pid, self.old_run, switch.digest(command)
                    ),
                    historical_account=preparation.retained_history(state),
                    old_config_path=str(self.old_config),
                    source=source,
                    process_identity=birth,
                    historical_contract_anchor=anchor,
                    immutable_prefixes=self._prefixes(),
                    source_lock=preparation.source_lock_identity(
                        self.old_config, switch
                    ),
                )

        def preflight(self, snapshot):
            import subprocess

            result = subprocess.run(
                [
                    str(self.settings.sdk_python),
                    "-I",
                    "-B",
                    str(Path(__file__)),
                    "check-source",
                    "--config",
                    str(self.config),
                ],
                input=json.dumps(snapshot["source"]),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode:
                switch.fail("CANDIDATE_UNPROVEN")
            value = json.loads(result.stdout)
            self.validate_preflight(snapshot, value)
            return value

        def validate_preflight(self, snapshot, proof):
            if (
                proof.get("status") != "SOURCE_PREFLIGHT_PASSED"
                or proof.get("source_sha256") != switch.digest(snapshot["source"])
                or proof.get("config_sha256") != self.identity(self.config)["sha256"]
                or proof.get("controller_sha256")
                != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                or proof.get("sdk_sha256")
                != self.identity(self.settings.sdk_python, interpreter=True)["sha256"]
                or not 0
                <= time.time() - datetime.fromisoformat(proof["checked_at"]).timestamp()
                < 60
            ):
                switch.fail("CANDIDATE_UNPROVEN")

        def issue(self, snapshot, intent):
            from guiyi_quant.simnow_execution import infrastructure_recovery as permit

            now = datetime.now(UTC)
            ends = [
                datetime.fromisoformat(s["end"])
                for s in snapshot["source"]["window"]["sessions"]
                if datetime.fromisoformat(s["start"])
                <= now
                < datetime.fromisoformat(s["end"])
            ]
            self._issued_grant_sha256 = permit.issue(
                self.settings,
                source=snapshot["source"],
                intent_path=intent,
                now=now,
                expires_at=min(now + timedelta(seconds=120), min(ends)),
                authority=self._window,
            )
            return self._issued_grant_sha256

        def readback(self, snapshot):
            from guiyi_quant import htdy_account_execution as a
            from guiyi_quant.simnow_execution import infrastructure_recovery as permit

            control = json.loads(
                switch.private(self.folder / "continuous.json").read_bytes()
            )
            if (
                control.get("run_id") == self.old_run
                or control.get("status") != "TRADING"
                or control.get("account_takeover_pending") is not False
                or control.get("account_recovery_hold") is not False
                or control.get("auto_order") is not True
            ):
                return None
            pid = self._pid()
            self._prove(pid, "trade", self.config)
            if (
                self.plist.read_bytes() != self.candidate_plist.read_bytes()
                or self.monitor.read_bytes() != self.monitor_source()
                or self.identity(self.config) != snapshot["preimage"]["config"]
                or self.identity(self.settings.sdk_python, interpreter=True)
                != snapshot["preimage"]["sdk"]
            ):
                switch.fail("PREIMAGE_CHANGED")
            path = Path(self.settings.infrastructure_recovery_permit)
            grant, grant_sha = permit.io.read(path)
            if (grant_sha != self._issued_grant_sha256 or grant.get('source') != snapshot['source']):
                switch.fail('PREIMAGE_CHANGED')
            expected_owner = dict(
                grant_sha256=grant_sha, run_id=control["run_id"], pid=pid
            )
            for claim in (
                path.with_name(path.name + ".run-claim"),
                permit._global(self.settings),
            ):
                if permit.io.read(claim)[0] != expected_owner:
                    switch.fail("HOST_UNPROVEN")
            if permit.io.read(path.with_name(path.name + ".attempt-claim"))[0] != {
                **expected_owner,
                "day": permit.DAY,
            }:
                switch.fail("HOST_UNPROVEN")
            self._new_run_clear(control["run_id"])
            state = a.LocalStore.inspect(self.folder / "account.sqlite")
            now = datetime.now(UTC)
            if not (
                state.phase == "READY"
                and state.readback_valid
                and state.readback.complete
                and state.readback.at <= now < state.readback.valid_until
            ):
                return None
            current_history = preparation.retained_history(state)
            for name, old in snapshot["historical_account"].items():
                current = current_history[name]
                if current[: len(old)] != old:
                    switch.fail("PREIMAGE_CHANGED")
            with __import__("sqlite3").connect(
                (self.folder / "signals.sqlite").as_uri() + "?mode=ro", uri=True
            ) as db:
                db.execute("PRAGMA query_only=ON")
                budget = permit._tables(db, self.settings.account_id)
            expected = {
                **snapshot["source"]["budget"],
                "attempts": [
                    [d, 2 if d == permit.DAY else n]
                    for d, n in snapshot["source"]["budget"]["attempts"]
                ],
            }
            if budget != expected:
                switch.fail("PREIMAGE_CHANGED")
            if (
                self._prefixes(snapshot["immutable_prefixes"])
                != snapshot["immutable_prefixes"]
            ):
                switch.fail("PREIMAGE_CHANGED")
            if (
                hashlib.sha256(
                    switch.private(
                        Path(snapshot["source"]["failure"]["path"])
                    ).read_bytes()
                ).hexdigest()
                != snapshot["source"]["failure"]["sha256"]
            ):
                switch.fail("PREIMAGE_CHANGED")
            from guiyi_quant.htdy_account_execution.codec import digest as state_digest

            index = json.loads(
                switch.private(self.settings.state_root / "monitor.json").read_bytes()
            )
            fresh = json.loads(
                switch.private(self.folder / "continuous.json").read_bytes()
            )
            if (
                fresh.get("run_id") != control["run_id"]
                or fresh.get("status") != "TRADING"
                or fresh.get("account_takeover_pending") is not False
                or fresh.get("account_recovery_hold") is not False
                or fresh.get("auto_order") is not True
                or fresh.get("trading_day") != permit.DAY
                or index.get("run_id") != control["run_id"]
                or index.get("host_status") != "TRADING"
                or index.get("native_source_id") != state.readback.source_id
                or index.get("ledger_hash") != state_digest(state)
                or index.get("account_takeover_pending") is not False
                or not 0
                <= time.time()
                - datetime.fromisoformat(index["published_at"]).timestamp()
                <= 8
            ):
                return None
            control = fresh
            if self._pid() != pid:
                switch.fail("HOST_UNPROVEN")
            self._prove(pid, "trade", self.config)
            self._new_run_clear(control["run_id"])
            final = datetime.now(UTC)
            if not state.readback.at <= final < state.readback.valid_until or not all(
                0 <= final.timestamp() - datetime.fromisoformat(stamp).timestamp() <= 8
                for stamp in (control["at"], index["published_at"])
            ):
                return None
            return dict(
                pid=pid,
                run_id=control["run_id"],
                at=control["at"],
                phase="READY",
                account_takeover_pending=False,
                auto_order=True,
                attempt=2,
                old_blocks_preserved=True,
            )

        def _new_run_clear(self, run):
            fd = os.open(
                switch.private(self.folder, directory=True),
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            try:
                with os.scandir(fd) as entries:
                    if any(e.name.startswith("failure-" + run + "-") for e in entries):
                        switch.fail("HOST_UNPROVEN")
            finally:
                os.close(fd)

    return Backend


class Coordinator:
    def __init__(
        self, backend, directory, switch, *, clock=time.time, sleep=time.sleep
    ):
        self.backend, self.directory, self.switch = backend, Path(directory), switch
        self.clock, self.sleep = clock, sleep
        self.state = self.directory / "state.private.json"

    def plan(self):
        from guiyi_quant.simnow_execution import infrastructure_recovery as permit

        if (
            self.state.exists()
            or Path(self.backend.settings.infrastructure_recovery_permit).exists()
            or permit._global(self.backend.settings).exists()
        ):
            self.switch.fail("ATTEMPT_CONSUMED")
        snapshot = self.backend.snapshot()
        proof = self.backend.preflight(snapshot)
        now = self.clock()
        value = dict(
            schema=permit.SCHEMA,
            created_at=now,
            expires_at=now + 60,
            snapshot=snapshot,
            sdk_preflight=proof,
        )
        return dict(value, plan_hash=self.switch.digest(value))

    def apply(self, plan):
        import fcntl
        from app.runtime_handover import deployment_lock
        from guiyi_quant.simnow_execution import infrastructure_recovery as permit

        raw = {k: v for k, v in plan.items() if k != "plan_hash"}
        if (
            raw.get("schema") != permit.SCHEMA
            or self.switch.digest(raw) != plan.get("plan_hash")
            or plan["expires_at"] - plan["created_at"] != 60
            or not plan["created_at"] <= self.clock() < plan["expires_at"]
        ):
            self.switch.fail("PLAN_INVALID")
        frozen = plan["snapshot"]
        with deployment_lock():
            identity = preparation_lock(frozen, self.switch)
            fd = os.open(identity["path"], os.O_RDONLY | os.O_NOFOLLOW)
            try:
                st = os.fstat(fd)
                if (st.st_dev, st.st_ino) != (identity["device"], identity["inode"]):
                    self.switch.fail("PREIMAGE_CHANGED")
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if self.backend.snapshot() != frozen:
                    self.switch.fail("PREIMAGE_CHANGED")
                self.backend.validate_preflight(frozen, plan["sdk_preflight"])
                if not plan["created_at"] <= self.clock() < plan["expires_at"]:
                    self.switch.fail("PLAN_EXPIRED")
                record = dict(
                    schema=permit.SCHEMA,
                    plan_hash=plan["plan_hash"],
                    stage="INTENT",
                    result="UNKNOWN",
                )
                self.switch.write_private(self.state, record, exclusive=True)

                def phase(stage, **extra):
                    record.update(stage=stage, **extra)
                    self.switch.write_private(self.state, record)

                try:
                    phase("STOP_REQUESTED")
                    self.backend.stop(
                        frozen["host"]["pid"],
                        expires_at=plan["expires_at"],
                        clock=self.clock,
                    )
                    end = self.clock() + 35
                    while not self.backend.stopped(frozen):
                        if self.clock() >= end:
                            self.switch.fail("STOP_TIMEOUT")
                        self.sleep(0.25)
                    phase("STOPPED")
                    with self.backend.offline_guard(frozen):
                        self.backend.verify_offline(frozen)
                        if not self.backend.window_open():
                            self.switch.fail("WINDOW_UNPROVEN")
                        phase("INSTALLING")
                        if not self.backend.install(frozen):
                            self.switch.fail("INSTALL_UNPROVEN")
                        phase("INSTALLED")
                        intent = self.directory / permit.INTENT_NAME
                        self.switch.write_private(
                            intent,
                            dict(
                                schema=permit.SCHEMA,
                                stage="START_REQUESTED",
                                source=frozen["source"],
                                config_path=str(self.backend.config),
                                config_sha256=hashlib.sha256(
                                    self.backend.config.read_bytes()
                                ).hexdigest(),
                                old_pid_exited=True,
                            ),
                            exclusive=True,
                        )
                        phase(
                            "START_REQUESTED", grant=self.backend.issue(frozen, intent)
                        )
                    if not self.backend.start(frozen):
                        self.switch.fail("START_UNPROVEN")
                    phase("VERIFYING")
                    end = self.clock() + 180
                    previous = None
                    while self.clock() < end:
                        value = self.backend.readback(frozen)
                        if value:
                            if previous and (value["pid"], value["run_id"]) == (
                                previous["pid"],
                                previous["run_id"],
                            ):
                                phase(
                                    "COMPLETE",
                                    result="ACCOUNT_RECOVERED",
                                    readback=value,
                                )
                                return record
                            previous = value
                        self.sleep(2)
                    self.switch.fail("READBACK_UNPROVEN")
                except Exception:
                    phase(record["stage"], result="UNKNOWN")
                    raise
            finally:
                os.close(fd)


def preparation_lock(snapshot, switch):
    path = switch.private(Path(snapshot["old_config_path"]).parent / "switch.lock")
    st = path.stat()
    identity = dict(path=str(path), device=st.st_dev, inode=st.st_ino)
    if identity != snapshot["source_lock"]:
        switch.fail("PREIMAGE_CHANGED")
    return identity


def bootstrap(root, config, isolated):
    sys.dont_write_bytecode = True
    os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on"
    sys.path[:0] = [str(root / "packages/quant-core"), str(root / "services/quant-api")]
    from guiyi_quant.simnow_execution.settings import load_settings

    settings = load_settings(config)
    if (
        settings.project_root != root
        or isolated
        and Path(sys.executable).resolve() != settings.sdk_python.resolve()
    ):
        raise ValueError("CANDIDATE_UNPROVEN")
    site = (
        settings.api_env
        / "lib"
        / ("python" + str(sys.version_info.major) + "." + str(sys.version_info.minor))
        / "site-packages"
    )
    if not site.is_dir() or site.is_symlink():
        raise ValueError("CANDIDATE_UNPROVEN")
    sys.path.append(str(site))
    from app.private_settings import private_dependency_settings

    runner = module(root / "scripts/broker/simnow_supervisor.py", "infra_environment")
    values, _ = private_dependency_settings(
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    )
    env = runner.dependency_environment(values)
    changed = any(os.environ.get(k) != v for k, v in env.items())
    os.environ.update(env)
    if changed:
        os.execv(
            sys.executable,
            [
                sys.executable,
                "-I" if isolated else "-B",
                "-B",
                str(Path(__file__).resolve()),
                *sys.argv[1:],
            ],
        )
    return settings


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("plan", "apply", "check-source"))
    for key in ("config", "plist", "directory", "probe", "outage"):
        p.add_argument("--" + key, type=Path, required=key == "config")
    args = p.parse_args()
    root = Path(__file__).resolve().parents[3]
    try:
        settings = bootstrap(root, args.config, args.action == "check-source")
        from guiyi_quant.simnow_execution import infrastructure_recovery as permit
        from app.simnow_infrastructure_readiness import recovery_window

        if args.action == "check-source":
            raw = sys.stdin.buffer.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("SOURCE_TOO_LARGE")
            source = json.loads(raw)
            now = datetime.now(UTC)
            ends = [
                datetime.fromisoformat(s["end"])
                for s in source["window"]["sessions"]
                if datetime.fromisoformat(s["start"])
                <= now
                < datetime.fromisoformat(s["end"])
            ]
            permit.preflight_source(
                settings,
                source,
                now,
                min(now + timedelta(seconds=120), min(ends)),
                lambda: recovery_window(permit.DAY, datetime.now(UTC)),
            )
            print(
                json.dumps(
                    dict(
                        status="SOURCE_PREFLIGHT_PASSED",
                        source_sha256=hashlib.sha256(
                            permit.io._bytes(source)
                        ).hexdigest(),
                        config_sha256=settings.source_config_sha256,
                        controller_sha256=hashlib.sha256(
                            Path(__file__).read_bytes()
                        ).hexdigest(),
                        sdk_sha256=permit.io.sdk_identity(settings.sdk_python)[
                            "sha256"
                        ],
                        checked_at=datetime.now(UTC).isoformat(),
                    )
                )
            )
            return 0
        if any(
            getattr(args, k) is None for k in ("plist", "directory", "probe", "outage")
        ):
            raise ValueError("CANDIDATE_UNPROVEN")
        prep = module(
            root / "scripts/ops/macos/simnow-preparation-recovery.py",
            "infra_reused_mechanics",
        )
        switch = prep.load_switch(root)
        backend = backend_type(switch, prep)(
            args.config, args.plist, args.directory, args.probe, args.outage
        )
        coordinator = Coordinator(backend, args.directory, switch)
        path = args.directory / "plan.private.json"
        if args.action == "plan":
            value = coordinator.plan()
            switch.write_private(path, value, exclusive=True)
            print(json.dumps(dict(status="PLAN_READY", plan_hash=value["plan_hash"])))
            return 0
        value = coordinator.apply(json.loads(switch.private(path).read_bytes()))
        print(json.dumps(dict(status=value["result"], stage=value["stage"])))
        return 0
    except Exception as exc:
        code = (
            str(exc)
            if isinstance(exc, ValueError)
            and str(exc)
            in {
                "INFRASTRUCTURE_RECOVERY_INVALID",
                "INFRASTRUCTURE_RECOVERY_MARKET_UNPROVEN",
                "READBACK_UNPROVEN",
                "ATTEMPT_CONSUMED",
                "PLAN_EXPIRED",
                "PREIMAGE_CHANGED",
                "CANDIDATE_UNPROVEN",
                "HOST_UNPROVEN",
                "WINDOW_UNPROVEN",
            }
            else "INFRASTRUCTURE_RECOVERY_FAILED"
        )
        print(json.dumps(dict(status="READBACK_REQUIRED", code=code)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
