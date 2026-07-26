from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.backup.database_only_drill import (
    DatabaseOnlyDrillError,
    DockerDatabaseOnlyDrillRuntime,
    execute_database_only_restore_drill,
    verify_database_only_backup,
)


def _write_backup(root: Path) -> Path:
    dump = root / "database" / "guiyi_quant.dump"
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"postgres-dump")
    manifest = {
        "schema_version": "guiyi_local_backup_v1",
        "status": "completed",
        "mode": "database-only",
        "database": {
            "included": True,
            "alembic_revision": "20260721_0025",
            "table_counts": {
                "profile_active_bindings": 5124,
                "after_market_scheduler_checkpoints": 0,
            },
            "report14": {
                "md5": "ae807ef77f7d9a4ce3067996558b57e8",
                "trades": 155,
                "orders": 239,
            },
            "dump": {
                "path": "database/guiyi_quant.dump",
                "size": len(b"postgres-dump"),
                "sha256": hashlib.sha256(b"postgres-dump").hexdigest(),
            },
        },
    }
    manifest_path = root / "backup_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    (root / "backup_manifest.sha256").write_text(
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        encoding="utf-8",
    )
    return root


class _Runtime:
    def __init__(self, *, cleanup_complete: bool = True) -> None:
        self.cleanup_complete = cleanup_complete

    def restore_and_verify(self, artifact, *, target_database):
        return {
            "alembic_revision": artifact.manifest["database"][
                "alembic_revision"
            ],
            "table_counts": artifact.manifest["database"]["table_counts"],
            "report14": artifact.manifest["database"]["report14"],
            "transaction_read_only": True,
            "pg_restore_version": "pg_restore 16",
        }

    def cleanup(self):
        return {
            "container_removed": self.cleanup_complete,
            "volume_removed": self.cleanup_complete,
        }


def test_database_only_artifact_is_hash_and_mode_bound(tmp_path: Path) -> None:
    artifact = verify_database_only_backup(_write_backup(tmp_path / "backup"))

    assert artifact.manifest["mode"] == "database-only"
    assert artifact.dump_path.read_bytes() == b"postgres-dump"
    assert len(artifact.manifest_sha256) == 64


def test_database_only_artifact_rejects_dump_drift(tmp_path: Path) -> None:
    root = _write_backup(tmp_path / "backup")
    (root / "database" / "guiyi_quant.dump").write_bytes(b"drift")

    with pytest.raises(DatabaseOnlyDrillError, match="dump_checksum_mismatch"):
        verify_database_only_backup(root)


def test_isolated_drill_requires_complete_cleanup_and_create_only_receipt(
    tmp_path: Path,
) -> None:
    root = _write_backup(tmp_path / "backup")
    receipt = tmp_path / "evidence" / "isolated_restore_receipt.json"
    result = execute_database_only_restore_drill(
        backup_root=root,
        receipt_path=receipt,
        target_database="guiyi_restore_s607_recovery",
        runtime=_Runtime(),
    )

    assert result["status"] == "passed"
    assert result["cleanup_complete"] is True
    assert json.loads(receipt.read_text(encoding="utf-8")) == result
    with pytest.raises(
        DatabaseOnlyDrillError,
        match="drill_receipt_already_exists",
    ):
        execute_database_only_restore_drill(
            backup_root=root,
            receipt_path=receipt,
            target_database="guiyi_restore_s607_recovery",
            runtime=_Runtime(),
        )


def test_isolated_drill_fails_when_owned_resources_are_not_removed(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        DatabaseOnlyDrillError,
        match="isolated_cleanup_failed",
    ):
        execute_database_only_restore_drill(
            backup_root=_write_backup(tmp_path / "backup"),
            receipt_path=tmp_path / "receipt.json",
            target_database="guiyi_restore_s607_recovery",
            runtime=_Runtime(cleanup_complete=False),
        )


class _DockerRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.container_id = "container-id"
        self.container_name = ""
        self.volume_name = ""
        self.token = ""
        self.env_mode: int | None = None
        self.env_content = ""

    def __call__(self, command: list[str]) -> str:
        self.commands.append(command)
        if command[:4] == ["docker", "volume", "ls", "--quiet"]:
            return ""
        if command[:3] == ["docker", "volume", "create"]:
            self.token = command[4].split("=", 1)[1]
            self.volume_name = command[-1]
            return f"{self.volume_name}\n"
        if command[:3] == ["docker", "volume", "inspect"]:
            return f"{self.volume_name}\n{self.token}\n"
        if command[:3] == ["docker", "run", "--detach"]:
            name_index = command.index("--name") + 1
            self.container_name = command[name_index]
            env_path = Path(command[command.index("--env-file") + 1])
            self.env_mode = env_path.stat().st_mode & 0o777
            self.env_content = env_path.read_text(encoding="utf-8")
            return f"{self.container_id}\n"
        if command[:2] == ["docker", "inspect"]:
            return (
                f"{self.container_id}\n/{self.container_name}\n"
                f"{self.token}\n"
            )
        if command[:3] == ["docker", "exec", self.container_id]:
            if "pg_restore" in command and "--version" in command:
                return "pg_restore (PostgreSQL) 16.4\n"
            return ""
        if command[:2] == ["docker", "cp"]:
            return ""
        if command[:2] == ["docker", "port"]:
            return "127.0.0.1:54321\n"
        if command[:3] == ["docker", "rm", "--force"]:
            return ""
        if command[:3] == ["docker", "volume", "rm"]:
            return ""
        raise AssertionError(command)


def test_docker_runtime_uses_private_env_and_passwordless_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = verify_database_only_backup(
        _write_backup(tmp_path / "backup")
    )
    runner = _DockerRunner()
    runtime = DockerDatabaseOnlyDrillRuntime(
        command_runner=runner,
        password="top-secret",
    )

    monkeypatch.setattr(
        "scripts.backup.database_only_drill.verify_restored_database_only",
        lambda database_url, current_artifact: {
            "alembic_revision": current_artifact.manifest["database"][
                "alembic_revision"
            ],
            "table_counts": current_artifact.manifest["database"][
                "table_counts"
            ],
            "report14": current_artifact.manifest["database"]["report14"],
            "transaction_read_only": True,
        },
    )
    evidence = runtime.restore_and_verify(
        artifact,
        target_database="guiyi_restore_s607_recovery",
    )
    cleanup = runtime.cleanup()

    rendered = json.dumps(runner.commands)
    assert evidence["pg_restore_version"].startswith("pg_restore")
    assert cleanup == {
        "container_removed": True,
        "volume_removed": True,
    }
    assert runner.env_mode == 0o600
    assert "top-secret" in runner.env_content
    assert "top-secret" not in rendered
    assert "--single-transaction" in rendered
    assert ["docker", "rm", "--force", runner.container_id] in runner.commands
    assert ["docker", "volume", "rm", runner.volume_name] in runner.commands
