"""Exact v1.15.3/gen16 fault boundary -> v1.15.4/gen17 staged recovery.

This deliberately does not use selective promotion or accept changed contracts
while old writers run. Old readiness is evidence, never a drain prerequisite.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from contextlib import ExitStack
import os
import json
from pathlib import Path

from app.runtime_bindings import BindingRegistry, SERVICES
from app.reference_trading.recovery_campaign import AttemptProgress, digest

CONTINUOUS = ("market-feed", "live", "alert", "reference-worker", "api", "web")
CALENDARS = ("after-market", "late-provider-recovery", "weekly-audit", "log-rotate")
OLD_COMMIT = "c28438d3d7ad6d6c66272027996f4a25e2facdfe"
ORDER = ("drain", "stop-install", "start", "resume-reference")


class FaultRecoveryError(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise FaultRecoveryError(code)


def registry(value):
    from app.runtime_bindings import ServiceBinding

    return BindingRegistry(
        1, {key: ServiceBinding(**item) for key, item in value["services"].items()}
    )


def freeze(
    backend, *, candidate_root, candidate_commit, projection_readback, projection_sha256
):
    old = backend.bindings()
    require(
        old is not None and set(old.services) == SERVICES,
        "FAULT_RECOVERY_TOPOLOGY_INVALID",
    )
    require(
        all(
            item.generation == 16
            and item.tag == "v1.15.3"
            and item.commit == OLD_COMMIT
            and item.enabled
            and item.launchd_label is None
            for item in old.services.values()
        ),
        "FAULT_RECOVERY_OLD_IDENTITY_INVALID",
    )
    old_roots = {item.root for item in old.services.values()}
    require(
        len(old_roots) == 1
        and Path(next(iter(old_roots))).name == "release-v1.15.3"
        and Path(candidate_root).name == "release-v1.15.4"
        and Path(candidate_root).parent == Path(next(iter(old_roots))).parent,
        "FAULT_RECOVERY_CANDIDATE_INVALID",
    )
    backend.verify_release(candidate_root, "v1.15.4", candidate_commit)
    for item in old.services.values():
        backend.verify_release(Path(item.root), item.tag, item.commit)
    contracts = backend.contracts(candidate_root)
    new = BindingRegistry(
        1,
        {
            name: replace(
                item,
                root=str(candidate_root),
                tag="v1.15.4",
                commit=candidate_commit,
                generation=17,
                contracts=contracts,
            )
            for name, item in old.services.items()
        },
    )
    plan = {
        "schema_version": 1,
        "kind": "exact_gen16_fault_to_gen17",
        "old": asdict(old),
        "new": asdict(new),
        "registry_sha256": backend.binding_hash(),
        "protected": backend.protected(old),
        "installed": backend.installed(old),
        "old_health": backend.old_health(old),
        "projection_readback": str(projection_readback),
        "projection_sha256": projection_sha256,
        "frozen_at": datetime.now(UTC).isoformat(),
    }
    # Unknown journals and failed owner bytes are copied as raw evidence in the
    # frozen plan; they are never rewritten into a success.
    plan["plan_hash"] = digest(plan)
    return plan


def validate(plan):
    require(
        plan.get("schema_version") == 1
        and plan.get("kind") == "exact_gen16_fault_to_gen17"
        and plan.get("plan_hash")
        == digest({key: value for key, value in plan.items() if key != "plan_hash"}),
        "FAULT_RECOVERY_PLAN_HASH_INVALID",
    )
    old, new = registry(plan["old"]), registry(plan["new"])
    require(
        set(old.services) == set(new.services) == SERVICES,
        "FAULT_RECOVERY_TOPOLOGY_INVALID",
    )
    require(
        all(
            item.generation == 16
            and item.commit == OLD_COMMIT
            and item.tag == "v1.15.3"
            for item in old.services.values()
        )
        and all(
            item.generation == 17 and item.tag == "v1.15.4"
            for item in new.services.values()
        ),
        "FAULT_RECOVERY_GENERATION_INVALID",
    )
    return old, new


class StageAttempt:
    """One directory per stage; an uncertain stage cannot be retried or skipped."""

    def __init__(self, root, plan):
        self.root, self.plan = Path(root), plan
        self.state_path = self.root / "state.json"

    def state(self):
        if not self.state_path.exists():
            return {
                "plan_hash": self.plan["plan_hash"],
                "completed": [],
                "effects": {},
                "phase": "prepared",
            }
        value = json.loads(self.state_path.read_bytes())
        require(
            value.get("plan_hash") == self.plan["plan_hash"],
            "FAULT_RECOVERY_ATTEMPT_PLAN_DRIFT",
        )
        return value

    def begin(self, phase):
        state = self.state()
        require(
            state["phase"] != "outcome_unknown",
            "FAULT_RECOVERY_OUTCOME_UNKNOWN_READBACK_REQUIRED",
        )
        require(
            len(state["completed"]) < len(ORDER)
            and ORDER[len(state["completed"])] == phase,
            "FAULT_RECOVERY_STAGE_ORDER_INVALID",
        )
        require(
            self.root.is_absolute()
            and not self.root.is_symlink()
            and self.root.parent.resolve() == self.root.parent,
            "FAULT_RECOVERY_ATTEMPT_UNSAFE",
        )
        if not self.root.exists():
            require(phase == "drain", "FAULT_RECOVERY_ATTEMPT_MISSING")
            self.root.mkdir(mode=0o700)
            fd = os.open(self.root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        progress = AttemptProgress(self.root / phase, plan_hash=self.plan["plan_hash"])
        return state, progress

    def persist(self, state):
        from app.runtime_handover import _write

        _write(self.state_path, state)


def run_stage(plan, phase, *, backend, attempt):
    old, new = validate(plan)
    with backend.deployment_guard():
        state, progress = attempt.begin(phase)
        effects = state["effects"]
        effects["controller_plan_hash"] = plan["plan_hash"]
        intent_written = False

        def mutate(name, action):
            nonlocal intent_written
            progress.record("intent", action=name)
            intent_written = True
            result = action()
            effects[name] = result
            state["phase"] = "in_progress"
            attempt.persist(state)
            progress.record("committed", action=name)
            return result

        try:
            backend.verify_release(
                Path(new.services["api"].root), "v1.15.4", new.services["api"].commit
            )
            backend.assert_protected(plan)
            require(
                backend.bindings()
                == (old if phase in ("drain", "stop-install") else new),
                "FAULT_RECOVERY_REGISTRY_DRIFT",
            )
            if phase == "drain":
                require(
                    backend.binding_hash() == plan["registry_sha256"],
                    "FAULT_RECOVERY_REGISTRY_DRIFT",
                )
                backend.assert_installed(old, plan["installed"])
                for name in CONTINUOUS:
                    request = mutate(
                        "drain:" + name,
                        lambda name=name: backend.request_drain(name, 16),
                    )
                    effects["request:" + name] = request
                # Failure/not-ready is preserved. Only a real parked lifecycle,
                # released kernel lock and verified Feed close authorize stop.
                proof = backend.await_parked(old, effects, seconds=30)
                backend.verify_feed_closed(old.services["market-feed"], proof)
                effects["parked_proof"] = proof
                attempt.persist(state)
            elif phase == "stop-install":
                effects["projection_readback"] = backend.verify_projection_restore(
                    plan, effects
                )
                attempt.persist(state)
                effects["fault_window"] = backend.fault_window(plan, effects)
                attempt.persist(state)
                with ExitStack() as held:
                    held.enter_context(backend.after_market_guard())
                    held.enter_context(backend.maintenance_guard())
                    held.enter_context(backend.owner_guards(old))
                    backend.assert_parked(old, effects)
                    backend.assert_installed(old, plan["installed"])
                    for name in (*CALENDARS, *CONTINUOUS):
                        backend.assert_idle_or_parked(old.services[name], effects)
                        mutate(
                            "stop:" + name,
                            lambda name=name: backend.stop(old.services[name]),
                        )
                    backend.assert_old_pids_exited(effects["parked_proof"])
                    mutate(
                        "retain-history", lambda: backend.retain_history(old, new, plan)
                    )
                    for name in sorted(SERVICES):
                        mutate(
                            "install:" + name,
                            lambda name=name: backend.install(
                                old.services[name], new.services[name], plan
                            ),
                        )
                    mutate("launcher", lambda: backend.install_launcher(new, plan))
                    # Ten authority records move in one registry CAS; none can
                    # keep an old input/reference fingerprint writer alive.
                    mutate(
                        "registry-cas",
                        lambda: backend.commit_bindings(new, plan["registry_sha256"]),
                    )
                    require(
                        backend.bindings() == new,
                        "FAULT_RECOVERY_REGISTRY_READBACK_FAILED",
                    )
                    backend.assert_new_installed(new)
            elif phase == "start":
                effects["fault_window"] = backend.fault_window(plan, effects)
                attempt.persist(state)
                require(
                    all("stop:" + name in effects for name in CONTINUOUS),
                    "FAULT_RECOVERY_OLD_STOP_UNPROVEN",
                )
                backend.assert_old_pids_exited(effects["parked_proof"])
                request = mutate(
                    "new-reference-drain",
                    lambda: backend.request_drain("reference-worker", 17),
                )
                effects["reference17_request"] = request
                # Consumers precede the sole publisher. Reference is deliberately
                # parked for its new-root exact bounded recovery CLI.
                for name in ("live", "alert", "reference-worker", "api", "web"):
                    mutate(
                        "start:" + name,
                        lambda name=name: backend.start(new.services[name]),
                    )
                backend.await_new_reference_parked(
                    new.services["reference-worker"], request
                )
                backend.verify_partial_started(new)
            else:
                effects["reference_recovery_readback"] = (
                    backend.verify_reference_recovery(new, effects)
                )
                attempt.persist(state)
                backend.assert_old_consumers_at_boundary(plan, new)
                request = effects["reference17_request"]
                mutate(
                    "resume-reference",
                    lambda: backend.cancel_reference_drain(
                        new.services["reference-worker"], request
                    ),
                )
                backend.await_reference_ready(new.services["reference-worker"])
                # NEW_DAY belongs solely to the unchanged feed path, after old
                # source/completed cursors reach their retained boundaries.
                mutate(
                    "start:market-feed",
                    lambda: backend.start(new.services["market-feed"]),
                )
                backend.await_full_ready(new)
                for name in CALENDARS:
                    mutate(
                        "calendar:" + name,
                        lambda name=name: backend.start_calendar(new.services[name]),
                    )
                    backend.verify_calendar(new.services[name])
                backend.assert_protected(plan)
            state["completed"].append(phase)
            state["phase"] = (
                "reference_recovery_pending" if phase == "start" else "stage_complete"
            )
            attempt.persist(state)
            progress.record("stage_complete", phase=phase)
            return state
        except Exception:
            state["phase"] = (
                "outcome_unknown" if intent_written else "precondition_blocked"
            )
            state["failed_stage"] = phase
            try:
                attempt.persist(state)
                progress.record(state["phase"] + "_no_retry", phase=phase)
                if intent_written and backend.bindings() == new:
                    progress.record("halt_new_writers_intent")
                    effects["halt_unknown"] = backend.halt_unknown(new)
                    attempt.persist(state)
                    progress.record("halt_new_writers_readback")
            finally:
                progress.close()
            raise
        finally:
            if state.get("failed_stage") != phase:
                progress.close()


def independent_readback(plan, *, backend, attempt):
    old, new = validate(plan)
    state = attempt.state()
    backend.assert_protected(plan)
    if state["phase"] == "outcome_unknown":
        return {
            "status": "OUTCOME_UNKNOWN_READBACK_ONLY",
            "failed_stage": state.get("failed_stage"),
            "known_prefix": state["effects"],
            "registry": asdict(backend.bindings()),
            "owners": backend.old_health(backend.bindings()),
        }
    require(state["completed"] == list(ORDER), "FAULT_RECOVERY_STAGES_PENDING")
    require(backend.bindings() == new, "FAULT_RECOVERY_REGISTRY_DRIFT")
    backend.assert_new_installed(new)
    backend.await_full_ready(new)
    for name in CALENDARS:
        backend.verify_calendar(new.services[name])
    return {
        "status": "GEN17_RUNTIME_READY",
        "natural_acceptance": "PENDING_NEW_COMPLETED_OBSERVATION",
        "retained_history": "NOT_A_NEW_NATURAL_RUN",
        "recipient_acceptance": "UNKNOWN",
    }
