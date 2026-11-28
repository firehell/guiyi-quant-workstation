"""Restore the existing 57-product Tick installation during its proven closed window."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from hashlib import sha256
import argparse
import json
import os
import plistlib
from pathlib import Path
import re
import sys
import time

from dotenv import dotenv_values
from sqlalchemy import func, select

from app.alerts.models import AlertEvent, AlertRule
from app.alerts.notification_config import load_notification_config
from app.alerts.service import AlertService
from app.market_data.live_recovery_guard import after_market_recovery_guard
from app.runtime_bootstrap import BootstrapBackend
from app.market_data.market_foundation_scope import formal_tick_initial_day, require_formal_tick_binding
from app.market_data.observation_stream import ObservationStream, TTL_SECONDS
from app.market_data.operational_universe import load_operational_products
from app.reference_trading.recovery_campaign import digest
from app.runtime_bindings import (
    BindingRegistry,
    MARKET_RECOVERY_SERVICES,
    ServiceBinding,
    _parse_bindings,
    write_recovered_market,
)
from app.runtime_cohort import CALENDARS, require
from app.runtime_cohort_errors import CohortError
from app.runtime_deployment import assert_no_unknown_deployment, owner_process_matches
from app.runtime_handover import (
    _read,
    _write,
    deployment_lock,
    owner_lock_available,
    read_service_state,
    request_drain,
)
from app.runtime_identity import file_snapshot, read_launchd_service
from app.runtime_market_cohort_host import _candidate_market_component, _redis
from app.runtime_market_scope_cutover import QuietWindowMarketStartHost, _same_day_tick_proof
from app.runtime_market_source_handover import _consumers, redis_instance
from app.runtime_workstation_forward import WorkstationHost, PAIR, closed_ports

START_ORDER = (
    "api",
    "web",
    "live",
    "reference-worker",
    "alert",
    "market-feed",
    "after-market",
    "late-provider-recovery",
)
MARKERS = ("market-runtime-enabled", "reference-worker-enabled", "alert-runtime-enabled")
KIND = "existing_tick_market_recovery_v1"

# The consumer does not exist yet. Freeze both streams, the prior Live ACK,
# registration and exact terminal completed row inside a single Redis operation.
NEW_ALERT = """
if redis.call('exists', KEYS[1], KEYS[2]) ~= 0 then return 0 end
if redis.call('get',KEYS[3]) ~= ARGV[1] or redis.call('get',KEYS[4]) ~= ARGV[2] then return 0 end
for i=5,7,2 do
  local row=redis.call('xrevrange',KEYS[i],'+','-','count',1)
  local a=i==5 and 2 or 4
  if #row~=1 or row[1][1]~=ARGV[a] or redis.call('xlen',KEYS[i])~=tonumber(ARGV[a+1])
    or redis.call('hlen',KEYS[i+1])~=tonumber(ARGV[a+1]) then return 0 end
end
redis.call('set',KEYS[1],ARGV[4],'EX',ARGV[6])
redis.call('set',KEYS[2],ARGV[1])
return 1
"""


class RecoveryHost(WorkstationHost):
    def notification(self):
        value = dotenv_values(self.target_config).get("GUIYI_ALERT_NOTIFICATION_CONFIG_PATH")
        require(bool(value), "MARKET_NOTIFICATION_CONFIG_UNPROVEN")
        path = Path(value)
        raw = file_snapshot(path, private=True)[0]
        config = load_notification_config(path)
        require(file_snapshot(path, private=True)[0] == raw, "MARKET_NOTIFICATION_CONFIG_DRIFT")
        return {"transport": config.transport, "sha256": sha256(raw).hexdigest()}

    def boundary(self, day, *, registered=False):
        settings, config_digest = self.settings()
        calendar = QuietWindowMarketStartHost.closed_day_authority(self, settings, day)
        products = load_operational_products()
        require(
            len(products) == 57 and set(products) == calendar["subscriptions"].keys(), "MARKET_SCOPE_DRIFT"
        )
        with self._catalog_session(settings) as (session, _):
            service = AlertService(session, operational_products=products)
            # The native Alert supervisor closes orphan handoffs at startup.
            # Require zero pending first to preserve all historical delivery rows.
            require(
                session.scalar(
                    select(AlertEvent.id)
                    .where(AlertEvent.notification_status == "HANDOFF_PENDING")
                    .limit(1)
                )
                is None,
                "MARKET_NOTIFICATION_HANDOFF_PENDING",
            )
            historical = [
                [status, count, latest]
                for status, count, latest in session.execute(
                    select(AlertEvent.notification_status, func.count(), func.max(AlertEvent.id))
                    .group_by(AlertEvent.notification_status)
                    .order_by(AlertEvent.notification_status)
                )
            ]
            rules = {}
            for rule in session.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))):
                scope = service.effective_frequency_scope(rule)
                rules[rule.rule_code] = {
                    "id": rule.id,
                    "stored_scope_sha256": digest(rule.scope_product_frequencies),
                    "products": len(scope),
                    "frequencies": sum(map(len, scope.values())),
                    "scope_sha256": digest({k: list(v) for k, v in scope.items()}),
                }
        with _redis(settings["REDIS_URL"]) as redis:
            binding = require_formal_tick_binding(redis, *self._storage(settings))
            initial = formal_tick_initial_day(redis)
            require(initial is not None and initial <= day, "MARKET_REDIS_BINDING_DRIFT")
            stream = ObservationStream(redis, kind="completed")
            require(
                stream.days() == (day,) and _consumers(stream) == (("alert",) if registered else ()),
                "MARKET_COMPLETED_CONSUMERS_DRIFT",
            )
            if not registered:
                require(not redis.exists(stream.cursor_key("alert", day)), "MARKET_ALERT_CURSOR_DRIFT")
            proof, _, staged = _same_day_tick_proof(
                redis,
                day,
                calendar["subscriptions"],
                completed_consumers=("alert",) if registered else (),
            )
            require(staged, "MARKET_RETAINED_SCOPE_UNPROVEN")
            # The only permitted boundary change is the newly added Alert registration.
            proof["streams"]["completed"][day.isoformat()]["cursors"] = {}
            return {
                "day": day.isoformat(),
                "first_session": calendar["first_session"],
                "scope": digest(calendar),
                "rules": rules,
                "historical_events_sha256": digest(historical),
                "config": config_digest,
                "notification": self.notification(),
                "instance": redis_instance(redis),
                "binding": binding,
                "initial_day": initial.isoformat(),
                "streams": proof["streams"],
                "retained_selection": proof["selection_sha256"],
            }

    def register_alert(self, boundary, *, may_exist):
        day = date.fromisoformat(boundary["day"])
        settings, _ = self.settings()
        with _redis(settings["REDIS_URL"]) as redis:
            require(
                redis_instance(redis) == boundary["instance"]
                and require_formal_tick_binding(redis, *self._storage(settings)) == boundary["binding"],
                "MARKET_REDIS_BINDING_DRIFT",
            )
            source = ObservationStream(redis, kind="source")
            stream = ObservationStream(redis, kind="completed")
            daily = boundary["day"]
            before = boundary["streams"]["source"][daily]
            after = boundary["streams"]["completed"][daily]
            cursor, registration = stream.cursor_key("alert", day), stream.registration_key("alert")
            if redis.exists(registration) or redis.exists(cursor):
                require(
                    may_exist
                    and stream.registered_day("alert") == day
                    and stream.cursor("alert", day) == after["tail"],
                    "MARKET_ALERT_CURSOR_DRIFT",
                )
                return
            result = redis.eval(
                NEW_ALERT,
                8,
                cursor,
                registration,
                source.registration_key("live"),
                source.cursor_key("live", day),
                source.key(day),
                source.identity_key(day),
                stream.key(day),
                stream.identity_key(day),
                daily,
                before["tail"],
                before["count"],
                after["tail"],
                after["count"],
                TTL_SECONDS,
            )
            require(result == 1, "MARKET_ALERT_TAIL_DRIFT")

    def alert_registered(self, day):
        settings, _ = self.settings()
        with _redis(settings["REDIS_URL"]) as redis:
            stream = ObservationStream(redis, kind="completed")
            keys = [stream.registration_key("alert"), stream.cursor_key("alert", day)]
            observed = redis.mget(*keys)
            require(
                all(v is None for v in observed) or all(v is not None for v in observed),
                "MARKET_ALERT_CURSOR_DRIFT",
            )
            return observed[0] is not None

    def targets(self, root, tag, commit, previous):
        pair, _, schema = self.candidate(root, tag, commit, previous)
        component = _candidate_market_component(root)
        return {n: replace(pair["api"], service=n) for n in START_ORDER}, list(component), schema

    def check_calendar_window(self, targets):
        for name in ("after-market", "late-provider-recovery"):
            BootstrapBackend()._assert_recovery_calendar_safe(
                plistlib.loads(self._plist(targets[name])), ahead_minutes=12
            )

    def ready_artifacts(self, target, boundary):
        run_dir = Path(target.root) / ".run"
        require(
            run_dir.resolve() == run_dir
            and not any(
                os.path.lexists(run_dir / name)
                for name in (
                    "after-market-status.json",
                    "after-market-history.json",
                    "late-provider-recovery-status.json",
                )
            ),
            "MARKET_TARGET_SCHEDULE_HISTORY_PRESENT",
        )
        settings, _ = self.settings()
        self.deadline = time.monotonic() + 90
        self._prove_staged_warmup(target, settings, boundary["binding"], direct=True)

    def old_web(self, previous):
        for name in PAIR:
            item = previous.services[name]
            require(
                item.enabled
                and item.launchd_label is None
                and self.bytes(self.path(item)) == self._plist(item),
                "MARKET_OLD_HTTP_UNPROVEN",
            )
            self.verify_release(Path(item.root), item.tag, item.commit)
        self.ready({n: previous.services[n] for n in PAIR})

    def old_role(self, item, root, initial_files, attempt):
        path = self.path(item)
        before = sha256(self.bytes(path)).hexdigest() if os.path.lexists(path) else None
        require(
            path.name in initial_files and before == initial_files[path.name], "MARKET_OLD_DEFINITION_DRIFT"
        )
        intent = attempt / ("old-bootout-" + item.service + ".json")
        identity = {"label": item.label, "generation": item.generation, "commit": item.commit}
        submitted = _read(intent)
        require(submitted is None or submitted == identity, "MARKET_OLD_PARK_INTENT_DRIFT")
        output = read_launchd_service(item.label, root=root)
        if output:
            self.verify_loaded(item, output)
            if item.service not in PAIR:
                self._assert_old_job_idle(item, output)
        if submitted is None and (not output or item.service not in PAIR):
            require(self.free(item.service), "MARKET_OLD_JOB_BUSY")
        return output, intent, identity, submitted

    def preflight_parking(self, old, root, initial_files, attempt):
        dispatcher = self.directory / "run-local-service.sh"
        require(
            sha256(self.bytes(dispatcher)).hexdigest() == initial_files.get(dispatcher.name),
            "MARKET_OLD_DISPATCHER_DRIFT",
        )
        drains = _read(attempt / "drains.json") or {}
        require(
            set(drains) <= set(PAIR)
            and all(isinstance(v, str) and re.fullmatch("[0-9a-f]{32}", v) for v in drains.values()),
            "MARKET_HTTP_DRAIN_DRIFT",
        )
        for name in START_ORDER:
            item = old.services[name]
            self.old_role(item, root, initial_files, attempt)
            if name in PAIR:
                control = _read(self.directory / f"{name}.handover.json") or {}
                if control.get("generation") == item.generation and control.get("phase") == "drain":
                    require(
                        drains.get(name) and control.get("request_id") == drains[name],
                        "MARKET_HTTP_DRAIN_DRIFT",
                    )

    def park(self, old, root, initial_files, attempt):
        # Check every selected predecessor before the first side effect. Recheck
        # each role immediately before its own drain or unload as well.
        self.preflight_parking(old, root, initial_files, attempt)
        for name in START_ORDER:
            item = old.services[name]
            output, intent, identity, submitted = self.old_role(item, root, initial_files, attempt)
            if submitted is not None:
                self.wait_parked(item, root, "MARKET_OLD_PARK_UNPROVEN")
                continue
            if output and name in PAIR:
                self.drain_http(item, attempt)
            self.unload_verified(item, root, old=True, before_bootout=lambda: _write(intent, identity))
            self.wait_parked(item, root, "MARKET_OLD_PARK_UNPROVEN")
        closed_ports()

    def wait_parked(self, item, root, code, *, timeout=30):
        """A successful bootout can return before launchd releases the job and owner."""
        deadline = time.monotonic() + timeout
        while True:
            disabled, _ = self.authorities(root)
            output = read_launchd_service(item.label, root=root)
            if output:
                self.verify_loaded(item, output)
            if disabled.get(item.label) is True and output is None and self.free(item.service):
                return
            require(time.monotonic() < deadline, code)
            time.sleep(0.2)

    def unload_verified(self, item, root, *, old=False, before_bootout=None):
        guard = (
            after_market_recovery_guard(root=self.directory / "live-recovery-guards", legacy_root=True)
            if item.service in CALENDARS
            else nullcontext()
        )
        with guard:
            target = f"gui/{os.getuid()}/{item.label}"
            disabled, _ = self.authorities(root)
            if disabled.get(item.label) is not True:
                self.launch("disable", target)
            current = read_launchd_service(item.label, root=root)
            if current:
                self.verify_loaded(item, current)
                if item.service in CALENDARS or old and item.service not in PAIR:
                    self._assert_old_job_idle(item, current)
                    require(self.free(item.service), "MARKET_OLD_JOB_BUSY")
                if before_bootout is not None:
                    before_bootout()
                self.launch("bootout", target)

    def free(self, name):
        return not os.path.lexists(self.directory / f"{name}.owner.lock") or owner_lock_available(
            name, runtime_dir=self.directory
        )

    def drain_http(self, item, attempt):
        name = item.service
        intents = _read(attempt / "drains.json") or {}
        control = _read(self.directory / f"{name}.handover.json") or {}
        identifier = intents.get(name)
        if control.get("generation") == item.generation and control.get("phase") == "drain":
            require(identifier and control.get("request_id") == identifier, "MARKET_HTTP_DRAIN_DRIFT")
        else:
            self.ready({name: item})

            def remember(value):
                intents[name] = value
                _write(attempt / "drains.json", intents)

            request_drain(
                name,
                generation=item.generation,
                runtime_dir=self.directory,
                before_install=remember,
                request_id=identifier,
            )
        until = time.monotonic() + 35
        while time.monotonic() < until:
            state = read_service_state(name, runtime_dir=self.directory) or {}
            if (
                state.get("phase") == "parked"
                and state.get("generation") == item.generation
                and self.free(name)
            ):
                return
            time.sleep(0.2)
        raise CohortError("MARKET_HTTP_DRAIN_TIMEOUT")

    def install(self, bindings, attempt, preimage):
        for item in bindings.values():
            self._install_file(self.path(item), self._plist(item), attempt, preimage)
        root = Path(bindings["api"].root)
        for name in MARKERS:
            path = root / ".run" / name
            require(path.parent.resolve() == path.parent, "MARKET_ACTIVATION_MARKER_DRIFT")
            if not os.path.lexists(path):
                self.install_marker(path)
            require(self.bytes(path) == b"enabled\n", "MARKET_ACTIVATION_MARKER_DRIFT")

    def prove_running(self, item, *, wait=False):
        budget = 240 if item.service == "alert" else 50
        # Feed and Live clear ready during every poll. A matching live owner can
        # be sampled repeatedly without changing any service or accepting stale proof.
        observe_poll = not wait and item.service in {"market-feed", "live"}
        until = time.monotonic() + (budget if wait else 8 if observe_poll else 0)
        sampled_pid = None
        suffix = item.service.upper().replace("-", "_")
        while True:
            out = read_launchd_service(item.label, root=Path(item.root))
            if out:
                self.verify_loaded(item, out)
                if item.service in CALENDARS:
                    self.verify_calendar(item)
                    return
                state = read_service_state(item.service, runtime_dir=self.directory) or {}
                same_owner = (
                    state.get("phase") == "active"
                    and state.get("generation") == item.generation
                    and owner_process_matches(state, item)
                    and 0 <= (self.now() - datetime.fromisoformat(state["at"])).total_seconds() <= 30
                )
                if observe_poll:
                    require(
                        same_owner and not self.free(item.service), "MARKET_POLL_OWNER_UNPROVEN_" + suffix
                    )
                    pid = state["pid"]
                    require(sampled_pid in (None, pid), "MARKET_POLL_OWNER_CHANGED_" + suffix)
                    sampled_pid = pid
                if (
                    same_owner
                    and state.get("ready") is True
                    and (item.service not in PAIR or self.owns_http(item, state["pid"]))
                ):
                    if observe_poll:
                        proof = state.get("proof")
                        require(
                            isinstance(proof, dict)
                            and "failure_code" not in proof
                            and (
                                proof.get("cycle_ok") is True
                                or item.service == "market-feed"
                                and isinstance(proof.get("closed_cleaned"), dict)
                                and proof["closed_cleaned"].get("status") == "CLOSED_CLEANED"
                                or item.service == "live"
                                and {"input_read_frontier", "trading_day"} <= proof.keys()
                            ),
                            "MARKET_POLL_SUCCESS_UNPROVEN_" + suffix,
                        )
                    return {"pid": state["pid"], "ready_at": state["at"]}
                if observe_poll:
                    require(
                        state.get("ready") is False and state.get("proof") == {},
                        "MARKET_POLL_FAILURE_" + suffix,
                    )
            elif sampled_pid is not None:
                raise CohortError("MARKET_POLL_OWNER_CHANGED_" + suffix)
            if not out and not wait or time.monotonic() >= until:
                if sampled_pid is not None:
                    raise CohortError("MARKET_COMPLETED_POLL_UNPROVEN_" + suffix)
                raise CohortError("MARKET_OWNER_NOT_READY_" + suffix)
            time.sleep(0.25)

    def start_selected(self, targets):
        for name in START_ORDER:
            item = targets[name]
            out = read_launchd_service(item.label, root=Path(item.root))
            if out is None:
                require(self.free(name), "MARKET_TARGET_OWNER_BUSY")
                (self.start_calendar if name in CALENDARS else self.start)(item)
            self.prove_running(item, wait=True)

    def stop_selected(self, targets):
        # Verify all installed jobs before acting on any label.
        root = Path(targets["api"].root)
        for item in targets.values():
            require(self.bytes(self.path(item)) == self._plist(item), "MARKET_TARGET_DEFINITION_DRIFT")
            out = read_launchd_service(item.label, root=root)
            if out:
                self.verify_loaded(item, out)
        for name in reversed(START_ORDER):
            item = targets[name]
            self.unload_verified(item, root)
            self.wait_parked(item, root, "MARKET_TARGET_STOP_UNKNOWN")
        closed_ports()


def prepare(host, root, tag, commit, day):
    assert_no_unknown_deployment()
    old, old_hash, raw = host.inventory()
    require(
        old
        and set(START_ORDER) == MARKET_RECOVERY_SERVICES
        and all(
            n in old.services
            and old.services[n].enabled == (n != "alert")
            and old.services[n].launchd_label is None
            for n in START_ORDER
        ),
        "MARKET_OLD_TOPOLOGY_UNSUPPORTED",
    )
    targets, component, schema = host.targets(root, tag, commit, old)
    host.old_web(old)
    previous = host.evidence(old, root, peers_only=True)
    boundary = host.boundary(day)
    require(host.inventory()[2] == raw, "MARKET_REGISTRY_DRIFT")
    host.check_calendar_window(targets)
    host.ready_artifacts(targets["market-feed"], boundary)
    expected = host.installation_preimage(old)
    value = {
        "kind": KIND,
        "created": host.now().isoformat(),
        "old_sha256": old_hash,
        "targets": {n: asdict(b) for n, b in targets.items()},
        "component": component,
        "schema": schema,
        "boundary": boundary,
        "files": expected,
        "old_evidence": previous,
    }
    return {**value, "plan_sha256": digest(value)}


def inspect(host, plan):
    require(
        plan.get("kind") == KIND
        and plan.get("plan_sha256") == digest({k: v for k, v in plan.items() if k != "plan_sha256"})
        and set(plan["targets"]) == MARKET_RECOVERY_SERVICES,
        "MARKET_RECOVERY_PLAN_INVALID",
    )
    targets = {n: ServiceBinding(**plan["targets"][n]) for n in START_ORDER}
    require(all(n == v.service for n, v in targets.items()), "MARKET_RECOVERY_PLAN_INVALID")
    observed, actual, raw = host.inventory()
    attempt = host.directory / ("market-recovery-" + plan["plan_sha256"])
    if actual == plan["old_sha256"]:
        return "old", observed, targets, attempt
    path = attempt / "previous-registry.json"
    if not path.is_file():
        raise CohortError("MARKET_REGISTRY_OUTCOME_UNKNOWN")
    original = file_snapshot(path, private=True)[0]
    require(sha256(original).hexdigest() == plan["old_sha256"], "MARKET_ORIGINAL_DRIFT")
    old = _parse_bindings(original, inventory=True)
    require(
        old and observed and observed.services == {**old.services, **targets},
        "MARKET_REGISTRY_OUTCOME_UNKNOWN",
    )
    return "new", old, targets, attempt


def peers(host, old, root, plan):
    current = host.evidence(old, root, peers_only=True, skip_names=MARKET_RECOVERY_SERVICES)
    require(
        current == {k: v for k, v in plan["old_evidence"].items() if k not in MARKET_RECOVERY_SERVICES},
        "MARKET_UNSELECTED_PEER_DRIFT",
    )


def readback(host, plan):
    authority, old, targets, _ = inspect(host, plan)
    state = _read(host.directory / "market-recovery.json") or {}
    result = {
        "authority": authority,
        "phase": state.get("phase") if state.get("plan_sha256") == plan["plan_sha256"] else None,
    }
    if result["phase"] == "switched":
        require(authority == "new", "MARKET_REGISTRY_DRIFT")
        result.update(verify_switched(host, old, targets, plan))
    return result


def verify_switched(host, old, targets, plan):
    root = Path(targets["api"].root)
    peers(host, old, root, plan)
    completed_polls = {}
    for item in targets.values():
        require(host.bytes(host.path(item)) == host._plist(item), "MARKET_INSTALLED_DEFINITION_DRIFT")
        proof = host.prove_running(item)
        if item.service in {"market-feed", "live"}:
            completed_polls[item.service] = proof
    settings, config = host.settings()
    require(
        config == plan["boundary"]["config"] and host.notification() == plan["boundary"]["notification"],
        "MARKET_CONFIGURATION_DRIFT",
    )
    with _redis(settings["REDIS_URL"]) as redis:
        boundary = plan["boundary"]
        require(
            redis_instance(redis) == boundary["instance"]
            and require_formal_tick_binding(redis, *host._storage(settings)) == boundary["binding"],
            "MARKET_REDIS_BINDING_DRIFT",
        )
        completed = ObservationStream(redis, kind="completed")
        observed_day = completed.registered_day("alert")
        require(observed_day >= date.fromisoformat(boundary["day"]), "MARKET_ALERT_CURSOR_DRIFT")
        current_cursor = completed.cursor("alert", observed_day)
        if observed_day.isoformat() == boundary["day"]:
            floor = boundary["streams"]["completed"][boundary["day"]]["tail"]
            require(
                tuple(map(int, current_cursor.split("-"))) >= tuple(map(int, floor.split("-"))),
                "MARKET_ALERT_CURSOR_DRIFT",
            )
    return {
        "generation": targets["api"].generation,
        "tag": targets["api"].tag,
        "services": list(START_ORDER),
        "notification": host.notification()["transport"],
        "alert_day": observed_day.isoformat(),
        "completed_polls": completed_polls,
    }


def apply(host, plan, *, resume=False):
    with deployment_lock(runtime_dir=host.directory):
        authority, old, targets, attempt = inspect(host, plan)
        root = Path(targets["api"].root)
        pointer = host.directory / "market-recovery.json"
        state = _read(pointer) or {}
        own = state.get("plan_sha256") == plan["plan_sha256"]

        def record(phase):
            _write(pointer, {"phase": phase, "plan_sha256": plan["plan_sha256"]})

        if own and state["phase"] == "switched":
            return readback(host, plan)
        assert_no_unknown_deployment(market_recovery_sha256=plan["plan_sha256"] if resume else None)
        day = date.fromisoformat(plan["boundary"]["day"])
        require(
            (not resume and not own and authority == "old") or (resume and own),
            "MARKET_RECOVERY_ATTEMPT_REQUIRED",
        )
        identity = targets["api"]
        check, component, schema = host.targets(root, identity.tag, identity.commit, old)
        require(
            check == targets and component == plan["component"] and schema == plan["schema"],
            "MARKET_CANDIDATE_DRIFT",
        )
        peers(host, old, root, plan)
        if not resume:
            require(
                timedelta(0)
                <= host.now() - datetime.fromisoformat(plan["created"])
                <= timedelta(minutes=15),
                "MARKET_RECOVERY_PLAN_EXPIRED",
            )
            host.old_web(old)
            require(
                host.evidence(old, root, peers_only=True) == plan["old_evidence"]
                and host.installation_preimage(old) == plan["files"],
                "MARKET_OLD_HOST_DRIFT",
            )
        phase = state.get("phase") if own else None
        if phase == "starting" and authority == "new":
            # A crash may have occurred after the last successful bootstrap.
            # Converge a fully verified running generation without stopping any process.
            try:
                result = verify_switched(host, old, targets, plan)
            except CohortError as error:
                if not str(error).startswith("MARKET_OWNER_NOT_READY_"):
                    raise
            else:
                record("switched")
                return {"authority": "new", "phase": "switched", **result}
        if phase in {"starting", "stop_unknown", "start_failed"}:
            require(authority == "new", "MARKET_REGISTRY_DRIFT")
            # An interruption after Feed intake must not re-park a live trading session.
            require(
                host.now() + timedelta(minutes=10)
                < datetime.fromisoformat(plan["boundary"]["first_session"]),
                "MARKET_RESTART_WINDOW_CLOSED",
            )
            record("stop_unknown")
            host.stop_selected(targets)
            record("start_failed")
        host.check_calendar_window(targets)
        registered = host.alert_registered(day)
        require(
            not registered
            or resume
            and authority == "new"
            and phase in {"alert_intent", "starting", "stop_unknown", "start_failed"},
            "MARKET_ALERT_REGISTRATION_UNPROVEN",
        )
        require(host.boundary(day, registered=registered) == plan["boundary"], "MARKET_BOUNDARY_DRIFT")
        if not resume:
            host.ready_artifacts(targets["market-feed"], plan["boundary"])
            current, before, raw = host.inventory()
            require(before == plan["old_sha256"], "MARKET_REGISTRY_DRIFT")
            # Recover safely if killed after the original was saved but before journal creation.
            if not attempt.exists():
                attempt.mkdir(mode=0o700)
            require(
                attempt.resolve() == attempt
                and attempt.stat().st_uid == os.getuid()
                and attempt.stat().st_mode & 0o077 == 0,
                "MARKET_ATTEMPT_INVALID",
            )
            path = attempt / "previous-registry.json"
            if not path.exists():
                host._private_original(path, raw)
            require(file_snapshot(path, private=True)[0] == raw, "MARKET_ORIGINAL_DRIFT")
            host._sync_directory(attempt)
            host._sync_directory(host.directory)
            record("parking")
        if authority == "old":
            require(phase in {None, "parking", "cas_intent"}, "MARKET_RECOVERY_PHASE_INVALID")
            host.park(old, root, plan["files"], attempt)
        settings, _ = host.settings()
        scope = BindingRegistry(1, targets)
        with host.guards_for_direct_start(scope, settings):
            peers(host, old, root, plan)
            require(host.boundary(day, registered=registered) == plan["boundary"], "MARKET_BOUNDARY_DRIFT")
            if authority == "old":
                record("cas_intent")
                try:
                    write_recovered_market(targets, expected_sha256=plan["old_sha256"], home=host.home)
                except BaseException:
                    raise CohortError("MARKET_CAS_READBACK_REQUIRED") from None
            require(inspect(host, plan)[0] == "new", "MARKET_CAS_READBACK_REQUIRED")
            if not registered:
                record("installing")
            host.install(targets, attempt, plan["files"])
            peers(host, old, root, plan)
            for item in targets.values():
                require(read_launchd_service(item.label, root=root) is None, "MARKET_SELECTED_NOT_PARKED")
            closed_ports()
            record("alert_intent")
            host.register_alert(plan["boundary"], may_exist=registered)
            require(host.boundary(day, registered=True) == plan["boundary"], "MARKET_BOUNDARY_DRIFT")
        record("starting")
        try:
            host.start_selected(targets)
            require(inspect(host, plan)[0] == "new", "MARKET_REGISTRY_DRIFT")
            peers(host, old, root, plan)
            require(host.boundary(day, registered=True) == plan["boundary"], "MARKET_BOUNDARY_DRIFT")
        except BaseException:
            record("stop_unknown")
            host.stop_selected(targets)
            record("start_failed")
            raise
        record("switched")
        return readback(host, plan)


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--day", type=date.fromisoformat, required=True)
    target = sub.add_parser("plan")
    for key in ("root", "tag", "commit", "day"):
        target.add_argument("--" + key, required=True)
    for name in ("apply", "resume", "read"):
        sub.add_parser(name).add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        host = RecoveryHost()
        if args.operation == "audit":
            old, registry_sha, _ = host.inventory()
            host.old_web(old)
            before = host.evidence(old, Path(__file__).resolve().parents[3], peers_only=True)
            value = {
                "registry": registry_sha,
                "other_services": before,
                "boundary": host.boundary(args.day),
            }
        elif args.operation == "plan":
            value = prepare(host, Path(args.root), args.tag, args.commit, date.fromisoformat(args.day))
        else:
            plan = json.loads(file_snapshot(args.plan, private=True)[0])
            value = (
                readback(host, plan)
                if args.operation == "read"
                else apply(host, plan, resume=args.operation == "resume")
            )
        print(json.dumps(value, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        reason = str(error)
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": reason
                    if re.fullmatch(r"[A-Z0-9_]+", reason)
                    else "MARKET_RECOVERY_PREFLIGHT_UNAVAILABLE",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
