#!/usr/bin/env python3
"""Prepare exact current-formula histories for a separately fenced transition.

Default is plan-only. Existing reference history is advanced through P4; no
Canonical/provider/notification/order operation is available here.
"""

import argparse
from dataclasses import asdict
from datetime import date, datetime, UTC
import json
import os
from pathlib import Path
import re


from app.reference_trading.models import ReferenceStream
from app.reference_trading.planning import (
    HistoricalReferenceRequest,
    HistoricalStreamRequest,
    WorkBudget,
    plan_to_dict,
    plan_from_dict,
)
from app.reference_trading.plan_bundle import write_plan, read_plan


def write_private(path, value):
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    temporary = path.with_name(path.name + ".pending")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def identity(product, strategy, frequency):
    from app.market_data.newow.product_release import candidate_input_quality_policy
    from guiyi_quant.newow.product_adapters import build_product_identity
    from guiyi_quant.newow.product_identity import (
        reference_model_version,
        futures_adaptation_version,
    )
    from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
    from guiyi_quant.reference_trading import StreamIdentity

    policy = candidate_input_quality_policy(product, frequency, candidate_weekly=False)
    if strategy == "dual_fusion":
        return build_fusion_stream_identity(
            product, frequency, input_quality_policy=policy
        )
    p = build_product_identity(
        product, strategy, frequency, input_quality_policy=policy
    )
    return StreamIdentity(
        "newow_" + strategy,
        p.formula_versions,
        p.profile_id,
        reference_model_version(p),
        futures_adaptation_version(frequency, policy),
        product,
        frequency,
        "actual_dominant",
        "historical_replay",
        None,
    )


def committed_readback(factory, record, *, expected_stream_id=None):
    """Skip only a still-published, checksummed exact completion."""
    from app.reference_trading.newow_bootstrap import NewowForwardBootstrap

    if record.get("status") != "COMMITTED" or (expected_stream_id is not None and record.get("stream_id") != expected_stream_id):
        raise ValueError("FORMULA_PREPARE_RECEIPT_INVALID")
    reports = record.get("result", {}).get("streams", [])
    if len(reports) != 1:
        raise ValueError("FORMULA_PREPARE_RECEIPT_INVALID")
    snapshot = reports[0].get("snapshot")
    if (not isinstance(snapshot, dict) or reports[0].get("stream_id") != record.get("stream_id")
            or reports[0].get("status") not in {"completed", "noop"}
            or snapshot.get("stream_id") != record.get("stream_id")):
        raise ValueError("FORMULA_PREPARE_RECEIPT_INVALID")
    with factory() as db:
        if db.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text
            db.execute(text("SET TRANSACTION READ ONLY"))
        *_, binding = NewowForwardBootstrap(factory)._source(db, record["stream_id"])
        if any(
            binding[key] != snapshot[key] for key in ("stream_id", "revision_id", "seq")
        ):
            raise ValueError("FORMULA_PREPARE_READBACK_DRIFT")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--since", type=date.fromisoformat, required=True)
    parser.add_argument("--through", type=date.fromisoformat, required=True)
    parser.add_argument("--product", action="append")
    parser.add_argument("--frequency", action="append", choices=["1w", "1d", "60m"])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    from app.market_data.operational_universe import load_operational_products
    from app.db.session import SessionLocal
    from app.reference_trading.composition import open_historical_reference_components

    operational = set(load_operational_products())
    products = sorted(set(args.product or operational))
    if (
        not products
        or not set(products) <= operational
        or any(not re.fullmatch("[a-z]{1,8}", p) for p in products)
    ):
        raise ValueError("FORMULA_PREPARE_SCOPE_INVALID")
    directory = args.directory
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("FORMULA_PREPARE_PATH_INVALID")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.resolve() != directory or directory.stat().st_mode & 0o077:
        raise ValueError("FORMULA_PREPARE_PATH_INVALID")
    header = directory / "scope.json"
    body = dict(
        version="newow_formula_history_prepare_v1",
        products=products,
        frequencies=args.frequency or ["1w", "1d", "60m"],
        since=args.since.isoformat(),
        through=args.through.isoformat(),
        rebuild=args.rebuild,
    )
    if header.exists():
        saved = json.loads(header.read_text())
        if any(saved[k] != v for k, v in body.items()):
            raise ValueError("FORMULA_PREPARE_SCOPE_DRIFT")
    else:
        saved = {**body, "as_of": datetime.now(UTC).isoformat()}
        write_private(header, saved)
    as_of = datetime.fromisoformat(saved["as_of"])
    for product in products:
        for frequency in body["frequencies"]:
            with open_historical_reference_components(reuse_market_inputs=True) as (
                planner,
                service,
            ):
                for strategy in ["trend", "oscillation", "dual_fusion"]:
                    key = product + "-" + frequency + "-" + strategy
                    target = identity(product, strategy, frequency)
                    status_path = directory / (key + ".status.json")
                    if status_path.exists():
                        prior = json.loads(status_path.read_text())
                        if prior["status"] == "COMMITTED":
                            committed_readback(SessionLocal, prior, expected_stream_id=target.stream_id)
                            print(key, "already_committed", flush=True)
                            continue
                        raise ValueError(
                            "FORMULA_PREPARE_PRIOR_ATTEMPT_REQUIRES_READBACK"
                        )
                    with SessionLocal() as db:
                        existing = db.get(ReferenceStream, target.stream_id)
                        active = bool(existing and existing.active_revision_id)
                    operation = (
                        "rebuild"
                        if args.rebuild and active
                        else "advance"
                        if active
                        else "build"
                    )
                    request = HistoricalReferenceRequest(
                        operation,
                        (
                            HistoricalStreamRequest(
                                target, args.since, args.through, as_of
                            ),
                        ),
                        WorkBudget(1, 100000, 600, 256 * 1024 * 1024),
                    )
                    plan_path = directory / (key + ".plan.json")
                    if plan_path.exists():
                        plan = plan_from_dict(read_plan(plan_path))
                        if (
                            plan.operation != operation
                            or len(plan.streams) != 1
                            or plan.streams[0].request != request.streams[0]
                        ):
                            raise ValueError("FORMULA_PREPARE_PLAN_DRIFT")
                    else:
                        plan = planner.plan(request)
                        write_plan(plan_path, plan_to_dict(plan))
                    if not args.apply:
                        print(key, "PLANNED", plan.plan_hash, flush=True)
                        continue
                    record = dict(
                        status="REQUESTED",
                        plan_hash=plan.plan_hash,
                        operation=operation,
                        stream_id=target.stream_id,
                        source_token=plan.streams[0].source_token,
                    )
                    write_private(status_path, record)
                    result = getattr(
                        service,
                        {
                            "build": "execute",
                            "advance": "advance",
                            "rebuild": "rebuild",
                        }[operation],
                    )(plan, plan.plan_hash)
                    record.update(
                        status="COMMITTED"
                        if result.status in {"completed", "noop"}
                        else "READBACK_REQUIRED",
                        result=asdict(result),
                    )
                    if record["status"] == "COMMITTED":
                        committed_readback(SessionLocal, record)
                    write_private(status_path, record)
                    print(key, result.status, result.streams[0].reason, flush=True)
                    if record["status"] != "COMMITTED":
                        raise ValueError("FORMULA_PREPARE_RESULT_REQUIRES_READBACK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
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
