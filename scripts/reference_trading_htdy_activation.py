#!/usr/bin/env python3
"""Explicit plan/apply/readback for the exact operational HTDY 60m scope.

No DB URL, dotenv, or connection is loaded at import. Apply requires an exact
plan file, the separately supplied hash, and an explicit database URL.
"""

from __future__ import annotations

import argparse
from datetime import datetime, UTC
import json
import os
from pathlib import Path
import sys

from app.reference_trading.repository import RepositoryConflict


def _strict_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("HTDY_PLAN_JSON_DUPLICATE_KEY")
        value[key] = item
    return value


def _read_plan(path: Path):
    if not path.is_file() or path.is_symlink():
        raise ValueError("HTDY_PLAN_FILE_INVALID")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("HTDY_PLAN_JSON_INVALID")))
    if not isinstance(value, dict):
        raise ValueError("HTDY_PLAN_JSON_INVALID")
    return value


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--recording-start", required=True)
    plan.add_argument("--expires-at", required=True)
    plan.add_argument("--host", required=True)
    plan.add_argument("--environment", required=True)
    plan.add_argument("--output", type=Path, required=True)
    for name in ("apply", "readback"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--expected-plan-hash", required=True)
        command.add_argument("--database-url-env", required=True,
                             help="Name of an explicitly exported database URL environment variable")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        from app.market_data.operational_universe import load_operational_products
        from app.reference_trading.htdy_activation import (
            apply_operational_htdy_activation, plan_operational_htdy_activation,
            readback_htdy_activation,
        )

        operational = load_operational_products()
        if len(operational) != 60:
            raise ValueError("HTDY_OPERATIONAL_SCOPE_NOT_60")
        if args.command == "plan":
            result = plan_operational_htdy_activation(
                operational=operational,
                recording_start=datetime.fromisoformat(args.recording_start),
                expires_at=datetime.fromisoformat(args.expires_at), now=datetime.now(UTC),
                host=args.host, environment=args.environment)
            # Exclusive creation prevents overwriting a frozen plan.
            with args.output.open("x", encoding="utf-8") as output:
                json.dump(result, output, ensure_ascii=False, sort_keys=True, indent=2)
                output.write("\n")
            print(json.dumps({"plan_hash": result["plan_hash"], "products": 60,
                              "output": str(args.output)}, ensure_ascii=False))
            return 0
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        plan = _read_plan(args.plan)
        database_url = os.environ.get(args.database_url_env, "")
        if not database_url.startswith("postgresql+psycopg://"):
            raise ValueError("HTDY_DATABASE_URL_INVALID")
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            factory = sessionmaker(engine)
            if args.command == "apply":
                result = apply_operational_htdy_activation(
                    factory, plan, expected_plan_hash=args.expected_plan_hash,
                    operational=operational, now=datetime.now(UTC))
            else:
                result = readback_htdy_activation(
                    factory, plan, expected_plan_hash=args.expected_plan_hash,
                    operational=operational)
        finally:
            engine.dispose()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        code = str(error)
        if not code.startswith(("HTDY_", "PLAN_")):
            code = "HTDY_CLI_INPUT_INVALID"
    except RepositoryConflict as error:
        code = str(error)
    except Exception:
        code = "HTDY_CLI_FAILED_READBACK_REQUIRED" if args.command == "apply" else "HTDY_CLI_FAILED"
    print(json.dumps({"status": "BLOCKED", "reason": code}), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
