from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.backtest.trust_audit import (  # noqa: E402
    BacktestTrustAuditError,
    build_backtest_trust_audit,
    render_audit_markdown,
)
from app.db.session import SessionLocal  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 13 read-only backtest trust audit.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--report-id", type=int, help="BacktestReport id to audit")
    target.add_argument("--task-no", help="Audit latest report for a BacktestTask task_no")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument(
        "--allow-non-passed-quality",
        action="store_true",
        help="Do not warn when quality_status is non-failed but not passed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with SessionLocal() as session:
            audit = build_backtest_trust_audit(
                session,
                report_id=args.report_id,
                task_no=args.task_no,
                strict_quality=not args.allow_non_passed_quality,
            )
    except BacktestTrustAuditError as exc:
        print(_json({"ok": False, "readonly": True, "error": str(exc)}))
        return 1
    except SQLAlchemyError as exc:
        print(_json({"ok": False, "readonly": True, "error_type": type(exc).__name__, "error": _safe_error(exc)}))
        return 1

    if args.format == "markdown":
        print(render_audit_markdown(audit), end="")
    else:
        print(_json({"ok": True, **audit}))
    return 0


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _safe_error(exc: BaseException) -> str:
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    for marker in ("/Volumes/", "/Users/", "/private/", "\\Users\\"):
        message = message.replace(marker, "<local-path>/")
    lowered = message.lower()
    if any(token in lowered for token in ("password", "token", "secret", "license", "webhook")):
        return "<redacted>"
    return message[:500]


if __name__ == "__main__":
    raise SystemExit(main())
