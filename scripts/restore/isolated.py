from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from sqlalchemy.engine import make_url

from scripts.restore.core import DockerPostgresRuntime, RestoreDependencies, RestoreError, execute_isolated_restore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Restore a W7 full artifact into disposable isolated resources.")
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--target-database", required=True)
    parser.add_argument("--target-data-root", type=Path, required=True)
    parser.add_argument("--confirm-isolated-restore", action="store_true")
    return parser


def default_dependencies() -> RestoreDependencies:
    from app.db.session import DATABASE_URL, PROJECT_ROOT
    return RestoreDependencies(
        production_database=str(make_url(DATABASE_URL).database or ""),
        production_roots=(PROJECT_ROOT, PROJECT_ROOT / "data"),
        runtime=DockerPostgresRuntime(),
    )


def main(argv: Sequence[str] | None = None, *, dependencies: RestoreDependencies | None = None) -> int:
    try:
        args = build_parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        result = execute_isolated_restore(
            backup_root=args.backup_root,
            target_database=args.target_database,
            target_data_root=args.target_data_root,
            isolated=args.isolated,
            confirm_isolated_restore=args.confirm_isolated_restore,
            dependencies=dependencies or default_dependencies(),
        )
    except RestoreError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True))
        return 2
    except Exception as exc:  # noqa: BLE001 - unexpected details are deliberately redacted.
        print(json.dumps({"status": "blocked", "error": "isolated_restore_failed", "error_type": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
