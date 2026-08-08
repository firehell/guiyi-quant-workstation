#!/usr/bin/env python3
"""Migration-only Gate A candidate operator (plan / preflight / apply / verify).

Database URL must come from ``GUIYI_GATE_A_DATABASE_URL`` (preferred) or
``--database-url``. Prefer the env var so credentials are not visible in ``ps``.

Apply requires ``--i-confirm-gate-a-apply``.
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
    parser = argparse.ArgumentParser(description="Gate A candidate operator")
    parser.add_argument(
        "command",
        choices=("plan", "preflight", "apply", "verify", "reset-bars", "repair-sessions"),
        help="Operator phase",
    )
    parser.add_argument("--scope-json", type=Path, required=False)
    parser.add_argument("--output-json", type=Path, required=False)
    parser.add_argument("--database-url", required=False)
    parser.add_argument("--expected-scope-digest", required=False)
    parser.add_argument("--expected-report-sha256", required=False)
    parser.add_argument("--through", default="2026-08-07")
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
        "--resume",
        action="store_true",
        help="Allow non-empty candidate root / catalog for resume",
    )
    parser.add_argument(
        "--i-confirm-gate-a-apply",
        action="store_true",
        help="Required single-use intent acknowledgement for apply",
    )
    return parser.parse_args(argv)


def _database_url(args: argparse.Namespace) -> str:
    value = (args.database_url or os.environ.get("GUIYI_GATE_A_DATABASE_URL") or "").strip()
    if not value:
        raise SystemExit("GUIYI_GATE_A_DATABASE_URL or --database-url is required")
    return value


def _active_products() -> tuple[str, ...]:
    path = _repo_root() / "data" / "universe" / "active_products.txt"
    products = tuple(
        item.strip().lower()
        for item in path.read_text(encoding="utf-8").splitlines()
        if item.strip()
    )
    if len(products) != 69 or len(set(products)) != 69:
        raise SystemExit("ACTIVE_UNIVERSE_INVALID")
    return products


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    api_root = root / "services" / "quant-api"
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    from app.market_data.gate_a_operator import (  # noqa: WPS433
        GateAOperatorError,
        assert_isolated_database,
        build_gate_a_scope_report,
        file_sha256,
        load_exact_scope,
        open_candidate_session,
        repair_night_session_effective_from,
        reset_candidate_bar_catalog,
        run_apply,
        run_preflight,
        run_verify,
    )

    args = _parse_args(argv)
    database_url = _database_url(args)

    try:
        if args.command == "plan":
            through = date.fromisoformat(args.through)
            candidate_root = (
                args.candidate_root
                or root
                / "data/canonical-candidates/converge-canonical-data-foundation"
                / f"through={through.isoformat()}"
            ).resolve()
            session = open_candidate_session(database_url)
            try:
                assert_isolated_database(database_url, args.candidate_catalog)
                report = build_gate_a_scope_report(
                    session=session,
                    products=_active_products(),
                    through=through,
                    candidate_root=candidate_root,
                    candidate_catalog=args.candidate_catalog,
                )
            finally:
                session.close()
            output = (
                args.output_json
                or root
                / "data/canonical-candidates/converge-canonical-data-foundation"
                / f"through={through.isoformat()}.evidence"
                / f"exact-scope-rule2-delisted-through-{through.isoformat()}.json"
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            payload = {
                "action": "gate_a_plan",
                "status": "passed",
                "output_json": output.as_posix(),
                "scope_digest": report["scope_digest"],
                "report_sha256": file_sha256(output),
                "counts": report["counts"],
            }
        elif args.command == "reset-bars":
            session = open_candidate_session(database_url)
            try:
                assert_isolated_database(database_url, args.candidate_catalog)
                payload = {
                    "action": "gate_a_reset_bars",
                    "status": "passed",
                    **reset_candidate_bar_catalog(session),
                }
            finally:
                session.close()
        elif args.command == "repair-sessions":
            session = open_candidate_session(database_url)
            try:
                assert_isolated_database(database_url, args.candidate_catalog)
                payload = repair_night_session_effective_from(session, _active_products())
            finally:
                session.close()
        else:
            if not args.scope_json or not args.expected_scope_digest or not args.expected_report_sha256:
                raise SystemExit(
                    "--scope-json --expected-scope-digest --expected-report-sha256 required"
                )
            loaded = load_exact_scope(
                args.scope_json,
                expected_scope_digest=args.expected_scope_digest,
                expected_report_sha256=args.expected_report_sha256,
            )
            if args.command == "preflight":
                payload = run_preflight(
                    loaded,
                    database_url=database_url,
                    resume=bool(args.resume),
                )
            elif args.command == "apply":
                assert_isolated_database(database_url, loaded.candidate_catalog)
                session = open_candidate_session(database_url)
                try:
                    payload = run_apply(
                        loaded,
                        session=session,
                        resume=bool(args.resume),
                        require_intent_token=True,
                        intent_confirmed=bool(args.i_confirm_gate_a_apply),
                    )
                finally:
                    session.close()
            else:
                assert_isolated_database(database_url, loaded.candidate_catalog)
                session = open_candidate_session(database_url)
                try:
                    payload = run_verify(loaded, session=session)
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
                    "error": "GATE_A_OPERATOR_FAILED",
                    "detail": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 1

    print(json.dumps(payload, ensure_ascii=False, default=str))
    if args.command == "apply":
        bootstrap = payload.get("bootstrap") or {}
        status = bootstrap.get("status") if isinstance(bootstrap, dict) else None
        return 0 if status in {"passed", "noop"} else 1
    return 0 if payload.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
