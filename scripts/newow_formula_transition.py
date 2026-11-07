#!/usr/bin/env python3
"""Retire the exact operational legacy oscillator/fusion pairs under writer fence."""

import argparse
from collections import defaultdict
from datetime import datetime, UTC, timedelta
import fcntl
import json
import os
from pathlib import Path
import re
import time

from sqlalchemy import select, text
from app.db.session import SessionLocal
from app.market_data.operational_universe import load_operational_products
from app.reference_trading.formula_transition import NewowFormulaTransition, CODES, _row
from app.reference_trading.models import (
    ReferenceStream,
    ReferenceRevision,
    ReferenceBatch,
    ReferenceActionRow,
    ReferenceTradeRow,
    ReferenceMarkRow,
    ReferenceActivationReceipt,
)
from app.reference_trading.planning import _canonical_identity
from app.reference_trading.repository import _identity_from_row
from app.runtime_bindings import resolve_service_binding
from app.runtime_handover import (
    deployment_lock,
    runtime_directory,
    read_service_state,
    request_drain,
    _read,
)
from scripts.newow_formula_prepare import identity, write_private


def require(value, code):
    if not value:
        raise ValueError(code)


def validate_scope(scope):
    """Resume only the frozen complete operational topology, never a partial file."""
    products = set(load_operational_products())
    require(len(products) == 60, "FORMULA_SCOPE_INCOMPLETE")
    require(isinstance(scope, dict) and scope.get("version") == "newow_formula_transition_scope_v1",
            "FORMULA_SCOPE_DRIFT")
    groups = scope.get("groups")
    expected = {p + "-" + f: (p, f) for p in products for f in ("1w", "1d", "60m")}
    require(isinstance(groups, dict) and set(groups) == set(expected), "FORMULA_SCOPE_INCOMPLETE")
    old_ids = set()
    for key, (product, frequency) in expected.items():
        pairs = groups[key]
        require(isinstance(pairs, (tuple, list)) and len(pairs) == 2
                and all(isinstance(pair, (tuple, list)) and len(pair) == 2 for pair in pairs),
                "FORMULA_SCOPE_DRIFT")
        require({pair[1] for pair in pairs} == {
            identity(product, code.removeprefix("newow_"), frequency).stream_id for code in CODES
        }, "FORMULA_SCOPE_DRIFT")
        for old_id, _ in pairs:
            require(isinstance(old_id, str) and re.fullmatch(r"reference-stream:[0-9a-f]{64}", old_id)
                    and old_id not in old_ids, "FORMULA_SCOPE_DRIFT")
            old_ids.add(old_id)
    require(datetime.fromisoformat(scope["expires_at"]).tzinfo is not None
            and datetime.fromisoformat(scope["recording_start"]).tzinfo is not None
            and datetime.fromisoformat(scope["expires_at"]) <= datetime.fromisoformat(scope["recording_start"]),
            "FORMULA_SCOPE_DRIFT")


def validate_plan_binding(plan, pairs, scope):
    require(plan.get("recording_start") == scope["recording_start"]
            and plan.get("expires_at") == scope["expires_at"]
            and len(plan.get("items", [])) == 2, "FORMULA_PLAN_SCOPE_DRIFT")
    actual = {(item["old"]["stream"]["stream_id"], item["bootstrap"]["source"]["stream_id"])
              for item in plan["items"]}
    require(actual == {tuple(pair) for pair in pairs}, "FORMULA_PLAN_SCOPE_DRIFT")


def inventory():
    groups = defaultdict(list)
    products = set(load_operational_products())
    require(len(products) == 60, "FORMULA_SCOPE_INCOMPLETE")
    codes = defaultdict(set)
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        for row in db.scalars(
            select(ReferenceStream).where(
                ReferenceStream.enabled.is_(True),
                ReferenceStream.strategy_code.in_(CODES),
                ReferenceStream.recording_mode == "forward_observation",
            )
        ):
            require(
                row.product in products
                and row.frequency in {"1d", "1w", "60m"}
                and not _canonical_identity(_identity_from_row(row)),
                "FORMULA_SCOPE_DRIFT",
            )
            historical = identity(
                row.product, row.strategy_code.removeprefix("newow_"), row.frequency
            )
            codes[(row.product, row.frequency)].add(row.strategy_code)
            groups[(row.product, row.frequency)].append(
                (row.stream_id, historical.stream_id)
            )
    require(
        set(groups) == {(p, f) for p in products for f in ("1w", "1d", "60m")}
        and all(len(v) == 2 for v in groups.values())
        and all(v == CODES for v in codes.values()),
        "FORMULA_SCOPE_INCOMPLETE",
    )
    return {p + "-" + f: sorted(v) for (p, f), v in sorted(groups.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    directory = args.directory
    require(
        directory.is_absolute() and not directory.is_symlink(), "FORMULA_PATH_INVALID"
    )
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(
        directory.resolve() == directory and not directory.stat().st_mode & 0o077,
        "FORMULA_PATH_INVALID",
    )
    scope_file = directory / "scope.json"
    if args.status:
        require(scope_file.exists(), "FORMULA_SCOPE_MISSING")
        service = NewowFormulaTransition(SessionLocal, assert_fenced=lambda: None)
        scope = json.loads(scope_file.read_text())
        validate_scope(scope)
        statuses = {}
        for key in scope["groups"]:
            plan_file = directory / (key + ".plan.json")
            if plan_file.exists():
                plan = json.loads(plan_file.read_text())
                validate_plan_binding(plan, scope["groups"][key], scope)
                statuses[key] = service.status(plan)
            else:
                statuses[key] = None
        print(
            json.dumps(
                dict(
                    committed=sum(v is not None for v in statuses.values()),
                    total=len(statuses),
                )
            )
        )
        return
    with deployment_lock():
        binding = resolve_service_binding("reference-worker")
        require(binding is not None and binding.enabled, "FORMULA_BINDING_INVALID")
        if scope_file.exists():
            scope = json.loads(scope_file.read_text())
            require(
                scope["generation"] == binding.generation
                and scope["root"] == binding.root,
                "FORMULA_BINDING_DRIFT",
            )
        else:
            groups = inventory()
            now = datetime.now(UTC)
            scope = dict(
                version="newow_formula_transition_scope_v1",
                groups=groups,
                generation=binding.generation,
                root=binding.root,
                recording_start=(now + timedelta(hours=5)).isoformat(),
                expires_at=(now + timedelta(hours=4)).isoformat(),
            )
            write_private(scope_file, scope)
        validate_scope(scope)
        # Exact source validation precedes any drain or production mutation.
        from app.reference_trading.newow_bootstrap import NewowForwardBootstrap

        with SessionLocal() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            for pairs in scope["groups"].values():
                for _, hid in pairs:
                    NewowForwardBootstrap(SessionLocal)._source(db, hid)
        if not args.apply:
            print(
                json.dumps(
                    dict(
                        status="SOURCES_VERIFIED",
                        groups=len(scope["groups"]),
                        production_writes=False,
                    )
                )
            )
            return
        control_file = directory / "drain.json"
        if control_file.exists():
            control = json.loads(control_file.read_text())
            require(
                _read(runtime_directory() / "reference-worker.handover.json")
                == control,
                "FORMULA_DRAIN_DRIFT",
            )
        else:
            existing = _read(runtime_directory() / "reference-worker.handover.json")
            require(
                existing is None or existing.get("phase") == "cancelled",
                "FORMULA_DRAIN_ALREADY_PRESENT",
            )
            request_drain("reference-worker", generation=binding.generation)
            control = _read(runtime_directory() / "reference-worker.handover.json")
            write_private(control_file, control)
        deadline = time.monotonic() + 120
        while True:
            state = read_service_state("reference-worker")
            if (
                state
                and state.get("phase") == "parked"
                and state.get("generation") == binding.generation
            ):
                break
            require(time.monotonic() < deadline, "FORMULA_DRAIN_TIMEOUT")
            time.sleep(0.2)
        fd = os.open(
            runtime_directory() / "reference-worker.owner.lock",
            os.O_RDWR | os.O_NOFOLLOW,
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def fenced():
                actual = resolve_service_binding("reference-worker")
                current = read_service_state("reference-worker")
                held = os.fstat(fd)
                disk = (runtime_directory() / "reference-worker.owner.lock").lstat()
                require(
                    actual == binding
                    and current["phase"] == "parked"
                    and current["generation"] == binding.generation
                    and _read(runtime_directory() / "reference-worker.handover.json")
                    == control
                    and (held.st_dev, held.st_ino) == (disk.st_dev, disk.st_ino),
                    "FORMULA_FENCE_LOST",
                )

            service = NewowFormulaTransition(SessionLocal, assert_fenced=fenced)
            # Freeze ALL pairs before writing any terminal boundary.
            for key, pairs in scope["groups"].items():
                plan_file = directory / (key + ".plan.json")
                if plan_file.exists():
                    validate_plan_binding(json.loads(plan_file.read_text()), pairs, scope)
                    original_file = directory / (key + ".originals.json")
                    require(original_file.is_file() and not original_file.is_symlink(),
                            "FORMULA_ORIGINALS_MISSING")
                    continue
                plan = service.plan(
                    pairs,
                    recording_start=datetime.fromisoformat(scope["recording_start"]),
                    expires_at=datetime.fromisoformat(scope["expires_at"]),
                    now=datetime.now(UTC),
                )
                originals = {}
                with SessionLocal() as db:
                    db.execute(text("SET TRANSACTION READ ONLY"))
                    for model in (
                        ReferenceStream,
                        ReferenceRevision,
                        ReferenceBatch,
                        ReferenceActionRow,
                        ReferenceTradeRow,
                        ReferenceMarkRow,
                        ReferenceActivationReceipt,
                    ):
                        originals[model.__tablename__] = [
                            _row(row)
                            for row in db.scalars(
                                select(model).where(
                                    model.stream_id.in_([p[0] for p in pairs])
                                )
                            )
                        ]
                write_private(directory / (key + ".originals.json"), originals)
                write_private(plan_file, plan)
            for key in scope["groups"]:
                plan = json.loads((directory / (key + ".plan.json")).read_text())
                validate_plan_binding(plan, scope["groups"][key], scope)
                result = service.status(plan)
                if result is None:
                    result = service.apply(
                        plan,
                        expected_plan_hash=plan["plan_hash"],
                        now=datetime.now(UTC),
                    )
                require(
                    service.status(plan) == result, "FORMULA_COMMIT_READBACK_FAILED"
                )
                write_private(directory / (key + ".result.json"), result)
                print(key, "COMMITTED", flush=True)
        finally:
            os.close(fd)
        # Keep the proven drain: old release cannot consume retired/new identities.
        print(
            json.dumps(
                dict(
                    status="COMMITTED",
                    groups=len(scope["groups"]),
                    writer="parked_until_release_switch",
                )
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        code = str(error)
        print(
            json.dumps(
                dict(
                    status="blocked",
                    code=code
                    if re.fullmatch("[A-Z][A-Z0-9_]{1,120}", code)
                    else type(error).__name__,
                )
            )
        )
        raise SystemExit(1)
