from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import ctypes
from dataclasses import dataclass
from datetime import UTC, datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import sys
from typing import Any, Protocol


SCHEMA_VERSION = "guiyi_local_backup_v1"
REPORT14_MD5 = "ae807ef77f7d9a4ce3067996558b57e8"
REPORT14_TRADES = 155
REPORT14_ORDERS = 239
RETENTION_CLASSES = {"daily", "weekly", "monthly", "milestone"}
MODES = {"database-only", "data-only", "full"}

REQUIRED_DATA_SPECS: tuple[tuple[str, str], ...] = (
    ("canonical_parquet", "data/parquet/canonical"),
    ("manifests", "data/manifests"),
    ("processed_provenance", "data/processed"),
    ("versioned_reports", "data/reports"),
    ("data_profiles", "configs/data_profiles"),
    ("oos_configs", "configs/oos"),
    ("data_universe", "data/universe"),
    ("env_template", ".env.example"),
)
OPTIONAL_DATA_SPECS: tuple[tuple[str, str], ...] = (
    ("env_templates", "configs/env"),
    ("launchd_templates", "deploy/launchd"),
)
EXCLUDED_CATEGORIES = (
    ".env",
    "runtime project.env",
    "redis",
    "logs",
    "cache",
    "data/parquet/market",
    "worktrees",
    "virtualenv",
    "runtime checkout",
)


class BackupError(RuntimeError):
    """A stable, redacted fail-closed backup error."""


@dataclass(frozen=True)
class DatabaseEvidence:
    identity: dict[str, Any]
    alembic_revision: str
    table_counts: dict[str, int]
    report14: dict[str, Any]
    active_profile_bindings: list[dict[str, Any]]
    tool: dict[str, Any]


class DatabaseProvider(Protocol):
    def create_dump(self, destination: Path, *, tool_mode: str, container: str) -> DatabaseEvidence: ...


@dataclass(frozen=True)
class BackupDependencies:
    now: Callable[[], datetime]
    token_hex: Callable[[int], str]
    git_commit: Callable[[Path], str]
    git_tree_state_hash: Callable[[Path], str]
    device_id: Callable[[Path], int]
    mount_point: Callable[[Path], Path]
    available_bytes: Callable[[Path], int]
    database_provider: DatabaseProvider | None


@dataclass(frozen=True)
class _SourceFile:
    category: str
    relative_path: str
    source: Path
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _PathIdentity:
    device: int
    inode: int


def default_dependencies() -> BackupDependencies:
    return BackupDependencies(
        now=lambda: datetime.now(UTC),
        token_hex=secrets.token_hex,
        git_commit=_git_commit,
        git_tree_state_hash=_git_tree_state_hash,
        device_id=lambda path: path.stat().st_dev,
        mount_point=_mount_point,
        available_bytes=lambda path: shutil.disk_usage(path).free,
        database_provider=PostgresDumpProvider(),
    )


def execute_backup(
    *,
    mode: str,
    source_root: Path,
    output_root: Path,
    backup_id: str | None,
    retention_class: str,
    include_raw: bool,
    execute: bool,
    tool_mode: str,
    postgres_container: str,
    same_device_snapshot: bool = False,
    dependencies: BackupDependencies | None = None,
) -> dict[str, Any]:
    deps = dependencies or default_dependencies()
    source = source_root.expanduser().resolve(strict=False)
    output = output_root.expanduser().resolve(strict=False)
    _validate_request(
        mode=mode,
        source_root=source,
        output_root=output,
        retention_class=retention_class,
        include_raw=include_raw,
        tool_mode=tool_mode,
        same_device_snapshot=same_device_snapshot,
        dependencies=deps,
    )
    if backup_id is not None:
        _validate_backup_id(backup_id)
    source_files = _collect_source_files(source, include_raw=include_raw) if mode in {"data-only", "full"} else []
    estimated_bytes = sum(item.size for item in source_files)
    if deps.available_bytes(output) < int(estimated_bytes * 1.1):
        raise BackupError("insufficient_output_capacity")

    current = _utc(deps.now())
    if not execute:
        planned_id = backup_id or f"guiyi-v1-{current:%Y%m%dT%H%M%SZ}-dryrun-{deps.token_hex(4)}"
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "dry-run",
            "mode": mode,
            "backup_id": planned_id,
            "source_file_count": len(source_files),
            "estimated_source_bytes": estimated_bytes,
            "would_write": False,
            "would_connect_database": False,
            "production_backup_executed": False,
            "storage_scope": (
                "same_device_snapshot"
                if same_device_snapshot
                else "independent_device_backup"
            ),
            "disaster_recovery_ready": not same_device_snapshot,
        }

    commit = deps.git_commit(source)
    identifier = backup_id or f"guiyi-v1-{current:%Y%m%dT%H%M%SZ}-{commit[:8]}-{deps.token_hex(4)}"
    _validate_backup_id(identifier)
    final_dir = output / identifier
    staging = output / f".{identifier}.partial-{os.getpid()}-{deps.token_hex(3)}"
    lock_fd, lock_path = _claim_backup_id(output, identifier)
    staging_identity: _PathIdentity | None = None
    try:
        if _path_exists(final_dir):
            raise BackupError("backup_already_exists")
        if _path_exists(staging):
            raise BackupError("backup_staging_already_exists")
        staging.mkdir(mode=0o700)
        staging_identity = _path_identity(staging)
        created_at = current.isoformat()
        database_manifest = _database_not_included()
        database_evidence: DatabaseEvidence | None = None
        if mode in {"database-only", "full"}:
            if deps.database_provider is None:
                raise BackupError("database_provider_unavailable")
            dump_path = staging / "database/guiyi_quant.dump"
            database_evidence = deps.database_provider.create_dump(
                dump_path,
                tool_mode=tool_mode,
                container=postgres_container,
            )
            _verify_report14(database_evidence.report14)
            database_manifest = _database_manifest(database_evidence, dump_path, staging)

        inventory_rows: list[dict[str, Any]] = []
        if source_files:
            inventory_rows = _copy_source_files(source, staging, source_files)
            _verify_source_snapshot(source, source_files, include_raw=include_raw)
        inventory_path = staging / "inventories/files.jsonl"
        inventory_path.parent.mkdir(parents=True, exist_ok=True)
        inventory_bytes = b"".join(
            (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            for row in inventory_rows
        )
        inventory_path.write_bytes(inventory_bytes)
        if mode == "full" and database_evidence is not None:
            active_profile_bindings = _verify_active_profile_bindings(
                source,
                database_evidence.active_profile_bindings,
                {row["relative_path"]: row for row in inventory_rows},
            )
            database_manifest["active_profile_bindings"] = active_profile_bindings
            database_manifest["active_profile_binding_count"] = len(active_profile_bindings)
            database_manifest["active_profile_file_count"] = len(
                {str(row["relative_path"]) for row in active_profile_bindings}
            )

        categories = _category_summary(inventory_rows)
        included_categories = set(categories)
        excluded_categories = set(EXCLUDED_CATEGORIES)
        known_data_categories = {
            *(category for category, _relative in REQUIRED_DATA_SPECS),
            *(category for category, _relative in OPTIONAL_DATA_SPECS),
            "raw",
        }
        excluded_categories.update(known_data_categories.difference(included_categories))
        if database_manifest["included"]:
            included_categories.add("database")
        else:
            excluded_categories.add("database")
        if not include_raw:
            excluded_categories.add("data/raw")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "backup_id": identifier,
            "status": "completed",
            "mode": mode,
            "retention_class": retention_class,
            "created_at": created_at,
            "completed_at": _utc(deps.now()).isoformat(),
            "source": {
                "root": str(source),
                "git_commit": commit,
                "git_tree_state_sha256": deps.git_tree_state_hash(source),
            },
            "database": database_manifest,
            "categories": categories,
            "inventory": {
                "path": "inventories/files.jsonl",
                "file_count": len(inventory_rows),
                "total_size": sum(int(row["size"]) for row in inventory_rows),
                "sha256": _sha256_bytes(inventory_bytes),
            },
            "included_categories": sorted(included_categories),
            "excluded_categories": sorted(excluded_categories),
            "retention_policy": {
                "daily": 7,
                "weekly": 4,
                "monthly": 12,
                "milestone": "indefinite",
                "automatic_deletion": False,
            },
            "boundaries": {
                "secrets_included": False,
                "redis_included": False,
                "production_restore_authorized": False,
                "profile_binding_modified": False,
                "canonical_source_modified": False,
                "storage_scope": (
                    "same_device_snapshot"
                    if same_device_snapshot
                    else "independent_device_backup"
                ),
                "same_device_snapshot": same_device_snapshot,
                "independent_device_backup": not same_device_snapshot,
                "disaster_recovery_ready": not same_device_snapshot,
            },
        }
        manifest_path = staging / "backup_manifest.json"
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
        manifest_path.write_bytes(manifest_bytes)
        (staging / "backup_manifest.sha256").write_text(_sha256_bytes(manifest_bytes) + "\n", encoding="utf-8")
        _verify_staged_backup(staging, manifest)
        _make_read_only(staging)
        if _path_exists(final_dir):
            raise BackupError("backup_already_exists")
        try:
            _rename_no_replace(staging, final_dir)
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise BackupError("backup_already_exists") from exc
            raise
        staging_identity = None
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "completed",
            "mode": mode,
            "backup_id": identifier,
            "backup_path": str(final_dir),
            "production_backup_executed": True,
        }
    except Exception:
        if staging_identity is not None:
            _remove_owned_staging(staging, staging_identity)
        raise
    finally:
        _release_backup_id(lock_fd, lock_path)


def _validate_request(
    *,
    mode: str,
    source_root: Path,
    output_root: Path,
    retention_class: str,
    include_raw: bool,
    tool_mode: str,
    same_device_snapshot: bool,
    dependencies: BackupDependencies,
) -> None:
    if mode not in MODES:
        raise BackupError("backup_mode_invalid")
    if retention_class not in RETENTION_CLASSES:
        raise BackupError("retention_class_invalid")
    if tool_mode not in {"auto", "host", "docker"}:
        raise BackupError("pg_tool_mode_invalid")
    if include_raw and mode == "database-only":
        raise BackupError("include_raw_requires_data_mode")
    if same_device_snapshot and (
        mode != "full"
        or retention_class != "milestone"
        or include_raw
    ):
        raise BackupError(
            "same_device_snapshot_requires_full_milestone_without_raw"
        )
    if not source_root.is_dir():
        raise BackupError("source_root_unavailable")
    if not output_root.is_dir():
        raise BackupError("output_root_unavailable")
    if _paths_overlap(source_root, output_root):
        raise BackupError("source_output_roots_overlap")
    mount = dependencies.mount_point(output_root)
    if not mount.exists():
        raise BackupError("output_mount_unavailable")
    if mount.resolve(strict=False) == Path(mount.anchor):
        raise BackupError("output_mount_not_external")
    if (
        dependencies.device_id(source_root)
        == dependencies.device_id(output_root)
        and not same_device_snapshot
    ):
        raise BackupError("output_device_must_differ")


def _collect_source_files(source_root: Path, *, include_raw: bool) -> list[_SourceFile]:
    specs = list(REQUIRED_DATA_SPECS)
    for category, relative in REQUIRED_DATA_SPECS:
        if not (source_root / relative).exists():
            raise BackupError(f"required_source_missing:{category}")
    specs.extend((category, relative) for category, relative in OPTIONAL_DATA_SPECS if (source_root / relative).exists())
    if include_raw:
        raw = source_root / "data/raw"
        if not raw.is_dir():
            raise BackupError("required_source_missing:raw")
        specs.append(("raw", "data/raw"))
    result: list[_SourceFile] = []
    seen: set[str] = set()
    for category, relative in specs:
        target = source_root / relative
        paths = [target] if target.is_file() or target.is_symlink() else sorted(target.rglob("*"))
        for path in paths:
            if path.is_dir() and not path.is_symlink():
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise BackupError(f"source_entry_not_regular:{path.relative_to(source_root)}")
            relative_path = path.relative_to(source_root).as_posix()
            if relative_path in seen:
                continue
            seen.add(relative_path)
            result.append(
                _SourceFile(
                    category=category,
                    relative_path=relative_path,
                    source=path,
                    size=info.st_size,
                    mtime_ns=info.st_mtime_ns,
                )
            )
    return sorted(result, key=lambda item: item.relative_path)


def _copy_source_files(source_root: Path, staging: Path, source_files: Sequence[_SourceFile]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in source_files:
        before = item.source.lstat()
        if (before.st_size, before.st_mtime_ns) != (item.size, item.mtime_ns) or not stat.S_ISREG(before.st_mode):
            raise BackupError(f"source_changed_during_backup:{item.relative_path}")
        destination = staging / "files" / item.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.source, destination)
        after = item.source.lstat()
        if (after.st_size, after.st_mtime_ns) != (item.size, item.mtime_ns):
            raise BackupError(f"source_changed_during_backup:{item.relative_path}")
        source_sha = _sha256_file(item.source)
        destination_sha = _sha256_file(destination)
        if source_sha != destination_sha:
            raise BackupError(f"copied_file_checksum_mismatch:{item.relative_path}")
        rows.append(
            {
                "category": item.category,
                "relative_path": item.relative_path,
                "size": item.size,
                "mtime_ns": item.mtime_ns,
                "sha256": destination_sha,
            }
        )
    return rows


def _verify_source_snapshot(source_root: Path, expected: Sequence[_SourceFile], *, include_raw: bool) -> None:
    current = _collect_source_files(source_root, include_raw=include_raw)
    expected_state = [(item.relative_path, item.size, item.mtime_ns) for item in expected]
    current_state = [(item.relative_path, item.size, item.mtime_ns) for item in current]
    if current_state != expected_state:
        raise BackupError("source_file_set_changed_during_backup")


def _verify_active_profile_bindings(
    source_root: Path,
    bindings: Sequence[Mapping[str, Any]],
    inventory_by_path: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not bindings:
        raise BackupError("active_profile_bindings_missing")
    verified: list[dict[str, Any]] = []
    for binding in bindings:
        binding_id = binding.get("binding_id")
        market_data_file_id = binding.get("market_data_file_id")
        raw_path = binding.get("file_path")
        profile_database_id = binding.get("profile_database_id")
        raw_config_path = binding.get("profile_config_path")
        identity_fields = ("profile_id", "instrument_symbol", "contract_code", "period", "data_version")
        if (
            binding_id is None
            or market_data_file_id is None
            or profile_database_id is None
            or not raw_path
            or not raw_config_path
            or any(not binding.get(field) for field in identity_fields)
        ):
            raise BackupError("active_profile_binding_unresolved")
        relative = _source_relative_path(source_root, str(raw_path), "active_profile_file_outside_source_root")
        inventory = inventory_by_path.get(relative)
        if inventory is None:
            raise BackupError(f"active_profile_file_not_backed_up:{relative}")
        if inventory.get("category") != "canonical_parquet":
            raise BackupError(f"active_profile_file_not_canonical:{relative}")
        expected_checksum = binding.get("checksum")
        if expected_checksum and str(expected_checksum) != str(inventory["sha256"]):
            raise BackupError(f"active_profile_checksum_mismatch:{relative}")
        expected_size = binding.get("file_size_bytes")
        if expected_size is not None and int(expected_size) != int(inventory["size"]):
            raise BackupError(f"active_profile_file_size_mismatch:{relative}")
        config_relative = _source_relative_path(
            source_root,
            str(raw_config_path),
            "active_profile_config_outside_source_root",
        )
        config_inventory = inventory_by_path.get(config_relative)
        if config_inventory is None:
            raise BackupError(f"active_profile_config_not_backed_up:{config_relative}")
        if config_inventory.get("category") != "data_profiles":
            raise BackupError(f"active_profile_config_category_invalid:{config_relative}")
        verified.append(
            {
                "binding_id": int(binding_id),
                "profile_database_id": int(profile_database_id),
                "profile_id": str(binding["profile_id"]),
                "profile_config_relative_path": config_relative,
                "profile_config_sha256": str(config_inventory["sha256"]),
                "instrument_symbol": str(binding["instrument_symbol"]),
                "contract_code": str(binding["contract_code"]),
                "period": str(binding["period"]),
                "data_version": str(binding["data_version"]),
                "market_data_file_id": int(market_data_file_id),
                "relative_path": relative,
                "sha256": str(inventory["sha256"]),
                "size": int(inventory["size"]),
            }
        )
    return verified


def _source_relative_path(source_root: Path, raw_path: str, outside_error: str) -> str:
    candidate = Path(raw_path)
    resolved = candidate.resolve(strict=False) if candidate.is_absolute() else (source_root / candidate).resolve(strict=False)
    try:
        return resolved.relative_to(source_root).as_posix()
    except ValueError as exc:
        raise BackupError(outside_error) from exc


def _database_manifest(evidence: DatabaseEvidence, dump_path: Path, staging: Path) -> dict[str, Any]:
    return {
        "included": True,
        "identity": dict(evidence.identity),
        "alembic_revision": evidence.alembic_revision,
        "snapshot_consistent": True,
        "table_counts": dict(sorted(evidence.table_counts.items())),
        "report14": dict(evidence.report14),
        "active_profile_binding_count": None,
        "active_profile_file_count": None,
        "active_profile_bindings": None,
        "tool": dict(evidence.tool),
        "dump": {
            "path": dump_path.relative_to(staging).as_posix(),
            "size": dump_path.stat().st_size,
            "sha256": _sha256_file(dump_path),
            "format": "custom",
        },
    }


def _database_not_included() -> dict[str, Any]:
    return {
        "included": False,
        "identity": None,
        "alembic_revision": None,
        "snapshot_consistent": None,
        "table_counts": None,
        "report14": None,
        "active_profile_binding_count": None,
        "active_profile_file_count": None,
        "active_profile_bindings": None,
        "tool": None,
        "dump": None,
    }


def _verify_report14(value: Mapping[str, Any]) -> None:
    if (
        value.get("md5") != REPORT14_MD5
        or int(value.get("trades") or 0) != REPORT14_TRADES
        or int(value.get("orders") or 0) != REPORT14_ORDERS
    ):
        raise BackupError("report14_invariant_mismatch")


def _category_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        category = str(row["category"])
        summary = result.setdefault(category, {"file_count": 0, "total_size": 0})
        summary["file_count"] += 1
        summary["total_size"] += int(row["size"])
    return dict(sorted(result.items()))


def _verify_staged_backup(staging: Path, manifest: Mapping[str, Any]) -> None:
    inventory = manifest["inventory"]
    inventory_path = staging / str(inventory["path"])
    if _sha256_file(inventory_path) != inventory["sha256"]:
        raise BackupError("inventory_checksum_mismatch")
    database = manifest["database"]
    if database["included"]:
        dump = database["dump"]
        if _sha256_file(staging / dump["path"]) != dump["sha256"]:
            raise BackupError("database_dump_checksum_mismatch")


def _claim_backup_id(output_root: Path, backup_id: str) -> tuple[int, Path]:
    lock_path = output_root / f".{backup_id}.lock"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise BackupError("backup_id_locked") from exc
    return descriptor, lock_path


def _release_backup_id(descriptor: int, lock_path: Path) -> None:
    owned_lock = _identity_from_stat(os.fstat(descriptor))
    os.close(descriptor)
    try:
        _remove_owned_lock(lock_path, owned_lock)
    except FileNotFoundError:
        return


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _identity_from_stat(info: os.stat_result) -> _PathIdentity:
    return _PathIdentity(device=info.st_dev, inode=info.st_ino)


def _path_identity(path: Path) -> _PathIdentity:
    return _identity_from_stat(path.stat(follow_symlinks=False))


def _remove_owned_lock(lock_path: Path, owned_identity: _PathIdentity) -> None:
    quarantine = _isolate_owned_path(lock_path, owned_identity, kind="lock")
    if quarantine is None:
        return
    if _path_identity(quarantine) != owned_identity:
        raise BackupError("lock_ownership_lost_quarantine_preserved")
    try:
        quarantine.unlink()
    except FileNotFoundError:
        return


def _remove_owned_staging(staging: Path, owned_identity: _PathIdentity) -> None:
    quarantine = _isolate_owned_path(staging, owned_identity, kind="staging")
    if quarantine is None:
        return
    if _path_identity(quarantine) != owned_identity:
        raise BackupError("staging_ownership_lost_quarantine_preserved")
    _remove_staging(quarantine)


def _isolate_owned_path(path: Path, owned_identity: _PathIdentity, *, kind: str) -> Path | None:
    try:
        current_identity = _path_identity(path)
    except FileNotFoundError:
        return None
    if current_identity != owned_identity:
        return None
    try:
        quarantine = _move_to_quarantine(path, kind=kind)
    except FileNotFoundError:
        return None
    moved_identity = _path_identity(quarantine)
    if moved_identity == owned_identity:
        return quarantine
    try:
        _rename_no_replace(quarantine, path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise BackupError(f"{kind}_ownership_lost_quarantine_preserved") from exc
        raise BackupError(f"{kind}_ownership_lost_quarantine_preserved") from exc
    return None


def _move_to_quarantine(path: Path, *, kind: str) -> Path:
    for _attempt in range(8):
        candidate = path.parent / f".backup-{kind}-quarantine-{os.getpid()}-{secrets.token_hex(8)}"
        try:
            _rename_no_replace(path, candidate)
            return candidate
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                continue
            raise
    raise BackupError(f"{kind}_quarantine_unavailable")


def _remove_staging(staging: Path) -> None:
    if staging.is_symlink():
        raise BackupError("staging_ownership_lost_quarantine_preserved")
    staging.chmod(0o700)
    for path in staging.rglob("*"):
        if path.is_symlink():
            continue
        path.chmod(0o700 if path.is_dir() else 0o600)
    shutil.rmtree(staging)


def _rename_no_replace(source: Path, destination: Path) -> None:
    if sys.platform == "darwin":
        _darwin_rename_no_replace(source, destination)
        return
    if sys.platform.startswith("linux"):
        _linux_rename_no_replace(source, destination)
        return
    raise BackupError("atomic_rename_noreplace_unavailable")


def _darwin_rename_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renamex_np = getattr(libc, "renamex_np", None)
    if renamex_np is None:
        raise BackupError("atomic_rename_noreplace_unavailable")
    renamex_np.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    renamex_np.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = renamex_np(os.fsencode(source), os.fsencode(destination), 0x00000004)
    if result != 0:
        _raise_rename_error(source, destination)


def _linux_rename_no_replace(source: Path, destination: Path) -> None:
    syscall_number = {
        "aarch64": 276,
        "amd64": 316,
        "arm64": 276,
        "i386": 353,
        "i686": 353,
        "ppc64le": 357,
        "riscv64": 276,
        "s390x": 347,
        "x86_64": 316,
    }.get(os.uname().machine)
    if syscall_number is None:
        raise BackupError("atomic_rename_noreplace_unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    syscall = getattr(libc, "syscall", None)
    if syscall is None:
        raise BackupError("atomic_rename_noreplace_unavailable")
    ctypes.set_errno(0)
    result = syscall(
        syscall_number,
        -100,
        ctypes.c_char_p(os.fsencode(source)),
        -100,
        ctypes.c_char_p(os.fsencode(destination)),
        0x00000001,
    )
    if result != 0:
        _raise_rename_error(source, destination)


def _raise_rename_error(source: Path, destination: Path) -> None:
    code = ctypes.get_errno()
    if code in {errno.ENOSYS, errno.ENOTSUP}:
        raise BackupError("atomic_rename_noreplace_unavailable")
    raise OSError(code, os.strerror(code), str(source), str(destination))


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


class PostgresDumpProvider:
    """Create a pg_dump and its evidence from one exported MVCC snapshot."""

    def create_dump(self, destination: Path, *, tool_mode: str, container: str) -> DatabaseEvidence:
        try:
            from sqlalchemy import create_engine, text
            from sqlalchemy.engine import make_url
            from app.db.session import DATABASE_URL
        except ImportError as exc:
            raise BackupError("database_dependencies_unavailable") from exc
        url = make_url(DATABASE_URL)
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        try:
            with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
                transaction = connection.begin()
                try:
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    snapshot = str(connection.scalar(text("SELECT pg_export_snapshot()")) or "")
                    if not snapshot:
                        raise BackupError("database_snapshot_export_failed")
                    table_names = list(
                        connection.scalars(
                            text(
                                "SELECT table_name FROM information_schema.tables "
                                "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
                            )
                        )
                    )
                    counts: dict[str, int] = {}
                    preparer = connection.dialect.identifier_preparer
                    for table_name in table_names:
                        quoted = preparer.quote(str(table_name))
                        counts[str(table_name)] = int(connection.scalar(text(f"SELECT count(*) FROM {quoted}")) or 0)
                    revision = str(connection.scalar(text("SELECT version_num FROM alembic_version")) or "")
                    report14 = {
                        "md5": connection.scalar(text("SELECT md5(to_jsonb(t)::text) FROM backtest_reports t WHERE id=14")),
                        "trades": int(connection.scalar(text("SELECT count(*) FROM backtest_trades WHERE report_id=14")) or 0),
                        "orders": int(connection.scalar(text("SELECT count(*) FROM backtest_orders WHERE report_id=14")) or 0),
                    }
                    _verify_report14(report14)
                    profile_bindings = [
                        dict(row)
                        for row in connection.execute(
                            text(
                                "SELECT b.id AS binding_id, p.id AS profile_database_id, "
                                "b.profile_id, p.config_path AS profile_config_path, b.instrument_symbol, "
                                "b.contract_code, b.period, b.data_version, b.market_data_file_id, "
                                "m.file_path, m.checksum, m.file_size_bytes "
                                "FROM profile_active_bindings b "
                                "LEFT JOIN data_profiles p ON p.profile_id=b.profile_id "
                                "LEFT JOIN market_data_files m ON m.id=b.market_data_file_id "
                                "WHERE b.binding_status='active' "
                                "ORDER BY b.profile_id, b.instrument_symbol, b.contract_code, b.period, b.id"
                            )
                        ).mappings()
                    ]
                    selected_mode, version = _run_pg_dump(
                        destination,
                        snapshot=snapshot,
                        tool_mode=tool_mode,
                        container=container,
                        url=url,
                    )
                    transaction.rollback()
                except Exception:
                    transaction.rollback()
                    raise
        except BackupError:
            raise
        except Exception as exc:
            raise BackupError(f"database_backup_failed:{type(exc).__name__}") from exc
        finally:
            engine.dispose()
        return DatabaseEvidence(
            identity={
                "driver": url.drivername,
                "host": url.host,
                "port": url.port,
                "database": url.database,
            },
            alembic_revision=revision,
            table_counts=counts,
            report14=report14,
            active_profile_bindings=profile_bindings,
            tool={"mode": selected_mode, "version": version},
        )


def _run_pg_dump(destination: Path, *, snapshot: str, tool_mode: str, container: str, url: Any) -> tuple[str, str]:
    selected = tool_mode
    if selected == "auto":
        selected = "host" if shutil.which("pg_dump") else "docker"
    destination.parent.mkdir(parents=True, exist_ok=True)
    common = ["--format=custom", "--no-owner", "--no-acl", f"--snapshot={snapshot}"]
    if selected == "host":
        executable = shutil.which("pg_dump")
        if executable is None:
            raise BackupError("pg_dump_unavailable")
        command = [executable, *common, f"--file={destination}"]
        environment = _pg_environment(url)
        version_command = [executable, "--version"]
        stdout: Any = subprocess.DEVNULL
    else:
        docker = shutil.which("docker")
        if docker is None:
            raise BackupError("docker_unavailable")
        command = [
            docker,
            "exec",
            container,
            "pg_dump",
            *common,
            "--username",
            str(url.username or "guiyi"),
            "--dbname",
            str(url.database or "guiyi_quant"),
        ]
        environment = os.environ.copy()
        version_command = [docker, "exec", container, "pg_dump", "--version"]
        stdout = destination.open("wb")
    try:
        subprocess.run(command, check=True, env=environment, stdout=stdout, stderr=subprocess.PIPE)
        version = subprocess.run(version_command, check=True, capture_output=True, text=True).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise BackupError(f"pg_dump_failed:exit_{exc.returncode}") from exc
    finally:
        if selected == "docker" and hasattr(stdout, "close"):
            stdout.close()
    if not destination.is_file() or destination.stat().st_size == 0:
        raise BackupError("pg_dump_output_missing")
    return selected, version


def _pg_environment(url: Any) -> dict[str, str]:
    environment = os.environ.copy()
    values = {
        "PGHOST": url.host,
        "PGPORT": str(url.port) if url.port else None,
        "PGUSER": url.username,
        "PGDATABASE": url.database,
        "PGPASSWORD": url.password,
    }
    for name, value in values.items():
        if value is not None:
            environment[name] = str(value)
    return environment


def _git_commit(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD")


def _git_tree_state_hash(root: Path) -> str:
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    return _sha256_bytes(status.encode())


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(("git", *args), cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise BackupError("git_identity_unavailable") from exc


def _mount_point(path: Path) -> Path:
    current = path.resolve()
    while not os.path.ismount(current):
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _validate_backup_id(value: str) -> None:
    if not value or len(value) > 128 or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in value):
        raise BackupError("backup_id_invalid")


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "BackupDependencies",
    "BackupError",
    "DatabaseEvidence",
    "PostgresDumpProvider",
    "default_dependencies",
    "execute_backup",
]
