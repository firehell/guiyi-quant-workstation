"""Resume a committed Market source generation before its first target session."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from time import monotonic

from app.market_data.live_market import RedisLiveStore
from app.market_data.market_foundation_scope import require_formal_tick_binding
from app.market_data.observation_stream import ObservationStream
from app.reference_trading.recovery_campaign import digest
from app.runtime_cohort import (
    CALENDARS,
    _resolution_source,
    _sync_resolution_directory,
    continuous_services,
    market_source_recovery_direction,
    registry,
    require,
)
from app.runtime_cohort_errors import CohortError
from app.runtime_deployment import assert_no_unknown_deployment, owner_process_matches
from app.runtime_handover import HandoverError, _read, _write, cancel_drain, deployment_lock, read_service_state
from app.runtime_market_cohort_host import _ACCOUNTS, _account_lock, _private, _redis
from app.runtime_market_source_handover import old_observation_snapshot, redis_instance, verify_preserved_observations


_RECOVERY = "market-source-forward.json"


def forward_recovery_status(host, plan, original):
    evidence = _read(host._attempt(plan) / _RECOVERY)
    if evidence is None:
        return "not_started"
    if forward_completed(host, plan, original):
        return "recovered"
    return "readback_required"


def forward_completed(host, plan, original):
    pointer = _read(host.directory / "cohort-release.json")
    evidence = _read(host._attempt(plan) / _RECOVERY)
    return _receipt_matches(pointer, evidence, plan["plan_sha256"], original)


def _receipt_matches(pointer, evidence, plan_sha, original):
    return (
        evidence is not None and evidence.get("phase") == "recovered"
        and evidence.get("plan_sha256") == plan_sha
        and original is not None and original.get("plan_sha256") == plan_sha
        and evidence.get("original_state_sha256") == digest(original)
        and pointer is not None and pointer.get("phase") == "switched"
        and pointer.get("plan_sha256") == plan_sha
        and pointer.get("market_forward_sha256") == digest(evidence)
    )


def verified_forward_pointer(directory, pointer):
    plan_sha = pointer.get("plan_sha256")
    if not isinstance(plan_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", plan_sha):
        return False
    attempt = directory / "cohort-attempts" / plan_sha
    if attempt.resolve() != attempt:
        return False
    evidence_path = attempt / _RECOVERY
    pointer_path = directory / "cohort-release.json"
    try:
        if not _receipt_matches(pointer, _read(evidence_path), plan_sha, _read(attempt / "state.json")):
            return False
        _sync_published(evidence_path)
        _sync_published(pointer_path)
        return _read(pointer_path) == pointer
    except (HandoverError, OSError, ValueError):
        return False


def _stopped_generation(host, plan, new):
    old = registry(plan["old"])
    host.assert_new_installed(new)
    require(all(host.definition_absent(b) for name, b in old.services.items()
                if b.label != new.services[name].label), "MARKET_SOURCE_LEGACY_OWNER_PRESENT")
    require(all(host.definition_absent(new.services[name]) for name in CALENDARS),
            "MARKET_SOURCE_FORWARD_CALENDAR_UNPROVEN")
    controls = {}
    for name in continuous_services(new):
        binding = new.services[name]
        if not binding.enabled:
            continue
        loaded = not host.definition_absent(binding)
        control = _read(host.directory / f"{name}.handover.json")
        request = None
        if loaded or (control and control.get("generation") == binding.generation and control.get("phase") == "drain"):
            host._check_parked_control(name, binding, control)
            request = control["request_id"]
        if loaded:
            state = read_service_state(name, runtime_dir=host.directory)
            require(state and state.get("phase") == "parked" and state.get("generation") == binding.generation
                    and str(host.loaded(binding)) == str(state.get("pid"))
                    and owner_process_matches(state, binding), "MARKET_SOURCE_FORWARD_OWNER_UNPROVEN")
        controls[name] = (loaded, request)
    return controls


def _check_zero_target(host, plan, args, staged):
    settings = host._active_target(plan)
    day = args["day"]
    with _redis(settings["REDIS_URL"]) as target:
        require(redis_instance(target) == args["expected_instance"]
                and require_formal_tick_binding(target, args["database"], args["canonical"]) == staged["binding"],
                "MARKET_SOURCE_FORWARD_TARGET_DRIFT")
        source = ObservationStream(target, kind="source")
        completed = ObservationStream(target, kind="completed")
        require(source.days() == (day,) and completed.days() == ((day,) if args["alert_enabled"] else ())
                and not target.exists(source.key(day), source.identity_key(day), completed.key(day), completed.identity_key(day))
                and RedisLiveStore(target).subscriptions(day) == args["subscriptions"]
                and source.registered_day("live") == day and source.cursor("live", day) == "0-0",
                "MARKET_SOURCE_FORWARD_TARGET_NOT_PRISTINE")
        if args["alert_enabled"]:
            require(completed.registered_day("alert") == day and completed.cursor("alert", day) == "0-0",
                    "MARKET_SOURCE_ALERT_CURSOR_DRIFT")


def _verify_original(host, plan, state, new):
    effects = state["effects"]
    require({"old_exited", "market_source_preserve", "market_source_stage", "install"} <= effects.keys()
            and "calendars_on" not in effects and not state["phase"].startswith("calendars_on")
            and state.get("failed_phase") != "calendars_on",
            "MARKET_SOURCE_FORWARD_PREIMAGE_UNPROVEN")
    require(effects["old_exited"].get("old_pids_exited") is True, "MARKET_SOURCE_FORWARD_PREIMAGE_UNPROVEN")
    intent = plan["market_source_handover"]
    retained = effects["market_source_preserve"]
    staged = effects["market_source_stage"]
    host._accounts = effects["old_exited"]["accounts"]
    require(set(host._accounts) == _ACCOUNTS.keys()
            and all(digest(row) == intent[f"{name}_sha256"] for name, row in host._accounts.items()),
            "MARKET_SOURCE_FORWARD_ACCOUNT_PREIMAGE_DRIFT")
    raw, host._old_settings = host.retained_project_config(plan)
    host._target_config_sha = staged["config_sha256"]
    journals = {k: v for k, v in retained.items() if k != "archive_sha256"}
    require(digest({"old_config": sha256(raw).hexdigest(), "target_config": host._target_config_sha,
                    "journals": journals}) == intent.get("host_sha256"),
            "MARKET_SOURCE_FORWARD_PREIMAGE_UNPROVEN")
    settings = host._active_target(plan)
    args = host._target_arguments(plan, settings)
    old_day = date.fromisoformat(intent["old_day"])
    _, _, _, windows, _, _ = host._authority(host._old_settings, old_day)
    terminals = host._terminals(windows, args["subscriptions"], "1m")
    for binding in new.services.values():
        host.verify_release(Path(binding.root), binding.tag, binding.commit)
    host.check_schema_compatibility(plan)
    host.assert_protected(plan)
    verify_preserved_observations(host._attempt(plan), retained["archive_sha256"], check_budget=host._before_deadline)
    with _redis(host._old_settings["REDIS_URL"]) as old:
        require(old_observation_snapshot(old, old_day, alert_enabled=args["alert_enabled"],
                                         check_budget=host._before_deadline, terminals=terminals) == journals,
                "MARKET_SOURCE_FORWARD_OLD_FRONTIER_DRIFT")
    _check_zero_target(host, plan, args, staged)
    return args, staged, windows


def recover_market_source_forward(host, supplied):
    """One separate startup attempt against the current registry. No CAS or config write."""
    with deployment_lock(runtime_dir=host.directory):
        plan, state = host._evidence(supplied)
        new = registry(plan["new"])
        pointer_path = host.directory / "cohort-release.json"
        pointer_raw, pointer = _resolution_source(pointer_path)
        attempt = host._attempt(plan)
        original_path = attempt / "state.json"
        original_raw, original = _resolution_source(original_path)
        require(original == state and pointer.get("plan_sha256") == plan["plan_sha256"]
                and pointer.get("phase") not in {"switched", "cancelled"}
                and market_source_recovery_direction(plan, state, host.bindings()) == "forward_only",
                "MARKET_SOURCE_FORWARD_CAS_UNPROVEN")
        evidence = attempt / _RECOVERY
        require(not os.path.lexists(evidence), "MARKET_SOURCE_FORWARD_ATTEMPT_CONSUMED")
        assert_no_unknown_deployment(cohort_plan_sha256=plan["plan_sha256"])
        registry_sha = host.binding_hash()
        host.deadline = monotonic() + plan["downtime_seconds"]
        host._target_config_sha = state["effects"]["market_source_stage"]["config_sha256"]
        host.check_controller_catalog(host._active_target(plan))

        def immutable():
            host._before_deadline()
            require(host.bindings() == new and host.binding_hash() == registry_sha
                    and _private(original_path) == original_raw and _private(pointer_path) == pointer_raw,
                    "MARKET_SOURCE_FORWARD_IDENTITY_DRIFT")
            host._active_target(plan)

        with host.guards(plan):
            args, staged, windows = _verify_original(host, plan, state, new)
            for name, (_, folder) in _ACCOUNTS.items():
                row = host._accounts[name]
                pids = [row["pid"], *([row["helper_pid"]] if name == "tqkq" else [])]
                require(host._account_absent(name) and all(host._pid_absent(pid) for pid in pids),
                        "MARKET_SOURCE_FORWARD_ACCOUNT_STOP_UNPROVEN")
                host._account_guards.enter_context(_account_lock(host.directory / folder / "owner.lock", stopped=True))
            host._verify_stopped_accounts(plan, windows)
            controls = _stopped_generation(host, plan, new)
            immutable()
            receipt = {"plan_sha256": plan["plan_sha256"], "original_state_sha256": digest(state),
                       "registry_sha256": registry_sha, "phase": "claimed", "effects": {}}
            host._private_original(evidence, json.dumps(receipt, sort_keys=True).encode())
            host._sync_directory(attempt)

        def step(name, operation):
            immutable()
            _check_zero_target(host, plan, args, staged)
            receipt["phase"] = name
            _write(evidence, receipt)
            receipt["effects"][name] = operation()
            _write(evidence, receipt)

        def resume(names):
            for name in names:
                loaded, request = controls[name]
                binding = new.services[name]
                require(host.definition_absent(binding) == (not loaded), "MARKET_SOURCE_FORWARD_OWNER_DRIFT")
                if request is not None:
                    cancel_drain(name, request_id=request, runtime_dir=host.directory)
                if not loaded:
                    host.start(binding)
            return {"services": list(names)}

        def publish(path, value):
            try:
                _write(path, value)
            except OSError:
                require(_read(path) == value, "MARKET_SOURCE_FORWARD_READBACK_REQUIRED")
                _sync_published(path)
            require(_read(path) == value, "MARKET_SOURCE_FORWARD_READBACK_REQUIRED")

        try:
            step("consumers", lambda: resume(tuple(name for name in controls if name != "market-feed")))
            step("receiving", lambda: host.market_source_consumers_ready(plan, None))
            step("feed", lambda: resume(("market-feed",)))
            step("verified", lambda: host.verify_market_source(plan, None))
            step("calendars", lambda: host.restore_calendars(plan))
            host.assert_protected(plan)
            immutable()
            receipt["phase"] = "recovered"
            publish(evidence, receipt)
            closed = {**pointer, "phase": "switched", "market_forward_sha256": digest(receipt)}
            publish(pointer_path, closed)
        except Exception:
            try:
                complete = forward_completed(host, plan, state)
                if complete:
                    _sync_published(evidence)
                    _sync_published(pointer_path)
            except Exception:
                complete = False
            if not complete:
                receipt["failed_phase"] = "publication" if receipt["phase"] == "recovered" else receipt["phase"]
                receipt["phase"] = "outcome_unknown"
                try:
                    _write(evidence, receipt)
                finally:
                    try:
                        receipt["halt"] = host.halt_unknown(plan)
                    except Exception:
                        receipt["halt"] = "unproven"
                    _write(evidence, receipt)
                raise CohortError("MARKET_SOURCE_FORWARD_READBACK_REQUIRED") from None
        return {"status": "recovered", "plan_sha256": plan["plan_sha256"],
                "readback": receipt["effects"]["verified"]}


def _sync_published(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_resolution_directory(path.parent)
