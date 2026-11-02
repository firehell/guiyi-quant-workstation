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
import signal
import subprocess
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
RESUME_NAME = "pre-native-resume"
PARENT_PID = 15437
PARENT_RUN = "c7a83cf0a185498b8d58315211718b87"


def process_identity(pid, run):
    result = run(["/bin/ps", "-p", str(pid), "-o", "lstart="])
    birth = result.stdout.strip()
    if result.returncode or not birth:
        raise ValueError("HOST_UNPROVEN")
    return hashlib.sha256(f"{pid}:{birth}".encode()).hexdigest()


def source_lock_identity(config, switch):
    path = switch.private(Path(config).parent / "switch.lock")
    info = path.stat()
    return dict(path=str(path), device=info.st_dev, inode=info.st_ino)


def authority_window():
    """The existing takeover authority and the original host's market phases."""
    from app.simnow_takeover_window import authoritative_window
    from app.db.session import SessionLocal
    from app.db.readonly import readonly_transaction
    from app.market_data.market_phase import MarketPhaseResolver, MarketPhase
    from app.market_data.operational_universe import load_operational_products

    now = datetime.now(UTC)
    window = authoritative_window(now, target_day=DAY)
    with SessionLocal() as db, readonly_transaction(db, timeout_seconds=30):
        phases = [MarketPhaseResolver(db).resolve(p, now) for p in load_operational_products()]
    days = {p.trading_day.strftime("%Y%m%d") for p in phases
            if p.phase is MarketPhase.TRADING and p.trading_day is not None}
    if len(phases) != 60 or any(p.phase is MarketPhase.UNKNOWN for p in phases) or days != {DAY}:
        raise ValueError("WINDOW_UNPROVEN")
    return dict(trading_day=DAY, active=True, sessions=window["sessions"],
                session_facts_sha256=window["session_facts_sha256"])


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
            base = self.home / "Library/Application Support/GuiyiQuant" / STATE_NAME
            self.resume = directory == base / RESUME_NAME
            if (
                directory not in (base, base / RESUME_NAME)
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
            self.old_pid, self.old_run = (PARENT_PID, PARENT_RUN) if self.resume else (OLD_PID, OLD_RUN)
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
            return authority_window()

        def window_open(self):
            try:
                return self._window()["active"] is True
            except Exception:
                return False

        def _probe(self):
            value = json.loads(switch.private(self.probe).read_bytes())
            stamp = datetime.fromisoformat(value["proof_at"]).timestamp()
            expected = process_identity(self.old_pid, self.run)
            if not (
                value["status"] == "READ_ONLY_INSPECTED"
                and value["detached"] is True
                and value["target_calls"] == value["target_writes"] == 0
                and value["pid"] == self.old_pid
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
            source = dict(
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
            return self._resume_source(source) if self.resume else source

        def _resume_source(self, source):
            from guiyi_quant.simnow_execution import preparation_recovery as permit
            from guiyi_quant.simnow_execution.supervisor import global_account_lock_directory

            root = self.directory.parent
            parent, unused = permit.read(root / permit.NAME)
            claim, unused = permit.read(root / (permit.NAME + ".run-claim"))
            if claim.get("pid") != self.old_pid or claim.get("run_id") != self.old_run or source != parent["source"]:
                switch.fail("PREIMAGE_CHANGED")
            paths = dict(grant=root / permit.NAME, intent=root / permit.INTENT_NAME,
                         state=root / "state.private.json", run_claim=root / (permit.NAME + ".run-claim"),
                         global_claim=global_account_lock_directory() / (
                             self.settings.account_id + "." + DAY + ".preparation-recovery.run-claim"),
                         failure=self.folder / ("failure-" + self.old_run + "-0.json"))
            refs = {}
            for key, path in paths.items():
                unused, digest = permit.read(path)
                refs[key] = dict(path=str(path), sha256=digest)
            source = {**source, "failure": refs["failure"], "pre_native_parent": refs}
            # One canonical contract validates the complete immutable parent chain.
            permit._parent(self.settings, source, root)
            return source

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
                source_lock = source_lock_identity(self.old_config, switch)
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
                if pid != self.old_pid:
                    switch.fail("HOST_UNPROVEN")
                self._prove(pid, "trade", self.old_config)
                birth = self._probe()
                control = json.loads(
                    switch.private(self.folder / "continuous.json").read_bytes()
                )
                if not (
                    control["run_id"] == self.old_run
                    and control["status"] == "RECOVERY_BLOCKED"
                    and control["trading_day"] in ({None, DAY} if self.resume else {DAY})
                    and control["account_takeover_pending"] is True
                    and control["opening_enabled"] is False
                    and (not self.resume or control.get("account_recovery_hold") is True)
                    and (not self.resume or control.get("auto_order") is False)
                    and 0
                    <= time.time() - datetime.fromisoformat(control["at"]).timestamp()
                    <= 8
                ):
                    switch.fail("HOST_UNPROVEN")
                anchor = self._historical_anchor()
                preimage.update(
                    account=account,
                    host_pid=pid,
                    host_run_id=self.old_run,
                    locks=[
                        dict(path=str(p), device=p.stat().st_dev, inode=p.stat().st_ino)
                        for p in self.locks
                    ],
                )
                self._stop_signals = self.identity(self.folder / "signals.sqlite")
                self._stop_requires_permit = False
                self._stop_ordinary = None
                self._stop_historical_anchor = anchor
                self._stop_process_identity = birth
                return dict(
                    candidate=dict(tag=self.tag, commit=exact),
                    preimage=preimage,
                    account=account,
                    host=host_fact(
                        pid,
                        self.old_run,
                        switch.digest(self._prove(pid, "trade", self.old_config)),
                    ),
                    historical_account=retained_history(local),
                    old_config_path=str(self.old_config),
                    source=self._source(),
                    historical_contract_anchor=anchor,
                    process_identity=birth,
                    source_lock=source_lock,
                )

        def preflight(self, snapshot):
            """An isolated SDK interpreter reads exactly this source; no API instance."""
            args = [str(self.settings.sdk_python), "-I", "-B", str(self.code /
                    "scripts/ops/macos/simnow-preparation-recovery.py"), "check-source", "--config", str(self.config)]
            result = subprocess.run(args, input=json.dumps(snapshot["source"], sort_keys=True),
                                    capture_output=True, text=True, timeout=60, check=False)
            try:
                proof = json.loads(result.stdout)
            except (TypeError, ValueError):
                switch.fail("CANDIDATE_UNPROVEN")
            if result.returncode:
                switch.fail("CANDIDATE_UNPROVEN")
            self.validate_preflight(snapshot, proof)
            return proof

        def validate_preflight(self, snapshot, proof):
            expected = {"status", "diagnostic", "checked_at", "valid_until", "source_sha256",
                        "config_sha256", "sdk_sha256", "controller_sha256"}
            now = datetime.now(UTC)
            if (type(proof) is not dict or set(proof) != expected
                or proof.get("status") != "SOURCE_PREFLIGHT_PASSED"
                or proof.get("source_sha256") != switch.digest(snapshot["source"])
                or proof.get("config_sha256") != self.identity(self.config)["sha256"]
                or proof.get("sdk_sha256") != self.identity(self.settings.sdk_python, interpreter=True)["sha256"]
                or proof.get("controller_sha256") != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                or proof.get("diagnostic", {}).get("code") != "PASSED"
                or not all(type(value) is bool and value for value in proof.get("diagnostic", {}).get("checks", {}).values())):
                switch.fail("CANDIDATE_UNPROVEN")
            issued, expiry = (datetime.fromisoformat(proof[key]) for key in ("checked_at", "valid_until"))
            if (issued.tzinfo is None or expiry.tzinfo is None or not issued <= now < expiry
                or not timedelta(0) < expiry - issued <= timedelta(seconds=60)):
                switch.fail("PLAN_EXPIRED")

        def stop(self, pid, *, expires_at, clock=time.time):
            self._prove(pid, "trade", self.old_config)
            if (self.identity(self.folder / "signals.sqlite") != self._stop_signals
                or self._historical_anchor() != self._stop_historical_anchor):
                switch.fail("PREIMAGE_CHANGED")
            # Repeat the birth check after potentially slow authority reads and
            # immediately before the fixed cooperative signal.
            if pid != self.old_pid or process_identity(pid, self.run) != self._stop_process_identity:
                switch.fail("HOST_UNPROVEN")
            if clock() >= expires_at:
                switch.fail("PLAN_EXPIRED")
            os.kill(pid, signal.SIGTERM)

        def stopped(self, snapshot):
            pid = snapshot["host"]["pid"]
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                if process_identity(pid, self.run) == snapshot["process_identity"]:
                    return False
            status = json.loads(switch.private(self.folder / "continuous.json").read_bytes())
            return status["status"] == "STOPPED" and status["run_id"] == snapshot["host"]["run_id"]

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
                authority=self._window,
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
                and control.get("account_recovery_hold") is True
            ):
                return None
            pid = self._pid()
            if (control["run_id"] == self.old_run or
                pid == self.old_pid and process_identity(pid, self.run) == snapshot["process_identity"]):
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
                account_recovery_hold=True,
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
        if source_lock_identity(snapshot["old_config_path"], self.switch) != snapshot["source_lock"]:
            self.switch.fail("PREIMAGE_CHANGED")
        proof = self.backend.preflight(snapshot)
        now = self.clock()
        plan = dict(
            schema=SCHEMA, created_at=now, expires_at=now + 60, snapshot=snapshot,
            sdk_preflight=proof,
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
        identity = source_lock_identity(plan["snapshot"]["old_config_path"], self.switch)
        if identity != plan["snapshot"]["source_lock"]:
            self.switch.fail("PREIMAGE_CHANGED")
        with deployment_lock():
            fd = os.open(source_lock, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                held = os.fstat(fd)
                if (held.st_dev, held.st_ino) != (identity["device"], identity["inode"]):
                    self.switch.fail("PREIMAGE_CHANGED")
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if self.backend.snapshot() != plan["snapshot"]:
                    self.switch.fail("PREIMAGE_CHANGED")
                # The plan's actual SDK proof is exact-source-bound, short-lived,
                # and revalidated against this fresh snapshot before any effect.
                self.backend.validate_preflight(plan["snapshot"], plan["sdk_preflight"])
                if not plan["created_at"] <= self.clock() < plan["expires_at"]:
                    self.switch.fail("PLAN_EXPIRED")
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
                    self.backend.stop(snapshot["host"]["pid"], expires_at=plan["expires_at"], clock=self.clock)
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
                    origin = dict(
                            schema="simnow_adapter_preparation_recovery_intent_v1",
                            stage="START_REQUESTED",
                            source=snapshot["source"],
                            config_path=str(self.backend.config),
                            config_sha256=hashlib.sha256(
                                self.backend.config.read_bytes()
                            ).hexdigest(),
                            old_run_id=snapshot["host"]["run_id"],
                            old_pid=snapshot["host"]["pid"],
                            old_pid_exited=True,
                            created_at=datetime.now(UTC).isoformat(),
                        )
                    if "pre_native_parent" in snapshot["source"]:
                        origin["old_process_identity"] = snapshot["process_identity"]
                    self.switch.write_private(
                        intent, origin,
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


def check_source(settings, source):
    """Pure core check in the configured SDK interpreter, with no state writes."""
    from guiyi_quant.simnow_execution import preparation_recovery as permit
    from guiyi_quant.simnow_execution import deployment_connection as io
    at = datetime.now(UTC)
    ends = [datetime.fromisoformat(item["end"]) for item in source["window"]["sessions"]
            if datetime.fromisoformat(item["start"]) <= at < datetime.fromisoformat(item["end"])]
    if not ends:
        raise ValueError("WINDOW_UNPROVEN")
    diagnostic = permit.preflight_source(settings, source, at, min(at + timedelta(seconds=300), min(ends)),
                                         authority_window)
    completed = datetime.now(UTC)
    until = min(completed + timedelta(seconds=60), min(ends))
    if not completed < until:
        raise ValueError("WINDOW_UNPROVEN")
    return dict(status="SOURCE_PREFLIGHT_PASSED", diagnostic=diagnostic, checked_at=completed.isoformat(),
                valid_until=until.isoformat(), source_sha256=hashlib.sha256(io._bytes(source)).hexdigest(),
                config_sha256=settings.source_config_sha256, sdk_sha256=io.sdk_identity(settings.sdk_python)["sha256"],
                controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def bootstrap(root, config, *, isolated=False):
    """Add configured API dependencies before app imports; never import a gateway."""
    sys.dont_write_bytecode = True
    os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on"
    sys.path[:0] = [str(root / "services/quant-api"), str(root / "packages/quant-core")]
    from guiyi_quant.simnow_execution.settings import load_settings
    settings = load_settings(config)
    if settings.project_root != root or isolated and Path(sys.executable).resolve() != settings.sdk_python.resolve():
        raise ValueError("CANDIDATE_UNPROVEN")
    site = settings.api_env / "lib" / ("python" + str(sys.version_info.major) + "." +
                                       str(sys.version_info.minor)) / "site-packages"
    if not site.is_dir() or site.is_symlink():
        raise ValueError("CANDIDATE_UNPROVEN")
    sys.path.append(str(site))
    from app.private_settings import private_dependency_settings
    spec = importlib.util.spec_from_file_location("preparation_env", root / "scripts/broker/simnow_supervisor.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    values, unused = private_dependency_settings(Path.home() / "Library/Application Support/GuiyiQuant/project.env")
    environment = runner.dependency_environment(values)
    changed = any(os.environ.get(key) != value for key, value in environment.items())
    os.environ.update(environment)
    if changed:
        os.execv(sys.executable, [sys.executable, "-I" if isolated else "-B", "-B",
                                 str(Path(__file__).resolve()), *sys.argv[1:]])
    from app.core.env import PROJECT_ROOT
    if PROJECT_ROOT != root:
        raise ValueError("CANDIDATE_UNPROVEN")
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "check-source"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plist", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--diagnostic", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    try:
        settings = bootstrap(root, args.config, isolated=args.action == "check-source")
        if args.action == "check-source":
            raw = sys.stdin.buffer.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("CANDIDATE_UNPROVEN")
            print(json.dumps(check_source(settings, json.loads(raw)), sort_keys=True))
            return 0
        if any(value is None for value in (args.plist, args.directory, args.probe, args.diagnostic)):
            raise ValueError("CANDIDATE_UNPROVEN")
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
        from guiyi_quant.simnow_execution.preparation_recovery import guard_diagnostic
        code = str(error)
        print(
            json.dumps(
                dict(
                    status="BLOCKED",
                    code=code
                    if re.fullmatch("[A-Z_]{1,80}", code)
                    else "RECOVERY_UNPROVEN",
                    diagnostic=guard_diagnostic(),
                )
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
