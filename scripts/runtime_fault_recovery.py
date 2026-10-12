#!/usr/bin/env python3
"""Exact gen16->gen17 recovery phases; default is read-only freeze/readback.

Run old-gen drain, then the separately reviewed Live projection restore while
this controller is not holding deployment.lock. Stop/install requires its exact
successful readback. Reference stays gen17 parked until its independent recovery
CLI commits bounded interruptions, expired originals and normal cursor ACK.
"""

from __future__ import annotations

import argparse
from io import StringIO
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "services/quant-api"),
    str(ROOT / "packages/quant-core"),
    str(ROOT),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        required=True,
        choices=(
            "freeze",
            "drain",
            "stop-install",
            "start",
            "resume-reference",
            "readback",
        ),
    )
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--expected-plan-hash")
    parser.add_argument("--attempt", type=Path)
    parser.add_argument("--projection-readback", type=Path)
    parser.add_argument("--projection-sha256")
    parser.add_argument("--reference-plan", type=Path)
    parser.add_argument("--reference-plan-hash")
    parser.add_argument("--reference-attempt", type=Path)
    parser.add_argument("--outage-plan", type=Path)
    parser.add_argument("--outage-plan-hash")
    parser.add_argument("--outage-attempt", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    mutation = args.phase not in ("freeze", "readback")
    if mutation != args.apply or args.candidate_root != ROOT:
        raise RuntimeError("FAULT_RECOVERY_PHASE_OR_ROOT_INVALID")
    from app.runtime_bindings import verify_release

    verify_release(ROOT, "v1.15.4", args.candidate_commit)
    # Configuration remains private and unchanged; only this process loads it.
    from dotenv import dotenv_values
    from scripts.newow_weekly_recovery import _read_private_settings_content
    from app.runtime_handover import runtime_directory

    values = dotenv_values(
        stream=StringIO(
            _read_private_settings_content(runtime_directory() / "project.env").decode()
        )
    )
    for key, value in values.items():
        if key not in ("HOME", "CODEX_HOME", "PATH") and isinstance(value, str):
            os.environ[key] = value
    if os.environ.get("REDIS_URL", "") in ("", "redis://127.0.0.1:6379/0"):
        from urllib.parse import quote

        password = os.environ.get("REDIS_PASSWORD") or os.environ.get(
            "POSTGRES_PASSWORD"
        )
        if not password:
            raise RuntimeError("FAULT_RECOVERY_REDIS_CONFIGURATION_REQUIRED")
        os.environ["REDIS_URL"] = (
            "redis://:" + quote(password, safe="") + "@127.0.0.1:6379/0"
        )
    from app.runtime_fault_recovery import (
        freeze,
        run_stage,
        independent_readback,
        StageAttempt,
        validate,
    )
    from app.runtime_fault_recovery_host import FaultRecoveryHost
    from app.reference_trading.recovery_campaign import write_once

    backend = FaultRecoveryHost(
        projection_sha256=args.projection_sha256,
        reference_plan=args.reference_plan,
        reference_plan_hash=args.reference_plan_hash,
        reference_attempt=args.reference_attempt,
        outage_plan=args.outage_plan,
        outage_plan_hash=args.outage_plan_hash,
        outage_attempt=args.outage_attempt,
    )
    if args.phase == "freeze":
        if args.projection_readback is None:
            raise RuntimeError("FAULT_RECOVERY_PROJECTION_READBACK_PATH_REQUIRED")
        with backend.deployment_guard():
            with backend.after_market_guard(), backend.maintenance_guard():
                plan = freeze(
                    backend,
                    candidate_root=ROOT,
                    candidate_commit=args.candidate_commit,
                    projection_readback=args.projection_readback,
                    projection_sha256=args.projection_sha256,
                )
                write_once(args.plan, plan)
        print(
            json.dumps(
                {
                    "status": "FAULT_RECOVERY_FROZEN_NO_APPLY",
                    "plan_hash": plan["plan_hash"],
                    "old_ready_required": False,
                    "new_generation": 17,
                }
            )
        )
    else:
        plan = json.loads(backend.bytes(args.plan, limit=16 * 1024 * 1024))
        validate(plan)
        if plan["plan_hash"] != args.expected_plan_hash or args.attempt is None:
            raise RuntimeError("FAULT_RECOVERY_PLAN_OR_ATTEMPT_REQUIRED")
        attempt = StageAttempt(args.attempt, plan)
        if args.phase == "readback":
            with backend.deployment_guard():
                result = independent_readback(plan, backend=backend, attempt=attempt)
            print(json.dumps(result))
        else:
            result = run_stage(plan, args.phase, backend=backend, attempt=attempt)
            print(
                json.dumps(
                    {
                        "status": result["phase"],
                        "completed": result["completed"],
                        "natural_acceptance": "PENDING",
                    }
                )
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        code = str(error)
        if not code or not all(
            char.isupper() or char.isdigit() or char == "_" for char in code
        ):
            code = "FAULT_RECOVERY_FAILED_READBACK_REQUIRED"
        print(json.dumps({"status": "STOPPED", "reason": code}))
        raise SystemExit(2)
