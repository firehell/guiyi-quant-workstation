from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from scripts.backup.core import BackupDependencies, BackupError, default_dependencies, execute_backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a fail-closed local Guiyi V1 backup.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--database-only", action="store_true")
    modes.add_argument("--data-only", action="store_true")
    modes.add_argument("--full", action="store_true")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--backup-id")
    parser.add_argument("--retention-class", choices=("daily", "weekly", "monthly", "milestone"), default="daily")
    parser.add_argument("--include-raw", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Create the backup; omitted means dry-run.")
    parser.add_argument("--pg-tool-mode", choices=("auto", "host", "docker"), default="auto")
    parser.add_argument("--postgres-container", default="guiyi-postgres")
    return parser


def main(argv: Sequence[str] | None = None, *, dependencies: BackupDependencies | None = None) -> int:
    try:
        args = build_parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0)
    mode = "database-only" if args.database_only else "data-only" if args.data_only else "full"
    try:
        result = execute_backup(
            mode=mode,
            source_root=args.source_root,
            output_root=args.output_root,
            backup_id=args.backup_id,
            retention_class=args.retention_class,
            include_raw=args.include_raw,
            execute=args.execute,
            tool_mode=args.pg_tool_mode,
            postgres_container=args.postgres_container,
            dependencies=dependencies or default_dependencies(),
        )
    except BackupError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:  # noqa: BLE001 - unexpected details are intentionally redacted.
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__, "error": "backup_failed"}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
