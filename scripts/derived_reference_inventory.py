#!/usr/bin/env python3
"""Emit a stable, read-only derived/reference inventory as canonical JSON."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

from sqlalchemy import create_engine


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError("CLI_ARGUMENT_INVALID")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.derived_reference_inventory import (  # noqa: E402
    DerivedReferenceInventoryConfig,
    build_derived_reference_inventory,
)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description="Read-only derived/reference inventory; it has no delete or apply mode.", allow_abbrev=False)
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--database-url-env", help="Explicit URL environment-variable name for an external read-only Gate.")
    parser.add_argument("--max-files", type=int, default=10_000)
    parser.add_argument("--max-file-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--max-total-bytes", type=int, default=1024 * 1024 * 1024)
    parser.add_argument("--max-ids", type=int, default=1_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except ValueError as exc:
        print(json.dumps({"schema_version": 1, "command": "derived-reference-inventory", "readonly": True, "status": "error", "error_type": type(exc).__name__}, sort_keys=True), file=sys.stderr)
        return 2
    connection = None
    engine = None
    try:
        if args.database_url_env and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", args.database_url_env):
            raise ValueError("DATABASE_URL_ENV_NAME_INVALID")
        database_url = os.environ.get(args.database_url_env) if args.database_url_env else None
        if database_url:
            engine = create_engine(database_url)
            connection = engine.connect()
        payload = build_derived_reference_inventory(
            DerivedReferenceInventoryConfig(
                repo_root=args.repo_root.resolve(strict=False),
                data_root=args.data_root.absolute(),
                max_files=args.max_files,
                max_file_bytes=args.max_file_bytes,
                max_total_bytes=args.max_total_bytes,
                max_ids=args.max_ids,
            ),
            connection=connection,
        )
    except Exception as exc:  # noqa: BLE001 - JSON CLI must preserve a safe failure boundary.
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "command": "derived-reference-inventory",
                    "readonly": True,
                    "status": "error",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        if connection is not None:
            connection.close()
        if engine is not None:
            engine.dispose()
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
