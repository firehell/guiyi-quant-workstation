from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import stat
from typing import Any

from scripts.backup.core import REPORT14_MD5, REPORT14_ORDERS, REPORT14_TRADES, SCHEMA_VERSION


class ArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedBackupArtifact:
    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    inventory: tuple[dict[str, Any], ...]
    dump_path: Path


def verify_backup_artifact(root: Path) -> VerifiedBackupArtifact:
    requested = root.expanduser()
    if requested.is_symlink():
        raise ArtifactError("backup_root_unavailable")
    resolved = requested.resolve(strict=False)
    if not resolved.is_dir():
        raise ArtifactError("backup_root_unavailable")
    manifest_path = resolved / "backup_manifest.json"
    sidecar = resolved / "backup_manifest.sha256"
    _regular(manifest_path, "backup_manifest_missing")
    _regular(sidecar, "backup_manifest_checksum_missing")
    digest = _sha256(manifest_path)
    if sidecar.read_text(encoding="utf-8").strip() != digest:
        raise ArtifactError("backup_manifest_checksum_mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError("backup_manifest_invalid") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("status") != "completed":
        raise ArtifactError("backup_manifest_contract_invalid")
    if manifest.get("mode") != "full" or not (manifest.get("database") or {}).get("included"):
        raise ArtifactError("full_backup_required")
    report14 = manifest["database"].get("report14") or {}
    if (
        report14.get("md5") != REPORT14_MD5
        or int(report14.get("trades") or 0) != REPORT14_TRADES
        or int(report14.get("orders") or 0) != REPORT14_ORDERS
    ):
        raise ArtifactError("report14_invariant_mismatch")
    inventory_meta = manifest.get("inventory") or {}
    inventory_path = _inside(resolved, str(inventory_meta.get("path") or ""), "inventory_path_invalid")
    _regular(inventory_path, "inventory_missing")
    if _sha256(inventory_path) != inventory_meta.get("sha256"):
        raise ArtifactError("inventory_checksum_mismatch")
    rows: list[dict[str, Any]] = []
    for line in inventory_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ArtifactError("inventory_invalid") from exc
        relative = str(row.get("relative_path") or "")
        source = _inside(resolved / "files", relative, "inventory_path_invalid")
        _regular(source, f"backup_file_missing:{relative}")
        if source.stat().st_size != int(row.get("size", -1)) or _sha256(source) != row.get("sha256"):
            raise ArtifactError(f"backup_file_checksum_mismatch:{relative}")
        rows.append(dict(row))
    if len(rows) != int(inventory_meta.get("file_count", -1)):
        raise ArtifactError("inventory_file_count_mismatch")
    declared = {str(row["relative_path"]) for row in rows}
    if len(declared) != len(rows):
        raise ArtifactError("inventory_duplicate_path")
    if sum(int(row.get("size", -1)) for row in rows) != int(inventory_meta.get("total_size", -1)):
        raise ArtifactError("inventory_total_size_mismatch")
    actual = {
        path.relative_to(resolved / "files").as_posix()
        for path in (resolved / "files").rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != declared:
        raise ArtifactError("backup_file_set_mismatch")
    inventory_by_path = {str(row["relative_path"]): row for row in rows}
    bindings = manifest["database"].get("active_profile_bindings") or []
    if (
        not bindings
        or len(bindings) != int(manifest["database"].get("active_profile_binding_count", -1))
        or len({str(binding.get("relative_path") or "") for binding in bindings})
        != int(manifest["database"].get("active_profile_file_count", -1))
    ):
        raise ArtifactError("active_profile_binding_contract_invalid")
    for binding in bindings:
        relative = str(binding.get("relative_path") or "")
        config_relative = str(binding.get("profile_config_relative_path") or "")
        canonical = inventory_by_path.get(relative)
        config = inventory_by_path.get(config_relative)
        if (
            canonical is None
            or canonical.get("category") != "canonical_parquet"
            or canonical.get("sha256") != binding.get("sha256")
            or int(canonical.get("size", -1)) != int(binding.get("size", -2))
            or config is None
            or config.get("category") != "data_profiles"
            or config.get("sha256") != binding.get("profile_config_sha256")
        ):
            raise ArtifactError("active_profile_binding_artifact_mismatch")
    dump_meta = manifest["database"].get("dump") or {}
    dump_path = _inside(resolved, str(dump_meta.get("path") or ""), "database_dump_path_invalid")
    _regular(dump_path, "database_dump_missing")
    if dump_path.stat().st_size != int(dump_meta.get("size", -1)) or _sha256(dump_path) != dump_meta.get("sha256"):
        raise ArtifactError("database_dump_checksum_mismatch")
    allowed = {
        manifest_path,
        sidecar,
        inventory_path,
        dump_path,
        *(resolved / "files" / relative for relative in declared),
    }
    for path in resolved.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ArtifactError("backup_symlink_rejected")
        if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
            raise ArtifactError("backup_special_entry_rejected")
        if stat.S_ISREG(info.st_mode) and path not in allowed:
            raise ArtifactError("backup_extra_file_rejected")
    return VerifiedBackupArtifact(resolved, manifest, digest, tuple(rows), dump_path)


def _inside(root: Path, relative: str, error: str) -> Path:
    relative_path = Path(relative)
    if not relative or relative_path.is_absolute() or ".." in relative_path.parts:
        raise ArtifactError(error)
    candidate = root / relative_path
    current = root
    for part in relative_path.parts:
        current /= part
        if current.is_symlink():
            raise ArtifactError(error)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise ArtifactError(error) from exc
    return candidate


def _regular(path: Path, error: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ArtifactError(error) from exc
    if not stat.S_ISREG(info.st_mode):
        raise ArtifactError(error)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["ArtifactError", "VerifiedBackupArtifact", "verify_backup_artifact"]
