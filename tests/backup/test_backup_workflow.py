from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

import scripts.backup.core as backup_core
from scripts.backup.core import BackupDependencies, BackupError, DatabaseEvidence, execute_backup
from scripts.backup.create import main


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    files = {
        "data/parquet/canonical/jm.parquet": b"parquet",
        "data/manifests/jm.csv": b"manifest",
        "data/processed/jm.json": b"processed",
        "data/reports/report.json": b"report",
        "configs/data_profiles/live_observation_v1.json": b"{}",
        "configs/oos/jm_v1b_report14_frozen.json": b"{}",
        "data/universe/products.txt": b"jm\n",
        ".env.example": b"DATABASE_URL=redacted\n",
        "configs/env/worktree.env.example": b"SAFE=true\n",
        "deploy/launchd/api.plist.template": b"template",
        "data/raw/jm.raw": b"raw",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


class FakeDatabaseProvider:
    def __init__(self, *, report_md5: str = "ae807ef77f7d9a4ce3067996558b57e8") -> None:
        self.calls = 0
        self.report_md5 = report_md5

    def create_dump(self, destination: Path, *, tool_mode: str, container: str) -> DatabaseEvidence:
        self.calls += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"custom-format-dump")
        return DatabaseEvidence(
            identity={"driver": "postgresql", "host": "127.0.0.1", "port": 5432, "database": "guiyi_quant"},
            alembic_revision="20260721_0025",
            table_counts={"backtest_reports": 14, "market_data_files": 100},
            report14={"md5": self.report_md5, "trades": 155, "orders": 239},
            active_profile_bindings=[
                {
                    "binding_id": 7,
                    "profile_database_id": 3,
                    "profile_id": "live_observation_v1",
                    "profile_config_path": "configs/data_profiles/live_observation_v1.json",
                    "instrument_symbol": "jm",
                    "contract_code": "jm2609",
                    "period": "1m",
                    "data_version": "jm-test-v1",
                    "market_data_file_id": 11,
                    "file_path": "data/parquet/canonical/jm.parquet",
                    "checksum": hashlib.sha256(b"parquet").hexdigest(),
                    "file_size_bytes": len(b"parquet"),
                }
            ],
            tool={"mode": tool_mode, "version": "PostgreSQL 16"},
        )


def _dependencies(tmp_path: Path, provider: FakeDatabaseProvider | None = None) -> BackupDependencies:
    source = tmp_path / "source"
    output = tmp_path / "backup-device"
    return BackupDependencies(
        now=lambda: datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        token_hex=lambda _n: "deadbeef",
        git_commit=lambda _root: "90e968a3b7af15058288d773e4971f06e1180a83",
        git_tree_state_hash=lambda _root: "a" * 64,
        device_id=lambda path: 1 if path.resolve() == source.resolve() else 2,
        mount_point=lambda path: output.resolve(),
        available_bytes=lambda _path: 10**12,
        database_provider=provider,
    )


def test_default_is_dry_run_with_zero_writes_or_database_calls(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    provider = FakeDatabaseProvider()

    exit_code = main(
        ["--full", "--source-root", str(source), "--output-root", str(output)],
        dependencies=_dependencies(tmp_path, provider),
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "dry-run"
    assert payload["would_write"] is False
    assert payload["would_connect_database"] is False
    assert provider.calls == 0
    assert list(output.iterdir()) == []


def test_data_backup_is_create_only_and_raw_is_opt_in(tmp_path: Path) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    deps = _dependencies(tmp_path)

    result = execute_backup(
        mode="data-only",
        source_root=source,
        output_root=output,
        backup_id="backup-001",
        retention_class="daily",
        include_raw=False,
        execute=True,
        tool_mode="auto",
        postgres_container="guiyi-postgres",
        dependencies=deps,
    )

    backup = output / "backup-001"
    assert result["status"] == "completed"
    assert backup.is_dir()
    assert not (backup / "files/data/raw/jm.raw").exists()
    manifest = json.loads((backup / "backup_manifest.json").read_text())
    assert manifest["schema_version"] == "guiyi_local_backup_v1"
    assert manifest["database"]["included"] is False
    assert "database" in manifest["excluded_categories"]
    assert "raw" in manifest["excluded_categories"]
    assert "data/raw" in manifest["excluded_categories"]
    manifest_hash = hashlib.sha256((backup / "backup_manifest.json").read_bytes()).hexdigest()
    assert (backup / "backup_manifest.sha256").read_text().strip() == manifest_hash
    inventory = [json.loads(line) for line in (backup / "inventories/files.jsonl").read_text().splitlines()]
    assert all("sha256" in row and "relative_path" in row for row in inventory)

    with pytest.raises(BackupError, match="backup_already_exists"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="backup-001",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=deps,
        )


def test_full_backup_binds_database_and_active_profile_files(tmp_path: Path) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    provider = FakeDatabaseProvider()

    execute_backup(
        mode="full",
        source_root=source,
        output_root=output,
        backup_id="backup-full",
        retention_class="milestone",
        include_raw=True,
        execute=True,
        tool_mode="docker",
        postgres_container="guiyi-postgres",
        dependencies=_dependencies(tmp_path, provider),
    )

    manifest = json.loads((output / "backup-full/backup_manifest.json").read_text())
    assert provider.calls == 1
    assert manifest["database"]["included"] is True
    assert manifest["database"]["alembic_revision"] == "20260721_0025"
    assert manifest["database"]["report14"] == {
        "md5": "ae807ef77f7d9a4ce3067996558b57e8",
        "orders": 239,
        "trades": 155,
    }
    assert manifest["database"]["dump"]["sha256"]
    assert manifest["database"]["active_profile_binding_count"] == 1
    assert manifest["database"]["active_profile_bindings"][0]["profile_id"] == "live_observation_v1"
    assert "database" in manifest["included_categories"]
    assert (output / "backup-full/files/data/raw/jm.raw").is_file()


def test_report14_or_profile_drift_fails_and_cleans_only_staging(tmp_path: Path) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    sentinel = output / "existing-backup"
    sentinel.mkdir()
    (sentinel / "keep").write_text("keep")
    provider = FakeDatabaseProvider(report_md5="wrong")

    with pytest.raises(BackupError, match="report14_invariant_mismatch"):
        execute_backup(
            mode="full",
            source_root=source,
            output_root=output,
            backup_id="bad-backup",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path, provider),
        )

    assert (sentinel / "keep").read_text() == "keep"
    assert not (output / "bad-backup").exists()
    assert not list(output.glob(".bad-backup.partial-*"))

    missing_profile = FakeDatabaseProvider()
    original = missing_profile.create_dump

    def missing(destination: Path, *, tool_mode: str, container: str) -> DatabaseEvidence:
        evidence = original(destination, tool_mode=tool_mode, container=container)
        binding = {**evidence.active_profile_bindings[0], "file_path": "data/parquet/canonical/missing.parquet"}
        return replace(evidence, active_profile_bindings=[binding])

    missing_profile.create_dump = missing  # type: ignore[method-assign]
    with pytest.raises(BackupError, match="active_profile_file_not_backed_up"):
        execute_backup(
            mode="full",
            source_root=source,
            output_root=output,
            backup_id="missing-profile",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path, missing_profile),
        )


def test_symlink_and_same_device_fail_closed(tmp_path: Path) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    (source / "data/reports/link").symlink_to(source / "data/reports/report.json")

    with pytest.raises(BackupError, match="source_entry_not_regular"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="symlink",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path),
        )

    (source / "data/reports/link").unlink()
    deps = replace(_dependencies(tmp_path), device_id=lambda _path: 1)
    with pytest.raises(BackupError, match="output_device_must_differ"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="same-device",
            retention_class="daily",
            include_raw=False,
            execute=False,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=deps,
        )


def test_cli_rejects_invalid_mode_and_raw_boundary(tmp_path: Path) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    assert main(["--source-root", str(source), "--output-root", str(output)], dependencies=_dependencies(tmp_path)) == 2
    assert main(
        ["--database-only", "--include-raw", "--source-root", str(source), "--output-root", str(output)],
        dependencies=_dependencies(tmp_path, FakeDatabaseProvider()),
    ) == 2


def test_source_mutation_aborts_and_removes_only_partial_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    sentinel = output / "existing-backup"
    sentinel.mkdir()
    (sentinel / "keep").write_text("keep")
    original_copyfile = backup_core.shutil.copyfile

    def copy_then_mutate(source_path: str | Path, destination: str | Path) -> str:
        result = original_copyfile(source_path, destination)
        path = Path(source_path)
        if path.name == "jm.parquet":
            path.write_bytes(path.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(backup_core.shutil, "copyfile", copy_then_mutate)

    with pytest.raises(BackupError, match="source_changed_during_backup"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="mutating-source",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path),
        )

    assert (sentinel / "keep").read_text() == "keep"
    assert not (output / "mutating-source").exists()
    assert not list(output.glob(".mutating-source.partial-*"))


def test_missing_output_mount_fails_closed_before_any_write(tmp_path: Path) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    deps = replace(_dependencies(tmp_path), mount_point=lambda _path: tmp_path / "missing-mount")

    with pytest.raises(BackupError, match="output_mount_unavailable"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="missing-mount",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=deps,
        )

    assert list(output.iterdir()) == []

    root_mount_deps = replace(_dependencies(tmp_path), mount_point=lambda _path: Path("/"))
    with pytest.raises(BackupError, match="output_mount_not_external"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="root-mount",
            retention_class="daily",
            include_raw=False,
            execute=False,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=root_mount_deps,
        )


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"market_data_file_id": None}, "active_profile_binding_unresolved"),
        ({"file_path": "../data/parquet/canonical/jm.parquet"}, "active_profile_file_outside_source_root"),
        ({"file_path": "data/reports/report.json", "checksum": None, "file_size_bytes": None}, "active_profile_file_not_canonical"),
        ({"checksum": "0" * 64}, "active_profile_checksum_mismatch"),
        ({"profile_config_path": "../configs/data_profiles/live_observation_v1.json"}, "active_profile_config_outside_source_root"),
        ({"profile_config_path": ".env.example"}, "active_profile_config_category_invalid"),
    ],
)
def test_active_profile_binding_drift_fails_closed(
    tmp_path: Path,
    changes: dict[str, object],
    error: str,
) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    provider = FakeDatabaseProvider()
    original = provider.create_dump

    def changed(destination: Path, *, tool_mode: str, container: str) -> DatabaseEvidence:
        evidence = original(destination, tool_mode=tool_mode, container=container)
        binding = {**evidence.active_profile_bindings[0], **changes}
        return replace(evidence, active_profile_bindings=[binding])

    provider.create_dump = changed  # type: ignore[method-assign]
    with pytest.raises(BackupError, match=error):
        execute_backup(
            mode="full",
            source_root=source,
            output_root=output,
            backup_id=f"binding-{error}",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path, provider),
        )

    assert list(output.iterdir()) == []


def test_full_backup_requires_at_least_one_active_profile_binding(tmp_path: Path) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    provider = FakeDatabaseProvider()
    original = provider.create_dump

    def no_bindings(destination: Path, *, tool_mode: str, container: str) -> DatabaseEvidence:
        evidence = original(destination, tool_mode=tool_mode, container=container)
        return replace(evidence, active_profile_bindings=[])

    provider.create_dump = no_bindings  # type: ignore[method-assign]
    with pytest.raises(BackupError, match="active_profile_bindings_missing"):
        execute_backup(
            mode="full",
            source_root=source,
            output_root=output,
            backup_id="no-active-bindings",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path, provider),
        )

    assert list(output.iterdir()) == []


def test_dry_run_validates_backup_id_and_execute_respects_exclusive_lock(tmp_path: Path) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()

    with pytest.raises(BackupError, match="backup_id_invalid"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="invalid/id",
            retention_class="daily",
            include_raw=False,
            execute=False,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path),
        )

    lock = output / ".locked-backup.lock"
    lock.write_text("owned-by-another-process")
    with pytest.raises(BackupError, match="backup_id_locked"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="locked-backup",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path),
        )

    assert lock.read_text() == "owned-by-another-process"


def test_existing_staging_is_preserved_when_backup_aborts_before_creating_it(tmp_path: Path) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    staging = output / f".foreign-staging.partial-{os.getpid()}-deadbeef"
    staging.mkdir()
    (staging / "keep").write_text("foreign staging")

    with pytest.raises(BackupError, match="backup_staging_already_exists"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="foreign-staging",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path),
        )

    assert (staging / "keep").read_text() == "foreign staging"
    assert not (output / ".foreign-staging.lock").exists()


def test_release_backup_id_preserves_lock_replaced_after_acquire(tmp_path: Path) -> None:
    descriptor, lock_path = backup_core._claim_backup_id(tmp_path, "replaced-lock")  # noqa: SLF001
    previous_lock = tmp_path / "previous-lock"
    lock_path.rename(previous_lock)
    lock_path.write_text("owned-by-replacement")

    backup_core._release_backup_id(descriptor, lock_path)  # noqa: SLF001

    assert lock_path.read_text() == "owned-by-replacement"
    previous_lock.unlink()


def test_cleanup_preserves_staging_replaced_after_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    original_verify = backup_core._verify_staged_backup
    replaced: dict[str, Path] = {}

    def replace_staging_then_abort(staging: Path, manifest: object) -> None:
        del manifest
        owned_staging = output / "owned-staging-after-replacement"
        staging.rename(owned_staging)
        staging.mkdir()
        foreign_marker = staging / "foreign-marker"
        foreign_marker.write_text("foreign staging")
        replaced["foreign"] = foreign_marker
        raise BackupError("injected_staging_abort")

    monkeypatch.setattr(backup_core, "_verify_staged_backup", replace_staging_then_abort)
    with pytest.raises(BackupError, match="injected_staging_abort"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="staging-replacement",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path),
        )

    assert replaced["foreign"].read_text() == "foreign staging"
    monkeypatch.setattr(backup_core, "_verify_staged_backup", original_verify)


def test_release_backup_id_preserves_lock_replaced_after_identity_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor, lock_path = backup_core._claim_backup_id(tmp_path, "replacement-window")  # noqa: SLF001
    previous_lock = tmp_path / "owned-lock-before-replacement"
    original_stat = Path.stat
    replaced = False

    def stat_then_replace(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        nonlocal replaced
        result = original_stat(path, follow_symlinks=follow_symlinks)
        if path == lock_path and not replaced:
            lock_path.rename(previous_lock)
            lock_path.write_text("foreign replacement")
            replaced = True
        return result

    monkeypatch.setattr(Path, "stat", stat_then_replace)
    backup_core._release_backup_id(descriptor, lock_path)  # noqa: SLF001

    assert replaced is True
    assert lock_path.read_text() == "foreign replacement"
    assert previous_lock.exists()


def test_promotion_preserves_empty_destination_created_after_final_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    final_dir = output / "promotion-replacement"
    original_path_exists = backup_core._path_exists
    final_checks = 0
    foreign_identity: tuple[int, int] | None = None

    def create_foreign_destination_after_check(path: Path) -> bool:
        nonlocal final_checks, foreign_identity
        exists = original_path_exists(path)
        if path == final_dir:
            final_checks += 1
            if final_checks == 2:
                assert exists is False
                final_dir.mkdir()
                info = final_dir.stat()
                foreign_identity = (info.st_dev, info.st_ino)
        return exists

    monkeypatch.setattr(backup_core, "_path_exists", create_foreign_destination_after_check)
    with pytest.raises(BackupError, match="backup_already_exists"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="promotion-replacement",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path),
        )

    assert foreign_identity is not None
    current = final_dir.stat()
    assert (current.st_dev, current.st_ino) == foreign_identity


def test_rename_failure_cleans_read_only_staging_and_releases_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    rename_calls = 0

    def fail_final_rename(path: Path, target: Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 1:
            raise OSError("injected rename failure")
        path.rename(target)

    monkeypatch.setattr(backup_core, "_rename_no_replace", fail_final_rename, raising=False)
    with pytest.raises(OSError, match="injected rename failure"):
        execute_backup(
            mode="data-only",
            source_root=source,
            output_root=output,
            backup_id="rename-failure",
            retention_class="daily",
            include_raw=False,
            execute=True,
            tool_mode="auto",
            postgres_container="guiyi-postgres",
            dependencies=_dependencies(tmp_path),
        )

    assert list(output.iterdir()) == []


def test_host_pg_dump_uses_custom_snapshot_args_and_keeps_password_out_of_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "guiyi.dump"
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_which(name: str) -> str | None:
        return "/usr/local/bin/pg_dump" if name == "pg_dump" else None

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        if "--version" in command:
            return SimpleNamespace(stdout="pg_dump (PostgreSQL) 16.3\n")
        file_argument = next(value for value in command if value.startswith("--file="))
        Path(file_argument.removeprefix("--file=")).write_bytes(b"fake-custom-dump")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(backup_core.shutil, "which", fake_which)
    monkeypatch.setattr(backup_core.subprocess, "run", fake_run)
    url = make_url("postgresql+psycopg://guiyi:top-secret@127.0.0.1:5432/guiyi_quant")

    mode, version = backup_core._run_pg_dump(  # noqa: SLF001 - intentional external-tool contract test.
        destination,
        snapshot="00000003-0000001B-1",
        tool_mode="host",
        container="guiyi-postgres",
        url=url,
    )

    dump_command, dump_options = calls[0]
    assert mode == "host"
    assert version == "pg_dump (PostgreSQL) 16.3"
    assert "--format=custom" in dump_command
    assert "--no-owner" in dump_command
    assert "--no-acl" in dump_command
    assert "--snapshot=00000003-0000001B-1" in dump_command
    assert "top-secret" not in json.dumps(dump_command)
    assert dump_options["env"]["PGPASSWORD"] == "top-secret"  # type: ignore[index]
    assert destination.read_bytes() == b"fake-custom-dump"


def test_missing_pg_dump_and_unexpected_provider_errors_are_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = tmp_path / "missing.dump"
    monkeypatch.setattr(backup_core.shutil, "which", lambda _name: None)
    url = make_url("postgresql+psycopg://guiyi:top-secret@127.0.0.1:5432/guiyi_quant")
    with pytest.raises(BackupError, match="pg_dump_unavailable"):
        backup_core._run_pg_dump(  # noqa: SLF001 - intentional external-tool failure test.
            destination,
            snapshot="snapshot",
            tool_mode="host",
            container="guiyi-postgres",
            url=url,
        )

    class SecretFailingProvider:
        def create_dump(self, destination: Path, *, tool_mode: str, container: str) -> DatabaseEvidence:
            raise RuntimeError("top-secret")

    source = _source_root(tmp_path)
    output = tmp_path / "backup-device"
    output.mkdir()
    deps = replace(_dependencies(tmp_path), database_provider=SecretFailingProvider())
    exit_code = main(
        [
            "--database-only",
            "--source-root",
            str(source),
            "--output-root",
            str(output),
            "--backup-id",
            "redacted-failure",
            "--execute",
        ],
        dependencies=deps,
    )

    output_text = capsys.readouterr().out
    assert exit_code == 2
    assert "top-secret" not in output_text
    assert json.loads(output_text) == {"error": "backup_failed", "error_type": "RuntimeError", "status": "blocked"}
    assert not list(output.iterdir())
