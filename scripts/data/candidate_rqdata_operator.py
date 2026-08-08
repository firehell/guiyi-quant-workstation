#!/usr/bin/env python3
"""RQData-only Candidate operator (preflight / update / audit / verify).

Uses ``build_candidate_historical_data_manager`` + ``HistoricalDataManager.update``
with ``legacy=None``. Database URL from ``GUIYI_GATE_A_DATABASE_URL`` or
``--database-url``. Apply requires ``--i-confirm-candidate-apply``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RQData-only Candidate operator")
    parser.add_argument(
        "command",
        choices=("preflight", "update", "audit", "verify", "reset"),
        help="Operator phase",
    )
    parser.add_argument("--through", default="2026-08-07")
    parser.add_argument("--database-url", required=False)
    parser.add_argument(
        "--candidate-root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--candidate-catalog",
        default="guiyi_canonical_candidate_20260807",
    )
    parser.add_argument(
        "--products",
        default="jm",
        help="Comma-separated product symbols (default: jm)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="For update: perform writes (still requires intent flag)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Allow non-empty candidate catalog/root",
    )
    parser.add_argument(
        "--i-confirm-candidate-apply",
        action="store_true",
        help="Required single-use intent acknowledgement for apply",
    )
    return parser.parse_args(argv)


def _database_url(args: argparse.Namespace) -> str:
    value = (args.database_url or os.environ.get("GUIYI_GATE_A_DATABASE_URL") or "").strip()
    if not value:
        raise SystemExit("GUIYI_GATE_A_DATABASE_URL or --database-url is required")
    return value


def _products(raw: str) -> tuple[str, ...]:
    items = tuple(
        dict.fromkeys(part.strip().lower() for part in raw.split(",") if part.strip())
    )
    if not items:
        raise SystemExit("PRODUCTS_REQUIRED")
    return items


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    api_root = root / "services" / "quant-api"
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    from app.core.env import load_project_env
    from app.market_data.gate_a_operator import (  # noqa: WPS433
        CandidateRunConfig,
        GateAOperatorError,
        default_candidate_root,
        open_candidate_session,
        reset_candidate_bar_catalog,
        reset_candidate_storage,
        run_rqdata_audit,
        run_rqdata_preflight,
        run_rqdata_update,
        run_rqdata_verify,
    )

    load_project_env()
    args = _parse_args(argv)
    database_url = _database_url(args)
    through = date.fromisoformat(args.through)
    candidate_root = (
        args.candidate_root or default_candidate_root(through)
    ).resolve()
    config = CandidateRunConfig(
        through=through,
        candidate_root=candidate_root,
        candidate_catalog=args.candidate_catalog,
        products=_products(args.products),
    )

    try:
        if args.command == "preflight":
            payload = run_rqdata_preflight(
                config,
                database_url=database_url,
                resume=bool(args.resume),
            )
        elif args.command == "reset":
            session = open_candidate_session(database_url)
            try:
                from app.market_data.gate_a_operator import assert_isolated_database

                assert_isolated_database(database_url, config.candidate_catalog)
                payload = {
                    "action": "candidate_rqdata_reset",
                    "status": "passed",
                    "catalog": reset_candidate_bar_catalog(session),
                    "storage": reset_candidate_storage(config.candidate_root),
                }
            finally:
                session.close()
        elif args.command == "update":
            session = open_candidate_session(database_url)
            try:
                from app.market_data.gate_a_operator import assert_isolated_database

                assert_isolated_database(database_url, config.candidate_catalog)
                payload = run_rqdata_update(
                    config,
                    session=session,
                    apply=bool(args.apply),
                    require_intent_token=True,
                    intent_confirmed=bool(args.i_confirm_candidate_apply),
                )
            finally:
                session.close()
        elif args.command == "audit":
            session = open_candidate_session(database_url)
            try:
                from app.market_data.gate_a_operator import assert_isolated_database

                assert_isolated_database(database_url, config.candidate_catalog)
                payload = run_rqdata_audit(config, session=session)
            finally:
                session.close()
        else:
            session = open_candidate_session(database_url)
            try:
                from app.market_data.gate_a_operator import assert_isolated_database

                assert_isolated_database(database_url, config.candidate_catalog)
                payload = run_rqdata_verify(config, session=session)
            finally:
                session.close()
    except GateAOperatorError as exc:
        print(json.dumps({"status": "failed", "error": exc.code}, ensure_ascii=False))
        return 2
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - operator boundary
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "CANDIDATE_RQDATA_OPERATOR_FAILED",
                    "detail": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 1

    print(json.dumps(payload, ensure_ascii=False, default=str))
    if args.command == "update" and args.apply:
        update = payload.get("update") or {}
        status = update.get("status") if isinstance(update, dict) else None
        return 0 if status in {"passed", "noop"} else 1
    return 0 if payload.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
