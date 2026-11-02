"""One-shot account-only recovery; reuses the native SimNow switch mechanics."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time


HISTORY_FIELDS = ("orders", "fills", "reservations", "signals", "risk_decisions")


def retained_history(state):
    from guiyi_quant.htdy_account_execution.codec import digest

    return {
        name: [digest(item) for item in getattr(state, name)] for name in HISTORY_FIELDS
    }


def obligations_clear(state):
    return (
        not state.positions
        and not state.unresolved_fill_ids
        and all(
            order.reconciled
            and order.status in {"LOCAL_ABORTED", "CANCELLED", "REJECTED", "FILLED"}
            for order in state.orders
        )
        and all(item.released for item in state.reservations)
    )


def diagnostic_inventory_clear(inventory, account_id):
    from guiyi_quant.simnow_execution.inventory import number

    return (
        inventory.account_id == account_id
        and inventory.trading_day == DAY
        and not any(inventory.data[k] for k in ("positions", "orders", "trades"))
        and all(
            number(inventory.data["funds"][0][key]) == 0
            for key in ("CurrMargin", "FrozenMargin", "FrozenCommission")
        )
    )


def host_fact(pid, run_id, command_identity):
    return dict(
        label="com.guiyi.quant-simnow",
        mode="trade",
        unique=True,
        pid=pid,
        run_id=run_id,
        dual_locks_held_by_pid=True,
        command_identity=command_identity,
    )


DAY = "20261103"
OLD_RUN = "4af489cab654450db267587ee3b5c0f7"
OLD_PID = 15566
SCHEMA = "simnow_adapter_preparation_recovery_plan_v1"
STATE_NAME = "simnow-preparation-recovery-20261103"


def load_switch(root):
    spec = importlib.util.spec_from_file_location(
        "preparation_switch_mechanics",
        root / "scripts/ops/macos/simnow-trade-switch.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def backend_type(switch):
    class Backend(switch.MacBackend):
        def __init__(self, config, plist, directory, probe, diagnostic):
            from app.core.env import PROJECT_ROOT
            from app.runtime_bindings import verify_release
            from guiyi_quant.simnow_execution.settings import load_settings
            from guiyi_quant.simnow_execution.supervisor import (
                global_account_lock_directory,
            )

            self.home = Path.home()
            self.code = PROJECT_ROOT
            self.config, self.candidate_plist = (
                switch.private(config),
                switch.private(plist),
            )
            self.settings = load_settings(self.config)
            self.cfg = json.loads(self.config.read_bytes())
            self.tag = self.run(
                [
                    "/usr/bin/git",
                    "-C",
                    self.code,
                    "describe",
                    "--tags",
                    "--exact-match",
                    "HEAD",
                ]
            ).stdout.strip()
            self.exact = self.run(
                ["/usr/bin/git", "-C", self.code, "rev-parse", "HEAD"]
            ).stdout.strip()
            verify_release(self.code, self.tag, self.exact)
            switch.private(directory, directory=True)
            if (
                directory
                != self.home / "Library/Application Support/GuiyiQuant" / STATE_NAME
                or self.settings.project_root != self.code
                or self.settings.preparation_recovery_permit
                != directory / "preparation-recovery-permit.private.json"
                or not self.settings.account_recovery_hold
                or not self.settings.account_takeover_pending
            ):
                switch.fail("CANDIDATE_UNPROVEN")
            self.directory, self.probe, self.diagnostic = directory, probe, diagnostic
            self.ordinary = True  # Reuse trade→trade backup/identity mechanics only.
            self.window = "blocked-adapter-preparation"
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
            spec = importlib.util.spec_from_file_location(
                "preparation_switch_service",
                self.code / "scripts/ops/macos/simnow-service.py",
            )
            self.service = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.service)

        def release_identity(self, root):
            from app.runtime_bindings import verify_release

            root = Path(root)
            tag = self.run(
                [
                    "/usr/bin/git",
                    "-C",
                    root,
                    "describe",
                    "--tags",
                    "--exact-match",
                    "HEAD",
                ]
            ).stdout.strip()
            commit = self.run(
                ["/usr/bin/git", "-C", root, "rev-parse", "HEAD"]
            ).stdout.strip()
            verify_release(root, tag, commit)
            return dict(root=str(root), tag=tag, commit=commit)

        def _window(self):
            from app.simnow_takeover_window import authoritative_window
            from app.db.session import SessionLocal
            from app.db.readonly import readonly_transaction
            from app.market_data.market_phase import MarketPhaseResolver, MarketPhase
            from app.market_data.operational_universe import load_operational_products

            now = datetime.now(UTC)
            window = authoritative_window(now, target_day=DAY)
            with SessionLocal() as db, readonly_transaction(db, timeout_seconds=30):
                phases = [
                    MarketPhaseResolver(db).resolve(p, now)
                    for p in load_operational_products()
                ]
            days = {
                p.trading_day.strftime("%Y%m%d")
                for p in phases
                if p.phase is MarketPhase.TRADING and p.trading_day is not None
            }
            if (
                len(phases) != 60
                or any(p.phase is MarketPhase.UNKNOWN for p in phases)
                or days != {DAY}
            ):
                switch.fail("WINDOW_UNPROVEN")
            return dict(
                trading_day=DAY,
                active=True,
                sessions=window["sessions"],
                session_facts_sha256=window["session_facts_sha256"],
            )

        def window_open(self):
            try:
                return self._window()["active"] is True
            except Exception:
                return False

        def _probe(self):
            value = json.loads(switch.private(self.probe).read_bytes())
            stamp = datetime.fromisoformat(value["proof_at"]).timestamp()
            start = self.run(
                ["/bin/ps", "-p", str(OLD_PID), "-o", "lstart="]
            ).stdout.strip()
            expected = hashlib.sha256(f"{OLD_PID}:{start}".encode()).hexdigest()
            if not (
                value["status"] == "READ_ONLY_INSPECTED"
                and value["detached"] is True
                and value["target_calls"] == value["target_writes"] == 0
                and value["pid"] == OLD_PID
                and value["process_identity"] == expected
                and value["gateway_count"] == value["portfolio_count"] == 0
                and value["supervisor_count"] == 1
                and value["supervisors"]
                == [
                    dict(
                        driver_absent=True,
                        host_absent=True,
                        pending=True,
                        expected_run=True,
                    )
                ]
                and 0 <= time.time() - stamp <= 90
            ):
                switch.fail("HOST_UNPROVEN")
            return expected

        def _source(self):
            from guiyi_quant.simnow_execution import deployment_connection as io

            state = self.diagnostic
            fact = switch.private(state / "native-fact.private.json")
            receipt = switch.private(state / "release.private.json")
            failure = switch.private(
                self.folder / ("failure-" + OLD_RUN + "-10342.json")
            )
            original = json.loads(failure.read_bytes())
            from guiyi_quant.simnow_execution.inventory import read_snapshot

            verified = json.loads(fact.read_bytes())
            cleanup = json.loads(receipt.read_bytes())
            if not (
                verified.get("schema") == "simnow_independent_session_diagnostic_v1"
                and verified.get("readback_complete") is True
                and verified.get("old_run") == OLD_RUN
                and verified.get("old_failure_sha256")
                == hashlib.sha256(failure.read_bytes()).hexdigest()
                and cleanup.get("plan_sha256") == verified.get("plan_sha256")
                and cleanup.get("status") == "READ_ONLY_DIAGNOSTIC_COMPLETE"
                and cleanup.get("native_released") is True
                and cleanup.get("spi_detached") is True
                and cleanup.get("guard_after_release_passed") is True
                and cleanup.get("fact_sha256")
                == hashlib.sha256(fact.read_bytes()).hexdigest()
            ):
                switch.fail("ACCOUNT_UNPROVEN")
            inventory = read_snapshot(verified["snapshot"])
            if not diagnostic_inventory_clear(inventory, self.settings.account_id):
                switch.fail("PENDING_OBLIGATIONS")
            if (
                hashlib.sha256(failure.read_bytes()).hexdigest()
                != "e226869bbf4705518db57504503466330c42d126e21df998caa50e6cb27b7cf7"
                or original.get("code") != "CONTINUOUS_RECOVERY_REQUIRED"
                or original.get("diagnostic", {}).get("stage") != "ADAPTER_CONSTRUCTION"
                or original.get("diagnostic", {}).get("recovery_stage")
                != "ADAPTER_PREPARATION"
            ):
                switch.fail("ACCOUNT_UNPROVEN")
            # Diagnostic fact/receipt validation is shared with the runtime grant.
            budget = self._budget()
            if (
                dict(budget["attempts"]).get(DAY) != 2
                or dict(budget["blocks"]).get(DAY) != "CONTINUOUS_RECOVERY_REQUIRED"
            ):
                switch.fail("ACCOUNT_UNPROVEN")
            window = self._window()
            return dict(
                account_anchor=io.account_anchor(self.settings),
                budget=budget,
                window={
                    k: window[k]
                    for k in ("trading_day", "sessions", "session_facts_sha256")
                },
                failure=dict(
                    path=str(failure),
                    sha256=hashlib.sha256(failure.read_bytes()).hexdigest(),
                ),
                diagnostic=dict(
                    path=str(fact), sha256=hashlib.sha256(fact.read_bytes()).hexdigest()
                ),
                release_receipt=dict(
                    path=str(receipt),
                    sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
                ),
            )

        def _budget(self):
            import sqlite3

            with sqlite3.connect(
                (self.folder / "signals.sqlite").as_uri() + "?mode=ro", uri=True
            ) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                return {
                    name: [
                        list(row)
                        for row in db.execute(
                            "SELECT * FROM "
                            + name
                            + ("" if name == "identity" else " ORDER BY day")
                        )
                    ]
                    for name in ("identity", "attempts", "blocks")
                }

        def snapshot(self):
            from guiyi_quant.simnow_execution.account_binding import (
                _snapshot_account_proof,
                existing_account,
            )

            with _snapshot_account_proof(
                self.settings.state_root, self.settings.account_id
            ):
                exact, _ = self._candidate()
                preimage = self._preimage()
                account = self._account()
                local = existing_account(
                    self.settings.state_root, self.settings.account_id
                )
                if (
                    not obligations_clear(local)
                    or account["today_attempts"] != 2
                    or account["day_block_code"] != "CONTINUOUS_RECOVERY_REQUIRED"
                    or account["local_obligations_clear"] is not True
                ):
                    switch.fail("PENDING_OBLIGATIONS")
                pid = self._pid()
                if pid != OLD_PID:
                    switch.fail("HOST_UNPROVEN")
                self._prove(pid, "trade", self.old_config)
                birth = self._probe()
                control = json.loads(
                    switch.private(self.folder / "continuous.json").read_bytes()
                )
                if not (
                    control["run_id"] == OLD_RUN
                    and control["status"] == "RECOVERY_BLOCKED"
                    and control["trading_day"] == DAY
                    and control["account_takeover_pending"] is True
                    and control["opening_enabled"] is False
                    and 0
                    <= time.time() - datetime.fromisoformat(control["at"]).timestamp()
                    <= 8
                ):
                    switch.fail("HOST_UNPROVEN")
                anchor = self._historical_anchor()
                preimage.update(
                    account=account,
                    host_pid=pid,
                    host_run_id=OLD_RUN,
                    locks=[
                        dict(path=str(p), device=p.stat().st_dev, inode=p.stat().st_ino)
                        for p in self.locks
                    ],
                )
                self._stop_signals = self.identity(self.folder / "signals.sqlite")
                self._stop_requires_permit = False
                self._stop_ordinary = None
                self._stop_historical_anchor = anchor
                return dict(
                    candidate=dict(tag=self.tag, commit=exact),
                    preimage=preimage,
                    account=account,
                    host=host_fact(
                        pid,
                        OLD_RUN,
                        switch.digest(self._prove(pid, "trade", self.old_config)),
                    ),
                    historical_account=retained_history(local),
                    old_config_path=str(self.old_config),
                    source=self._source(),
                    historical_contract_anchor=anchor,
                    process_identity=birth,
                )

        def verify_offline(self, snapshot):
            if self._historical_anchor() != snapshot["historical_contract_anchor"]:
                switch.fail("PREIMAGE_CHANGED")
            result = self.offline_preflight(snapshot)
            if not (
                result["writer_idle"]
                and result["protected_state_unchanged"]
                and result["native_prefix_unchanged"]
                and result["native_appended_count"] == 0
                and result["preimage"] == snapshot["preimage"]
                and self._source() == snapshot["source"]
            ):
                switch.fail("PREIMAGE_CHANGED")

        def issue(self, snapshot, intent_path):
            from guiyi_quant.simnow_execution import preparation_recovery as permit

            now = datetime.now(UTC)
            ends = [
                datetime.fromisoformat(s["end"])
                for s in snapshot["source"]["window"]["sessions"]
                if datetime.fromisoformat(s["start"])
                <= now
                < datetime.fromisoformat(s["end"])
            ]
            expiry = min(now + timedelta(seconds=300), min(ends))
            return permit.issue(
                self.settings,
                self.config,
                intent_path=intent_path,
                source=snapshot["source"],
                now=now,
                expires_at=expiry,
            )

        def readback_held(self, snapshot):
            from guiyi_quant import htdy_account_execution as a

            control = json.loads(
                switch.private(self.folder / "continuous.json").read_bytes()
            )
            if not (
                control["status"] == "ACCOUNT_RECOVERED_HELD"
                and control["account_takeover_pending"] is False
                and control["opening_enabled"] is False
                and control["auto_order"] is False
            ):
                return None
            pid = self._pid()
            if pid == OLD_PID or control["run_id"] == OLD_RUN:
                switch.fail("READBACK_UNPROVEN")
            self._prove(pid, "trade", self.config)
            if (
                self.plist.read_bytes() != self.candidate_plist.read_bytes()
                or self.monitor.read_bytes() != self.monitor_source()
            ):
                switch.fail("PREIMAGE_CHANGED")
            current = a.LocalStore.inspect(self.folder / "account.sqlite")
            if not (
                current.phase == "READY"
                and current.readback_valid
                and current.readback.complete
                and obligations_clear(current)
                and retained_history(current) == snapshot["historical_account"]
            ):
                switch.fail("ACCOUNT_UNPROVEN")
            now = datetime.now(UTC)
            if not current.readback.at <= now < current.readback.valid_until:
                return None
            from guiyi_quant.htdy_account_execution.codec import digest as ledger_digest
            import sqlite3

            index = json.loads(
                switch.private(self.settings.state_root / "monitor.json").read_bytes()
            )
            if (
                index.get("run_id") != control["run_id"]
                or index.get("host_status") != "ACCOUNT_RECOVERED_HELD"
                or index.get("account_takeover_pending") is not False
                or index.get("opening_enabled") is not False
                or index.get("native_source_id") != current.readback.source_id
                or index.get("ledger_hash") != ledger_digest(current)
                or not 0
                <= time.time() - datetime.fromisoformat(control["at"]).timestamp()
                <= 8
                or not 0
                <= time.time()
                - datetime.fromisoformat(index["published_at"]).timestamp()
                <= 8
            ):
                return None
            prefix = snapshot["account"]["databases"]["native-evidence.sqlite"]["rows"]
            with sqlite3.connect(
                (self.folder / "native-evidence.sqlite").as_uri() + "?mode=ro", uri=True
            ) as db:
                db.execute("PRAGMA query_only=ON")
                rows = db.execute(
                    "SELECT rowid,source,payload FROM snapshots WHERE rowid<=? ORDER BY rowid",
                    (prefix[-1][0],),
                ).fetchall()
            if [
                [n, source, hashlib.sha256(raw.encode()).hexdigest()]
                for n, source, raw in rows
            ] != prefix:
                switch.fail("PREIMAGE_CHANGED")
            budget = self._budget()
            expected = json.loads(json.dumps(snapshot["source"]["budget"]))
            expected["attempts"] = [
                [d, 3 if d == DAY else c] for d, c in expected["attempts"]
            ]
            if budget != expected:
                switch.fail("PREIMAGE_CHANGED")
            for name in ("dispatch.sqlite",):
                if (
                    self.identity(self.folder / name)
                    != snapshot["account"]["databases"][name]
                ):
                    switch.fail("PREIMAGE_CHANGED")
            return dict(
                pid=pid,
                run_id=control["run_id"],
                at=control["at"],
                account_phase="READY",
                readback_valid=True,
                account_takeover_pending=False,
                opening_enabled=False,
                auto_order=False,
                attempt=3,
                old_blocks_preserved=True,
                no_new_orders=True,
                no_unresolved_orders=True,
                tag=self.tag,
                commit=self.exact,
            )

    return Backend


class Coordinator:
    def __init__(
        self, backend, directory, switch, *, clock=time.time, sleep=time.sleep
    ):
        self.backend, self.directory, self.switch = backend, Path(directory), switch
        self.clock, self.sleep = clock, sleep
        self.state = self.directory / "state.private.json"

    def plan(self):
        if self.state.exists():
            self.switch.fail("ATTEMPT_CONSUMED")
        snapshot = self.backend.snapshot()
        now = self.clock()
        plan = dict(
            schema=SCHEMA, created_at=now, expires_at=now + 60, snapshot=snapshot
        )
        plan["plan_hash"] = self.switch.digest(plan)
        return plan

    def apply(self, plan):
        from app.runtime_handover import deployment_lock
        import fcntl

        raw = {k: v for k, v in plan.items() if k != "plan_hash"}
        if (
            plan.get("schema") != SCHEMA
            or self.switch.digest(raw) != plan.get("plan_hash")
            or plan["expires_at"] - plan["created_at"] != 60
            or not plan["created_at"] <= self.clock() < plan["expires_at"]
        ):
            self.switch.fail("PLAN_INVALID")
        source_lock = Path(plan["snapshot"]["old_config_path"]).parent / "switch.lock"
        self.switch.private(source_lock)
        with deployment_lock():
            fd = os.open(source_lock, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if self.backend.snapshot() != plan["snapshot"]:
                    self.switch.fail("PREIMAGE_CHANGED")
                record = dict(
                    stage="INTENT",
                    schema=SCHEMA,
                    plan_hash=plan["plan_hash"],
                    result="UNKNOWN",
                )
                self.switch.write_private(self.state, record, exclusive=True)

                def phase(stage, **extra):
                    record.update(stage=stage, at=self.clock(), **extra)
                    self.switch.write_private(self.state, record)

                snapshot = plan["snapshot"]
                try:
                    phase("STOP_REQUESTED")
                    if not plan["created_at"] <= self.clock() < plan["expires_at"]:
                        self.switch.fail("PLAN_EXPIRED")
                    self.backend.stop(snapshot["host"]["pid"])
                    until = self.clock() + 35
                    while not self.backend.stopped(snapshot):
                        if self.clock() >= until:
                            self.switch.fail("STOP_TIMEOUT")
                        self.sleep(0.25)
                    phase("STOPPED")
                    with self.backend.offline_guard(snapshot):
                        self.backend.verify_offline(snapshot)
                        if not self.backend.window_open():
                            self.switch.fail("WINDOW_UNPROVEN")
                        phase("INSTALLING")
                        if not self.backend.install(snapshot):
                            self.switch.fail("INSTALL_UNPROVEN")
                        phase("INSTALLED")
                        self.backend.verify_installed = True
                    # This immutable origin is not rewritten as lifecycle progresses.
                    intent = self.directory / "preparation-recovery-intent.private.json"
                    self.switch.write_private(
                        intent,
                        dict(
                            schema="simnow_adapter_preparation_recovery_intent_v1",
                            stage="START_REQUESTED",
                            source=snapshot["source"],
                            config_path=str(self.backend.config),
                            config_sha256=hashlib.sha256(
                                self.backend.config.read_bytes()
                            ).hexdigest(),
                            old_run_id=OLD_RUN,
                            old_pid=OLD_PID,
                            old_pid_exited=True,
                            created_at=datetime.now(UTC).isoformat(),
                        ),
                        exclusive=True,
                    )
                    grant = self.backend.issue(snapshot, intent)
                    phase("START_REQUESTED", grant=grant)
                    if not self.backend.start(snapshot):
                        self.switch.fail("START_UNPROVEN")
                    phase("VERIFYING")
                    until = self.clock() + 180
                    previous = None
                    while self.clock() < until:
                        value = self.backend.readback_held(snapshot)
                        if value:
                            if previous and (value["pid"], value["run_id"]) == (
                                previous["pid"],
                                previous["run_id"],
                            ):
                                phase(
                                    "COMPLETE",
                                    result="ACCOUNT_RECOVERED_HELD",
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plist", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(root / "services/quant-api"), str(root / "packages/quant-core")]
    try:
        if os.environ.get("GUIYI_PREPARATION_RECOVERY_READY") != "1":
            from app.private_settings import private_dependency_settings

            spec = importlib.util.spec_from_file_location(
                "preparation_env", root / "scripts/broker/simnow_supervisor.py"
            )
            runner = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runner)
            settings, _ = private_dependency_settings(
                Path.home() / "Library/Application Support/GuiyiQuant/project.env"
            )
            os.environ.update(runner.dependency_environment(settings))
            os.environ["GUIYI_PREPARATION_RECOVERY_READY"] = "1"
            os.execv(sys.executable, [sys.executable, "-B", __file__, *sys.argv[1:]])
        switch = load_switch(root)
        backend = backend_type(switch)(
            args.config, args.plist, args.directory, args.probe, args.diagnostic
        )
        coordinator = Coordinator(backend, args.directory, switch)
        plan_path = args.directory / "plan.private.json"
        if args.action == "plan":
            result = coordinator.plan()
            switch.write_private(plan_path, result, exclusive=True)
            print(json.dumps(dict(status="PLAN_READY", plan_hash=result["plan_hash"])))
        else:
            result = coordinator.apply(
                json.loads(switch.private(plan_path).read_bytes())
            )
            print(json.dumps(result))
        return 0
    except Exception as error:
        code = str(error)
        print(
            json.dumps(
                dict(
                    status="BLOCKED",
                    code=code
                    if re.fullmatch("[A-Z_]{1,80}", code)
                    else "RECOVERY_UNPROVEN",
                )
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
