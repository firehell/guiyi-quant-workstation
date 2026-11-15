#!/usr/bin/env python3
"""Plan and atomically switch blocked Newow H1 groups without replaying the gap."""

import argparse
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import stat
import time

from sqlalchemy import select

from app.db.readonly import readonly_transaction
from app.db.session import SessionLocal
from app.market_data.composition import build_market_data_service
from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
from app.market_data.operational_universe import load_operational_products
from app.private_settings import read_private_settings_content
from app.reference_trading.formula_transition import H1_CODES, require
from app.reference_trading.inbox import _head_query
from app.reference_trading.inbox_recovery import verified_resolution_ids
from app.reference_trading.models import ReferenceInboxInput, ReferenceStream
from app.reference_trading.newow_bootstrap import _BorrowedSession, _hash
from app.reference_trading.newow_h1_boundary import NewowH1Boundary
from app.reference_trading.recovery_campaign import write_once
from app.runtime_bindings import resolve_service_binding, verify_release
from app.runtime_cohort_host import CohortHost, owner_process_matches
from app.runtime_handover import (
    _read, cancel_drain, deployment_lock, read_service_state, request_drain, runtime_directory,
)

SERVICE = "reference-worker"
VERSION = "newow_h1_boundary_scope_v1"


def inventory(now):
    groups = defaultdict(dict)
    blocked = defaultdict(dict)
    with SessionLocal() as db, readonly_transaction(db, timeout_seconds=30):
        rows = db.scalars(select(ReferenceStream).where(
            ReferenceStream.enabled.is_(True),
            ReferenceStream.recording_mode == "forward_observation",
            ReferenceStream.frequency == "60m", ReferenceStream.strategy_code.in_(H1_CODES),
        )).all()
        products = set(load_operational_products())
        require(len(products) == 60, "NEWOW_H1_OPERATIONAL_SCOPE")
        require({row.product for row in rows} == products, "NEWOW_H1_OPERATIONAL_SCOPE")
        resolved = verified_resolution_ids(db, stream_ids=tuple(row.stream_id for row in rows))
        resolver = MarketPhaseResolver(db)
        market = build_market_data_service(db)
        for row in rows:
            require(row.strategy_code not in groups[row.product], "NEWOW_H1_DUPLICATE_ROUTE")
            groups[row.product][row.strategy_code] = row.stream_id
            head = db.scalar(_head_query(row.stream_id, resolved))
            if head and (head.status, head.code) in {
                ("BLOCKED", "OBSERVATION_GAP"),
                ("PENDING", "REFERENCE_FUSION_SOURCE_NOT_READY"),
            }:
                original = db.get(ReferenceInboxInput, head.input_id)
                require(original is not None, "NEWOW_H1_HEAD_INPUT_MISSING")
                blocked[row.product][row.strategy_code] = {
                    "delivery_id": head.delivery_id, "input_id": head.input_id,
                    "envelope_sha256": original.envelope_sha256,
                    "revision_id": head.revision_id, "generation": head.generation,
                    "status": head.status, "code": head.code,
                }
        require(all(set(group) == H1_CODES for group in groups.values()), "NEWOW_H1_SCOPE_INCOMPLETE")
        require(blocked and all(set(heads) == H1_CODES for heads in blocked.values()),
                "NEWOW_H1_DEPENDENCY_SCOPE_DRIFT")
        boundaries = {}
        for product in sorted(blocked):
            phase = resolver.resolve(product, now)
            start = phase.next_session_start
            require(phase.phase in {MarketPhase.CLOSED, MarketPhase.BREAK}
                    and phase.current_session is None and start is not None and start > now,
                    "NEWOW_H1_SESSION_NOT_PROVEN")
            upcoming = resolver.resolve(product, start)
            current = upcoming.current_session
            require(upcoming.phase is MarketPhase.TRADING and current is not None
                    and current.start == start and upcoming.trading_day is not None,
                    "NEWOW_H1_SESSION_NOT_PROVEN")
            day = upcoming.trading_day
            owner = market.dominant_segment_for_day(product, day)
            endpoints = market.expected_contract_replay_endpoints(
                symbol=product, contract=owner.contract, frequency="60m", trading_day=day,
                after=start, cutoff=current.end, since=owner.start_trading_day,
            )
            require(bool(endpoints), "NEWOW_H1_FIRST_ENDPOINT_MISSING")
            endpoint, endpoint_day = endpoints[0]
            require(start < endpoint <= current.end and endpoint_day == day, "NEWOW_H1_FIRST_ENDPOINT_DRIFT")
            boundaries[product] = (start, endpoint, sorted(groups[product].values()), blocked[product])
        return boundaries


def make_plan(binding, now, service):
    targets = inventory(now)
    # One scope expires before the earliest selected session can begin.
    expiry = min(now + timedelta(minutes=15), min(target[0] for target in targets.values()))
    groups = {product: service.plan(ids, recording_start=end, expires_at=expiry, now=now)
              for product, (_, end, ids, _) in targets.items()}
    body = {"version": VERSION, "binding": asdict(binding), "groups": groups,
            "heads": {product: target[3] for product, target in targets.items()}}
    return {**body, "plan_hash": _hash(body)}


def validate_plan(plan, binding, expected):
    require(plan.get("version") == VERSION and plan.get("binding") == asdict(binding)
            and plan.get("plan_hash") == expected
            and _hash({key: value for key, value in plan.items() if key != "plan_hash"}) == expected,
            "NEWOW_H1_SCOPE_PLAN_DRIFT")


def verify_targets(plan, now):
    targets = inventory(now)
    require(set(targets) == set(plan["groups"]), "NEWOW_H1_SCOPE_PLAN_DRIFT")
    for product, group in plan["groups"].items():
        start, endpoint, ids, heads = targets[product]
        expiry = datetime.fromisoformat(group["expires_at"])
        require(now < expiry <= start and endpoint.isoformat() == group["recording_start"]
                and ids == [item["old"]["stream"]["stream_id"] for item in group["items"]]
                and heads == plan["heads"][product],
                "NEWOW_H1_SCOPE_PLAN_DRIFT")


def settle_attempt(plan, binding, attempt, directory, control_path, receipts):
    require(attempt.resolve() == attempt and attempt.is_dir(), "NEWOW_H1_ATTEMPT_INVALID")
    intent = json.loads(read_private_settings_content(attempt / "intent.json"))
    request_id = intent.get("request_id")
    require(intent == {"plan_hash": plan["plan_hash"], "binding": asdict(binding),
                       "request_id": request_id}
            and isinstance(request_id, str), "NEWOW_H1_ATTEMPT_DRIFT")
    control = _read(control_path)
    if control and control.get("request_id") == request_id and control.get("phase") != "cancelled":
        CohortHost._check_parked_control(SERVICE, binding, control)
        owner = read_service_state(SERVICE, runtime_dir=directory)
        require(resolve_service_binding(SERVICE) == binding and owner
                and str(owner.get("pid")) == str(CohortHost().loaded(binding, allow_idle=False))
                and owner_process_matches(owner, binding), "NEWOW_H1_OWNER_UNPROVEN")
        cancel_drain(SERVICE, request_id=request_id, runtime_dir=directory)
    return result(receipts) if receipts else {"status": "NO_COMMIT", "products": 0, "routes": 0}


def apply(plan, binding, attempt):
    directory = runtime_directory()
    control_path = directory / f"{SERVICE}.handover.json"
    with deployment_lock(runtime_dir=directory):
        reader = NewowH1Boundary(SessionLocal, assert_fenced=lambda: None)
        prior = scope_readback(reader, plan)
        if attempt.exists() or prior:
            return settle_attempt(plan, binding, attempt, directory, control_path, prior)
        CohortHost().session_proof()
        verify_targets(plan, datetime.now(UTC))
        old_control = _read(control_path)
        attempt.mkdir(mode=0o700)
        if old_control and old_control.get("phase") != "cancelled":
            generation = old_control.get("generation")
            require(type(generation) is int and 0 < generation < binding.generation,
                    "NEWOW_H1_DRAIN_PRESENT")
            CohortHost._check_parked_control(SERVICE, replace(binding, generation=generation), old_control)
            owner = read_service_state(SERVICE, runtime_dir=directory)
            require(owner and owner.get("phase") == "active"
                    and str(owner.get("pid")) == str(CohortHost().loaded(binding, allow_idle=False))
                    and owner_process_matches(owner, binding), "NEWOW_H1_OWNER_UNPROVEN")
            raw = read_private_settings_content(control_path)
            require(json.loads(raw) == old_control, "NEWOW_H1_DRAIN_DRIFT")
            write_once(attempt / "superseded-control.json", {"raw_hex": raw.hex()})
            require(read_private_settings_content(control_path) == raw, "NEWOW_H1_DRAIN_DRIFT")
        def persist_intent(request_id):
            write_once(attempt / "intent.json", {"plan_hash": plan["plan_hash"],
                       "binding": asdict(binding), "request_id": request_id})

        request_id = request_drain(SERVICE, generation=binding.generation,
                                   runtime_dir=directory, before_install=persist_intent)
        started = False
        definite = False
        try:
            deadline = time.monotonic() + 120
            while True:
                state = read_service_state(SERVICE, runtime_dir=directory)
                if (state and state.get("phase") == "parked" and state.get("ready") is False
                        and state.get("generation") == binding.generation):
                    break
                require(time.monotonic() < deadline, "NEWOW_H1_DRAIN_TIMEOUT")
                time.sleep(0.2)
            lock_path = directory / f"{SERVICE}.owner.lock"
            fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

                def fenced():
                    control = _read(control_path)
                    state = read_service_state(SERVICE, runtime_dir=directory)
                    locked, live = os.fstat(fd), lock_path.lstat()
                    require(resolve_service_binding(SERVICE) == binding
                            and control and control.get("request_id") == request_id
                            and control.get("phase") == "drain"
                            and state and state.get("phase") == "parked" and state.get("ready") is False
                            and state.get("generation") == binding.generation
                            and stat.S_ISREG(locked.st_mode) and locked.st_uid == os.getuid()
                            and not locked.st_mode & 0o077 and locked.st_nlink == 1
                            and (locked.st_dev, locked.st_ino) == (live.st_dev, live.st_ino),
                            "NEWOW_H1_FENCE_LOST")

                service = NewowH1Boundary(SessionLocal, assert_fenced=fenced)
                now = datetime.now(UTC)
                verify_targets(plan, now)
                for group in plan["groups"].values():
                    require(service.plan(service._plan_members(group),
                                         recording_start=datetime.fromisoformat(group["recording_start"]),
                                         expires_at=datetime.fromisoformat(group["expires_at"]),
                                         now=now) == group, "NEWOW_H1_PREIMAGE_DRIFT")
                try:
                    started = True
                    with SessionLocal() as db, db.begin():
                        scope = NewowH1Boundary(lambda: _BorrowedSession(db), assert_fenced=fenced)
                        for group in plan["groups"].values():
                            scope.apply(group, expected_plan_hash=group["plan_hash"], now=datetime.now(UTC))
                        require(datetime.now(UTC) < min(
                            datetime.fromisoformat(group["expires_at"]) for group in plan["groups"].values()
                        ), "NEWOW_H1_SCOPE_EXPIRED")
                        fenced()
                except Exception:
                    independent = scope_readback(reader, plan)
                    definite = not independent
                    if not independent:
                        raise
                receipts = scope_readback(reader, plan)
                require(bool(receipts), "NEWOW_H1_READBACK_REQUIRED")
                definite = True
                write_once(attempt / "receipts.json", receipts)
            finally:
                os.close(fd)
        finally:
            if not started or definite:
                cancel_drain(SERVICE, request_id=request_id, runtime_dir=directory)
    return result(receipts)


def scope_readback(service, plan):
    receipts = {}
    for product, group in plan["groups"].items():
        receipt = service.status(group)
        if receipt is not None:
            receipts[product] = receipt
    require(not receipts or set(receipts) == set(plan["groups"]), "NEWOW_H1_SCOPE_PARTIAL_COMMIT")
    return receipts


def result(receipts):
    return {"status": "COMMITTED", "products": len(receipts), "routes": len(receipts) * 4}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("plan", "apply", "status"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--expected-plan-hash")
    parser.add_argument("--attempt", type=Path)
    args = parser.parse_args(argv)

    binding = resolve_service_binding(SERVICE)
    root = Path(__file__).resolve().parents[1]
    require(binding is not None and binding.enabled and Path(binding.root) == root,
            "NEWOW_H1_FORMAL_BINDING_REQUIRED")
    verify_release(root, binding.tag, binding.commit)
    require(args.plan.is_absolute() and args.plan.parent.resolve() == args.plan.parent,
            "NEWOW_H1_PLAN_PATH_INVALID")
    service = NewowH1Boundary(SessionLocal, assert_fenced=lambda: None)
    if args.phase == "plan":
        CohortHost().session_proof()
        plan = make_plan(binding, datetime.now(UTC), service)
        write_once(args.plan, plan)
        result = {"status": "PLANNED", "products": len(plan["groups"]), "plan_hash": plan["plan_hash"]}
    else:
        plan = json.loads(read_private_settings_content(args.plan))
        validate_plan(plan, binding, args.expected_plan_hash)
        if args.phase == "status":
            present = len(scope_readback(service, plan))
            result = {"status": "READBACK", "committed_products": present, "products": len(plan["groups"])}
        else:
            require(args.attempt is not None and args.attempt.is_absolute()
                    and args.attempt.parent.resolve() == args.attempt.parent, "NEWOW_H1_ATTEMPT_INVALID")
            result = apply(plan, binding, args.attempt)
    print(json.dumps(result))


if __name__ == "__main__":
    from sqlalchemy.exc import SQLAlchemyError
    from app.reference_trading.repository import RepositoryConflict

    try:
        main()
    except (RepositoryConflict, ValueError, RuntimeError, OSError, SQLAlchemyError) as error:
        code = str(error)
        if not code.isascii() or not code.replace("_", "").isalnum() or len(code) > 100:
            code = type(error).__name__
        print(json.dumps({"status": "BLOCKED", "code": code}))
        raise SystemExit(1)
