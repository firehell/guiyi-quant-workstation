"""Forward-only replacement of two inactive desktop ports at an exact application release."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import plistlib
import re
import socket
import sys
import time

from app.reference_trading.recovery_campaign import digest
from app.runtime_bindings import (
    ServiceBinding,
    authorized_program_arguments,
    contract_fingerprints,
    market_start_preimage,
    write_workstation_pair,
)
from app.runtime_bootstrap import parse_disabled_states
from app.runtime_cohort import require
from app.runtime_cohort_errors import CohortError
from app.runtime_contracts import REQUIRED_SERVICES
from app.runtime_deployment import assert_no_unknown_deployment, owner_process_matches
from app.runtime_handover import _read, _write, deployment_lock, owner_lock_available, read_service_state
from app.runtime_identity import (
    command_result,
    file_snapshot,
    launchd_arguments,
    launchd_environments,
    read_command,
    read_launchd_service,
)
from app.runtime_market_direct_start import MarketDirectStartHost
from app.runtime_workstation_schema import verify_installed_schema

PAIR = ("api", "web")
EXTERNAL = (
    "com.guiyi.quant-subing-paper",
    "com.guiyi.quant-simnow",
    "com.guiyi.quant-tqkq-simulation",
    "com.guiyi.quant-subing-development-model",
)
KIND = "workstation_api_web_forward_v1"


def closed_ports():
    for port in (8000, 5173):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise CohortError("WORKSTATION_PORT_BUSY") from None


def idle(output):
    return re.findall(r"^\tstate = (.+)$", output, re.M) in (
        ["not running"],
        ["waiting"],
        ["spawn scheduled"],
    ) and not re.search(r"^\s*pid = ", output, re.M)


def same_declarations(output, expected):
    return any(
        all(env.get(k) == value for k, value in expected.items()) for env in launchd_environments(output)
    )


class WorkstationHost(MarketDirectStartHost):
    def inventory(self):
        return market_start_preimage(home=self.home)

    def authorities(self, root):
        disabled = parse_disabled_states(
            read_command(["/bin/launchctl", "print-disabled", f"gui/{os.getuid()}"], root=root).encode()
        )
        known = self._loaded_inventory(root)
        return disabled, known

    def evidence(self, previous, root, *, peers_only=False):
        require(REQUIRED_SERVICES <= previous.services.keys(), "WORKSTATION_INVENTORY_INCOMPLETE")
        disabled, loaded = self.authorities(root)
        permitted = {b.label for b in previous.services.values()}
        if peers_only:
            permitted.update("com.guiyi.quant-" + name for name in PAIR)
        require(loaded <= permitted, "WORKSTATION_UNOWNED_JOB")
        rows = {}
        historic_contracts = {}
        for name, binding in sorted(previous.services.items()):
            if peers_only and name in PAIR:
                continue
            key = (binding.tag, binding.commit)
            if key not in historic_contracts:
                tag_ref = "refs/tags/" + binding.tag
                git = ["/usr/bin/git", "-c", "core.fsmonitor=false"]
                require(
                    read_command([*git, "cat-file", "-t", tag_ref], root=root) == "tag"
                    and read_command([*git, "rev-parse", tag_ref + "^{commit}"], root=root)
                    == binding.commit,
                    "WORKSTATION_SUPERSEDED_TAG_UNPROVEN",
                )
                historic_contracts[key] = contract_fingerprints(root, revision=binding.commit)
            require(binding.contracts == historic_contracts[key], "WORKSTATION_SUPERSEDED_CONTRACT_DRIFT")
            oldroot = Path(binding.root)
            require(
                not os.path.lexists(oldroot)
                and not root.is_relative_to(oldroot)
                and not oldroot.is_relative_to(root),
                "WORKSTATION_OLD_ROOT_RUNNABLE",
            )
            require(oldroot == oldroot.resolve(), "WORKSTATION_OLD_ROOT_DRIFT")
            label = binding.label
            path = self.path(binding)
            raw = file_snapshot(path)[0] if os.path.lexists(path) else None
            output = read_launchd_service(label, root=root)
            require(bool(output) == (label in loaded), "WORKSTATION_LAUNCHD_READBACK_DRIFT")
            env = {
                "GUIYI_PROJECT_ROOT": binding.root,
                "GUIYI_RUNTIME_COMMIT": binding.commit,
                "GUIYI_RUNTIME_TAG": binding.tag,
                "GUIYI_RUNTIME_GENERATION": str(binding.generation),
            }
            if raw is not None:
                plist = plistlib.loads(raw)
                require(
                    plist.get("Label") == label
                    and tuple(plist.get("ProgramArguments", ()))
                    == authorized_program_arguments(binding, self.home)
                    and all(plist.get("EnvironmentVariables", {}).get(k) == v for k, v in env.items()),
                    "WORKSTATION_INSTALLED_IDENTITY_UNPROVEN",
                )
            require(raw is not None or not binding.enabled and output is None, "WORKSTATION_PLIST_MISSING")
            if output:
                self._assert_old_job_idle(binding, output)
                require(same_declarations(output, env), "WORKSTATION_LOADED_IDENTITY_UNPROVEN")
            if (self.directory / f"{name}.owner.lock").exists():
                require(owner_lock_available(name, runtime_dir=self.directory), "WORKSTATION_OWNER_BUSY")
            rows[name] = {
                "label": label,
                "loaded": bool(output),
                "disabled": disabled.get(label),
                "plist": sha256(raw).hexdigest() if raw is not None else None,
            }
        for label in EXTERNAL:
            output = read_launchd_service(label, root=root)
            path = self.home / "Library/LaunchAgents" / (label + ".plist")
            raw = file_snapshot(path)[0] if os.path.lexists(path) else None
            if raw is not None or output:
                require(raw and label == EXTERNAL[0], "WORKSTATION_EXTERNAL_ACCOUNT_PRESENT")
                args = plistlib.loads(raw).get("ProgramArguments", [])
                require(
                    len(args) == 3
                    and args[0] == "/bin/bash"
                    and Path(args[2]).is_absolute()
                    and args[1] == str(Path(args[2]) / "scripts/ops/macos/run-subing-paper.sh")
                    and not os.path.lexists(args[2])
                    and not root.is_relative_to(Path(args[2]))
                    and (not output or idle(output) and launchd_arguments(output) == tuple(args)),
                    "WORKSTATION_EXTERNAL_ACCOUNT_RUNNABLE",
                )
            rows[label] = {
                "loaded": bool(output),
                "disabled": disabled.get(label),
                "plist": sha256(raw).hexdigest() if raw is not None else None,
            }
        # Old candidate files outside the current registry must be disabled at login.
        for name in PAIR:
            for path in sorted(
                (self.home / "Library/LaunchAgents").glob(f"com.guiyi.quant-{name}-candidate-*.plist")
            ):
                label = path.stem
                if label in permitted:
                    continue
                require(
                    disabled.get(label) is True and read_launchd_service(label, root=root) is None,
                    "WORKSTATION_RETIRED_CANDIDATE_RUNNABLE",
                )
                rows[label] = {"disabled": True, "plist": sha256(file_snapshot(path)[0]).hexdigest()}
        return rows

    def assert_no_backtest_autostart(self, root):
        # The API lifespan recovers existing runs when a configured store exists.
        inherited = read_command(["/bin/launchctl", "getenv", "GUIYI_BACKTEST_STORE"], root=root)
        raw = file_snapshot(self.target_config, private=True)[0]
        require(
            not inherited
            and not re.search(rb"(?m)^\s*(?:export\s+)?GUIYI_BACKTEST_STORE\s*=", raw)
            and not os.path.lexists(self.home / ".local/state/guiyi/backtest-center/research.sqlite3"),
            "WORKSTATION_BACKTEST_AUTOSTART_UNPROVEN",
        )

    def candidate(self, root, tag, commit, previous):
        self.assert_no_backtest_autostart(root)
        contracts = self.verify_application_release(root, tag, commit, previous)
        settings, config_hash = self.settings()
        schema = verify_installed_schema(root, settings["DATABASE_URL"])
        require(
            self.bytes(self.directory / "run-local-service.sh")
            == (root / "scripts/ops/macos/runtime-service-dispatch.sh").read_bytes(),
            "WORKSTATION_DISPATCHER_DRIFT",
        )
        generation = max(b.generation for b in previous.services.values()) + 1
        return (
            {n: ServiceBinding(n, str(root), tag, commit, generation, True, contracts) for n in PAIR},
            config_hash,
            schema,
        )

    def verify_targets_absent(self, pair):
        root = Path(pair["api"].root)
        for binding in pair.values():
            require(
                not os.path.lexists(self.path(binding))
                and read_launchd_service(binding.label, root=root) is None,
                "WORKSTATION_TARGET_LABEL_PRESENT",
            )
        closed_ports()

    def commit_pair(self, pair, before):
        return write_workstation_pair(pair, expected_sha256=before, home=self.home)

    def park_old_pair(self, old_pair, root):
        for previous in old_pair.values():
            output = read_launchd_service(previous.label, root=root)
            if output:
                self._assert_old_job_idle(previous, output)
            target = f"gui/{os.getuid()}/{previous.label}"
            self.launch("disable", target)
            if output:
                self.launch("bootout", target)
            disabled, _ = self.authorities(root)
            require(
                disabled.get(previous.label) is True
                and read_launchd_service(previous.label, root=root) is None,
                "WORKSTATION_OLD_PORT_STILL_LOADED",
            )

    def preflight_start(self, pair, *, resume=False):
        parked = []
        for binding in pair.values():
            root = Path(binding.root)
            path = self.path(binding)
            if os.path.lexists(path):
                require(self.bytes(path) == self._plist(binding), "WORKSTATION_TARGET_PLIST_DRIFT")
            output = read_launchd_service(binding.label, root=root)
            if output:
                self.verify_loaded(binding, output)
                if idle(output):
                    require(
                        resume and owner_lock_available(binding.service, runtime_dir=self.directory),
                        "WORKSTATION_TARGET_RUNNING_UNPROVEN",
                    )
                    parked.append(binding)
                else:
                    owner = read_service_state(binding.service, runtime_dir=self.directory)
                    require(
                        owner
                        and owner.get("generation") == binding.generation
                        and owner_process_matches(owner, binding)
                        and self.owns_http(binding, owner["pid"]),
                        "WORKSTATION_TARGET_RUNNING_UNPROVEN",
                    )
                    continue
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", 8000 if binding.service == "api" else 5173))
                except OSError:
                    raise CohortError("WORKSTATION_PORT_BUSY") from None
        # Both endpoints were classified before mutating an exact idle startup.
        for binding in parked:
            root = Path(binding.root)
            target = f"gui/{os.getuid()}/{binding.label}"
            output = read_launchd_service(binding.label, root=root)
            require(output and idle(output), "WORKSTATION_TARGET_RUNNING_UNPROVEN")
            self.verify_loaded(binding, output)
            self.launch("disable", target)
            output = read_launchd_service(binding.label, root=root)
            if output:
                require(idle(output), "WORKSTATION_TARGET_RUNNING_UNPROVEN")
                self.verify_loaded(binding, output)
                self.launch("bootout", target)
            disabled, _ = self.authorities(root)
            require(
                disabled.get(binding.label) is True
                and read_launchd_service(binding.label, root=root) is None,
                "WORKSTATION_TARGET_STOP_UNKNOWN",
            )

    def install_pair(self, pair, attempt):
        for binding in pair.values():
            path = self.path(binding)
            wanted = self._plist(binding)
            if os.path.lexists(path):
                require(self.bytes(path) == wanted, "WORKSTATION_TARGET_PLIST_DRIFT")
            else:
                self._install_file(path, wanted, attempt, {path.name: None})
            output = read_launchd_service(binding.label, root=Path(binding.root))
            if output is None:
                self.start(binding)
            else:
                self.verify_loaded(binding, output)

    def verify_loaded(self, binding, output):
        require(
            launchd_arguments(output) == authorized_program_arguments(binding, self.home)
            and same_declarations(
                output,
                {
                    "GUIYI_PROJECT_ROOT": binding.root,
                    "GUIYI_RUNTIME_COMMIT": binding.commit,
                    "GUIYI_RUNTIME_TAG": binding.tag,
                    "GUIYI_RUNTIME_GENERATION": str(binding.generation),
                },
            ),
            "WORKSTATION_TARGET_IDENTITY_DRIFT",
        )

    def owns_http(self, binding, owner_pid):
        port = 8000 if binding.service == "api" else 5173
        root = Path(binding.root)
        result = command_result(["/usr/sbin/lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], root=root)
        child = result.stdout.strip()
        if result.returncode or not child.isdecimal():
            return False
        parent = command_result(["/bin/ps", "-p", child, "-o", "ppid="], root=root)
        if parent.returncode or parent.stdout.strip() != str(owner_pid):
            return False
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            client.request("GET", "/api/health" if binding.service == "api" else "/")
            response = client.getresponse()
            if response.status != 200:
                return False
            body = response.read(1_048_577)
            if binding.service == "api":
                health = json.loads(body)
                return (
                    health.get("service") == "guiyi-quant-api"
                    and health.get("status") == "ok"
                    and health.get("version") == binding.tag[1:]
                )
            return len(body) <= 1_048_576 and body == (root / "apps/quant-web/dist/index.html").read_bytes()
        except (OSError, ValueError, http.client.HTTPException):
            return False
        finally:
            client.close()

    def ready(self, pair):
        end = time.monotonic() + 45
        while time.monotonic() < end:
            for name, binding in pair.items():
                state = read_service_state(name, runtime_dir=self.directory)
                output = read_launchd_service(binding.label, root=Path(binding.root))
                if output:
                    self.verify_loaded(binding, output)
                if not (
                    output
                    and state
                    and state.get("generation") == binding.generation
                    and state.get("phase") == "active"
                    and state.get("ready")
                    and owner_process_matches(state, binding)
                    and self.owns_http(binding, state["pid"])
                ):
                    break
            else:
                return
            time.sleep(0.25)
        raise CohortError("WORKSTATION_HTTP_OWNER_NOT_READY")

    def stop_new(self, pair):
        for binding in pair.values():
            output = read_launchd_service(binding.label, root=Path(binding.root))
            path = self.path(binding)
            require(
                not os.path.lexists(path) or self.bytes(path) == self._plist(binding),
                "WORKSTATION_TARGET_PLIST_DRIFT",
            )
            if output:
                self.verify_loaded(binding, output)
            target = f"gui/{os.getuid()}/{binding.label}"
            self.launch("disable", target)
            if output:
                self.launch("bootout", target)
            disabled, _ = self.authorities(Path(binding.root))
            require(
                disabled.get(binding.label) is True
                and read_launchd_service(binding.label, root=Path(binding.root)) is None,
                "WORKSTATION_TARGET_STOP_UNKNOWN",
            )
        closed_ports()


def peer_rows(evidence):
    return {key: value for key, value in evidence.items() if key not in PAIR}


def make_plan(host, root, tag, commit, *, instant=None):
    assert_no_unknown_deployment()
    old, before, raw = host.inventory()
    require(old is not None, "WORKSTATION_PRIOR_REGISTRY_REQUIRED")
    pair, config, schema = host.candidate(root, tag, commit, old)
    require(
        all(old.services[n].enabled and old.services[n].label != pair[n].label for n in PAIR),
        "WORKSTATION_OLD_PORT_IDENTITY_UNSUPPORTED",
    )
    evidence = host.evidence(old, root)
    host.verify_targets_absent(pair)
    require(host.inventory()[2] == raw, "WORKSTATION_REGISTRY_DRIFT")
    plan = {
        "kind": KIND,
        "created_at": (instant or host.now()).isoformat(),
        "registry_sha256": before,
        "config_sha256": config,
        "schema": schema,
        "candidate": {n: asdict(b) for n, b in pair.items()},
        "evidence": evidence,
    }
    plan["plan_sha256"] = digest(plan)
    return plan


def parse_plan(plan):
    require(
        isinstance(plan, dict)
        and plan.get("kind") == KIND
        and set(plan.get("candidate", {})) == set(PAIR)
        and plan.get("plan_sha256") == digest({k: v for k, v in plan.items() if k != "plan_sha256"}),
        "WORKSTATION_PLAN_INVALID",
    )
    pair = {n: ServiceBinding(**plan["candidate"][n]) for n in PAIR}
    require(all(n == b.service for n, b in pair.items()), "WORKSTATION_PAIR_INVALID")
    return pair


def status(host, plan):
    pair = parse_plan(plan)
    observed, current, _ = host.inventory()
    attempt = host.directory / ("workstation-forward-" + plan["plan_sha256"])
    if os.path.lexists(attempt):
        from app.runtime_bindings import _parse_bindings

        raw = file_snapshot(attempt / "previous-registry.json", private=True)[0]
        require(sha256(raw).hexdigest() == plan["registry_sha256"], "WORKSTATION_PREIMAGE_DRIFT")
        original = _parse_bindings(raw, inventory=True)
        desired = {**original.services, **pair}
    else:
        original, desired = None, None
    if current == plan["registry_sha256"]:
        authority = "old"
    elif observed and desired == observed.services:
        authority = "new"
    else:
        authority = "unknown"
    return authority, original, pair, attempt


def apply(host, plan, *, resume=False):
    with deployment_lock(runtime_dir=host.directory):
        authority, original, pair, attempt = status(host, plan)
        root = Path(pair["api"].root)
        pointer = host.directory / "workstation-forward.json"
        progress = _read(pointer)

        def record(phase):
            _write(pointer, {"phase": phase, "plan_sha256": plan["plan_sha256"]})

        if resume:
            require(
                authority == "new"
                and progress
                and progress.get("plan_sha256") == plan["plan_sha256"]
                and progress.get("phase")
                in {"cas_intent", "cas_unknown", "starting", "start_failed", "stop_unknown"},
                "WORKSTATION_RESUME_UNPROVEN",
            )
            assert_no_unknown_deployment(workstation_plan_sha256=plan["plan_sha256"])
            release, config, schema = host.candidate(root, pair["api"].tag, pair["api"].commit, original)
            require(
                release == pair and config == plan["config_sha256"] and schema == plan["schema"],
                "WORKSTATION_CANDIDATE_DRIFT",
            )
        else:
            require(
                authority == "old"
                and not os.path.lexists(attempt)
                and (progress is None or progress.get("phase") in {"switched", "cancelled"}),
                "WORKSTATION_ATTEMPT_CONSUMED",
            )
            created = datetime.fromisoformat(plan["created_at"])
            require(
                timedelta(0) <= host.now() - created <= timedelta(minutes=15), "WORKSTATION_PLAN_EXPIRED"
            )
            checked = make_plan(host, root, pair["api"].tag, pair["api"].commit, instant=created)
            require(checked == plan, "WORKSTATION_PLAN_DRIFT")
            original, previous_hash, raw = host.inventory()
            require(previous_hash == plan["registry_sha256"], "WORKSTATION_REGISTRY_DRIFT")
            attempt.mkdir(mode=0o700)
            host._private_original(attempt / "previous-registry.json", raw)
            host._private_original(attempt / "plan.json", json.dumps(plan, sort_keys=True).encode())
            host._sync_directory(attempt)
            host._sync_directory(host.directory)
            record("cas_intent")
            try:
                host.commit_pair(pair, previous_hash)
            except BaseException:
                record("cas_unknown")
                raise CohortError("WORKSTATION_CAS_READBACK_REQUIRED") from None
        require(status(host, plan)[0] == "new", "WORKSTATION_CAS_READBACK_REQUIRED")
        peers = peer_rows(plan["evidence"])
        require(
            peer_rows(host.evidence(original, root, peers_only=True)) == peers, "WORKSTATION_PEER_DRIFT"
        )
        host.preflight_start(pair, resume=resume)
        record("starting")
        try:
            host.park_old_pair({n: original.services[n] for n in PAIR}, root)
            host.assert_no_backtest_autostart(root)
            host.install_pair(pair, attempt)
            host.ready(pair)
            require(
                status(host, plan)[0] == "new"
                and peer_rows(host.evidence(original, root, peers_only=True)) == peers,
                "WORKSTATION_READBACK_DRIFT",
            )
        except BaseException:
            record("stop_unknown")
            host.stop_new(pair)
            record("start_failed")
            raise CohortError("WORKSTATION_FORWARD_START_FAILED") from None
        record("switched")
        return {
            "phase": "switched",
            "services": list(PAIR),
            "generation": pair["api"].generation,
            "tag": pair["api"].tag,
            "commit": pair["api"].commit,
        }


def cancel_uncommitted(host, plan):
    with deployment_lock(runtime_dir=host.directory):
        authority, original, pair, _ = status(host, plan)
        progress = _read(host.directory / "workstation-forward.json")
        require(
            authority == "old"
            and original
            and progress
            and progress.get("plan_sha256") == plan["plan_sha256"]
            and progress.get("phase") in {"cas_intent", "cas_unknown"},
            "WORKSTATION_NOT_UNCOMMITTED",
        )
        host.verify_targets_absent(pair)
        require(
            host.evidence(original, Path(pair["api"].root)) == plan["evidence"], "WORKSTATION_PLAN_DRIFT"
        )
        _write(
            host.directory / "workstation-forward.json",
            {"phase": "cancelled", "plan_sha256": plan["plan_sha256"]},
        )
        return {"phase": "cancelled", "authority": "old"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    ops = parser.add_subparsers(dest="op", required=True)
    plan = ops.add_parser("plan")
    for key in ("candidate-root", "tag", "commit"):
        plan.add_argument("--" + key, required=True)
    audit = ops.add_parser("audit")
    audit.add_argument("--root", required=True)
    for name in ("apply", "read", "resume", "cancel-uncommitted"):
        ops.add_parser(name).add_argument("--plan", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        host = WorkstationHost()
        if args.op == "audit":
            old, digest_value, _ = host.inventory()
            require(old is not None, "WORKSTATION_PRIOR_REGISTRY_REQUIRED")
            closed_ports()
            value = {"registry_sha256": digest_value, "evidence": host.evidence(old, Path(args.root))}
        elif args.op == "plan":
            value = make_plan(host, Path(args.candidate_root), args.tag, args.commit)
        else:
            plan = json.loads(file_snapshot(args.plan, private=True)[0])
            if args.op == "read":
                authority, _, _, _ = status(host, plan)
                value = {
                    "authority": authority,
                    "progress": _read(host.directory / "workstation-forward.json"),
                }
            elif args.op == "cancel-uncommitted":
                value = cancel_uncommitted(host, plan)
            else:
                value = apply(host, plan, resume=args.op == "resume")
        print(json.dumps(value, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        message = str(error)
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": message
                    if re.fullmatch("[A-Z0-9_]+", message)
                    else "WORKSTATION_PREFLIGHT_UNAVAILABLE",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
