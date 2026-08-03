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
from app.data_core.task07 import canonical_digest


_DIRECT = {"1m", "1d", "1w"}
_DERIVED = {"5m", "15m", "30m", "60m"}
_SHA256 = frozenset("0123456789abcdef")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
_JOURNAL_FLAGS = (
    os.O_WRONLY
    | os.O_APPEND
    | os.O_CREAT
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
    replacement: Mapping[str, Any] | None,
    verified_replacement_ids: set[int],
) -> None:
    if asset.get("source_scope") == "protected_evidence_root":
        raise Task07DeletionError("TASK07_DELETION_PROTECTED")
    frequency = str(asset.get("frequency") or "")
    if frequency in _DERIVED:
        raise Task07DeletionError("TASK07_DELETION_COLD_DERIVED")
    disposition = asset.get("disposition")
    is_direct_kline = (
        asset.get("provider") == "rqdata"
        and asset.get("data_type")
        in {"bars", "contract_bars_raw", "daily_baseline", "v2_canonical"}
        and frequency in _DIRECT
    )
    if is_direct_kline:
        source_id = asset.get("market_data_file_id")
        if replacement is None or source_id not in verified_replacement_ids:
            raise Task07DeletionError("TASK07_DELETION_REPLACEMENT_REQUIRED")
        _validate_replacement(replacement)
        if (
            replacement.get("market_data_file_id") != source_id
            or _replacement_source_checksum(replacement)
            != asset.get("physical_checksum")
        ):
            raise Task07DeletionError("TASK07_DELETION_REPLACEMENT_DRIFT")
        return
    if disposition != "RETIREMENT_CANDIDATE":
        raise Task07DeletionError("TASK07_DELETION_DISPOSITION_BLOCKED")


def build_deletion_plan(
    *,
    assets: Iterable[Mapping[str, Any]],
    approved_roots: Iterable[Path],
    quarantine_root: Path,
    base_sha: str,
    database_revision: str,
    reference_digest: str,
    canonical_replacements: Iterable[Mapping[str, Any]],
    verified_replacement_ids: set[int] | None = None,
) -> dict[str, Any]:
    roots = tuple(Path(root) for root in approved_roots)
    if not roots or not all(root.is_absolute() and root.is_dir() for root in roots):
        raise Task07DeletionError("TASK07_DELETION_APPROVED_ROOT_INVALID")
    if any(root.is_symlink() for root in roots):
        raise Task07DeletionError("TASK07_DELETION_APPROVED_ROOT_SYMLINK")
    quarantine = Path(quarantine_root)
    if not quarantine.is_absolute() or ".." in quarantine.parts:
        raise Task07DeletionError("TASK07_DELETION_QUARANTINE_INVALID")
    quarantine_matches = [root for root in roots if _path_under(quarantine, root)]
    if len(quarantine_matches) != 1:
        raise Task07DeletionError("TASK07_DELETION_QUARANTINE_INVALID")
    if len(base_sha) != 40 or not _is_sha256(reference_digest):
        raise Task07DeletionError("TASK07_DELETION_FACTS_INVALID")
    replacements = {
        int(item["market_data_file_id"]): dict(item)
        for item in canonical_replacements
        if type(item.get("market_data_file_id")) is int
    }
    verified = set(verified_replacement_ids or ())
    files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_ids: set[int] = set()
    for asset in sorted(assets, key=lambda item: int(item["market_data_file_id"])):
        source_id = asset.get("market_data_file_id")
        if type(source_id) is not int or source_id < 1 or source_id in seen_ids:
            raise Task07DeletionError("TASK07_DELETION_ASSET_ID_INVALID")
        seen_ids.add(source_id)
        _classify_candidate(asset, replacements.get(source_id), verified)
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
        replacement = replacements.get(source_id)
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
                "canonical_replacement_receipt_digest": (
                    replacement.get("receipt_digest") if replacement else None
                ),
                "canonical_replacement_receipt": (
                    dict(replacement) if replacement else None
                ),
                "recoverability": "atomic_quarantine_restore",
            }
        )
    facts = {
        "base_sha": base_sha,
        "database_revision": database_revision,
        "reference_digest": reference_digest,
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
        "files": files,
        "market_data_files_preserved": True,
        "permanent_unlink_authorized": False,
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
    if (
        plan.get("schema_version") != 1
        or plan.get("command") != "data.task07.deletion-plan"
        or plan.get("status") != "planned"
        or plan.get("market_data_files_preserved") is not True
        or plan.get("permanent_unlink_authorized") is not False
        or plan.get("deletion_authorized") is not False
        or not isinstance(plan.get("files"), list)
    ):
        raise Task07DeletionError("TASK07_DELETION_PLAN_INVALID")
    excluded = {
        "schema_version",
        "command",
        "status",
        "plan_digest",
        "deletion_authorized",
        "readonly",
        "effects",
        "approval_packet",
        "approval_packet_hash",
    }
    facts = {key: value for key, value in plan.items() if key not in excluded}
    if plan.get("plan_digest") != _digest("guiyi.task07.deletion-plan.v1", facts):
        raise Task07DeletionError("TASK07_DELETION_PLAN_DIGEST_MISMATCH")
    return facts


def build_deletion_approval_packet(plan: Mapping[str, Any]) -> dict[str, Any]:
    _validate_plan(plan)
    facts = {
        "plan_digest": plan["plan_digest"],
        "base_sha": plan["base_sha"],
        "database_revision": plan["database_revision"],
        "reference_digest": plan["reference_digest"],
        "approved_roots": plan["approved_roots"],
        "quarantine_root": plan["quarantine_root"],
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


def _verify_packet(
    plan: Mapping[str, Any], packet_path: Path, approval_hash: str
) -> None:
    try:
        packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Task07DeletionError("TASK07_DELETION_APPROVAL_INVALID") from exc
    expected = build_deletion_approval_packet(plan)
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
    _verify_facts(
        plan,
        current_base_sha=current_base_sha,
        current_database_revision=current_database_revision,
        current_reference_digest=current_reference_digest,
    )
    _verify_packet(plan, packet_path, approval_hash)
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
        "effects",
    }
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


def _ensure_private_quarantine(path: Path) -> None:
    parent = path.parent
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise Task07DeletionError("TASK07_DELETION_QUARANTINE_INVALID")
    else:
        os.mkdir(path, 0o700)
        parent_fd = os.open(parent, _DIR_FLAGS)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    value = os.stat(path, follow_symlinks=False)
    if stat.S_IMODE(value.st_mode) != 0o700 or value.st_uid != os.getuid():
        raise Task07DeletionError("TASK07_DELETION_QUARANTINE_NOT_PRIVATE")


def _append_journal(path: Path, entry: Mapping[str, Any]) -> None:
    payload = (
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    fd = os.open(path, _JOURNAL_FLAGS, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    directory_fd = os.open(path.parent, _DIR_FLAGS)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


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
    _verify_facts(
        plan,
        current_base_sha=current_base_sha,
        current_database_revision=current_database_revision,
        current_reference_digest=current_reference_digest,
    )
    _verify_packet(plan, packet_path, approval_hash)
    _validate_preflight(plan, preflight, approval_hash)
    for item in plan["files"]:
        _verify_source(item)
    quarantine = Path(str(plan["quarantine_root"]))
    _ensure_private_quarantine(quarantine)
    journal = quarantine / f"{plan['plan_digest']}.jsonl"
    if journal.exists() or journal.is_symlink():
        raise Task07DeletionError("TASK07_DELETION_JOURNAL_ALREADY_EXISTS")
    _append_journal(
        journal,
        {
            "event": "intent",
            "plan_digest": plan["plan_digest"],
            "file_count": len(plan["files"]),
            "permanent_unlink_authorized": False,
        },
    )
    quarantine_fd = os.open(quarantine, _DIR_FLAGS)
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
            target_name = (
                f"{item['market_data_file_id']}-{item['sha256'][:16]}-"
                f"{source.name}"
            )
            moved_item = {
                "market_data_file_id": item["market_data_file_id"],
                "source_path": str(source),
                "quarantine_path": str(quarantine / target_name),
                "target_name": target_name,
                "sha256": item["sha256"],
                "file_dev": item["file_dev"],
                "file_inode": item["file_inode"],
                "size": item["size"],
            }
            _rename_no_replace(parent_fd, source.name, quarantine_fd, target_name)
            moved.append(moved_item)
            os.fsync(parent_fd)
            os.fsync(quarantine_fd)
            _append_journal(journal, {"event": "moved", **moved_item})
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
        _append_journal(
            journal,
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
                _append_journal(
                    journal, {"event": "compensated", **moved_item}
                )
            except Exception as compensation_error:
                compensation_failed = True
                _append_journal(
                    journal,
                    {
                        "event": "recovery_required",
                        "market_data_file_id": moved_item["market_data_file_id"],
                        "error_type": type(compensation_error).__name__,
                    },
                )
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
    verified_replacement_ids: set[int] | None = None,
) -> dict[str, Any]:
    _validate_plan(plan)
    _verify_facts(
        plan,
        current_base_sha=current_base_sha,
        current_database_revision=current_database_revision,
        current_reference_digest=current_reference_digest,
    )
    excluded = {
        "schema_version",
        "command",
        "status",
        "receipt_digest",
        "effects",
    }
    facts = {key: value for key, value in receipt.items() if key not in excluded}
    if (
        receipt.get("schema_version") != 1
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
    verified_ids = set(verified_replacement_ids or ())
    for planned, moved in zip(plan["files"], files, strict=True):
        source = Path(str(moved["source_path"]))
        quarantine = Path(str(moved["quarantine_path"]))
        if source.exists() or source.is_symlink():
            raise Task07DeletionError("TASK07_DELETION_SOURCE_REAPPEARED")
        if quarantine.is_symlink() or not quarantine.is_file():
            raise Task07DeletionError("TASK07_DELETION_QUARANTINE_DRIFT")
        value = os.stat(quarantine, follow_symlinks=False)
        if (
            value.st_dev != planned["file_dev"]
            or value.st_ino != planned["file_inode"]
            or value.st_size != planned["size"]
            or _file_checksum(quarantine) != planned["sha256"]
        ):
            raise Task07DeletionError("TASK07_DELETION_QUARANTINE_DRIFT")
        if (
            planned.get("canonical_replacement_receipt_digest") is not None
            and planned["market_data_file_id"] not in verified_ids
        ):
            raise Task07DeletionError("TASK07_DELETION_REPLACEMENT_VERIFY_REQUIRED")
    journal = Path(str(receipt["journal_path"]))
    if journal.is_symlink() or _file_checksum(journal) != receipt.get("journal_sha256"):
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
