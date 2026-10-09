#!/usr/bin/env python3
"""Plan Newow forward warm-up read-only; apply one exact product explicitly."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
import tempfile
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.url import normalize_database_url
from app.market_data.operational_universe import load_active_products, load_operational_products
from app.reference_trading.newow_bootstrap import NewowForwardBootstrap, _hash, validate_product_scope
from app.reference_trading.repository import RepositoryConflict
from app.reference_trading.recording_scope import FREQUENCIES, strategies_for
from scripts.newow_weekly_recovery import load_private_readonly_settings


def _instant(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("BOOTSTRAP_TIME_INVALID")
    return parsed


def apply_product(service, scope_plan, *, product, expected_plan_hash, now, on_progress=None):
    if (scope_plan.get("version") not in {"newow_forward_bootstrap_scope_v1", "newow_forward_bootstrap_scope_v2"}
            or scope_plan.get("plan_hash") != expected_plan_hash
            or _hash({key: value for key, value in scope_plan.items() if key != "plan_hash"}) != expected_plan_hash):
        raise RepositoryConflict("PLAN_HASH_CONFLICT")
    product = product.lower()
    items = [item for item in scope_plan["items"] if item["product"] == product]
    frequencies = scope_plan.get("frequencies", ["1w", "1d", "60m"])
    if (not isinstance(frequencies, list) or not frequencies
            or any(not isinstance(frequency, str) for frequency in frequencies)
            or len(set(frequencies)) != len(frequencies) or not set(frequencies) <= set(FREQUENCIES)):
        raise RepositoryConflict("BOOTSTRAP_FREQUENCY_SCOPE_INVALID")
    expected = {(strategy, frequency) for frequency in frequencies for strategy in strategies_for(frequency)}
    if (len(items) != len(expected) or {(item["strategy"], item["frequency"]) for item in items} != expected
            or any(item["status"] != "ready" or not item.get("plan") for item in items)):
        raise RepositoryConflict("BOOTSTRAP_PRODUCT_NOT_READY")
    for item in items:
        nested = item["plan"]
        if (nested.get("product"), nested.get("strategy"), nested.get("frequency")) != (
            item["product"], item["strategy"], item["frequency"]
        ):
            raise RepositoryConflict("BOOTSTRAP_PRODUCT_PLAN_IDENTITY_CONFLICT")
    order = {strategy: index for index, strategy in enumerate(("trend", "oscillation", "main_rise", "dual_fusion"))}
    periods = {frequency: index for index, frequency in enumerate(FREQUENCIES)}
    items.sort(key=lambda item: (periods[item["frequency"]], order[item["strategy"]]))
    # Each period's three base streams are initialized before fusion.
    results = []
    for item in items:
        plan = item["plan"]
        if on_progress is not None:
            on_progress(item, None, results)
        result = service.apply(plan, expected_plan_hash=plan["plan_hash"], now=now())
        results.append({"product": product, "strategy": item["strategy"], "frequency": item["frequency"], **result})
        if on_progress is not None:
            on_progress(item, result, results)
    return {"version": "newow_forward_bootstrap_receipt_v1", "scope_plan_hash": expected_plan_hash,
            "product": product, "results": results}


def _write_result(path, result):
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-env", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--product", action="append")
    parser.add_argument("--frequency", action="append", choices=FREQUENCIES)
    parser.add_argument("--recording-start")
    parser.add_argument("--expires-at")
    parser.add_argument("--host", default="local")
    parser.add_argument("--environment", default="production")
    parser.add_argument("--recovery-policy", choices=("block", "interrupt_and_restart"), default="block")
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan-hash")
    args = parser.parse_args(argv)
    if args.apply and (not args.plan_file or not args.expected_plan_hash or not args.product or len(args.product) != 1):
        parser.error("--apply requires --plan-file, --expected-plan-hash and one --product")
    if not args.apply and (not args.recording_start or not args.expires_at):
        parser.error("planning requires --recording-start and --expires-at")
    engine = None
    reserved = False
    journal = {"version": "newow_forward_bootstrap_journal_v1", "status": "PREPARING", "results": []}
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.output.open("x", encoding="utf-8") as handle:
                json.dump(journal, handle)
            reserved = True
        except FileExistsError as error:
            raise RepositoryConflict("BOOTSTRAP_OUTPUT_EXISTS") from error
        # Safe private loader returns credentials only to the program, never stdout.
        settings, _ = load_private_readonly_settings(args.project_env)
        engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
        service = NewowForwardBootstrap(sessionmaker(engine, expire_on_commit=False))
        operational, active = load_operational_products(), load_active_products()
        products = validate_product_scope(operational, active)
        if args.apply:
            plan = json.loads(args.plan_file.read_text(encoding="utf-8"))
            if tuple(plan.get("products", ())) != products:
                raise RepositoryConflict("BOOTSTRAP_PRODUCT_SCOPE_DRIFT")
            journal["scope_plan_hash"] = args.expected_plan_hash
            def progress(item, receipt, completed):
                journal.update({"status": "APPLYING", "results": list(completed),
                    "current": {"product": item["product"], "strategy": item["strategy"],
                                "frequency": item["frequency"], "plan_hash": item["plan"]["plan_hash"],
                                "target_stream_id": item["plan"]["target_stream_id"],
                                "commit_state": "receipt_read_back" if receipt else "readback_required"}})
                _write_result(args.output, journal)
            result = apply_product(service, plan, product=args.product[0],
                expected_plan_hash=args.expected_plan_hash, now=lambda: datetime.now(UTC), on_progress=progress)
        else:
            result = service.plan_scope(operational, active, selected_products=args.product, selected_frequencies=args.frequency,
                recording_start=_instant(args.recording_start), expires_at=_instant(args.expires_at),
                host=args.host, environment=args.environment, recovery_policy=args.recovery_policy,
                now=datetime.now(UTC))
        _write_result(args.output, result)
        print(json.dumps({"status": "APPLIED" if args.apply else "PLANNED", "output": str(args.output),
                          "plan_hash": result.get("plan_hash", result.get("scope_plan_hash"))}))
        return 0
    except (RepositoryConflict, ValueError) as error:
        code = str(error) if isinstance(error, RepositoryConflict) else "BOOTSTRAP_INPUT_INVALID"
        if reserved:
            journal.update({"status": "BLOCKED", "reason": code})
            _write_result(args.output, journal)
        print(json.dumps({"status": "BLOCKED", "reason": code}), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - never expose credentials, SQL or connection errors
        if reserved:
            journal.update({"status": "BLOCKED", "reason": "BOOTSTRAP_EXECUTION_FAILED_READBACK_REQUIRED"})
            try:
                _write_result(args.output, journal)
            except OSError:
                pass
        print(json.dumps({"status": "BLOCKED", "reason": "BOOTSTRAP_EXECUTION_FAILED_READBACK_REQUIRED"}), file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
