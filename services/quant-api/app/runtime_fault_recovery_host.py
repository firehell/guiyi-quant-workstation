"""Host adapter for the exact fault-recovery state machine. No eager I/O."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
from time import monotonic, sleep

from app.runtime_bindings import (
    read_bindings,
    bindings_sha256,
    verify_release,
    contract_fingerprints,
    authorized_program_arguments,
    write_bindings,
)
from app.runtime_handover import (
    runtime_directory,
    deployment_lock,
    read_service_state,
    request_drain,
    cancel_drain,
    owner_lock_available,
    _read,
)
from app.runtime_fault_recovery import (
    CONTINUOUS,
    CALENDARS,
    FaultRecoveryError,
    require,
)
from app.reference_trading.recovery_campaign import digest


class FaultRecoveryHost:
    def __init__(
        self,
        *,
        projection_sha256=None,
        reference_plan=None,
        reference_attempt=None,
        outage_plan=None,
        outage_plan_hash=None,
        outage_attempt=None,
        reference_plan_hash=None,
    ):
        self.projection_sha256 = projection_sha256
        self.reference_plan = reference_plan
        self.reference_attempt = reference_attempt
        self.reference_plan_hash = reference_plan_hash
        self.outage_plan, self.outage_plan_hash, self.outage_attempt = (
            outage_plan,
            outage_plan_hash,
            outage_attempt,
        )
        self.directory = runtime_directory()
        self.home = Path.home()

    bindings = staticmethod(read_bindings)
    binding_hash = staticmethod(bindings_sha256)
    verify_release = staticmethod(verify_release)
    contracts = staticmethod(contract_fingerprints)
    deployment_guard = staticmethod(deployment_lock)

    def bytes(self, path, *, limit=None):
        from app.runtime_identity import file_snapshot as _snapshot

        path = Path(path)
        if limit is None:
            # Retain the historical after-market status limit at the policy caller.
            from app.market_data.after_market_limits import MAX_STATUS_BYTES

            size_limit = MAX_STATUS_BYTES if path.name == "after-market-status.json" else 1024 * 1024
            return _snapshot(path, limit=size_limit)[0]
        require(
            path.is_absolute() and path.parent.resolve() == path.parent,
            "FAULT_RECOVERY_FILE_UNSAFE",
        )
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            require(
                stat.S_ISREG(before.st_mode)
                and before.st_uid == os.getuid()
                and before.st_nlink == 1
                and not before.st_mode & 0o022
                and before.st_size <= limit,
                "FAULT_RECOVERY_FILE_UNSAFE",
            )
            raw = os.read(fd, limit + 1)

            def identity(item):
                return (
                    item.st_dev,
                    item.st_ino,
                    item.st_size,
                    item.st_mtime_ns,
                    item.st_ctime_ns,
                )

            require(
                len(raw) == before.st_size
                and identity(before) == identity(os.fstat(fd))
                and identity(before) == identity(path.lstat()),
                "FAULT_RECOVERY_FILE_DRIFT",
            )
            return raw
        finally:
            os.close(fd)

    def launch(self, *args, missing=False):
        result = subprocess.run(
            ["/bin/launchctl", *args], capture_output=True, timeout=15
        )
        require(
            result.returncode == 0 or missing and result.returncode == 113,
            "FAULT_RECOVERY_LAUNCHD_UNKNOWN",
        )
        return result

    def path(self, binding):
        return self.home / "Library/LaunchAgents" / f"{binding.label}.plist"

    def loaded(self, binding, *, idle=False, allow_idle=False):
        from app.runtime_identity import read_launchd_service as _read_launchd_service, verify_loaded_service as _verify_loaded_service
        from app.runtime_identity import launchd_arguments as _arguments, launchd_environments as _environments

        output = _read_launchd_service(binding.label, root=Path(binding.root))
        if output is None:
            return None
        working = self.home if binding.service in ("api", "web") else Path(binding.root)
        fields = _verify_loaded_service(
            output,
            root=Path(binding.root),
            commit=binding.commit,
            working_directory=working,
            allow_idle=idle or allow_idle,
            require_idle=idle,
        )
        require(
            _arguments(output) == authorized_program_arguments(binding, self.home)
            and any(
                env.get("GUIYI_RUNTIME_GENERATION") == str(binding.generation)
                and env.get("GUIYI_RUNTIME_TAG") == binding.tag
                for env in _environments(output)
            ),
            "FAULT_RECOVERY_LOADED_IDENTITY_INVALID",
        )
        return fields.get("pid")

    def protected(self, old):
        from app.db.session import SessionLocal
        from app.alerts.models import AlertRule
        from app.notifications.newow import NewowNotificationPolicy
        from app.reference_trading.models import ReferenceStream
        from sqlalchemy import select, text

        with SessionLocal() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            rules = [
                dict(row._mapping)
                for row in session.execute(
                    select(
                        AlertRule.id,
                        AlertRule.rule_code,
                        AlertRule.enabled,
                        AlertRule.scope_product_frequencies,
                        AlertRule.created_at,
                        AlertRule.updated_at,
                    ).order_by(AlertRule.id)
                )
            ]
            policy = [
                dict(row._mapping)
                for row in session.execute(
                    select(
                        NewowNotificationPolicy.policy_id,
                        NewowNotificationPolicy.enabled,
                        NewowNotificationPolicy.enabled_at,
                        NewowNotificationPolicy.topic_hash,
                        NewowNotificationPolicy.products,
                    ).order_by(NewowNotificationPolicy.policy_id)
                )
            ]
            identities = [
                dict(row._mapping)
                for row in session.execute(
                    select(
                        ReferenceStream.stream_id,
                        ReferenceStream.identity_hash,
                        ReferenceStream.strategy_code,
                        ReferenceStream.formula_versions,
                        ReferenceStream.profile_id,
                        ReferenceStream.reference_model_version,
                        ReferenceStream.futures_adaptation_version,
                        ReferenceStream.product,
                        ReferenceStream.frequency,
                        ReferenceStream.series_kind,
                        ReferenceStream.recording_mode,
                        ReferenceStream.observation_policy_version,
                        ReferenceStream.enabled,
                    )
                    .where(ReferenceStream.enabled.is_(True))
                    .order_by(ReferenceStream.stream_id)
                )
            ]
            schema = (
                session.execute(text("SELECT version_num FROM alembic_version"))
                .scalars()
                .all()
            )
        # No credentials or external topic name enter the artifact. Changing
        # only the explicit recovery generations/checkpoints is permitted.
        db = digest(
            {
                "rules": rules,
                "policy": policy,
                "reference_identities": identities,
                "schema": schema,
            }
        )
        roots = {Path(item.root) for item in old.services.values()}
        files = {}
        for root in roots:
            for name in (
                "after-market-status.json",
                "after-market-history.json",
                "market-runtime-enabled",
                "alert-runtime-enabled",
                "reference-worker-enabled",
                "weekly-audit-enabled",
            ):
                path = root / ".run" / name
                if path.exists():
                    files[str(path)] = sha256(self.bytes(path)).hexdigest()
        # Prior failures/unknown attempts remain byte-for-byte protected.
        for pattern in (
            "*generation*.json",
            "*deployment*.json",
            "*scheduled-update.json",
        ):
            for path in self.directory.glob(pattern):
                files[str(path)] = sha256(self.bytes(path)).hexdigest()
        for item in old.services.values():
            env = plistlib.loads(self.bytes(self.path(item))).get(
                "EnvironmentVariables", {}
            )
            private_config = env.get("GUIYI_ALERT_NOTIFICATION_CONFIG_PATH")
            if private_config:
                files[private_config] = sha256(
                    self.bytes(Path(private_config))
                ).hexdigest()
        files[str(self.directory / "project.env")] = sha256(
            self.bytes(self.directory / "project.env")
        ).hexdigest()
        return {"db_scope_policy_identity_sha256": db, "files": files}

    def assert_protected(self, plan):
        from app.runtime_fault_recovery import registry

        current = self.protected(registry(plan["old"]))
        require(current == plan["protected"], "FAULT_RECOVERY_PROTECTED_FACT_DRIFT")

    def installed(self, reg):
        result = {}
        for name, binding in reg.services.items():
            raw = self.bytes(self.path(binding))
            payload = plistlib.loads(raw)
            self.verify_plist(binding, payload)
            pid = self.loaded(binding, idle=name in CALENDARS, allow_idle=True)
            result[name] = {
                "plist_hex": raw.hex(),
                "sha256": sha256(raw).hexdigest(),
                "loaded_pid": pid,
            }
        result["launcher_sha256"] = sha256(
            self.bytes(self.directory / "run-local-service.sh")
        ).hexdigest()
        return result

    def verify_plist(self, binding, payload):
        env = payload.get("EnvironmentVariables", {})
        require(
            not set(env)
            - {
                "PATH",
                "GUIYI_PROJECT_ROOT",
                "GUIYI_RUNTIME_COMMIT",
                "GUIYI_RUNTIME_TAG",
                "GUIYI_RUNTIME_GENERATION",
                "GUIYI_RUNTIME_HANDOVER_ENABLED",
                "GUIYI_OBSERVATION_STREAM_ENABLED",
                "GUIYI_ALERT_NOTIFICATION_CONFIG_PATH",
            },
            "FAULT_RECOVERY_PLIST_PRIVATE_CONFIG_FORBIDDEN",
        )
        require(
            payload.get("Label") == binding.label
            and tuple(payload.get("ProgramArguments", ()))
            == authorized_program_arguments(binding, self.home)
            and payload.get("WorkingDirectory")
            == (str(self.home) if binding.service in ("api", "web") else binding.root)
            and all(
                env.get(key) == value
                for key, value in {
                    "GUIYI_PROJECT_ROOT": binding.root,
                    "GUIYI_RUNTIME_COMMIT": binding.commit,
                    "GUIYI_RUNTIME_TAG": binding.tag,
                    "GUIYI_RUNTIME_GENERATION": str(binding.generation),
                    "GUIYI_RUNTIME_HANDOVER_ENABLED": "1",
                    "GUIYI_OBSERVATION_STREAM_ENABLED": "1",
                }.items()
            ),
            "FAULT_RECOVERY_PLIST_IDENTITY_INVALID",
        )
        if binding.service in CALENDARS:
            require(
                payload.get("RunAtLoad") is False
                and payload.get("KeepAlive") is False
                and bool(payload.get("StartCalendarInterval")),
                "FAULT_RECOVERY_CALENDAR_INVALID",
            )

    def old_health(self, reg):
        return {
            name: {
                "owner": read_service_state(name),
                "raw_hex": self.bytes(self.directory / f"{name}.owner.json").hex(),
            }
            for name in CONTINUOUS
        }

    def assert_installed(self, reg, preimage):
        for name, binding in reg.services.items():
            require(
                sha256(self.bytes(self.path(binding))).hexdigest()
                == preimage[name]["sha256"],
                "FAULT_RECOVERY_PLIST_DRIFT",
            )
        require(
            sha256(self.bytes(self.directory / "run-local-service.sh")).hexdigest()
            == preimage["launcher_sha256"],
            "FAULT_RECOVERY_LAUNCHER_DRIFT",
        )

    def request_drain(self, name, generation):
        return request_drain(name, generation=generation)

    def assert_parked(self, old, effects):
        for name in CONTINUOUS:
            binding = old.services[name]
            state, control = (
                read_service_state(name),
                _read(self.directory / f"{name}.handover.json"),
            )
            request = effects["drain:" + name]
            require(
                state
                and state.get("phase") == "parked"
                and state.get("ready") is False
                and state.get("generation") == 16
                and control
                and control.get("phase") == "drain"
                and control.get("generation") == 16
                and control.get("request_id") == request
                and str(state.get("pid")) == str(self.loaded(binding)),
                "FAULT_RECOVERY_OLD_PARK_UNPROVEN",
            )

    def await_parked(self, old, effects, *, seconds):
        deadline = monotonic() + seconds
        while monotonic() < deadline:
            try:
                self.assert_parked(old, effects)
                require(
                    all(owner_lock_available(name) for name in CONTINUOUS),
                    "FAULT_RECOVERY_OWNER_BUSY",
                )
                from app.redis_connections import get_redis_connection

                redis = get_redis_connection()
                try:
                    raw = redis.get("live:feed:heartbeat")
                    require(raw is not None, "FAULT_RECOVERY_FEED_CLOSE_MISSING")
                    feed = json.loads(raw)
                finally:
                    redis.close()
                return {
                    "owners": {name: read_service_state(name) for name in CONTINUOUS},
                    "feed_close": feed,
                    "at": datetime.now(UTC).isoformat(),
                }
            except FaultRecoveryError:
                sleep(0.1)
        raise FaultRecoveryError("FAULT_RECOVERY_OLD_PARK_TIMEOUT")

    def verify_feed_closed(self, binding, proof):
        value = proof["feed_close"]
        at = datetime.fromisoformat(value["generated_at"])
        require(
            at.tzinfo
            and 0 <= (datetime.now(UTC) - at).total_seconds() <= 30
            and value.get("runtime_generation") == 16
            and value.get("runtime_commit") == binding.commit
            and value.get("runtime_root") == binding.root
            and value.get("runtime_tag") == binding.tag
            and value.get("input_pending_count") == 0
            and value.get("subscribed_count") == 0
            and value.get("input_failure") is None,
            "FAULT_RECOVERY_FEED_CLOSE_UNPROVEN",
        )

    @contextmanager
    def owner_guards(self, old):
        descriptors = []
        try:
            for name in CONTINUOUS:
                path = self.directory / f"{name}.owner.lock"
                fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
                info = os.fstat(fd)
                require(
                    stat.S_ISREG(info.st_mode)
                    and info.st_uid == os.getuid()
                    and info.st_nlink == 1
                    and not info.st_mode & 0o077,
                    "FAULT_RECOVERY_LOCK_INVALID",
                )
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                descriptors.append(fd)
            yield
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def after_market_guard(self):
        from app.market_data.live_recovery_guard import after_market_recovery_guard

        return after_market_recovery_guard(wait=False)

    @contextmanager
    def maintenance_guard(self):
        from app.db.session import SessionLocal
        from app.market_data.catalog import MarketCatalog
        from app.market_data.composition import canonical_root

        with SessionLocal() as session:
            lease = MarketCatalog(session, canonical_root()).acquire_maintenance_lock()
            require(lease is not None, "SOURCE_BUSY")
            try:
                yield
            finally:
                lease.release()

    def verify_projection_restore(self, plan, effects):
        raw = self.bytes(Path(plan["projection_readback"]))
        expected = plan.get("projection_sha256") or self.projection_sha256
        require(
            expected is not None and sha256(raw).hexdigest() == expected,
            "FAULT_RECOVERY_RESTORE_READBACK_DRIFT",
        )
        value = json.loads(raw)
        require(
            value.get("status") == "PROJECTION_RESTORED"
            and value.get("evidence_class") == "task_repair"
            and value.get("source_cursor_unchanged") is True
            and value.get("completed_prefix_unchanged") is True
            and value.get("natural_status_unchanged") is True
            and value.get("remaining_missing_bars") == 0
            and value.get("drain_executed") is False,
            "FAULT_RECOVERY_PROJECTION_RESTORE_REQUIRED",
        )
        old = next(iter(plan["old"]["services"].values()))
        require(
            value.get("runtime") == {"root": old["root"], "commit": old["commit"]},
            "FAULT_RECOVERY_RESTORE_IDENTITY_INVALID",
        )
        exact_services = {
            "after-market",
            "market-feed",
            "live",
            "alert",
            "reference-worker",
        }
        require(
            set(value.get("bindings", {})) == exact_services,
            "FAULT_RECOVERY_RESTORE_BINDING_DRIFT",
        )
        for name in exact_services:
            require(
                value["bindings"][name] == plan["old"]["services"][name],
                "FAULT_RECOVERY_RESTORE_BINDING_DRIFT",
            )
        new = plan["new"]["services"]["api"]
        require(
            value.get("candidate") == {"root": new["root"], "commit": new["commit"]},
            "FAULT_RECOVERY_RESTORE_CANDIDATE_DRIFT",
        )
        at = datetime.fromisoformat(value["at"])
        parked_at = datetime.fromisoformat(effects["parked_proof"]["at"])
        require(
            at.tzinfo is not None
            and parked_at.tzinfo is not None
            and parked_at <= at <= datetime.now(UTC),
            "FAULT_RECOVERY_RESTORE_TIME_UNPROVEN",
        )
        actual = self.projection_journal_readback()
        require(
            all(
                value.get(key) == actual[key]
                for key in (
                    "source_count",
                    "completed_count",
                    "source_cursor",
                    "source_tail",
                )
            ),
            "FAULT_RECOVERY_RESTORE_JOURNAL_DRIFT",
        )
        natural = value.get("natural_status_preimage", {})
        for name in ("after-market-status.json", "after-market-history.json"):
            key = str(Path(old["root"]) / ".run" / name)
            require(
                natural.get(name) == plan["protected"]["files"].get(key),
                "FAULT_RECOVERY_RESTORE_NATURAL_STATUS_DRIFT",
            )
        return {
            "sha256": expected,
            "path": plan["projection_readback"],
            "authority_hash": value["authority_hash"],
            "plan_sha256": value["plan_sha256"],
        }

    def projection_journal_readback(self):
        from datetime import date
        from app.redis_connections import get_redis_connection
        from app.market_data.observation_stream import ObservationStream

        redis = get_redis_connection()
        try:
            day = date(2026, 10, 12)
            source, completed = (
                ObservationStream(redis, kind="source"),
                ObservationStream(redis, kind="completed"),
            )
            return {
                "source_count": redis.xlen(source.key(day)),
                "completed_count": redis.xlen(completed.key(day)),
                "source_cursor": source.cursor("live", day),
                "source_tail": source.tail(day),
            }
        finally:
            redis.close()

    def fault_window(self, plan, effects):
        """Quiesced publisher repair window, including an active night Session.

        Session authority is still mandatory. TRADING is permitted only after
        the sealed old Feed retired, every gen16 lifecycle parked/released and
        all calendars are idle or absent. No generic promotion gate changes.
        """
        from app.runtime_fault_recovery import registry

        old = registry(plan["old"])
        if self.bindings() == old:
            self.assert_parked(old, effects)
            require(
                all(owner_lock_available(name) for name in CONTINUOUS),
                "FAULT_RECOVERY_OWNER_BUSY",
            )
        else:
            require(
                all(self.definition_absent(old.services[name]) for name in CONTINUOUS),
                "FAULT_RECOVERY_OLD_LABEL_PRESENT",
            )
            self.assert_old_pids_exited(effects["parked_proof"])
        sealed = effects["parked_proof"]["feed_close"]
        require(
            sealed.get("input_pending_count") == 0
            and sealed.get("subscribed_count") == 0
            and sealed.get("runtime_generation") == 16
            and sealed.get("runtime_commit") == old.services["market-feed"].commit,
            "FAULT_RECOVERY_SEALED_PUBLISHER_UNPROVEN",
        )
        from app.runtime_scheduled import ScheduledBackend

        for name in CALENDARS:
            if self.bindings() == old:
                require(
                    ScheduledBackend().idle(old.services[name]),
                    "FAULT_RECOVERY_CALENDAR_BUSY",
                )
            else:
                require(
                    self.definition_absent(self.bindings().services[name]),
                    "FAULT_RECOVERY_CALENDAR_LABEL_PRESENT",
                )
        from app.db.session import SessionLocal
        from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
        from app.market_data.operational_universe import load_operational_products
        from app.market_data.composition import build_market_data_service

        now = datetime.now(UTC)
        phases = {}
        with SessionLocal() as session:
            products = load_operational_products()
            resolver, mds = (
                MarketPhaseResolver(session),
                build_market_data_service(session),
            )
            require(len(products) == 60, "FAULT_RECOVERY_UNIVERSE_INVALID")
            for product in products:
                phase = resolver.resolve(product, now)
                require(
                    phase.phase is not MarketPhase.UNKNOWN,
                    "FAULT_RECOVERY_SESSION_UNPROVEN",
                )
                if phase.trading_day is not None:
                    mds.dominant_segment_for_day(product, phase.trading_day)
                phases[product] = phase.phase.value
        return {
            "kind": "all_old_publishers_closed",
            "session_phases": phases,
            "old_generation": 16,
            "new_generation": 17,
            "checked_at": now.isoformat(),
        }

    def assert_idle_or_parked(self, binding, effects):
        if binding.service in CALENDARS:
            from app.runtime_scheduled import ScheduledBackend

            require(ScheduledBackend().idle(binding), "FAULT_RECOVERY_CALENDAR_BUSY")
        else:
            require(
                read_service_state(binding.service).get("phase") == "parked",
                "FAULT_RECOVERY_OLD_PARK_UNPROVEN",
            )

    def stop(self, binding):
        target = f"gui/{os.getuid()}/{binding.label}"
        self.launch("disable", target)
        if (
            self.loaded(binding, idle=binding.service in CALENDARS) is not None
            or binding.service in CALENDARS
        ):
            self.launch("bootout", target, missing=True)
        require(self.definition_absent(binding), "FAULT_RECOVERY_LABEL_STILL_LOADED")
        return {"label": binding.label, "absent": True}

    def assert_old_pids_exited(self, proof):
        deadline = monotonic() + 10
        while monotonic() < deadline:
            remaining = []
            for state in proof["owners"].values():
                try:
                    os.kill(int(state["pid"]), 0)
                    remaining.append(state["pid"])
                except ProcessLookupError:
                    continue
            if not remaining:
                return
            sleep(0.1)
        raise FaultRecoveryError("FAULT_RECOVERY_OLD_PID_EXIT_UNPROVEN")

    def retain_history(self, old, new, plan):
        from app.market_data.after_market_history import make_history, publish_history
        from app.market_data.operational_universe import load_operational_products

        source = (
            Path(old.services["after-market"].root) / ".run/after-market-status.json"
        )
        raw = self.bytes(source)
        require(
            sha256(raw).hexdigest() == plan["protected"]["files"][str(source)],
            "FAULT_RECOVERY_HISTORY_DRIFT",
        )
        history = make_history(
            raw,
            commit=old.services["after-market"].commit,
            products=load_operational_products(),
            now=datetime.now(UTC),
        )
        target = (
            Path(new.services["after-market"].root) / ".run/after-market-history.json"
        )
        require(not target.exists(), "FAULT_RECOVERY_HISTORY_TARGET_EXISTS")
        publish_history(target, history)
        require(
            not (target.parent / "after-market-status.json").exists(),
            "FAULT_RECOVERY_NATURAL_STATUS_FORGED",
        )
        return {
            "retained_sha256": sha256(self.bytes(target)).hexdigest(),
            "source_commit": history["source_commit"],
        }

    def install(self, old, new, plan):
        payload = plistlib.loads(
            bytes.fromhex(plan["installed"][old.service]["plist_hex"])
        )
        env = dict(payload["EnvironmentVariables"])
        env.update(
            GUIYI_PROJECT_ROOT=new.root,
            GUIYI_RUNTIME_TAG=new.tag,
            GUIYI_RUNTIME_COMMIT=new.commit,
            GUIYI_RUNTIME_GENERATION="17",
            GUIYI_RUNTIME_HANDOVER_ENABLED="1",
            GUIYI_OBSERVATION_STREAM_ENABLED="1",
        )
        payload.update(
            EnvironmentVariables=env,
            WorkingDirectory=str(self.home)
            if new.service in ("api", "web")
            else new.root,
            ProgramArguments=list(authorized_program_arguments(new, self.home)),
            Disabled=False,
        )
        if new.service in CALENDARS:
            payload.update(RunAtLoad=False, KeepAlive=False)
        self.verify_plist(new, payload)
        # Atomic plist replacement with fsync, same owner-private directory.
        raw = plistlib.dumps(payload)
        path = self.path(new)
        require(not path.is_symlink(), "FAULT_RECOVERY_PLIST_UNSAFE")
        import tempfile

        fd, temp = tempfile.mkstemp(prefix=".gen17-plist-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(raw)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        markers = {
            "live": "market-runtime-enabled",
            "alert": "alert-runtime-enabled",
            "reference-worker": "reference-worker-enabled",
            "weekly-audit": "weekly-audit-enabled",
        }
        if new.service in markers:
            source = Path(old.root) / ".run" / markers[new.service]
            require(self.bytes(source) == b"enabled\n", "FAULT_RECOVERY_MARKER_DRIFT")
            target = Path(new.root) / ".run" / markers[new.service]
            self.install_marker(target)
        return {"plist_sha256": sha256(raw).hexdigest()}

    def install_marker(self, path):
        require(not path.exists(), "FAULT_RECOVERY_MARKER_TARGET_EXISTS")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(b"enabled\n")
            file.flush()
            os.fsync(file.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def install_launcher(self, new, plan):
        raw = self.bytes(
            Path(new.services["api"].root)
            / "scripts/ops/macos/runtime-service-dispatch.sh"
        )
        path = self.directory / "run-local-service.sh"
        require(
            sha256(self.bytes(path)).hexdigest()
            == plan["installed"]["launcher_sha256"],
            "FAULT_RECOVERY_LAUNCHER_DRIFT",
        )
        # Reuse the existing launcher only when byte-identical; replacing it is
        # a separately reviewed effect, and is unnecessary for this exact patch.
        require(self.bytes(path) == raw, "FAULT_RECOVERY_LAUNCHER_CHANGE_UNSUPPORTED")
        return {"sha256": sha256(raw).hexdigest(), "unchanged": True}

    def commit_bindings(self, new, old_hash):
        return write_bindings(new, expected_sha256=old_hash)

    def assert_new_installed(self, new):
        for binding in new.services.values():
            self.verify_plist(binding, plistlib.loads(self.bytes(self.path(binding))))

    def definition_absent(self, binding):
        from app.runtime_identity import read_launchd_service as _read_launchd_service

        return _read_launchd_service(binding.label, root=Path(binding.root)) is None

    def start(self, binding):
        require(self.definition_absent(binding), "FAULT_RECOVERY_START_LABEL_PRESENT")
        self.launch("enable", f"gui/{os.getuid()}/{binding.label}")
        self.launch("bootstrap", f"gui/{os.getuid()}", str(self.path(binding)))
        return {"label": binding.label, "bootstrapped": True}

    def verify_calendar(self, binding):
        from app.runtime_scheduled import ScheduledBackend
        from app.runtime_identity import read_launchd_service as _read_launchd_service

        require(
            _read_launchd_service(binding.label, root=Path(binding.root)) is not None
            and ScheduledBackend().idle(binding),
            "FAULT_RECOVERY_CALENDAR_IDLE_UNPROVEN",
        )
        self.verify_plist(binding, plistlib.loads(self.bytes(self.path(binding))))

    def start_calendar(self, binding):
        from app.runtime_bootstrap import BootstrapBackend

        payload = plistlib.loads(self.bytes(self.path(binding)))
        BootstrapBackend()._assert_recovery_calendar_safe(payload)
        return self.start(binding)

    def await_new_reference_parked(self, binding, request, *, held_guard=None):
        """Prove parked ownership using the caller's actual held fd, or a free lock.

        Controller calls leave held_guard unset and still require release. The
        maintenance Reference CLI passes its inode-validating guard while it
        owns the kernel lock; probing a second fd would conflict with itself.
        """
        deadline = monotonic() + 30
        while monotonic() < deadline:
            if held_guard is not None:
                held_guard()
            state, control = (
                read_service_state("reference-worker"),
                _read(self.directory / "reference-worker.handover.json"),
            )
            if (
                state
                and state.get("generation") == 17
                and state.get("phase") == "parked"
                and state.get("ready") is False
                and control
                and control.get("request_id") == request
                and control.get("generation") == 17
                and control.get("phase") == "drain"
                and (held_guard is not None or owner_lock_available("reference-worker"))
                and str(state.get("pid")) == str(self.loaded(binding))
            ):
                return
            sleep(0.1)
        raise FaultRecoveryError("FAULT_RECOVERY_NEW_REFERENCE_PARK_TIMEOUT")

    def verify_partial_started(self, new):
        # This is expressly not Runtime Ready while Reference stays parked.
        for name in ("live", "alert", "api", "web"):
            require(
                self.loaded(new.services[name]) is not None,
                "FAULT_RECOVERY_NEW_PROCESS_MISSING",
            )

    def verify_reference_recovery(self, new, effects):
        self.await_new_reference_parked(
            new.services["reference-worker"], effects["reference17_request"]
        )
        from app.redis_connections import get_redis_connection
        from app.market_data.observation_stream import ObservationStream

        redis = get_redis_connection()
        try:
            completed = ObservationStream(redis, kind="completed")
            require(
                all(
                    completed.cursor("reference", day) == completed.tail(day)
                    for day in completed.days()
                ),
                "FAULT_RECOVERY_REFERENCE_NOT_AT_TAIL",
            )
        finally:
            redis.close()
        require(
            self.reference_plan is not None
            and self.reference_attempt is not None
            and self.reference_plan_hash is not None,
            "FAULT_RECOVERY_REFERENCE_READBACK_REQUIRED",
        )
        from app.reference_trading.recovery_campaign import validate_campaign
        from app.reference_trading.bounded_recovery import BoundedForwardRecovery
        from app.db.session import SessionLocal

        frozen = json.loads(
            self.bytes(Path(self.reference_plan), limit=16 * 1024 * 1024)
        )
        plans = validate_campaign(frozen, expected_hash=self.reference_plan_hash)
        identity = frozen["identity"]
        binding = new.services["reference-worker"]
        require(
            identity["code_root"] == binding.root
            and identity["code_commit"] == binding.commit
            and identity["binding"] == asdict(binding)
            and len(plans) == 180,
            "FAULT_RECOVERY_REFERENCE_IDENTITY_DRIFT",
        )
        events = [
            json.loads(line)
            for line in self.bytes(
                Path(self.reference_attempt) / "progress.jsonl"
            ).splitlines()
        ]
        require(
            events
            and events[0].get("plan_hash") == self.reference_plan_hash
            and events[-1].get("stage") == "finished"
            and events[-1].get("cursor") == frozen["tail_id"]
            and not any(item.get("stage") == "stopped_no_retry" for item in events),
            "FAULT_RECOVERY_REFERENCE_ATTEMPT_UNPROVEN",
        )
        recovery = BoundedForwardRecovery(SessionLocal, verify_gap=lambda *_: ())
        for plan in plans:
            require(
                recovery.readback(plan) is not None
                and recovery.consumed_calculation(plan) is not None,
                "FAULT_RECOVERY_REFERENCE_DB_READBACK_FAILED",
            )
        require(
            self.outage_plan is not None
            and self.outage_plan_hash is not None
            and self.outage_attempt is not None,
            "FAULT_RECOVERY_OUTAGE_READBACK_REQUIRED",
        )
        outage = json.loads(self.bytes(Path(self.outage_plan), limit=16 * 1024 * 1024))
        outage_plans = validate_campaign(outage, expected_hash=self.outage_plan_hash)
        require(
            outage["day"] == "2026-10-13"
            and len(outage_plans) == 180
            and len({item.capture.stream_id for item in outage_plans}) == 180
            and {item.capture.stream_id for item in outage_plans}
            == {item.capture.stream_id for item in plans}
            and {group["product"] for group in outage["groups"]}
            == {group["product"] for group in frozen["groups"]}
            and outage["identity"]["binding"] == asdict(binding)
            and outage["identity"]["code_root"] == binding.root
            and outage["identity"]["code_commit"] == binding.commit
            and outage["identity"]["outage_controller_plan_hash"]
            == effects["controller_plan_hash"]
            and all(
                item.journal_proof.get("kind") == "SERVICE_OUTAGE"
                and item.capture.input_payload["reason"] == "SERVICE_OUTAGE"
                and item.journal_proof["fence"]["old_feed_close"]
                == effects["parked_proof"]["feed_close"]
                and datetime.fromisoformat(item.journal_proof["cutoff"])
                <= datetime.now(UTC)
                for item in outage_plans
            ),
            "FAULT_RECOVERY_OUTAGE_IDENTITY_DRIFT",
        )
        outage_events = [
            json.loads(line)
            for line in self.bytes(
                Path(self.outage_attempt) / "progress.jsonl"
            ).splitlines()
        ]
        require(
            outage_events
            and outage_events[0].get("plan_hash") == self.outage_plan_hash
            and outage_events[-1].get("stage") == "finished"
            and not any(
                item.get("stage") == "stopped_no_retry" for item in outage_events
            ),
            "FAULT_RECOVERY_OUTAGE_ATTEMPT_UNPROVEN",
        )
        require(
            all(
                recovery.readback(item) is not None
                and recovery.consumed_calculation(item) is not None
                for item in outage_plans
            ),
            "FAULT_RECOVERY_OUTAGE_DB_READBACK_FAILED",
        )
        return {
            "plan_hash": self.reference_plan_hash,
            "streams": 180,
            "outage_plan_hash": self.outage_plan_hash,
            "progress_sha256": sha256(
                self.bytes(Path(self.reference_attempt) / "progress.jsonl")
            ).hexdigest(),
        }

    def assert_old_consumers_at_boundary(self, plan, new):
        from app.runtime_deployment import observation_progress

        require(
            all(
                row["cursor"] == row["tail"]
                for row in observation_progress("live").values()
            ),
            "FAULT_RECOVERY_SOURCE_NOT_DRAINED",
        )
        for service in ("alert", "reference-worker"):
            require(
                all(
                    row["cursor"] == row["tail"]
                    for row in observation_progress(service).values()
                ),
                "FAULT_RECOVERY_COMPLETED_NOT_DRAINED",
            )

    def cancel_reference_drain(self, binding, request):
        control = _read(self.directory / "reference-worker.handover.json")
        require(
            control
            and control.get("generation") == 17
            and control.get("request_id") == request
            and control.get("phase") == "drain",
            "FAULT_RECOVERY_REFERENCE_REQUEST_DRIFT",
        )
        cancel_drain("reference-worker", request_id=request)
        return {"request_id": request, "cancelled": True}

    def await_reference_ready(self, binding):
        self.await_ready_names(
            {binding.service: binding}, ("reference-worker",), seconds=60
        )

    def await_ready_names(self, bindings, names, *, seconds):
        from app.runtime_deployment import owner_process_matches

        deadline = monotonic() + seconds
        while monotonic() < deadline:
            accepted = True
            for name in names:
                binding, state = bindings[name], read_service_state(name)
                accepted = accepted and bool(
                    state
                    and state.get("generation") == 17
                    and state.get("phase") == "active"
                    and state.get("ready") is True
                    and owner_process_matches(state, binding)
                    and 0
                    <= (
                        datetime.now(UTC) - datetime.fromisoformat(state["at"])
                    ).total_seconds()
                    <= 30
                )
                if name == "reference-worker" and state:
                    proof = state.get("proof", {}).get("reference_runtime", {})
                    accepted = (
                        accepted
                        and proof.get("blocked_count") == 0
                        and proof.get("stage") == "cycle"
                    )
                    accepted = (
                        accepted
                        and proof.get("historical_refresh_alive") is True
                        and proof.get("notifications_alive") is True
                    )
            if accepted:
                return
            sleep(0.2)
        raise FaultRecoveryError("FAULT_RECOVERY_NEW_READY_TIMEOUT")

    def await_full_ready(self, new):
        self.await_ready_names(new.services, CONTINUOUS, seconds=120)
        from app.redis_connections import get_redis_connection

        redis = get_redis_connection()
        try:
            for name, key in (
                ("live", "live:heartbeat"),
                ("market-feed", "live:feed:heartbeat"),
            ):
                raw = redis.get(key)
                require(raw is not None, "FAULT_RECOVERY_NEW_HEARTBEAT_MISSING")
                value = json.loads(raw)
                binding = new.services[name]
                require(
                    value.get("available") is True
                    and value.get("operational_count") == 60
                    and all(
                        value.get(key) == expected
                        for key, expected in {
                            "runtime_generation": 17,
                            "runtime_commit": binding.commit,
                            "runtime_root": binding.root,
                            "runtime_tag": "v1.15.4",
                        }.items()
                    )
                    and 0
                    <= (
                        datetime.now(UTC)
                        - datetime.fromisoformat(value["generated_at"])
                    ).total_seconds()
                    <= 30,
                    "FAULT_RECOVERY_NEW_HEARTBEAT_INVALID",
                )
        finally:
            redis.close()

    def halt_unknown(self, new):
        """Cooperative drain only; never kill or restart an uncertain writer."""
        require(self.bindings() == new, "FAULT_RECOVERY_HALT_REGISTRY_DRIFT")
        requested, failed = {}, []
        for name in CONTINUOUS:
            try:
                requested[name] = request_drain(name, generation=17)
            except Exception:
                failed.append(name)
        for name in CALENDARS:
            try:
                self.launch("disable", f"gui/{os.getuid()}/{new.services[name].label}")
            except Exception:
                failed.append(name)
        return {"requests": requested, "failed": failed, "force_kill": False}
