#!/usr/bin/env python3
"""Plan, apply, or read back bounded same-revision oscillation Inbox recovery."""

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re

from reference_observation_recovery import ROOT, load_dependencies, parked_reference_guard, verify_code

from app.private_settings import read_private_settings_content  # noqa: E402

VERSION = "reference_oscillation_warm_campaign_v1"
ATTEMPT_DIRECTORY = "reference-oscillation-warm-attempts"


def scope(ids):
    from app.reference_trading.inbox_recovery import require

    ids = tuple(ids)
    require(
        1 <= len(ids) <= 60 and len(set(ids)) == len(ids)
        and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in ids),
        "RECOVERY_SCOPE_INVALID",
    )
    return tuple(sorted(ids))


def encode(identity, plans):
    from app.reference_trading.inbox_recovery import digest

    body = {"version": VERSION, "identity": identity, "plans": [asdict(plan) for plan in plans]}
    return {**body, "plan_hash": digest(body)}


def decode(raw, expected_hash, identity):
    from app.reference_trading.capture import ForwardCapture
    from app.reference_trading.contracts import CheckpointToken
    from app.reference_trading.inbox_recovery import InboxRecoveryPlan, digest, require
    from app.reference_trading.newow_inbox_warm_recovery import POLICY

    value = json.loads(raw)
    require(isinstance(value, dict), "RECOVERY_PLAN_INVALID")
    body = {key: item for key, item in value.items() if key != "plan_hash"}
    require(
        value.get("version") == VERSION
        and value.get("plan_hash") == expected_hash == digest(body),
        "RECOVERY_PLAN_HASH_CONFLICT",
    )
    require(value["identity"] == identity, "RECOVERY_EXECUTION_IDENTITY_DRIFT")
    plans = []
    for row in value["plans"]:
        data = dict(row)
        cap = dict(data.pop("capture"))
        for field in ("bar_end", "observed_at"):
            cap[field] = datetime.fromisoformat(cap[field])
        data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        data["checkpoint"] = CheckpointToken(**data["checkpoint"])
        plan = InboxRecoveryPlan(capture=ForwardCapture(**cap), **data)
        require(
            plan.plan_hash == digest(plan.proof())
            and plan.rollback_continuation is None
            and POLICY in plan.capture.source_proof
            and plan.capture.source_proof["inbox_delivery_id"] == plan.delivery_id
            and plan.attempt_namespace_sha256 == identity["attempt_namespace_sha256"],
            "RECOVERY_PLAN_INVALID",
        )
        plans.append(plan)
    require(
        tuple(plan.delivery_id for plan in plans) == scope(plan.delivery_id for plan in plans),
        "RECOVERY_SCOPE_INVALID",
    )
    return plans


@contextmanager
def maintenance(directory, binding, config_sha, attempt_dir):
    from app.db.session import SessionLocal
    from app.market_data.catalog import MarketCatalog
    from app.market_data.composition import canonical_root
    from app.reference_trading.inbox_recovery import digest, require
    from app.reference_trading.newow_inbox_warm_recovery import NewowOscillationInboxWarmRecovery
    from app.reference_trading.transaction_guards import assert_source_allowed

    with parked_reference_guard(directory=directory, expected_binding=asdict(binding)) as (guard, bindings_sha):
        with SessionLocal() as session:
            lease = MarketCatalog(session, canonical_root()).acquire_maintenance_lock(
                caller="reference-oscillation-warm",
            )
            require(lease is not None, "RECOVERY_CATALOG_BUSY")
            try:
                def fence():
                    guard()
                    require(
                        sha256(read_private_settings_content(directory / "project.env")).hexdigest() == config_sha,
                        "RECOVERY_DEPENDENCY_DRIFT",
                    )
                    return {
                        "binding_sha256": bindings_sha,
                        "config_sha256": config_sha,
                        "attempt_namespace_sha256": digest(str(attempt_dir)),
                    }

                def commit_guard(db, stream_id):
                    fence()
                    assert_source_allowed(db, stream_id)

                yield NewowOscillationInboxWarmRecovery(
                    SessionLocal, attempt_dir=attempt_dir, verify_fence=fence,
                ), commit_guard
            finally:
                lease.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("plan", "apply", "readback"))
    parser.add_argument("--exact-root", type=Path, required=True)
    parser.add_argument("--exact-commit", required=True)
    parser.add_argument("--binding-generation", type=int, required=True)
    parser.add_argument("--plan-file", type=Path, required=True)
    parser.add_argument("--plan-hash")
    parser.add_argument("--delivery-id", action="append", default=[])
    parser.add_argument("--expires-minutes", type=int, default=60)
    args = parser.parse_args(argv)
    if not (
        args.plan_file.is_absolute() and args.plan_file.parent.resolve(strict=True) == args.plan_file.parent
        and 1 <= args.expires_minutes <= 120
        and ((args.phase == "plan" and not args.plan_hash and args.delivery_id)
             or (args.phase != "plan" and args.plan_hash and not args.delivery_id))
    ):
        raise ValueError("RECOVERY_ARGUMENTS_INVALID")
    verify_code(args.exact_root, args.exact_commit)
    from app.runtime_bindings import resolve_service_binding
    from app.runtime_handover import runtime_directory

    binding = resolve_service_binding("reference-worker")
    if not (
        binding is not None and binding.enabled and binding.generation == args.binding_generation
        and Path(binding.root) == ROOT and binding.commit == args.exact_commit
    ):
        raise ValueError("RECOVERY_RUNTIME_BINDING_INVALID")
    directory = runtime_directory()
    config_sha = load_dependencies(directory / "project.env")
    from app.reference_trading.inbox_recovery import digest, require
    from app.reference_trading.recovery_campaign import write_once

    attempt_dir = directory / ATTEMPT_DIRECTORY
    identity = {
        "binding": asdict(binding),
        "config_sha256": config_sha,
        "attempt_namespace_sha256": digest(str(attempt_dir)),
    }
    plans = [] if args.phase == "plan" else decode(
        read_private_settings_content(args.plan_file), args.plan_hash, identity,
    )
    if args.phase == "readback":
        from app.db.session import SessionLocal
        from app.reference_trading.inbox_recovery import InboxRecovery

        require(attempt_dir.is_dir(), "RECOVERY_ATTEMPT_DIRECTORY_MISSING")
        inbox = InboxRecovery(
            SessionLocal, attempt_dir=attempt_dir,
            verify_fence=lambda: None, verify_source=lambda _: None,
        )
        results = [
            {"delivery_id": plan.delivery_id, "calculation": inbox.readback(plan)}
            for plan in plans
        ]
        print(json.dumps({
            "status": "READBACK_ONLY",
            "committed": sum(row["calculation"] is not None for row in results),
            "total": len(plans),
            "deliveries": results,
        }))
        return 0

    with maintenance(directory, binding, config_sha, attempt_dir) as (recovery, commit_guard):
        if args.phase == "plan":
            ids = scope(args.delivery_id)
            expiry = datetime.now(UTC) + timedelta(minutes=args.expires_minutes)
            frozen = encode(identity, [recovery.plan(delivery_id, expires_at=expiry) for delivery_id in ids])
            write_once(args.plan_file, frozen)
            print(json.dumps({"status": "FROZEN_NO_APPLY", "plan_hash": frozen["plan_hash"], "deliveries": len(ids)}))
            return 0

        remaining = [plan for plan in plans if recovery.readback(plan) is None]
        for plan in remaining:
            require(not (attempt_dir / f"{plan.delivery_id}.json").exists(), "RECOVERY_ATTEMPT_ALREADY_STARTED")
            recovery.inbox.check_external(plan)
        for plan in remaining:
            recovery.apply(plan, expected_plan_hash=plan.plan_hash, commit_guard=commit_guard)
        require(all(recovery.readback(plan) is not None for plan in plans), "RECOVERY_READBACK_REQUIRED")
    print(json.dumps({"status": "RECOVERY_COMMITTED", "deliveries": len(plans)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        code = str(error)
        print(json.dumps({"status": "STOPPED", "code": code if re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", code) else "RECOVERY_INTERNAL_ERROR"}))
        raise SystemExit(1) from None
