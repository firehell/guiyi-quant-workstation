from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = SCRIPT_PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED = "ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED"
ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED = "ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED"
FIXED_AUDIT_END = date(2026, 7, 10)
CANONICAL_UNIVERSE_PATH = Path("data/universe/full_products_90.txt")
DEFAULT_OUTPUT_DIR = Path(
    "data/reports/full_history_audit_v2_20260710/actual_dominant_roll_006"
)
WRITE_BOUNDARY_FLAGS = {
    "writes_database": False,
    "writes_parquet": False,
    "writes_manifest": False,
    "writes_quality": False,
    "calls_provider_api": False,
    "calls_rqdata": False,
}
ActualDominantRollAuditConfig = None
run_actual_dominant_roll_audit = None
write_actual_dominant_roll_reports = None


class CompactJsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        _emit(
            _result_payload(
                status="INVALID_ARGUMENTS",
                output_dir="unavailable",
                error=_redact_database_url(message),
                error_type="ArgumentError",
            ),
            error=True,
        )
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = CompactJsonArgumentParser(
        description="Read-only actual rank-one dominant-contract roll audit.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    verify.add_argument("--audit-end", type=date.fromisoformat, default=FIXED_AUDIT_END)
    verify.add_argument("--scan-mode", choices=("quick", "full"), default="quick")
    verify.add_argument("--products-file", type=Path, default=CANONICAL_UNIVERSE_PATH)
    verify.add_argument("--product", action="append", default=[])
    verify.add_argument("--max-workers", type=int, default=4)
    verify.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve(strict=False)
    output_dir = _resolve(project_root, args.output_dir)
    if not args.output_dir.is_absolute() and not output_dir.is_relative_to(project_root):
        _emit(
            _result_payload(
                status="INVALID_OUTPUT_DIRECTORY",
                output_dir=output_dir,
                error="relative output directory must remain beneath project root",
            ),
            error=True,
        )
        return 2
    products_file = _resolve(project_root, args.products_file)
    canonical_products_file = _resolve(project_root, CANONICAL_UNIVERSE_PATH)
    if products_file != canonical_products_file:
        _emit(
            _result_payload(
                status="INVALID_PRODUCTS_FILE",
                output_dir=output_dir,
                error=(
                    "products file must point to canonical path "
                    f"{CANONICAL_UNIVERSE_PATH}"
                ),
            ),
            error=True,
        )
        return 2
    if output_dir.exists():
        _emit(
            _result_payload(
                status="OUTPUT_EXISTS",
                output_dir=output_dir,
                error=f"refusing to overwrite existing output directory: {output_dir}",
            ),
            error=True,
        )
        return 3

    load_dotenv(project_root / ".env", override=False)
    try:
        config_type, audit_runner, report_writer, session_factory = (
            _load_runtime_dependencies()
        )

        with session_factory() as session:
            result = audit_runner(
                config_type(
                    project_root=project_root,
                    audit_end=args.audit_end,
                    scan_mode=args.scan_mode,
                    products=tuple(args.product),
                    max_workers=args.max_workers,
                    require_postgresql=True,
                ),
                session,
            )
            paths = report_writer(result, output_dir)
    except FileExistsError as exc:
        _emit(
            _result_payload(
                status="OUTPUT_EXISTS",
                output_dir=output_dir,
                error=_redact_database_url(str(exc))[:800],
                error_type=type(exc).__name__,
            ),
            error=True,
        )
        return 3
    except Exception as exc:  # noqa: BLE001 - fail-closed CLI boundary with redaction.
        message = _redact_database_url(str(exc))
        database_error = type(exc).__name__ in {
            "OperationalError",
            "InterfaceError",
            "DatabaseError",
        }
        status = (
            "ENV_BLOCKED_DB"
            if database_error
            or "ENV_BLOCKED_DB" in message
            or "POSTGRES" in message.upper()
            or "DATABASE" in message.upper()
            else "ACTUAL_DOMINANT_ROLL_AUDIT_BLOCKED"
        )
        _emit(
            _result_payload(
                status=status,
                output_dir=output_dir,
                error=message[:800],
                error_type=type(exc).__name__,
            ),
            error=True,
        )
        return 2

    _emit(
        _result_payload(
            status=result.summary["status"],
            output_dir=output_dir,
            summary=result.summary,
            outputs=paths,
        )
    )
    if result.summary["status"] == ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED:
        return 0
    if result.summary["status"] == ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED:
        return 4
    return 2


def _resolve(project_root: Path, value: Path) -> Path:
    return (value if value.is_absolute() else project_root / value).resolve(strict=False)


def _load_runtime_dependencies():
    from app.db.session import SessionLocal  # noqa: PLC0415
    from app.services.rqdata_ingest.actual_dominant_roll_audit_v2 import (  # noqa: PLC0415
        ActualDominantRollAuditConfig as RuntimeConfig,
        run_actual_dominant_roll_audit as runtime_audit_runner,
        write_actual_dominant_roll_reports as runtime_report_writer,
    )

    return (
        ActualDominantRollAuditConfig or RuntimeConfig,
        run_actual_dominant_roll_audit or runtime_audit_runner,
        write_actual_dominant_roll_reports or runtime_report_writer,
        SessionLocal,
    )


def _result_payload(
    *,
    status: str,
    output_dir: Path | str,
    error: str | None = None,
    error_type: str | None = None,
    summary: dict[str, object] | None = None,
    outputs: dict[str, Path] | None = None,
) -> dict[str, object]:
    summary = summary or {}
    count_keys = (
        "product_count",
        "rank1_mapping_count",
        "residual_count",
        "hard_jm_residual_count",
        "formal_residual_count",
        "inventory_residual_count",
    )
    payload: dict[str, object] = {
        "status": status,
        "output_directory": str(output_dir),
        "counts": {key: summary[key] for key in count_keys if key in summary},
        "db_snapshot_source": summary.get(
            "db_snapshot_source",
            "direct_postgresql" if summary.get("direct_postgresql") else "unavailable",
        ),
        **{
            key: bool(summary.get(key, value))
            for key, value in WRITE_BOUNDARY_FLAGS.items()
        },
    }
    if outputs is not None:
        payload["outputs"] = {name: str(path) for name, path in outputs.items()}
    if error is not None:
        payload["error"] = error
    if error_type is not None:
        payload["error_type"] = error_type
    return payload


def _emit(payload: dict[str, object], *, error: bool = False) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        file=sys.stderr if error else sys.stdout,
    )


def _redact_database_url(message: str) -> str:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        return message
    normalized_url = _normalize_database_url(database_url)
    replacements = {
        database_url: "[REDACTED_DATABASE_URL]",
        normalized_url: "[REDACTED_DATABASE_URL]",
    }
    for candidate in (database_url, normalized_url):
        try:
            password = urlsplit(candidate).password
        except ValueError:
            password = None
        if password:
            replacements[password] = "[REDACTED_DATABASE_PASSWORD]"
            replacements[unquote(password)] = "[REDACTED_DATABASE_PASSWORD]"
    for sensitive in sorted(replacements, key=len, reverse=True):
        if sensitive:
            message = message.replace(sensitive, replacements[sensitive])
    return message


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    return database_url


if __name__ == "__main__":
    raise SystemExit(main())
