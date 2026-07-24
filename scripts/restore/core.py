from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Any, Protocol

from scripts.backup.artifact import ArtifactError, VerifiedBackupArtifact, verify_backup_artifact
from scripts.backup.core import (
    BackupError,
    _identity_from_stat,
    _isolate_owned_path,
    _path_identity,
    _remove_owned_lock,
    _remove_owned_staging,
    _rename_no_replace,
)


RESTORE_SCHEMA_VERSION = "guiyi_isolated_restore_v1"
REPORT14_MD5 = "ae807ef77f7d9a4ce3067996558b57e8"
TARGET_DATABASE_PATTERN = re.compile(r"guiyi_restore_[a-z0-9_]+")


class RestoreError(RuntimeError):
    pass


class RestoreRuntime(Protocol):
    def restore_and_verify(
        self, artifact: VerifiedBackupArtifact, *, target_database: str, target_root: Path
    ) -> dict[str, Any]: ...

    def cleanup(self) -> dict[str, bool]: ...


class UnavailableRuntime:
    def restore_and_verify(self, artifact: VerifiedBackupArtifact, *, target_database: str, target_root: Path) -> dict[str, Any]:
        raise RestoreError("restore_runtime_unavailable")

    def cleanup(self) -> dict[str, bool]:
        return {"container_removed": True, "volume_removed": True}


class DockerPostgresRuntime:
    def __init__(self, *, command_runner: Any | None = None, password: str | None = None) -> None:
        self.command_runner = command_runner or self._run
        self.password = password or secrets.token_urlsafe(32)
        self.container: str | None = None
        self.container_id: str | None = None
        self.volume: str | None = None
        self._ownership_token: str | None = None
        self._container_candidate = False
        self._container_owned = False
        self._volume_candidate = False
        self._volume_owned = False

    @staticmethod
    def pg_restore_command(container: str, database: str, dump_path: Path) -> list[str]:
        return ["docker", "exec", container, "pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl", "--username", "guiyi_restore", "--dbname", database, str(dump_path)]

    def restore_and_verify(self, artifact: VerifiedBackupArtifact, *, target_database: str, target_root: Path) -> dict[str, Any]:
        token = secrets.token_hex(6)
        self._ownership_token = token
        self.container = f"guiyi-restore-{token}"
        self.volume = f"guiyi_restore_{token}"
        ownership_label = f"guiyi.restore.id={token}"
        existing = self.command_runner(
            ["docker", "volume", "ls", "--quiet", "--filter", f"name=^{self.volume}$"]
        ).splitlines()
        if self.volume in existing:
            raise RestoreError("isolated_volume_already_exists")
        created_volume = self.command_runner(["docker", "volume", "create", "--label", ownership_label, self.volume]).strip()
        if created_volume != self.volume:
            raise RestoreError("isolated_volume_identity_mismatch")
        self._volume_candidate = True
        if self._inspect_volume(self.volume) != (self.volume, token):
            raise RestoreError("isolated_volume_ownership_mismatch")
        self._volume_owned = True
        with tempfile.TemporaryDirectory(prefix="guiyi-restore-env-") as directory:
            env_file = Path(directory) / "postgres.env"
            _write_private_file(
                env_file,
                f"POSTGRES_USER=guiyi_restore\nPOSTGRES_PASSWORD={self.password}\nPOSTGRES_DB={target_database}\n".encode(),
            )
            created_container = self.command_runner(["docker", "run", "--detach", "--name", self.container, "--label", ownership_label, "--publish", "127.0.0.1::5432", "--mount", f"type=volume,source={self.volume},target=/var/lib/postgresql/data", "--env-file", str(env_file), "postgres:16"]).strip()
            if not created_container:
                raise RestoreError("isolated_container_identity_missing")
            self.container_id = created_container
            self._container_candidate = True
            if self._inspect_container(self.container_id) != (
                self.container_id,
                self.container,
                token,
            ):
                raise RestoreError("isolated_container_ownership_mismatch")
            self._container_owned = True
        assert self.container_id is not None
        for _attempt in range(30):
            try:
                self.command_runner(["docker", "exec", self.container_id, "pg_isready", "--username", "guiyi_restore", "--dbname", target_database])
                break
            except RestoreError:
                time.sleep(1)
        else:
            raise RestoreError("isolated_postgres_not_ready")
        self.command_runner(["docker", "cp", str(artifact.dump_path), f"{self.container_id}:/tmp/guiyi.dump"])
        self.command_runner(self.pg_restore_command(self.container_id, target_database, Path("/tmp/guiyi.dump")))
        version = self.command_runner(["docker", "exec", self.container_id, "pg_restore", "--version"]).strip()
        port_text = self.command_runner(["docker", "port", self.container_id, "5432/tcp"]).strip()
        port = int(port_text.rsplit(":", 1)[-1])
        url = f"postgresql+psycopg://guiyi_restore:{self.password}@127.0.0.1:{port}/{target_database}"
        evidence = verify_restored_database(url, artifact, target_root)
        evidence["pg_restore_version"] = version
        return evidence

    def cleanup(self) -> dict[str, bool]:
        container_removed = True
        volume_removed = True
        if self._container_candidate:
            if not self.container_id or not self.container or not self._ownership_token:
                container_removed = False
            else:
                try:
                    owned = self._inspect_container(self.container_id) == (
                        self.container_id,
                        self.container,
                        self._ownership_token,
                    )
                except RestoreError:
                    owned = False
                if not owned:
                    container_removed = False
                else:
                    try:
                        self.command_runner(["docker", "rm", "--force", self.container_id])
                        self._container_candidate = False
                        self._container_owned = False
                    except RestoreError:
                        container_removed = False
        elif self._container_owned:
            container_removed = False
        if self.volume and self._volume_candidate and not self._volume_owned:
            try:
                self._volume_owned = self._inspect_volume(self.volume) == (
                    self.volume,
                    self._ownership_token,
                )
            except RestoreError:
                self._volume_owned = False
            if not self._volume_owned:
                volume_removed = False
        if self.volume and self._volume_owned:
            try:
                owned = self._inspect_volume(self.volume) == (
                    self.volume,
                    self._ownership_token,
                )
            except RestoreError:
                owned = False
            if not owned:
                volume_removed = False
            else:
                try:
                    self.command_runner(["docker", "volume", "rm", self.volume])
                    self._volume_owned = False
                    self._volume_candidate = False
                except RestoreError:
                    volume_removed = False
        return {"container_removed": container_removed, "volume_removed": volume_removed}

    def _inspect_container(self, identifier: str) -> tuple[str, str, str]:
        output = self.command_runner(
            [
                "docker",
                "inspect",
                "--format",
                '{{.Id}}\n{{.Name}}\n{{ index .Config.Labels "guiyi.restore.id" }}',
                identifier,
            ]
        ).splitlines()
        if len(output) != 3:
            raise RestoreError("isolated_container_identity_missing")
        return output[0].strip(), output[1].strip().removeprefix("/"), output[2].strip()

    def _inspect_volume(self, name: str) -> tuple[str, str]:
        output = self.command_runner(
            [
                "docker",
                "volume",
                "inspect",
                "--format",
                '{{.Name}}\n{{ index .Labels "guiyi.restore.id" }}',
                name,
            ]
        ).splitlines()
        if len(output) != 2:
            raise RestoreError("isolated_volume_identity_missing")
        return output[0].strip(), output[1].strip()

    @staticmethod
    def _run(command: list[str], **_kwargs: Any) -> str:
        try:
            return subprocess.run(command, check=True, capture_output=True, text=True).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            code = exc.returncode if isinstance(exc, subprocess.CalledProcessError) else "unavailable"
            raise RestoreError(f"isolated_runtime_command_failed:{code}") from exc


@dataclass(frozen=True)
class RestoreDependencies:
    production_database: str
    production_roots: tuple[Path, ...]
    runtime: RestoreRuntime
    now: Any = lambda: datetime.now(UTC)
    token_hex: Any = secrets.token_hex

    @classmethod
    def for_tests(
        cls,
        *,
        production_database: str,
        production_roots: tuple[Path, ...] = (),
        runtime: RestoreRuntime | None = None,
    ) -> "RestoreDependencies":
        return cls(production_database, production_roots, runtime or UnavailableRuntime())


def execute_isolated_restore(
    *,
    backup_root: Path,
    target_database: str,
    target_data_root: Path,
    isolated: bool,
    confirm_isolated_restore: bool,
    dependencies: RestoreDependencies,
) -> dict[str, Any]:
    if not isolated or not confirm_isolated_restore:
        raise RestoreError("isolated_restore_confirmation_required")
    if (
        not isinstance(dependencies.production_database, str)
        or not dependencies.production_database.strip()
    ):
        raise RestoreError("production_database_identity_unavailable")
    if TARGET_DATABASE_PATTERN.fullmatch(target_database) is None:
        raise RestoreError("target_database_invalid")
    if target_database == dependencies.production_database:
        raise RestoreError("target_database_matches_production")
    requested_backup = backup_root.expanduser()
    backup = requested_backup.resolve(strict=False)
    requested_target = target_data_root.expanduser()
    if requested_target.is_symlink():
        raise RestoreError("target_data_root_not_empty")
    target = requested_target.parent.resolve(strict=False) / requested_target.name
    _validate_target(target, backup, dependencies.production_roots)
    try:
        artifact = verify_backup_artifact(requested_backup)
    except ArtifactError as exc:
        raise RestoreError(str(exc)) from exc
    database_identity = artifact.manifest["database"].get("identity")
    artifact_database = (
        database_identity.get("database")
        if isinstance(database_identity, dict)
        else None
    )
    if not isinstance(artifact_database, str) or not artifact_database.strip():
        raise RestoreError("artifact_database_identity_unavailable")
    if target_database == artifact_database:
        raise RestoreError("target_database_matches_artifact")
    recorded_source_root = Path(str(artifact.manifest["source"]["root"]))
    _validate_target(target, backup, (*dependencies.production_roots, recorded_source_root))
    parent = target.parent
    if not parent.is_dir():
        raise RestoreError("target_parent_unavailable")
    lock = parent / f".{target.name}.restore.lock"
    lock_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        lock_flags |= os.O_NOFOLLOW
    try:
        lock_fd = os.open(lock, lock_flags, 0o600)
    except FileExistsError as exc:
        raise RestoreError("restore_target_locked") from exc
    target_reservation: Path | None = None
    target_reservation_identity: Any | None = None
    staging: Path | None = None
    staging_identity: Any | None = None
    owned_restore_root: Path | None = None
    runtime_started = False
    try:
        if _path_exists(target):
            target_reservation, target_reservation_identity = _reserve_empty_target(
                target,
                token_hex=dependencies.token_hex,
            )
        staging = parent / f".{target.name}.partial-{os.getpid()}-{dependencies.token_hex(3)}"
        staging.mkdir(mode=0o700)
        staging_identity = _path_identity(staging)
        owned_restore_root = staging
        with tempfile.TemporaryDirectory(prefix="guiyi-restore-dump-") as directory:
            private_directory = Path(directory)
            private_directory.chmod(0o700)
            stable_artifact = _stabilize_database_dump(artifact, private_directory)
            _extract(stable_artifact, staging)
            runtime_started = True
            evidence = dependencies.runtime.restore_and_verify(
                stable_artifact,
                target_database=target_database,
                target_root=staging,
            )
        _validate_evidence(artifact, evidence)
        try:
            cleanup = dependencies.runtime.cleanup()
        except Exception as exc:
            raise RestoreError("isolated_runtime_cleanup_failed") from exc
        if not all(cleanup.values()):
            raise RestoreError("isolated_runtime_cleanup_failed")
        runtime_started = False
        receipt = _receipt(artifact, target_database, target, evidence, cleanup, dependencies.now())
        _write_receipt(staging, receipt)
        owned_restore_root = _quarantine_owned_path(
            staging,
            staging_identity,
            kind="restore-staging",
            error="staging_ownership_lost",
        )
        _make_read_only(owned_restore_root)
        try:
            _rename_no_replace(owned_restore_root, target)
        except BackupError as exc:
            raise RestoreError("target_promotion_failed") from exc
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise RestoreError("target_root_changed_during_restore") from exc
            raise RestoreError("target_promotion_failed") from exc
        owned_restore_root = target
        if _path_identity(target) != staging_identity:
            raise RestoreError("target_root_changed_during_restore")
        if target_reservation is not None and target_reservation_identity is not None:
            _remove_owned_directory(
                target_reservation,
                target_reservation_identity,
                kind="restore-target-reservation",
                error="target_reservation_cleanup_failed",
            )
            target_reservation = None
        return {"status": "completed", "receipt": str(target / "isolated_restore_receipt.json")}
    except Exception as primary_error:
        cleanup_failed = False
        if runtime_started:
            try:
                runtime_cleanup = dependencies.runtime.cleanup()
                if not all(runtime_cleanup.values()):
                    cleanup_failed = True
            except Exception:
                cleanup_failed = True
        if owned_restore_root is not None and staging_identity is not None:
            try:
                _remove_owned_directory(
                    owned_restore_root,
                    staging_identity,
                    kind="restore-root",
                    error="restore_root_cleanup_failed",
                )
            except RestoreError:
                cleanup_failed = True
        if target_reservation is not None and target_reservation_identity is not None:
            try:
                _restore_target_reservation(
                    target_reservation,
                    target_reservation_identity,
                    target,
                )
            except RestoreError:
                cleanup_failed = True
        if cleanup_failed:
            raise RestoreError("isolated_restore_cleanup_failed") from primary_error
        raise
    finally:
        _release_lock(lock_fd, lock)


def _validate_target(target: Path, backup: Path, production_roots: tuple[Path, ...]) -> None:
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise RestoreError("target_data_root_not_empty")
    protected = (backup, backup.parent, *production_roots)
    for root in protected:
        resolved = root.expanduser().resolve(strict=False)
        if target == resolved or target in resolved.parents or resolved in target.parents:
            raise RestoreError("target_data_root_overlaps_protected_root")


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _reserve_empty_target(target: Path, *, token_hex: Any) -> tuple[Path, Any]:
    try:
        identity = _path_identity(target)
    except FileNotFoundError as exc:
        raise RestoreError("target_root_changed_during_restore") from exc
    if target.is_symlink() or not target.is_dir() or any(target.iterdir()):
        raise RestoreError("target_data_root_not_empty")
    for _attempt in range(8):
        reservation = (
            target.parent
            / f".{target.name}.restore-target-reservation-{os.getpid()}-{token_hex(8)}"
        )
        try:
            _rename_no_replace(target, reservation)
            break
        except BackupError as exc:
            raise RestoreError("target_reservation_failed") from exc
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                continue
            raise RestoreError("target_reservation_failed") from exc
    else:
        raise RestoreError("target_reservation_unavailable")
    try:
        moved_identity = _path_identity(reservation)
    except FileNotFoundError as exc:
        raise RestoreError("target_root_changed_during_restore") from exc
    if moved_identity != identity:
        try:
            _rename_no_replace(reservation, target)
        except (BackupError, OSError) as exc:
            raise RestoreError("target_ownership_lost_reservation_preserved") from exc
        raise RestoreError("target_root_changed_during_restore")
    return reservation, identity


def _quarantine_owned_path(
    path: Path,
    identity: Any,
    *,
    kind: str,
    error: str,
) -> Path:
    try:
        quarantine = _isolate_owned_path(path, identity, kind=kind)
    except (BackupError, OSError) as exc:
        raise RestoreError(error) from exc
    if quarantine is None:
        raise RestoreError(error)
    try:
        if _path_identity(quarantine) != identity:
            raise RestoreError(error)
    except FileNotFoundError as exc:
        raise RestoreError(error) from exc
    return quarantine


def _remove_owned_directory(
    path: Path,
    identity: Any,
    *,
    kind: str,
    error: str,
) -> None:
    quarantine = _quarantine_owned_path(
        path,
        identity,
        kind=kind,
        error=error,
    )
    try:
        _remove_owned_staging(quarantine, identity)
    except (BackupError, OSError) as exc:
        raise RestoreError(error) from exc


def _restore_target_reservation(
    reservation: Path,
    identity: Any,
    target: Path,
) -> None:
    if _path_exists(target):
        raise RestoreError("target_reservation_restore_blocked")
    quarantine = _quarantine_owned_path(
        reservation,
        identity,
        kind="restore-target-reservation",
        error="target_reservation_ownership_lost",
    )
    try:
        _rename_no_replace(quarantine, target)
    except BackupError as exc:
        raise RestoreError("target_reservation_restore_failed") from exc
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise RestoreError("target_reservation_restore_blocked") from exc
        raise RestoreError("target_reservation_restore_failed") from exc
    if _path_identity(target) != identity:
        raise RestoreError("target_reservation_ownership_lost")


def _stabilize_database_dump(
    artifact: VerifiedBackupArtifact,
    private_directory: Path,
) -> VerifiedBackupArtifact:
    dump = artifact.manifest["database"]["dump"]
    expected_size = int(dump["size"])
    expected_sha256 = str(dump["sha256"])
    source_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        source_flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(artifact.dump_path, source_flags)
    except OSError as exc:
        raise RestoreError("database_dump_stabilization_failed") from exc
    destination = private_directory / "verified.dump"
    destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        destination_flags |= os.O_NOFOLLOW
    try:
        source_info = os.fstat(source_fd)
        if not stat.S_ISREG(source_info.st_mode) or source_info.st_size != expected_size:
            raise RestoreError("database_dump_changed_after_verification")
        destination_fd = os.open(destination, destination_flags, 0o600)
        try:
            os.fchmod(destination_fd, 0o600)
            digest = hashlib.sha256()
            copied = 0
            with os.fdopen(source_fd, "rb", closefd=False) as source_handle:
                with os.fdopen(destination_fd, "wb", closefd=False) as destination_handle:
                    for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                        destination_handle.write(chunk)
                        digest.update(chunk)
                        copied += len(chunk)
                    destination_handle.flush()
            if copied != expected_size or digest.hexdigest() != expected_sha256:
                raise RestoreError("database_dump_changed_after_verification")
        finally:
            os.close(destination_fd)
    except OSError as exc:
        raise RestoreError("database_dump_stabilization_failed") from exc
    finally:
        os.close(source_fd)
    return replace(artifact, dump_path=destination)


def _extract(artifact: VerifiedBackupArtifact, staging: Path) -> None:
    for row in artifact.inventory:
        relative = Path(str(row["relative_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise RestoreError("inventory_path_invalid")
        source = artifact.root / "files" / relative
        destination = staging / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if _sha256(destination) != row["sha256"]:
            raise RestoreError("restored_file_checksum_mismatch")


def _validate_evidence(artifact: VerifiedBackupArtifact, evidence: dict[str, Any]) -> None:
    database = artifact.manifest["database"]
    if evidence.get("alembic_revision") != database.get("alembic_revision"):
        raise RestoreError("restored_alembic_revision_mismatch")
    if evidence.get("table_counts") != database.get("table_counts"):
        raise RestoreError("restored_table_counts_mismatch")
    report = evidence.get("report14") or {}
    if report != database.get("report14") or report.get("md5") != REPORT14_MD5:
        raise RestoreError("restored_report14_mismatch")
    if evidence.get("transaction_read_only") is not True or evidence.get("consumer_methods") != ["GET"] * 5:
        raise RestoreError("consumer_smoke_not_read_only")
    if evidence.get("database_unchanged") is not True or evidence.get("profile_verified") is not True:
        raise RestoreError("isolated_restore_verification_failed")


def _receipt(artifact: VerifiedBackupArtifact, database: str, target: Path, evidence: dict[str, Any], cleanup: dict[str, bool], now: datetime) -> dict[str, Any]:
    return {
        "schema_version": RESTORE_SCHEMA_VERSION,
        "status": "passed",
        "created_at": now.astimezone(UTC).isoformat(),
        "tool": {"restore_schema_version": RESTORE_SCHEMA_VERSION, "postgres_image": "postgres:16"},
        "backup": {"backup_id": artifact.manifest["backup_id"], "manifest_sha256": artifact.manifest_sha256},
        "artifact_verification": {
            "file_count": artifact.manifest["inventory"]["file_count"],
            "total_size": artifact.manifest["inventory"]["total_size"],
            "dump_sha256": artifact.manifest["database"]["dump"]["sha256"],
            "profile_binding_count": artifact.manifest["database"]["active_profile_binding_count"],
            "all_declared_files_verified": True,
            "profile_verified": evidence["profile_verified"],
        },
        "isolated": {"target_database": database, "target_data_root": str(target), **cleanup},
        "database": {key: evidence[key] for key in ("alembic_revision", "table_counts", "report14", "pg_restore_version")},
        "consumer_smoke": evidence["consumer_smoke"],
        "boundaries": {
            "transaction_read_only": True,
            "database_unchanged": True,
            "production_database_touched": False,
            "production_data_touched": False,
            "profile_binding_modified": False,
            "worker_started": False,
            "scheduler_started": False,
            "redis_accessed": False,
            "wechat_called": False,
        },
    }


def _write_receipt(root: Path, receipt: dict[str, Any]) -> None:
    path = root / "isolated_restore_receipt.json"
    sidecar = root / "isolated_restore_receipt.sha256"
    payload = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    receipt_identity = _write_create_only(path, payload)
    try:
        _write_create_only(sidecar, (hashlib.sha256(payload).hexdigest() + "\n").encode())
    except Exception:
        try:
            quarantine = _quarantine_owned_path(
                path,
                receipt_identity,
                kind="restore-receipt",
                error="restore_receipt_cleanup_failed",
            )
            quarantine.unlink()
        except (OSError, RestoreError) as exc:
            raise RestoreError("restore_receipt_cleanup_failed") from exc
        raise


def _write_create_only(path: Path, payload: bytes) -> Any:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise RestoreError("restore_receipt_already_exists") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        return _identity_from_stat(os.fstat(handle.fileno()))


def _write_private_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _release_lock(descriptor: int, path: Path) -> None:
    identity = _identity_from_stat(os.fstat(descriptor))
    os.close(descriptor)
    try:
        _remove_owned_lock(path, identity)
    except FileNotFoundError:
        return
    except (BackupError, OSError) as exc:
        raise RestoreError("restore_lock_cleanup_failed") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_restored_database(database_url: str, artifact: VerifiedBackupArtifact, target_root: Path) -> dict[str, Any]:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, inspect, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from sqlalchemy.orm.attributes import set_committed_value

    from app.db.session import get_db
    from app.main import app
    from app.models.backtest import BacktestTradeModel
    from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding

    url = make_url(database_url)
    if url.database is None or TARGET_DATABASE_PATTERN.fullmatch(url.database) is None:
        raise RestoreError("target_database_identity_invalid")
    engine = create_engine(database_url, pool_pre_ping=True)
    database = artifact.manifest["database"]
    try:
        with Session(engine, autoflush=False) as session:
            _enforce_read_only(session)
            revision = str(session.scalar(text("SELECT version_num FROM alembic_version")) or "")
            tables = sorted(inspect(session.connection()).get_table_names())
            required = set(database["table_counts"])
            if any(re.fullmatch(r"[a-z_][a-z0-9_]*", name) is None for name in required):
                raise RestoreError("restored_table_name_invalid")
            if required != set(tables):
                raise RestoreError("restored_core_tables_missing")
            counts = {name: int(session.scalar(text(f'SELECT count(*) FROM "{name}"')) or 0) for name in sorted(required)}
            report14 = {
                "md5": session.scalar(text("SELECT md5(to_jsonb(t)::text) FROM backtest_reports t WHERE id=14")),
                "trades": int(session.scalar(text("SELECT count(*) FROM backtest_trades WHERE report_id=14")) or 0),
                "orders": int(session.scalar(text("SELECT count(*) FROM backtest_orders WHERE report_id=14")) or 0),
            }
            before = _database_snapshot(session, sorted(required))
            retained: list[Any] = []
            source_root = Path(str(artifact.manifest["source"]["root"])).expanduser().resolve(strict=False)
            for binding in database.get("active_profile_bindings") or []:
                market_file = session.get(MarketDataFile, int(binding["market_data_file_id"]))
                profile_binding = session.get(ProfileActiveBinding, int(binding["binding_id"]))
                profile = session.scalar(select(DataProfile).where(DataProfile.profile_id == binding["profile_id"]))
                market_file, profile = _verify_profile_binding_and_rebind(
                    market_file=market_file,
                    profile_binding=profile_binding,
                    profile=profile,
                    binding=binding,
                    source_root=source_root,
                    target_root=target_root,
                    set_value=set_committed_value,
                )
                retained.extend((market_file, profile))

            def override_db():
                yield session

            sentinel = object()
            previous_override = app.dependency_overrides.get(get_db, sentinel)
            app.dependency_overrides[get_db] = override_db
            methods: list[str] = []
            smoke: list[dict[str, Any]] = []
            client: TestClient | None = None
            try:
                client = TestClient(app)
                candidate = (database.get("active_profile_bindings") or [])[0]
                requests = [
                    ("market", "/api/v1/market/bars", {"symbol": candidate["instrument_symbol"], "contract": candidate["contract_code"], "period": candidate["period"], "profile_id": candidate["profile_id"], "access_mode": "research", "tail": "true", "limit": 1}),
                    ("backtest", "/api/backtests/reports/14", None),
                    ("signal_latest", "/api/signals/latest", {"limit": 1}),
                    ("signal_events", "/api/signals/events", {"limit": 1}),
                ]
                for name, path, params in requests:
                    response = client.get(path, params=params)
                    methods.append("GET")
                    body = response.json()
                    market_invalid = name == "market" and (
                        not body.get("bars")
                        or body.get("strict_research_ready") is not True
                        or (body.get("lineage") or {}).get("market_data_file_id") != candidate["market_data_file_id"]
                    )
                    if response.status_code != 200 or market_invalid:
                        raise RestoreError(f"consumer_smoke_failed:{name}")
                    details: dict[str, Any] = {}
                    if name == "market":
                        details = {
                            "row_count": len(body["bars"]),
                            "market_data_file_id": body["lineage"]["market_data_file_id"],
                        }
                    elif name == "backtest":
                        if body.get("id") != 14:
                            raise RestoreError("consumer_smoke_failed:backtest")
                        details = {"report_id": 14}
                    elif isinstance(body, list):
                        details = {"row_count": len(body)}
                    smoke.append({"consumer": name, "method": "GET", "status": "passed", **details})
                trade_id = int(session.scalar(select(BacktestTradeModel.id).where(BacktestTradeModel.report_id == 14).limit(1)) or 0)
                response = client.get(f"/api/reviews/lineage/backtest_trade/{trade_id}")
                methods.append("GET")
                review_body = response.json()
                if (
                    trade_id == 0
                    or response.status_code != 200
                    or review_body.get("source_type") != "backtest_trade"
                    or review_body.get("source_id") != trade_id
                ):
                    raise RestoreError("consumer_smoke_failed:review")
                smoke.append(
                    {
                        "consumer": "review",
                        "method": "GET",
                        "status": "passed",
                        "trade_id": trade_id,
                        "market_data_file_id": (review_body.get("primary") or {}).get("market_data_file_id"),
                    }
                )
            finally:
                if client is not None:
                    client.close()
                if previous_override is sentinel:
                    app.dependency_overrides.pop(get_db, None)
                else:
                    app.dependency_overrides[get_db] = previous_override
            after = _database_snapshot(session, sorted(required))
            unchanged = _session_unchanged(session, before, after)
            session.rollback()
            return {"alembic_revision": revision, "table_counts": counts, "report14": report14, "transaction_read_only": True, "database_unchanged": unchanged, "profile_verified": bool(retained), "consumer_methods": methods, "consumer_smoke": smoke}
    finally:
        engine.dispose()


def _database_snapshot(session: Any, tables: list[str]) -> dict[str, Any]:
    from sqlalchemy import text
    result: dict[str, Any] = {}
    for name in tables:
        row = session.execute(
            text(
                f'SELECT count(*) AS row_count, '
                f"md5(coalesce(string_agg(row_hash, '' ORDER BY row_hash), '')) AS content_md5 "
                f'FROM (SELECT md5(to_jsonb(t)::text) AS row_hash FROM "{name}" t) hashed'
            )
        ).mappings().one()
        result[name] = {"row_count": int(row["row_count"]), "content_md5": str(row["content_md5"])}
    return result


def _enforce_read_only(session: Any) -> None:
    from sqlalchemy import text

    session.execute(text("SET TRANSACTION READ ONLY"))


def _session_unchanged(session: Any, before: dict[str, Any], after: dict[str, Any]) -> bool:
    return before == after and not session.new and not session.dirty and not session.deleted


def _source_path(source_root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = source_root / candidate
    return candidate.resolve(strict=False)


def _verify_profile_binding_and_rebind(
    *,
    market_file: Any,
    profile_binding: Any,
    profile: Any,
    binding: dict[str, Any],
    source_root: Path,
    target_root: Path,
    set_value: Any,
) -> tuple[Any, Any]:
    if market_file is None or profile_binding is None or profile is None:
        raise RestoreError("restored_profile_binding_missing")
    identity = (
        profile_binding.id == int(binding["binding_id"])
        and profile.id == int(binding["profile_database_id"])
        and profile.profile_id == binding["profile_id"]
        and profile_binding.profile_id == binding["profile_id"]
        and profile_binding.instrument_symbol == binding["instrument_symbol"]
        and profile_binding.contract_code == binding["contract_code"]
        and profile_binding.period == binding["period"]
        and profile_binding.data_version == binding["data_version"]
        and profile_binding.market_data_file_id == market_file.id
        and profile_binding.binding_status == "active"
        and market_file.instrument_symbol == binding["instrument_symbol"]
        and market_file.contract_code == binding["contract_code"]
        and market_file.period == binding["period"]
        and market_file.data_version == binding["data_version"]
        and market_file.file_size_bytes == int(binding["size"])
        and market_file.checksum == binding["sha256"]
        and market_file.data_role == "primary"
        and market_file.quality_status != "failed"
    )
    if not identity:
        raise RestoreError("restored_profile_binding_missing")
    config = _isolated_file(target_root, str(binding["profile_config_relative_path"]))
    target = _isolated_file(target_root, str(binding["relative_path"]))
    source_config = _source_path(source_root, str(binding["profile_config_relative_path"]))
    source_file = _source_path(source_root, str(binding["relative_path"]))
    if _source_path(source_root, str(profile.config_path)) != source_config:
        raise RestoreError("restored_profile_config_identity_mismatch")
    if _source_path(source_root, market_file.file_path) != source_file:
        raise RestoreError("restored_profile_file_identity_mismatch")
    if not config.is_file() or _sha256(config) != binding["profile_config_sha256"]:
        raise RestoreError("restored_profile_config_mismatch")
    if not target.is_file() or _sha256(target) != binding["sha256"]:
        raise RestoreError("restored_profile_file_mismatch")
    set_value(market_file, "file_path", str(target))
    set_value(profile, "config_path", str(config))
    return market_file, profile


def _isolated_file(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if not relative or relative_path.is_absolute() or ".." in relative_path.parts:
        raise RestoreError("restored_profile_path_invalid")
    target = (root / relative_path).resolve(strict=False)
    try:
        target.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise RestoreError("restored_profile_path_invalid") from exc
    return target


__all__ = ["DockerPostgresRuntime", "RestoreDependencies", "RestoreError", "RestoreRuntime", "execute_isolated_restore", "verify_restored_database"]
