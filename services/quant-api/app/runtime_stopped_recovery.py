"""Finite, immutable stopped frontiers for consumer-only same-generation failures.

Historical failures remain unknown. A confirmation certifies a current parked
frontier, not the outcome of any old command. Successor attempts carry a flat
set of retained evidence hashes rather than recursively selected predecessors.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import os
from pathlib import Path

from app import runtime_cohort_recovery as recovery
from app.runtime_handover import deployment_lock, owner_lock_available
from app.reference_trading.recovery_campaign import digest

KIND = "consumer_stopped_confirmation_v1"
MODE = "reconciled_stopped"
ERROR = "COHORT_STOPPED_FRONTIER_UNPROVEN"


def require(value):
    recovery.require(value, ERROR)


def descriptor(path):
    raw, _ = recovery._resolution_source(Path(path))
    return {"path": str(Path(path).resolve()), "sha256": sha256(raw).hexdigest()}


def valid_plan(plan):
    value = plan.get("stopped_confirmation")
    return (
        plan.get("mode") == MODE
        and "predecessor" not in plan
        and "stop_after" not in plan
        and isinstance(value, dict)
        and set(value) == {"path", "sha256"}
        and isinstance(value["path"], str)
        and Path(value["path"]).is_absolute()
        and isinstance(value["sha256"], str)
        and recovery.re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None
        and plan.get("audit", {}).get("stopped_confirmation") == value
    )


def _inventory(host, allowed, *, own=None):
    parent = host.directory / "cohort-forward-recoveries"
    recovery._directory(parent)
    children = list(parent.iterdir())
    require(len(children) <= 1024)
    found = set()
    for child in children:
        recovery._directory(child)
        require(recovery.re.fullmatch(r"[0-9a-f]{64}", child.name) is not None)
        require(child.name in allowed or child.name == own)
        found.add(child.name)
    require(set(allowed) <= found)


def read_confirmation(host, selected):
    require(isinstance(selected, dict) and set(selected) == {"path", "sha256"})
    path = Path(selected["path"])
    require(
        path.is_absolute()
        and path == path.resolve()
        and path.name == "stopped-confirmation.json"
        and path.parent.parent == host.directory / "cohort-forward-recoveries"
    )
    recovery._directory(path.parent)
    raw, value = recovery._resolution_source(path)
    require(sha256(raw).hexdigest() == selected["sha256"])
    require(
        set(value)
        == {
            "schema_version",
            "kind",
            "source",
            "failed_plan_sha256",
            "failed_plan_path",
            "attempts",
            "files",
            "audit",
            "controller",
            "confirmed_at",
        }
        and value["schema_version"] == 1
        and value["kind"] == KIND
        and path.parent.name == value["failed_plan_sha256"]
        and isinstance(value["attempts"], list)
        and 1 <= len(value["attempts"]) <= 1024
        and len(value["attempts"]) == len(set(value["attempts"]))
        and value["failed_plan_sha256"] in value["attempts"]
        and isinstance(value["files"], dict)
        and 1 <= len(value["files"]) <= 8192
    )
    recovery._historical_source(host, value["source"])
    for name, fingerprint in value["files"].items():
        data, _ = recovery._resolution_source(Path(name))
        require(sha256(data).hexdigest() == fingerprint)
    for name in value["attempts"]:
        require(recovery.re.fullmatch(r"[0-9a-f]{64}", name) is not None)
        for leaf in ("plan.json", "state.json"):
            require(
                str(host.directory / "cohort-forward-recoveries" / name / leaf)
                in value["files"]
            )
    _validate_lineage(host, value)
    controller = value["controller"]
    recovery._verify_historical_release(
        host, Path(controller["root"]), controller["tag"], controller["commit"]
    )
    return value


def _validate_lineage(host, value):
    """Check every retained failure once; flat membership cannot bless an unknown."""
    identity = value["source"]
    members = set(value["attempts"])
    plans = {}
    for name in members:
        folder = host.directory / "cohort-forward-recoveries" / name
        _, plan = recovery._resolution_source(folder / "plan.json")
        _, state = recovery._resolution_source(folder / "state.json")
        recovery._validate(
            plan,
            datetime.fromisoformat(plan["created_at"]),
            historical=True,
            history_directory=host.directory,
        )
        require(
            plan["source"] == identity
            and state.get("source") == identity
            and state.get("schema_version") == 1
            and state.get("kind") == recovery.KIND
            and plan["plan_sha256"] == state.get("plan_sha256") == name
        )
        controller = plan["audit"]["controller"]
        recovery._verify_historical_release(
            host, Path(controller["root"]), controller["tag"], controller["commit"]
        )
        plans[name] = plan
        mode = plan.get("mode")
        if mode is None:
            recovery._predecessor(
                host, _public_path(value, plan), identity, historical=True
            )
        elif mode == "confirmed_live_stop":
            recovery._intake_predecessor(host, _public_path(value, plan), identity)
        elif mode == "confirmed_intake_halt":
            recovery._feed_predecessor(host, _public_path(value, plan), identity)
        elif mode == "confirmed_feed_halt" and plan.get("stop_after") == "feed_close":
            recovery._feed_close_attempt(
                host, _public_path(value, plan), plan["predecessor"]
            )
        elif mode in {"confirmed_feed_halt", MODE}:
            generation = (
                recovery.registry(
                    plan["new"], historical=True, history_directory=host.directory
                )
                .services["live"]
                .generation
            )
            require(
                state.get("phase") == "outcome_unknown"
                and state.get("failed_stage") == "intake"
                and state.get("error_code") == "COHORT_FORWARD_READY_TIMEOUT"
                and state.get("effects")
                == {"consumers": {"resumed_generation": generation}}
                and not os.path.lexists(folder / "receipt.json")
            )
        else:
            require(False)
    failed = plans[value["failed_plan_sha256"]]
    public_raw, public = recovery._resolution_source(Path(value["failed_plan_path"]))
    require(
        public == failed
        and value["files"].get(value["failed_plan_path"])
        == sha256(public_raw).hexdigest()
    )
    if failed.get("mode") == "confirmed_feed_halt":
        predecessor, _ = recovery._feed_predecessor(
            host, failed["predecessor"]["plan_path"], identity
        )
        require(predecessor == failed["predecessor"])
        close, _ = recovery._feed_close_attempt(
            host, failed["audit"]["feed_close"]["attempt"]["plan_path"], predecessor
        )
        require(close == failed["audit"]["feed_close"]["attempt"])
        expected = {
            item["plan_sha256"]
            for item in recovery._permitted_predecessors(predecessor)
        }
        expected.update((close["plan_sha256"], failed["plan_sha256"]))
    elif failed.get("mode") == MODE:
        selected = failed["stopped_confirmation"]
        raw, parent = recovery._resolution_source(Path(selected["path"]))
        require(
            value["files"].get(selected["path"])
            == selected["sha256"]
            == sha256(raw).hexdigest()
            and parent.get("kind") == KIND
            and parent.get("source") == identity
            and failed["plan_sha256"] not in parent["attempts"]
            and all(
                value["files"].get(path) == fingerprint
                for path, fingerprint in parent["files"].items()
            )
        )
        expected = set(parent["attempts"]) | {failed["plan_sha256"]}
    else:
        require(False)
    require(expected == members)


def _public_path(value, plan):
    """Descriptors in descendants bind the public identity of each old member."""
    selected = plan["plan_sha256"]
    if selected == value["failed_plan_sha256"]:
        return value["failed_plan_path"]
    for name in value["files"]:
        if Path(name).name in {
            "state.json",
            "receipt.json",
            "feed-close-confirmation.json",
            "stopped-confirmation.json",
        }:
            continue
        _, candidate = recovery._resolution_source(Path(name))
        if candidate == plan and Path(name).name != "plan.json":
            return name
    # Public source files can themselves be named plan.json; require exact content.
    for name in value["files"]:
        _, candidate = recovery._resolution_source(Path(name))
        if candidate == plan:
            return name
    require(False)


def verify_pin(host, selected, *, own=None):
    value = read_confirmation(host, selected)
    _inventory(host, value["attempts"], own=own)
    return value


def _evidence(host, path):
    raw, plan = recovery._resolution_source(Path(path))
    recovery._validate(
        plan,
        datetime.fromisoformat(plan["created_at"]),
        historical=True,
        history_directory=host.directory,
    )
    source, _, identity = recovery._source(host, plan["source"]["plan_path"])
    require(identity == plan["source"] and source["new"] == plan["new"])
    attempt = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"]
    recovery._directory(attempt.parent)
    recovery._directory(attempt)
    private_raw, private = recovery._resolution_source(attempt / "plan.json")
    state_raw, state = recovery._resolution_source(attempt / "state.json")
    generation = recovery.registry(source["new"]).services["live"].generation
    require(
        private == plan
        and state.get("schema_version") == 1
        and state.get("kind") == recovery.KIND
        and state.get("phase") == "outcome_unknown"
        and state.get("failed_stage") == "intake"
        and state.get("error_code") == "COHORT_FORWARD_READY_TIMEOUT"
        and state.get("plan_sha256") == plan["plan_sha256"]
        and state.get("source") == identity
        and state.get("effects") == {"consumers": {"resumed_generation": generation}}
        and not os.path.lexists(attempt / "receipt.json")
    )
    controller = plan["audit"]["controller"]
    recovery._verify_historical_release(
        host, Path(controller["root"]), controller["tag"], controller["commit"]
    )
    files, attempts = {}, set()

    def retain(file):
        data, _ = recovery._resolution_source(file)
        files[str(file.resolve())] = sha256(data).hexdigest()

    def retain_attempt(item):
        public = Path(item["plan_path"])
        retain(public)
        folder = attempt.parent / item["plan_sha256"]
        recovery._directory(folder)
        for leaf in ("plan.json", "state.json"):
            retain(folder / leaf)
        for leaf in ("receipt.json", "feed-close-confirmation.json"):
            if os.path.lexists(folder / leaf):
                retain(folder / leaf)
        attempts.add(item["plan_sha256"])

    if plan.get("mode") == "confirmed_feed_halt" and "stop_after" not in plan:
        selected, _ = recovery._feed_predecessor(
            host, plan["predecessor"]["plan_path"], identity
        )
        require(selected == plan["predecessor"])
        closure, receipt = recovery._feed_close_attempt(
            host, plan["audit"]["feed_close"]["attempt"]["plan_path"], selected
        )
        require(closure == plan["audit"]["feed_close"]["attempt"])
        for item in recovery._permitted_predecessors(selected):
            retain_attempt(item)
        retain_attempt(closure)
        pids = receipt["feed_close"]["observed_pids"]
    elif plan.get("mode") == MODE:
        previous = read_confirmation(host, plan["stopped_confirmation"])
        require(previous["source"] == identity)
        files.update(previous["files"])
        attempts.update(previous["attempts"])
        retain(Path(plan["stopped_confirmation"]["path"]))
        pids = previous["audit"]["feed_exited_pids"]
    else:
        require(False)
    retain(Path(path))
    retain(attempt / "plan.json")
    retain(attempt / "state.json")
    attempts.add(plan["plan_sha256"])
    retain(Path(identity["plan_path"]))
    retain(host.directory / "cohort-attempts" / identity["plan_sha256"] / "state.json")
    _inventory(host, attempts)
    require(pids and all(type(pid) is int and 1 < pid <= 2**31 - 1 for pid in pids))
    return source, plan, files, sorted(attempts), sorted(set(pids))


def observe_stopped(host, source, budget, *, feed_pids):
    """Verify current controls and fresh OS/data facts; never restore old controls."""
    from app.reference_trading.receiving_liveness import (
        receiving_context_identity,
        receiving_snapshot_identity,
    )

    with host._resume_owner_guards():
        fixed = host._fixed(source, budget)
        owners = host._parked_owners(source, held=True)
        controls = host._controls(source)
        require(
            all(
                host.definition_absent(recovery.registry(source["new"]).services[n])
                for n in recovery.CALENDARS
            )
        )
        require(host._feed_exited(source, feed_pids, budget))
        require(host._calculation_boundary() is True)
        original = recovery._resolution_source(
            host.directory / "cohort-attempts" / source["plan_sha256"] / "state.json"
        )[1]
        from app.runtime_deployment import observation_progress, progress_reached

        for name in ("market-feed", "live", "alert"):
            require(
                progress_reached(
                    observation_progress(name),
                    original["effects"]["drain"]["progress"][name],
                    service=name,
                )
            )
        snapshot = host._snapshot(source, budget)
        require(
            snapshot["old_tail_reached"] is True
            and all(
                row["ack"] == row["current_tail"] == row["final_tail"]
                for row in snapshot["days"].values()
            )
        )
        frontier = host._feed_frontiers(source, budget)
        require(host._feed_frontiers(source, budget) == frontier)
        require(
            owners == host._parked_owners(source, held=True)
            and controls == host._controls(source)
        )
        require(host._feed_exited(source, feed_pids, budget))
        # Kernel locks above cover the current owners throughout the readback.
        require(
            owner_lock_available("market-feed", runtime_dir=host.directory) is False
        )
        budget()
        return {
            "registry_sha256": host.binding_hash(),
            "installed_sha256": digest(fixed),
            "old_exited_sha256": host._old_exited(source),
            "protected": source["protected"],
            "new_protected": host._new_protected,
            "owners": owners,
            "controls": controls,
            "receiving": receiving_snapshot_identity(snapshot),
            "receiving_context": receiving_context_identity(snapshot),
            "window": host.recovery_window(),
            "controller": host._controller(),
            "feed_exited_pids": feed_pids,
            "frontiers_sha256": digest(frontier),
        }


def reconcile_stopped(host, path):
    with deployment_lock(runtime_dir=host.directory):
        source, failed, files, attempts, pids = _evidence(host, path)
        end = host.monotonic() + 120

        def budget():
            recovery.require(host.monotonic() < end, "COHORT_STOPPED_READBACK_TIMEOUT")

        with host.forward_guards(source):
            host._expected_new_protected = failed["audit"]["new_protected"]
            audit = host.audit_stopped(source, budget, feed_pids=pids)
            require(
                all(
                    audit.get(key) == failed["audit"].get(key)
                    for key in (
                        "installed_sha256",
                        "protected",
                        "new_protected",
                        "receiving_context",
                    )
                )
            )
            budget()
            again = _evidence(host, path)
            require((files, attempts, pids) == again[2:])
            target = (
                host.directory
                / "cohort-forward-recoveries"
                / failed["plan_sha256"]
                / "stopped-confirmation.json"
            )
            if os.path.lexists(target):
                selected = descriptor(target)
                old = read_confirmation(host, selected)
                require(
                    old["files"] == files
                    and old["attempts"] == attempts
                    and old["audit"] == audit
                )
            else:
                value = {
                    "schema_version": 1,
                    "kind": KIND,
                    "source": failed["source"],
                    "failed_plan_path": str(Path(path).resolve()),
                    "failed_plan_sha256": failed["plan_sha256"],
                    "attempts": attempts,
                    "files": files,
                    "audit": audit,
                    "controller": host._controller(),
                    "confirmed_at": host.now().isoformat(),
                }
                fingerprint = recovery._exclusive_json(target, value)
                selected = {"path": str(target), "sha256": fingerprint}
                read_confirmation(host, selected)
            return {
                "status": "stopped_confirmed",
                "confirmation": selected,
                "original_attempt_preserved": True,
                "recovery_started": False,
            }


def audit_for_plan(host, source, selected, budget):
    value = verify_pin(host, selected)
    require(source["new"] == recovery._historical_source(host, value["source"])["new"])
    host._expected_new_protected = value["audit"]["new_protected"]
    current = host.audit_stopped(
        source, budget, feed_pids=value["audit"]["feed_exited_pids"]
    )
    # Session phase may naturally change after reconciliation; freeze its fresh authority.
    require(
        {k: v for k, v in current.items() if k not in ("window", "controller")}
        == {
            k: v for k, v in value["audit"].items() if k not in ("window", "controller")
        }
    )
    return {**current, "stopped_confirmation": selected}


def freeze_stopped(host, source_path, confirmation):
    source, _, identity = recovery._source(host, source_path)
    selected = descriptor(Path(confirmation))
    value = verify_pin(host, selected)
    require(value["source"] == identity)
    now = host.now()
    end = host.monotonic() + 600

    def budget():
        recovery.require(
            host.monotonic() < end and host.now() < now + timedelta(minutes=15),
            "COHORT_FORWARD_PLAN_EXPIRED",
        )

    audit = audit_for_plan(host, source, selected, budget)
    result = {
        "schema_version": 1,
        "kind": recovery.KIND,
        "source": identity,
        "new": source["new"],
        "audit": audit,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
        "downtime_seconds": 600,
        "mode": MODE,
        "stopped_confirmation": selected,
    }
    result["plan_sha256"] = digest(result)
    recovery._validate(result, host.now())
    return result
