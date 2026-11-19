"""Read-only admission for a recovery interrupted before any Feed intent."""

from datetime import datetime, timedelta
from hashlib import sha256
import os
from pathlib import Path

from app import runtime_cohort_recovery as recovery
from app.runtime_handover import deployment_lock


def require(condition):
    recovery.require(condition, "COHORT_FORWARD_INTAKE_CONTINUATION_UNPROVEN")


def evidence(host, path):
    path = Path(path)
    require(path.is_absolute() and path == path.resolve())
    public, plan = recovery._resolution_source(path)
    recovery._validate(
        plan, datetime.fromisoformat(plan["created_at"]),
        historical=True, history_directory=host.directory,
    )
    require(
        plan.get("mode") == "reconciled_stopped"
        and "intake_continuation" not in plan and "closed_feed" in plan
        and "stop_after" not in plan
    )
    folder = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"]
    recovery._directory(folder)
    private, _ = recovery._resolution_source(folder / "plan.json")
    raw, state = recovery._resolution_source(folder / "state.json")
    effects = state.get("effects", {})
    require(
        public == private and not os.path.lexists(folder / "receipt.json")
        and set(state) == {"schema_version", "kind", "phase", "plan_sha256", "source", "effects"}
        and state["schema_version"] == 1 and state["kind"] == recovery.KIND
        and state["phase"] == "intake_complete"
        and state["plan_sha256"] == plan["plan_sha256"] and state["source"] == plan["source"]
        and set(effects) == {"consumers", "intake"}
        and effects["consumers"] == {
            "resumed_generation": plan["new"]["services"]["market-feed"]["generation"]
        }
        and recovery._valid_intake_result(effects["intake"])
        and effects["intake"]["remaining_count"] == 0
        and effects["intake"]["old_tail_reached"] is True
    )
    controller = plan["audit"]["controller"]
    recovery._verify_historical_release(
        host, Path(controller["root"]), controller["tag"], controller["commit"]
    )
    return {
        "path": str(path), "plan_sha256": plan["plan_sha256"],
        "plan_bytes_sha256": sha256(public).hexdigest(),
        "state_bytes_sha256": sha256(raw).hexdigest(),
    }, plan, effects


def read_pin(host, plan):
    pin, previous, effects = evidence(host, plan["intake_continuation"]["path"])
    require(
        pin == plan["intake_continuation"]
        and all(plan[k] == previous[k] for k in (
            "source", "new", "stopped_confirmation", "closed_feed"
        ))
        and {k: v for k, v in plan["audit"].items() if k not in {"controller", "window", "active_consumers"}}
        == {k: v for k, v in previous["audit"].items() if k not in {"controller", "window"}}
    )
    return effects


def observe(host, source, audit, budget):
    new = recovery.registry(source["new"])
    host._expected_controller = audit["controller"]
    host._expected_new_protected = audit["new_protected"]
    require(recovery.digest(host._fixed(source, budget)) == audit["installed_sha256"])
    require(host._old_exited(source) == audit["old_exited_sha256"])
    closure = audit["feed_close"]["proof"]
    require(
        host._feed_exited(source, closure["observed_pids"], budget)
        and recovery.owner_lock_available("market-feed", runtime_dir=host.directory)
        and all(host.definition_absent(new.services[name]) for name in recovery.CALENDARS)
    )
    owners = {}
    for name in recovery.continuous_services(new):
        old = audit["controls"][name]
        current = recovery._read(host.directory / (name + ".handover.json"))
        if name == "market-feed":
            require(current == old)
            continue
        require(current == {**old, "phase": "cancelled"})
        state = host._active(new.services[name])
        require(state is not None)
        owners[name] = state["pid"]
        budget()
    host._calculation_boundary(active=True)
    host._check_receiving_context(source, audit, budget)
    intake = host.await_consumers(source, audit, budget)
    require(
        recovery._valid_intake_result(intake) and intake["remaining_count"] == 0
        and intake["old_tail_reached"] is True
    )
    for name, pid in owners.items():
        state = host._active(new.services[name])
        require(state is not None and state["pid"] == pid)
    budget()
    return owners


def freeze(host, path):
    from app.runtime_stopped_recovery import verify_pin

    with deployment_lock(runtime_dir=host.directory):
        pin, previous, _ = evidence(host, path)
        verify_pin(
            host, previous["stopped_confirmation"],
            closed_feed=previous["closed_feed"], predecessor=pin["plan_sha256"],
        )
        identity = previous["source"]
        source = recovery._source(
            host, identity["plan_path"],
            allow_original=identity.get("kind") == recovery.ORIGINAL_FEED_SOURCE,
        )
        require(source[2] == identity and source[0]["new"] == previous["new"])
        now = host.now()
        expires = now + recovery.STOPPED_RESUME_VALIDITY
        deadline = host.monotonic() + 360

        def budget():
            require(host.monotonic() < deadline and now <= host.now() < expires)

        with host.forward_guards(source[0]):
            audit = {
                **previous["audit"],
                "controller": host._controller(), "window": host.recovery_window(),
            }
            audit["active_consumers"] = observe(host, source[0], audit, budget)
            host.check_continuation_calendar_window(source[0], budget)
            require(evidence(host, path)[0] == pin)

        result = {k: v for k, v in previous.items() if k != "plan_sha256"}
        result.update(
            audit=audit, created_at=now.isoformat(), expires_at=expires.isoformat(),
            intake_continuation=pin,
        )
        result["plan_sha256"] = recovery.digest(result)
        recovery._validate(result, host.now())
        return result
