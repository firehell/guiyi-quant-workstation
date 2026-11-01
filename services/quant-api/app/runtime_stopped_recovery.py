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


def historical_source(host, identity):
    if identity.get("kind") == recovery.ORIGINAL_FEED_SOURCE:
        source, _, current = recovery._original_verified_feed_source(
            host, identity["plan_path"], historical=True
        )
        require(current == identity)
        return source
    return recovery._historical_source(host, identity)


def current_source(host, path, identity):
    source, _, current = recovery._source(
        host, path, allow_original=identity.get("kind") == recovery.ORIGINAL_FEED_SOURCE
    )
    require(current == identity)
    return source


def failure_feed_state(plan, state):
    """Classify only completed startup effects; verification itself is read-only."""
    generation = plan["new"]["services"]["live"]["generation"]
    consumers = {"resumed_generation": generation}
    require(state.get("phase") == "outcome_unknown")
    effects = state.get("effects", {})
    if state.get("failed_stage") == "intake":
        require(
            effects == {"consumers": consumers}
            and state.get("error_code") == "COHORT_FORWARD_READY_TIMEOUT"
        )
        return "absent"
    label = (
        plan["new"]["services"]["market-feed"].get("launchd_label")
        or "com.guiyi.quant-market-feed"
    )
    require(
        state.get("failed_stage") == "verified"
        and state.get("error_type") == "CohortError"
        and state.get("error_code")
        in {
            "COHORT_FORWARD_READY_TIMEOUT",
            "COHORT_FORWARD_DEADLINE_EXCEEDED",
            "COHORT_FORWARD_PLAN_EXPIRED",
            "REFERENCE_RECEIVING_LIVENESS_UNPROVEN",
            "REFERENCE_RECEIVING_QUERY_INTERRUPTED",
        }
        and set(effects) == {"consumers", "intake", "feed"}
        and effects["consumers"] == consumers
        and recovery._valid_intake_result(effects["intake"])
        and effects["feed"] == {"bootstrapped": True, "label": label}
    )
    return "parked"


def valid_parked_feed_audit(audit, new):
    try:
        intent = audit["feed_close"]
        pids = intent["observed_pids"]
        return (
            audit["feed_state"] == "parked"
            and set(intent)
            == {
                "kind",
                "observed_pids",
                "binding_sha256",
                "owners_sha256",
                "controls_sha256",
                "frontiers_sha256",
            }
            and intent["kind"] == "parked_feed_close_intent_v1"
            and isinstance(pids, list)
            and 1 <= len(pids) <= 64
            and all(type(pid) is int and 1 < pid <= 2**31 - 1 for pid in pids)
            and pids == sorted(set(pids)) == audit["feed_observed_pids"]
            and intent["binding_sha256"] == digest(new["services"]["market-feed"])
            and intent["owners_sha256"] == digest(audit["owners"])
            and intent["controls_sha256"] == digest(audit["controls"])
            and intent["frontiers_sha256"] == audit["frontiers_sha256"]
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def valid_plan(plan):
    try:
        value = plan.get("stopped_confirmation")
        return (
            plan.get("mode") == MODE
            and "predecessor" not in plan
            and ("stop_after" not in plan or plan["stop_after"] == "feed_close")
            and isinstance(value, dict)
            and set(value) == {"path", "sha256"}
            and isinstance(value["path"], str)
            and Path(value["path"]).is_absolute()
            and isinstance(value["sha256"], str)
            and recovery.re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None
            and plan.get("audit", {}).get("stopped_confirmation") == value
            and (
                (
                    plan.get("stop_after") == "feed_close"
                    and "closed_feed" not in plan
                    and plan["audit"].get("feed_state") == "parked"
                    and plan["audit"].get("feed_close", {}).get("kind")
                    == "parked_feed_close_intent_v1"
                )
                or (
                    "stop_after" not in plan
                    and (
                        (
                            "closed_feed" not in plan
                            and plan["audit"].get("feed_state", "absent") == "absent"
                        )
                        or (
                            isinstance(plan.get("closed_feed"), dict)
                            and plan["audit"].get("feed_state") == "absent"
                            and plan["audit"].get("feed_close", {}).get("attempt")
                            == plan["closed_feed"]
                        )
                    )
                )
            )
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _inventory(host, allowed, *, own=None):
    parent = host.directory / "cohort-forward-recoveries"
    recovery._directory(parent)
    children = list(parent.iterdir())
    require(len(children) <= 1024)
    entries = []
    for child in children:
        recovery._directory(child)
        require(recovery.re.fullmatch(r"[0-9a-f]{64}", child.name) is not None)
        _, state = recovery._resolution_source(child / "state.json")
        entries.append((child, state))
    closed = recovery._closed_predecessors(host, entries)
    found = set()
    for child, _ in entries:
        require(child.name in allowed or child.name == own or child.name in closed)
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
    historical_source(host, value["source"])
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


def read_closed_feed(host, path, identity, selected):
    """Read one successful close-only receipt bound to this parked confirmation."""
    path = Path(path)
    raw, plan = recovery._resolution_source(path)
    recovery._validate(
        plan,
        datetime.fromisoformat(plan["created_at"]),
        historical=True,
        history_directory=host.directory,
    )
    require(
        valid_plan(plan)
        and plan.get("stop_after") == "feed_close"
        and plan.get("source") == identity
        and plan.get("stopped_confirmation") == selected
    )
    confirmation = read_confirmation(host, selected)
    require(
        confirmation["source"] == identity
        and confirmation["audit"].get("feed_state") == "parked"
        and plan["audit"]["feed_close"] == confirmation["audit"]["feed_close"]
        and plan["new"] == historical_source(host, identity)["new"]
    )
    controller = plan["audit"]["controller"]
    recovery._verify_historical_release(
        host, Path(controller["root"]), controller["tag"], controller["commit"]
    )
    folder = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"]
    recovery._directory(folder.parent)
    recovery._directory(folder)
    private_raw, private = recovery._resolution_source(folder / "plan.json")
    state_raw, state = recovery._resolution_source(folder / "state.json")
    receipt_raw, receipt = recovery._resolution_source(folder / "receipt.json")
    require(
        private == plan
        and state.get("schema_version") == receipt.get("schema_version") == 1
        and state.get("kind") == recovery.KIND
        and state.get("phase") == "feed_closed"
        and state.get("plan_sha256")
        == receipt.get("plan_sha256")
        == plan["plan_sha256"]
        and state.get("source") == receipt.get("source") == identity
        and state.get("receipt_sha256") == sha256(receipt_raw).hexdigest()
        and receipt.get("kind") == "feed_close_readback_v1"
        and receipt.get("original_attempt_preserved") is True
        and receipt.get("recovery_started") is False
        and set(state.get("effects", {})) == {"feed_stop"}
        and state["effects"]["feed_stop"] == receipt.get("feed_close")
        and recovery._valid_feed_close(
            receipt.get("feed_close"), plan["audit"]["feed_close"]
        )
    )
    return {
        "plan_path": str(path.resolve()),
        "plan_sha256": plan["plan_sha256"],
        "plan_bytes_sha256": sha256(raw).hexdigest(),
        "private_plan_bytes_sha256": sha256(private_raw).hexdigest(),
        "state_bytes_sha256": sha256(state_raw).hexdigest(),
        "receipt_bytes_sha256": sha256(receipt_raw).hexdigest(),
    }, receipt


def _validate_lineage(host, value):
    """Check every retained failure once; flat membership cannot bless an unknown."""
    identity = value["source"]
    members = set(value["attempts"])
    plans, states = {}, {}
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
        states[name] = state
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
        elif (
            mode == recovery.ORIGINAL_FEED_MODE
            and plan.get("stop_after") == "feed_close"
        ):
            recovery._original_feed_close_attempt(
                host, _public_path(value, plan), identity
            )
        elif mode == MODE and plan.get("stop_after") == "feed_close":
            read_closed_feed(
                host, _public_path(value, plan), identity, plan["stopped_confirmation"]
            )
        elif mode in {"confirmed_feed_halt", MODE, recovery.ORIGINAL_FEED_MODE}:
            failure_feed_state(plan, state)
            require(not os.path.lexists(folder / "receipt.json"))
            if mode == recovery.ORIGINAL_FEED_MODE:
                require(
                    "stop_after" not in plan
                    and state.get("error_type") == "CohortError"
                    and identity.get("kind") == recovery.ORIGINAL_FEED_SOURCE
                )
        else:
            require(False)
    failed = plans[value["failed_plan_sha256"]]
    require(
        value["audit"].get("feed_state", "absent")
        == failure_feed_state(failed, states[value["failed_plan_sha256"]])
    )
    if value["audit"].get("feed_state") == "parked":
        require(valid_parked_feed_audit(value["audit"], failed["new"]))
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
    elif failed.get("mode") == recovery.ORIGINAL_FEED_MODE:
        close, _ = recovery._original_feed_close_attempt(
            host, failed["original_close"]["plan_path"], identity
        )
        require(close == failed["original_close"])
        expected = {close["plan_sha256"], failed["plan_sha256"]}
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
        if "closed_feed" in failed:
            closed, _ = read_closed_feed(
                host, failed["closed_feed"]["plan_path"], identity, selected
            )
            require(closed == failed["closed_feed"])
            expected.add(closed["plan_sha256"])
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


def verify_pin(host, selected, *, own=None, closed_feed=None):
    value = read_confirmation(host, selected)
    allowed = set(value["attempts"])
    if closed_feed is not None:
        closure, _ = read_closed_feed(
            host, closed_feed["plan_path"], value["source"], selected
        )
        require(closure == closed_feed)
        allowed.add(closure["plan_sha256"])
    _inventory(host, allowed, own=own)
    return value


def _evidence(host, path):
    raw, plan = recovery._resolution_source(Path(path))
    recovery._validate(
        plan,
        datetime.fromisoformat(plan["created_at"]),
        historical=True,
        history_directory=host.directory,
    )
    identity = plan["source"]
    source = current_source(host, identity["plan_path"], identity)
    require(identity == plan["source"] and source["new"] == plan["new"])
    attempt = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"]
    recovery._directory(attempt.parent)
    recovery._directory(attempt)
    private_raw, private = recovery._resolution_source(attempt / "plan.json")
    state_raw, state = recovery._resolution_source(attempt / "state.json")
    require(
        private == plan
        and state.get("schema_version") == 1
        and state.get("kind") == recovery.KIND
        and state.get("plan_sha256") == plan["plan_sha256"]
        and state.get("source") == identity
        and not os.path.lexists(attempt / "receipt.json")
    )
    feed_state = failure_feed_state(plan, state)
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
    elif plan.get("mode") == recovery.ORIGINAL_FEED_MODE:
        require("stop_after" not in plan and state.get("error_type") == "CohortError")
        closure, receipt = recovery._original_feed_close_attempt(
            host, plan["original_close"]["plan_path"], identity
        )
        require(closure == plan["original_close"])
        retain_attempt(closure)
        pids = receipt["feed_close"]["observed_pids"]
    elif plan.get("mode") == MODE:
        previous = read_confirmation(host, plan["stopped_confirmation"])
        require(previous["source"] == identity)
        files.update(previous["files"])
        attempts.update(previous["attempts"])
        retain(Path(plan["stopped_confirmation"]["path"]))
        pids = previous["audit"].get(
            "feed_exited_pids", previous["audit"].get("feed_observed_pids")
        )
        if "closed_feed" in plan:
            closure, receipt = read_closed_feed(
                host,
                plan["closed_feed"]["plan_path"],
                identity,
                plan["stopped_confirmation"],
            )
            require(closure == plan["closed_feed"])
            retain_attempt(closure)
            pids = receipt["feed_close"]["observed_pids"]
    else:
        require(False)
    retain(Path(path))
    retain(attempt / "plan.json")
    retain(attempt / "state.json")
    attempts.add(plan["plan_sha256"])
    retain(Path(identity["plan_path"]))
    if identity.get("kind") == recovery.ORIGINAL_FEED_SOURCE:
        retain(
            host.directory / "cohort-attempts" / identity["plan_sha256"] / "plan.json"
        )
    retain(host.directory / "cohort-attempts" / identity["plan_sha256"] / "state.json")
    _inventory(host, attempts)
    require(pids and all(type(pid) is int and 1 < pid <= 2**31 - 1 for pid in pids))
    return (
        source,
        plan,
        files,
        sorted(attempts),
        sorted(set(pids)),
        feed_state == "parked",
    )


def observe_stopped(host, source, budget, *, feed_pids, feed_parked=False):
    """Verify current controls and fresh OS/data facts; never restore old controls."""
    from app.reference_trading.receiving_liveness import (
        receiving_context_identity,
        receiving_snapshot_identity,
    )

    intent = host.feed_close_intent(source, budget) if feed_parked else None
    owner_options = {"feed_parked": True} if feed_parked else {}
    with host._resume_owner_guards():
        fixed = host._fixed(source, budget)
        owners = host._parked_owners(source, held=True, **owner_options)
        controls = host._controls(source)
        require(
            all(
                host.definition_absent(recovery.registry(source["new"]).services[n])
                for n in recovery.CALENDARS
            )
        )
        if feed_parked:
            require(host._feed_pids(source) == intent["observed_pids"])
        else:
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
            owners == host._parked_owners(source, held=True, **owner_options)
            and controls == host._controls(source)
        )
        if feed_parked:
            require(
                host._feed_pids(source) == intent["observed_pids"]
                and digest(frontier) == intent["frontiers_sha256"]
                and digest(owners) == intent["owners_sha256"]
                and digest(controls) == intent["controls_sha256"]
            )
        else:
            require(host._feed_exited(source, feed_pids, budget))
        # Kernel locks above cover the current owners throughout the readback.
        require(
            owner_lock_available("market-feed", runtime_dir=host.directory) is False
        )
        budget()
        result = {
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
            "frontiers_sha256": digest(frontier),
        }
        if feed_parked:
            result.update(
                feed_state="parked",
                feed_close=intent,
                feed_observed_pids=intent["observed_pids"],
            )
            require(valid_parked_feed_audit(result, source["new"]))
        else:
            result["feed_exited_pids"] = feed_pids
        return result


def reconcile_stopped(host, path):
    with deployment_lock(runtime_dir=host.directory):
        source, failed, files, attempts, pids, feed_parked = _evidence(host, path)
        end = host.monotonic() + 120

        def budget():
            recovery.require(host.monotonic() < end, "COHORT_STOPPED_READBACK_TIMEOUT")

        with host.forward_guards(source):
            host._expected_new_protected = failed["audit"]["new_protected"]
            audit = host.audit_stopped(
                source,
                budget,
                feed_pids=pids,
                **({"feed_parked": True} if feed_parked else {}),
            )
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
            require((files, attempts, pids, feed_parked) == again[2:])
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


def audit_for_plan(host, source, selected, budget, *, closed_feed=None):
    value = verify_pin(host, selected, closed_feed=closed_feed)
    require(source["new"] == historical_source(host, value["source"])["new"])
    host._expected_new_protected = value["audit"]["new_protected"]
    parked = value["audit"].get("feed_state") == "parked"
    expected = dict(value["audit"])
    receipt = None
    if closed_feed is not None:
        require(parked)
        closure, receipt = read_closed_feed(
            host, closed_feed["plan_path"], value["source"], selected
        )
        require(closure == closed_feed)
        pids = receipt["feed_close"]["observed_pids"]
        expected.pop("feed_close")
        expected.pop("feed_observed_pids")
        expected["feed_state"] = "absent"
        expected["feed_exited_pids"] = pids
        expected["owners"] = {
            **expected["owners"],
            "market-feed": {
                "phase": "absent",
                "generation": source["new"]["services"]["market-feed"]["generation"],
            },
        }
    else:
        pids = (
            expected["feed_observed_pids"] if parked else expected["feed_exited_pids"]
        )
    current = host.audit_stopped(
        source,
        budget,
        feed_pids=pids,
        **({"feed_parked": True} if parked and closed_feed is None else {}),
    )
    if closed_feed is not None:
        current["feed_state"] = "absent"
    # Session phase may naturally change after reconciliation; freeze its fresh authority.
    require(
        {k: v for k, v in current.items() if k not in ("window", "controller")}
        == {k: v for k, v in expected.items() if k not in ("window", "controller")}
    )
    if closed_feed is not None:
        require(
            current["frontiers_sha256"] == receipt["feed_close"]["frontiers_sha256"]
        )
        current["feed_close"] = {
            "kind": "feed_close_readback_v1",
            "attempt": closed_feed,
            "proof": receipt["feed_close"],
        }
    return {**current, "stopped_confirmation": selected}


def freeze_stopped(
    host, source_path, confirmation, *, close_feed_only=False, feed_close_plan=None
):
    selected = descriptor(Path(confirmation))
    value = read_confirmation(host, selected)
    identity = value["source"]
    source = current_source(host, source_path, identity)
    require(value["source"] == identity)
    parked = value["audit"].get("feed_state") == "parked"
    require(
        (parked and (close_feed_only != (feed_close_plan is not None)))
        or (not parked and not close_feed_only and feed_close_plan is None)
    )
    closed_feed = (
        read_closed_feed(host, feed_close_plan, identity, selected)[0]
        if feed_close_plan is not None
        else None
    )
    verify_pin(host, selected, closed_feed=closed_feed)
    now = host.now()
    end = host.monotonic() + 600

    def budget():
        recovery.require(
            host.monotonic() < end and host.now() < now + timedelta(minutes=15),
            "COHORT_FORWARD_PLAN_EXPIRED",
        )

    audit = audit_for_plan(host, source, selected, budget, closed_feed=closed_feed)
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
    if close_feed_only:
        result["stop_after"] = "feed_close"
    if closed_feed is not None:
        result["closed_feed"] = closed_feed
    result["plan_sha256"] = digest(result)
    recovery._validate(result, host.now())
    return result
