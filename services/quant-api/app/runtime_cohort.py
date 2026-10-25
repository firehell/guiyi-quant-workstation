"""All-service stopped-world release. Never accepts mixed active contracts."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta
import json
import stat
import os
from pathlib import Path
import re
from time import monotonic

from app.runtime_bindings import (
    BindingRegistry,
    SERVICES,
    ServiceBinding,
    _read as read_plan,
)
from app.runtime_handover import _read, _write, deployment_lock
from app.reference_trading.recovery_campaign import digest

CONTINUOUS = ("market-feed", "live", "alert", "reference-worker", "api", "web")
CALENDARS = ("after-market", "late-provider-recovery", "weekly-audit", "log-rotate")
TERMINAL = frozenset({"switched", "cancelled"})


class CohortError(ValueError):
    pass


def require(value, code):
    if not value:
        raise CohortError(code)


def registry(value):
    return BindingRegistry(
        1, {k: ServiceBinding(**v) for k, v in value["services"].items()}
    )


def freeze_cohort(host, *, candidate_root, tag, commit):
    previous = host.bindings()
    require(
        previous is not None and set(previous.services) == SERVICES,
        "COHORT_SERVICE_SET_INVALID",
    )
    state = _read(host.directory / "cohort-release.json")
    require(
        state is None or state.get("phase") in TERMINAL,
        "COHORT_RECOVERY_READBACK_REQUIRED",
    )
    require(
        Path(candidate_root).name == "release-" + tag
        and all(
            Path(v.root).parent == Path(candidate_root).parent
            for v in previous.services.values()
        ),
        "COHORT_RELEASE_ROOT_INVALID",
    )
    host.verify_release(candidate_root, tag, commit)

    def version(value):
        require(
            re.fullmatch(r"v\d+\.\d+\.\d+", value) is not None, "COHORT_TAG_INVALID"
        )
        return tuple(map(int, value[1:].split(".")))

    require(
        version(tag) > max(version(v.tag) for v in previous.services.values()),
        "COHORT_FORWARD_RELEASE_REQUIRED",
    )
    contracts = host.contracts(candidate_root)
    for old in previous.services.values():
        host.verify_release(Path(old.root), old.tag, old.commit)
        require(
            old.contracts["db"] == contracts["db"], "COHORT_SCHEMA_CHANGE_UNSUPPORTED"
        )
    generation = max(v.generation for v in previous.services.values()) + 1
    new = BindingRegistry(
        1,
        {
            k: replace(
                v,
                root=str(candidate_root),
                tag=tag,
                commit=commit,
                contracts=contracts,
                generation=generation,
                launchd_label=None,
            )
            for k, v in previous.services.items()
        },
    )
    now = host.now()
    result = {
        "schema_version": 1,
        "kind": "stopped_world_release_v1",
        "old": asdict(previous),
        "new": asdict(new),
        "registry_sha256": host.binding_hash(),
        "protected": host.protected(previous),
        "installed": host.installed(previous),
        "window": host.session_proof(),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
        "downtime_seconds": 600,
    }
    result["plan_sha256"] = digest(result)
    return result


def validate(plan, now):
    try:
        require(
            plan["schema_version"] == 1
            and plan["kind"] == "stopped_world_release_v1"
            and plan["plan_sha256"]
            == digest({k: v for k, v in plan.items() if k != "plan_sha256"}),
            "COHORT_PLAN_INVALID",
        )
        require(
            datetime.fromisoformat(plan["expires_at"])
            - datetime.fromisoformat(plan["created_at"])
            == timedelta(minutes=15),
            "COHORT_TTL_INVALID",
        )
        require(
            datetime.fromisoformat(plan["created_at"])
            <= now
            < datetime.fromisoformat(plan["expires_at"]),
            "COHORT_PLAN_EXPIRED",
        )
        old, new = registry(plan["old"]), registry(plan["new"])
        require(
            set(old.services) == set(new.services) == SERVICES,
            "COHORT_SERVICE_SET_INVALID",
        )
        require(plan["downtime_seconds"] == 600, "COHORT_BUDGET_INVALID")
        require(
            all(old.services[k].enabled for k in CONTINUOUS),
            "COHORT_CONTINUOUS_DISABLED_UNSUPPORTED",
        )
        targets = {
            (v.root, v.tag, v.commit, v.generation) for v in new.services.values()
        }
        require(len(targets) == 1, "COHORT_TARGET_INVALID")
        target = next(iter(new.services.values()))
        require(
            Path(target.root).name == "release-" + target.tag
            and all(
                Path(v.root).parent == Path(target.root).parent
                for v in old.services.values()
            ),
            "COHORT_RELEASE_ROOT_INVALID",
        )
        for key, value in new.services.items():
            require(
                value.enabled == old.services[key].enabled
                and value.launchd_label is None
                and value.generation
                == max(v.generation for v in old.services.values()) + 1,
                "COHORT_TARGET_INVALID",
            )
        require(
            len({tuple(sorted(v.contracts.items())) for v in new.services.values()})
            == 1,
            "COHORT_TARGET_CONTRACTS_INVALID",
        )
        require(
            all(
                new.services[k].contracts["db"] == v.contracts["db"]
                for k, v in old.services.items()
            ),
            "COHORT_SCHEMA_CHANGE_UNSUPPORTED",
        )
        require(
            tuple(map(int, next(iter(new.services.values())).tag[1:].split(".")))
            > max(tuple(map(int, v.tag[1:].split("."))) for v in old.services.values()),
            "COHORT_FORWARD_RELEASE_REQUIRED",
        )
        return old, new
    except (KeyError, TypeError, OverflowError) as error:
        raise CohortError("COHORT_PLAN_INVALID") from error


def apply_cohort(host, plan):
    old, _new = validate(plan, host.now())
    with deployment_lock(runtime_dir=host.directory):
        current = _read(host.directory / "cohort-release.json")
        require(
            current is None or current.get("phase") in TERMINAL,
            "COHORT_RECOVERY_READBACK_REQUIRED",
        )
        require(
            host.bindings() == old and host.binding_hash() == plan["registry_sha256"],
            "COHORT_REGISTRY_DRIFT",
        )
        host.check_plan(plan)
        attempts = host.directory / "cohort-attempts"
        require(not attempts.is_symlink(), "COHORT_ATTEMPT_DIRECTORY_UNSAFE")
        attempts.mkdir(mode=0o700, exist_ok=True)
        metadata = attempts.lstat()
        require(
            attempts.resolve() == attempts
            and stat.S_ISDIR(metadata.st_mode)
            and metadata.st_uid == os.getuid()
            and stat.S_IMODE(metadata.st_mode) == 0o700,
            "COHORT_ATTEMPT_DIRECTORY_UNSAFE",
        )
        attempt = attempts / plan["plan_sha256"]
        try:
            attempt.mkdir(mode=0o700)
        except FileExistsError:
            raise CohortError("COHORT_ATTEMPT_CONSUMED") from None
        state = {
            "schema_version": 1,
            "plan_sha256": plan["plan_sha256"],
            "phase": "claimed",
            "effects": {},
        }

        def persist(phase):
            state["phase"] = phase
            _write(attempt / "state.json", state)
            _write(host.directory / "cohort-release.json", state)

        persist("claimed")
        committed = False
        suspended = False
        try:
            host.prewarm(plan)
            host.check_plan(plan)
            validate(plan, host.now())
            host.deadline = monotonic() + plan["downtime_seconds"]

            def step(name, action):
                require(monotonic() < host.deadline, "COHORT_DOWNTIME_EXCEEDED")
                persist(name)
                result = action()
                state["effects"][name] = result
                persist(name + "_complete")
                return result

            suspended = True
            step("calendars_off", lambda: host.suspend_calendars(plan))
            proof = step("drain", lambda: host.drain(plan))
            with host.guards(plan):
                step("old_exited", lambda: host.stop_old(plan, proof))
                step("preserve", lambda: host.preserve(plan, attempt))
                step("install", lambda: host.install(plan, attempt))
                validate(plan, host.now())
                require(monotonic() < host.deadline, "COHORT_DOWNTIME_EXCEEDED")
                persist("committing")
                committed = True  # Unknown CAS result is never an automatic rollback.
                host.commit(plan)
                persist("committed")
            step("consumers", lambda: host.start_consumers(plan))
            step("consumers_ready", lambda: host.consumers_ready(plan, proof))
            step("feed", lambda: host.start_feed(plan))
            readback = step("verified", lambda: host.verify(plan, proof))
            step("calendars_on", lambda: host.restore_calendars(plan))
            host.assert_protected(plan)
            persist("switched")
            return {"status": "switched", "readback": readback}
        except Exception as error:
            state["error_type"] = type(error).__name__
            if committed:
                try:
                    persist("outcome_unknown")
                finally:
                    try:
                        host.halt_unknown(plan)
                    except Exception:
                        pass  # Keep the nonterminal journal; only independent readback may resolve it.
                raise CohortError("COHORT_OUTCOME_UNKNOWN_READBACK_REQUIRED") from None
            try:
                if suspended:
                    host.restore_old(plan)
                persist("cancelled")
            except Exception:
                persist("restore_unknown")
                raise CohortError("COHORT_RESTORE_UNKNOWN_READBACK_REQUIRED") from None
            raise CohortError("COHORT_PRECONDITION_CANCELLED") from None


def main(argv=None):
    import argparse
    from app.runtime_cohort_host import CohortHost

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--candidate-root", required=True, type=Path)
    p.add_argument("--tag", required=True)
    p.add_argument("--commit", required=True)
    p = sub.add_parser("apply-plan")
    p.add_argument("--plan", required=True, type=Path)
    p = sub.add_parser("warmup")
    p.add_argument("service", choices=CONTINUOUS)
    args = parser.parse_args(argv)
    try:
        if args.mode == "warmup":
            from app.runtime_deployment import warmup_service
            import guiyi_quant
            from app.core.env import PROJECT_ROOT
            from app.version import APP_VERSION

            print(
                json.dumps(
                    {
                        "status": "ready",
                        "service": args.service,
                        "proof": warmup_service(args.service),
                        "source_roots": {
                            "app": str(Path(__file__).resolve()),
                            "core": str(Path(guiyi_quant.__file__).resolve()),
                            "project_root": str(PROJECT_ROOT),
                            "version": APP_VERSION,
                        },
                    }
                )
            )
            return 0
        host = CohortHost()
        if args.mode == "plan":
            result = freeze_cohort(
                host,
                candidate_root=args.candidate_root,
                tag=args.tag,
                commit=args.commit,
            )
        else:
            raw = read_plan(args.plan)
            require(raw is not None, "COHORT_PLAN_MISSING")
            result = apply_cohort(host, json.loads(raw))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, CohortError) else type(error).__name__
        code = (
            code
            if re.fullmatch("[A-Z][A-Z0-9_]+", code or "")
            else "COHORT_OPERATION_BLOCKED"
        )
        print(json.dumps({"status": "blocked", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
