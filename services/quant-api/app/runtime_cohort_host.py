"""Exact Mac host operations for a bounded, all-service cold release."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from fnmatch import fnmatchcase
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
from time import monotonic, sleep

from app.runtime_cohort import CONTINUOUS, CALENDARS, CohortError, WARMUP_SAFE_CODES, registry, require
from app.runtime_fault_recovery_host import FaultRecoveryHost
from app.runtime_bindings import (
    authorized_program_arguments,
    contract_fingerprints,
    write_bindings,
)
from app.runtime_handover import (
    read_service_state,
    owner_lock_available,
    cancel_drain,
)
from app.runtime_deployment import (
    observation_progress,
    progress_reached,
    assert_no_unknown_deployment,
    owner_process_matches,
)


IDENTITY_NAMES = {
    "live": "live_market",
    "reference-worker": "reference_worker",
    "after-market": "after_market",
    "late-provider-recovery": "late_provider_recovery",
    "weekly-audit": "weekly_audit",
}


def _warmup_failure(service, condition, code=None):
    error = CohortError("COHORT_CANDIDATE_WARMUP_FAILED")
    error.service = service
    error.warmup_condition = condition
    error.warmup_code = code if code is None or isinstance(code, str) and code in WARMUP_SAFE_CODES else "COHORT_OPERATION_BLOCKED"
    return error


class CohortHost(FaultRecoveryHost):
    now = staticmethod(lambda: datetime.now(UTC))

    def bytes(self, path, *, limit=None):
        path = Path(path)
        if (limit is None and path.parent == self.directory
                and path.name == "newow-historical-refresh-state.json"):
            # Preserve the original control bytes under their existing reader
            # contract; ordinary config and other paths keep their smaller cap.
            from app.reference_trading.historical_refresh import MAX_REFRESH_STATE_BYTES
            from app.runtime_identity import file_snapshot

            return file_snapshot(path, limit=MAX_REFRESH_STATE_BYTES)[0]
        if (
            limit is None
            and path.parent == self.directory
            and any(
                fnmatchcase(path.name, pattern)
                for pattern in (
                    "*generation*.json",
                    "*deployment*.json",
                    "*scheduled-update.json",
                )
            )
        ):
            # Existing recovery evidence can exceed the ordinary config limit.
            # Keep the same fd/directory/owner/link/race checks and a finite cap.
            from app.runtime_identity import file_snapshot

            return file_snapshot(path, limit=8 * 1024 * 1024)[0]
        return super().bytes(path, limit=limit)

    def installed(self, reg):
        from app.runtime_identity import read_launchd_service

        result = super().installed(reg)
        for name, binding in reg.services.items():
            loaded = (
                read_launchd_service(binding.label, root=Path(binding.root)) is not None
            )
            require(
                (self.loaded(binding, allow_idle=True) == result[name]["loaded_pid"])
                if loaded
                else result[name]["loaded_pid"] is None,
                "COHORT_LOADED_PREIMAGE_CHANGED",
            )
            result[name]["loaded"] = loaded
            if name in CONTINUOUS and binding.enabled:
                state = read_service_state(name)
                if state and state.get("phase") == "parked":
                    from app.runtime_handover import _read

                    control = _read(self.directory / f"{name}.handover.json")
                    require(
                        loaded and state.get("generation") == binding.generation
                        and str(state.get("pid")) == str(result[name]["loaded_pid"])
                        and owner_process_matches(state, binding)
                        and owner_lock_available(name, runtime_dir=self.directory),
                        "COHORT_PARKED_PREIMAGE_UNPROVEN",
                    )
                    self._check_parked_control(name, binding, control)
                    result[name]["parked_drain"] = control
        return result

    @staticmethod
    def _check_parked_control(name, binding, control):
        require(
            isinstance(control, dict)
            and set(control) == {"schema_version", "service", "generation", "request_id", "phase"}
            and type(control["schema_version"]) is int and control["schema_version"] == 1
            and control["service"] == name
            and type(control["generation"]) is int and control["generation"] == binding.generation
            and isinstance(control["request_id"], str)
            and re.fullmatch(r"[0-9a-f]{32}", control["request_id"])
            and control["phase"] == "drain",
            "COHORT_PARKED_DRAIN_UNPROVEN",
        )

    def _preserved_drain(self, plan, name):
        from app.runtime_handover import _read

        control = plan["installed"].get(name, {}).get("parked_drain")
        if control is not None:
            self._check_parked_control(name, registry(plan["old"]).services[name], control)
            require(_read(self.directory / f"{name}.handover.json") == control,
                    "COHORT_PARKED_DRAIN_CHANGED")
        return control

    def session_proof(self):
        from app.db.session import SessionLocal
        from app.db.readonly import readonly_transaction
        from app.market_data.composition import build_market_feed_service
        from app.market_data.market_phase import MarketPhaseResolver, MarketPhase
        from app.market_data.operational_universe import load_operational_products

        now = self.now()
        with (
            SessionLocal() as session,
            readonly_transaction(session, timeout_seconds=20),
        ):
            products = load_operational_products()
            require(len(products) == 60, "COHORT_SCOPE_INVALID")
            resolver = MarketPhaseResolver(session)
            phases = {p: resolver.resolve(p, now) for p in products}
            require(
                all(
                    v.phase in (MarketPhase.CLOSED, MarketPhase.BREAK)
                    and v.current_session is None
                    for v in phases.values()
                ),
                "COHORT_REST_WINDOW_REQUIRED",
            )
            require(
                all(
                    v.next_session_start is not None
                    and v.next_session_start > now + timedelta(seconds=660)
                    for v in phases.values()
                ),
                "COHORT_WINDOW_TOO_SHORT_OR_UNKNOWN",
            )
            feed = build_market_feed_service(session)
            require(feed.quiescent(now), "COHORT_SESSION_GRACE_OR_AUTHORITY_UNKNOWN")
            # Live consumers are started before Feed. Match the exact same
            # Calendar/Session day authority used by JournalLiveMarketService;
            # this protocol cannot initialize a newer day while Feed is stopped.
            from app.redis_connections import get_redis_connection
            from app.market_data.observation_stream import ObservationStream

            days = set()
            for product, phase in phases.items():
                if phase.trading_day is not None:
                    days.add(phase.trading_day)
                else:
                    upcoming = resolver.resolve(product, phase.next_session_start)
                    require(
                        upcoming.phase is MarketPhase.TRADING
                        and upcoming.trading_day is not None
                        and upcoming.current_session is not None
                        and upcoming.current_session.start == phase.next_session_start,
                        "COHORT_NEXT_SESSION_DAY_UNPROVEN",
                    )
                    days.add(upcoming.trading_day)
            try:
                redis = get_redis_connection()
                try:
                    registered = ObservationStream(redis, kind="source").registered_day(
                        "live"
                    )
                finally:
                    redis.close()
            except Exception:
                raise CohortError("COHORT_REGISTERED_DAY_UNPROVEN") from None
            require(days == {registered}, "COHORT_DAY_INITIALIZATION_REQUIRED")
            return {
                "registered_trading_day": registered.isoformat(),
                "mode": "closed_idle",
                "products": len(products),
                "phases": {
                    p: {
                        "phase": v.phase.value,
                        "trading_day": v.trading_day.isoformat()
                        if v.trading_day
                        else None,
                        "next_session_start": v.next_session_start.isoformat(),
                    }
                    for p, v in phases.items()
                },
            }

    def schema_compatibility(self, old, new):
        """Known preinstalled additive schema only; this never runs a migration."""
        from app.runtime_schema_compatibility import (
            tracked_db_contract, prove_reference_inbox_addition,
            verify_installed_reference_inbox, SchemaCompatibilityError,
        )
        from app.db.session import SessionLocal
        try:
            target = next(iter(new.services.values()))
            new_files, new_heads = tracked_db_contract(Path(target.root))
            with SessionLocal() as session:
                installed = verify_installed_reference_inbox(session)
            transitions = {}
            roots = {}
            for binding in old.services.values():
                if binding.contracts["db"] == target.contracts["db"]:
                    continue
                if binding.root not in roots:
                    roots[binding.root] = tracked_db_contract(Path(binding.root))
                old_files, old_heads = roots[binding.root]
                proof = prove_reference_inbox_addition(old_files, new_files,
                    old_heads=old_heads, new_heads=new_heads, installed=installed)
                require(proof["old_db"] == binding.contracts["db"]
                        and proof["new_db"] == target.contracts["db"], "COHORT_CONTRACT_DRIFT")
                prior = transitions.setdefault(binding.contracts["db"], proof)
                require(prior == proof, "COHORT_SCHEMA_PROOF_DRIFT")
            require(bool(transitions), "COHORT_SCHEMA_PROOF_UNEXPECTED")
            return transitions
        except SchemaCompatibilityError as error:
            raise CohortError(str(error)) from None

    def check_schema_compatibility(self, plan):
        if "schema_compatibility" not in plan:
            return
        old, new = registry(plan["old"]), registry(plan["new"])
        require(self.schema_compatibility(old, new) == plan["schema_compatibility"],
                "COHORT_SCHEMA_PROOF_DRIFT")

    @contextmanager
    def _reference_receiving_context(self, target):
        from app.reference_trading.receiving_handover import target_supports_receiving_handover
        from app.reference_trading.inbox_protocol import build_receiving_protocol
        from app.runtime_schema_compatibility import verify_installed_reference_inbox
        from app.market_data.observation_stream import ObservationStream
        from app.redis_connections import get_redis_connection
        from app.db.session import SessionLocal
        from app.db.readonly import readonly_transaction
        from app.reference_trading.models import ReferenceStream, ReferenceInboxInput, ReferenceInboxDelivery
        from app.reference_trading.inbox import _digest, _aware
        from sqlalchemy import select, func, exists

        require(target_supports_receiving_handover(Path(target.root)), "COHORT_REFERENCE_TARGET_UNSUPPORTED")
        protocol = build_receiving_protocol()
        if protocol.read() is None:
            yield None
            return
        with SessionLocal() as session:
            schema = verify_installed_reference_inbox(session)
        redis = get_redis_connection()
        try:
            journal = ObservationStream(redis, kind="completed")
            days = journal.days()
            with SessionLocal() as session, readonly_transaction(session, timeout_seconds=20):
                activations = session.execute(select(ReferenceStream.stream_id, ReferenceStream.identity_hash,
                    ReferenceStream.active_revision_id, ReferenceStream.activation_generation,
                    ReferenceStream.recording_start, ReferenceStream.activation_plan_hash).where(
                    ReferenceStream.enabled.is_(True), ReferenceStream.recording_mode == "forward_observation")
                    .order_by(ReferenceStream.stream_id)).all()
                require(all(revision is not None and type(generation) is int and generation > 0 and start is not None
                            and isinstance(plan_hash, str) and re.fullmatch(r"[0-9a-f]{64}", plan_hash)
                            for _stream, _identity, revision, generation, start, plan_hash in activations),
                        "COHORT_REFERENCE_ACTIVATION_UNPROVEN")
                fixed = [(*row[:4], _aware(row[4]).astimezone(UTC).isoformat(), row[5]) for row in activations]
                resolved = ()
                if schema["revision"] == "20261028_0054":
                    from app.reference_trading.inbox_recovery import verified_resolution_ids
                    resolved = verified_resolution_ids(session)
                unfinished = exists(select(1).where(ReferenceInboxDelivery.input_id == ReferenceInboxInput.input_id,
                                                    ReferenceInboxDelivery.status != "COMPLETED",
                                                    ReferenceInboxDelivery.delivery_id.not_in(resolved)))
                used = session.scalar(select(func.coalesce(func.sum(ReferenceInboxInput.payload_bytes), 0)).where(unfinished))
                by_day = session.execute(select(ReferenceInboxInput.trading_day, func.count()).where(
                    ReferenceInboxInput.trading_day.in_(days)).group_by(ReferenceInboxInput.trading_day)).all()
            authority = {"schema": schema, "activation_sha256": _digest(fixed), "enabled_count": len(fixed)}
            capacity = {"unfinished_bytes": int(used), "day_inputs": {day.isoformat(): count for day, count in by_day}}
            yield protocol, journal, authority, capacity
        finally:
            redis.close()

    def freeze_reference_receiving_handover(self, new):
        from app.reference_trading.receiving_handover import target_supports_receiving_handover, freeze_receiving_intent
        target = new.services["reference-worker"]
        if not target_supports_receiving_handover(Path(target.root)):
            return None  # Legacy candidates retain every original backlog gate.
        try:
            with self._reference_receiving_context(target) as context:
                if context is None:
                    return None
                protocol, journal, authority, _capacity = context
                return freeze_receiving_intent(protocol, journal, target=asdict(target), schema_proof=authority)
        except Exception:
            raise CohortError("COHORT_REFERENCE_BACKLOG_UNPROVEN") from None

    def check_reference_receiving_intent(self, plan):
        if "reference_receiving_handover" not in plan:
            return
        from app.reference_trading.receiving_handover import verify_receiving_intent
        target = registry(plan["new"]).services["reference-worker"]
        try:
            with self._reference_receiving_context(target) as context:
                require(context is not None, "COHORT_REFERENCE_BACKLOG_UNPROVEN")
                protocol, journal, authority, _capacity = context
                verify_receiving_intent(protocol, journal, plan["reference_receiving_handover"],
                                        target=asdict(target), schema_proof=authority)
        except Exception:
            raise CohortError("COHORT_REFERENCE_BACKLOG_UNPROVEN") from None

    def _reference_handover_budget(self, plan):
        require(monotonic() < self.deadline, "COHORT_DOWNTIME_EXCEEDED")
        require(datetime.fromisoformat(plan["created_at"]) <= self.now() < datetime.fromisoformat(plan["expires_at"]),
                "COHORT_PLAN_EXPIRED")

    def seal_reference_receiving_handover(self, plan, progress):
        from app.reference_trading.receiving_handover import seal_receiving_backlog
        target = registry(plan["new"]).services["reference-worker"]
        try:
            self._reference_handover_budget(plan)
            with self._reference_receiving_context(target) as context:
                require(context is not None, "COHORT_REFERENCE_BACKLOG_UNPROVEN")
                protocol, journal, authority, capacity = context
                proof = seal_receiving_backlog(protocol, journal, plan["reference_receiving_handover"],
                    target=asdict(target), schema_proof=authority, progress=progress, capacity=capacity,
                    check_budget=lambda: self._reference_handover_budget(plan))
            self._reference_handover_budget(plan)
            self._reference_receiving_drain = proof
            return proof
        except Exception:
            raise CohortError("COHORT_REFERENCE_BACKLOG_UNPROVEN") from None

    def check_reference_receiving_handover(self, plan, proof):
        if "reference_receiving_handover" not in plan:
            return
        from app.reference_trading.receiving_handover import verify_receiving_backlog
        target = registry(plan["new"]).services["reference-worker"]
        try:
            self._reference_handover_budget(plan)
            with self._reference_receiving_context(target) as context:
                require(context is not None, "COHORT_REFERENCE_BACKLOG_UNPROVEN")
                protocol, journal, authority, capacity = context
                verify_receiving_backlog(protocol, journal, plan["reference_receiving_handover"],
                    proof["reference_receiving_handover"], target=asdict(target), schema_proof=authority,
                    capacity=capacity, check_budget=lambda: self._reference_handover_budget(plan))
            self._reference_handover_budget(plan)
        except Exception:
            raise CohortError("COHORT_REFERENCE_BACKLOG_UNPROVEN") from None

    def check_plan(self, plan):
        self.check_reference_receiving_intent(plan)
        self.check_schema_compatibility(plan)
        assert_no_unknown_deployment(cohort_plan_sha256=plan["plan_sha256"])
        old, new = registry(plan["old"]), registry(plan["new"])
        require(
            self.bindings() == old and self.binding_hash() == plan["registry_sha256"],
            "COHORT_REGISTRY_DRIFT",
        )
        for binding in (*old.services.values(), *new.services.values()):
            self.verify_release(Path(binding.root), binding.tag, binding.commit)
            require(
                binding.contracts == contract_fingerprints(Path(binding.root)),
                "COHORT_CONTRACT_DRIFT",
            )
        require(self.installed(old) == plan["installed"], "COHORT_INSTALLED_DRIFT")
        require(self.protected(old) == plan["protected"], "COHORT_PROTECTED_FACT_DRIFT")
        require(self.session_proof() == plan["window"], "COHORT_SESSION_CHANGED")

    @staticmethod
    def _candidate_sources(value, root, tag):
        try:
            sources = value["source_roots"]
            if sources["project_root"] != str(root) or sources["version"] != tag[1:]:
                return False
            for name, package in (
                ("app", root / "services/quant-api/app"),
                ("core", root / "packages/quant-core/guiyi_quant"),
            ):
                path = Path(sources[name])
                if (
                    not path.is_absolute()
                    or not path.is_file()
                    or path.resolve() != path
                    or not path.is_relative_to(package)
                ):
                    return False
            return True
        except (KeyError, TypeError, ValueError, OSError):
            return False

    @staticmethod
    def _verify_web_dependencies(root):
        node = Path("/opt/homebrew/bin/node")
        vite = root / "apps/quant-web/node_modules/vite/bin/vite.js"
        require(node.is_file() and vite.is_file(), "COHORT_WEB_DEPENDENCY_MISSING")
        try:
            result = subprocess.run(
                [str(node), str(vite), "--version"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            require(
                result.returncode == 0 and "vite/" in result.stdout,
                "COHORT_WEB_DEPENDENCY_INVALID",
            )
        except (OSError, subprocess.TimeoutExpired):
            raise CohortError("COHORT_WEB_DEPENDENCY_INVALID") from None

    def prewarm(self, plan):
        old, new = registry(plan["old"]), registry(plan["new"])
        root = Path(new.services["api"].root)
        if old.services["web"].enabled:
            self._verify_web_dependencies(root)
        for name, binding in new.services.items():
            if binding.label != old.services[name].label:
                require(
                    not os.path.lexists(self.path(binding)),
                    "COHORT_TARGET_PLIST_CONFLICT",
                )
        marker_names = {
            "live": "market-runtime-enabled",
            "alert": "alert-runtime-enabled",
            "reference-worker": "reference-worker-enabled",
            "weekly-audit": "weekly-audit-enabled",
        }
        for service, name in marker_names.items():
            if not old.services[service].enabled:
                continue
            source = Path(old.services[service].root) / ".run" / name
            require(self.bytes(source) == b"enabled\n", "COHORT_ACTIVATION_UNPROVEN")
            target = root / ".run" / name
            if target.exists():
                require(
                    self.bytes(target) == b"enabled\n", "COHORT_TARGET_MARKER_DRIFT"
                )
            else:
                self.install_marker(target)
        proofs = {}
        for service in (
            "api",
            "web",
            "live",
            "alert",
            "reference-worker",
            "market-feed",
        ):
            if not old.services[service].enabled:
                continue
            env = dict(os.environ)
            b = new.services[service]
            previous_payload = plistlib.loads(
                bytes.fromhex(plan["installed"][service]["plist_hex"])
            )
            # Only the existing private config path is copied; no secret enters the plan.
            notification_path = previous_payload["EnvironmentVariables"].get(
                "GUIYI_ALERT_NOTIFICATION_CONFIG_PATH"
            )
            if notification_path:
                env["GUIYI_ALERT_NOTIFICATION_CONFIG_PATH"] = notification_path
            env.update(
                GUIYI_PROJECT_ROOT=b.root,
                GUIYI_RUNTIME_COMMIT=b.commit,
                GUIYI_RUNTIME_TAG=b.tag,
                GUIYI_RUNTIME_GENERATION=str(b.generation),
                GUIYI_RUNTIME_HANDOVER_ENABLED="1",
                GUIYI_OBSERVATION_STREAM_ENABLED="1",
            )
            try:
                result = subprocess.run(
                    [
                        str(root / "services/quant-api/.venv/bin/python"),
                        "-m",
                        "app.runtime_cohort",
                        "warmup",
                        service,
                    ],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    # Full scoped Alert replay runs before the downtime budget.
                    timeout=600 if service == "alert" else 120,
                    check=False,
                )
                value = json.loads(result.stdout.strip().splitlines()[-1])
                if not isinstance(value, dict):
                    raise _warmup_failure(service, "output_invalid")
                if result.returncode != 0 or value.get("status") != "ready":
                    raise _warmup_failure(service, "candidate_blocked", value.get("code"))
                if value.get("service") != service or not self._candidate_sources(value, root, b.tag):
                    raise _warmup_failure(service, "source_identity", "COHORT_CANDIDATE_SOURCE_IDENTITY_UNPROVEN")
                proofs[service] = value.get("proof")
            except CohortError:
                raise
            except subprocess.TimeoutExpired:
                raise _warmup_failure(service, "subprocess_timeout") from None
            except OSError:
                raise _warmup_failure(service, "execution_failed") from None
            except (ValueError, IndexError):
                raise _warmup_failure(service, "output_invalid") from None
        return proofs

    def suspend_calendars(self, plan):
        from app.runtime_scheduled import ScheduledBackend

        old = registry(plan["old"])
        backend = ScheduledBackend()
        for name in CALENDARS:
            binding = old.services[name]
            backend.freeze(binding)
            require(backend.idle(binding), "COHORT_CALENDAR_BUSY")
            self.launch("disable", f"gui/{os.getuid()}/{binding.label}")
            require(backend.idle(binding), "COHORT_CALENDAR_START_RACE")
            self._bootout_old_once(
                binding,
                plan["installed"][name].get("loaded_pid"),
                deadline=min(self.deadline, monotonic() + 30),
            )
        return {"idle_unloaded": list(CALENDARS)}

    def _await_old_absent(self, binding, pid, *, deadline):
        """After one bootout request, observe label removal before PID exit."""
        while monotonic() < deadline:
            if self.definition_absent(binding):
                if pid is None:
                    return
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return
                except OSError:
                    raise CohortError("COHORT_OLD_PID_EXIT_UNPROVEN") from None
            sleep(0.1)
        raise CohortError("COHORT_OLD_BOOTOUT_TIMEOUT")

    def _bootout_old_once(self, binding, pid, *, deadline):
        if pid is not None:
            require(
                type(pid) is int
                and pid > 1
                or isinstance(pid, str)
                and re.fullmatch(r"[1-9][0-9]*", pid)
                and int(pid) > 1,
                "COHORT_OLD_PID_UNPROVEN",
            )
            pid = int(pid)
        requests = getattr(self, "bootout_requests", None)
        if requests is None:
            requests = self.bootout_requests = {}
        require(binding.service not in requests, "COHORT_BOOTOUT_ALREADY_REQUESTED")
        # Record before the call: even an uncertain launchctl result consumes
        # this request and restore must first observe its teardown boundary.
        requests[binding.service] = {"label": binding.label, "pid": pid}
        self.launch("bootout", f"gui/{os.getuid()}/{binding.label}", missing=True)
        self._await_old_absent(binding, pid, deadline=deadline)

    def drain(self, plan):
        old = registry(plan["old"])
        self.drains = {}
        for name in CONTINUOUS:
            binding = old.services[name]
            if not binding.enabled:
                continue
            preserved = self._preserved_drain(plan, name)
            self.drains[name] = (preserved["request_id"] if preserved is not None
                                 else self.request_drain(name, binding.generation))
            deadline = min(self.deadline, monotonic() + 10)
            while monotonic() < deadline:
                state = read_service_state(name)
                if (
                    state
                    and state.get("phase") == "parked"
                    and state.get("generation") == binding.generation
                    and str(state.get("pid"))
                    == str(self.loaded(binding, allow_idle=True))
                    and (preserved is None or str(state.get("pid"))
                         == str(plan["installed"][name]["loaded_pid"]))
                    and owner_lock_available(name)
                ):
                    break
                sleep(0.05)
            else:
                error = CohortError("COHORT_OLD_DRAIN_TIMEOUT")
                error.service = name
                raise error
        from app.redis_connections import get_redis_connection

        redis = get_redis_connection()
        try:
            raw = redis.get("live:feed:heartbeat")
            require(raw is not None, "COHORT_FEED_CLOSE_MISSING")
            value = json.loads(raw)
        finally:
            redis.close()
        feed = old.services["market-feed"]
        require(
            value.get("runtime_commit") == feed.commit
            and value.get("runtime_generation") == feed.generation
            and value.get("input_pending_count") == 0
            and value.get("input_failure") is None
            and value.get("subscribed_count") == 0
            and 0
            <= (
                self.now() - datetime.fromisoformat(value["generated_at"])
            ).total_seconds()
            <= 30,
            "COHORT_FEED_CLOSE_UNPROVEN",
        )
        self.session_proof()
        progress = {
            name: observation_progress(name)
            for name in ("market-feed", "live", "alert", "reference-worker")
        }
        require(
            all(
                value["cursor"] == value["tail"]
                for name, values in progress.items() if name != "reference-worker"
                for value in values.values()
            ),
            "COHORT_OBSERVATION_BACKLOG",
        )
        reference_handover = None
        if "reference_receiving_handover" in plan:
            reference_handover = self.seal_reference_receiving_handover(plan, progress["reference-worker"])
        else:
            require(all(value["cursor"] == value["tail"] for value in progress["reference-worker"].values()),
                    "COHORT_OBSERVATION_BACKLOG")
        from app.db.session import SessionLocal
        from sqlalchemy import select, func
        from app.reference_trading.models import ReferenceBatch, ReferenceStream

        with SessionLocal() as session:
            require(
                session.scalar(
                    select(func.count())
                    .select_from(ReferenceBatch)
                    .join(
                        ReferenceStream,
                        ReferenceStream.stream_id == ReferenceBatch.stream_id,
                    )
                    .where(
                        ReferenceStream.enabled.is_(True),
                        ReferenceBatch.revision_id
                        == ReferenceStream.active_revision_id,
                        ReferenceBatch.kind == "capture",
                        ReferenceBatch.consumed_by_batch_id.is_(None),
                    )
                )
                == 0,
                "COHORT_PENDING_CAPTURE",
            )
        return {
            "owners": {name: read_service_state(name) for name in CONTINUOUS},
            "progress": progress,
            "feed_close": value,
            **({"reference_receiving_handover": reference_handover} if reference_handover is not None else {}),
        }

    @contextmanager
    def guards(self, plan):
        with ExitStack() as stack:
            stack.enter_context(self.after_market_guard())
            stack.enter_context(self.maintenance_guard())
            stack.enter_context(self.owner_guards(registry(plan["old"])))
            yield

    def stop_old(self, plan, proof):
        old = registry(plan["old"])
        for name in CONTINUOUS:
            binding = old.services[name]
            self.launch("disable", f"gui/{os.getuid()}/{binding.label}")
            pid = proof["owners"][name]["pid"]
            require(pid is not None, "COHORT_OLD_PID_UNPROVEN")
            self._bootout_old_once(
                binding,
                pid,
                deadline=min(self.deadline, monotonic() + 30),
            )
        self.session_proof()
        return {
            "old_pids_exited": True,
            "bootout_requests": dict(self.bootout_requests),
        }

    @staticmethod
    def _sync_directory(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _private_original(path, raw):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    @contextmanager
    def _stable_state_guard(self, path):
        lock = path.with_suffix(".lock")
        fd = os.open(
            lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
        )
        try:
            item = os.fstat(fd)
            require(
                stat.S_ISREG(item.st_mode)
                and item.st_uid == os.getuid()
                and item.st_nlink == 1
                and not stat.S_IMODE(item.st_mode) & 0o077,
                "COHORT_STABLE_STATE_LOCK_UNSAFE",
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CohortError("COHORT_STABLE_STATE_BUSY") from None
            yield
        finally:
            os.close(fd)

    def preserve(self, plan, attempt):
        old, new = registry(plan["old"]), registry(plan["new"])
        require(self.protected(old) == plan["protected"], "COHORT_PROTECTED_FACT_DRIFT")
        evidence = attempt / "originals"
        evidence.mkdir(mode=0o700)
        self._sync_directory(attempt)
        stable = tuple(
            self.directory / name
            for name in (
                "market-day-metadata-preparation.json",
                "newow-historical-refresh-state.json",
            )
        )
        sources = {Path(name) for name in plan["protected"]["files"]}
        sources.update(stable)
        for service, name in (
            ("weekly-audit", "weekly-audit-status.json"),
            ("late-provider-recovery", "late-provider-recovery-status.json"),
        ):
            sources.add(Path(old.services[service].root) / ".run" / name)
        captured = {}
        index = []
        # All processes have exited and the cohort holds the maintenance/owner
        # guards. These two additional locks exclude their independent writers.
        with ExitStack() as stack:
            for path in stable:
                stack.enter_context(self._stable_state_guard(path))
            for path in sorted(sources):
                row = {"source": str(path), "present": os.path.lexists(path)}
                if row["present"]:
                    raw = self.bytes(path)
                    digest = sha256(raw).hexdigest()
                    expected = plan["protected"]["files"].get(str(path))
                    require(
                        expected is None or digest == expected, "COHORT_ORIGINAL_DRIFT"
                    )
                    name = f"{len(index):03}.bin"
                    self._private_original(evidence / name, raw)
                    row.update(file=name, sha256=digest, size_bytes=len(raw))
                    captured[path] = raw
                else:
                    require(
                        str(path) not in plan["protected"]["files"],
                        "COHORT_ORIGINAL_DRIFT",
                    )
                index.append(row)
            raw_index = (
                json.dumps(
                    {"schema_version": 1, "files": index}, sort_keys=True, indent=2
                )
                + "\n"
            ).encode()
            self._private_original(evidence / "index.json", raw_index)
            self._sync_directory(evidence)
        # Stable state stays at its original path and may legitimately advance
        # after restart; its stop-boundary snapshot is evidence, not a CAS target.
        # Preserve historical evidence using the existing retained-history selection rules.
        from app.market_data.after_market import public_after_market_status
        from app.market_data.after_market_history import (
            read_history,
            make_history,
            publish_history,
        )
        from app.market_data.operational_universe import load_operational_products

        products = load_operational_products()
        source = (
            Path(old.services["after-market"].root) / ".run/after-market-status.json"
        )
        history = read_history(
            source.with_name("after-market-history.json"),
            products=products,
            now=self.now(),
        )
        if source.exists():
            raw = self.bytes(source)
            public = public_after_market_status(json.loads(raw))
            require(
                public and public.get("current_run") is None,
                "COHORT_AFTER_MARKET_RUNNING",
            )
            last = public.get("last_run") or {}
            day = public.get("last_successful_trading_day")
            retained_day = (
                history["status"].get("last_successful_trading_day")
                if history
                else None
            )
            negative = public.get("last_failure") is not None or last.get("status") in (
                "failed",
                "interrupted",
            )
            recovered = (
                last.get("status") == "passed"
                and history is not None
                and last["finished_at"] >= history["status"]["last_run"]["finished_at"]
            )
            if (
                negative
                or recovered
                or day is not None
                and (retained_day is None or day > retained_day)
            ):
                history = make_history(
                    raw,
                    commit=old.services["after-market"].commit,
                    products=products,
                    now=self.now(),
                )
        target_root = Path(new.services["after-market"].root)
        require(
            not (target_root / ".run/after-market-status.json").exists(),
            "COHORT_TARGET_STATUS_PRESENT",
        )
        if history and (target_root / ".run/after-market-history.json").exists():
            existing = read_history(
                target_root / ".run/after-market-history.json",
                products=products,
                now=self.now(),
            )
            require(
                all(
                    existing.get(k) == v
                    for k, v in history.items()
                    if k != "retained_at"
                ),
                "COHORT_TARGET_HISTORY_CONFLICT",
            )
        elif history:
            publish_history(target_root / ".run/after-market-history.json", history)
        # Weekly status is natural evidence bound to its original release.
        # It is retained only in originals, never promoted into current status.
        require(
            not os.path.lexists(target_root / ".run/weekly-audit-status.json"),
            "COHORT_TARGET_NATURAL_STATUS_PRESENT",
        )
        # Late-provider runs are separate one-shot control state (schema/runs),
        # not new-version natural acceptance. Preserve consumed and pending runs
        # byte-for-byte after the existing reader proves cross-root compatibility.
        from app.market_data.late_provider_recovery import _read as read_late_state

        late_source = (
            Path(old.services["late-provider-recovery"].root)
            / ".run/late-provider-recovery-status.json"
        )
        late_target = target_root / ".run/late-provider-recovery-status.json"
        require(not os.path.lexists(late_target), "COHORT_TARGET_LATE_STATE_PRESENT")
        if late_source in captured:
            raw = captured[late_source]
            require(
                read_late_state(late_source) == json.loads(raw),
                "COHORT_LATE_STATE_DRIFT",
            )
            self._private_original(late_target, raw)
            self._sync_directory(late_target.parent)
        self._sync_directory(attempt)
        return {
            "original_files": sum(row["present"] for row in index),
            "original_index_sha256": sha256(raw_index).hexdigest(),
            "stable_state_migrated": False,
            "history_retained": history is not None,
        }

    def install(self, plan, attempt):
        new = registry(plan["new"])
        for name, binding in new.services.items():
            payload = plistlib.loads(
                bytes.fromhex(plan["installed"][name]["plist_hex"])
            )
            env = dict(payload["EnvironmentVariables"])
            env.update(
                GUIYI_PROJECT_ROOT=binding.root,
                GUIYI_RUNTIME_COMMIT=binding.commit,
                GUIYI_RUNTIME_TAG=binding.tag,
                GUIYI_RUNTIME_GENERATION=str(binding.generation),
                GUIYI_RUNTIME_HANDOVER_ENABLED="1",
                GUIYI_OBSERVATION_STREAM_ENABLED="1",
            )
            payload.update(
                Label=binding.label,
                EnvironmentVariables=env,
                WorkingDirectory=str(self.home)
                if name in ("api", "web")
                else binding.root,
                ProgramArguments=list(authorized_program_arguments(binding, self.home)),
                Disabled=not binding.enabled,
            )
            if name in CALENDARS:
                payload.update(RunAtLoad=False, KeepAlive=False)
            else:
                payload.update(RunAtLoad=True, KeepAlive=True)
            self.verify_plist(binding, payload)
            self._replace_plist(self.path(binding), plistlib.dumps(payload))
        self.install_launcher(new, plan)
        self.assert_new_installed(new)
        self.session_proof()
        return {"installed": list(new.services)}

    @staticmethod
    def _replace_plist(path, raw):
        import tempfile

        require(not path.is_symlink(), "COHORT_PLIST_UNSAFE")
        fd, temp = tempfile.mkstemp(prefix=".cohort-plist-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def commit(self, plan):
        self.check_schema_compatibility(plan)
        old, new = registry(plan["old"]), registry(plan["new"])
        require(
            self.bindings() == old and self.binding_hash() == plan["registry_sha256"],
            "COHORT_REGISTRY_DRIFT",
        )
        require(
            all(self.definition_absent(v) for v in old.services.values()),
            "COHORT_OLD_LABEL_PRESENT",
        )
        for binding in new.services.values():
            self.verify_release(Path(binding.root), binding.tag, binding.commit)
        self.session_proof()
        if "reference_receiving_handover" in plan:
            self.check_reference_receiving_handover(plan,
                {"reference_receiving_handover": getattr(self, "_reference_receiving_drain", None)})
        now = self.now()
        require(datetime.fromisoformat(plan["created_at"]) <= now < datetime.fromisoformat(plan["expires_at"]),
                "COHORT_PLAN_EXPIRED")
        require(monotonic() < self.deadline, "COHORT_DOWNTIME_EXCEEDED")
        return write_bindings(new, expected_sha256=plan["registry_sha256"])

    def start_consumers(self, plan):
        new = registry(plan["new"])
        for name in ("live", "alert", "reference-worker", "api", "web"):
            if new.services[name].enabled:
                self.start(new.services[name])
        return {"started": "consumers"}

    def _feed_closed_healthy(self, binding, state, window):
        """A Feed poll success and its own exact heartbeat must agree.

        Feed marks not-ready before every poll, including rejected polls which
        may leave the previous heartbeat untouched. A fresh older heartbeat is
        therefore never sufficient to waive owner readiness.
        """
        from app.redis_connections import get_redis_connection

        try:
            redis = get_redis_connection()
            try:
                raw = redis.get("live:feed:heartbeat")
            finally:
                redis.close()
            if not isinstance(raw, (str, bytes)) or len(raw) > 65536:
                return False
            value = json.loads(raw)
            if not isinstance(value, dict):
                return False
            generated = datetime.fromisoformat(value["generated_at"])
            owner_at = datetime.fromisoformat(state["at"])
            phases = window["phases"]
            if not (
                window["mode"] == "closed_idle"
                and value.get("runtime_commit") == binding.commit
                and value.get("runtime_generation") == binding.generation
                and value.get("runtime_root") == binding.root
                and value.get("runtime_tag") == binding.tag
                and generated.tzinfo is not None
                and owner_at.tzinfo is not None
                and generated <= owner_at
                and 0 <= (self.now() - generated).total_seconds() <= 30
                and value.get("available") is True
                and "input_failure" in value
                and value["input_failure"] is None
                # Feed's explicit available=True also proves its internal
                # metadata error is None; reject an exported error if present.
                and value.get("metadata_preparation_error") is None
                and type(value.get("input_pending_count")) is int
                and value["input_pending_count"] == 0
                and type(value.get("subscribed_count")) is int
                and value["subscribed_count"] == 0
                and type(value.get("operational_count")) is int
                and value["operational_count"] == len(phases)
                and value.get("phase_by_product")
                == {p: row["phase"] for p, row in phases.items()}
                and all(row["phase"] in {"CLOSED", "BREAK"} for row in phases.values())
            ):
                return False
            cleaned = value.get("closed_cleaned")
            owner_proof = state.get("proof", {})
            if not isinstance(owner_proof, dict):
                return False
            if cleaned is None:
                consistent = (
                    owner_proof.get("cycle_ok") is True
                    and owner_proof.get("closed_cleaned") is None
                )
            else:
                checked = datetime.fromisoformat(cleaned["cleanup_checked_at"])
                day = date.fromisoformat(cleaned["trading_day"])
                consistent = (
                    cleaned.get("status") == "CLOSED_CLEANED"
                    and cleaned.get("cleanup_verified") is True
                    and checked.tzinfo is not None
                    and checked <= generated
                    and day.isoformat() == cleaned["trading_day"]
                    and type(cleaned.get("consumer_count")) is int
                    and cleaned["consumer_count"] >= 1
                    and type(cleaned.get("pending_count")) is int
                    and cleaned["pending_count"] == 0
                    and type(cleaned.get("remaining_bar_keys")) is int
                    and cleaned["remaining_bar_keys"] == 0
                    and cleaned.get("subscription_present") is False
                    and cleaned.get("natural_bar_verified") is False
                    and re.fullmatch(r"[0-9]+-[0-9]+", cleaned["source_cursor"])
                    is not None
                    and re.fullmatch(r"[0-9a-f]{40}", cleaned["source_commit"])
                    is not None
                    and cleaned.get("evidence_kind") in {"current", "retained"}
                    and type(cleaned.get("after_market_generation")) is int
                    and cleaned["after_market_generation"] >= 1
                    and all(row["phase"] == "CLOSED" for row in phases.values())
                    and owner_proof.get("closed_cleaned") == cleaned
                )
            return consistent and state.get("ready") is True
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return False
        except Exception:  # Redis failures remain a bounded unhealthy proof.
            return False

    def _receiving_snapshot(self, plan, proof, state, check_budget):
        from app.db.session import SessionLocal
        from app.reference_trading.receiving_liveness import (
            ReceivingControlAbort,
            ReceivingLivenessError,
            snapshot_receiving,
        )

        target = registry(plan["new"]).services["reference-worker"]
        control_error = None

        def trusted_budget():
            nonlocal control_error
            try:
                check_budget()
            except CohortError as error:
                control_error = error
                raise ReceivingControlAbort from None

        with self._reference_receiving_context(target) as context:
            require(context is not None, "COHORT_REFERENCE_SOURCE_UNPROVEN")
            protocol, journal, authority, _capacity = context
            try:
                snapshot = snapshot_receiving(
                    SessionLocal,
                    protocol,
                    journal,
                    intent=plan["reference_receiving_handover"],
                    source_proof=proof["reference_receiving_handover"],
                    target=asdict(target),
                    schema_proof=authority,
                    check_budget=trusted_budget,
                    sampled_at=self.now(),
                    owner_cycle_at=state["at"],
                )
            except ReceivingControlAbort:
                if control_error is None:
                    raise ReceivingLivenessError("REFERENCE_RECEIVING_LIVENESS_UNPROVEN") from None
                raise control_error from None
            check_budget()
            return snapshot

    def _await_names(self, plan, names, proof, seconds):
        from app.reference_trading.receiving_liveness import (
            ReceivingCycleStale,
            completed_receiving_report,
            receiving_sample_is_fresh,
            receiving_pair_candidate,
            prove_receiving_liveness,
        )

        new = registry(plan["new"])
        end = min(self.deadline, monotonic() + seconds)
        before = previous = None
        by_stage = {}

        def check_budget():
            self._reference_handover_budget(plan)
            require(monotonic() < end, "COHORT_NEW_READY_TIMEOUT")

        while monotonic() < end:
            matched = True
            accepted = {}
            window = self.session_proof()
            for name in names:
                binding = new.services[name]
                if not binding.enabled:
                    continue
                state = read_service_state(name)
                valid = bool(
                    state
                    and state.get("phase") == "active"
                    and state.get("generation") == binding.generation
                    and owner_process_matches(state, binding)
                    and 0
                    <= (
                        self.now() - datetime.fromisoformat(state["at"])
                    ).total_seconds()
                    <= 30
                )
                receiving_path = name == "reference-worker" and (
                    "reference_receiving_handover" in plan
                    or "receiving" in (state or {}).get("proof", {})
                )
                if valid and name in proof["progress"] and not receiving_path:
                    valid = progress_reached(
                        observation_progress(name),
                        proof["progress"][name],
                        service=name,
                        proof=state.get("proof"),
                    )
                mode = "active"
                if valid and name == "market-feed":
                    mode = "closed_idle"
                    valid = self._feed_closed_healthy(binding, state, window)
                elif valid and name == "reference-worker":
                    owner_proof = state.get("proof", {})
                    if receiving_path:
                        valid = (
                            "reference_receiving_handover" in plan
                            and completed_receiving_report(state)
                            and not owner_lock_available(name)
                        )
                        if valid:
                            try:
                                current = self._receiving_snapshot(
                                    plan, proof, state, check_budget
                                )
                            except ReceivingCycleStale:
                                valid = False
                            else:
                                now = self.now()
                                report_stage = owner_proof["reference_runtime"]["stage"]
                                before = by_stage.get(report_stage)
                                before, valid = receiving_pair_candidate(
                                    before, previous, current, now=now
                                )
                                by_stage[report_stage] = before
                                previous = current
                                if valid:
                                    mode = prove_receiving_liveness(
                                        before, current, now=now
                                    )["mode"]
                    else:
                        rp = owner_proof.get("reference_runtime", {})
                        valid = (
                            state.get("ready") is True
                            and rp.get("stage") == "cycle"
                            and rp.get("blocked_count") == 0
                        )
                elif valid:
                    valid = state.get("ready") is True
                matched = matched and valid
                accepted[name] = mode
            if matched:
                if any(
                    mode.startswith("durable_receiving") for mode in accepted.values()
                ):
                    require(monotonic() < end, "COHORT_NEW_READY_TIMEOUT")
                    if not all(
                        receiving_sample_is_fresh(value, now=self.now())
                        for value in (before, previous)
                    ):
                        before = previous
                        by_stage[report_stage] = previous
                        sleep(0.2)
                        continue
                return accepted
            sleep(0.2)
        raise CohortError("COHORT_NEW_READY_TIMEOUT")

    def consumers_ready(self, plan, proof):
        return self._await_names(
            plan, ("live", "alert", "reference-worker", "api", "web"), proof, 240
        )

    def start_feed(self, plan):
        binding = registry(plan["new"]).services["market-feed"]
        if binding.enabled:
            self.start(binding)
        return {"started": "market-feed"}

    def verify(self, plan, proof):
        modes = self._await_names(plan, CONTINUOUS, proof, 120)
        from app.services.deployment_identity import deployment_identity_health

        new = registry(plan["new"])
        api = new.services["api"]
        identity = deployment_identity_health(root=Path(api.root), commit=api.commit)
        # Calendars are deliberately still unloaded here; validate them after registration.
        from urllib.request import urlopen

        with urlopen("http://127.0.0.1:8000/api/health", timeout=5) as response:
            require(
                json.load(response).get("version") == api.tag[1:],
                "COHORT_API_VERSION_MISMATCH",
            )
        with urlopen("http://127.0.0.1:5173/", timeout=5) as response:
            require(response.status == 200, "COHORT_WEB_UNAVAILABLE")
        require(self.bindings() == new, "COHORT_BINDING_DRIFT")
        for name in CONTINUOUS:
            row = identity["services"].get(IDENTITY_NAMES.get(name, name), {})
            require(
                row.get("status")
                == ("matched" if new.services[name].enabled else "disabled"),
                "COHORT_CONTINUOUS_IDENTITY_UNPROVEN",
            )
        return {
            "continuous_modes": modes,
            "natural_acceptance": "pending",
            "continuous_identity": "matched",
        }

    def restore_calendars(self, plan):
        new = registry(plan["new"])
        for name in CALENDARS:
            binding = new.services[name]
            if binding.enabled:
                self.start_calendar(binding)
            else:
                self.launch("disable", f"gui/{os.getuid()}/{binding.label}")
        from app.services.deployment_identity import deployment_identity_health

        api = new.services["api"]
        identity = deployment_identity_health(root=Path(api.root), commit=api.commit)
        require(
            len(identity["services"]) == len(new.services),
            "COHORT_FINAL_IDENTITY_UNPROVEN",
        )
        for name, binding in new.services.items():
            row = identity["services"].get(IDENTITY_NAMES.get(name, name), {})
            require(
                row.get("status") == ("matched" if binding.enabled else "disabled"),
                "COHORT_FINAL_IDENTITY_UNPROVEN",
            )
        return {"calendar_registration_only": True, "identity": "matched"}

    def assert_protected(self, plan):
        require(
            self.protected(registry(plan["old"])) == plan["protected"],
            "COHORT_PROTECTED_FACT_DRIFT",
        )

    def restore_old(self, plan):
        old = registry(plan["old"])
        require(self.bindings() == old, "COHORT_OLD_RESTORE_REGISTRY_UNKNOWN")
        preserved = {name: control for name in old.services
                     if (control := self._preserved_drain(plan, name)) is not None}
        # launchctl can still report a tearing-down definition after bootout
        # returned. Do not cancel drain or mistake that definition for a live
        # restored process. Recovery has a separate finite wait budget.
        restore_deadline = monotonic() + 60
        for name, request in getattr(self, "bootout_requests", {}).items():
            require(
                name in old.services
                and request.get("label") == old.services[name].label,
                "COHORT_RESTORE_BOOTOUT_IDENTITY_CHANGED",
            )
            self._await_old_absent(
                old.services[name], request.get("pid"), deadline=restore_deadline
            )
        for name, binding in old.services.items():
            self._replace_plist(
                self.path(binding), bytes.fromhex(plan["installed"][name]["plist_hex"])
            )
        for name, request in getattr(self, "drains", {}).items():
            if name not in preserved:
                cancel_drain(name, request_id=request)
        for name, binding in old.services.items():
            preimage = plan["installed"][name]
            require(
                type(preimage.get("loaded")) is bool, "COHORT_LOADED_PREIMAGE_MISSING"
            )
            if name in preserved:
                # An old reader may not understand newly committed recovery
                # facts. Even a retained drain cannot make its startup safe:
                # old startup can initialize a writer before checking drain.
                # Keep a surviving owner parked; never restart an exited one.
                continue
            target = f"gui/{os.getuid()}/{binding.label}"
            self.launch("enable" if binding.enabled else "disable", target)
            if preimage["loaded"]:
                if self.definition_absent(binding):
                    if binding.enabled:
                        self.start(binding)
                    else:
                        # Restore a disabled idle registration without enabling
                        # it or kickstarting its scheduled business action.
                        self.launch(
                            "bootstrap", f"gui/{os.getuid()}", str(self.path(binding))
                        )
            else:
                require(
                    self.definition_absent(binding),
                    "COHORT_RESTORE_ABSENT_DEFINITION_CHANGED",
                )
        self.assert_installed(old, plan["installed"])
        new = registry(plan["new"])
        for name, binding in new.services.items():
            if (
                binding.label != old.services[name].label
                and self.path(binding).exists()
            ):
                require(
                    self.definition_absent(binding), "COHORT_RESTORE_NEW_LABEL_LOADED"
                )
                self.verify_plist(
                    binding, plistlib.loads(self.bytes(self.path(binding)))
                )
                self.path(binding).unlink()
        deadline = monotonic() + 30
        while monotonic() < deadline:
            active = True
            for name in CONTINUOUS:
                binding = old.services[name]
                if not binding.enabled:
                    continue
                state = read_service_state(name)
                if name in preserved:
                    self._preserved_drain(plan, name)
                    if self.definition_absent(binding):
                        require(owner_lock_available(name, runtime_dir=self.directory),
                                "COHORT_PARKED_OWNER_EXIT_UNPROVEN")
                        continue
                active = active and bool(
                    state
                    and state.get("phase") == ("parked" if name in preserved else "active")
                    and state.get("generation") == binding.generation
                    and owner_process_matches(state, binding)
                    and (name not in preserved or owner_lock_available(name, runtime_dir=self.directory))
                    and (name not in preserved or str(state.get("pid")) == str(plan["installed"][name]["loaded_pid"]))
                )
            if active:
                for name, binding in old.services.items():
                    if name in CALENDARS:
                        require(
                            (not self.definition_absent(binding))
                            is plan["installed"][name]["loaded"],
                            "COHORT_OLD_RESTORE_CALENDAR_UNPROVEN",
                        )
                require(not any(self.definition_absent(old.services[name]) for name in preserved),
                        "COHORT_PARKED_OWNER_FORWARD_RECOVERY_REQUIRED")
                return
            sleep(0.1)
        raise CohortError("COHORT_OLD_RESTORE_OWNER_UNPROVEN")

    def halt_unknown(self, plan):
        new = registry(plan["new"])
        if self.bindings() != new:
            return
        for name in CONTINUOUS:
            if new.services[name].enabled:
                try:
                    self.request_drain(name, new.services[name].generation)
                except Exception:
                    pass
        for name in CALENDARS:
            try:
                self.launch("disable", f"gui/{os.getuid()}/{new.services[name].label}")
            except Exception:
                pass

    def verify_old_restored(self, plan):
        """Audit an already-restored pre-CAS cohort; never start or stop anything."""
        from app.runtime_handover import _read
        from app.runtime_scheduled import ScheduledBackend
        from app.reference_trading.recovery_campaign import digest

        old, new = registry(plan["old"]), registry(plan["new"])
        require(
            self.bindings() == old and self.binding_hash() == plan["registry_sha256"],
            "COHORT_REGISTRY_DRIFT",
        )
        protected = self.protected(old)
        require(protected == plan["protected"], "COHORT_PROTECTED_FACT_DRIFT")
        releases = {}
        for binding in old.services.values():
            releases[(binding.root, binding.tag, binding.commit)] = binding.contracts
        for (root, tag, commit), contracts in releases.items():
            self.verify_release(Path(root), tag, commit)
            require(
                contract_fingerprints(Path(root)) == contracts, "COHORT_CONTRACT_DRIFT"
            )
        installed = self.installed(old)
        require(
            installed.get("launcher_sha256")
            == plan["installed"].get("launcher_sha256"),
            "COHORT_RESTORE_LAUNCHER_DRIFT",
        )
        rows = {}
        for name, binding in old.services.items():
            actual, expected = installed[name], plan["installed"][name]
            require(
                actual.get("sha256") == expected.get("sha256")
                and actual.get("plist_hex") == expected.get("plist_hex")
                and type(actual.get("loaded")) is bool
                and actual["loaded"] is expected.get("loaded"),
                "COHORT_RESTORE_INSTALLED_DRIFT",
            )
            if name in CALENDARS and actual["loaded"]:
                require(
                    ScheduledBackend().idle(binding), "COHORT_RESTORE_CALENDAR_BUSY"
                )
            rows[name] = {
                "root": binding.root,
                "tag": binding.tag,
                "commit": binding.commit,
                "generation": binding.generation,
                "enabled": binding.enabled,
                "label": binding.label,
                "loaded": actual["loaded"],
                "pid": str(actual["loaded_pid"])
                if actual["loaded_pid"] is not None
                else None,
                "plist_sha256": actual["sha256"],
            }

        def audit_owners():
            owners = {}
            for name in CONTINUOUS:
                binding = old.services[name]
                require(
                    binding.enabled and installed[name]["loaded"],
                    "COHORT_RESTORE_OWNER_UNPROVEN",
                )
                state = read_service_state(name, runtime_dir=self.directory)
                try:
                    fresh = (
                        bool(state)
                        and 0
                        <= (
                            self.now() - datetime.fromisoformat(state["at"])
                        ).total_seconds()
                        <= 30
                    )
                except (KeyError, ValueError, TypeError):
                    fresh = False
                require(
                    fresh
                    and state.get("schema_version") == 1
                    and state.get("service") == name
                    and state.get("phase") == "active"
                    and type(state.get("pid")) is int
                    and state["pid"] > 0
                    and state.get("generation") == binding.generation
                    and str(state["pid"]) == str(installed[name]["loaded_pid"])
                    and owner_process_matches(state, binding),
                    "COHORT_RESTORE_OWNER_UNPROVEN",
                )
                try:
                    os.kill(state["pid"], 0)
                except OSError:
                    raise CohortError("COHORT_RESTORE_OWNER_PID_UNPROVEN") from None
                require(
                    not owner_lock_available(name, runtime_dir=self.directory),
                    "COHORT_RESTORE_OWNER_LOCK_UNPROVEN",
                )
                request = _read(self.directory / f"{name}.handover.json")
                require(
                    request is None
                    or (
                        request.get("schema_version") == 1
                        and request.get("service") == name
                        and type(request.get("generation")) is int
                        and request.get("phase") in {"drain", "cancelled"}
                        and re.fullmatch(r"[0-9a-f]{32}", request.get("request_id", ""))
                        is not None
                        and (
                            request["generation"] != binding.generation
                            or request["phase"] == "cancelled"
                        )
                    ),
                    "COHORT_RESTORE_DRAIN_ACTIVE",
                )
                owners[name] = {
                    key: state.get(key)
                    for key in ("pid", "generation", "phase", "at", "ready")
                }
            return owners

        audit_owners()
        absent = []
        for name, binding in new.services.items():
            if binding.label != old.services[name].label:
                require(
                    self.definition_absent(binding), "COHORT_RESTORE_NEW_LABEL_PRESENT"
                )
                absent.append(binding.label)
        require(self.installed(old) == installed, "COHORT_RESTORE_READBACK_DRIFT")
        owners = audit_owners()
        for name, binding in new.services.items():
            if binding.label != old.services[name].label:
                require(
                    self.definition_absent(binding), "COHORT_RESTORE_NEW_LABEL_PRESENT"
                )
        require(
            self.bindings() == old
            and self.binding_hash() == plan["registry_sha256"]
            and self.protected(old) == protected,
            "COHORT_RESTORE_READBACK_DRIFT",
        )
        identity = {
            "registry_sha256": plan["registry_sha256"],
            "services": rows,
            "launcher_sha256": installed["launcher_sha256"],
            "protected_sha256": digest(protected),
            "new_labels_absent": sorted(absent),
        }
        return {
            "kind": "precommit_restore_readback",
            "observed_at": self.now().isoformat(),
            "identity_sha256": digest(identity),
            "identity": identity,
            "owners": owners,
        }
