"""Start the published Market and Compute services at a fresh Tick boundary."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import re
import socket
import sys
from time import monotonic
from urllib.parse import urlsplit

from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.compute_runtime.artifact import require_locked_core
from app.market_data.catalog import MarketCatalog
from app.market_data.live_market import RedisLiveStore
from app.market_data.live_recovery_guard import after_market_recovery_guard
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_foundation_scope import (
    formal_tick_fingerprint, formal_tick_initial_day, require_formal_tick_binding,
)
from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
from app.market_data.observation_stream import ObservationStream
from app.market_data.operational_universe import load_operational_products
from app.market_data.storage import CanonicalMonthlyStore
from app.runtime_bindings import (
    BindingRegistry, ServiceBinding, authorized_program_arguments, market_start_preimage,
    write_market_start_bindings,
)
from app.runtime_cohort import CALENDARS, _resolution_source, registry, require
from app.runtime_cohort_errors import CohortError
from app.runtime_contracts import REQUIRED_SERVICES
from app.runtime_deployment import assert_no_unknown_deployment, owner_process_matches
from app.runtime_handover import _read, _write, deployment_lock, owner_lock_available, read_service_state
from app.runtime_identity import launchd_arguments, launchd_environments, read_command, read_launchd_service, safe_directory
from app.runtime_market_cohort_host import MarketCohortHost, _TICK_MARKER, _candidate_market_component, _private_configuration, _redis
from app.runtime_market_source_handover import (
    read_first_completed_minutes, read_staged_observations, redis_instance, stage_new_observations,
)
from app.reference_trading.recovery_campaign import digest

_CORE = frozenset({"api", "web", "market-feed", "live", "reference-worker", "after-market"})
_MARKERS = {
    "live": "market-runtime-enabled",
    "reference-worker": "reference-worker-enabled",
    "weekly-audit": "weekly-audit-enabled",
}
_RUNTIME_SERVICES = REQUIRED_SERVICES | {"home-projection"}
_KIND = "market_direct_start_v1"
_ACTIVE_SESSION = "active_session"
_PHASES = ("parking", "staging", "installing", "committing", "starting", "switched")


def _target_bindings(previous, root, tag, commit, contracts):
    prior = previous.services if previous else {}
    generation = 1 + max((item.generation for item in prior.values()), default=0)
    enabled = _CORE | {name for name in CALENDARS if name in prior and prior[name].enabled}
    return BindingRegistry(1, {
        name: ServiceBinding(name, str(root), tag, commit, generation, name in enabled, contracts)
        for name in sorted(REQUIRED_SERVICES | prior.keys())
    })


def _candidate(plan):
    return registry(plan["new"]).services["api"]


def _attempt_path(host, plan):
    return host.directory / "market-direct-start-attempts" / plan["plan_sha256"]


def _validate_plan(plan):
    require(
        isinstance(plan, dict) and plan.get("kind") == _KIND
        and isinstance(plan.get("plan_sha256"), str)
        and plan["plan_sha256"] == digest({key: value for key, value in plan.items() if key != "plan_sha256"}),
        "MARKET_DIRECT_START_PLAN_INVALID",
    )


def _read_authority(host, settings, root, day, *, active_session):
    if active_session:
        return host.active_authority(settings, root, day)
    return host.authority(settings, root, day)


def freeze_market_direct_start(host, *, root, tag, commit, day, active_session=False):
    assert_no_unknown_deployment()
    previous, preimage, _ = market_start_preimage(home=host.home)
    contracts, component = host.release(root, tag, commit, previous)
    settings, config_hash = host.settings()
    authority = _read_authority(host, settings, root, day, active_session=active_session)
    target_instance = host.target_instance(settings, authority)
    new = _target_bindings(previous, root, tag, commit, contracts)
    plan = {
        "kind": _KIND, "registry_sha256": preimage,
        "new": asdict(new),
        "component": list(component), "config_sha256": config_hash,
        "day": day.isoformat(), "authority": authority, "target_instance": target_instance,
        "created_at": host.now().isoformat(),
        "installed": host.installation_preimage(new),
    }
    plan["plan_sha256"] = digest(plan)
    return plan


def apply_market_direct_start(host, plan, *, resume=False):
    _validate_plan(plan)
    with deployment_lock(runtime_dir=host.directory):
        pointer = host.directory / "cohort-release.json"
        current = _read(pointer)
        same = current is not None and current.get("plan_sha256") == plan["plan_sha256"]
        new = registry(plan["new"])
        old, preimage, raw = market_start_preimage(home=host.home)
        if same and current.get("kind") == _KIND and current.get("phase") == "switched":
            require(old == new, "MARKET_DIRECT_START_BINDING_DRIFT")
            host.verify_installed(new)
            return {"status": "already_started", "generation": _candidate(plan).generation}
        require(same == resume, "MARKET_DIRECT_START_EXPLICIT_RESUME_REQUIRED")
        assert_no_unknown_deployment(cohort_plan_sha256=plan["plan_sha256"] if resume else None)
        attempt = _attempt_path(host, plan)
        if resume:
            require(current.get("kind") == _KIND and current.get("phase") in _PHASES
                    and _resolution_source(attempt / "plan.json")[1] == plan,
                    "MARKET_DIRECT_START_ATTEMPT_INVALID")
        phase = current["phase"] if resume else None
        bound = old == new
        require(
            (bound and phase in {"committing", "starting"})
            or (not bound and preimage == plan["registry_sha256"] and phase != "starting"),
            "MARKET_DIRECT_START_BINDING_DRIFT",
        )
        candidate = _candidate(plan)
        root, day = Path(candidate.root), date.fromisoformat(plan["day"])
        contracts, component = host.release(root, candidate.tag, candidate.commit, None if bound else old)
        expected = new if bound else _target_bindings(old, root, candidate.tag, candidate.commit, contracts)
        require(expected == new and all(binding.contracts == contracts for binding in new.services.values())
                and list(component) == plan["component"], "MARKET_DIRECT_START_RELEASE_DRIFT")
        settings, config_hash = host.settings()
        now = host.now()
        authority = plan["authority"]
        active_session = authority.get("mode") == _ACTIVE_SESSION
        limit = authority["window_end"] if active_session else authority["first_session"]
        past_start_window = now + timedelta(seconds=660) >= datetime.fromisoformat(limit)
        require(datetime.fromisoformat(plan["created_at"]) <= now
                and config_hash == plan["config_sha256"], "MARKET_DIRECT_START_AUTHORITY_DRIFT")
        if not bound or not past_start_window:
            require(_read_authority(host, settings, root, day, active_session=active_session) == authority,
                    "MARKET_DIRECT_START_AUTHORITY_DRIFT")
        host.deadline = monotonic() + 600
        if not resume:
            require(host.installation_preimage(new) == plan["installed"], "MARKET_DIRECT_START_INSTALL_DRIFT")
            attempt.parent.mkdir(mode=0o700, exist_ok=True)
            with safe_directory(attempt.parent):
                attempt.mkdir(mode=0o700)
            _write(attempt / "plan.json", plan)
            if raw is not None:
                host._private_original(attempt / "previous-registry.json", raw)
            host._sync_directory(attempt)

        def persist(value):
            _write(pointer, {"schema_version": 1, "kind": _KIND, "plan_sha256": plan["plan_sha256"], "phase": value})

        if not bound:
            if "retained_tick" in authority:
                if phase in (None, "parking"):
                    persist("parking")
                host.prepare_retained_scope(old, plan, settings, attempt)
            with host.guards_for_direct_start(new, settings):
                if active_session:
                    require(host.active_authority(settings, root, day) == authority,
                            "MARKET_DIRECT_START_AUTHORITY_DRIFT")
                if phase in (None, "parking"):
                    persist("parking")
                host.park(old, new)
                if active_session:
                    require(host.active_authority(settings, root, day) == authority,
                            "MARKET_DIRECT_START_AUTHORITY_DRIFT")
                stage_may_exist = phase in {"staging", "installing", "committing"}
                persist("staging")
                host.stage(plan, settings, may_exist=stage_may_exist)
                persist("installing")
                host.install_new(new, attempt, plan["installed"])
                host.assert_ready_to_bind(plan, new, settings)
                persist("committing")
                write_market_start_bindings(new, home=host.home, expected_sha256=preimage)
        require(host.bindings() == new, "MARKET_DIRECT_START_BINDING_DRIFT")
        persist("starting")
        proof = host.start_new(plan, verify_running_only=past_start_window)
        persist("switched")
        return {"status": "switched", "generation": candidate.generation, **(proof or {})}


def read_market_direct_start(host, plan):
    _validate_plan(plan)
    pointer = host.directory / "cohort-release.json"
    current = _read(pointer)
    require(current is not None and current.get("kind") == _KIND
            and current.get("plan_sha256") == plan["plan_sha256"], "MARKET_DIRECT_START_ATTEMPT_INVALID")
    active, preimage, _ = market_start_preimage(home=host.home)
    new = registry(plan["new"])
    bound = active == new
    require(bound or preimage == plan["registry_sha256"], "MARKET_DIRECT_START_BINDING_DRIFT")
    target = host.read_target(plan, bound=bound)
    require(_read(pointer) == current and market_start_preimage(home=host.home)[1] == preimage,
            "MARKET_DIRECT_START_READBACK_DRIFT")
    return {"status": "readback", "phase": current["phase"], "registry": "new" if bound else "previous",
            "redis": target}


def cancel_uncommitted_market_direct_start(host, plan):
    with deployment_lock(runtime_dir=host.directory):
        proof = read_market_direct_start(host, plan)
        empty = proof["redis"] == "empty" and proof["phase"] in {"parking", "staging"}
        staged = proof["redis"] == "staged" and proof["phase"] in {"staging", "installing", "committing"}
        require(proof["registry"] == "previous" and (empty or staged), "MARKET_DIRECT_START_CANCEL_UNPROVEN")
        path = host.directory / "cohort-release.json"
        _write(path, {**_read(path), "phase": "cancelled"})
        return {"status": "cancelled", "target_retained": staged}


class MarketDirectStartHost(MarketCohortHost):
    def release(self, root, tag, commit, previous):
        from app.runtime_cohort import _require_forward_application_release

        require(root == Path(__file__).resolve().parents[3] and not os.path.lexists(root / ".env"),
                "MARKET_DIRECT_START_RELEASE_INVALID")
        self.verify_release(root, tag, commit)
        _require_forward_application_release(tag, previous)
        require(Path(sys.prefix).resolve() == (root / "services/quant-api/.venv").resolve(),
                "MARKET_DIRECT_START_PYTHON_UNPROVEN")
        require_locked_core()
        chart_pin = json.loads((root / "packages/quant-chart/package.json").read_bytes())["version"]
        chart_installed = json.loads((root / "apps/quant-web/node_modules/@guiyi/quant-chart/package.json").read_bytes())
        require(chart_installed["version"] == chart_pin
                and (root / "apps/quant-web/dist/index.html").is_file(), "MARKET_DIRECT_START_BUILD_UNPROVEN")
        self._verify_web_dependencies(root)
        require(not root.is_relative_to(self.directory), "MARKET_DIRECT_START_RELEASE_INVALID")
        return self.contracts(root), _candidate_market_component(root)

    def settings(self):
        raw, settings = _private_configuration(self.target_config)
        require(raw.splitlines().count(_TICK_MARKER) == 1, "MARKET_DIRECT_START_CONFIG_INVALID")
        if os.path.lexists(self.project_config):
            _, existing = _private_configuration(self.project_config)
            require(self._storage(settings) == self._storage(existing)
                    and (urlsplit(settings["REDIS_URL"]).port or 6379)
                    != (urlsplit(existing["REDIS_URL"]).port or 6379),
                    "MARKET_DIRECT_START_STORAGE_IDENTITY_DRIFT")
        return settings, sha256(raw).hexdigest()

    def authority(self, settings, root, day):
        now = self.now()
        with self._catalog_session(settings) as (session, canonical):
            installed = session.scalars(text("SELECT version_num FROM alembic_version")).all()
            heads = ScriptDirectory(str(root / "services/quant-api/alembic")).get_heads()
            require(len(heads) == 1 and installed == heads, "MARKET_DIRECT_START_SCHEMA_UNPROVEN")
            resolver = MarketPhaseResolver(session)
            market = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
            phases, subscriptions, windows, prior_days = {}, {}, {}, set()
            for product in load_operational_products():
                phase = resolver.resolve(product, now)
                starts = market.session_windows(symbol=product, trading_day=day)
                first = min(window.start for window in starts)
                require(phase.phase is MarketPhase.CLOSED and phase.next_session_start == first
                        and first > now + timedelta(seconds=660)
                        and resolver.resolve(product, first).trading_day == day,
                        "MARKET_DIRECT_START_PREOPEN_UNPROVEN")
                subscriptions[product] = market.dominant_segment_for_day(product, day).contract
                phases[product] = {"phase": "CLOSED"}
                windows[product] = [[window.start.isoformat(), window.end.isoformat()] for window in starts]
                prior_days.add(resolver.completed_observation_trading_day(product, now))
            require(subscriptions and len(prior_days) == 1 and None not in prior_days,
                    "MARKET_DIRECT_START_PREOPEN_UNPROVEN")
            prior_day = prior_days.pop()
            require(prior_day < day, "MARKET_DIRECT_START_PREOPEN_UNPROVEN")
        return {"prior_day": prior_day.isoformat(), "subscriptions": subscriptions,
                "sessions_sha256": digest(windows), "phases": phases, "mode": "closed_idle",
                "first_session": min((datetime.fromisoformat(values[0][0]) for values in windows.values())).isoformat()}

    def active_authority(self, settings, root, day):
        """Prove a live intake boundary without asserting earlier observations."""
        now = self.now()
        code = "MARKET_DIRECT_START_ACTIVE_SESSION_UNPROVEN"
        with self._catalog_session(settings) as (session, canonical):
            installed = session.scalars(text("SELECT version_num FROM alembic_version")).all()
            heads = ScriptDirectory(str(root / "services/quant-api/alembic")).get_heads()
            require(len(heads) == 1 and installed == heads, "MARKET_DIRECT_START_SCHEMA_UNPROVEN")
            resolver = MarketPhaseResolver(session)
            market = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
            phases, subscriptions, windows, future_edges = {}, {}, {}, []
            for product in load_operational_products():
                phase = resolver.resolve(product, now)
                sessions = market.session_windows(symbol=product, trading_day=day)
                phase_window = next((window for window in sessions if window.start <= now < window.end), None)
                require(phase.phase is not MarketPhase.UNKNOWN, code)
                if phase_window is not None:
                    require(phase.phase is MarketPhase.TRADING and phase.trading_day == day
                            and phase.current_session == phase_window, code)
                else:
                    require(phase.phase is not MarketPhase.TRADING, code)
                phases[product] = {"phase": phase.phase.value}
                subscriptions[product] = market.dominant_segment_for_day(product, day).contract
                windows[product] = [[window.start.isoformat(), window.end.isoformat()] for window in sessions]
                future_edges.extend(edge for window in sessions for edge in (window.start, window.end) if edge > now)
            require(any(value["phase"] == MarketPhase.TRADING.value for value in phases.values())
                    and future_edges and min(future_edges) > now + timedelta(seconds=660), code)
        if os.path.lexists(self.project_config):
            _, legacy = _private_configuration(self.project_config)
            with _redis(legacy["REDIS_URL"]) as client:
                keys = [RedisLiveStore._subscription_key(day)]
                for kind in ("source", "completed"):
                    stream = ObservationStream(client, kind=kind)
                    keys.extend((stream.key(day), stream.identity_key(day)))
                require(not client.exists(*keys), "MARKET_DIRECT_START_ACTIVE_ORIGINALS_PRESENT")
        return {"subscriptions": subscriptions, "sessions_sha256": digest(windows), "phases": phases,
                "mode": _ACTIVE_SESSION, "window_end": min(future_edges).isoformat()}

    def target_instance(self, settings, authority):
        return self.empty_target(settings)

    def empty_target(self, settings):
        database, canonical = self._storage(settings)
        with _redis(settings["REDIS_URL"]) as client:
            formal_tick_fingerprint(client, database, canonical)
            require(not client.info("keyspace") and len(client.client_list()) == 1,
                    "MARKET_DIRECT_START_TARGET_NOT_EMPTY")
            return redis_instance(client)

    @staticmethod
    def _storage(settings):
        from sqlalchemy.engine import make_url
        from app.db.url import normalize_database_url

        return make_url(normalize_database_url(settings["DATABASE_URL"])), Path(settings["GUIYI_CANONICAL_DATA_ROOT"])

    def _target_arguments(self, plan, settings):
        database, canonical = self._storage(settings)
        return {"database": database, "canonical": canonical, "day": date.fromisoformat(plan["day"]),
                "subscriptions": plan["authority"]["subscriptions"], "expected_instance": plan["target_instance"],
                "alert_enabled": False}

    def stage(self, plan, settings, *, may_exist):
        arguments = self._target_arguments(plan, settings)
        with _redis(settings["REDIS_URL"]) as client:
            require(len(client.client_list()) == 1, "MARKET_DIRECT_START_TARGET_HAS_CLIENTS")
            if may_exist:
                # A lost Redis reply is resolved with an exact readback, never a second write.
                binding = read_staged_observations(client, **arguments)
            else:
                binding = stage_new_observations(client, old_instance=None, **arguments)
        self._prove_staged_warmup(
            registry(plan["new"]).services["market-feed"], settings, binding, direct=True,
            active_day=arguments["day"] if plan["authority"].get("mode") == _ACTIVE_SESSION else None,
        )

    def read_target(self, plan, *, bound):
        settings, config_hash = self.settings()
        require(config_hash == plan["config_sha256"], "MARKET_DIRECT_START_CONFIG_DRIFT")
        args = self._target_arguments(plan, settings)
        with _redis(settings["REDIS_URL"]) as client:
            require(redis_instance(client) == args["expected_instance"], "MARKET_DIRECT_START_TARGET_DRIFT")
            if not client.info("keyspace"):
                require(not bound, "MARKET_DIRECT_START_BASELINE_MISSING")
                return "empty"
            if bound:
                require_formal_tick_binding(client, args["database"], args["canonical"])
                require(formal_tick_initial_day(client) == args["day"], "MARKET_DIRECT_START_TARGET_DAY_DRIFT")
                return "bound"
            read_staged_observations(client, **args)
            return "staged"

    @contextmanager
    def guards_for_direct_start(self, new, settings):
        with (after_market_recovery_guard(root=self.directory / "live-recovery-guards", legacy_root=True),
              self._catalog_session(settings) as (session, canonical),
              self.owner_guards(new, create_missing=True)):
            lease = MarketCatalog(session, canonical).acquire_maintenance_lock(caller="market-direct-start")
            require(lease is not None, "MARKET_DIRECT_START_MAINTENANCE_BUSY")
            try:
                yield
            finally:
                lease.release()

    def _loaded_inventory(self, root):
        output = read_command(["/bin/launchctl", "print", f"gui/{os.getuid()}"], root=root)
        names = "|".join(sorted(_RUNTIME_SERVICES))
        pattern = re.compile(r"\bcom\.guiyi\.quant-(?:" + names + r")(?:-candidate-[a-f0-9]{32})?(?=\s|$)")
        return set(pattern.findall(output))

    def park(self, previous, new):
        root = Path(new.services["api"].root)
        known = {binding.label: binding for binding in previous.services.values()} if previous else {}
        require(self._loaded_inventory(root) <= set(known), "MARKET_DIRECT_START_UNOWNED_JOB")
        for label, binding in known.items():
            output = read_launchd_service(label, root=root)
            if output is not None:
                self._assert_old_job_idle(binding, output)
        for label, binding in known.items():
            output = read_launchd_service(label, root=root)
            if output is None:
                continue
            self._assert_old_job_idle(binding, output)
            target = f"gui/{os.getuid()}/{label}"
            self.launch("disable", target)
            output = read_launchd_service(label, root=root)
            if output is not None:
                self._assert_old_job_idle(binding, output)
                self.launch("bootout", target)
        self._assert_clear(root)

    def _assert_old_job_idle(self, binding, output):
        require(launchd_arguments(output) == authorized_program_arguments(binding, self.home)
                and re.findall(r"^\tstate = (.+)$", output, re.MULTILINE) in
                (["not running"], ["waiting"], ["spawn scheduled"])
                and not re.search(r"^\s*pid = ", output, re.MULTILINE), "MARKET_DIRECT_START_OLD_JOB_BUSY")

    def _assert_clear(self, root):
        require(not self._loaded_inventory(root), "MARKET_DIRECT_START_OLD_JOB_PRESENT")
        for port in (8000, 5173):
            with socket.socket() as listener:
                try:
                    listener.bind(("127.0.0.1", port))
                except OSError:
                    raise CohortError("MARKET_DIRECT_START_PORT_BUSY") from None

    def _plist(self, binding):
        root = Path(binding.root)
        payload = plistlib.loads((root / "deploy/launchd" / f"{binding.label}.plist.template").read_bytes())
        env = payload["EnvironmentVariables"]
        env.pop("GUIYI_ALERT_NOTIFICATION_CONFIG_PATH", None)
        env.update(GUIYI_PROJECT_ROOT=binding.root, GUIYI_RUNTIME_COMMIT=binding.commit,
                   GUIYI_RUNTIME_TAG=binding.tag, GUIYI_RUNTIME_GENERATION=str(binding.generation),
                   GUIYI_RUNTIME_HANDOVER_ENABLED="1", GUIYI_OBSERVATION_STREAM_ENABLED="1",
                   GUIYI_RUNTIME_ENV=str(self.target_config))
        payload.update(ProgramArguments=list(authorized_program_arguments(binding, self.home)),
                       WorkingDirectory=str(self.home) if binding.service in {"api", "web"} else binding.root,
                       Disabled=not binding.enabled)
        for key in ("StandardOutPath", "StandardErrorPath"):
            payload[key] = str(self.home / "Library/Logs/GuiyiQuant" / Path(payload[key]).name)
        if binding.service in CALENDARS:
            payload.update(RunAtLoad=False, KeepAlive=False)
        self.verify_plist(binding, payload)
        return plistlib.dumps(payload)

    def installation_preimage(self, new):
        paths = [self.directory / "run-local-service.sh", *(self.path(item) for item in new.services.values())]
        return {path.name: sha256(self.bytes(path)).hexdigest() if os.path.lexists(path) else None for path in paths}

    def _install_file(self, path, desired, attempt, expected, *, executable=False):
        before = self.bytes(path) if os.path.lexists(path) else None
        if before != desired:
            require((sha256(before).hexdigest() if before is not None else None) == expected[path.name],
                    "MARKET_DIRECT_START_INSTALL_DRIFT")
            original = attempt / (path.name + ".original")
            if original.exists():
                require(self.bytes(original) == before, "MARKET_DIRECT_START_INSTALL_DRIFT")
            elif before is not None:
                self._private_original(original, before)
                self._sync_directory(attempt)
            self._replace_plist(path, desired)
        if executable:
            path.chmod(0o700)

    def install_new(self, new, attempt, expected):
        root = Path(new.services["api"].root)
        logs = self.home / "Library/Logs/GuiyiQuant"
        logs.mkdir(mode=0o700, exist_ok=True)
        with safe_directory(logs), safe_directory(self.home / "Library/LaunchAgents"):
            for binding in new.services.values():
                self._install_file(self.path(binding), self._plist(binding), attempt, expected)
                if not binding.enabled:
                    self.launch("disable", f"gui/{os.getuid()}/{binding.label}")
        dispatcher = (root / "scripts/ops/macos/runtime-service-dispatch.sh").read_bytes()
        self._install_file(self.directory / "run-local-service.sh", dispatcher, attempt, expected, executable=True)
        for service, name in _MARKERS.items():
            if new.services[service].enabled:
                path = root / ".run" / name
                if os.path.lexists(path):
                    require(self.bytes(path) == b"enabled\n", "MARKET_DIRECT_START_MARKER_DRIFT")
                else:
                    self.install_marker(path)
        self.verify_installed(new)

    def verify_installed(self, new):
        require(all(self.bytes(self.path(binding)) == self._plist(binding) for binding in new.services.values()),
                "MARKET_DIRECT_START_INSTALL_DRIFT")
        root = Path(new.services["api"].root)
        require(self.bytes(self.directory / "run-local-service.sh")
                == self.bytes(root / "scripts/ops/macos/runtime-service-dispatch.sh"),
                "MARKET_DIRECT_START_LAUNCHER_DRIFT")

    def assert_ready_to_bind(self, plan, new, settings):
        from app.runtime_bootstrap import BootstrapBackend

        root = Path(new.services["api"].root)
        self._assert_clear(root)
        self.verify_installed(new)
        _, config_hash = self.settings()
        authority = plan["authority"]
        require(config_hash == plan["config_sha256"] and monotonic() < self.deadline
                and _read_authority(self, settings, root, date.fromisoformat(plan["day"]),
                                    active_session=authority.get("mode") == _ACTIVE_SESSION) == authority,
                "MARKET_DIRECT_START_AUTHORITY_DRIFT")
        self.verify_staged(plan, settings)
        for name in CALENDARS:
            if new.services[name].enabled:
                BootstrapBackend()._assert_recovery_calendar_safe(plistlib.loads(self._plist(new.services[name])))

    def verify_staged(self, plan, settings):
        with _redis(settings["REDIS_URL"]) as client:
            read_staged_observations(client, **self._target_arguments(plan, settings))

    def start_new(self, plan, *, verify_running_only):
        new = registry(plan["new"])
        settings, config_hash = self.settings()
        require(config_hash == plan["config_sha256"], "MARKET_DIRECT_START_CONFIG_DRIFT")
        self.verify_installed(new)
        root = Path(new.services["api"].root)
        expected = {binding.label for binding in new.services.values() if binding.enabled}
        require(self._loaded_inventory(root) <= expected, "MARKET_DIRECT_START_UNOWNED_JOB")

        def verify_loaded(binding, output):
            declarations = {"GUIYI_RUNTIME_ENV": str(self.target_config), "GUIYI_PROJECT_ROOT": binding.root,
                            "GUIYI_RUNTIME_COMMIT": binding.commit, "GUIYI_RUNTIME_TAG": binding.tag,
                            "GUIYI_RUNTIME_GENERATION": str(binding.generation)}
            require(output is not None and launchd_arguments(output) == authorized_program_arguments(binding, self.home)
                    and any(all(env.get(k) == value for k, value in declarations.items())
                            for env in launchd_environments(output)), "MARKET_DIRECT_START_LOADED_DRIFT")

        def start(name, *, only_verify=False):
            binding = new.services[name]
            if not binding.enabled:
                return
            output = read_launchd_service(binding.label, root=root)
            if output is None:
                require(not only_verify, "MARKET_DIRECT_START_MISSED_PREOPEN")
                (self.start_calendar if name in CALENDARS else self.start)(binding)
            else:
                verify_loaded(binding, output)

        authority = plan["authority"]
        probe = {**plan, "window": authority, "market_source_handover": {
            "old_day": authority.get("prior_day"), "target_instance": plan["target_instance"]}}
        args = self._target_arguments(plan, settings)
        require(self.read_target(plan, bound=True) == "bound", "MARKET_DIRECT_START_BASELINE_MISSING")
        consumers = ("api", "web", "live", "reference-worker")
        for name in consumers:
            start(name, only_verify=verify_running_only)
        if not verify_running_only:
            self._await_direct(probe, settings, args, feed=False)
        start("market-feed", only_verify=verify_running_only)
        if not verify_running_only:
            self._await_direct(probe, settings, args, feed=True)
        else:
            for name in (*consumers, "market-feed"):
                binding = new.services[name]
                state = read_service_state(name, runtime_dir=self.directory)
                require(state and state.get("phase") == "active" and state.get("ready") is True
                        and state.get("generation") == binding.generation
                        and owner_process_matches(state, binding)
                        and 0 <= (self.now() - datetime.fromisoformat(state["at"])).total_seconds() <= 30,
                        "MARKET_DIRECT_START_OWNERS_NOT_READY")
        self.verify_continuous_identity(probe)
        proof = None
        if authority.get("mode") == _ACTIVE_SESSION:
            proof = self.verify_active_minutes(plan, settings, args)
        for name in CALENDARS:
            start(name)
            if new.services[name].enabled:
                self.verify_calendar(new.services[name])
        for binding in new.services.values():
            output = read_launchd_service(binding.label, root=root)
            if binding.enabled:
                verify_loaded(binding, output)
            else:
                require(output is None, "MARKET_DIRECT_START_DISABLED_JOB_PRESENT")
        return proof

    def verify_active_minutes(self, plan, settings, args):
        day = args["day"]
        with self._catalog_session(settings) as (session, canonical):
            market = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
            sessions = {product: (contract, market.session_windows(symbol=product, trading_day=day))
                        for product, contract in args["subscriptions"].items()}
        windows = {product: [[window.start.isoformat(), window.end.isoformat()] for window in rows]
                   for product, (_, rows) in sessions.items()}
        require(digest(windows) == plan["authority"]["sessions_sha256"], "MARKET_DIRECT_START_AUTHORITY_DRIFT")
        with _redis(settings["REDIS_URL"]) as client:
            require(redis_instance(client) == args["expected_instance"], "MARKET_DIRECT_START_TARGET_DRIFT")
            result = read_first_completed_minutes(client, day, sessions=sessions, now=self.now())
        cutoff = datetime.fromisoformat(plan["created_at"])
        verified = [row for row in result["products"].values()
                    if row["status"] == "verified" and datetime.fromisoformat(row["bar_end"]) >= cutoff]
        require(verified, "MARKET_DIRECT_START_ACTIVE_MINUTE_UNPROVEN")
        return {"activation_mode": _ACTIVE_SESSION, "opening_prefix": "not_observed",
                "first_completed_products": len(verified), "products": len(sessions)}

    def _await_direct(self, plan, settings, args, *, feed):
        from time import sleep

        active = plan["authority"].get("mode") == _ACTIVE_SESSION
        while monotonic() < self.deadline:
            if active:
                ready = self._active_target_ready(plan, settings, args, feed=feed)
            else:
                ready = self._ready_on_target(plan, settings, args, feed=feed) is not None
            if ready:
                return
            sleep(0.2)
        raise CohortError("MARKET_DIRECT_START_OWNERS_NOT_READY")

    def _active_target_ready(self, plan, settings, args, *, feed):
        new = registry(plan["new"])
        day = args["day"]
        now = self.now()
        require(now < datetime.fromisoformat(plan["authority"]["window_end"]),
                "MARKET_DIRECT_START_ACTIVE_SESSION_EXPIRED")
        names = ("api", "web", "reference-worker", "live") + (("market-feed",) if feed else ())
        with _redis(settings["REDIS_URL"]) as client:
            require(redis_instance(client) == args["expected_instance"], "MARKET_DIRECT_START_TARGET_DRIFT")
            require_formal_tick_binding(client, args["database"], args["canonical"])
            stream = ObservationStream(client, kind="source")
            require(stream.registered_day("live") == day
                    and RedisLiveStore(client).subscriptions(day) == args["subscriptions"],
                    "MARKET_DIRECT_START_TARGET_DAY_DRIFT")
            for name in names:
                binding = new.services[name]
                state = read_service_state(name, runtime_dir=self.directory)
                if not (state and state.get("phase") == "active" and state.get("ready") is True
                        and state.get("generation") == binding.generation
                        and owner_process_matches(state, binding)
                        and not owner_lock_available(name, runtime_dir=self.directory)
                        and 0 <= (now - datetime.fromisoformat(state["at"])).total_seconds() <= 30):
                    return False
                if name == "reference-worker" and state.get("proof", {}).get("reference_receipts") not in {
                    "waiting_archive", "current",
                }:
                    return False
                key = {"live": "live:heartbeat", "market-feed": "live:feed:heartbeat"}.get(name)
                if key:
                    pulse = json.loads(client.get(key) or b"{}")
                    if not (pulse.get("runtime_commit") == binding.commit
                            and pulse.get("runtime_generation") == binding.generation
                            and pulse.get("runtime_root") == binding.root
                            and pulse.get("runtime_tag") == binding.tag):
                        return False
                    generated = datetime.fromisoformat(pulse["generated_at"])
                    if not (generated <= datetime.fromisoformat(state["at"])
                            and 0 <= (now - generated).total_seconds() <= 30):
                        return False
                    if feed and pulse.get("available") is not True:
                        return False
                    if name == "market-feed":
                        phases = {p: proof["phase"] for p, proof in plan["authority"]["phases"].items()}
                        if not (pulse.get("registered_day") == day.isoformat()
                                and "input_failure" in pulse and pulse["input_failure"] is None
                                and pulse.get("phase_by_product") == phases
                                and pulse.get("operational_count") == len(phases)
                                and pulse.get("subscribed_count") == sum(v == MarketPhase.TRADING.value for v in phases.values())):
                            return False
            if feed and (stream.cursor("live", day) == "0-0"
                         or ObservationStream(client, kind="completed").tail(day) == "0-0"):
                return False
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--candidate-root", required=True, type=Path)
    plan_parser.add_argument("--tag", required=True)
    plan_parser.add_argument("--commit", required=True)
    plan_parser.add_argument("--trading-day", required=True, type=date.fromisoformat)
    mode = plan_parser.add_mutually_exclusive_group()
    mode.add_argument("--active-session", action="store_true")
    mode.add_argument("--preserve-tick-journal", action="store_true")
    mode.add_argument("--retire-rs-in-quiet-window", action="store_true")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--plan", required=True, type=Path)
    apply_parser.add_argument("--resume", action="store_true")
    read_parser = sub.add_parser("read")
    read_parser.add_argument("--plan", required=True, type=Path)
    cancel_parser = sub.add_parser("cancel-uncommitted")
    cancel_parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        require(sys.platform == "darwin", "MARKET_DIRECT_START_MACOS_REQUIRED")
        host = MarketDirectStartHost()
        if args.mode == "plan":
            if args.preserve_tick_journal:
                from app.runtime_market_scope_cutover import JournalPreservingMarketStartHost

                host = JournalPreservingMarketStartHost()
            if args.retire_rs_in_quiet_window:
                from app.runtime_market_scope_cutover import QuietWindowMarketStartHost

                host = QuietWindowMarketStartHost()
            result = freeze_market_direct_start(host, root=args.candidate_root, tag=args.tag,
                                                commit=args.commit, day=args.trading_day, active_session=args.active_session)
        else:
            _, plan = _resolution_source(args.plan)
            _validate_plan(plan)
            retained = plan["authority"].get("retained_tick")
            if retained is not None:
                from app.runtime_market_scope_cutover import JournalPreservingMarketStartHost, QuietWindowMarketStartHost

                host = QuietWindowMarketStartHost(retained) if retained.get("quiet_window") else JournalPreservingMarketStartHost(retained)
            if args.mode == "read":
                result = read_market_direct_start(host, plan)
                if retained is not None and result["phase"] == "switched":
                    result.update(host.verify_scope_api(plan))
            elif args.mode == "cancel-uncommitted":
                result = cancel_uncommitted_market_direct_start(host, plan)
            else:
                require(not Path(_candidate(plan).root).is_relative_to("/Volumes")
                        or os.environ.get("GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD") == "1",
                        "MARKET_DIRECT_START_EXTERNAL_VOLUME_REQUIRED")
                result = apply_market_direct_start(host, plan, resume=args.resume)
    except Exception as exc:
        code = str(exc) if isinstance(exc, CohortError) else "MARKET_DIRECT_START_UNAVAILABLE"
        result = {"status": "blocked", "code": code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", code)
                  else "MARKET_DIRECT_START_UNAVAILABLE"}
    print(json.dumps(result, sort_keys=True))
    return int(result.get("status") == "blocked")


if __name__ == "__main__":
    raise SystemExit(main())
