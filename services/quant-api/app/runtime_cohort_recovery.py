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
ORIGINAL_FEED_SOURCE = "original_cohort_verified_feed_halt_v1"
ORIGINAL_FEED_MODE = "original_verified_feed_halt_v1"

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
    for key, allowed in {
        "reason": {
            "owner_unavailable",
            "service_not_ready",
            "progress_pending",
            "http_unavailable",
            "reference_report_incomplete",
            "receiving_pair_pending",
            "calculation_pending",
            "calculation_unknown",
            "receiving_pair_expired",
            "receiving_cycle_stale",
        },
        "service": frozenset(CONTINUOUS),
        "report_stage": {
            "cycle",
            "receiving_cycle",
            "scan",
            "draining",
            "drained",
            "error",
        },
    }.items():
        if isinstance(value.get(key), str) and value[key] in allowed:
            result[key] = value[key]
    for key in ("pending_count", "unknown_count"):
        if type(value.get(key)) is int and 0 <= value[key] <= 2**63 - 1:
            result[key] = value[key]
    return result


def _verification_substep(host, name, *, before=None, current=None, **facts):
    diagnostic = {
        **{
            key: value
            for key, value in (_safe_verification_diagnostic(host) or {}).items()
            if key in VERIFICATION_TIMES
        },
        "substep": name,
        "observed_at": host.now().isoformat(),
    }
    for prefix, sample in (("before", before), ("current", current)):
        if isinstance(sample, dict):
            for key in ("sampled_at", "owner_cycle_at"):
                diagnostic[prefix + "_" + key] = sample.get(key)
    diagnostic.update(facts)
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
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _verify_historical_release(host, root, tag, commit):
    """Archived identities are only available to explicitly historical readers."""
    if root.is_dir():
        return host.verify_release(root, tag, commit)
    from app.core.env import PROJECT_ROOT
    from app.runtime_retirement import verify_historical_release

    return verify_historical_release(host.directory, PROJECT_ROOT, root, tag, commit)


def _predecessor(host, path, source_identity, *, historical=False):
    """Only the one immutable failed live-stop prefix; never an allow-unknown flag."""
    raw, frozen = _resolution_source(Path(path))
    _validate(
        frozen,
        datetime.fromisoformat(frozen["created_at"]),
        historical=True,
        history_directory=host.directory,
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
        == digest(
            asdict(
                registry(
                    original["new"], historical=True, history_directory=host.directory
                ).services["live"]
            )
        )
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
    _verify_historical_release(
        host, Path(controller["root"]), controller["tag"], controller["commit"]
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
    require(identity.get("kind") != ORIGINAL_FEED_SOURCE, "COHORT_FORWARD_PREDECESSOR_INVALID")
    raw, source = _resolution_source(Path(identity["plan_path"]))
    validate_cohort(
        source,
        datetime.fromisoformat(source["created_at"]),
        historical=True,
        history_directory=host.directory,
    )
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
    _validate(
        frozen,
        datetime.fromisoformat(frozen["created_at"]),
        historical=True,
        history_directory=host.directory,
    )
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
    generation = (
        registry(source["new"], historical=True, history_directory=host.directory)
        .services["live"]
        .generation
    )
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
    _verify_historical_release(
        host, Path(controller["root"]), controller["tag"], controller["commit"]
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
    if plan.get("mode") == "confirmed_intake_halt":
        return _feed_predecessor(host, path, identity)
    return (
        _intake_predecessor(host, path, identity)
        if plan.get("mode") == "confirmed_live_stop"
        else _predecessor(host, path, identity)
    )


def _valid_intake_result(value):
    try:
        return (
            set(value)
            == {
                "schema_version",
                "kind",
                "mode",
                "calculation_ready",
                "before_sha256",
                "after_sha256",
                "advanced_count",
                "remaining_count",
                "old_tail_reached",
            }
            and type(value["schema_version"]) is int
            and value["schema_version"] == 2
            and value["kind"] == "reference_receiving_liveness_v1"
            and value["calculation_ready"] is False
            and all(
                isinstance(value[k], str) and re.fullmatch(r"[0-9a-f]{64}", value[k])
                for k in ("before_sha256", "after_sha256")
            )
            and value["before_sha256"] != value["after_sha256"]
            and all(
                type(value[k]) is int and value[k] >= 0
                for k in ("advanced_count", "remaining_count")
            )
            and type(value["old_tail_reached"]) is bool
            and (
                (
                    value["mode"] == "durable_receiving_caught_up_idle"
                    and value["advanced_count"] == value["remaining_count"] == 0
                    and value["old_tail_reached"] is True
                )
                or (
                    value["advanced_count"] > 0
                    and (
                        (
                            value["mode"] == "durable_receiving"
                            and value["old_tail_reached"] is True
                            and value["remaining_count"] == 0
                        )
                        or (
                            value["mode"] == "durable_receiving_backlog_liveness"
                            and value["old_tail_reached"] is False
                            and value["remaining_count"] > 0
                        )
                    )
                )
            )
        )
    except (KeyError, TypeError):
        return False


def _feed_predecessor(host, path, identity):
    """Exactly A -> B -> C, where C started Feed and failed before verified completed."""
    raw, frozen = _resolution_source(Path(path))
    _validate(
        frozen,
        datetime.fromisoformat(frozen["created_at"]),
        historical=True,
        history_directory=host.directory,
    )
    source = _historical_source(host, identity)
    require(
        frozen.get("mode") == "confirmed_intake_halt"
        and frozen["source"] == identity
        and frozen["new"] == source["new"],
        "COHORT_FORWARD_PREDECESSOR_INVALID",
    )
    ancestor, previous = _intake_predecessor(
        host, frozen["predecessor"]["plan_path"], identity
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
    effects = state.get("effects", {})
    new = registry(source["new"], historical=True, history_directory=host.directory)
    require(
        private == frozen
        and state.get("schema_version") == 1
        and state.get("kind") == KIND
        and state.get("plan_sha256") == frozen["plan_sha256"]
        and state.get("source") == identity
        and state.get("phase") == "outcome_unknown"
        and state.get("failed_stage") == "verified"
        and set(effects) == {"consumers", "intake", "feed"}
        and effects["consumers"]
        == {"resumed_generation": new.services["live"].generation}
        and _valid_intake_result(effects["intake"])
        and effects["feed"]
        == {"bootstrapped": True, "label": new.services["market-feed"].label}
        and not os.path.lexists(attempt / "receipt.json"),
        "COHORT_FORWARD_PREDECESSOR_INVALID",
    )
    controller = frozen["audit"]["controller"]
    _verify_historical_release(
        host, Path(controller["root"]), controller["tag"], controller["commit"]
    )
    return {
        "plan_path": str(Path(path).resolve()),
        "plan_sha256": frozen["plan_sha256"],
        "plan_bytes_sha256": sha256(raw).hexdigest(),
        "private_plan_bytes_sha256": sha256(private_raw).hexdigest(),
        "state_bytes_sha256": sha256(state_raw).hexdigest(),
        "effects_sha256": digest(effects),
        "ancestor": ancestor,
        "feed_halt": True,
    }, frozen


def valid_confirmed_feed_halt(value, predecessor, audit):
    try:
        return (
            isinstance(predecessor, dict)
            and predecessor.get("feed_halt") is True
            and set(value)
            == {
                "predecessor_plan_sha256",
                "owners_sha256",
                "controls_sha256",
                "receiving_context",
                "feed_close_sha256",
                "all_consumers_parked",
                "current_tail_reached",
                "proof_sha256",
            }
            and value["predecessor_plan_sha256"] == predecessor["plan_sha256"]
            and value["owners_sha256"] == digest(audit["owners"])
            and value["controls_sha256"] == digest(audit["controls"])
            and value["receiving_context"] == audit["receiving_context"]
            and isinstance(value["receiving_context"], str)
            and re.fullmatch(r"[0-9a-f]{64}", value["receiving_context"]) is not None
            and value["feed_close_sha256"] == digest(audit["feed_close"])
            and value["all_consumers_parked"] is True
            and value["current_tail_reached"] is True
            and value["proof_sha256"]
            == digest({k: v for k, v in value.items() if k != "proof_sha256"})
        )
    except (KeyError, TypeError, ValueError):
        return False


def valid_original_verified_feed_halt(value, source, audit):
    try:
        return (
            source.get("kind") == ORIGINAL_FEED_SOURCE
            and set(value) == {
                "source_plan_sha256", "owners_sha256", "controls_sha256",
                "receiving_context", "feed_close_sha256",
                "all_consumers_parked", "current_tail_reached", "proof_sha256",
            }
            and value["source_plan_sha256"] == source["plan_sha256"]
            and value["owners_sha256"] == digest(audit["owners"])
            and value["controls_sha256"] == digest(audit["controls"])
            and value["receiving_context"] == audit["receiving_context"]
            and isinstance(value["receiving_context"], str)
            and re.fullmatch(r"[0-9a-f]{64}", value["receiving_context"]) is not None
            and value["feed_close_sha256"] == digest(audit["feed_close"])
            and value["all_consumers_parked"] is True
            and value["current_tail_reached"] is True
            and value["proof_sha256"]
            == digest({key: item for key, item in value.items() if key != "proof_sha256"})
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _valid_feed_close(proof, intent):
    try:
        at = datetime.fromisoformat(proof["observed_at"])
        return (
            set(proof)
            == {
                "kind",
                "intent_sha256",
                "observed_pids",
                "label_absent",
                "observed_pids_exited",
                "owner_lock_available",
                "frontiers_sha256",
                "observed_at",
            }
            and proof["kind"] == "feed_closed_v1"
            and intent["kind"] == "parked_feed_close_intent_v1"
            and proof["intent_sha256"] == digest(intent)
            and isinstance(proof["observed_pids"], list)
            and 1 <= len(proof["observed_pids"]) <= 64
            and all(
                type(p) is int and 1 < p <= 2**31 - 1 for p in proof["observed_pids"]
            )
            and proof["observed_pids"] == sorted(set(proof["observed_pids"]))
            and set(intent["observed_pids"]).issubset(proof["observed_pids"])
            and all(
                proof[k] is True
                for k in (
                    "label_absent",
                    "observed_pids_exited",
                    "owner_lock_available",
                )
            )
            and proof["frontiers_sha256"] == intent["frontiers_sha256"]
            and at.tzinfo is not None
            and at.utcoffset() is not None
        )
    except (KeyError, TypeError, ValueError):
        return False


def _unknown_feed_close(host, path, predecessor):
    """Only the recorded close-only identity-readback failure, never a new attempt."""
    raw, plan = _resolution_source(Path(path))
    _validate(
        plan,
        datetime.fromisoformat(plan["created_at"]),
        historical=True,
        history_directory=host.directory,
    )
    require(
        plan.get("mode") == "confirmed_feed_halt"
        and plan.get("stop_after") == "feed_close"
        and plan["predecessor"] == predecessor,
        "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
    )
    require(
        _feed_predecessor(host, predecessor["plan_path"], plan["source"])[0]
        == predecessor,
        "COHORT_FORWARD_PREDECESSOR_DRIFT",
    )
    controller = plan["audit"]["controller"]
    _verify_historical_release(
        host, Path(controller["root"]), controller["tag"], controller["commit"]
    )
    attempt = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"]
    _directory(attempt.parent)
    _directory(attempt)
    private_raw, private = _resolution_source(attempt / "plan.json")
    state_raw, state = _resolution_source(attempt / "state.json")
    effect = state.get("effects", {}).get("feed_stop", {})
    pids = effect.get("observed_pids")
    require(
        private == plan
        and state.get("schema_version") == 1
        and state.get("kind") == KIND
        and state.get("plan_sha256") == plan["plan_sha256"]
        and state.get("source") == plan["source"]
        and state.get("phase") == "outcome_unknown"
        and state.get("failed_stage") == "feed_stop_intent"
        and state.get("error_type") == "RuntimeIdentityError"
        and state.get("error_code") == "SERVICE_IDENTITY_INVALID"
        and set(state.get("effects", {})) == {"feed_stop"}
        and set(effect) == {"phase", "intent", "observed_pids"}
        and effect["phase"] in {"bootout_requested", "bootout_waiting"}
        and effect["intent"] == plan["audit"]["feed_close"]
        and isinstance(pids, list)
        and 1 <= len(pids) <= 64
        and all(type(p) is int and 1 < p <= 2**31 - 1 for p in pids)
        and pids == sorted(set(pids))
        and set(effect["intent"]["observed_pids"]).issubset(pids)
        and not os.path.lexists(attempt / "receipt.json"),
        "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
    )
    identity = {
        "plan_path": str(Path(path).resolve()),
        "plan_sha256": plan["plan_sha256"],
        "plan_bytes_sha256": sha256(raw).hexdigest(),
        "private_plan_bytes_sha256": sha256(private_raw).hexdigest(),
        "state_bytes_sha256": sha256(state_raw).hexdigest(),
    }
    return identity, plan, state, attempt


def _feed_close_attempt(host, path, predecessor):
    raw, plan = _resolution_source(Path(path))
    _validate(
        plan,
        datetime.fromisoformat(plan["created_at"]),
        historical=True,
        history_directory=host.directory,
    )
    require(
        plan.get("mode") == "confirmed_feed_halt"
        and plan.get("stop_after") == "feed_close"
        and plan["predecessor"] == predecessor,
        "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
    )
    selected, _previous = _feed_predecessor(
        host, predecessor["plan_path"], plan["source"]
    )
    require(selected == predecessor, "COHORT_FORWARD_PREDECESSOR_DRIFT")
    controller = plan["audit"]["controller"]
    _verify_historical_release(
        host, Path(controller["root"]), controller["tag"], controller["commit"]
    )
    attempt = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"]
    _directory(attempt.parent)
    _directory(attempt)
    private_raw, private = _resolution_source(attempt / "plan.json")
    state_raw, state = _resolution_source(attempt / "state.json")
    if state.get("phase") == "outcome_unknown":
        identity, _plan, original, _attempt = _unknown_feed_close(
            host, path, predecessor
        )
        confirmation_raw, confirmation = _resolution_source(
            attempt / "feed-close-confirmation.json"
        )
        controller = confirmation.get("controller", {})
        require(
            set(confirmation)
            == {
                "schema_version",
                "kind",
                "source_close_attempt",
                "controller",
                "feed_close",
                "recovery_started",
            }
            and confirmation.get("schema_version") == 1
            and confirmation.get("kind") == "feed_close_confirmation_v1"
            and confirmation.get("source_close_attempt") == identity
            and confirmation.get("recovery_started") is False
            and _valid_feed_close(
                confirmation.get("feed_close"), plan["audit"]["feed_close"]
            )
            and confirmation["feed_close"]["observed_pids"]
            == original["effects"]["feed_stop"]["observed_pids"],
            "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
        )
        _verify_historical_release(
            host, Path(controller["root"]), controller["tag"], controller["commit"]
        )
        return {
            **identity,
            "confirmation_bytes_sha256": sha256(confirmation_raw).hexdigest(),
        }, {
            "schema_version": 1,
            "kind": "feed_close_readback_v1",
            "source": plan["source"],
            "plan_sha256": plan["plan_sha256"],
            "feed_close": confirmation["feed_close"],
            "recovery_started": False,
            "original_attempt_preserved": True,
        }
    receipt_raw, receipt = _resolution_source(attempt / "receipt.json")
    require(
        private == plan
        and state.get("phase") == "feed_closed"
        and state.get("schema_version") == receipt.get("schema_version") == 1
        and state.get("kind") == KIND
        and state.get("plan_sha256") == plan["plan_sha256"]
        and state.get("source") == plan["source"]
        and state.get("receipt_sha256") == sha256(receipt_raw).hexdigest()
        and receipt.get("kind") == "feed_close_readback_v1"
        and receipt.get("plan_sha256") == plan["plan_sha256"]
        and receipt.get("source") == plan["source"]
        and receipt.get("recovery_started") is False
        and receipt.get("original_attempt_preserved") is True
        and set(state.get("effects", {})) == {"feed_stop"}
        and state["effects"]["feed_stop"] == receipt.get("feed_close")
        and _valid_feed_close(receipt.get("feed_close"), plan["audit"]["feed_close"]),
        "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
    )
    return {
        "plan_path": str(Path(path).resolve()),
        "plan_sha256": plan["plan_sha256"],
        "plan_bytes_sha256": sha256(raw).hexdigest(),
        "private_plan_bytes_sha256": sha256(private_raw).hexdigest(),
        "state_bytes_sha256": sha256(state_raw).hexdigest(),
        "receipt_bytes_sha256": sha256(receipt_raw).hexdigest(),
    }, receipt


def _original_feed_close_attempt(host, path, source_identity):
    """Only a terminal close receipt for this one original post-feed source."""
    raw, plan = _resolution_source(Path(path))
    _validate(
        plan, datetime.fromisoformat(plan["created_at"]), historical=True,
        history_directory=host.directory,
    )
    historical_source = _original_verified_feed_source(
        host, source_identity["plan_path"], historical=True,
    )[2]
    require(
        plan.get("mode") == ORIGINAL_FEED_MODE
        and plan.get("stop_after") == "feed_close"
        and plan.get("source") == historical_source == source_identity,
        "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
    )
    controller = plan["audit"]["controller"]
    _verify_historical_release(
        host, Path(controller["root"]), controller["tag"], controller["commit"]
    )
    attempt = host.directory / "cohort-forward-recoveries" / plan["plan_sha256"]
    _directory(attempt.parent)
    _directory(attempt)
    private_raw, private = _resolution_source(attempt / "plan.json")
    state_raw, state = _resolution_source(attempt / "state.json")
    receipt_raw, receipt = _resolution_source(attempt / "receipt.json")
    require(
        private == plan
        and state.get("phase") == "feed_closed"
        and state.get("schema_version") == receipt.get("schema_version") == 1
        and state.get("kind") == KIND
        and state.get("plan_sha256") == plan["plan_sha256"]
        and state.get("source") == source_identity
        and state.get("receipt_sha256") == sha256(receipt_raw).hexdigest()
        and receipt.get("kind") == "feed_close_readback_v1"
        and receipt.get("plan_sha256") == plan["plan_sha256"]
        and receipt.get("source") == source_identity
        and receipt.get("recovery_started") is False
        and receipt.get("original_attempt_preserved") is True
        and set(state.get("effects", {})) == {"feed_stop"}
        and state["effects"]["feed_stop"] == receipt.get("feed_close")
        and _valid_feed_close(receipt.get("feed_close"), plan["audit"]["feed_close"]),
        "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
    )
    return {
        "plan_path": str(Path(path).resolve()),
        "plan_sha256": plan["plan_sha256"],
        "plan_bytes_sha256": sha256(raw).hexdigest(),
        "private_plan_bytes_sha256": sha256(private_raw).hexdigest(),
        "state_bytes_sha256": sha256(state_raw).hexdigest(),
        "receipt_bytes_sha256": sha256(receipt_raw).hexdigest(),
    }, receipt


def _closed_predecessors(host, entries):
    closed = set()
    if (host.directory / "release-retirements").exists():
        from app.core.env import PROJECT_ROOT
        from app.runtime_retirement import sealed_closed_attempts

        closed.update(sealed_closed_attempts(host.directory, PROJECT_ROOT, entries))
    for child, state in entries:
        if child.name in closed:
            continue
        if state.get("phase") != "recovered" or not state.get("receipt_sha256"):
            continue
        raw, receipt = _resolution_source(child / "receipt.json")
        require(
            sha256(raw).hexdigest() == state["receipt_sha256"],
            "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
        )
        original_resolution = receipt.get("original_feed_halt_resolution")
        if original_resolution is not None:
            _raw, plan = _resolution_source(child / "plan.json")
            _validate(
                plan, datetime.fromisoformat(plan["created_at"]),
                historical=True, history_directory=host.directory,
            )
            source_identity = _original_verified_feed_source(
                host, plan["source"]["plan_path"], historical=True,
            )[2]
            require(
                plan.get("mode") == ORIGINAL_FEED_MODE
                and "stop_after" not in plan
                and set(original_resolution)
                == {"kind", "source", "feed_close", "confirmation"}
                and original_resolution["kind"]
                == "original_cohort_verified_feed_halt_resolution_v1"
                and receipt.get("source") == state.get("source")
                == plan["source"] == source_identity
                and receipt.get("plan_sha256") == state.get("plan_sha256")
                == plan["plan_sha256"] == child.name
                and original_resolution["source"] == source_identity
                and original_resolution["feed_close"] == plan["original_close"]
                and original_resolution["confirmation"]
                == plan["audit"]["original_verified_feed_halt"]
                and valid_original_verified_feed_halt(
                    original_resolution["confirmation"], source_identity,
                    plan["audit"],
                ),
                "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
            )
            closure, _receipt = _original_feed_close_attempt(
                host, plan["original_close"]["plan_path"], source_identity,
            )
            require(
                closure == plan["original_close"],
                "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
            )
            closed.add(closure["plan_sha256"])
            continue
        resolution = receipt.get("predecessor_resolution")
        if receipt.get("stopped_resolution") is not None:
            from app.runtime_stopped_recovery import read_confirmation, valid_plan

            _raw, stopped_plan = _resolution_source(child / "plan.json")
            _validate(
                stopped_plan,
                datetime.fromisoformat(stopped_plan["created_at"]),
                historical=True,
                history_directory=host.directory,
            )
            require(
                valid_plan(stopped_plan)
                and receipt["stopped_resolution"]
                == stopped_plan["stopped_confirmation"]
                and receipt.get("source")
                == state.get("source")
                == stopped_plan["source"]
                and receipt.get("plan_sha256")
                == state.get("plan_sha256")
                == child.name
                == stopped_plan["plan_sha256"],
                "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
            )
            confirmation = read_confirmation(host, receipt["stopped_resolution"])
            require(
                confirmation["source"] == stopped_plan["source"],
                "COHORT_FORWARD_SOURCE_DRIFT",
            )
            closed.update(confirmation["attempts"])
            continue
        if resolution is None:
            continue
        _raw, plan = _resolution_source(child / "plan.json")
        predecessor = resolution.get("predecessor")
        if plan.get("mode") == "confirmed_feed_halt":
            _validate(
                plan,
                datetime.fromisoformat(plan["created_at"]),
                historical=True,
                history_directory=host.directory,
            )
            require(
                "stop_after" not in plan
                and plan.get("predecessor") == predecessor
                and resolution.get("kind") == "confirmed_feed_halt_resolution_v1"
                and resolution.get("successor_plan_sha256")
                == child.name
                == plan["plan_sha256"]
                == receipt.get("plan_sha256")
                == state.get("plan_sha256")
                and receipt.get("source") == state.get("source") == plan["source"]
                and resolution.get("confirmation")
                == plan["audit"].get("confirmed_feed_halt")
                and valid_confirmed_feed_halt(
                    resolution["confirmation"], predecessor, plan["audit"]
                ),
                "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
            )
            selected, _previous = _feed_predecessor(
                host, predecessor["plan_path"], plan["source"]
            )
            closure, _receipt = _feed_close_attempt(
                host, plan["audit"]["feed_close"]["attempt"]["plan_path"], selected
            )
            require(
                selected == predecessor
                and closure == plan["audit"]["feed_close"]["attempt"],
                "COHORT_FORWARD_PREDECESSOR_DRIFT",
            )
            closed.update(
                item["plan_sha256"] for item in _permitted_predecessors(selected)
            )
            continue
        if plan.get("mode") == "confirmed_intake_halt":
            _validate(
                plan,
                datetime.fromisoformat(plan["created_at"]),
                historical=True,
                history_directory=host.directory,
            )
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


def _permitted_predecessors(predecessor):
    if predecessor is None:
        return []
    if predecessor.get("feed_halt") is True:
        return [
            predecessor,
            predecessor["ancestor"],
            predecessor["ancestor"]["ancestor"],
        ]
    return (
        [predecessor, predecessor["ancestor"]]
        if "ancestor" in predecessor
        else [predecessor]
    )


def _no_unresolved_recovery(
    host, predecessor=None, *, pending_feed_close=None, stopped=None,
    original_close=None, original_source=None,
):
    if stopped is not None:
        from app.runtime_stopped_recovery import verify_pin

        verify_pin(host, stopped)
        return
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
        if child.name in closed:
            continue
        if original_close is not None and child.name == original_close["plan_sha256"]:
            require(
                original_source is not None
                and _original_feed_close_attempt(
                    host, original_close["plan_path"], original_source,
                )[0] == original_close,
                "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
            )
            continue
        if (
            pending_feed_close is not None
            and child.name == pending_feed_close["plan_sha256"]
        ):
            require(
                predecessor is not None
                and predecessor.get("feed_halt") is True
                and _unknown_feed_close(
                    host, pending_feed_close["plan_path"], predecessor
                )[0]
                == pending_feed_close,
                "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
            )
            continue
        confirmation_path = child / "feed-close-confirmation.json"
        if state.get("phase") == "feed_closed" or os.path.lexists(confirmation_path):
            _raw, plan = _resolution_source(child / "plan.json")
            selected = plan.get("predecessor", {})
            require(
                (selected == predecessor and selected.get("feed_halt") is True)
                or selected.get("plan_sha256") in closed,
                "COHORT_FORWARD_RECOVERY_READBACK_REQUIRED",
            )
            public = child / "plan.json"
            if state.get("phase") != "feed_closed":
                _raw, confirmation = _resolution_source(confirmation_path)
                public = Path(confirmation["source_close_attempt"]["plan_path"])
            require(
                _feed_close_attempt(host, public, selected)[0]["plan_sha256"]
                == child.name,
                "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
            )
            continue
        permitted = _permitted_predecessors(predecessor)
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


def valid_original_verified_feed_state(plan, state):
    """Pure, exact original-journal shape for recovery and retirement audit."""
    try:
        effects = state["effects"]
        return (
            type(plan) is dict and type(state) is dict
            and set(state) == {
                "schema_version", "plan_sha256", "phase", "effects",
                "failed_phase", "error_type",
            }
            and state["schema_version"] == 1
            and state["plan_sha256"] == plan["plan_sha256"]
            and state["phase"] == "outcome_unknown"
            and state["failed_phase"] == "verified"
            and state["error_type"] == "ReceivingLivenessError"
            and type(effects) is dict
            and set(effects) == {
                "prewarm", "calendars_off", "drain", "old_exited",
                "preserve", "install", "consumers", "consumers_ready",
                "feed", "bootout_requests",
            }
            and effects["consumers"] == {"started": "consumers"}
            and effects["feed"] == {"started": "market-feed"}
            and effects["old_exited"].get("old_pids_exited") is True
            and effects["old_exited"].get("bootout_requests")
            == effects["bootout_requests"]
            and effects["preserve"].get("history_retained") is True
            and set(effects["install"].get("installed", ()))
            == set(plan["new"]["services"])
            and set(effects["consumers_ready"])
            == set(CONTINUOUS) - {"market-feed"}
            and set(effects["drain"]) == {
                "feed_close", "owners", "progress",
                "reference_receiving_handover",
            }
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _original_verified_feed_source(host, path, *, historical=False):
    """A single original verified-phase halt, with every consumed byte pinned."""
    path = Path(path)
    raw, plan = _resolution_source(path)
    try:
        created = datetime.fromisoformat(plan["created_at"])
        require(created <= host.now(), "COHORT_FORWARD_SOURCE_INVALID")
        _old, new = validate_cohort(
            plan, created, historical=True, history_directory=host.directory,
        )
        if not historical:
            require(host.bindings() == new, "COHORT_FORWARD_REGISTRY_DRIFT")
        attempt = host.directory / "cohort-attempts" / plan["plan_sha256"]
        for directory in (attempt.parent, attempt):
            _directory(directory)
        private_raw, private = _resolution_source(attempt / "plan.json")
        attempt_raw, state = _resolution_source(attempt / "state.json")
        global_raw, global_state = (
            (attempt_raw, state) if historical else _resolution_source(
                host.directory / "cohort-release.json"
            )
        )
        require(
            private == plan and global_state == state
            and global_raw == attempt_raw
            and valid_original_verified_feed_state(plan, state),
            "COHORT_FORWARD_SOURCE_INVALID",
        )
        effects = state["effects"]
        identity = {
            "kind": ORIGINAL_FEED_SOURCE,
            "plan_path": str(path.resolve()),
            "plan_sha256": plan["plan_sha256"],
            "plan_bytes_sha256": sha256(raw).hexdigest(),
            "private_plan_bytes_sha256": sha256(private_raw).hexdigest(),
            "attempt_bytes_sha256": sha256(attempt_raw).hexdigest(),
            "global_bytes_sha256": sha256(global_raw).hexdigest(),
            "effects_sha256": digest(effects),
        }
        return plan, state, identity
    except CohortError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise CohortError("COHORT_FORWARD_SOURCE_INVALID") from None


def _source(host, path, *, allow_original=False):
    if allow_original:
        return _original_verified_feed_source(host, path)
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


def _validate(plan, now, *, historical=False, history_directory=None, history_verifier=None):
    from app.runtime_stopped_recovery import valid_plan as valid_stopped_plan

    try:
        require(
            ("stopped_confirmation" in plan)
            == (plan.get("mode") == "reconciled_stopped"),
            "COHORT_FORWARD_PLAN_INVALID",
        )
        require(
            set(plan) - {"mode", "predecessor", "stop_after", "stopped_confirmation", "original_close"}
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
            (
                "mode" not in plan
                and "predecessor" not in plan
                and "stopped_confirmation" not in plan
            )
            or (plan.get("mode") == "reconciled_stopped" and valid_stopped_plan(plan))
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
            )
            or (
                plan.get("mode") == "confirmed_feed_halt"
                and "live_restart_intent" not in plan["audit"]
                and valid_confirmed_feed_halt(
                    plan["audit"].get("confirmed_feed_halt"),
                    plan.get("predecessor"),
                    plan["audit"],
                )
                and (
                    (
                        plan.get("stop_after") == "feed_close"
                        and plan["audit"]["feed_close"].get("kind")
                        == "parked_feed_close_intent_v1"
                    )
                    or (
                        "stop_after" not in plan
                        and plan["audit"]["feed_close"].get("kind")
                        == "feed_close_readback_v1"
                    )
                )
            )
            or (
                plan.get("mode") == ORIGINAL_FEED_MODE
                and "predecessor" not in plan
                and "stopped_confirmation" not in plan
                and "live_restart_intent" not in plan["audit"]
                and valid_original_verified_feed_halt(
                    plan["audit"].get("original_verified_feed_halt"),
                    plan.get("source"), plan["audit"],
                )
                and (
                    (plan.get("stop_after") == "feed_close"
                     and "original_close" not in plan
                     and plan["audit"]["feed_close"].get("kind")
                     == "parked_feed_close_intent_v1")
                    or ("stop_after" not in plan
                        and isinstance(plan.get("original_close"), dict)
                        and plan["audit"]["feed_close"].get("kind")
                        == "feed_close_readback_v1")
                )
            ),
            "COHORT_FORWARD_PLAN_INVALID",
        )
        require(
            "stop_after" not in plan
            or (
                plan.get("mode") in {"confirmed_feed_halt", ORIGINAL_FEED_MODE}
                and plan["stop_after"] == "feed_close"
            ),
            "COHORT_FORWARD_PLAN_INVALID",
        )
        require(
            (isinstance(plan.get("source"), dict)
             and plan["source"].get("kind") == ORIGINAL_FEED_SOURCE)
            == (plan.get("mode") == ORIGINAL_FEED_MODE)
            and ("original_close" not in plan
                 or plan.get("mode") == ORIGINAL_FEED_MODE),
            "COHORT_FORWARD_PLAN_INVALID",
        )
        registry(
            plan["new"], historical=historical, history_directory=history_directory,
            history_verifier=history_verifier,
        )
    except (TypeError, KeyError, OverflowError):
        raise CohortError("COHORT_FORWARD_PLAN_INVALID") from None


def freeze_forward_recovery(
    host,
    source_plan_path,
    *,
    predecessor_recovery_plan=None,
    close_feed_only=False,
    feed_close_plan=None,
    stopped_confirmation=None,
    original_verified_feed_halt=False,
):
    """Read-only new intent; the historical plan's elapsed budget is never reused."""
    if stopped_confirmation is not None:
        require(
            predecessor_recovery_plan is None
            and not close_feed_only
            and feed_close_plan is None
            and not original_verified_feed_halt,
            "COHORT_FORWARD_PLAN_INVALID",
        )
        from app.runtime_stopped_recovery import freeze_stopped

        return freeze_stopped(host, source_plan_path, stopped_confirmation)
    require(type(original_verified_feed_halt) is bool, "COHORT_FORWARD_PLAN_INVALID")
    if original_verified_feed_halt:
        require(
            predecessor_recovery_plan is None
            and type(close_feed_only) is bool
            and (close_feed_only != (feed_close_plan is not None)),
            "COHORT_FORWARD_PLAN_INVALID",
        )
    source, _state, identity = _source(
        host, source_plan_path, allow_original=original_verified_feed_halt,
    )
    original_close = (
        _original_feed_close_attempt(host, feed_close_plan, identity)[0]
        if original_verified_feed_halt and feed_close_plan is not None
        else None
    )
    predecessor = (
        _load_selected_predecessor(host, predecessor_recovery_plan, identity)[0]
        if predecessor_recovery_plan is not None
        else None
    )
    _no_unresolved_recovery(
        host, predecessor, original_close=original_close,
        original_source=identity if original_verified_feed_halt else None,
    )
    require(
        type(close_feed_only) is bool
        and (not close_feed_only or feed_close_plan is None)
        and (
            original_verified_feed_halt
            or
            not close_feed_only
            and feed_close_plan is None
            or predecessor is not None
            and predecessor.get("feed_halt") is True
        ),
        "COHORT_FORWARD_PLAN_INVALID",
    )
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

    kwargs = {"predecessor": predecessor}
    if original_verified_feed_halt:
        kwargs.update(
            original_identity=identity,
            close_feed_only=close_feed_only,
            feed_close_plan=feed_close_plan,
        )
    if predecessor is not None and predecessor.get("feed_halt") is True:
        kwargs.update(close_feed_only=close_feed_only, feed_close_plan=feed_close_plan)
    audit = host.audit_forward(source, budget, **kwargs)
    budget()
    require(
        _source(host, source_plan_path, allow_original=original_verified_feed_halt)[2]
        == identity, "COHORT_FORWARD_SOURCE_DRIFT"
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
            mode="confirmed_feed_halt"
            if predecessor.get("feed_halt") is True
            else "confirmed_intake_halt"
            if "ancestor" in predecessor
            else "confirmed_live_stop",
            predecessor=predecessor,
        )
    if original_verified_feed_halt:
        result["mode"] = ORIGINAL_FEED_MODE
        if original_close is not None:
            require(
                _original_feed_close_attempt(
                    host, original_close["plan_path"], identity,
                )[0] == original_close,
                "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
            )
            result["original_close"] = original_close
    if close_feed_only:
        result["stop_after"] = "feed_close"
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


def confirm_unknown_feed_close(host, path):
    """Fresh read-only closure proof; preserve the consumed unknown and never launch."""
    raw, plan = _resolution_source(Path(path))
    _validate(
        plan, datetime.fromisoformat(plan["created_at"])
    )  # Historical audit, not execution.
    predecessor = _feed_predecessor(
        host, plan["predecessor"]["plan_path"], plan["source"]
    )[0]
    with deployment_lock(runtime_dir=host.directory), host.forward_guards(plan):
        identity, plan, state, attempt = _unknown_feed_close(host, path, predecessor)
        _no_unresolved_recovery(host, predecessor, pending_feed_close=identity)
        source, _original, source_identity = _source(host, plan["source"]["plan_path"])
        require(source_identity == plan["source"], "COHORT_FORWARD_SOURCE_DRIFT")
        controller = host._controller()
        end = getattr(host, "monotonic", monotonic)() + 120

        def budget():
            require(
                getattr(host, "monotonic", monotonic)() < end,
                "COHORT_FORWARD_DEADLINE_EXCEEDED",
            )

        proof = host.confirm_feed_close_unknown(source, plan, state, budget)
        require(
            _valid_feed_close(proof, plan["audit"]["feed_close"])
            and proof["observed_pids"]
            == state["effects"]["feed_stop"]["observed_pids"],
            "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
        )
        require(
            _unknown_feed_close(host, path, predecessor)[0] == identity
            and _source(host, plan["source"]["plan_path"])[2] == source_identity
            and host._controller() == controller,
            "COHORT_FORWARD_FEED_CLOSE_DRIFT",
        )
        budget()
        target = attempt / "feed-close-confirmation.json"
        if os.path.lexists(target):
            descriptor, _receipt = _feed_close_attempt(host, path, predecessor)
            fingerprint = descriptor["confirmation_bytes_sha256"]
        else:
            fingerprint = _exclusive_json(
                target,
                {
                    "schema_version": 1,
                    "kind": "feed_close_confirmation_v1",
                    "source_close_attempt": identity,
                    "controller": controller,
                    "feed_close": proof,
                    "recovery_started": False,
                },
            )
        require(
            _unknown_feed_close(host, path, predecessor)[0] == identity,
            "COHORT_FORWARD_FEED_CLOSE_DRIFT",
        )
        return {
            "status": "feed_closed_confirmed",
            "confirmation_sha256": fingerprint,
            "original_attempt_preserved": True,
            "recovery_started": False,
        }


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
        original_halt = plan.get("mode") == ORIGINAL_FEED_MODE
        source, _state, identity = _source(
            host, plan["source"]["plan_path"], allow_original=original_halt,
        )
        predecessor = None
        if plan.get("mode") in {
            "confirmed_live_stop",
            "confirmed_intake_halt",
            "confirmed_feed_halt",
        }:
            predecessor = _load_selected_predecessor(
                host, plan["predecessor"]["plan_path"], identity
            )[0]
            require(
                predecessor == plan["predecessor"], "COHORT_FORWARD_PREDECESSOR_DRIFT"
            )
        original_close = plan.get("original_close") if original_halt else None
        if original_close is not None:
            require(
                _original_feed_close_attempt(
                    host, original_close["plan_path"], identity,
                )[0] == original_close,
                "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
            )
        _no_unresolved_recovery(
            host, predecessor, stopped=plan.get("stopped_confirmation"),
            original_close=original_close,
            original_source=identity if original_halt else None,
        )
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
            if plan.get("mode") == "reconciled_stopped":
                from app.runtime_stopped_recovery import verify_pin

                verify_pin(host, plan["stopped_confirmation"], own=plan["plan_sha256"])
            require(
                host._controller() == plan["audit"]["controller"],
                "COHORT_FORWARD_CONTROLLER_DRIFT",
            )
            require(
                _source(
                    host, plan["source"]["plan_path"],
                    allow_original=original_halt,
                )[2] == identity,
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
            if plan.get("mode") == "confirmed_feed_halt" and "stop_after" not in plan:
                frozen_close = plan["audit"]["feed_close"]["attempt"]
                require(
                    _feed_close_attempt(host, frozen_close["plan_path"], predecessor)[0]
                    == frozen_close,
                    "COHORT_FORWARD_FEED_CLOSE_DRIFT",
                )
            if original_close is not None:
                require(
                    _original_feed_close_attempt(
                        host, original_close["plan_path"], identity,
                    )[0] == original_close,
                    "COHORT_FORWARD_FEED_CLOSE_DRIFT",
                )
            host.check_protected_forward(source, plan["audit"])
            budget()

        with host.forward_guards(source):
            kwargs = {"expected": plan["audit"], "predecessor": predecessor}
            if original_halt:
                kwargs.update(
                    original_identity=identity,
                    close_feed_only=plan.get("stop_after") == "feed_close",
                    feed_close_plan=(
                        original_close["plan_path"]
                        if original_close is not None else None
                    ),
                )
            if plan.get("mode") == "confirmed_feed_halt":
                kwargs.update(
                    close_feed_only=plan.get("stop_after") == "feed_close",
                    feed_close_plan=(
                        plan["audit"]["feed_close"]["attempt"]["plan_path"]
                        if "stop_after" not in plan
                        else None
                    ),
                )
            if plan.get("mode") == "reconciled_stopped":
                from app.runtime_stopped_recovery import audit_for_plan

                audit = audit_for_plan(
                    host, source, plan["stopped_confirmation"], budget
                )
            else:
                audit = host.audit_forward(source, budget, **kwargs)
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
                if name in {"intake", "verified"}:
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

            if plan.get("stop_after") == "feed_close":

                def record_feed_stop(value):
                    journal["effects"]["feed_stop"] = value
                    persist("feed_stop_intent")

                proof = step(
                    "feed_stop",
                    lambda: host.stop_parked_feed(
                        source, plan["audit"], budget, record_feed_stop
                    ),
                )
                require(
                    _valid_feed_close(proof, plan["audit"]["feed_close"]),
                    "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
                )
                receipt = {
                    "schema_version": 1,
                    "kind": "feed_close_readback_v1",
                    "plan_sha256": plan["plan_sha256"],
                    "source": identity,
                    "feed_close": proof,
                    "original_attempt_preserved": True,
                    "recovery_started": False,
                }
                journal["receipt_sha256"] = _exclusive_json(
                    attempt / "receipt.json", receipt
                )
                unchanged()
                persist("feed_closed")
                return {
                    "status": "feed_closed",
                    "receipt_sha256": journal["receipt_sha256"],
                    "recovery_started": False,
                    "original_attempt_preserved": True,
                }

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
            if plan.get("mode") == "reconciled_stopped":
                receipt["stopped_resolution"] = plan["stopped_confirmation"]
            if predecessor is not None:
                receipt["predecessor_resolution"] = {
                    "kind": "confirmed_feed_halt_resolution_v1"
                    if predecessor.get("feed_halt") is True
                    else "confirmed_intake_halt_resolution_v1"
                    if "ancestor" in predecessor
                    else "confirmed_live_stop_resolution_v1",
                    "predecessor": predecessor,
                    "successor_plan_sha256": plan["plan_sha256"],
                    "confirmation": plan["audit"][
                        "confirmed_feed_halt"
                        if predecessor.get("feed_halt") is True
                        else "confirmed_intake_halt"
                        if "ancestor" in predecessor
                        else "confirmed_live_stop"
                    ],
                }
            if original_halt:
                receipt["original_feed_halt_resolution"] = {
                    "kind": "original_cohort_verified_feed_halt_resolution_v1",
                    "source": identity,
                    "feed_close": original_close,
                    "confirmation": plan["audit"]["original_verified_feed_halt"],
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
            if original_halt:
                result["original_feed_halt_resolution"] = {
                    "source_plan_sha256": identity["plan_sha256"],
                    "feed_close_plan_sha256": original_close["plan_sha256"],
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
            if stage in {"intake", "verified"}:
                diagnostic = _safe_verification_diagnostic(host)
                if diagnostic is not None:
                    journal[stage + "_diagnostic"] = diagnostic
            try:
                persist("outcome_unknown" if mutated else "precondition_blocked")
            finally:
                if mutated and plan.get("stop_after") != "feed_close":
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

    def audit_stopped(self, source, budget, *, feed_pids):
        from app.runtime_stopped_recovery import observe_stopped

        return observe_stopped(self, source, budget, feed_pids=feed_pids)

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
        self,
        source,
        *,
        held=False,
        allow_live_restart=False,
        live_absent=False,
        feed_parked=False,
    ):
        new = registry(source["new"])
        result = {}
        for name in CONTINUOUS:
            binding = new.services[name]
            if name == "market-feed" and not feed_parked:
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
        _verification_substep(
            self,
            "calculation_boundary",
            pending_count=pending,
            unknown_count=unknown,
            reason="calculation_unknown"
            if unknown
            else "calculation_pending"
            if pending
            else "receiving_pair_pending",
        )
        require(
            unknown == 0 and (active or pending == 0),
            "COHORT_FORWARD_CALCULATION_UNKNOWN",
        )
        return pending == 0

    def _snapshot(self, source, check_budget, *, state=None):
        from app.reference_trading.receiving_liveness import (
            snapshot_receiving,
            ReceivingLivenessError,
            ReceivingCycleStale,
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
        except ReceivingCycleStale:
            raise
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

    def audit_forward(
        self,
        source,
        check_budget,
        *,
        expected=None,
        predecessor=None,
        close_feed_only=False,
        feed_close_plan=None,
        original_identity=None,
    ):
        from app.reference_trading.receiving_liveness import receiving_snapshot_identity

        original_halt = original_identity is not None
        require(
            not original_halt or (
                predecessor is None
                and original_identity.get("kind") == ORIGINAL_FEED_SOURCE
                and original_identity.get("plan_sha256") == source["plan_sha256"]
                and (close_feed_only != (feed_close_plan is not None))
            ),
            "COHORT_FORWARD_SOURCE_INVALID",
        )
        feed_halt = (predecessor is not None and predecessor.get("feed_halt") is True) or original_halt
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
            allow_live_restart=predecessor is None and not original_halt,
            live_absent=predecessor is not None and not intake_halt,
            **({"feed_parked": True} if feed_halt and close_feed_only else {}),
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
        if original_halt:
            from app.reference_trading.receiving_liveness import receiving_context_identity

            require(
                snapshot["old_tail_reached"] is True
                and all(row["ack"] == row["current_tail"] == row["final_tail"]
                        for row in snapshot["days"].values()),
                "COHORT_FORWARD_LEGACY_FRONTIER_UNPROVEN",
            )
            context = receiving_context_identity(snapshot)
            if close_feed_only:
                feed_close = self.feed_close_intent(source, check_budget)
            else:
                closure, receipt = _original_feed_close_attempt(
                    self, feed_close_plan, original_identity,
                )
                feed_close = {
                    "kind": "feed_close_readback_v1",
                    "attempt": closure,
                    "proof": self.confirm_feed_closed(
                        source, receipt["feed_close"], check_budget, feed_close_plan,
                    ),
                }
            proof = {
                "source_plan_sha256": original_identity["plan_sha256"],
                "owners_sha256": digest(owners),
                "controls_sha256": digest(controls),
                "receiving_context": context,
                "feed_close_sha256": digest(feed_close),
                "all_consumers_parked": True,
                "current_tail_reached": True,
            }
            proof["proof_sha256"] = digest(proof)
            additional = {
                "receiving_context": context,
                "feed_close": feed_close,
                "original_verified_feed_halt": proof,
            }
        if intake_halt:
            from app.reference_trading.receiving_liveness import (
                receiving_context_identity,
            )

            _raw, selected_plan = _resolution_source(Path(predecessor["plan_path"]))
            identity = _source(self, selected_plan["source"]["plan_path"])[2]
            fresh, previous = (_feed_predecessor if feed_halt else _intake_predecessor)(
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
            if feed_halt:
                require(
                    close_feed_only or feed_close_plan is not None,
                    "COHORT_FORWARD_FEED_CLOSE_UNPROVEN",
                )
                if close_feed_only:
                    feed_close = self.feed_close_intent(source, check_budget)
                else:
                    closure, receipt = _feed_close_attempt(
                        self, feed_close_plan, predecessor
                    )
                    feed_close = {
                        "kind": "feed_close_readback_v1",
                        "attempt": closure,
                        "proof": self.confirm_feed_closed(
                            source, receipt["feed_close"], check_budget, feed_close_plan
                        ),
                    }
                proof = {
                    "predecessor_plan_sha256": predecessor["plan_sha256"],
                    "owners_sha256": digest(owners),
                    "controls_sha256": digest(controls),
                    "receiving_context": context,
                    "feed_close_sha256": digest(feed_close),
                    "all_consumers_parked": True,
                    "current_tail_reached": True,
                }
                proof["proof_sha256"] = digest(proof)
                additional = {
                    "receiving_context": context,
                    "feed_close": feed_close,
                    "confirmed_feed_halt": proof,
                }
            else:
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
                additional = {
                    "receiving_context": context,
                    "confirmed_intake_halt": proof,
                }
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

    def _feed_frontiers(self, source, check_budget):
        """Hash every retained source original/index plus fully DB-verified completed input."""
        from app.redis_connections import get_redis_connection
        from app.market_data.observation_stream import ObservationStream, DAILY_LIMIT
        from app.reference_trading.receiving_liveness import receiving_snapshot_identity

        client = get_redis_connection()
        try:
            journal = ObservationStream(client, kind="source")
            days = journal.days()
            require(
                journal.registered_day("live") in days and len(days) <= 32,
                "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN",
            )
            result = {}
            for day in days:
                cursor, tail = journal.cursor("live", day), journal.tail(day)
                require(cursor == tail, "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN")
                frontier, seen, content_hash = "0-0", {}, sha256()
                while frontier != tail:
                    check_budget()
                    rows = journal.read(
                        "live", day, count=512, after=frontier, through=tail
                    )
                    require(bool(rows), "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN")
                    for event in rows:
                        raw = event.to_json()
                        content = json.loads(raw)
                        content.pop("source_observed_at")
                        content.pop("raw_received_at")
                        fingerprint = json.dumps(
                            content,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                        require(
                            event.observation_id not in seen
                            and len(seen) < DAILY_LIMIT,
                            "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN",
                        )
                        seen[event.observation_id] = (event.stream_id, raw, fingerprint)
                        content_hash.update(
                            json.dumps(
                                [event.stream_id, event.observation_id, raw],
                                separators=(",", ":"),
                            ).encode()
                            + b"\n"
                        )
                        frontier = event.stream_id
                indexed = set()
                require(
                    client.hlen(journal.identity_key(day)) == len(seen),
                    "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN",
                )
                for index, (key, raw) in enumerate(
                    client.hscan_iter(journal.identity_key(day), count=512)
                ):
                    if index % 512 == 0:
                        check_budget()
                    key = key.decode() if isinstance(key, bytes) else key
                    value = json.loads(raw)
                    require(
                        key in seen
                        and key not in indexed
                        and (
                            value.get("id"),
                            value.get("payload"),
                            value.get("content"),
                        )
                        == seen[key],
                        "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN",
                    )
                    indexed.add(key)
                require(
                    indexed == set(seen)
                    and journal.tail(day) == tail
                    and journal.cursor("live", day) == cursor,
                    "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN",
                )
                result[day.isoformat()] = {
                    "cursor": cursor,
                    "tail": tail,
                    "count": len(seen),
                    "sha256": content_hash.hexdigest(),
                }
            require(journal.days() == days, "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN")
            snapshot = self._snapshot(source, check_budget)
            require(
                all(
                    v["ack"] == v["current_tail"] == v["final_tail"]
                    for v in snapshot["days"].values()
                ),
                "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN",
            )
            return {
                "source": result,
                "completed_sha256": receiving_snapshot_identity(snapshot),
            }
        finally:
            client.close()

    def _feed_pids(self, source):
        binding = registry(source["new"]).services["market-feed"]
        owner = read_service_state("market-feed", runtime_dir=self.directory)
        loaded = self.loaded(binding)
        require(
            owner
            and owner.get("phase") == "parked"
            and owner.get("generation") == binding.generation
            and type(owner.get("pid")) is int
            and str(owner["pid"]) == str(loaded)
            and owner_process_matches(owner, binding),
            "COHORT_FORWARD_FEED_OWNER_UNPROVEN",
        )
        return self._observed_feed_pids(source, [owner["pid"]])

    def _observed_feed_pids(self, source, previous):
        from app.runtime_identity import read_command

        binding = registry(source["new"]).services["market-feed"]
        loaded = self._shutdown_feed_pid(binding)
        parents = {}
        for line in read_command(
            ["/bin/ps", "-axo", "pid=,ppid="], root=Path(binding.root)
        ).splitlines():
            fields = line.split()
            require(
                len(fields) == 2 and all(v.isdigit() for v in fields),
                "COHORT_FORWARD_FEED_OWNER_UNPROVEN",
            )
            parents[int(fields[0])] = int(fields[1])
        pids = set(previous)
        if loaded is not None:
            require(
                str(loaded).isdigit() and 1 < int(loaded) <= 2**31 - 1,
                "COHORT_FORWARD_FEED_OWNER_UNPROVEN",
            )
            pids.add(int(loaded))
        while True:
            expanded = pids | {pid for pid, parent in parents.items() if parent in pids}
            require(len(expanded) <= 64, "COHORT_FORWARD_FEED_OWNER_UNPROVEN")
            if expanded == pids:
                return sorted(pids)
            pids = expanded

    def _shutdown_feed_pid(self, binding):
        """Observe PID during teardown, without treating a transient state as ready."""
        from app.runtime_identity import read_launchd_service, launchd_arguments
        from app.runtime_bindings import authorized_program_arguments

        output = read_launchd_service(binding.label, root=Path(binding.root))
        if output is None:
            return None
        scopes, headers, environment = [], {}, {}
        for raw in output.splitlines():
            line = raw.strip()
            if line.endswith((" = {", " => {")):
                name, operator, _brace = line.rsplit(" ", 2)
                require(scopes or operator == "=", "COHORT_FORWARD_FEED_OWNER_UNPROVEN")
                scopes.append((name, operator))
            elif line == "}":
                require(bool(scopes), "COHORT_FORWARD_FEED_OWNER_UNPROVEN")
                scopes.pop()
            elif len(scopes) == 1:
                match = re.fullmatch(r"(pid|working directory) = (.*)", line)
                if match:
                    require(
                        match[1] not in headers, "COHORT_FORWARD_FEED_OWNER_UNPROVEN"
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
                        "COHORT_FORWARD_FEED_OWNER_UNPROVEN",
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
            "COHORT_FORWARD_FEED_OWNER_UNPROVEN",
        )
        pid = headers.get("pid")
        require(
            pid is None or re.fullmatch(r"[1-9][0-9]{0,9}", pid),
            "COHORT_FORWARD_FEED_OWNER_UNPROVEN",
        )
        return pid

    def feed_close_intent(self, source, check_budget):
        with self._resume_owner_guards():
            owners = self._parked_owners(source, held=True, feed_parked=True)
            frontiers = self._feed_frontiers(source, check_budget)
            pids = self._feed_pids(source)
            require(
                self._feed_frontiers(source, check_budget) == frontiers,
                "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN",
            )
            return {
                "kind": "parked_feed_close_intent_v1",
                "observed_pids": pids,
                "binding_sha256": digest(
                    asdict(registry(source["new"]).services["market-feed"])
                ),
                "owners_sha256": digest(owners),
                "controls_sha256": digest(self._controls(source)),
                "frontiers_sha256": digest(frontiers),
            }

    def _feed_exited(self, source, pids, check_budget):
        binding = registry(source["new"]).services["market-feed"]
        absent = self.definition_absent(binding)
        exited = True
        for pid in pids:
            check_budget()
            try:
                os.kill(pid, 0)
                exited = False
            except ProcessLookupError:
                pass
            except OSError:
                raise CohortError("COHORT_FORWARD_FEED_EXIT_UNPROVEN") from None
        return absent and exited

    def confirm_feed_closed(self, source, proof, check_budget, close_plan):
        _raw, plan = _resolution_source(Path(close_plan))
        intent = plan["audit"]["feed_close"]
        require(_valid_feed_close(proof, intent), "COHORT_FORWARD_FEED_CLOSE_UNPROVEN")
        with self._resume_owner_guards():
            self._parked_owners(source, held=True)
            require(
                self._feed_exited(source, proof["observed_pids"], check_budget),
                "COHORT_FORWARD_FEED_EXIT_UNPROVEN",
            )
            first = self._feed_frontiers(source, check_budget)
            require(
                digest(first) == intent["frontiers_sha256"]
                and self._feed_frontiers(source, check_budget) == first,
                "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN",
            )
        require(
            owner_lock_available("market-feed", runtime_dir=self.directory),
            "COHORT_FORWARD_FEED_EXIT_UNPROVEN",
        )
        # Keep the immutable closure-event time; the OS/prefix checks above are
        # performed afresh on every audit, not inferred from this old timestamp.
        return proof

    def confirm_feed_close_unknown(self, source, plan, state, check_budget):
        """No launch path: certify this recorded request from fresh absence and full input."""
        self._expected_controller = self._controller()
        self._expected_new_protected = plan["audit"]["new_protected"]
        audit = plan["audit"]
        intent = audit["feed_close"]
        pids = state["effects"]["feed_stop"]["observed_pids"]
        require(
            digest(self._fixed(source, check_budget)) == audit["installed_sha256"]
            and self._controls(source) == audit["controls"],
            "COHORT_FORWARD_AUDIT_DRIFT",
        )
        self._old_exited(source)
        self._calculation_boundary()
        with self._resume_owner_guards():
            expected = dict(audit["owners"])
            expected["market-feed"] = {
                "phase": "absent",
                "generation": registry(source["new"])
                .services["market-feed"]
                .generation,
            }
            require(
                self._parked_owners(source, held=True) == expected
                and self._feed_exited(source, pids, check_budget),
                "COHORT_FORWARD_FEED_EXIT_UNPROVEN",
            )
            frontiers = self._feed_frontiers(source, check_budget)
            require(
                digest(frontiers) == intent["frontiers_sha256"]
                and self._feed_frontiers(source, check_budget) == frontiers,
                "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN",
            )
        require(
            owner_lock_available("market-feed", runtime_dir=self.directory)
            and self._feed_exited(source, pids, check_budget),
            "COHORT_FORWARD_FEED_EXIT_UNPROVEN",
        )
        self.check_protected_forward(source, audit)
        require(
            self._controls(source) == audit["controls"]
            and digest(self._fixed(source, check_budget)) == audit["installed_sha256"],
            "COHORT_FORWARD_AUDIT_DRIFT",
        )
        check_budget()
        return {
            "kind": "feed_closed_v1",
            "intent_sha256": digest(intent),
            "observed_pids": pids,
            "label_absent": True,
            "observed_pids_exited": True,
            "owner_lock_available": True,
            "frontiers_sha256": intent["frontiers_sha256"],
            "observed_at": self.now().isoformat(),
        }

    def stop_parked_feed(self, source, audit, check_budget, record):
        binding = registry(source["new"]).services["market-feed"]
        self._expected_controller = audit["controller"]
        intent = audit["feed_close"]
        with self.forward_guards(source):
            require(
                self.feed_close_intent(source, check_budget) == intent,
                "COHORT_FORWARD_FEED_INTENT_DRIFT",
            )
            with self._resume_owner_guards():
                require(
                    self._parked_owners(source, held=True, feed_parked=True)
                    == audit["owners"]
                    and self._controls(source) == audit["controls"]
                    and self._feed_pids(source) == intent["observed_pids"]
                    and digest(self._fixed(source, check_budget))
                    == audit["installed_sha256"],
                    "COHORT_FORWARD_AUDIT_DRIFT",
                )
                self.check_protected_forward(source, audit)
                check_budget()
                record(
                    {
                        "phase": "bootout_requested",
                        "intent": intent,
                        "observed_pids": intent["observed_pids"],
                    }
                )
                require(
                    self._feed_pids(source) == intent["observed_pids"]
                    and self._controls(source) == audit["controls"]
                    and self._controller() == audit["controller"],
                    "COHORT_FORWARD_FEED_INTENT_DRIFT",
                )
                self.check_protected_forward(source, audit)
                check_budget()
                self.launch("bootout", f"gui/{os.getuid()}/{binding.label}")
                end = self.monotonic() + 30
                pids = intent["observed_pids"]
                while True:
                    observed = self._observed_feed_pids(source, pids)
                    if observed != pids:
                        pids = observed
                        record(
                            {
                                "phase": "bootout_waiting",
                                "intent": intent,
                                "observed_pids": pids,
                            }
                        )
                    if self._feed_exited(source, pids, check_budget):
                        break
                    require(self.monotonic() < end, "COHORT_FORWARD_FEED_EXIT_UNPROVEN")
                    check_budget()
                    sleep(0.1)
                frontiers = self._feed_frontiers(source, check_budget)
                require(
                    digest(frontiers) == intent["frontiers_sha256"]
                    and self._feed_frontiers(source, check_budget) == frontiers
                    and self._controls(source) == audit["controls"]
                    and digest(self._fixed(source, check_budget))
                    == audit["installed_sha256"],
                    "COHORT_FORWARD_FEED_FRONTIER_UNPROVEN",
                )
                self._calculation_boundary()
            require(
                owner_lock_available("market-feed", runtime_dir=self.directory)
                and self._feed_exited(source, pids, check_budget),
                "COHORT_FORWARD_FEED_EXIT_UNPROVEN",
            )
            check_budget()
            return {
                "kind": "feed_closed_v1",
                "intent_sha256": digest(intent),
                "observed_pids": pids,
                "label_absent": True,
                "observed_pids_exited": True,
                "owner_lock_available": True,
                "frontiers_sha256": intent["frontiers_sha256"],
                "observed_at": self.now().isoformat(),
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
            ReceivingCycleStale,
            completed_receiving_report,
            prove_receiving_liveness,
            receiving_sample_is_fresh,
            receiving_pair_candidate,
        )

        new = registry(source["new"])
        _raw, original = _resolution_source(
            self.directory / "cohort-attempts" / source["plan_sha256"] / "state.json"
        )
        end = self.monotonic() + (120 if feed else 240)
        before = None
        by_stage = {}
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
                _verification_substep(
                    self,
                    "owner_readiness",
                    reason="owner_unavailable",
                    service=next(name for name, state in states.items() if not state),
                )
                sleep(0.2)
                continue
            okay = True
            for name, state in states.items():
                if name == "reference-worker":
                    complete = completed_receiving_report(state)
                    okay = okay and complete
                    if not complete:
                        _verification_substep(
                            self,
                            "owner_readiness",
                            reason="reference_report_incomplete",
                            service=name,
                            report_stage=state.get("proof", {})
                            .get("reference_runtime", {})
                            .get("stage"),
                        )
                else:
                    reason = None
                    if state.get("ready") is not True:
                        reason = "service_not_ready"
                    elif name in original["effects"]["drain"][
                        "progress"
                    ] and not progress_reached(
                        observation_progress(name),
                        original["effects"]["drain"]["progress"][name],
                        service=name,
                        proof=state.get("proof"),
                    ):
                        reason = "progress_pending"
                    elif name in {"api", "web"} and not port_is_ready(name):
                        reason = "http_unavailable"
                    if reason is not None:
                        okay = False
                        _verification_substep(
                            self, "owner_readiness", reason=reason, service=name
                        )
                if not okay:
                    break
            if not okay:
                sleep(0.2)
                continue
            report_stage = states["reference-worker"]["proof"]["reference_runtime"][
                "stage"
            ]
            before = by_stage.get(report_stage)
            _verification_substep(self, "calculation_boundary", before=before)
            self._calculation_boundary(
                active=True
            )  # Pending calculation is not receiving inactivity.
            _verification_substep(self, "receiving_snapshot", before=before)
            try:
                current = self._snapshot(
                    source, check_budget, state=states["reference-worker"]
                )
            except ReceivingCycleStale:
                _verification_substep(
                    self, "receiving_snapshot", before=before,
                    reason="receiving_cycle_stale",
                )
                sleep(0.2)
                continue
            _verification_substep(
                self, "receiving_continuity", before=before, current=current
            )
            self._check_receiving_context(source, audit, check_budget, snapshot=current)
            now = self.now()
            before, candidate = receiving_pair_candidate(
                before, previous, current, now=now
            )
            by_stage[report_stage] = before
            previous = current
            if candidate:
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
                    by_stage[report_stage] = current
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
    freeze.add_argument("--close-feed-only", action="store_true")
    freeze.add_argument("--feed-close-plan", type=Path)
    freeze.add_argument("--stopped-confirmation", type=Path)
    freeze.add_argument("--original-verified-feed-halt", action="store_true")
    apply = sub.add_parser("apply-plan")
    apply.add_argument("--plan", required=True, type=Path)
    confirm = sub.add_parser("confirm-feed-close")
    confirm.add_argument("--plan", required=True, type=Path)
    stopped = sub.add_parser("reconcile-stopped")
    stopped.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        host = ForwardRecoveryHost()
        if args.mode == "plan":
            plan = freeze_forward_recovery(
                host,
                args.source_plan,
                predecessor_recovery_plan=args.predecessor_recovery_plan,
                close_feed_only=args.close_feed_only,
                feed_close_plan=args.feed_close_plan,
                stopped_confirmation=args.stopped_confirmation,
                original_verified_feed_halt=args.original_verified_feed_halt,
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
        elif args.mode == "confirm-feed-close":
            result = confirm_unknown_feed_close(host, args.plan)
        elif args.mode == "reconcile-stopped":
            from app.runtime_stopped_recovery import reconcile_stopped

            result = reconcile_stopped(host, args.plan)
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
