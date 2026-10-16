"""Local isolated PostgreSQL Paper CLI. No live enable or broker connection."""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("init", help="Create only the explicitly configured isolated Paper schema")
    reconcile = sub.add_parser("reconcile", help="Replay immutable Paper ledger without writes")
    reconcile.add_argument("--account", required=True)
    run = sub.add_parser("run", help="Explicit HISTORICAL_REPLAY, never a live worker")
    run.add_argument("--account", required=True)
    run.add_argument("--facts", type=Path, required=True)
    run.add_argument("--since", type=date.fromisoformat, required=True)
    run.add_argument("--through", type=date.fromisoformat, required=True)
    run.add_argument("--market-env", type=Path, required=True)
    run.add_argument("--canonical-root", type=Path, required=True)
    run.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # Capture before loading market configuration. Never reuse DATABASE_URL.
    paper_url = os.environ.get("GUIYI_PAPER_DATABASE_URL")
    if not paper_url:
        raise ValueError("PAPER_EXPLICIT_DATABASE_REQUIRED")
    from app.paper.ledger import PaperLedger
    ledger = PaperLedger(paper_url)
    try:
        if args.operation == "init":
            ledger.initialize_schema()
            result = {"status": "SCHEMA_INITIALIZED", "mode": "LOCAL_PAPER", "auto_order": False}
        elif args.operation == "reconcile":
            from app.paper.history import summary
            state, sequence = ledger.load(args.account)
            result = {**summary(state), "sequence": sequence, "verified": True}
        else:
            if args.since > args.through or not args.canonical_root.is_dir() or not args.market_env.is_file():
                raise ValueError("PAPER_INPUT_INVALID")
            from dotenv import load_dotenv
            load_dotenv(args.market_env, override=False)
            os.environ["GUIYI_CANONICAL_DATA_ROOT"] = str(args.canonical_root.resolve())
            from app.db.readonly import readonly_transaction
            from app.db.session import SessionLocal
            from app.market_data.composition import build_market_data_service
            from app.paper.history import commit_plan, load_historical_plan
            raw = json.loads(args.facts.read_text())
            with SessionLocal() as session, readonly_transaction(session, timeout_seconds=900):
                plan = load_historical_plan(build_market_data_service(session), raw, args.since, args.through)
            if args.dry_run:
                result = {**plan.expected_summary, "run_hash": plan.run_hash,
                          "command_count": len(plan.commands), "dry_run": True}
            else:
                result = commit_plan(ledger, args.account, plan)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        ledger.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        value = getattr(exc, "code", None) or str(exc)
        code = value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", value) else "PAPER_OPERATION_FAILED"
        print(json.dumps({"status": "BLOCKED", "code": code}))
        raise SystemExit(1) from None
