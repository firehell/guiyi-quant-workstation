#!/usr/bin/env python3
"""Emit a stable, read-only derived/reference inventory as canonical JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.derived_reference_inventory import (  # noqa: E402
    DerivedReferenceInventoryConfig,
    build_derived_reference_inventory,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only derived/reference inventory; it has no delete or apply mode.")
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--database-url", help="Optional injected database URL; never echoed to stdout or stderr.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    connection = None
    engine = None
    try:
        if args.database_url:
            engine = create_engine(args.database_url)
            connection = engine.raw_connection()
        payload = build_derived_reference_inventory(
            DerivedReferenceInventoryConfig(
                repo_root=args.repo_root.resolve(strict=False),
                data_root=args.data_root.resolve(strict=False),
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
