"""Explicit forward recovery of one already-committed cohort; never replay its CAS.

The consumed cohort's plan and attempt remain immutable. A separately frozen,
finite recovery attempt resumes only the exact installed new generation and
publishes its own receipt. Calculation failures remain independent of intake.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from time import monotonic

from app.runtime_cohort import (
    CohortError,
    registry,
    require,
    validate as validate_cohort,
    _resolution_source,
    _sync_resolution_directory,
)
from app.runtime_handover import _write, deployment_lock
from app.reference_trading.recovery_campaign import digest

from contextlib import ExitStack, contextmanager
import fcntl
from time import sleep
from app.runtime_cohort import CONTINUOUS, CALENDARS
from app.runtime_cohort_host import CohortHost, IDENTITY_NAMES
from app.runtime_handover import (
    _read,
    read_service_state,
    owner_lock_available,
    cancel_drain,
)
from app.runtime_deployment import (
    observation_progress,
    progress_reached,
    owner_process_matches,
    port_is_ready,
)

KIND = "postcas_forward_recovery_v1"

VERIFICATION_SUBSTEPS = frozenset(
    {
        "session_authority",
        "owner_readiness",
        "calculation_boundary",
        "receiving_snapshot",
        "receiving_continuity",
        "receiving_liveness",
        "fixed_identity",
        "deployment_identity",
        "api_http",
        "web_http",
        "post_step_guards",
        "budget",
    }
)
VERIFICATION_TIMES = (
    "observed_at",
    "before_sampled_at",
    "before_owner_cycle_at",
    "current_sampled_at",
    "current_owner_cycle_at",
)


def _safe_verification_diagnostic(host):
    value = getattr(host, "_forward_diagnostic", None)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("substep"), str)
        or value["substep"] not in VERIFICATION_SUBSTEPS
    ):
        return None
    result = {"substep": value["substep"]}
    for key in VERIFICATION_TIMES:
        raw = value.get(key)
        if not isinstance(raw, str) or len(raw) > 40:
            continue
        try:
            at = datetime.fromisoformat(raw)
            if at.tzinfo is not None and at.utcoffset() is not None:
                result[key] = at.isoformat()
        except ValueError:
            pass
    return result


def _verification_substep(host, name, *, before=None, current=None):
    diagnostic = {
        **(_safe_verification_diagnostic(host) or {}),
        "substep": name,
        "observed_at": host.now().isoformat(),
    }
    for prefix, sample in (("before", before), ("current", current)):
        if isinstance(sample, dict):
            for key in ("sampled_at", "owner_cycle_at"):
                diagnostic[prefix + "_" + key] = sample.get(key)
    host._forward_diagnostic = diagnostic


def prove_same_generation_startup(
    *, now, products, resolver, registered_day, subscriptions, dominant, sessions
):
    """Read the existing normal startup facts; never initialize day or subscriptions."""
    from app.market_data.market_phase import MarketPhase
    from app.market_data.domain import normalize_contract_for_symbol

    require(
        now.tzinfo is not None
        and products
        and len(set(products)) == len(products)
        and isinstance(subscriptions, dict)
        and set(subscriptions) == set(products),
        "COHORT_FORWARD_STARTUP_AUTHORITY_UNPROVEN",
    )
    phases, contracts = {}, {}
    closed_idle = True
    for product in products:
        phase = resolver.resolve(product, now)
        require(
            phase.symbol == product
            and phase.phase
            in {MarketPhase.TRADING, MarketPhase.BREAK, MarketPhase.CLOSED},
            "COHORT_FORWARD_SESSION_UNKNOWN",
        )
        if phase.phase is MarketPhase.TRADING:
            require(
                phase.trading_day == registered_day
                and phase.current_session is not None
                and phase.current_session.start <= now < phase.current_session.end,
                "COHORT_FORWARD_REGISTERED_DAY_DRIFT",
            )
        elif phase.phase is MarketPhase.BREAK:
            require(
                phase.trading_day == registered_day and phase.current_session is None,
                "COHORT_FORWARD_REGISTERED_DAY_DRIFT",
            )
        else:
            require(
                phase.current_session is None
                and (
                    phase.next_session_start is None or phase.next_session_start > now
                ),
                "COHORT_FORWARD_SESSION_UNKNOWN",
            )
            require(
                phase.trading_day == registered_day
                or resolver.completed_observation_trading_day(product, now)
                == registered_day,
                "COHORT_FORWARD_REGISTERED_DAY_DRIFT",
            )
        require(
            callable(sessions) and bool(sessions(product, registered_day)),
            "COHORT_FORWARD_SESSION_UNKNOWN",
        )
        contract = dominant(product, registered_day)
        require(
            isinstance(contract, str)
            and normalize_contract_for_symbol(product, contract) == contract
            and subscriptions[product] == contract,
            "COHORT_FORWARD_SUBSCRIPTION_DRIFT",
        )
        phases[product] = phase.phase.value
        contracts[product] = contract
        closed_idle = closed_idle and phase.phase is MarketPhase.CLOSED
    return {
        "mode": "same_generation_startup",
        "registered_trading_day": registered_day.isoformat(),
        "products": len(products),
        "phases": phases,
        "subscriptions_sha256": digest(contracts),
        "closed_idle": closed_idle,
        "natural_bar_verified": False,
    }


def compatible_live_restart_intent(current, frozen):
    try:
        keys = {
            "kind",
            "failure_code",
            "binding_sha256",
            "installed_sha256",
            "control_sha256",
            "observed_pids",
            "owned_pids",
            "minimum_runs",
        }
        return (
            set(current) == set(frozen) == keys
            and current["kind"] == frozen["kind"] == "draining_live_teardown_v1"
            and current["failure_code"]
            == frozen["failure_code"]
            == "COHORT_FORWARD_LIVE_DRAIN_RESTART_LOOP"
            and all(
                current[k] == frozen[k]
                for k in ("binding_sha256", "installed_sha256", "control_sha256")
            )
            and type(current["minimum_runs"]) is int
            and type(frozen["minimum_runs"]) is int
            and 2 <= frozen["minimum_runs"] <= current["minimum_runs"] <= 2**31 - 1
            and all(
                isinstance(v["observed_pids"], list)
                and 2 <= len(set(v["observed_pids"])) <= 64
                and v["observed_pids"] == sorted(set(v["observed_pids"]))
                and all(
                    type(pid) is int and 1 < pid <= 2**31 - 1
                    for pid in v["observed_pids"]
                )
                and isinstance(v["owned_pids"], list)
                and 2 <= len(set(v["owned_pids"])) <= 64
                and v["owned_pids"] == sorted(set(v["owned_pids"]))
                and set(v["owned_pids"]).issubset(v["observed_pids"])
                and all(
                    type(pid) is int and 1 < pid <= 2**31 - 1 for pid in v["owned_pids"]
                )
                for v in (current, frozen)
            )
        )
    except (KeyError, TypeError):
        return False


def valid_confirmed_live_stop(value, predecessor):
    """Exact bounded proof of this predecessor's completed Live teardown."""
    try:
        fields = {
            "predecessor_plan_sha256",
            "observed_pids",
            "live_absent",
            "observed_pids_exited",
            "owner_lock_available",
            "proof_sha256",
        }
        return (
            isinstance(value, dict)
            and set(value) == fields
            and value["predecessor_plan_sha256"] == predecessor["plan_sha256"]
            and isinstance(value["predecessor_plan_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", value["predecessor_plan_sha256"])
            is not None
            and isinstance(value["observed_pids"], list)
            and value["observed_pids"] == predecessor["observed_pids"]
            and 2 <= len(value["observed_pids"]) <= 64
            and value["observed_pids"] == sorted(set(value["observed_pids"]))
            and all(
                type(pid) is int and 1 < pid <= 2**31 - 1
                for pid in value["observed_pids"]
            )
            and all(
                value[key] is True
                for key in (
                    "live_absent",
                    "observed_pids_exited",
                    "owner_lock_available",
                )
            )
            and value["proof_sha256"]
            == digest({k: v for k, v in value.items() if k != "proof_sha256"})
        )
    except (KeyError, TypeError, ValueError):
        return False


def _predecessor(host, path, source_identity, *, historical=False):
    """Only the one immutable failed live-stop prefix; never an allow-unknown flag."""
    raw, frozen = _resolution_source(Path(path))
    _validate(
        frozen, datetime.fromisoformat(frozen["created_at"])
    )  # Identity audit, not replay.
    if historical:
        original, observed_identity = (
            _historical_source(host, source_identity),
            source_identity,
        )
    else:
        original, _state, observed_identity = _source(
            host, source_identity["plan_path"]
        )
    require(
        frozen.get("mode") is None
        and frozen["source"] == source_identity == observed_identity
        and frozen["new"] == original["new"],
        "COHORT_FORWARD_PREDECESSOR_INVALID",
    )
    attempt = host.directory / "cohort-forward-recoveries" / frozen["plan_sha256"]
    _directory(attempt.parent)
    _directory(attempt)
    private_raw, private = _resolution_source(attempt / "plan.json")
    state_raw, state = _resolution_source(attempt / "state.json")
    require(
        private == frozen
        and state.get("schema_version") == 1
        and state.get("kind") == KIND
        and state.get("plan_sha256") == frozen["plan_sha256"]
        and state.get("source") == frozen["source"]
        and state.get("phase") == "outcome_unknown"
        and set(state.get("effects", {})) == {"live_stop"},
        "COHORT_FORWARD_PREDECESSOR_INVALID",
    )
    effect = state["effects"]["live_stop"]
    intent = frozen["audit"].get("live_restart_intent")
    require(
        isinstance(effect, dict)
        and set(effect) == {"phase", "observed_pids", "intent"}
        and effect["phase"] in {"bootout_requested", "bootout_waiting"}
        and effect["intent"] == intent
        and compatible_live_restart_intent(intent, intent)
        and intent["binding_sha256"]
        == digest(asdict(registry(original["new"]).services["live"]))
        and isinstance(effect["observed_pids"], list)
        and 2 <= len(effect["observed_pids"]) <= 64
        and all(
            type(pid) is int and 1 < pid <= 2**31 - 1 for pid in effect["observed_pids"]
        )
        and effect["observed_pids"] == sorted(set(effect["observed_pids"]))
        and set(intent["observed_pids"]).issubset(effect["observed_pids"])
        and not os.path.lexists(attempt / "receipt.json"),
        "COHORT_FORWARD_PREDECESSOR_INVALID",
    )
    controller = frozen["audit"]["controller"]
    host.verify_release(
        Path(controller["root"]), controller["tag"], controller["commit"]
    )
    return {
        "plan_path": str(Path(path).resolve()),
        "plan_sha256": frozen["plan_sha256"],
        "plan_bytes_sha256": sha256(raw).hexdigest(),
        "private_plan_bytes_sha256": sha256(private_raw).hexdigest(),
        "state_bytes_sha256": sha256(state_raw).hexdigest(),
        "live_stop_sha256": digest(effect),
        "observed_pids": effect["observed_pids"],
    }, frozen


def _historical_source(host, identity):
    """Validate retained source bytes without relying on the mutable result pointer."""
    raw, source = _resolution_source(Path(identity["plan_path"]))
    validate_cohort(source, datetime.fromisoformat(source["created_at"]))
    attempt = host.directory / "cohort-attempts" / source["plan_sha256"]
    _directory(attempt.parent)
    _directory(attempt)
    state_raw, state = _resolution_source(attempt / "state.json")
    require(
        sha256(raw).hexdigest() == identity["plan_bytes_sha256"]
        and sha256(state_raw).hexdigest()
        == identity["attempt_bytes_sha256"]
        == identity["global_bytes_sha256"]
        and source["plan_sha256"] == identity["plan_sha256"]
        and state.get("schema_version") == 1
        and state.get("phase") == "outcome_unknown"
        and state.get("plan_sha256") == source["plan_sha256"]
        and {"drain", "install", "consumers"} <= set(state.get("effects", {}))
        and not {"feed", "verified", "calendars_on"} & set(state["effects"]),
        "COHORT_FORWARD_PREDECESSOR_INVALID",
    )
    return source


def _intake_predecessor(host, path, identity):
    """Exactly A live-stop -> B consumers/intake halt; no recursive retry chain."""
    raw, frozen = _resolution_source(Path(path))
    _validate(frozen, datetime.fromisoformat(frozen["created_at"]))
    source = _historical_source(host, identity)
    require(
        frozen.get("mode") == "confirmed_live_stop"
        and frozen["source"] == identity
        and frozen["new"] == source["new"]
        and frozen["audit"]["protected"] == source["protected"],
        "COHORT_FORWARD_PREDECESSOR_INVALID",
    )
    ancestor, previous = _predecessor(
        host, frozen["predecessor"]["plan_path"], identity, historical=True
    )
    require(
        ancestor == frozen["predecessor"]
        and frozen["audit"]["new_protected"] == previous["audit"]["new_protected"],
        "COHORT_FORWARD_PREDECESSOR_DRIFT",
    )
    attempt = host.directory / "cohort-forward-recoveries" / frozen["plan_sha256"]
    _directory(attempt.parent)
    _directory(attempt)
    private_raw, private = _resolution_source(attempt / "plan.json")
    state_raw, state = _resolution_source(attempt / "state.json")
    generation = registry(source["new"]).services["live"].generation
    require(
        private == frozen
        and state.get("schema_version") == 1
        and state.get("kind") == KIND
        and state.get("plan_sha256") == frozen["plan_sha256"]
        and state.get("source") == identity
        and state.get("phase") == "outcome_unknown"
        and state.get("failed_stage") == "intake"
        and state.get("effects") == {"consumers": {"resumed_generation": generation}}
        and not os.path.lexists(attempt / "receipt.json"),
        "COHORT_FORWARD_PREDECESSOR_INVALID",
    )
    controller = frozen["audit"]["controller"]
    host.verify_release(
        Path(controller["root"]), controller["tag"], controller["commit"]
    )
    return {
        "plan_path": str(Path(path).resolve()),
        "plan_sha256": frozen["plan_sha256"],
        "plan_bytes_sha256": sha256(raw).hexdigest(),
        "private_plan_bytes_sha256": sha256(private_raw).hexdigest(),
        "state_bytes_sha256": sha256(state_raw).hexdigest(),
        "effects_sha256": digest(state["effects"]),
        "ancestor": ancestor,
    }, frozen


def valid_confirmed_intake_halt(value, predecessor, audit):
    try:
        fields = {
            "predecessor_plan_sha256",
            "owners_sha256",
            "controls_sha256",
            "receiving_context",
            "all_consumers_parked",
            "feed_absent",
            "current_tail_reached",
            "proof_sha256",
        }
        return (
            isinstance(value, dict)
            and set(value) == fields
            and isinstance(predecessor, dict)
            and "ancestor" in predecessor
            and value["predecessor_plan_sha256"] == predecessor["plan_sha256"]
            and value["owners_sha256"] == digest(audit["owners"])
            and value["controls_sha256"] == digest(audit["controls"])
            and value["receiving_context"] == audit["receiving_context"]
            and re.fullmatch(r"[0-9a-f]{64}", value["receiving_context"]) is not None
            and all(
                value[key] is True
                for key in (
                    "all_consumers_parked",
                    "feed_absent",
                    "current_tail_reached",
                )
            )
            and value["proof_sha256"]
            == digest({k: v for k, v in value.items() if k != "proof_sha256"})
        )
    except (KeyError, TypeError, ValueError):
        return False


def _load_selected_predecessor(host, path, identity):
    _raw, plan = _resolution_source(Path(path))
    return (
        _intake_predecessor(host, path, identity)
        if plan.get("mode") == "confirmed_live_stop"
        else _predecessor(host, path, identity)
    )


def _closed_predecessors(host, entries):
    closed = set()
    for child, state in entries:
        if state.get("phase") != "recovered" or not state.get("receipt_sha256"):
            continue
        raw, receipt = _resolution_source(child / "receipt.json")
        require(
            sha256(raw).hexdigest() == state["receipt_sha256"],
            "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
        )
        resolution = receipt.get("predecessor_resolution")
        if resolution is None:
            continue
        _raw, plan = _resolution_source(child / "plan.json")
        predecessor = resolution.get("predecessor")
        if plan.get("mode") == "confirmed_intake_halt":
            _validate(plan, datetime.fromisoformat(plan["created_at"]))
            require(
                isinstance(predecessor, dict)
                and plan.get("predecessor") == predecessor
                and resolution.get("kind") == "confirmed_intake_halt_resolution_v1"
                and resolution.get("successor_plan_sha256")
                == child.name
                == plan.get("plan_sha256")
                == receipt.get("plan_sha256")
                == state.get("plan_sha256")
                and receipt.get("source") == state.get("source") == plan.get("source")
                and resolution.get("confirmation")
                == plan["audit"].get("confirmed_intake_halt")
                and valid_confirmed_intake_halt(
                    resolution.get("confirmation"), predecessor, plan["audit"]
                ),
                "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
            )
            selected, _before = _intake_predecessor(
                host, predecessor["plan_path"], plan["source"]
            )
            require(
                selected == predecessor, "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED"
            )
            closed.update(
                (selected["plan_sha256"], selected["ancestor"]["plan_sha256"])
            )
            continue
        require(
            isinstance(predecessor, dict)
            and plan.get("mode") == "confirmed_live_stop"
            and plan.get("predecessor") == predecessor
            and resolution.get("kind") == "confirmed_live_stop_resolution_v1"
            and resolution.get("successor_plan_sha256")
            == child.name
            == plan.get("plan_sha256")
            == receipt.get("plan_sha256")
            == state.get("plan_sha256")
            and plan["plan_sha256"]
            == digest({k: v for k, v in plan.items() if k != "plan_sha256"})
            and receipt.get("source") == state.get("source") == plan.get("source")
            and resolution.get("confirmation")
            == plan["audit"].get("confirmed_live_stop")
            and valid_confirmed_live_stop(resolution.get("confirmation"), predecessor),
            "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
        )
        name = predecessor.get("plan_sha256")
        require(
            isinstance(name, str) and re.fullmatch(r"[0-9a-f]{64}", name),
            "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
        )
        previous = host.directory / "cohort-forward-recoveries" / name
        _directory(previous)
        previous_plan_raw, previous_plan = _resolution_source(previous / "plan.json")
        previous_state_raw, previous_state = _resolution_source(previous / "state.json")
        require(
            sha256(previous_plan_raw).hexdigest()
            == predecessor["private_plan_bytes_sha256"]
            and sha256(previous_state_raw).hexdigest()
            == predecessor["state_bytes_sha256"]
            and previous_plan.get("plan_sha256")
            == name
            == previous_state.get("plan_sha256")
            and previous_state.get("phase") == "outcome_unknown"
            and previous_plan.get("source") == plan["source"]
            and digest(previous_state["effects"]["live_stop"])
            == predecessor["live_stop_sha256"],
            "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
        )
        closed.add(name)
    return closed


def _no_unresolved_recovery(host, predecessor=None):
    parent = host.directory / "cohort-forward-recoveries"
    if not parent.exists():
        require(not parent.is_symlink(), "COHORT_FORWARD_DIRECTORY_UNSAFE")
        return
    _directory(parent)
    children = list(parent.iterdir())
    require(len(children) <= 1024, "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED")
    entries = []
    for child in children:
        _directory(child)
        require(
            re.fullmatch(r"[0-9a-f]{64}", child.name), "COHORT_FORWARD_DIRECTORY_UNSAFE"
        )
        _raw, state = _resolution_source(child / "state.json")
        entries.append((child, state))
    closed = _closed_predecessors(host, entries)
    for child, state in entries:
        permitted = [] if predecessor is None else [predecessor]
        if predecessor is not None and "ancestor" in predecessor:
            permitted.append(predecessor["ancestor"])
        selected = next(
            (item for item in permitted if child.name == item["plan_sha256"]), None
        )
        allowed = selected is not None
        if allowed:
            raw, _state = _resolution_source(child / "state.json")
            require(
                sha256(raw).hexdigest() == selected["state_bytes_sha256"],
                "COHORT_FORWARD_PREDECESSOR_DRIFT",
            )
        require(
            state.get("phase") == "recovered" or child.name in closed or allowed,
            "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
        )


def _directory(path):
    info = path.lstat()
    require(
        path.resolve() == path
        and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        "COHORT_FORWARD_DIRECTORY_UNSAFE",
    )


def _source(host, path):
    path = Path(path)
    raw, plan = _resolution_source(path)
    try:
        created = datetime.fromisoformat(plan["created_at"])
        require(created <= host.now(), "COHORT_FORWARD_SOURCE_INVALID")
        _old, new = validate_cohort(plan, created)  # Historical identity audit only.
        require(host.bindings() == new, "COHORT_FORWARD_REGISTRY_DRIFT")
        attempt = host.directory / "cohort-attempts" / plan["plan_sha256"]
        for directory in (attempt.parent, attempt):
            _directory(directory)
        global_raw, global_state = _resolution_source(
            host.directory / "cohort-release.json"
        )
        attempt_raw, state = _resolution_source(attempt / "state.json")
        require(
            global_state == state
            and state.get("schema_version") == 1
            and state.get("phase") == "outcome_unknown"
            and state.get("plan_sha256") == plan["plan_sha256"]
            and isinstance(state.get("effects"), dict)
            and {"drain", "install", "consumers"} <= set(state["effects"])
            and not {"feed", "verified", "calendars_on"} & set(state["effects"]),
            "COHORT_FORWARD_SOURCE_INVALID",
        )
        identity = {
            "plan_path": str(path.resolve()),
            "plan_sha256": plan["plan_sha256"],
            "plan_bytes_sha256": sha256(raw).hexdigest(),
            "attempt_bytes_sha256": sha256(attempt_raw).hexdigest(),
            "global_bytes_sha256": sha256(global_raw).hexdigest(),
        }
        return plan, state, identity
    except (KeyError, TypeError, OverflowError):
        raise CohortError("COHORT_FORWARD_SOURCE_INVALID") from None


def _validate(plan, now):
    try:
        require(
            set(plan) - {"mode", "predecessor"}
            == {
                "schema_version",
                "kind",
                "source",
                "new",
                "audit",
                "created_at",
                "expires_at",
                "downtime_seconds",
                "plan_sha256",
            }
            and type(plan["schema_version"]) is int
            and plan["schema_version"] == 1
            and plan["kind"] == KIND
            and plan["downtime_seconds"] == 600
            and plan["plan_sha256"]
            == digest({k: v for k, v in plan.items() if k != "plan_sha256"}),
            "COHORT_FORWARD_PLAN_INVALID",
        )
        created, expires = (
            datetime.fromisoformat(plan["created_at"]),
            datetime.fromisoformat(plan["expires_at"]),
        )
        require(
            expires - created == timedelta(minutes=15), "COHORT_FORWARD_PLAN_INVALID"
        )
        require(created <= now < expires, "COHORT_FORWARD_PLAN_EXPIRED")
        require(
            ("mode" not in plan and "predecessor" not in plan)
            or (
                plan.get("mode") == "confirmed_live_stop"
                and isinstance(plan.get("predecessor"), dict)
                and "live_restart_intent" not in plan["audit"]
                and valid_confirmed_live_stop(
                    plan["audit"].get("confirmed_live_stop"), plan["predecessor"]
                )
            )
            or (
                plan.get("mode") == "confirmed_intake_halt"
                and "live_restart_intent" not in plan["audit"]
                and valid_confirmed_intake_halt(
                    plan["audit"].get("confirmed_intake_halt"),
                    plan.get("predecessor"),
                    plan["audit"],
                )
            ),
            "COHORT_FORWARD_PLAN_INVALID",
        )
        registry(plan["new"])
    except (TypeError, KeyError, OverflowError):
        raise CohortError("COHORT_FORWARD_PLAN_INVALID") from None


def freeze_forward_recovery(host, source_plan_path, *, predecessor_recovery_plan=None):
    """Read-only new intent; the historical plan's elapsed budget is never reused."""
    source, _state, identity = _source(host, source_plan_path)
    predecessor = (
        _load_selected_predecessor(host, predecessor_recovery_plan, identity)[0]
        if predecessor_recovery_plan is not None
        else None
    )
    _no_unresolved_recovery(host, predecessor)
    now = host.now()
    end = getattr(host, "monotonic", monotonic)() + 600

    def budget():
        require(
            getattr(host, "monotonic", monotonic)() < end,
            "COHORT_FORWARD_DEADLINE_EXCEEDED",
        )
        require(
            now <= host.now() < now + timedelta(minutes=15),
            "COHORT_FORWARD_PLAN_EXPIRED",
        )

    audit = host.audit_forward(source, budget, predecessor=predecessor)
    budget()
    require(
        _source(host, source_plan_path)[2] == identity, "COHORT_FORWARD_SOURCE_DRIFT"
    )
    result = {
        "schema_version": 1,
        "kind": KIND,
        "source": identity,
        "new": source["new"],
        "audit": audit,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
        "downtime_seconds": 600,
    }
    if predecessor is not None:
        require(
            _load_selected_predecessor(host, predecessor["plan_path"], identity)[0]
            == predecessor,
            "COHORT_FORWARD_PREDECESSOR_DRIFT",
        )
        result.update(
            mode="confirmed_intake_halt"
            if "ancestor" in predecessor
            else "confirmed_live_stop",
            predecessor=predecessor,
        )
    result["plan_sha256"] = digest(result)
    _validate(result, host.now())
    return result


def _exclusive_json(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_resolution_directory(path.parent)
    require(_resolution_source(path)[0] == raw, "COHORT_FORWARD_RECEIPT_WRITE_UNKNOWN")
    return sha256(raw).hexdigest()


def apply_forward_recovery(host, recovery_plan_path):
    """Resume exact new owners; no install, CAS, protocol change or old restoration."""
    _raw, plan = _resolution_source(Path(recovery_plan_path))
    _validate(plan, host.now())
    with deployment_lock(runtime_dir=host.directory):
        prior_attempt = (
            host.directory / "cohort-forward-recoveries" / plan["plan_sha256"]
        )
        require(
            not os.path.lexists(prior_attempt), "COHORT_FORWARD_ATTEMPT_ALREADY_EXISTS"
        )
        source, _state, identity = _source(host, plan["source"]["plan_path"])
        predecessor = None
        if plan.get("mode") in {"confirmed_live_stop", "confirmed_intake_halt"}:
            predecessor = _load_selected_predecessor(
                host, plan["predecessor"]["plan_path"], identity
            )[0]
            require(
                predecessor == plan["predecessor"], "COHORT_FORWARD_PREDECESSOR_DRIFT"
            )
        _no_unresolved_recovery(host, predecessor)
        require(identity == plan["source"], "COHORT_FORWARD_SOURCE_DRIFT")
        require(source["new"] == plan["new"], "COHORT_FORWARD_REGISTRY_DRIFT")
        deadline = getattr(host, "monotonic", monotonic)() + 600

        def budget():
            _validate(plan, host.now())
            require(
                getattr(host, "monotonic", monotonic)() < deadline,
                "COHORT_FORWARD_DEADLINE_EXCEEDED",
            )

        def unchanged():
            require(
                host._controller() == plan["audit"]["controller"],
                "COHORT_FORWARD_CONTROLLER_DRIFT",
            )
            require(
                _source(host, plan["source"]["plan_path"])[2] == identity,
                "COHORT_FORWARD_SOURCE_DRIFT",
            )
            if predecessor is not None:
                require(
                    _load_selected_predecessor(
                        host, predecessor["plan_path"], identity
                    )[0]
                    == predecessor,
                    "COHORT_FORWARD_PREDECESSOR_DRIFT",
                )
            host.check_protected_forward(source, plan["audit"])
            budget()

        with host.forward_guards(source):
            audit = host.audit_forward(
                source, budget, expected=plan["audit"], predecessor=predecessor
            )
            budget()
            require(audit == plan["audit"], "COHORT_FORWARD_AUDIT_DRIFT")
            unchanged()
        parent = host.directory / "cohort-forward-recoveries"
        require(not parent.is_symlink(), "COHORT_FORWARD_DIRECTORY_UNSAFE")
        parent.mkdir(mode=0o700, exist_ok=True)
        _directory(parent)
        attempt = parent / plan["plan_sha256"]
        try:
            attempt.mkdir(mode=0o700)
        except FileExistsError:
            raise CohortError("COHORT_FORWARD_ATTEMPT_ALREADY_EXISTS") from None
        _directory(attempt)
        _sync_resolution_directory(parent)
        _exclusive_json(attempt / "plan.json", plan)
        journal = {
            "schema_version": 1,
            "kind": KIND,
            "plan_sha256": plan["plan_sha256"],
            "source": identity,
            "phase": "claimed",
            "effects": {},
        }
        mutated = False

        def persist(phase):
            journal["phase"] = phase
            _write(attempt / "state.json", journal)

        persist("claimed")
        try:

            def step(name, action):
                nonlocal mutated
                unchanged()
                persist(name)
                if name == "verified":
                    host._forward_diagnostic = None
                mutated = (
                    True  # An uncertain command return is never permission to retry.
                )
                result = action()
                if name == "verified":
                    _verification_substep(host, "post_step_guards")
                unchanged()
                journal["effects"][name] = result
                persist(name + "_complete")
                return result

            if predecessor is None and "live_restart_intent" in plan["audit"]:

                def record_stop(value):
                    journal["effects"]["live_stop"] = value
                    persist("live_stop_intent")

                step(
                    "live_stop",
                    lambda: host.stop_draining_live(
                        source, plan["audit"], budget, record_stop
                    ),
                )
            step(
                "consumers",
                lambda: host.resume_consumers(source, plan["audit"], budget),
            )
            intake = step(
                "intake", lambda: host.await_consumers(source, plan["audit"], budget)
            )
            step("feed", lambda: host.resume_feed(source, plan["audit"], budget))
            readback = step(
                "verified", lambda: host.verify_forward(source, plan["audit"], budget)
            )
            step("calendars", lambda: host.forward_calendars(source, budget))
            unchanged()
            receipt = {
                "schema_version": 1,
                "kind": "postcas_forward_recovery_readback",
                "plan_sha256": plan["plan_sha256"],
                "source": identity,
                "observed_at": host.now().isoformat(),
                "intake": intake,
                "readback": readback,
                "natural_acceptance": "pending",
                "original_attempt_preserved": True,
            }
            if predecessor is not None:
                receipt["predecessor_resolution"] = {
                    "kind": "confirmed_intake_halt_resolution_v1"
                    if "ancestor" in predecessor
                    else "confirmed_live_stop_resolution_v1",
                    "predecessor": predecessor,
                    "successor_plan_sha256": plan["plan_sha256"],
                    "confirmation": plan["audit"][
                        "confirmed_intake_halt"
                        if "ancestor" in predecessor
                        else "confirmed_live_stop"
                    ],
                }
            receipt_sha = _exclusive_json(attempt / "receipt.json", receipt)
            journal["receipt_sha256"] = receipt_sha
            persist("recovered")
            unchanged()
            # This is a new recovery result. The original attempt is never rewritten.
            result = {
                "schema_version": 1,
                "kind": "postcas_forward_recovery_result",
                "phase": "switched",
                "source_phase": "outcome_unknown",
                "plan_sha256": plan["plan_sha256"],
                "source_plan_sha256": identity["plan_sha256"],
                "receipt_sha256": receipt_sha,
                "original_attempt_preserved": True,
            }
            if predecessor is not None:
                result["predecessor_resolution"] = {
                    "predecessor_plan_sha256": predecessor["plan_sha256"],
                    "receipt_sha256": receipt_sha,
                }
            target = host.directory / "cohort-release.json"
            try:
                _write(target, result)
            except OSError:
                require(
                    _resolution_source(target)[1] == result,
                    "COHORT_FORWARD_POINTER_WRITE_UNKNOWN",
                )
            require(
                _resolution_source(target)[1] == result,
                "COHORT_FORWARD_POINTER_WRITE_UNKNOWN",
            )
            return {
                "status": "recovered",
                "receipt_sha256": receipt_sha,
                "original_attempt_preserved": True,
                "natural_acceptance": "pending",
            }
        except Exception as error:
            from app.runtime_fault_recovery import FaultRecoveryError
            from app.runtime_identity import RuntimeIdentityError
            from app.runtime_deployment import DeploymentError
            from app.reference_trading.receiving_liveness import ReceivingLivenessError

            # Only our typed boundary errors carry public codes. Arbitrary
            # exception text can contain credentials, SQL or provider responses.
            trusted = type(error) in (
                CohortError,
                FaultRecoveryError,
                RuntimeIdentityError,
                DeploymentError,
                ReceivingLivenessError,
            )
            candidate = getattr(error, "code", None) if trusted else None
            if trusted and not isinstance(candidate, str):
                candidate = str(error)
            code = (
                candidate
                if isinstance(candidate, str)
                and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", candidate)
                else "COHORT_FORWARD_STEP_FAILED"
            )
            allowed_types = {
                "CohortError",
                "FaultRecoveryError",
                "RuntimeIdentityError",
                "DeploymentError",
                "RuntimeError",
                "TypeError",
                "ValueError",
                "KeyError",
                "OSError",
                "PermissionError",
                "FileNotFoundError",
                "BlockingIOError",
                "TimeoutExpired",
                "CalledProcessError",
                "ReceivingLivenessError",
            }
            error_type = type(error).__name__
            stage = journal["phase"]
            journal["error_code"] = code
            journal["error_type"] = (
                error_type if error_type in allowed_types else "REDACTED"
            )
            journal["failed_stage"] = (
                stage
                if isinstance(stage, str) and re.fullmatch(r"[a-z][a-z_]{0,63}", stage)
                else "unknown"
            )
            if stage == "verified":
                diagnostic = _safe_verification_diagnostic(host)
                if diagnostic is not None:
                    journal["verified_diagnostic"] = diagnostic
            try:
                persist("outcome_unknown" if mutated else "precondition_blocked")
            finally:
                if mutated:
                    try:
                        host.halt_unknown(source)
                    except Exception:
                        pass
            raise CohortError(
                "COHORT_FORWARD_OUTCOME_UNKNOWN" if mutated else code
            ) from None


class ForwardRecoveryHost(CohortHost):
    """Native adapter for already-installed, parked new owners only."""

    monotonic = staticmethod(monotonic)

    def recovery_window(self):
        """Normal same-generation startup authority; never a version-CAS exception."""
        from app.db.session import SessionLocal
        from app.db.readonly import readonly_transaction
        from app.market_data.composition import build_market_feed_service
        from app.market_data.observation_stream import ObservationStream

        feed = None
        try:
            with (
                SessionLocal() as session,
                readonly_transaction(session, timeout_seconds=20),
            ):
                feed = build_market_feed_service(
                    session
                )  # Composition only; no poll/provider startup.
                products = tuple(feed._products)
                require(len(products) == 60, "COHORT_FORWARD_SCOPE_INVALID")
                source = feed.source_stream
                completed = ObservationStream(source.redis, kind="completed")
                day = source.registered_day("live")
                require(
                    day in source.days()
                    and day in completed.days()
                    and all(
                        completed.registered_day(name) == day
                        for name in ("alert", "reference")
                    ),
                    "COHORT_FORWARD_REGISTERED_DAY_DRIFT",
                )
                return prove_same_generation_startup(
                    now=self.now(),
                    products=products,
                    resolver=feed._phase_resolver,
                    registered_day=day,
                    subscriptions=feed._store.subscriptions(day),
                    dominant=feed._dominant_source.dominant_for_day,
                    sessions=feed._coverage_session_source,
                )
        finally:
            if feed is not None:
                clients = {
                    id(client): client
                    for client in (feed._store._redis, feed.source_stream.redis)
                }
                for client in clients.values():
                    client.close()

    def _controller(self):
        from app.runtime_bindings import _git, _tracked

        root = Path(__file__).resolve().parents[3]
        tag = root.name.removeprefix("release-")
        require(
            root.name == "release-" + tag
            and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag),
            "COHORT_FORWARD_CONTROLLER_RELEASE_REQUIRED",
        )
        commit = _git(root, "rev-parse", "HEAD")
        self.verify_release(
            root, tag, commit
        )  # Exact annotated tag, detached HEAD, entire tree clean.
        tracked = _tracked(root)
        require(
            {
                "services/quant-api/app/runtime_cohort_recovery.py",
                "services/quant-api/app/reference_trading/receiving_liveness.py",
            }
            <= set(tracked),
            "COHORT_FORWARD_CONTROLLER_UNPROVEN",
        )
        return {
            "root": str(root),
            "tag": tag,
            "commit": commit,
            "source_sha256": sha256(self.bytes(Path(__file__))).hexdigest(),
            "tracked_sha256": digest(tracked),
        }

    def _protected_preimages(self, source):
        """Retain old evidence; current release state has its own exact preimage."""
        old, new = registry(source["old"]), registry(source["new"])
        previous = self.protected(old)
        require(previous == source["protected"], "COHORT_FORWARD_PROTECTED_DRIFT")
        current = self.protected(new)
        require(
            set(previous)
            == set(current)
            == {"db_scope_policy_identity_sha256", "files"}
            and previous["db_scope_policy_identity_sha256"]
            == current["db_scope_policy_identity_sha256"],
            "COHORT_FORWARD_PROTECTED_DRIFT",
        )
        names = {
            "after-market-status.json",
            "after-market-history.json",
            "market-runtime-enabled",
            "alert-runtime-enabled",
            "reference-worker-enabled",
            "weekly-audit-enabled",
        }

        def local_keys(reg):
            return {
                str(Path(binding.root) / ".run" / name)
                for binding in reg.services.values()
                for name in names
            }

        # Compare every shared real path and every non-local key, including new
        # private paths. No basename remapping can discard old natural evidence.
        before, after = previous["files"], current["files"]
        old_local, new_local = local_keys(old), local_keys(new)
        require(
            isinstance(before, dict)
            and isinstance(after, dict)
            and all(before[key] == after[key] for key in before.keys() & after.keys())
            and {key: value for key, value in before.items() if key not in old_local}
            == {key: value for key, value in after.items() if key not in new_local},
            "COHORT_FORWARD_PROTECTED_DRIFT",
        )
        markers = {
            "live": "market-runtime-enabled",
            "alert": "alert-runtime-enabled",
            "reference-worker": "reference-worker-enabled",
            "weekly-audit": "weekly-audit-enabled",
        }
        for service, name in markers.items():
            binding = new.services[service]
            path = Path(binding.root) / ".run" / name
            if binding.enabled:
                require(
                    path.exists() and self.bytes(path) == b"enabled\n",
                    "COHORT_FORWARD_ACTIVATION_UNPROVEN",
                )
            else:
                require(not os.path.lexists(path), "COHORT_FORWARD_ACTIVATION_UNPROVEN")
        return current

    def check_protected_forward(self, source, audit):
        require(
            self._protected_preimages(source) == audit["new_protected"],
            "COHORT_FORWARD_NEW_PROTECTED_DRIFT",
        )
        self._check_receiving_context(source, audit, lambda: None)

    def _check_receiving_context(self, source, audit, check_budget, *, snapshot=None):
        """Pin the frozen protocol/source authority before every recovery phase."""
        if "receiving_context" not in audit:
            return
        from app.reference_trading.receiving_liveness import receiving_context_identity

        check_budget()
        current = self._snapshot(source, check_budget) if snapshot is None else snapshot
        require(
            receiving_context_identity(current) == audit["receiving_context"],
            "COHORT_FORWARD_RECEIVING_CONTEXT_DRIFT",
        )
        check_budget()

    def _fixed(self, source, check_budget):
        controller = self._controller()
        require(
            controller == getattr(self, "_expected_controller", controller),
            "COHORT_FORWARD_CONTROLLER_DRIFT",
        )
        new = registry(source["new"])
        require(self.bindings() == new, "COHORT_FORWARD_REGISTRY_DRIFT")
        seen = set()
        for binding in new.services.values():
            identity = binding.root, binding.tag, binding.commit
            if identity not in seen:
                self.verify_release(Path(binding.root), binding.tag, binding.commit)
                require(
                    self.contracts(Path(binding.root)) == binding.contracts,
                    "COHORT_FORWARD_CONTRACT_DRIFT",
                )
                seen.add(identity)
            check_budget()
        current_protected = self._protected_preimages(source)
        require(
            current_protected
            == getattr(self, "_expected_new_protected", current_protected),
            "COHORT_FORWARD_NEW_PROTECTED_DRIFT",
        )
        self._new_protected = current_protected
        self.check_schema_compatibility(source)
        import plistlib

        installed = {}
        for name, binding in new.services.items():
            raw = self.bytes(self.path(binding))
            self.verify_plist(binding, plistlib.loads(raw))
            installed[name] = {"sha256": sha256(raw).hexdigest()}
        installed["launcher_sha256"] = sha256(
            self.bytes(self.directory / "run-local-service.sh")
        ).hexdigest()
        require(
            installed["launcher_sha256"] == source["installed"]["launcher_sha256"],
            "COHORT_FORWARD_LAUNCHER_DRIFT",
        )
        check_budget()
        return {
            name: {"sha256": row["sha256"]}
            for name, row in installed.items()
            if name != "launcher_sha256"
        } | {"launcher_sha256": installed["launcher_sha256"]}

    def _old_exited(self, source):
        _raw, state = _resolution_source(
            self.directory / "cohort-attempts" / source["plan_sha256"] / "state.json"
        )
        owners = state["effects"]["drain"]["owners"]
        require(set(owners) == set(CONTINUOUS), "COHORT_FORWARD_OLD_EXIT_UNPROVEN")
        for owner in owners.values():
            pid = owner.get("pid")
            require(
                type(pid) is int and 1 < pid <= 2**31 - 1,
                "COHORT_FORWARD_OLD_EXIT_UNPROVEN",
            )
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except OSError:
                raise CohortError("COHORT_FORWARD_OLD_EXIT_UNPROVEN") from None
            raise CohortError("COHORT_FORWARD_OLD_EXIT_UNPROVEN")
        return digest(owners)

    def _controls(self, source):
        new = registry(source["new"])
        result = {}
        for name in CONTINUOUS:
            value = _read(self.directory / (name + ".handover.json"))
            require(
                isinstance(value, dict)
                and set(value)
                == {"schema_version", "service", "generation", "request_id", "phase"}
                and value["schema_version"] == 1
                and value["service"] == name
                and type(value["generation"]) is int
                and value["generation"] == new.services[name].generation
                and value["phase"] == "drain"
                and isinstance(value["request_id"], str)
                and re.fullmatch(r"[0-9a-f]{32}", value["request_id"]),
                "COHORT_FORWARD_DRAIN_UNPROVEN",
            )
            result[name] = value
        return result

    def _parked_owners(
        self, source, *, held=False, allow_live_restart=False, live_absent=False
    ):
        new = registry(source["new"])
        result = {}
        for name in CONTINUOUS:
            binding = new.services[name]
            if name == "market-feed":
                require(
                    self.definition_absent(binding),
                    "COHORT_FORWARD_FEED_ALREADY_STARTED",
                )
                result[name] = {"phase": "absent", "generation": binding.generation}
                continue
            if name == "live" and live_absent:
                require(
                    self.definition_absent(binding), "COHORT_FORWARD_LIVE_EXIT_UNPROVEN"
                )
                result[name] = {"phase": "absent", "generation": binding.generation}
                continue
            state = read_service_state(name, runtime_dir=self.directory)
            if (
                name == "live"
                and allow_live_restart
                and state
                and state.get("phase") == "active"
            ):
                require(
                    state.get("generation") == binding.generation,
                    "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN",
                )
                result[name] = {
                    "phase": "draining_live_teardown",
                    "generation": binding.generation,
                }
                continue
            require(
                isinstance(state, dict)
                and state.get("phase") == "parked"
                and state.get("generation") == binding.generation
                and type(state.get("pid")) is int
                and state["pid"] > 1
                and str(state["pid"]) == str(self.loaded(binding))
                and owner_process_matches(state, binding)
                and (held or owner_lock_available(name, runtime_dir=self.directory)),
                "COHORT_FORWARD_OWNER_UNPROVEN",
            )
            result[name] = {key: state[key] for key in ("pid", "generation", "phase")}
        return result

    def _read_calculation_boundary(self):
        from app.db.session import SessionLocal
        from app.db.readonly import readonly_transaction
        from app.reference_trading.models import (
            ReferenceBatch,
            ReferenceStream,
            ReferenceInboxDelivery,
        )
        from sqlalchemy import select, func

        with (
            SessionLocal() as session,
            readonly_transaction(session, timeout_seconds=20),
        ):
            pending = session.scalar(
                select(func.count())
                .select_from(ReferenceBatch)
                .join(
                    ReferenceStream,
                    ReferenceStream.stream_id == ReferenceBatch.stream_id,
                )
                .where(
                    ReferenceStream.enabled.is_(True),
                    ReferenceBatch.revision_id == ReferenceStream.active_revision_id,
                    ReferenceBatch.kind == "capture",
                    ReferenceBatch.consumed_by_batch_id.is_(None),
                )
            )
            unknown = session.scalar(
                select(func.count())
                .select_from(ReferenceInboxDelivery)
                .where(ReferenceInboxDelivery.status == "UNKNOWN")
            )
        return pending, unknown

    def _calculation_boundary(self, *, active=False):
        pending, unknown = self._read_calculation_boundary()
        require(
            unknown == 0 and (active or pending == 0),
            "COHORT_FORWARD_CALCULATION_UNKNOWN",
        )
        return pending == 0

    def _snapshot(self, source, check_budget, *, state=None):
        from app.reference_trading.receiving_liveness import (
            snapshot_receiving,
            ReceivingLivenessError,
        )
        from app.db.session import SessionLocal

        _raw, original = _resolution_source(
            self.directory / "cohort-attempts" / source["plan_sha256"] / "state.json"
        )
        target = registry(source["new"]).services["reference-worker"]
        try:
            with self._reference_receiving_context(target) as context:
                require(context is not None, "COHORT_FORWARD_SOURCE_UNPROVEN")
                protocol, journal, authority, _capacity = context
                value = protocol.read()
                require(
                    value is not None
                    and value.get("status") == "active"
                    and value.get("intake_error") is None,
                    "COHORT_FORWARD_PROTOCOL_UNPROVEN",
                )
                check_budget()
                snapshot = snapshot_receiving(
                    SessionLocal,
                    protocol,
                    journal,
                    intent=source["reference_receiving_handover"],
                    source_proof=original["effects"]["drain"][
                        "reference_receiving_handover"
                    ],
                    target=asdict(target),
                    schema_proof=authority,
                    check_budget=check_budget,
                    sampled_at=self.now(),
                    owner_cycle_at=state["at"] if state else None,
                )
                check_budget()
                return snapshot
        except ReceivingLivenessError as error:
            raise CohortError(str(error)) from None

    def confirm_live_stop(self, source, predecessor, check_budget):
        from app.reference_trading.receiving_liveness import receiving_snapshot_identity

        # The controller has already revalidated all predecessor bytes; read its
        # private plan for the exact frozen receiving/protected/other-owner preimage.
        _raw, previous = _resolution_source(
            self.directory
            / "cohort-forward-recoveries"
            / predecessor["plan_sha256"]
            / "plan.json"
        )
        fresh, _previous = _predecessor(
            self, predecessor["plan_path"], previous["source"]
        )
        require(
            fresh == predecessor
            and previous["new"] == source["new"]
            and previous["source"]["plan_sha256"] == source["plan_sha256"],
            "COHORT_FORWARD_PREDECESSOR_DRIFT",
        )
        binding = registry(source["new"]).services["live"]
        require(
            self.definition_absent(binding)
            and owner_lock_available("live", runtime_dir=self.directory),
            "COHORT_FORWARD_LIVE_EXIT_UNPROVEN",
        )
        for pid in predecessor["observed_pids"]:
            check_budget()
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except OSError:
                raise CohortError("COHORT_FORWARD_LIVE_EXIT_UNPROVEN") from None
            raise CohortError("COHORT_FORWARD_LIVE_EXIT_UNPROVEN")
        owners = self._parked_owners(source, live_absent=True)
        expected_owners = dict(previous["audit"]["owners"])
        expected_owners["live"] = {"phase": "absent", "generation": binding.generation}
        require(owners == expected_owners, "COHORT_FORWARD_OWNER_UNPROVEN")
        self.check_protected_forward(source, previous["audit"])
        self.check_schema_compatibility(source)
        self._old_exited(source)
        self._calculation_boundary()
        require(
            receiving_snapshot_identity(self._snapshot(source, check_budget))
            == previous["audit"]["receiving"],
            "COHORT_FORWARD_SOURCE_DRIFT",
        )
        check_budget()
        proof = {
            "predecessor_plan_sha256": predecessor["plan_sha256"],
            "observed_pids": predecessor["observed_pids"],
            "live_absent": True,
            "observed_pids_exited": True,
            "owner_lock_available": True,
        }
        proof["proof_sha256"] = digest(proof)
        require(
            valid_confirmed_live_stop(proof, predecessor),
            "COHORT_FORWARD_PREDECESSOR_INVALID",
        )
        self._live_stopped = True
        return proof

    def audit_forward(self, source, check_budget, *, expected=None, predecessor=None):
        from app.reference_trading.receiving_liveness import receiving_snapshot_identity

        intake_halt = predecessor is not None and "ancestor" in predecessor
        confirmation = (
            self.confirm_live_stop(source, predecessor, check_budget)
            if predecessor is not None and not intake_halt
            else None
        )
        if expected is not None:
            self._expected_new_protected = expected["new_protected"]
        fixed = self._fixed(source, check_budget)
        old_exited = self._old_exited(source)
        controls = self._controls(source)
        owners = self._parked_owners(
            source,
            allow_live_restart=predecessor is None,
            live_absent=predecessor is not None and not intake_halt,
        )
        live_intent = None
        if owners["live"]["phase"] == "draining_live_teardown":
            live_intent = self._live_restart_intent(
                source, fixed["live"]["sha256"], controls["live"], check_budget
            )
            if expected is not None:
                require(
                    compatible_live_restart_intent(
                        live_intent, expected.get("live_restart_intent")
                    ),
                    "COHORT_FORWARD_LIVE_INTENT_DRIFT",
                )
                live_intent = expected["live_restart_intent"]
        new = registry(source["new"])
        require(
            all(self.definition_absent(new.services[name]) for name in CALENDARS),
            "COHORT_FORWARD_CALENDAR_ALREADY_LOADED",
        )
        self._calculation_boundary()
        _raw, state = _resolution_source(
            self.directory / "cohort-attempts" / source["plan_sha256"] / "state.json"
        )
        for name in ("market-feed", "live", "alert"):
            current = observation_progress(name)
            require(
                progress_reached(
                    current, state["effects"]["drain"]["progress"][name], service=name
                ),
                "COHORT_FORWARD_OTHER_CONSUMER_BACKLOG",
            )
        snapshot = self._snapshot(source, check_budget)
        window = self.recovery_window()
        check_budget()
        additional = {}
        if intake_halt:
            from app.reference_trading.receiving_liveness import (
                receiving_context_identity,
            )

            _raw, selected_plan = _resolution_source(Path(predecessor["plan_path"]))
            identity = _source(self, selected_plan["source"]["plan_path"])[2]
            fresh, previous = _intake_predecessor(
                self, predecessor["plan_path"], identity
            )
            require(
                fresh == predecessor
                and previous["audit"]["new_protected"] == self._new_protected,
                "COHORT_FORWARD_PREDECESSOR_DRIFT",
            )
            # Legacy B only retained a receiving digest. Require the entire current
            # queue independently DB/routes-verified and acknowledged, not just its old tail.
            require(
                snapshot["old_tail_reached"] is True
                and all(
                    row["ack"] == row["current_tail"] == row["final_tail"]
                    for row in snapshot["days"].values()
                ),
                "COHORT_FORWARD_LEGACY_FRONTIER_UNPROVEN",
            )
            context = receiving_context_identity(snapshot)
            proof = {
                "predecessor_plan_sha256": predecessor["plan_sha256"],
                "owners_sha256": digest(owners),
                "controls_sha256": digest(controls),
                "receiving_context": context,
                "all_consumers_parked": True,
                "feed_absent": True,
                "current_tail_reached": True,
            }
            proof["proof_sha256"] = digest(proof)
            additional = {"receiving_context": context, "confirmed_intake_halt": proof}
        return {
            "registry_sha256": self.binding_hash(),
            "installed_sha256": digest(fixed),
            "old_exited_sha256": old_exited,
            "protected": source["protected"],
            "new_protected": self._new_protected,
            "owners": owners,
            "controls": controls,
            "receiving": receiving_snapshot_identity(snapshot),
            "window": window,
            "controller": self._controller(),
            **additional,
            **({"live_restart_intent": live_intent} if live_intent is not None else {}),
            **(
                {"confirmed_live_stop": confirmation}
                if confirmation is not None
                else {}
            ),
        }

    def _live_launchd_sample(self, source):
        from app.runtime_identity import (
            read_launchd_service,
            verify_loaded_service,
            launchd_arguments,
        )
        from app.runtime_bindings import authorized_program_arguments

        binding = registry(source["new"]).services["live"]
        output = read_launchd_service(binding.label, root=Path(binding.root))
        require(output is not None, "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN")
        numbers, headers, environment, scopes = {}, {}, {}, []
        for raw in output.splitlines():
            line = raw.strip()
            if line.endswith((" = {", " => {")):
                name, operator, _brace = line.rsplit(" ", 2)
                require(
                    scopes or operator == "=", "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN"
                )
                scopes.append((name, operator))
            elif line == "}":
                require(bool(scopes), "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN")
                scopes.pop()
            elif len(scopes) == 1:
                match = re.fullmatch(r"(runs|last exit code) = ([0-9]+)", line)
                if match:
                    require(
                        match[1] not in numbers, "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN"
                    )
                    numbers[match[1]] = int(match[2])
                match = re.fullmatch(r"(state|pid|working directory) = (.*)", line)
                if match:
                    require(
                        match[1] not in headers, "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN"
                    )
                    headers[match[1]] = match[2]
            elif len(scopes) == 2 and scopes[-1] == ("environment", "="):
                match = re.fullmatch(
                    r"(GUIYI_PROJECT_ROOT|GUIYI_RUNTIME_COMMIT|GUIYI_RUNTIME_TAG|GUIYI_RUNTIME_GENERATION) => (.*)",
                    line,
                )
                if match:
                    require(
                        match[1] not in environment,
                        "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN",
                    )
                    environment[match[1]] = match[2]
        require(
            not scopes
            and headers.get("working directory") == binding.root
            and environment
            == {
                "GUIYI_PROJECT_ROOT": binding.root,
                "GUIYI_RUNTIME_COMMIT": binding.commit,
                "GUIYI_RUNTIME_TAG": binding.tag,
                "GUIYI_RUNTIME_GENERATION": str(binding.generation),
            }
            and launchd_arguments(output)
            == authorized_program_arguments(binding, self.home),
            "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN",
        )
        require(
            2 <= numbers.get("runs", 0) <= 2**31 - 1
            and numbers.get("last exit code") == 1,
            "COHORT_FORWARD_LIVE_LOOP_UNPROVEN",
        )
        if headers.get("state") == "spawn scheduled":
            # launchd's observed KeepAlive delay has no process. It contributes
            # no PID/ownership evidence; every identity above is still required.
            require("pid" not in headers, "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN")
            return {"pid": None, "observed_pid": None, "runs": numbers["runs"]}
        fields = verify_loaded_service(
            output, root=Path(binding.root), commit=binding.commit, allow_idle=True
        )
        require(
            fields.get("state") == "running" or not fields.get("pid"),
            "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN",
        )
        pid = (
            int(fields["pid"])
            if fields.get("state") == "running" and fields.get("pid")
            else None
        )
        if pid is not None:
            state = read_service_state("live", runtime_dir=self.directory)
            if not (
                state
                and state.get("phase") == "active"
                and state.get("pid") == pid
                and state.get("generation") == binding.generation
                and not owner_lock_available("live", runtime_dir=self.directory)
            ):
                sample = {"pid": None, "observed_pid": pid, "runs": numbers["runs"]}
                self._remember_live_sample(source, sample)
                return sample
        sample = {"pid": pid, "observed_pid": pid, "runs": numbers["runs"]}
        self._remember_live_sample(source, sample)
        return sample

    def _remember_live_sample(self, source, sample):
        binding = digest(asdict(registry(source["new"]).services["live"]))
        require(
            binding == getattr(self, "_observed_live_binding", binding),
            "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN",
        )
        self._observed_live_binding = binding
        observed = set(getattr(self, "_observed_live_pids", ()))
        pid = sample.get("observed_pid", sample.get("pid"))
        if pid is not None:
            require(
                type(pid) is int and 1 < pid <= 2**31 - 1,
                "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN",
            )
            observed.add(pid)
        require(len(observed) <= 64, "COHORT_FORWARD_LIVE_IDENTITY_UNPROVEN")
        self._observed_live_pids = observed

    def _live_restart_intent(self, source, installed_sha256, control, check_budget):
        binding = registry(source["new"]).services["live"]
        end = self.monotonic() + 25
        pids, runs = set(), 0
        while self.monotonic() < end:
            check_budget()
            require(
                self._controls(source)["live"] == control, "COHORT_FORWARD_DRAIN_DRIFT"
            )
            sample = self._live_launchd_sample(source)
            self._remember_live_sample(source, sample)
            require(sample["runs"] >= runs, "COHORT_FORWARD_LIVE_LOOP_UNPROVEN")
            runs = sample["runs"]
            if sample["pid"] is not None:
                pids.add(sample["pid"])
            if len(pids) >= 2:
                return {
                    "kind": "draining_live_teardown_v1",
                    "failure_code": "COHORT_FORWARD_LIVE_DRAIN_RESTART_LOOP",
                    "binding_sha256": digest(asdict(binding)),
                    "installed_sha256": installed_sha256,
                    "control_sha256": digest(control),
                    "observed_pids": sorted(self._observed_live_pids),
                    "owned_pids": sorted(pids),
                    "minimum_runs": runs,
                }
            sleep(0.2)
        raise CohortError("COHORT_FORWARD_LIVE_LOOP_UNPROVEN")

    def stop_draining_live(self, source, audit, check_budget, record):
        from app.reference_trading.receiving_liveness import receiving_snapshot_identity

        binding = registry(source["new"]).services["live"]
        self._expected_controller = audit["controller"]
        with self.forward_guards(source):
            fixed = self._fixed(source, check_budget)
            require(
                digest(fixed) == audit["installed_sha256"], "COHORT_FORWARD_AUDIT_DRIFT"
            )
            require(
                self._controls(source) == audit["controls"],
                "COHORT_FORWARD_DRAIN_DRIFT",
            )
            current = self._live_restart_intent(
                source, fixed["live"]["sha256"], audit["controls"]["live"], check_budget
            )
            require(
                compatible_live_restart_intent(current, audit["live_restart_intent"]),
                "COHORT_FORWARD_LIVE_INTENT_DRIFT",
            )
            self._calculation_boundary()
            require(
                receiving_snapshot_identity(self._snapshot(source, check_budget))
                == audit["receiving"],
                "COHORT_FORWARD_SOURCE_DRIFT",
            )
            self._old_exited(source)
            self.recovery_window()
            pids = set(audit["live_restart_intent"]["observed_pids"]) | set(
                current["observed_pids"]
            )
            latest = self._live_launchd_sample(source)
            self._remember_live_sample(source, latest)
            pids.update(self._observed_live_pids)
            evidence = {
                "phase": "bootout_requested",
                "observed_pids": sorted(pids),
                "intent": audit["live_restart_intent"],
            }
            record(evidence)  # Durable intent precedes the ONE native request.
            require(
                digest(self._fixed(source, check_budget)) == audit["installed_sha256"]
                and self._controls(source) == audit["controls"],
                "COHORT_FORWARD_AUDIT_DRIFT",
            )
            require(
                self._controller() == audit["controller"],
                "COHORT_FORWARD_CONTROLLER_DRIFT",
            )
            self.check_protected_forward(source, audit)
            check_budget()
            self.launch("bootout", f"gui/{os.getuid()}/{binding.label}")
            end = self.monotonic() + 30
            while self.monotonic() < end:
                check_budget()
                absent = self.definition_absent(binding)
                if not absent:
                    sample = self._live_launchd_sample(source)
                    self._remember_live_sample(source, sample)
                    new_pids = self._observed_live_pids - pids
                    if new_pids:
                        pids.update(new_pids)
                        record(
                            {
                                **evidence,
                                "phase": "bootout_waiting",
                                "observed_pids": sorted(pids),
                            }
                        )
                exited = True
                for pid in pids:
                    try:
                        os.kill(pid, 0)
                        exited = False
                    except ProcessLookupError:
                        pass
                    except OSError:
                        raise CohortError("COHORT_FORWARD_LIVE_EXIT_UNPROVEN") from None
                if (
                    absent
                    and exited
                    and owner_lock_available("live", runtime_dir=self.directory)
                ):
                    require(
                        self._controls(source) == audit["controls"],
                        "COHORT_FORWARD_DRAIN_DRIFT",
                    )
                    require(
                        digest(self._fixed(source, check_budget))
                        == audit["installed_sha256"],
                        "COHORT_FORWARD_AUDIT_DRIFT",
                    )
                    self._old_exited(source)
                    self._calculation_boundary()
                    require(
                        receiving_snapshot_identity(
                            self._snapshot(source, check_budget)
                        )
                        == audit["receiving"],
                        "COHORT_FORWARD_SOURCE_DRIFT",
                    )
                    expected_owners = dict(audit["owners"])
                    if "live" in expected_owners:
                        expected_owners["live"] = {
                            "phase": "absent",
                            "generation": binding.generation,
                        }
                    require(
                        self._parked_owners(source, live_absent=True)
                        == expected_owners,
                        "COHORT_FORWARD_OWNER_UNPROVEN",
                    )
                    self.recovery_window()
                    check_budget()
                    self._live_stopped = True
                    return {
                        **evidence,
                        "phase": "absent_exited",
                        "observed_pids": sorted(pids),
                    }
                sleep(0.1)
            raise CohortError("COHORT_FORWARD_LIVE_EXIT_UNPROVEN")

    @contextmanager
    def forward_guards(self, source):
        with self.after_market_guard(), self.maintenance_guard():
            yield

    @contextmanager
    def _resume_owner_guards(self):
        with ExitStack() as stack:
            descriptors = []
            for name in CONTINUOUS:
                path = self.directory / (name + ".owner.lock")
                fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
                stack.callback(os.close, fd)
                info = os.fstat(fd)
                require(
                    stat.S_ISREG(info.st_mode)
                    and info.st_uid == os.getuid()
                    and info.st_nlink == 1
                    and not info.st_mode & 0o077,
                    "COHORT_FORWARD_OWNER_LOCK_INVALID",
                )
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                descriptors.append((path, fd))

            def assert_held():
                for path, fd in descriptors:
                    disk, held = path.lstat(), os.fstat(fd)
                    require(
                        not stat.S_ISLNK(disk.st_mode)
                        and (disk.st_ino, disk.st_dev) == (held.st_ino, held.st_dev),
                        "COHORT_FORWARD_OWNER_LOCK_INVALID",
                    )
                return {
                    str(path): (os.fstat(fd).st_ino, os.fstat(fd).st_dev)
                    for path, fd in descriptors
                }

            assert_held()
            yield assert_held

    def resume_consumers(self, source, audit, check_budget):
        # Verify under real writer locks, then RELEASE them before waking v14's
        # nonblocking owner acquisition. Deployment/maintenance remain held.
        self._expected_controller = audit["controller"]
        with self.forward_guards(source):
            with self._resume_owner_guards() as held:
                expected_owners = dict(audit["owners"])
                if getattr(self, "_live_stopped", False):
                    expected_owners["live"] = {
                        "phase": "absent",
                        "generation": registry(source["new"])
                        .services["live"]
                        .generation,
                    }
                require(
                    self._controls(source) == audit["controls"]
                    and self._parked_owners(
                        source,
                        held=True,
                        live_absent=getattr(self, "_live_stopped", False),
                    )
                    == expected_owners,
                    "COHORT_FORWARD_AUDIT_DRIFT",
                )
                require(
                    digest(self._fixed(source, check_budget))
                    == audit["installed_sha256"],
                    "COHORT_FORWARD_AUDIT_DRIFT",
                )
                from app.reference_trading.receiving_liveness import (
                    receiving_snapshot_identity,
                )

                require(
                    receiving_snapshot_identity(self._snapshot(source, check_budget))
                    == audit["receiving"],
                    "COHORT_FORWARD_SOURCE_DRIFT",
                )
                self._old_exited(source)
                self._calculation_boundary()
                self.recovery_window()
                check_budget()
                lock_identities = held()
            for name in ("live", "alert", "reference-worker", "api", "web"):
                path = self.directory / (name + ".owner.lock")
                disk = path.lstat()
                require(
                    not stat.S_ISLNK(disk.st_mode)
                    and (disk.st_ino, disk.st_dev) == lock_identities[str(path)]
                    and owner_lock_available(name, runtime_dir=self.directory),
                    "COHORT_FORWARD_OWNER_LOCK_INVALID",
                )
                require(
                    self.bindings() == registry(source["new"])
                    and _read(self.directory / (name + ".handover.json"))
                    == audit["controls"][name],
                    "COHORT_FORWARD_DRAIN_DRIFT",
                )
                require(
                    self._controller() == audit["controller"],
                    "COHORT_FORWARD_CONTROLLER_DRIFT",
                )
                self.check_protected_forward(source, audit)
                check_budget()
                cancel_drain(
                    name,
                    request_id=audit["controls"][name]["request_id"],
                    runtime_dir=self.directory,
                )
                if name == "live" and getattr(self, "_live_stopped", False):
                    require(
                        self._controller() == audit["controller"],
                        "COHORT_FORWARD_CONTROLLER_DRIFT",
                    )
                    self.check_protected_forward(source, audit)
                    check_budget()
                    self.start(registry(source["new"]).services["live"])
        return {
            "resumed_generation": registry(source["new"])
            .services["reference-worker"]
            .generation
        }

    def _active(self, binding):
        state = read_service_state(binding.service, runtime_dir=self.directory)
        if not (
            state
            and state.get("phase") == "active"
            and state.get("generation") == binding.generation
            and owner_process_matches(state, binding)
            and not owner_lock_available(binding.service, runtime_dir=self.directory)
        ):
            return None
        try:
            at = datetime.fromisoformat(state["at"])
            if not 0 <= (self.now() - at).total_seconds() <= 30:
                return None
        except (KeyError, ValueError, TypeError):
            return None
        return state

    def _await(self, source, audit, check_budget, *, feed):
        from app.reference_trading.receiving_liveness import (
            prove_receiving_liveness,
            receiving_sample_is_fresh,
            verify_receiving_continuity,
            verify_receiving_nonregression,
        )

        new = registry(source["new"])
        _raw, original = _resolution_source(
            self.directory / "cohort-attempts" / source["plan_sha256"] / "state.json"
        )
        end = self.monotonic() + (120 if feed else 240)
        before = None
        previous = None
        while self.monotonic() < end:
            _verification_substep(self, "session_authority", before=before)
            check_budget()
            self.recovery_window()
            _verification_substep(self, "owner_readiness", before=before)
            names = (
                CONTINUOUS
                if feed
                else tuple(name for name in CONTINUOUS if name != "market-feed")
            )
            states = {name: self._active(new.services[name]) for name in names}
            if not all(states.values()):
                sleep(0.2)
                continue
            okay = True
            for name, state in states.items():
                if name == "reference-worker":
                    rp = state.get("proof", {})
                    receiving = rp.get("receiving", {})
                    okay = (
                        okay
                        and isinstance(receiving, dict)
                        and receiving.get("protocol_version") == 2
                        and receiving.get("intake_error") is None
                    )
                    okay = (
                        okay
                        and rp.get("reference_runtime", {}).get("stage")
                        == "receiving_cycle"
                    )
                else:
                    okay = okay and state.get("ready") is True
                    if name in original["effects"]["drain"]["progress"]:
                        okay = okay and progress_reached(
                            observation_progress(name),
                            original["effects"]["drain"]["progress"][name],
                            service=name,
                            proof=state.get("proof"),
                        )
                    if name in {"api", "web"}:
                        okay = okay and port_is_ready(name)
            if not okay:
                sleep(0.2)
                continue
            _verification_substep(self, "calculation_boundary", before=before)
            if not self._calculation_boundary(active=True):
                sleep(0.2)
                continue
            _verification_substep(self, "receiving_snapshot", before=before)
            current = self._snapshot(
                source, check_budget, state=states["reference-worker"]
            )
            _verification_substep(
                self, "receiving_continuity", before=before, current=current
            )
            self._check_receiving_context(source, audit, check_budget, snapshot=current)
            now = self.now()
            current_fresh = receiving_sample_is_fresh(current, now=now)
            if previous is not None:
                verify_receiving_continuity(previous, current)
            previous = current
            if before is None:
                before = current
            elif current["owner_cycle_at"] != before["owner_cycle_at"]:
                if not (current_fresh and receiving_sample_is_fresh(before, now=now)):
                    # Expiry only rolls the sampling window AFTER the entire
                    # context/ACK/DB transition has been checked. It never
                    # grants readiness, hides regression or extends the budget.
                    before = current
                    sleep(0.2)
                    continue
                comparison = verify_receiving_nonregression(before, current, now=now)
                if (
                    comparison["advanced_count"] == 0
                    and not comparison["caught_up_idle"]
                ):
                    before = current
                    sleep(0.2)
                    continue
                _verification_substep(
                    self, "fixed_identity", before=before, current=current
                )
                self._fixed(source, check_budget)
                _verification_substep(self, "budget", before=before, current=current)
                check_budget()
                require(self.monotonic() < end, "COHORT_FORWARD_READY_TIMEOUT")
                _verification_substep(
                    self, "receiving_liveness", before=before, current=current
                )
                now = self.now()
                fresh = [
                    receiving_sample_is_fresh(value, now=now)
                    for value in (before, current)
                ]
                if not all(fresh):
                    before = current
                    sleep(0.2)
                    continue
                return prove_receiving_liveness(before, current, now=now)
            sleep(0.2)
        raise CohortError("COHORT_FORWARD_READY_TIMEOUT")

    def await_consumers(self, source, audit, check_budget):
        return self._await(source, audit, check_budget, feed=False)

    def resume_feed(self, source, audit, check_budget):
        require(
            self._controller() == audit["controller"], "COHORT_FORWARD_CONTROLLER_DRIFT"
        )
        self.check_protected_forward(source, audit)
        self._fixed(source, check_budget)
        self.recovery_window()
        check_budget()
        control = _read(self.directory / "market-feed.handover.json")
        require(
            control == audit["controls"]["market-feed"], "COHORT_FORWARD_DRAIN_DRIFT"
        )
        binding = registry(source["new"]).services["market-feed"]
        require(self.definition_absent(binding), "COHORT_FORWARD_FEED_ALREADY_STARTED")
        self._check_receiving_context(source, audit, check_budget)
        cancel_drain(
            "market-feed", request_id=control["request_id"], runtime_dir=self.directory
        )
        require(
            self._controller() == audit["controller"], "COHORT_FORWARD_CONTROLLER_DRIFT"
        )
        self.check_protected_forward(source, audit)
        check_budget()
        return self.start(binding)

    def verify_forward(self, source, audit, check_budget):
        intake = self._await(source, audit, check_budget, feed=True)
        from app.services.deployment_identity import deployment_identity_health

        _verification_substep(self, "deployment_identity")
        new = registry(source["new"])
        api = new.services["api"]
        identity = deployment_identity_health(root=Path(api.root), commit=api.commit)
        require(
            all(
                identity.get("services", {})
                .get(IDENTITY_NAMES.get(name, name), {})
                .get("status")
                == "matched"
                for name in CONTINUOUS
            ),
            "COHORT_FORWARD_IDENTITY_UNPROVEN",
        )
        from urllib.request import urlopen

        _verification_substep(self, "api_http")
        with urlopen("http://127.0.0.1:8000/api/health", timeout=5) as response:
            require(
                json.load(response).get("version") == api.tag[1:],
                "COHORT_FORWARD_API_VERSION_MISMATCH",
            )
        _verification_substep(self, "web_http")
        with urlopen("http://127.0.0.1:5173/", timeout=5) as response:
            require(response.status == 200, "COHORT_FORWARD_WEB_UNAVAILABLE")
        _verification_substep(self, "budget")
        check_budget()
        return {
            "continuous_identity": "matched",
            "intake": intake,
            "calculation_ready": False,
            "natural_acceptance": "pending",
        }

    def forward_calendars(self, source, check_budget):
        new = registry(source["new"])
        for name in CALENDARS:
            self._fixed(source, check_budget)
            self.recovery_window()
            check_budget()
            binding = new.services[name]
            if binding.enabled:
                self.start_calendar(binding)
            else:
                self.launch("disable", f"gui/{os.getuid()}/{binding.label}")
            check_budget()
        from app.services.deployment_identity import deployment_identity_health

        api = new.services["api"]
        identity = deployment_identity_health(root=Path(api.root), commit=api.commit)
        require(
            len(identity.get("services", {})) == len(new.services)
            and all(
                identity["services"]
                .get(IDENTITY_NAMES.get(name, name), {})
                .get("status")
                == ("matched" if binding.enabled else "disabled")
                for name, binding in new.services.items()
            ),
            "COHORT_FORWARD_IDENTITY_UNPROVEN",
        )
        check_budget()
        return {"calendar_registration_only": True, "identity": "matched"}


def main(argv=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Explicit exact-generation forward recovery; never a version promotion."
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    freeze = sub.add_parser("plan")
    freeze.add_argument("--source-plan", required=True, type=Path)
    freeze.add_argument("--output", required=True, type=Path)
    freeze.add_argument("--predecessor-recovery-plan", type=Path)
    apply = sub.add_parser("apply-plan")
    apply.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        host = ForwardRecoveryHost()
        if args.mode == "plan":
            plan = freeze_forward_recovery(
                host,
                args.source_plan,
                predecessor_recovery_plan=args.predecessor_recovery_plan,
            )
            parent = args.output.parent
            info = parent.lstat()
            require(
                parent.resolve() == parent
                and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid()
                and not info.st_mode & 0o022,
                "COHORT_FORWARD_OUTPUT_UNSAFE",
            )
            _exclusive_json(args.output, plan)
            result = {
                "status": "planned",
                "kind": KIND,
                "plan_sha256": plan["plan_sha256"],
            }
        else:
            result = apply_forward_recovery(host, args.plan)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, CohortError)
            and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", str(error))
            else "COHORT_FORWARD_OPERATION_FAILED"
        )
        print(json.dumps({"status": "blocked", "code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
