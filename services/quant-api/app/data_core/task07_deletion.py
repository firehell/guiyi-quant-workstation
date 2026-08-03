"""Exact, recoverable Task 07 legacy-file quarantine orchestration.

This module deliberately implements quarantine only.  It never unlinks a file;
permanent deletion requires a later, separately reviewed gate.
"""

from __future__ import annotations

from hashlib import sha256
import errno
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable, Mapping

from app.data_core.canonical_store import _atomic_rename_no_replace_at
from app.data_core.contracts import BAR_FREQUENCY_VALUES
from app.data_core.task07 import canonical_digest


_KLINE_FREQUENCIES = frozenset(BAR_FREQUENCY_VALUES)
_SHA256 = frozenset("0123456789abcdef")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
_JOURNAL_FLAGS = (
    os.O_RDWR
    | os.O_APPEND
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
)
_HISTORICAL_EVIDENCE_PARTS = {"evidence", "reports", "receipts"}


class Task07DeletionError(ValueError):
    pass


def _digest(domain: str, facts: object) -> str:
    return canonical_digest({"domain": domain, "facts": facts})


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and not (set(value) - _SHA256)
    )


def _file_checksum_fd(file_fd: int) -> str:
    digest = sha256()
    os.lseek(file_fd, 0, os.SEEK_SET)
    while chunk := os.read(file_fd, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _read_all_fd(file_fd: int) -> bytes:
    chunks: list[bytes] = []
    os.lseek(file_fd, 0, os.SEEK_SET)
    while chunk := os.read(file_fd, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _file_checksum(path: Path) -> str:
    file_fd = os.open(path, _FILE_FLAGS)
    try:
        return _file_checksum_fd(file_fd)
    finally:
        os.close(file_fd)


def _path_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return path != root


def _reject_symlink_components(path: Path, root: Path) -> None:
    current = root
    if stat.S_ISLNK(os.lstat(root).st_mode):
        raise Task07DeletionError("TASK07_DELETION_SYMLINK")
    for component in path.relative_to(root).parts:
        current /= component
        if stat.S_ISLNK(os.lstat(current).st_mode):
            raise Task07DeletionError("TASK07_DELETION_SYMLINK")


def _replacement_source_checksum(receipt: Mapping[str, Any]) -> object:
    correction = receipt.get("correction_evidence")
    if isinstance(correction, Mapping):
        return correction.get("source_checksum")
    return receipt.get("source_checksum")


def _validate_replacement(receipt: Mapping[str, Any]) -> None:
    digest = receipt.get("receipt_digest")
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if (
        receipt.get("command") != "data.task07.apply"
        or receipt.get("status") != "passed"
        or not _is_sha256(digest)
        or canonical_digest(body) != digest
        or not _is_sha256(receipt.get("physical_checksum"))
        or not _is_sha256(receipt.get("manifest_digest"))
    ):
        raise Task07DeletionError("TASK07_DELETION_REPLACEMENT_RECEIPT_INVALID")


def _classify_candidate(
    asset: Mapping[str, Any],
) -> None:
    if asset.get("source_scope") == "protected_evidence_root":
        raise Task07DeletionError("TASK07_DELETION_PROTECTED")
    frequency = str(asset.get("frequency") or "")
    if frequency in _KLINE_FREQUENCIES or asset.get("data_type") in {
        "bars",
        "contract_bars_raw",
        "daily_baseline",
        "v2_canonical",
    }:
        raise Task07DeletionError("TASK07_DELETION_KLINE_PRESERVED")
    disposition = asset.get("disposition")
    if disposition != "RETIREMENT_CANDIDATE":
        raise Task07DeletionError("TASK07_DELETION_DISPOSITION_BLOCKED")
    if asset.get("provider") in {"rqdata", "local_parquet"} and asset.get(
        "data_role"
    ) == "primary":
        raise Task07DeletionError("TASK07_DELETION_CLASSIFICATION_INVALID")


def build_deletion_plan(
    *,
    assets: Iterable[Mapping[str, Any]],
    approved_roots: Iterable[Path],
    quarantine_root: Path,
    base_sha: str,
    database_revision: str,
    reference_digest: str,
    active_row_set_digest: str | None = None,
    reference_snapshot_digest: str | None = None,
    inventory_digest: str | None = None,
) -> dict[str, Any]:
    roots = tuple(Path(root) for root in approved_roots)
    if not roots or not all(root.is_absolute() and root.is_dir() for root in roots):
        raise Task07DeletionError("TASK07_DELETION_APPROVED_ROOT_INVALID")
    for root in roots:
        try:
            _reject_symlink_components(root, Path(root.anchor))
        except Task07DeletionError as exc:
            raise Task07DeletionError(
                "TASK07_DELETION_APPROVED_ROOT_SYMLINK"
            ) from exc
    quarantine = Path(quarantine_root)
    if not quarantine.is_absolute() or ".." in quarantine.parts:
        raise Task07DeletionError("TASK07_DELETION_QUARANTINE_INVALID")
    quarantine_matches = [root for root in roots if _path_under(quarantine, root)]
    if len(quarantine_matches) != 1:
        raise Task07DeletionError("TASK07_DELETION_QUARANTINE_INVALID")
    if (
        len(base_sha) != 40
        or set(base_sha) - _SHA256
        or not _is_sha256(reference_digest)
    ):
        raise Task07DeletionError("TASK07_DELETION_FACTS_INVALID")
    if not quarantine.is_dir():
        raise Task07DeletionError("TASK07_DELETION_QUARANTINE_MISSING")
    try:
        _reject_symlink_components(quarantine, quarantine_matches[0])
    except Task07DeletionError as exc:
        raise Task07DeletionError("TASK07_DELETION_QUARANTINE_SYMLINK") from exc
    quarantine_stat = os.stat(quarantine, follow_symlinks=False)
    if (
        stat.S_IMODE(quarantine_stat.st_mode) != 0o700
        or quarantine_stat.st_uid != os.getuid()
    ):
        raise Task07DeletionError("TASK07_DELETION_QUARANTINE_NOT_PRIVATE")
    active_digest = active_row_set_digest or _digest(
        "guiyi.task07.deletion-active-rows.empty.v1", []
    )
    snapshot_digest = reference_snapshot_digest or _digest(
        "guiyi.task07.deletion-reference-snapshot.v1",
        {"reference_digest": reference_digest, "active_row_set_digest": active_digest},
    )
    frozen_inventory_digest = inventory_digest or _digest(
        "guiyi.task07.deletion-test-inventory.v1",
        {"base_sha": base_sha, "reference_digest": reference_digest},
    )
    if not _is_sha256(frozen_inventory_digest):
        raise Task07DeletionError("TASK07_DELETION_INVENTORY_DIGEST_INVALID")
    files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_ids: set[int] = set()
    for asset in sorted(assets, key=lambda item: int(item["market_data_file_id"])):
        source_id = asset.get("market_data_file_id")
        if type(source_id) is not int or source_id < 1 or source_id in seen_ids:
            raise Task07DeletionError("TASK07_DELETION_ASSET_ID_INVALID")
        seen_ids.add(source_id)
        _classify_candidate(asset)
        lexical = Path(str(asset.get("file_path") or ""))
        if not lexical.is_absolute() or ".." in lexical.parts:
            raise Task07DeletionError("TASK07_DELETION_PATH_INVALID")
        lexical = lexical.absolute()
        lowered_parts = {part.lower() for part in lexical.parts}
        lowered_name = lexical.name.lower()
        if (
            lowered_parts & _HISTORICAL_EVIDENCE_PARTS
            or "report-14" in lowered_name
            or "report-15" in lowered_name
            or "report_14" in lowered_name
            or "report_15" in lowered_name
            or "receipt" in lowered_name
        ):
            raise Task07DeletionError(
                "TASK07_DELETION_HISTORICAL_EVIDENCE"
            )
        matching_roots = [root for root in roots if _path_under(lexical, root)]
        if len(matching_roots) != 1:
            raise Task07DeletionError("TASK07_DELETION_OUTSIDE_ROOT")
        root = matching_roots[0].absolute()
        _reject_symlink_components(lexical, root)
        resolved = lexical.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
        if not _path_under(resolved, resolved_root):
            raise Task07DeletionError("TASK07_DELETION_OUTSIDE_ROOT")
        if str(lexical) in seen_paths:
            raise Task07DeletionError("TASK07_DELETION_DUPLICATE_PATH")
        seen_paths.add(str(lexical))
        value = os.stat(lexical, follow_symlinks=False)
        root_stat = os.stat(root, follow_symlinks=False)
        if not stat.S_ISREG(value.st_mode):
            raise Task07DeletionError("TASK07_DELETION_NOT_REGULAR_FILE")
        checksum = _file_checksum(lexical)
        if (
            asset.get("physical_exists") is not True
            or asset.get("physical_checksum") != checksum
            or asset.get("file_size_bytes") not in {None, value.st_size}
        ):
            raise Task07DeletionError("TASK07_DELETION_FILE_DRIFT")
        files.append(
            {
                "market_data_file_id": source_id,
                "lexical_path": str(lexical),
                "resolved_path": str(resolved),
                "approved_root_lexical": str(root),
                "approved_root_resolved": str(resolved_root),
                "root_dev": root_stat.st_dev,
                "root_inode": root_stat.st_ino,
                "file_dev": value.st_dev,
                "file_inode": value.st_ino,
                "size": value.st_size,
                "mtime_ns": value.st_mtime_ns,
                "sha256": checksum,
                "disposition": asset.get("disposition"),
                "asset_classification": {
                    "provider": asset.get("provider"),
                    "data_type": asset.get("data_type"),
                    "frequency": asset.get("frequency"),
                    "data_role": asset.get("data_role"),
                    "quality_status": asset.get("quality_status"),
                    "source_scope": asset.get("source_scope"),
                    "disposition": asset.get("disposition"),
                },
                "recoverability": "atomic_quarantine_restore",
            }
        )
    facts = {
        "base_sha": base_sha,
        "database_revision": database_revision,
        "reference_digest": reference_digest,
        "active_row_set_digest": active_digest,
        "reference_snapshot_digest": snapshot_digest,
        "inventory_digest": frozen_inventory_digest,
        "approved_roots": [
            {
                "lexical": str(root.absolute()),
                "resolved": str(root.resolve(strict=True)),
                "dev": os.stat(root, follow_symlinks=False).st_dev,
                "inode": os.stat(root, follow_symlinks=False).st_ino,
            }
            for root in sorted(roots, key=str)
        ],
        "quarantine_root": str(quarantine.absolute()),
        "quarantine_root_lexical": str(quarantine.absolute()),
        "quarantine_root_resolved": str(quarantine.resolve(strict=True)),
        "quarantine_dev": quarantine_stat.st_dev,
        "quarantine_inode": quarantine_stat.st_ino,
        "files": files,
        "market_data_files_preserved": True,
        "permanent_unlink_authorized": False,
        "runtime_cutover_receipt_digest": None,
        "runtime_cutover_validated": False,
        "runtime_cutover_gate": "BLOCKED_TASK07_RUNTIME_CUTOVER_REQUIRED",
        "deletion_eligible": False,
    }
    return {
        "schema_version": 1,
        "command": "data.task07.deletion-plan",
        "status": "planned",
        **facts,
        "plan_digest": _digest("guiyi.task07.deletion-plan.v1", facts),
        "deletion_authorized": False,
    }


def _validate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    core_keys = {
        "schema_version", "command", "status", "base_sha",
        "database_revision", "reference_digest", "active_row_set_digest",
        "reference_snapshot_digest", "approved_roots", "quarantine_root",
        "inventory_digest",
        "quarantine_root_lexical", "quarantine_root_resolved",
        "quarantine_dev", "quarantine_inode", "files",
        "market_data_files_preserved", "permanent_unlink_authorized",
        "runtime_cutover_receipt_digest", "runtime_cutover_validated",
        "runtime_cutover_gate", "deletion_eligible", "plan_digest",
        "deletion_authorized",
    }
    unknown = set(plan) - core_keys
    if (
        unknown
        or plan.get("schema_version") != 1
        or plan.get("command") != "data.task07.deletion-plan"
        or plan.get("status") != "planned"
        or plan.get("market_data_files_preserved") is not True
        or plan.get("permanent_unlink_authorized") is not False
        or plan.get("deletion_authorized") is not False
        or not isinstance(plan.get("files"), list)
        or plan.get("runtime_cutover_receipt_digest") is not None
        or plan.get("runtime_cutover_validated") is not False
        or plan.get("runtime_cutover_gate")
        != "BLOCKED_TASK07_RUNTIME_CUTOVER_REQUIRED"
        or plan.get("deletion_eligible") is not False
        or not _is_sha256(plan.get("inventory_digest"))
    ):
        raise Task07DeletionError("TASK07_DELETION_PLAN_INVALID")
    excluded = {
        "schema_version",
        "command",
        "status",
        "plan_digest",
        "deletion_authorized",
    }
    facts = {key: value for key, value in plan.items() if key not in excluded}
    if plan.get("plan_digest") != _digest("guiyi.task07.deletion-plan.v1", facts):
        raise Task07DeletionError("TASK07_DELETION_PLAN_DIGEST_MISMATCH")
    for item in plan["files"]:
        if not isinstance(item, Mapping) or set(item) != {
            "market_data_file_id", "lexical_path", "resolved_path",
            "approved_root_lexical", "approved_root_resolved", "root_dev",
            "root_inode", "file_dev", "file_inode", "size", "mtime_ns",
            "sha256", "disposition", "asset_classification", "recoverability",
        }:
            raise Task07DeletionError("TASK07_DELETION_PLAN_INVALID")
        classification = item["asset_classification"]
        if not isinstance(classification, Mapping) or set(classification) != {
            "provider", "data_type", "frequency", "data_role", "quality_status",
            "source_scope", "disposition",
        }:
            raise Task07DeletionError("TASK07_DELETION_PLAN_INVALID")
        _classify_candidate(
            {
                **classification,
                "market_data_file_id": item["market_data_file_id"],
            }
        )
        if item["disposition"] != classification["disposition"]:
            raise Task07DeletionError("TASK07_DELETION_CLASSIFICATION_INVALID")
    return facts


def build_deletion_approval_packet(plan: Mapping[str, Any]) -> dict[str, Any]:
    _validate_plan(plan)
    raise Task07DeletionError("TASK07_RUNTIME_CUTOVER_GATE_REQUIRED")


def _build_unlocked_deletion_approval_packet(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_plan(plan)
    facts = {
        "plan_digest": plan["plan_digest"],
        "base_sha": plan["base_sha"],
        "database_revision": plan["database_revision"],
        "reference_digest": plan["reference_digest"],
        "active_row_set_digest": plan["active_row_set_digest"],
        "reference_snapshot_digest": plan["reference_snapshot_digest"],
        "inventory_digest": plan["inventory_digest"],
        "approved_roots": plan["approved_roots"],
        "quarantine_root": plan["quarantine_root"],
        "quarantine_root_resolved": plan["quarantine_root_resolved"],
        "quarantine_dev": plan["quarantine_dev"],
        "quarantine_inode": plan["quarantine_inode"],
        "file_manifest_digest": _digest(
            "guiyi.task07.deletion-files.v1", plan["files"]
        ),
        "file_count": len(plan["files"]),
        "permanent_unlink_authorized": False,
    }
    return {
        "schema_version": 1,
        "command": "data.task07.deletion-apply",
        "approval_scope": "exact_quarantine_only",
        "facts": facts,
        "packet_digest": _digest("guiyi.task07.deletion-approval.v1", facts),
    }


def _verify_facts(
    plan: Mapping[str, Any],
    *,
    current_base_sha: str,
    current_database_revision: str,
    current_reference_digest: str,
) -> None:
    if current_base_sha != plan.get("base_sha"):
        raise Task07DeletionError("TASK07_DELETION_BASE_SHA_DRIFT")
    if current_database_revision != plan.get("database_revision"):
        raise Task07DeletionError("TASK07_DELETION_DATABASE_REVISION_DRIFT")
    if current_reference_digest != plan.get("reference_digest"):
        raise Task07DeletionError("TASK07_DELETION_REFERENCE_DRIFT")


def _verify_unlocked_packet(
    plan: Mapping[str, Any], packet_path: Path, approval_hash: str
) -> None:
    try:
        packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Task07DeletionError("TASK07_DELETION_APPROVAL_INVALID") from exc
    expected = _build_unlocked_deletion_approval_packet(plan)
    if canonical_digest(packet) != approval_hash:
        raise Task07DeletionError("TASK07_DELETION_APPROVAL_HASH_MISMATCH")
    if packet != expected:
        raise Task07DeletionError("TASK07_DELETION_APPROVAL_FACTS_DRIFT")


def _verify_source(item: Mapping[str, Any]) -> None:
    path = Path(str(item["lexical_path"]))
    root = Path(str(item["approved_root_lexical"]))
    _reject_symlink_components(path, root)
    root_value = os.stat(root, follow_symlinks=False)
    if (
        root_value.st_dev != item.get("root_dev")
        or root_value.st_ino != item.get("root_inode")
        or str(root.resolve(strict=True)) != item.get("approved_root_resolved")
        or str(path.resolve(strict=True)) != item.get("resolved_path")
    ):
        raise Task07DeletionError("TASK07_DELETION_ROOT_DRIFT")
    value = os.stat(path, follow_symlinks=False)
    file_fd = os.open(path, _FILE_FLAGS)
    try:
        descriptor = os.fstat(file_fd)
        checksum = _file_checksum_fd(file_fd)
    finally:
        os.close(file_fd)
    if (
        value.st_dev != item.get("file_dev")
        or value.st_ino != item.get("file_inode")
        or value.st_size != item.get("size")
        or value.st_mtime_ns != item.get("mtime_ns")
        or descriptor.st_dev != value.st_dev
        or descriptor.st_ino != value.st_ino
        or checksum != item.get("sha256")
    ):
        raise Task07DeletionError("TASK07_DELETION_FILE_DRIFT")


def build_deletion_preflight(
    plan: Mapping[str, Any],
    *,
    packet_path: Path,
    approval_hash: str,
    current_base_sha: str,
    current_database_revision: str,
    current_reference_digest: str,
) -> dict[str, Any]:
    _validate_plan(plan)
    raise Task07DeletionError("TASK07_RUNTIME_CUTOVER_GATE_REQUIRED")


def _build_unlocked_deletion_preflight(
    plan: Mapping[str, Any],
    *,
    packet_path: Path,
    approval_hash: str,
    current_base_sha: str,
    current_database_revision: str,
    current_reference_digest: str,
) -> dict[str, Any]:
    _validate_plan(plan)
    _verify_facts(
        plan,
        current_base_sha=current_base_sha,
        current_database_revision=current_database_revision,
        current_reference_digest=current_reference_digest,
    )
    _verify_unlocked_packet(plan, packet_path, approval_hash)
    for item in plan["files"]:
        _verify_source(item)
    facts = {
        "plan_digest": plan["plan_digest"],
        "approval_hash": approval_hash,
        "base_sha": current_base_sha,
        "database_revision": current_database_revision,
        "reference_digest": current_reference_digest,
        "file_manifest_digest": _digest(
            "guiyi.task07.deletion-files.v1", plan["files"]
        ),
        "file_count": len(plan["files"]),
        "permanent_unlink_authorized": False,
        "readonly": True,
    }
    return {
        "schema_version": 1,
        "command": "data.task07.deletion-preflight",
        "status": "passed",
        **facts,
        "preflight_digest": _digest("guiyi.task07.deletion-preflight.v1", facts),
    }


def _validate_preflight(
    plan: Mapping[str, Any], preflight: Mapping[str, Any], approval_hash: str
) -> None:
    excluded = {
        "schema_version",
        "command",
        "status",
        "preflight_digest",
    }
    if set(preflight) != {
        "schema_version", "command", "status", "plan_digest", "approval_hash",
        "base_sha", "database_revision", "reference_digest",
        "file_manifest_digest", "file_count", "permanent_unlink_authorized",
        "readonly", "preflight_digest",
    }:
        raise Task07DeletionError("TASK07_DELETION_PREFLIGHT_DRIFT")
    facts = {key: value for key, value in preflight.items() if key not in excluded}
    if (
        preflight.get("schema_version") != 1
        or preflight.get("command") != "data.task07.deletion-preflight"
        or preflight.get("status") != "passed"
        or preflight.get("plan_digest") != plan.get("plan_digest")
        or preflight.get("approval_hash") != approval_hash
        or preflight.get("readonly") is not True
        or preflight.get("permanent_unlink_authorized") is not False
        or preflight.get("preflight_digest")
        != _digest("guiyi.task07.deletion-preflight.v1", facts)
    ):
        raise Task07DeletionError("TASK07_DELETION_PREFLIGHT_DRIFT")


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError("TASK07_DELETION_JOURNAL_SHORT_WRITE")
        offset += written


def _append_journal_fd(fd: int, entry: Mapping[str, Any]) -> None:
    payload = (
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    _write_all(fd, payload)
    os.fsync(fd)


def _open_plan_quarantine(plan: Mapping[str, Any]) -> int:
    quarantine = Path(str(plan["quarantine_root_lexical"]))
    matches = [
        item
        for item in plan["approved_roots"]
        if _path_under(quarantine, Path(str(item["lexical"])))
    ]
    if len(matches) != 1:
        raise Task07DeletionError("TASK07_DELETION_QUARANTINE_INVALID")
    root = Path(str(matches[0]["lexical"]))
    root_fd = os.open(root, _DIR_FLAGS)
    current_fd = os.dup(root_fd)
    try:
        root_value = os.fstat(root_fd)
        if (root_value.st_dev, root_value.st_ino) != (
            matches[0]["dev"],
            matches[0]["inode"],
        ):
            raise Task07DeletionError("TASK07_DELETION_ROOT_DRIFT")
        for component in quarantine.relative_to(root).parts:
            next_fd = os.open(component, _DIR_FLAGS, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        value = os.fstat(current_fd)
        if (
            value.st_dev != plan["quarantine_dev"]
            or value.st_ino != plan["quarantine_inode"]
            or stat.S_IMODE(value.st_mode) != 0o700
            or value.st_uid != os.getuid()
        ):
            raise Task07DeletionError("TASK07_DELETION_QUARANTINE_DRIFT")
        return current_fd
    except Exception:
        os.close(current_fd)
        raise
    finally:
        os.close(root_fd)


def _create_journal_fd(quarantine_fd: int, journal_name: str) -> int:
    try:
        return os.open(
            journal_name,
            _JOURNAL_FLAGS,
            0o600,
            dir_fd=quarantine_fd,
        )
    except FileExistsError as exc:
        raise Task07DeletionError(
            "TASK07_DELETION_JOURNAL_ALREADY_EXISTS"
        ) from exc


def _rename_no_replace(
    source_dir_fd: int, source_name: str, target_dir_fd: int, target_name: str
) -> None:
    try:
        _atomic_rename_no_replace_at(
            source_dir_fd, source_name, target_dir_fd, target_name
        )
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise Task07DeletionError("TASK07_DELETION_TARGET_EXISTS") from exc
        raise


def _open_parent(root: Path, source: Path) -> tuple[int, int]:
    root_fd = os.open(root, _DIR_FLAGS)
    current_fd = os.dup(root_fd)
    try:
        for component in source.parent.relative_to(root).parts:
            next_fd = os.open(component, _DIR_FLAGS, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return root_fd, current_fd
    except Exception:
        os.close(current_fd)
        os.close(root_fd)
        raise


def _verify_pinned_source(
    parent_fd: int, source_name: str, item: Mapping[str, Any]
) -> None:
    file_fd = os.open(source_name, _FILE_FLAGS, dir_fd=parent_fd)
    try:
        value = os.fstat(file_fd)
        checksum = _file_checksum_fd(file_fd)
    finally:
        os.close(file_fd)
    if (
        value.st_dev != item.get("file_dev")
        or value.st_ino != item.get("file_inode")
        or value.st_size != item.get("size")
        or value.st_mtime_ns != item.get("mtime_ns")
        or checksum != item.get("sha256")
    ):
        raise Task07DeletionError("TASK07_DELETION_FILE_DRIFT")


def _verify_planned_source_absent(
    plan: Mapping[str, Any], item: Mapping[str, Any]
) -> None:
    root = Path(str(item["approved_root_lexical"]))
    matches = [
        record
        for record in plan["approved_roots"]
        if record.get("lexical") == str(root)
        and record.get("resolved") == item.get("approved_root_resolved")
        and record.get("dev") == item.get("root_dev")
        and record.get("inode") == item.get("root_inode")
    ]
    if len(matches) != 1:
        raise Task07DeletionError("TASK07_DELETION_ROOT_DRIFT")
    try:
        root_fd, parent_fd = _open_parent(
            root, Path(str(item["lexical_path"]))
        )
    except OSError as exc:
        raise Task07DeletionError("TASK07_DELETION_ROOT_DRIFT") from exc
    try:
        root_value = os.fstat(root_fd)
        if (
            root_value.st_dev != item["root_dev"]
            or root_value.st_ino != item["root_inode"]
            or str(root.resolve(strict=True)) != item["approved_root_resolved"]
        ):
            raise Task07DeletionError("TASK07_DELETION_ROOT_DRIFT")
        name = Path(str(item["lexical_path"])).name
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise Task07DeletionError("TASK07_DELETION_SOURCE_REAPPEARED")
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def apply_deletion_plan(
    plan: Mapping[str, Any],
    *,
    packet_path: Path,
    approval_hash: str,
    preflight: Mapping[str, Any],
    current_base_sha: str,
    current_database_revision: str,
    current_reference_digest: str,
) -> dict[str, Any]:
    _validate_plan(plan)
    raise Task07DeletionError("TASK07_RUNTIME_CUTOVER_GATE_REQUIRED")


def _apply_unlocked_deletion_plan(
    plan: Mapping[str, Any],
    *,
    packet_path: Path,
    approval_hash: str,
    preflight: Mapping[str, Any],
    current_base_sha: str,
    current_database_revision: str,
    current_reference_digest: str,
) -> dict[str, Any]:
    _validate_plan(plan)
    _verify_facts(
        plan,
        current_base_sha=current_base_sha,
        current_database_revision=current_database_revision,
        current_reference_digest=current_reference_digest,
    )
    _verify_unlocked_packet(plan, packet_path, approval_hash)
    _validate_preflight(plan, preflight, approval_hash)
    for item in plan["files"]:
        _verify_source(item)
    quarantine = Path(str(plan["quarantine_root"]))
    journal = quarantine / f"{plan['plan_digest']}.jsonl"
    quarantine_fd = _open_plan_quarantine(plan)
    journal_fd: int | None = None
    try:
        journal_fd = _create_journal_fd(quarantine_fd, journal.name)
        os.fsync(quarantine_fd)
    except Exception:
        os.close(quarantine_fd)
        raise
    try:
        _append_journal_fd(
            journal_fd,
            {
                "event": "intent",
                "plan_digest": plan["plan_digest"],
                "file_count": len(plan["files"]),
                "permanent_unlink_authorized": False,
            },
        )
    except Exception as exc:
        os.close(journal_fd)
        os.close(quarantine_fd)
        raise Task07DeletionError("TASK07_DELETION_JOURNAL_FAILURE") from exc
    moved: list[dict[str, Any]] = []
    open_parents: list[tuple[int, int]] = []
    try:
        quarantine_stat = os.stat(quarantine, follow_symlinks=False)
        for item in plan["files"]:
            source = Path(str(item["lexical_path"]))
            root = Path(str(item["approved_root_lexical"]))
            if quarantine_stat.st_dev != item["file_dev"]:
                raise Task07DeletionError("TASK07_DELETION_CROSS_FILESYSTEM")
            root_fd, parent_fd = _open_parent(root, source)
            open_parents.append((root_fd, parent_fd))
            root_value = os.fstat(root_fd)
            if (root_value.st_dev, root_value.st_ino) != (
                item["root_dev"],
                item["root_inode"],
            ):
                raise Task07DeletionError("TASK07_DELETION_ROOT_DRIFT")
            current = os.stat(source.name, dir_fd=parent_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (
                item["file_dev"],
                item["file_inode"],
            ):
                raise Task07DeletionError("TASK07_DELETION_FILE_DRIFT")
            _verify_pinned_source(parent_fd, source.name, item)
            moved_item = _expected_moved_item(plan, item)
            target_name = str(moved_item["target_name"])
            _rename_no_replace(parent_fd, source.name, quarantine_fd, target_name)
            moved.append(moved_item)
            os.fsync(parent_fd)
            os.fsync(quarantine_fd)
            _append_journal_fd(journal_fd, {"event": "moved", **moved_item})
            quarantine_file_fd = os.open(
                target_name, _FILE_FLAGS, dir_fd=quarantine_fd
            )
            try:
                quarantined = os.fstat(quarantine_file_fd)
                quarantine_checksum = _file_checksum_fd(quarantine_file_fd)
            finally:
                os.close(quarantine_file_fd)
            if (
                quarantined.st_dev != item["file_dev"]
                or quarantined.st_ino != item["file_inode"]
                or quarantined.st_size != item["size"]
                or quarantine_checksum != item["sha256"]
            ):
                raise Task07DeletionError("TASK07_DELETION_QUARANTINE_DRIFT")
        _append_journal_fd(
            journal_fd,
            {
                "event": "committed",
                "plan_digest": plan["plan_digest"],
                "moved_count": len(moved),
                "permanent_unlink_authorized": False,
            },
        )
    except Exception as exc:
        if not moved and isinstance(exc, Task07DeletionError):
            raise
        compensation_failed = False
        for moved_item, (_root_fd, parent_fd) in zip(
            reversed(moved), reversed(open_parents[: len(moved)]), strict=True
        ):
            try:
                source = Path(str(moved_item["source_path"]))
                _rename_no_replace(
                    quarantine_fd,
                    str(moved_item["target_name"]),
                    parent_fd,
                    source.name,
                )
                os.fsync(parent_fd)
                os.fsync(quarantine_fd)
                try:
                    _append_journal_fd(
                        journal_fd, {"event": "compensated", **moved_item}
                    )
                except Exception:
                    pass
            except Exception as compensation_error:
                compensation_failed = True
                try:
                    _append_journal_fd(
                        journal_fd,
                        {
                            "event": "recovery_required",
                            "market_data_file_id": moved_item["market_data_file_id"],
                            "error_type": type(compensation_error).__name__,
                        },
                    )
                except Exception:
                    pass
        code = (
            "TASK07_DELETION_RECOVERY_REQUIRED"
            if compensation_failed
            else "TASK07_DELETION_APPLY_COMPENSATED"
        )
        raise Task07DeletionError(code) from exc
    finally:
        for root_fd, parent_fd in open_parents:
            os.close(parent_fd)
            os.close(root_fd)
        os.close(quarantine_fd)
        if journal_fd is not None:
            os.close(journal_fd)
    journal_checksum = _file_checksum(journal)
    facts = {
        "plan_digest": plan["plan_digest"],
        "approval_hash": approval_hash,
        "preflight_digest": preflight["preflight_digest"],
        "files": moved,
        "journal_path": str(journal),
        "journal_sha256": journal_checksum,
        "quarantined_count": len(moved),
        "deleted_row_count": 0,
        "permanent_unlink_authorized": False,
    }
    return {
        "schema_version": 1,
        "command": "data.task07.deletion-apply",
        "status": "passed",
        **facts,
        "receipt_digest": _digest("guiyi.task07.deletion-apply.v1", facts),
    }


def verify_deletion_apply(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    current_base_sha: str,
    current_database_revision: str,
    current_reference_digest: str,
) -> dict[str, Any]:
    _validate_plan(plan)
    raise Task07DeletionError("TASK07_RUNTIME_CUTOVER_GATE_REQUIRED")


def _verify_unlocked_deletion_apply(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    current_base_sha: str,
    current_database_revision: str,
    current_reference_digest: str,
) -> dict[str, Any]:
    _validate_plan(plan)
    _verify_facts(
        plan,
        current_base_sha=current_base_sha,
        current_database_revision=current_database_revision,
        current_reference_digest=current_reference_digest,
    )
    core_receipt_keys = {
        "schema_version", "command", "status", "plan_digest", "approval_hash",
        "preflight_digest", "files", "journal_path", "journal_sha256",
        "quarantined_count", "deleted_row_count", "permanent_unlink_authorized",
        "receipt_digest",
    }
    excluded = {
        "schema_version",
        "command",
        "status",
        "receipt_digest",
    }
    facts = {key: value for key, value in receipt.items() if key not in excluded}
    if (
        set(receipt) != core_receipt_keys
        or receipt.get("schema_version") != 1
        or receipt.get("command") != "data.task07.deletion-apply"
        or receipt.get("status") != "passed"
        or receipt.get("plan_digest") != plan.get("plan_digest")
        or receipt.get("permanent_unlink_authorized") is not False
        or receipt.get("deleted_row_count") != 0
        or receipt.get("receipt_digest")
        != _digest("guiyi.task07.deletion-apply.v1", facts)
    ):
        raise Task07DeletionError("TASK07_DELETION_RECEIPT_DRIFT")
    files = receipt.get("files")
    if not isinstance(files, list) or len(files) != len(plan["files"]):
        raise Task07DeletionError("TASK07_DELETION_RECEIPT_DRIFT")
    expected_files = [_expected_moved_item(plan, item) for item in plan["files"]]
    if files != expected_files:
        raise Task07DeletionError("TASK07_DELETION_RECEIPT_DRIFT")
    quarantine_fd = _open_plan_quarantine(plan)
    try:
        for planned, moved in zip(plan["files"], files, strict=True):
            _verify_planned_source_absent(plan, planned)
            file_fd = os.open(str(moved["target_name"]), _FILE_FLAGS, dir_fd=quarantine_fd)
            try:
                value = os.fstat(file_fd)
                checksum = _file_checksum_fd(file_fd)
            finally:
                os.close(file_fd)
            if (
                value.st_dev != planned["file_dev"]
                or value.st_ino != planned["file_inode"]
                or value.st_size != planned["size"]
                or checksum != planned["sha256"]
            ):
                raise Task07DeletionError("TASK07_DELETION_QUARANTINE_DRIFT")
        journal_fd = os.open(
            f"{plan['plan_digest']}.jsonl", _FILE_FLAGS, dir_fd=quarantine_fd
        )
        try:
            payload = _read_all_fd(journal_fd)
        finally:
            os.close(journal_fd)
    except OSError as exc:
        raise Task07DeletionError("TASK07_DELETION_QUARANTINE_DRIFT") from exc
    finally:
        os.close(quarantine_fd)
    journal = Path(str(plan["quarantine_root"])) / f"{plan['plan_digest']}.jsonl"
    if receipt.get("journal_path") != str(journal):
        raise Task07DeletionError("TASK07_DELETION_JOURNAL_DRIFT")
    try:
        events = [json.loads(line) for line in payload.splitlines()]
    except json.JSONDecodeError as exc:
        raise Task07DeletionError("TASK07_DELETION_JOURNAL_DRIFT") from exc
    expected_events = [
        {
            "event": "intent",
            "plan_digest": plan["plan_digest"],
            "file_count": len(plan["files"]),
            "permanent_unlink_authorized": False,
        },
        *({"event": "moved", **item} for item in expected_files),
        {
            "event": "committed",
            "plan_digest": plan["plan_digest"],
            "moved_count": len(plan["files"]),
            "permanent_unlink_authorized": False,
        },
    ]
    if (
        events != expected_events
        or sha256(payload).hexdigest() != receipt.get("journal_sha256")
    ):
        raise Task07DeletionError("TASK07_DELETION_JOURNAL_DRIFT")
    body = {
        "schema_version": 1,
        "command": "data.task07.deletion-verify",
        "status": "passed",
        "readonly": True,
        "plan_digest": plan["plan_digest"],
        "receipt_digest": receipt["receipt_digest"],
        "verified_count": len(files),
        "permanent_unlink_authorized": False,
    }
    return {**body, "verify_digest": _digest("guiyi.task07.deletion-verify.v1", body)}


def _expected_moved_item(
    plan: Mapping[str, Any], item: Mapping[str, Any]
) -> dict[str, Any]:
    source = Path(str(item["lexical_path"]))
    target_name = (
        f"{item['market_data_file_id']}-{str(item['sha256'])[:16]}-{source.name}"
    )
    return {
        "market_data_file_id": item["market_data_file_id"],
        "source_path": str(source),
        "quarantine_path": str(Path(str(plan["quarantine_root"])) / target_name),
        "target_name": target_name,
        "sha256": item["sha256"],
        "file_dev": item["file_dev"],
        "file_inode": item["file_inode"],
        "size": item["size"],
    }
