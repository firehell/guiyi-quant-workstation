"""All-service stopped-world release. Never accepts mixed active contracts."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta
from hashlib import sha256
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
from app.runtime_cohort_errors import CohortError

CONTINUOUS = ("market-feed", "live", "alert", "reference-worker", "api", "web")
CALENDARS = ("after-market", "late-provider-recovery", "weekly-audit", "log-rotate")
TERMINAL = frozenset({"switched", "cancelled"})
WARMUP_SAFE_CODES = frozenset({
    "COHORT_OPERATION_BLOCKED", "COHORT_CANDIDATE_SOURCE_IDENTITY_UNPROVEN",
    "REFERENCE_WARMUP_TIMEOUT", "REFERENCE_WARMUP_PREIMAGE_UNAVAILABLE",
    "REFERENCE_WARMUP_INITIAL_SEED_INVALID", "REFERENCE_WARMUP_SCOPE_EMPTY",
    "SUBING_REFERENCE_DATA_UNAVAILABLE", "CANONICAL_PUBLICATION_LAGGING",
    "CANONICAL_PUBLICATION_ENDPOINT_INVALID",
})
WARMUP_CONDITIONS = frozenset({
    "subprocess_timeout", "execution_failed", "output_invalid",
    "candidate_blocked", "source_identity",
})


def require(value, code):
    if not value:
        raise CohortError(code)


def registry(value, *, historical=False, history_directory=None, history_verifier=None):
    from app.runtime_bindings import historical_binding
    require(historical or history_verifier is None, "COHORT_HISTORY_SCOPE_INVALID")
    return BindingRegistry(
        1, {k: historical_binding(v, directory=history_directory, verifier=history_verifier) if historical else ServiceBinding(**v)
            for k, v in value["services"].items()}
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
    if any(value.contracts["db"] != contracts["db"] for value in previous.services.values()):
        verifier = getattr(host, "schema_compatibility", None)
        require(callable(verifier), "COHORT_SCHEMA_CHANGE_UNSUPPORTED")
        result["schema_compatibility"] = verifier(previous, new)
    freeze_reference = getattr(host, "freeze_reference_receiving_handover", None)
    if callable(freeze_reference):
        reference_intent = freeze_reference(new)
        if reference_intent is not None:
            result["reference_receiving_handover"] = reference_intent
    result["plan_sha256"] = digest(result)
    return result


def validate(plan, now, *, historical=False, history_directory=None, history_verifier=None):
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
        old, new = (registry(plan[key], historical=historical, history_directory=history_directory,
                            history_verifier=history_verifier)
                    for key in ("old", "new"))
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
        changed = {value.contracts["db"] for key, value in old.services.items()
                   if new.services[key].contracts["db"] != value.contracts["db"]}
        if changed:
            from app.runtime_schema_compatibility import validate_transition_proof, SchemaCompatibilityError
            proof = plan.get("schema_compatibility")
            require(isinstance(proof, dict) and set(proof) == changed, "COHORT_SCHEMA_CHANGE_UNSUPPORTED")
            for fingerprint in changed:
                try:
                    validate_transition_proof(proof[fingerprint], old_db=fingerprint, new_db=target.contracts["db"])
                except SchemaCompatibilityError:
                    raise CohortError("COHORT_SCHEMA_CHANGE_UNSUPPORTED") from None
        else:
            require("schema_compatibility" not in plan, "COHORT_SCHEMA_PROOF_UNEXPECTED")
        if "reference_receiving_handover" in plan:
            from app.reference_trading.receiving_handover import valid_receiving_handover_intent
            require(valid_receiving_handover_intent(plan["reference_receiving_handover"],
                    target=asdict(new.services["reference-worker"])), "COHORT_REFERENCE_BACKLOG_UNPROVEN")
        require(
            tuple(map(int, next(iter(new.services.values())).tag[1:].split(".")))
            > max(tuple(map(int, v.tag[1:].split("."))) for v in old.services.values()),
            "COHORT_FORWARD_RELEASE_REQUIRED",
        )
        return old, new
    except (KeyError, TypeError, OverflowError) as error:
        raise CohortError("COHORT_PLAN_INVALID") from error


def _check_schema(host, plan):
    if "schema_compatibility" in plan:
        verifier = getattr(host, "check_schema_compatibility", None)
        require(callable(verifier), "COHORT_SCHEMA_CHANGE_UNSUPPORTED")
        verifier(plan)


def _check_reference_handover(host, plan, proof):
    if "reference_receiving_handover" in plan:
        check = getattr(host, "check_reference_receiving_handover", None)
        require(callable(check), "COHORT_REFERENCE_BACKLOG_UNPROVEN")
        check(plan, proof)


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
        _check_schema(host, plan)
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
        # Retain the exact consumed intent before the first service effect.
        # Historical attempts are never backfilled; their original public plan
        # remains authoritative where no private copy was created at the time.
        _write(attempt / "plan.json", plan)
        require(_resolution_source(attempt / "plan.json")[1] == plan,
                "COHORT_PLAN_PERSISTENCE_UNPROVEN")
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
            state["effects"]["prewarm"] = host.prewarm(plan)
            persist("prewarmed")
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
                _check_reference_handover(host, plan, proof)
                _check_schema(host, plan)  # Fresh installed proof before any owner stop.
                step("old_exited", lambda: host.stop_old(plan, proof))
                step("preserve", lambda: host.preserve(plan, attempt))
                step("install", lambda: host.install(plan, attempt))
                validate(plan, host.now())
                require(monotonic() < host.deadline, "COHORT_DOWNTIME_EXCEEDED")
                _check_schema(host, plan)  # Revalidate after install, before CAS intent.
                _check_reference_handover(host, plan, proof)
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
            if getattr(host, "bootout_requests", None):
                state["effects"]["bootout_requests"] = dict(host.bootout_requests)
            state["error_type"] = type(error).__name__
            state["failed_phase"] = state["phase"]
            # Preserve only our bounded protocol code, never arbitrary exception
            # text (which can contain private connection or provider details).
            if isinstance(error, CohortError) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", str(error)):
                state["error_code"] = str(error)
                failed_service = getattr(error, "service", None)
                if failed_service in CONTINUOUS:
                    state["failed_service"] = failed_service
                    condition = getattr(error, "warmup_condition", None)
                    if condition in WARMUP_CONDITIONS:
                        code = getattr(error, "warmup_code", None)
                        state["warmup_diagnostic"] = {"condition": condition,
                            "code": code if code is None or isinstance(code, str) and code in WARMUP_SAFE_CODES else "COHORT_OPERATION_BLOCKED"}
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


def _resolution_source(path):
    raw = read_plan(path)
    require(raw is not None, "COHORT_RESOLUTION_SOURCE_MISSING")
    try:

        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, "COHORT_RESOLUTION_SOURCE_INVALID")
                result[key] = value
            return result

        value = json.loads(raw, object_pairs_hook=unique)
        require(isinstance(value, dict), "COHORT_RESOLUTION_SOURCE_INVALID")
    except (ValueError, UnicodeError):
        raise CohortError("COHORT_RESOLUTION_SOURCE_INVALID") from None
    return raw, value


def _sync_resolution_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def resolve_restored_cohort(host, plan_path):
    """Audit an externally restored pre-CAS attempt; never execute its plan."""
    with deployment_lock(runtime_dir=host.directory):
        plan_raw, plan = _resolution_source(Path(plan_path))
        # Reuse all identity/contract validation at the historical creation time.
        # Expiry is ignored only in this audit; apply_cohort has no such bypass.
        created = datetime.fromisoformat(plan["created_at"])
        require(created <= host.now(), "COHORT_PLAN_INVALID")
        old, _new = validate(plan, created)
        require(
            host.bindings() == old and host.binding_hash() == plan["registry_sha256"],
            "COHORT_REGISTRY_DRIFT",
        )
        attempt = host.directory / "cohort-attempts" / plan["plan_sha256"]
        for directory in (attempt.parent, attempt):
            info = directory.lstat()
            require(
                directory.resolve() == directory
                and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                "COHORT_ATTEMPT_DIRECTORY_UNSAFE",
            )
        global_path, state_path = (
            host.directory / "cohort-release.json",
            attempt / "state.json",
        )
        global_raw, global_state = _resolution_source(global_path)
        attempt_raw, attempt_state = _resolution_source(state_path)
        allowed = {
            "prewarm",
            "calendars_off",
            "drain",
            "old_exited",
            "preserve",
            "install",
            "bootout_requests",
        }
        for state in (global_state, attempt_state):
            require(
                state.get("schema_version") == 1
                and state.get("phase") == "restore_unknown"
                and state.get("plan_sha256") == plan["plan_sha256"]
                and isinstance(state.get("effects"), dict)
                and set(state["effects"]) <= allowed,
                "COHORT_PRECOMMIT_RESTORE_REQUIRED",
            )
        require(global_state == attempt_state, "COHORT_RESOLUTION_STATE_MISMATCH")
        sources = (
            (Path(plan_path), plan_raw),
            (global_path, global_raw),
            (state_path, attempt_raw),
        )

        def unchanged():
            for path, expected in sources:
                require(read_plan(path) == expected, "COHORT_RESOLUTION_SOURCE_DRIFT")
            require(
                host.bindings() == old
                and host.binding_hash() == plan["registry_sha256"],
                "COHORT_REGISTRY_DRIFT",
            )

        proof = host.verify_old_restored(plan)
        require(
            isinstance(proof, dict)
            and re.fullmatch(r"[0-9a-f]{64}", proof.get("identity_sha256", ""))
            is not None,
            "COHORT_RESTORE_PROOF_INVALID",
        )
        unchanged()
        receipt_path = attempt / "recovery-readback.json"
        receipt = {
            "schema_version": 1,
            "kind": "precommit_restore_readback",
            "plan_sha256": plan["plan_sha256"],
            "source_plan_sha256": sha256(plan_raw).hexdigest(),
            "source_global_sha256": sha256(global_raw).hexdigest(),
            "source_attempt_sha256": sha256(attempt_raw).hexdigest(),
            "observed_at": host.now().isoformat(),
            "proof": proof,
        }
        if os.path.lexists(receipt_path):
            receipt_raw, existing = _resolution_source(receipt_path)
            require(
                all(
                    existing.get(key) == value
                    for key, value in receipt.items()
                    if key not in {"observed_at", "proof"}
                )
                and isinstance(existing.get("proof"), dict)
                and existing["proof"].get("identity_sha256")
                == proof["identity_sha256"],
                "COHORT_RESOLUTION_RECEIPT_MISMATCH",
            )
        else:
            receipt_raw = (
                json.dumps(receipt, sort_keys=True, indent=2) + "\n"
            ).encode()
            fd = os.open(
                receipt_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(receipt_raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError:
                require(
                    read_plan(receipt_path) == receipt_raw,
                    "COHORT_RESOLUTION_RECEIPT_WRITE_UNKNOWN",
                )
        require(
            read_plan(receipt_path) == receipt_raw, "COHORT_RESOLUTION_RECEIPT_DRIFT"
        )
        # Also sync a complete receipt recovered after an uncertain write.
        fd = os.open(receipt_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        _sync_resolution_directory(attempt)
        unchanged()
        receipt_sha = sha256(receipt_raw).hexdigest()
        resolved = {
            **global_state,
            "phase": "cancelled",
            "resolution": {
                "kind": "precommit_restore_readback",
                "receipt_sha256": receipt_sha,
                "source_global_sha256": sha256(global_raw).hexdigest(),
                "source_attempt_sha256": sha256(attempt_raw).hexdigest(),
            },
        }
        try:
            _write(global_path, resolved)
        except OSError:
            # A failed fsync/return is not permission to replay the pointer write.
            _raw, observed = _resolution_source(global_path)
            require(observed == resolved, "COHORT_RESOLUTION_WRITE_UNKNOWN")
        _raw, observed = _resolution_source(global_path)
        require(
            observed == resolved and read_plan(state_path) == attempt_raw,
            "COHORT_RESOLUTION_WRITE_UNKNOWN",
        )
        return {
            "status": "cancelled",
            "plan_sha256": plan["plan_sha256"],
            "receipt_sha256": receipt_sha,
            "original_attempt_preserved": True,
        }


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
    p = sub.add_parser("resolve-restored")
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

            if args.service == "alert":
                from app.alerts.composition import warmup_alert_runtime

                proof = warmup_alert_runtime(allow_closed_warming=True, allow_break=True)
            elif args.service == 'reference-worker':
                from app.reference_trading.worker_entry import warmup_reference_worker
                proof = warmup_reference_worker(allow_classified_weekly_unavailable=True)
            else:
                proof = warmup_service(args.service)
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "service": args.service,
                        "proof": proof,
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
        elif args.mode == "resolve-restored":
            result = resolve_restored_cohort(host, args.plan)
        else:
            raw = read_plan(args.plan)
            require(raw is not None, "COHORT_PLAN_MISSING")
            result = apply_cohort(host, json.loads(raw))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        warmup_code = getattr(error, "code", None)
        if not isinstance(warmup_code, str) or warmup_code not in WARMUP_SAFE_CODES:
            warmup_code = str(error) if str(error) in WARMUP_SAFE_CODES else None
        code = (warmup_code if args.mode == "warmup" and warmup_code else
                str(error) if isinstance(error, CohortError) else type(error).__name__)
        code = (
            code
            if re.fullmatch("[A-Z][A-Z0-9_]+", code or "")
            else "COHORT_OPERATION_BLOCKED"
        )
        print(json.dumps({"status": "blocked", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
