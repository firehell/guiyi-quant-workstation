"""Hand over the two workstation ports without activating retired or Market peers."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import stat

from app.api.workstation_settings import PLUS, PROFILE, READER, profile
from app.backtest_center.experiments import _path as experiment_path
from app.backtest_center.store import RunStore
from app.core.env import PROJECT_ROOT
from app.runtime_bindings import BindingRegistry, MARKET_RECOVERY_SERVICES, _write_bindings, authorized_program_arguments, market_start_preimage
from app.runtime_cohort import require
from app.runtime_cohort_errors import CohortError
from app.runtime_deployment import LaunchdBackend, assert_no_unknown_deployment, execute_handover
from app.runtime_handover import deployment_lock
from app.runtime_identity import file_snapshot, launchd_environments, read_launchd_service
from app.runtime_market_recovery import RecoveryHost
from app.runtime_workstation_forward import PAIR
from app.version import APP_VERSION

LIVE_PEERS = MARKET_RECOVERY_SERVICES - set(PAIR)
RETIRED = {"log-rotate", "weekly-audit", "home-projection"}


@contextmanager
def quiet_backtest(path, *, reserve):
    """Fence submissions/claims through API drain and check for a first experiment store race."""
    reader = RunStore.open_reader(path)
    require(reader.path == path, "WORKSTATION_BACKTEST_STORE_UNPROVEN")
    experiments = experiment_path(reader)
    tables = [(path, "SELECT 1 FROM bt_runs WHERE status NOT IN ('SUCCEEDED','FAILED','CANCELED') LIMIT 1")]
    existed = os.path.lexists(experiments)
    if existed:
        tables.append((experiments, "SELECT 1 FROM experiments WHERE status NOT IN ('SUCCEEDED','INSUFFICIENT') LIMIT 1"))
    with ExitStack() as stack:
        for location, sql in tables:
            before = location.lstat()
            require(location.resolve(strict=True) == location and stat.S_ISREG(before.st_mode)
                    and before.st_uid == os.getuid() and before.st_nlink == 1 and not before.st_mode & 0o022,
                    "WORKSTATION_BACKTEST_STORE_UNPROVEN")
            db = stack.enter_context(closing(sqlite3.connect(
                location.as_uri() + ("?mode=rw" if reserve else "?mode=ro"),
                uri=True, isolation_level=None, timeout=3,
            )))
            db.execute("BEGIN IMMEDIATE" if reserve else "BEGIN")
            require(db.execute(sql).fetchone() is None, "WORKSTATION_BACKTEST_BUSY")
            after = location.lstat()
            require(os.path.samestat(before, after), "WORKSTATION_BACKTEST_STORE_DRIFT")
        yield
        require(existed == os.path.lexists(experiments), "WORKSTATION_BACKTEST_STORE_DRIFT")


def commit_port(previous, expected, candidate, *, home):
    """CAS only one prepared and strictly live port; preserve every other inventory row."""
    name = candidate.service
    require(name in PAIR and candidate.enabled and candidate.launchd_label and previous.services[name].enabled,
            "WORKSTATION_PORT_SCOPE_INVALID")
    candidate.__post_init__()
    others = [v.generation for k, v in previous.services.items()
              if k != name and (v.root, v.commit, v.tag) != (candidate.root, candidate.commit, candidate.tag)]
    require(candidate.generation == max(others + [previous.services[name].generation]) + 1,
            "WORKSTATION_PORT_GENERATION_DRIFT")
    target = BindingRegistry(1, {**previous.services, name: candidate})

    def recheck(*, home):
        actual, digest, _ = market_start_preimage(home=home)
        require(actual == previous and digest == expected, "WORKSTATION_PORT_INVENTORY_DRIFT")
        return digest

    return _write_bindings(target, home, expected, recheck, live_services={name: candidate})


class WorkstationPortBackend(LaunchdBackend):
    def __init__(self, path, check_candidate, ready):
        super().__init__()
        self.path = path
        self.check_candidate = check_candidate
        self.ready = ready

    def drain_owner(self, service, binding, request):
        self.check_candidate(self.candidates[service])
        if service == "api":
            with quiet_backtest(self.path, reserve=True):
                return super().drain_owner(service, binding, request)
        return super().drain_owner(service, binding, request)


    def verify(self, service, binding, request):
        if not super().verify(service, binding, request):
            return False
        self.ready({service: self.candidates[service]})
        return True


def protected(host, registry, root):
    require(registry.services.keys() == MARKET_RECOVERY_SERVICES | RETIRED, "WORKSTATION_PEER_SET_DRIFT")
    old_peers = host.evidence(registry, root, peers_only=True, skip_names=MARKET_RECOVERY_SERVICES)
    current_peers = {}
    for name in sorted(LIVE_PEERS):
        item = registry.services[name]
        raw = host.bytes(host.path(item))
        require(item.enabled and item.launchd_label is None and raw == host._plist(item),
                "WORKSTATION_PEER_PLIST_DRIFT")
        proof = host.prove_running(item)
        current_peers[name] = {"pid": proof["pid"] if proof else None, "plist": sha256(raw).hexdigest()}
    return {"legacy": old_peers, "running": current_peers}


def expected_definition(host, item):
    original = replace(item, launchd_label=None)
    payload = plistlib.loads(host._plist(original))
    payload.update(Label=item.label, ProgramArguments=list(authorized_program_arguments(item, host.home)))
    return payload


def isolated_port(host, item, root):
    output = read_launchd_service(item.label, root=root)
    require(output, "WORKSTATION_PORT_NOT_LOADED")
    host.verify_loaded(item, output)
    isolated = PLUS | {READER, "GUIYI_BACKTEST_STORE", "GUIYI_BACKTEST_CODE_REVISION"}
    require(not any(env.keys() & isolated for env in launchd_environments(output)), "WORKSTATION_PORT_ENV_CONFLICT")


def validate(host, root, tag, commit):
    assert_no_unknown_deployment()
    previous, _, _ = host.inventory()
    require(previous and tag == "v" + APP_VERSION, "WORKSTATION_CANDIDATE_INVALID")
    require(all(name in previous.services for name in PAIR), "WORKSTATION_PORT_SCOPE_INVALID")
    completed = {name for name in PAIR if (previous.services[name].root, previous.services[name].tag,
                 previous.services[name].commit) == (str(root), tag, commit)}
    prior = BindingRegistry(1, {k: v for k, v in previous.services.items() if k not in completed})
    contracts = host.verify_application_release(root, tag, commit, prior)
    for name in MARKET_RECOVERY_SERVICES:
        item = previous.services[name]
        host.verify_release(Path(item.root), item.tag, item.commit)
        require(item.contracts == contracts == host.contracts(Path(item.root)), "WORKSTATION_SHARED_CONTRACT_DRIFT")
    settings, market_config = host.settings()
    from app.runtime_workstation_schema import verify_installed_schema

    verify_installed_schema(root, settings["DATABASE_URL"])
    require(host.bytes(host.directory / "run-local-service.sh")
            == host.bytes(root / "scripts/ops/macos/runtime-service-dispatch.sh"), "WORKSTATION_DISPATCHER_DRIFT")
    values, profile_hash = profile(host.directory / PROFILE)
    require(PLUS <= values.keys() and Path(values["GUIYI_BACKTEST_PLUS_PYTHON"]).is_file()
            and os.access(values["GUIYI_BACKTEST_PLUS_PYTHON"], os.X_OK)
            and Path(values["GUIYI_BACKTEST_PLUS_BUNDLE"]).is_dir()
            and Path(values["GUIYI_BACKTEST_PLUS_COST_PROFILE"]).is_file(), "WORKSTATION_API_PROFILE_INCOMPLETE")
    held = protected(host, previous, root)
    for name in PAIR:
        item = previous.services[name]
        require(item.enabled and (name in completed or item.launchd_label is None),
                "WORKSTATION_OLD_PORT_IDENTITY_UNSUPPORTED")
        actual = plistlib.loads(host.bytes(host.path(item)))
        expected_plist = expected_definition(host, item)
        require(actual == expected_plist, "WORKSTATION_PORT_PLIST_DRIFT")
        host.ready({name: item})
        isolated_port(host, item, root)
        require(not os.path.lexists(Path(item.root) / ".env"), "WORKSTATION_PORT_ENV_CONFLICT")
    path = host.home / ".local/state/guiyi/backtest-center/research.sqlite3"
    if "api" not in completed:
        with quiet_backtest(path, reserve=False):
            pass
    generation = max(v.generation for v in prior.services.values()) + 1
    require(all(previous.services[n].generation == generation for n in completed), "WORKSTATION_PORT_GENERATION_DRIFT")
    return previous, completed, generation, market_config, profile_hash, held, path


def run(host, operation, root, tag, commit):
    previous, completed, generation, market_config, profile_hash, peers, path = validate(host, root, tag, commit)
    pending = [name for name in PAIR if name not in completed]
    if operation == "apply":
        for name in pending:
            old = previous.services[name]
            require(market_start_preimage(home=host.home)[0] == previous, "WORKSTATION_PORT_INVENTORY_DRIFT")
            expected = host.inventory()[1]
            new = replace(old, root=str(root), commit=commit, tag=tag, generation=generation)
            def check_candidate(candidate):
                isolated_port(host, candidate, root)
                proposed = BindingRegistry(1, {**previous.services, name: candidate})
                require(protected(host, proposed, root) == peers, "WORKSTATION_PEER_DRIFT")
                require(host.settings()[1] == market_config and profile(host.directory / PROFILE)[1] == profile_hash,
                        "WORKSTATION_CONFIGURATION_DRIFT")
                require(plistlib.loads(host.bytes(host.path(candidate))) == expected_definition(host, candidate),
                        "WORKSTATION_PORT_PLIST_DRIFT")
                require(host.inventory()[:2] == (previous, expected), "WORKSTATION_PORT_INVENTORY_DRIFT")

            backend = WorkstationPortBackend(path, check_candidate, host.ready)

            def commit_prepared():
                commit_port(previous, expected, backend.candidates[name], home=host.home)

            result = execute_handover(name, old, new, backend=backend, commit_binding=commit_prepared)
            require(result == "switched", "WORKSTATION_PORT_HANDOVER_INCOMPLETE")
            actual, _, _ = host.inventory()
            require(actual.services == {**previous.services, name: backend.candidates[name]},
                    "WORKSTATION_PORT_INVENTORY_DRIFT")
            host.ready({name: actual.services[name]})
            previous = actual
        require(protected(host, previous, root) == peers, "WORKSTATION_PEER_DRIFT")
        pending = []
    return {"status": "ready_to_switch" if pending else "switched", "pending": pending,
            "tag": tag, "commit": commit, "generation": generation, "market_config_sha256": market_config,
            "profile_sha256": profile_hash, "market_peers": peers["running"]}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("check", "apply"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    try:
        with deployment_lock():
            result = run(RecoveryHost(), args.operation, PROJECT_ROOT, args.tag, args.commit)
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        code = str(exc) if isinstance(exc, (CohortError, RuntimeError, ValueError)) else ""
        if not re.fullmatch("[A-Z][A-Z0-9_]{2,95}", code):
            code = "WORKSTATION_PORT_EVIDENCE_UNAVAILABLE"
        print(json.dumps({"status": "blocked", "code": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
