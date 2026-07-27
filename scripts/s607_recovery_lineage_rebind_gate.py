#!/usr/bin/env python3
"""Create one read-only, create-only S6-07 recovery lineage receipt."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
CORE_ROOT = PROJECT_ROOT / "packages" / "quant-core"
for root in (API_ROOT, CORE_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from app.services.s607_recovery_lineage_rebind import (  # noqa: E402
    RECEIPT_FILENAME,
    build_recovery_lineage_rebind_receipt,
    collect_database_state_read_only,
    collect_tracked_recovery_evidence,
    load_recovery_lineage_rebind_identity,
    sha256_file,
    write_recovery_lineage_receipt_create_only,
)


RECOVERY_RECORD_COMMIT = "97b50a2b121858ca52d6a5cb911b67578a75d69f"
FINAL_STEP4_COMMIT = "f63b3636539435ac9c6849e2dcf478800adf44e9"
ALLOWED_SOURCE_BRANCHES = {
    "main",
    "codex/v1-htdy-s608-real-acceptance",
}


def collect_source_identity(source_root: Path) -> dict[str, Any]:
    root = source_root.resolve(strict=True)

    def git(*arguments: str) -> str:
        result = subprocess.run(
            ("git", *arguments),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()

    branch = git("branch", "--show-current")
    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    tracked = git(
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    if branch not in ALLOWED_SOURCE_BRANCHES or tracked:
        raise RuntimeError("source_identity_invalid")
    for ancestor in (RECOVERY_RECORD_COMMIT, FINAL_STEP4_COMMIT):
        result = subprocess.run(
            ("git", "merge-base", "--is-ancestor", ancestor, commit),
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError("source_lineage_invalid")
    return {
        "root": str(root),
        "commit": commit,
        "tree": tree,
        "tracked_clean": True,
    }


def prepare_lineage_rebind(
    *,
    source_root: Path,
    runtime_env: Path,
    receipt_out: Path,
    confirmed: bool,
    now: Callable[[], datetime] | None = None,
    source_probe: Callable[[Path], Mapping[str, Any]] | None = None,
    evidence_probe: Callable[[Path], Mapping[str, Any]] | None = None,
    environment_probe: Callable[[Path], Any] | None = None,
    database_probe: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if not confirmed:
        raise RuntimeError("confirmation_required")
    source_root = source_root.resolve(strict=True)
    output = receipt_out.resolve(strict=False)
    relative = output.relative_to(source_root)
    expected_parent = Path(
        "data/reports/jm_live_signal_event_s6_08/htdy_schema_v3"
    )
    if (
        output.name != RECEIPT_FILENAME
        or relative.parent.parent != expected_parent
        or re.fullmatch(
            r"\d{8}-[0-9a-f]{12}",
            relative.parent.name,
        )
        is None
        or output.is_symlink()
    ):
        raise RuntimeError("receipt_output_scope_invalid")
    source_probe = source_probe or collect_source_identity
    evidence_probe = evidence_probe or collect_tracked_recovery_evidence
    if environment_probe is None:
        from jm_live_signal_event_deployment_gate import (
            probe_runtime_environment,
        )

        environment_probe = probe_runtime_environment
    database_probe = database_probe or collect_database_state_read_only
    created_at = (now or (lambda: datetime.now(UTC)))()
    environment = environment_probe(runtime_env)
    database_url = str(getattr(environment, "database_url", "") or "")
    if not database_url:
        raise RuntimeError("runtime_environment_invalid")
    source = dict(source_probe(source_root))
    evidence = dict(evidence_probe(source_root))
    database_state = dict(database_probe(database_url))
    receipt = build_recovery_lineage_rebind_receipt(
        source=source,
        tracked_evidence=evidence,
        current_database_state=database_state,
        created_at=created_at,
    )
    write_recovery_lineage_receipt_create_only(output, receipt)
    load_recovery_lineage_rebind_identity(
        output,
        expected_sha256=sha256_file(output),
    )
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the approved read-only S6-07 recovery lineage receipt."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--runtime-env", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    parser.add_argument(
        "--confirm-read-only-lineage-rebind",
        action="store_true",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = prepare_lineage_rebind(
            source_root=args.source_root,
            runtime_env=args.runtime_env,
            receipt_out=args.receipt_out,
            confirmed=args.confirm_read_only_lineage_rebind,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    output = args.receipt_out.resolve(strict=True)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "gate": receipt["gate"],
                "receipt_path": str(output),
                "receipt_sha256": sha256_file(output),
                "receipt_hash": receipt["receipt_hash"],
                "database_write_performed": False,
                "migration_performed": False,
                "approval_r_rerun": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
