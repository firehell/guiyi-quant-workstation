#!/usr/bin/env python3
"""Hash-bound operator CLI for the frozen 21-product retirement.

Inventory and verify are read-only.  Apply remains fail-closed behind an exact
approval packet and an independently hashed shutdown receipt.  This tool never
calls RQData and never selects products outside the frozen contract.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from app.data_core.product_retirement import (
    ProductRetirementError,
    apply_retirement_packet,
    build_inventory_packet,
    externalize_database_rows,
    inventory_database,
    inventory_files,
    packet_digest,
    remove_database_row_assets,
    verify_retirement_scope,
)


REQUIRED_STOPPED_SERVICES = (
    "com.guiyi.quant-api",
    "com.guiyi.quant-worker-backtests",
    "com.guiyi.quant-worker-signals",
    "com.guiyi.quant-htdy-s610-one-day-observer",
    "com.guiyi.quant-htdy-s610-one-day-dispatcher",
    "com.guiyi.quant-htdy-s610-observer",
)
MAX_JSON_BYTES = 1024 * 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    inventory = commands.add_parser("inventory", help="build a read-only exact deletion packet")
    _add_common_roots(inventory)
    inventory.add_argument("--project-root", type=Path, required=True)
    inventory.add_argument("--runtime-root", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)

    apply = commands.add_parser("apply", help="apply one exact approved packet")
    _add_common_roots(apply)
    apply.add_argument("--project-root", type=Path, required=True)
    apply.add_argument("--runtime-root", type=Path, required=True)
    apply.add_argument("--packet", type=Path, required=True)
    apply.add_argument("--packet-sha256", required=True)
    apply.add_argument("--approval", type=Path, required=True)
    apply.add_argument("--approval-sha256", required=True)
    apply.add_argument("--shutdown-receipt", type=Path, required=True)
    apply.add_argument("--shutdown-receipt-sha256", required=True)
    apply.add_argument("--receipt", type=Path, required=True)
    apply.add_argument("--execute", action="store_true", required=True)

    verify = commands.add_parser("verify", help="verify zero residual target objects")
    _add_common_roots(verify)
    verify.add_argument("--output", type=Path, required=True)
    return parser


def _add_common_roots(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-root",
        action="append",
        required=True,
        metavar="LABEL=ABSOLUTE_PATH",
        help="repeat for bounded raw/canonical/processed roots",
    )


def parse_roots(values: Sequence[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    resolved: list[Path] = []
    for raw in values:
        if "=" not in raw:
            raise ValueError("PRODUCT_RETIREMENT_ROOT_FORMAT_INVALID")
        label, path_text = raw.split("=", maxsplit=1)
        if re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", label) is None:
            raise ValueError("PRODUCT_RETIREMENT_ROOT_LABEL_INVALID")
        if label in roots:
            raise ValueError("PRODUCT_RETIREMENT_ROOT_DUPLICATE")
        path = Path(path_text)
        if not path.is_absolute() or path == Path("/") or len(path.parts) < 3:
            raise ValueError("PRODUCT_RETIREMENT_ROOT_TOO_BROAD")
        if not path.is_dir() or path.is_symlink():
            raise ValueError("PRODUCT_RETIREMENT_ROOT_INVALID")
        current = path.resolve(strict=True)
        if any(current == prior or current.is_relative_to(prior) or prior.is_relative_to(current) for prior in resolved):
            raise ValueError("PRODUCT_RETIREMENT_ROOT_OVERLAP")
        roots[label] = path
        resolved.append(current)
    return roots


def validate_shutdown_receipt(receipt: Mapping[str, Any], *, runtime_sha: str) -> None:
    if receipt.get("schema_version") != 1 or receipt.get("status") != "passed":
        raise ValueError("PRODUCT_RETIREMENT_SHUTDOWN_RECEIPT_INVALID")
    if receipt.get("runtime_sha") != runtime_sha:
        raise ValueError("PRODUCT_RETIREMENT_SHUTDOWN_RUNTIME_SHA_MISMATCH")
    services = receipt.get("services")
    if not isinstance(services, Mapping):
        raise ValueError("PRODUCT_RETIREMENT_SHUTDOWN_SERVICES_INVALID")
    for service in REQUIRED_STOPPED_SERVICES:
        if services.get(service) != "stopped":
            raise ValueError(f"PRODUCT_RETIREMENT_SERVICE_NOT_STOPPED:{service}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        roots = parse_roots(args.data_root)
        if args.command == "inventory":
            payload = _inventory(args, roots)
        elif args.command == "apply":
            payload = _apply(args, roots)
        else:
            payload = _verify(args, roots)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        return 0 if payload.get("status") in {"ready_for_exact_approval", "applied", "passed"} else 2
    except (OSError, ValueError, ProductRetirementError) as exc:
        payload = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "calls_rqdata": False,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


def _inventory(args: argparse.Namespace, roots: Mapping[str, Path]) -> dict[str, Any]:
    project_root = _validated_git_root(args.project_root)
    runtime_root = _validated_git_root(args.runtime_root)
    _validate_packet_bundle_output(
        args.output,
        protected_roots=(*roots.values(), project_root, runtime_root),
    )
    code_sha = _git_sha(project_root)
    runtime_sha = _git_sha(runtime_root)
    from app.db.session import engine

    with engine.connect() as connection:
        revision = _database_revision(connection)
        files, file_blockers = inventory_files(roots)
        rows, database_blockers = inventory_database(connection)
    packet = build_inventory_packet(
        files=files,
        database_rows=rows,
        blockers=(*file_blockers, *database_blockers),
        code_sha=code_sha,
        runtime_sha=runtime_sha,
        database_revision=revision,
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    packet = externalize_database_rows(packet, packet_path=args.output)
    digest = packet_digest(packet)
    try:
        written_digest = write_packet_exclusive(args.output, packet)
    except Exception:
        remove_database_row_assets(args.output)
        raise
    if written_digest != digest:
        raise ValueError("PRODUCT_RETIREMENT_PACKET_SERIALIZATION_DIGEST_MISMATCH")
    return {
        "status": packet["status"],
        "packet": str(args.output.absolute()),
        "packet_sha256": digest,
        "summary": packet["summary"],
        "writes_database": False,
        "writes_data_files": False,
        "calls_rqdata": False,
    }


def _apply(args: argparse.Namespace, roots: Mapping[str, Path]) -> dict[str, Any]:
    project_root = _validated_git_root(args.project_root)
    runtime_root = _validated_git_root(args.runtime_root)
    _validate_output(args.receipt, protected_roots=(*roots.values(), project_root, runtime_root))
    packet = _read_bound_json(args.packet, args.packet_sha256, "PACKET")
    approval = _read_bound_json(args.approval, args.approval_sha256, "APPROVAL")
    shutdown = _read_bound_json(
        args.shutdown_receipt,
        args.shutdown_receipt_sha256,
        "SHUTDOWN_RECEIPT",
    )
    code_sha = _git_sha(project_root)
    runtime_sha = _git_sha(runtime_root)
    validate_shutdown_receipt(shutdown, runtime_sha=runtime_sha)
    validate_writer_services_unloaded()
    from app.db.session import engine

    with engine.connect() as connection:
        revision = _database_revision(connection)
        receipt = apply_retirement_packet(
            connection,
            packet=packet,
            expected_packet_digest=args.packet_sha256,
            approval=approval,
            roots=roots,
            code_sha=code_sha,
            runtime_sha=runtime_sha,
            database_revision=revision,
            shutdown_receipt_digest=args.shutdown_receipt_sha256,
            now=datetime.now().astimezone().isoformat(timespec="seconds"),
            packet_root=args.packet.absolute().parent,
        )
    _write_json_exclusive(args.receipt, receipt)
    return {**receipt, "receipt": str(args.receipt.absolute()), "calls_rqdata": False}


def _verify(args: argparse.Namespace, roots: Mapping[str, Path]) -> dict[str, Any]:
    _validate_output(args.output, protected_roots=tuple(roots.values()))
    from app.db.session import engine

    with engine.connect() as connection:
        payload = verify_retirement_scope(connection, roots=roots)
    _write_json_exclusive(args.output, payload)
    return {**payload, "output": str(args.output.absolute()), "calls_rqdata": False}


def _validated_git_root(path: Path) -> Path:
    root = path.absolute()
    if not root.is_dir() or root.is_symlink() or not (root / ".git").exists():
        raise ValueError("PRODUCT_RETIREMENT_GIT_ROOT_INVALID")
    return root.resolve(strict=True)


def _git_sha(root: Path) -> str:
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise ValueError("PRODUCT_RETIREMENT_GIT_WORKTREE_DIRTY")
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("PRODUCT_RETIREMENT_GIT_SHA_INVALID")
    return value


def validate_writer_services_unloaded() -> None:
    domain = f"gui/{os.getuid()}"
    for service in REQUIRED_STOPPED_SERVICES:
        result = subprocess.run(
            ["launchctl", "print", f"{domain}/{service}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            raise ValueError(f"PRODUCT_RETIREMENT_SERVICE_STILL_LOADED:{service}")


def _database_revision(connection) -> str:
    rows = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if len(rows) != 1 or not str(rows[0]).strip():
        raise ValueError("PRODUCT_RETIREMENT_DATABASE_REVISION_INVALID")
    return str(rows[0]).strip()


def _validate_output(path: Path, *, protected_roots: Sequence[Path]) -> None:
    absolute = path.absolute()
    parent = absolute.parent
    if not parent.is_dir() or parent.is_symlink() or absolute.exists() or absolute.is_symlink():
        raise ValueError("PRODUCT_RETIREMENT_OUTPUT_INVALID")
    resolved_parent = parent.resolve(strict=True)
    for protected in protected_roots:
        resolved = protected.absolute().resolve(strict=True)
        if resolved_parent == resolved or resolved_parent.is_relative_to(resolved) or resolved.is_relative_to(resolved_parent):
            raise ValueError("PRODUCT_RETIREMENT_OUTPUT_OVERLAPS_PROTECTED_ROOT")


def _validate_packet_bundle_output(
    path: Path,
    *,
    protected_roots: Sequence[Path],
) -> None:
    _validate_output(path, protected_roots=protected_roots)
    assets_root = path.absolute().parent / f"{path.name}.assets"
    if assets_root.exists() or assets_root.is_symlink():
        raise ValueError("PRODUCT_RETIREMENT_SHARD_ROOT_COLLISION")


def _read_bound_json(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError(f"PRODUCT_RETIREMENT_{label}_SHA256_INVALID")
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"PRODUCT_RETIREMENT_{label}_FILE_INVALID")
    payload_bytes = path.read_bytes()
    if sha256(payload_bytes).hexdigest() != expected_sha256:
        raise ValueError(f"PRODUCT_RETIREMENT_{label}_FILE_DIGEST_MISMATCH")
    payload = json.loads(payload_bytes)
    if not isinstance(payload, dict):
        raise ValueError(f"PRODUCT_RETIREMENT_{label}_JSON_INVALID")
    return payload


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()


def write_packet_exclusive(path: Path, packet: Mapping[str, Any]) -> str:
    data = json.dumps(
        packet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
    return sha256(data).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
