from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import tempfile
import time
from typing import Any, Protocol


SCHEMA_VERSION = "guiyi_local_backup_v1"
TARGET_DATABASE = re.compile(r"guiyi_restore_[a-z0-9_]+")


class DatabaseOnlyDrillError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseOnlyBackupArtifact:
    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    dump_path: Path


class DatabaseOnlyDrillRuntime(Protocol):
    def restore_and_verify(
        self,
        artifact: DatabaseOnlyBackupArtifact,
        *,
        target_database: str,
    ) -> dict[str, Any]: ...

    def cleanup(self) -> dict[str, bool]: ...


class DockerDatabaseOnlyDrillRuntime:
    def __init__(
        self,
        *,
        command_runner: Any | None = None,
        password: str | None = None,
    ) -> None:
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
    def pg_restore_command(
        container: str,
        database: str,
        dump_path: Path,
    ) -> list[str]:
        return [
            "docker",
            "exec",
            container,
            "pg_restore",
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-acl",
            "--username",
            "guiyi_restore",
            "--dbname",
            database,
            str(dump_path),
        ]

    def restore_and_verify(
        self,
        artifact: DatabaseOnlyBackupArtifact,
        *,
        target_database: str,
    ) -> dict[str, Any]:
        token = secrets.token_hex(6)
        self._ownership_token = token
        self.container = f"guiyi-db-drill-{token}"
        self.volume = f"guiyi_db_drill_{token}"
        ownership_label = f"guiyi.db-drill.id={token}"
        existing = self.command_runner(
            [
                "docker",
                "volume",
                "ls",
                "--quiet",
                "--filter",
                f"name=^{self.volume}$",
            ]
        ).splitlines()
        if self.volume in existing:
            raise DatabaseOnlyDrillError("isolated_volume_already_exists")
        created_volume = self.command_runner(
            [
                "docker",
                "volume",
                "create",
                "--label",
                ownership_label,
                self.volume,
            ]
        ).strip()
        if created_volume != self.volume:
            raise DatabaseOnlyDrillError(
                "isolated_volume_identity_mismatch"
            )
        self._volume_candidate = True
        if self._inspect_volume(self.volume) != (self.volume, token):
            raise DatabaseOnlyDrillError(
                "isolated_volume_ownership_mismatch"
            )
        self._volume_owned = True
        with tempfile.TemporaryDirectory(
            prefix="guiyi-db-drill-env-"
        ) as directory:
            env_file = Path(directory) / "postgres.env"
            _write_private_file(
                env_file,
                (
                    "POSTGRES_USER=guiyi_restore\n"
                    f"POSTGRES_PASSWORD={self.password}\n"
                    f"POSTGRES_DB={target_database}\n"
                ).encode(),
            )
            created_container = self.command_runner(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    self.container,
                    "--label",
                    ownership_label,
                    "--publish",
                    "127.0.0.1::5432",
                    "--mount",
                    (
                        f"type=volume,source={self.volume},"
                        "target=/var/lib/postgresql/data"
                    ),
                    "--env-file",
                    str(env_file),
                    "postgres:16",
                ]
            ).strip()
            if not created_container:
                raise DatabaseOnlyDrillError(
                    "isolated_container_identity_missing"
                )
            self.container_id = created_container
            self._container_candidate = True
            if self._inspect_container(self.container_id) != (
                self.container_id,
                self.container,
                token,
            ):
                raise DatabaseOnlyDrillError(
                    "isolated_container_ownership_mismatch"
                )
            self._container_owned = True
        assert self.container_id is not None
        for _attempt in range(30):
            try:
                self.command_runner(
                    [
                        "docker",
                        "exec",
                        self.container_id,
                        "pg_isready",
                        "--username",
                        "guiyi_restore",
                        "--dbname",
                        target_database,
                    ]
                )
                break
            except DatabaseOnlyDrillError:
                time.sleep(1)
        else:
            raise DatabaseOnlyDrillError(
                "isolated_postgres_not_ready"
            )
        self.command_runner(
            [
                "docker",
                "cp",
                str(artifact.dump_path),
                f"{self.container_id}:/tmp/guiyi.dump",
            ]
        )
        self.command_runner(
            self.pg_restore_command(
                self.container_id,
                target_database,
                Path("/tmp/guiyi.dump"),
            )
        )
        version = self.command_runner(
            [
                "docker",
                "exec",
                self.container_id,
                "pg_restore",
                "--version",
            ]
        ).strip()
        port_text = self.command_runner(
            ["docker", "port", self.container_id, "5432/tcp"]
        ).strip()
        port = int(port_text.rsplit(":", 1)[-1])
        database_url = (
            "postgresql+psycopg://guiyi_restore:"
            f"{self.password}@127.0.0.1:{port}/{target_database}"
        )
        evidence = verify_restored_database_only(
            database_url,
            artifact,
        )
        evidence["pg_restore_version"] = version
        return evidence

    def cleanup(self) -> dict[str, bool]:
        container_removed = not self._container_candidate
        volume_removed = not self._volume_candidate
        if (
            self._container_candidate
            and self.container_id
            and self.container
            and self._ownership_token
        ):
            try:
                owned = self._inspect_container(self.container_id) == (
                    self.container_id,
                    self.container,
                    self._ownership_token,
                )
                if owned:
                    self.command_runner(
                        ["docker", "rm", "--force", self.container_id]
                    )
                    self._container_candidate = False
                    self._container_owned = False
                    container_removed = True
            except DatabaseOnlyDrillError:
                container_removed = False
        if (
            self._volume_candidate
            and self.volume
            and self._ownership_token
        ):
            try:
                owned = self._inspect_volume(self.volume) == (
                    self.volume,
                    self._ownership_token,
                )
                if owned:
                    self.command_runner(
                        ["docker", "volume", "rm", self.volume]
                    )
                    self._volume_candidate = False
                    self._volume_owned = False
                    volume_removed = True
            except DatabaseOnlyDrillError:
                volume_removed = False
        return {
            "container_removed": container_removed,
            "volume_removed": volume_removed,
        }

    def _inspect_container(
        self,
        identifier: str,
    ) -> tuple[str, str, str]:
        output = self.command_runner(
            [
                "docker",
                "inspect",
                "--format",
                (
                    '{{.Id}}\n{{.Name}}\n'
                    '{{ index .Config.Labels "guiyi.db-drill.id" }}'
                ),
                identifier,
            ]
        ).splitlines()
        if len(output) != 3:
            raise DatabaseOnlyDrillError(
                "isolated_container_identity_missing"
            )
        return (
            output[0].strip(),
            output[1].strip().removeprefix("/"),
            output[2].strip(),
        )

    def _inspect_volume(self, name: str) -> tuple[str, str]:
        output = self.command_runner(
            [
                "docker",
                "volume",
                "inspect",
                "--format",
                (
                    '{{.Name}}\n'
                    '{{ index .Labels "guiyi.db-drill.id" }}'
                ),
                name,
            ]
        ).splitlines()
        if len(output) != 2:
            raise DatabaseOnlyDrillError(
                "isolated_volume_identity_missing"
            )
        return output[0].strip(), output[1].strip()

    @staticmethod
    def _run(command: list[str]) -> str:
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            code = (
                exc.returncode
                if isinstance(exc, subprocess.CalledProcessError)
                else "unavailable"
            )
            raise DatabaseOnlyDrillError(
                f"isolated_runtime_command_failed:{code}"
            ) from exc


def verify_database_only_backup(
    root: Path,
) -> DatabaseOnlyBackupArtifact:
    requested = root.expanduser()
    if requested.is_symlink():
        raise DatabaseOnlyDrillError("backup_root_unavailable")
    resolved = requested.resolve(strict=False)
    if not resolved.is_dir():
        raise DatabaseOnlyDrillError("backup_root_unavailable")
    manifest_path = resolved / "backup_manifest.json"
    sidecar_path = resolved / "backup_manifest.sha256"
    _regular(manifest_path, "backup_manifest_missing")
    _regular(sidecar_path, "backup_manifest_checksum_missing")
    manifest_sha256 = _sha256(manifest_path)
    if (
        sidecar_path.read_text(encoding="utf-8").strip()
        != manifest_sha256
    ):
        raise DatabaseOnlyDrillError("backup_manifest_checksum_mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatabaseOnlyDrillError("backup_manifest_invalid") from exc
    database = manifest.get("database")
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("status") != "completed"
        or manifest.get("mode") != "database-only"
        or not isinstance(database, dict)
        or database.get("included") is not True
        or database.get("alembic_revision") != "20260721_0025"
        or not isinstance(database.get("table_counts"), dict)
    ):
        raise DatabaseOnlyDrillError("database_only_manifest_invalid")
    dump = database.get("dump")
    if not isinstance(dump, dict):
        raise DatabaseOnlyDrillError("database_dump_invalid")
    dump_path = _inside(
        resolved,
        str(dump.get("path") or ""),
        "database_dump_path_invalid",
    )
    _regular(dump_path, "database_dump_missing")
    if (
        dump_path.stat().st_size != int(dump.get("size", -1))
        or _sha256(dump_path) != dump.get("sha256")
    ):
        raise DatabaseOnlyDrillError("dump_checksum_mismatch")
    return DatabaseOnlyBackupArtifact(
        root=resolved,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        dump_path=dump_path,
    )


def execute_database_only_restore_drill(
    *,
    backup_root: Path,
    receipt_path: Path,
    target_database: str,
    runtime: DatabaseOnlyDrillRuntime,
) -> dict[str, Any]:
    if TARGET_DATABASE.fullmatch(target_database) is None:
        raise DatabaseOnlyDrillError("target_database_invalid")
    receipt = receipt_path.expanduser().resolve(strict=False)
    if receipt.exists() or receipt.is_symlink():
        raise DatabaseOnlyDrillError("drill_receipt_already_exists")
    artifact = verify_database_only_backup(backup_root)
    restore_error: Exception | None = None
    evidence: dict[str, Any] | None = None
    try:
        evidence = runtime.restore_and_verify(
            artifact,
            target_database=target_database,
        )
        _validate_restored_evidence(artifact, evidence)
    except Exception as exc:  # noqa: BLE001 - cleanup must still execute.
        restore_error = exc
    cleanup = runtime.cleanup()
    cleanup_complete = cleanup == {
        "container_removed": True,
        "volume_removed": True,
    }
    if not cleanup_complete:
        raise DatabaseOnlyDrillError("isolated_cleanup_failed") from (
            restore_error
        )
    if restore_error is not None:
        if isinstance(restore_error, DatabaseOnlyDrillError):
            raise restore_error
        raise DatabaseOnlyDrillError("isolated_restore_failed") from restore_error
    assert evidence is not None
    result = {
        "schema_version": 1,
        "status": "passed",
        "backup_root": str(artifact.root),
        "backup_manifest_sha256": artifact.manifest_sha256,
        "dump_sha256": artifact.manifest["database"]["dump"]["sha256"],
        "target_database": target_database,
        "alembic_revision": evidence["alembic_revision"],
        "table_counts": evidence["table_counts"],
        "report14": evidence["report14"],
        "transaction_read_only": True,
        "pg_restore_version": evidence["pg_restore_version"],
        "cleanup": cleanup,
        "cleanup_complete": True,
    }
    _write_create_only(receipt, result)
    return result


def _validate_restored_evidence(
    artifact: DatabaseOnlyBackupArtifact,
    evidence: dict[str, Any],
) -> None:
    database = artifact.manifest["database"]
    if (
        evidence.get("alembic_revision")
        != database.get("alembic_revision")
        or evidence.get("table_counts") != database.get("table_counts")
        or evidence.get("report14") != database.get("report14")
        or evidence.get("transaction_read_only") is not True
        or not str(evidence.get("pg_restore_version") or "").startswith(
            "pg_restore"
        )
    ):
        raise DatabaseOnlyDrillError(
            "isolated_restore_verification_failed"
        )


def verify_restored_database_only(
    database_url: str,
    artifact: DatabaseOnlyBackupArtifact,
) -> dict[str, Any]:
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    url = make_url(database_url)
    if (
        url.database is None
        or TARGET_DATABASE.fullmatch(url.database) is None
    ):
        raise DatabaseOnlyDrillError(
            "target_database_identity_invalid"
        )
    engine = create_engine(database_url, pool_pre_ping=True)
    expected = artifact.manifest["database"]
    try:
        with Session(engine, autoflush=False) as session:
            session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            )
            session.execute(text("SET TRANSACTION READ ONLY"))
            revision = str(
                session.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                or ""
            )
            tables = sorted(
                inspect(session.connection()).get_table_names()
            )
            required = set(expected["table_counts"])
            if any(
                re.fullmatch(r"[a-z_][a-z0-9_]*", name) is None
                for name in required
            ):
                raise DatabaseOnlyDrillError(
                    "restored_table_name_invalid"
                )
            if required != set(tables):
                raise DatabaseOnlyDrillError(
                    "restored_core_tables_missing"
                )
            counts = {
                name: int(
                    session.scalar(
                        text(f'SELECT count(*) FROM "{name}"')
                    )
                    or 0
                )
                for name in sorted(required)
            }
            report14 = {
                "md5": session.scalar(
                    text(
                        "SELECT md5(to_jsonb(t)::text) "
                        "FROM backtest_reports t WHERE id=14"
                    )
                ),
                "trades": int(
                    session.scalar(
                        text(
                            "SELECT count(*) FROM backtest_trades "
                            "WHERE report_id=14"
                        )
                    )
                    or 0
                ),
                "orders": int(
                    session.scalar(
                        text(
                            "SELECT count(*) FROM backtest_orders "
                            "WHERE report_id=14"
                        )
                    )
                    or 0
                ),
            }
            session.rollback()
            return {
                "alembic_revision": revision,
                "table_counts": counts,
                "report14": report14,
                "transaction_read_only": True,
            }
    finally:
        engine.dispose()


def _write_create_only(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise DatabaseOnlyDrillError(
            "drill_receipt_already_exists"
        ) from exc
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_private_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _inside(root: Path, relative: str, error: str) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or ".." in relative_path.parts
    ):
        raise DatabaseOnlyDrillError(error)
    candidate = root / relative_path
    try:
        candidate.resolve(strict=False).relative_to(
            root.resolve(strict=False)
        )
    except ValueError as exc:
        raise DatabaseOnlyDrillError(error) from exc
    return candidate


def _regular(path: Path, error: str) -> None:
    try:
        information = path.lstat()
    except FileNotFoundError as exc:
        raise DatabaseOnlyDrillError(error) from exc
    if not stat.S_ISREG(information.st_mode):
        raise DatabaseOnlyDrillError(error)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
