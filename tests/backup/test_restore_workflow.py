from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import stat
from types import SimpleNamespace

import pytest

from scripts.backup.artifact import verify_backup_artifact
from scripts.restore.core import DockerPostgresRuntime, RestoreDependencies, RestoreError, _database_snapshot, _enforce_read_only, _session_unchanged, _validate_evidence, _verify_profile_binding_and_rebind, execute_isolated_restore
from scripts.restore.isolated import main


def _artifact(tmp_path: Path) -> Path:
    root = tmp_path / "backup-device" / "backup-full"
    files = {
        "data/parquet/canonical/jm.parquet": b"parquet",
        "configs/data_profiles/live_observation_v1.json": b"{}",
    }
    rows = []
    for relative, content in files.items():
        path = root / "files" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        rows.append({"category": "canonical_parquet" if relative.endswith("parquet") else "data_profiles", "relative_path": relative, "size": len(content), "mtime_ns": 1, "sha256": hashlib.sha256(content).hexdigest()})
    inventory = b"".join((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode() for row in rows)
    (root / "inventories").mkdir()
    (root / "inventories/files.jsonl").write_bytes(inventory)
    dump = root / "database/guiyi_quant.dump"
    dump.parent.mkdir()
    dump.write_bytes(b"dump")
    report14 = {"md5": "ae807ef77f7d9a4ce3067996558b57e8", "trades": 155, "orders": 239}
    manifest = {
        "schema_version": "guiyi_local_backup_v1", "backup_id": "backup-full", "status": "completed", "mode": "full",
        "source": {"root": "/production/guiyi"},
        "inventory": {"path": "inventories/files.jsonl", "file_count": 2, "total_size": 9, "sha256": hashlib.sha256(inventory).hexdigest()},
        "database": {"included": True, "alembic_revision": "20260721_0025", "table_counts": {"backtest_reports": 14}, "report14": report14, "dump": {"path": "database/guiyi_quant.dump", "size": 4, "sha256": hashlib.sha256(b"dump").hexdigest()}, "active_profile_binding_count": 1, "active_profile_file_count": 1, "active_profile_bindings": [{"binding_id": 1, "profile_database_id": 1, "profile_id": "live_observation_v1", "profile_config_relative_path": "configs/data_profiles/live_observation_v1.json", "profile_config_sha256": hashlib.sha256(b"{}").hexdigest(), "instrument_symbol": "jm", "contract_code": "JM2609", "period": "1m", "data_version": "v1", "market_data_file_id": 7, "relative_path": "data/parquet/canonical/jm.parquet", "sha256": hashlib.sha256(b"parquet").hexdigest(), "size": 7}]},
    }
    payload = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    (root / "backup_manifest.json").write_bytes(payload)
    (root / "backup_manifest.sha256").write_text(hashlib.sha256(payload).hexdigest() + "\n")
    return root


class FakeRuntime:
    def __init__(self, *, fail: bool = False, cleanup_results: list[dict[str, bool]] | None = None, on_restore=None) -> None:
        self.fail = fail
        self.cleanup_results = cleanup_results or [{"container_removed": True, "volume_removed": True}]
        self.on_restore = on_restore
        self.cleaned = 0

    def restore_and_verify(self, artifact, *, target_database: str, target_root: Path):
        if self.on_restore is not None:
            self.on_restore()
        if self.fail:
            raise RuntimeError("secret-password")
        report = artifact.manifest["database"]["report14"]
        return {"alembic_revision": "20260721_0025", "table_counts": {"backtest_reports": 14}, "report14": report, "transaction_read_only": True, "database_unchanged": True, "profile_verified": True, "pg_restore_version": "pg_restore 16", "consumer_methods": ["GET"] * 5, "consumer_smoke": [{"consumer": name, "method": "GET", "status": "passed"} for name in ("market", "backtest", "signal_latest", "signal_events", "review")]}

    def cleanup(self):
        self.cleaned += 1
        return self.cleanup_results[min(self.cleaned - 1, len(self.cleanup_results) - 1)]


def _rewrite_manifest(root: Path, mutate) -> None:
    path = root / "backup_manifest.json"
    manifest = json.loads(path.read_text())
    mutate(manifest)
    payload = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    path.write_bytes(payload)
    (root / "backup_manifest.sha256").write_text(hashlib.sha256(payload).hexdigest() + "\n")


def _add_inventory_file(root: Path, relative: str, content: bytes) -> None:
    path = root / "files" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    inventory_path = root / "inventories/files.jsonl"
    rows = [json.loads(line) for line in inventory_path.read_text().splitlines()]
    rows.append({"category": "versioned_reports", "relative_path": relative, "size": len(content), "mtime_ns": 1, "sha256": hashlib.sha256(content).hexdigest()})
    payload = b"".join((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode() for row in rows)
    inventory_path.write_bytes(payload)
    _rewrite_manifest(root, lambda manifest: manifest["inventory"].update(file_count=len(rows), total_size=sum(row["size"] for row in rows), sha256=hashlib.sha256(payload).hexdigest()))


def test_restore_requires_explicit_isolated_confirmation(tmp_path: Path) -> None:
    with pytest.raises(RestoreError, match="isolated_restore_confirmation_required"):
        execute_isolated_restore(
            backup_root=tmp_path / "backup",
            target_database="guiyi_restore_test",
            target_data_root=tmp_path / "restore",
            isolated=False,
            confirm_isolated_restore=False,
            dependencies=RestoreDependencies.for_tests(production_database="guiyi_quant"),
        )


def test_full_artifact_restores_create_only_receipt(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated" / "root"
    target.parent.mkdir()
    runtime = FakeRuntime()
    result = execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_test", target_data_root=target, isolated=True, confirm_isolated_restore=True, dependencies=RestoreDependencies.for_tests(production_database="guiyi_quant", production_roots=(tmp_path / "production",), runtime=runtime))
    assert result["status"] == "completed"
    receipt = json.loads((target / "isolated_restore_receipt.json").read_text())
    assert receipt["schema_version"] == "guiyi_isolated_restore_v1"
    assert receipt["tool"]["postgres_image"] == "postgres:16"
    assert receipt["artifact_verification"]["all_declared_files_verified"] is True
    assert receipt["boundaries"]["production_database_touched"] is False
    assert runtime.cleaned == 1
    assert (target / "data/parquet/canonical/jm.parquet").read_bytes() == b"parquet"
    receipt_bytes = (target / "isolated_restore_receipt.json").read_bytes()
    assert (target / "isolated_restore_receipt.sha256").read_text().strip() == hashlib.sha256(receipt_bytes).hexdigest()
    assert stat.S_IMODE(target.stat().st_mode) == 0o555
    assert stat.S_IMODE((target / "data/parquet/canonical/jm.parquet").stat().st_mode) == 0o444


def test_preexisting_empty_target_is_claimed_without_overwriting_content(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.mkdir(parents=True)
    runtime = FakeRuntime()
    result = execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_test", target_data_root=target, isolated=True, confirm_isolated_restore=True, dependencies=RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime))
    assert result["status"] == "completed"
    assert (target / "isolated_restore_receipt.json").is_file()


def test_tamper_and_protected_targets_fail_before_runtime(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    runtime = FakeRuntime()
    deps = RestoreDependencies.for_tests(production_database="guiyi_quant", production_roots=(tmp_path / "production",), runtime=runtime)
    with pytest.raises(RestoreError, match="target_database_invalid"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_quant", target_data_root=tmp_path / "target", isolated=True, confirm_isolated_restore=True, dependencies=deps)
    matching = RestoreDependencies.for_tests(production_database="guiyi_restore_production", runtime=runtime)
    with pytest.raises(RestoreError, match="target_database_matches_production"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_production", target_data_root=tmp_path / "target", isolated=True, confirm_isolated_restore=True, dependencies=matching)
    with pytest.raises(RestoreError, match="target_data_root_overlaps_protected_root"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_x", target_data_root=tmp_path / "production/restore", isolated=True, confirm_isolated_restore=True, dependencies=deps)
    target = tmp_path / "nonempty"
    target.mkdir()
    (target / "keep").write_text("keep")
    with pytest.raises(RestoreError, match="target_data_root_not_empty"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_x", target_data_root=target, isolated=True, confirm_isolated_restore=True, dependencies=deps)
    (backup / "files/data/parquet/canonical/jm.parquet").write_bytes(b"tampered")
    with pytest.raises(RestoreError, match="backup_file_checksum_mismatch"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_x", target_data_root=tmp_path / "clean", isolated=True, confirm_isolated_restore=True, dependencies=deps)
    assert runtime.cleaned == 0


def test_database_name_is_ascii_and_target_symlink_is_rejected(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    runtime = FakeRuntime()
    deps = RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime)
    with pytest.raises(RestoreError, match="target_database_invalid"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_测试", target_data_root=tmp_path / "target", isolated=True, confirm_isolated_restore=True, dependencies=deps)
    symlink_target = tmp_path / "symlink-target"
    symlink_target.mkdir()
    link = tmp_path / "restore-link"
    link.symlink_to(symlink_target, target_is_directory=True)
    with pytest.raises(RestoreError, match="target_data_root_not_empty"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_x", target_data_root=link, isolated=True, confirm_isolated_restore=True, dependencies=deps)
    assert runtime.cleaned == 0


def test_manifest_source_root_is_always_protected(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    source_root = tmp_path / "recorded-production-source"
    source_root.mkdir()
    _rewrite_manifest(backup, lambda manifest: manifest["source"].update(root=str(source_root)))
    runtime = FakeRuntime()
    with pytest.raises(RestoreError, match="target_data_root_overlaps_protected_root"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_x", target_data_root=source_root / "restore", isolated=True, confirm_isolated_restore=True, dependencies=RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime))
    assert runtime.cleaned == 0


def test_full_contract_inventory_dump_and_traversal_drift_fail_closed(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    deps = RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime)

    non_full = _artifact(tmp_path / "non-full")
    _rewrite_manifest(non_full, lambda manifest: manifest.update(mode="data-only"))
    with pytest.raises(RestoreError, match="full_backup_required"):
        execute_isolated_restore(backup_root=non_full, target_database="guiyi_restore_x", target_data_root=tmp_path / "non-full-target", isolated=True, confirm_isolated_restore=True, dependencies=deps)

    inventory_drift = _artifact(tmp_path / "inventory-drift")
    (inventory_drift / "inventories/files.jsonl").write_text("{}\n")
    with pytest.raises(RestoreError, match="inventory_checksum_mismatch"):
        execute_isolated_restore(backup_root=inventory_drift, target_database="guiyi_restore_x", target_data_root=tmp_path / "inventory-target", isolated=True, confirm_isolated_restore=True, dependencies=deps)

    dump_drift = _artifact(tmp_path / "dump-drift")
    (dump_drift / "database/guiyi_quant.dump").write_bytes(b"changed")
    with pytest.raises(RestoreError, match="database_dump_checksum_mismatch"):
        execute_isolated_restore(backup_root=dump_drift, target_database="guiyi_restore_x", target_data_root=tmp_path / "dump-target", isolated=True, confirm_isolated_restore=True, dependencies=deps)

    traversal = _artifact(tmp_path / "traversal")
    inventory_path = traversal / "inventories/files.jsonl"
    rows = [json.loads(line) for line in inventory_path.read_text().splitlines()]
    rows[0]["relative_path"] = "../escape"
    payload = b"".join((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode() for row in rows)
    inventory_path.write_bytes(payload)
    _rewrite_manifest(traversal, lambda manifest: manifest["inventory"].update(sha256=hashlib.sha256(payload).hexdigest()))
    with pytest.raises(RestoreError, match="inventory_path_invalid"):
        execute_isolated_restore(backup_root=traversal, target_database="guiyi_restore_x", target_data_root=tmp_path / "traversal-target", isolated=True, confirm_isolated_restore=True, dependencies=deps)
    assert runtime.cleaned == 0


def test_missing_extra_symlink_and_report_invariant_fail_closed(tmp_path: Path) -> None:
    deps = RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=FakeRuntime())

    missing = _artifact(tmp_path / "missing")
    (missing / "files/data/parquet/canonical/jm.parquet").unlink()
    with pytest.raises(RestoreError, match="backup_file_missing"):
        execute_isolated_restore(backup_root=missing, target_database="guiyi_restore_x", target_data_root=tmp_path / "missing-target", isolated=True, confirm_isolated_restore=True, dependencies=deps)

    extra = _artifact(tmp_path / "extra")
    (extra / "unexpected.txt").write_text("unexpected")
    with pytest.raises(RestoreError, match="backup_extra_file_rejected"):
        execute_isolated_restore(backup_root=extra, target_database="guiyi_restore_x", target_data_root=tmp_path / "extra-target", isolated=True, confirm_isolated_restore=True, dependencies=deps)

    special = _artifact(tmp_path / "special")
    os.mkfifo(special / "unexpected.fifo")
    with pytest.raises(RestoreError, match="backup_special_entry_rejected"):
        execute_isolated_restore(backup_root=special, target_database="guiyi_restore_x", target_data_root=tmp_path / "special-target", isolated=True, confirm_isolated_restore=True, dependencies=deps)

    symlink = _artifact(tmp_path / "symlink")
    canonical = symlink / "files/data/parquet/canonical/jm.parquet"
    canonical.unlink()
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"parquet")
    canonical.symlink_to(outside)
    with pytest.raises(RestoreError, match="inventory_path_invalid"):
        execute_isolated_restore(backup_root=symlink, target_database="guiyi_restore_x", target_data_root=tmp_path / "symlink-target", isolated=True, confirm_isolated_restore=True, dependencies=deps)

    report = _artifact(tmp_path / "report")
    _rewrite_manifest(report, lambda manifest: manifest["database"]["report14"].update(trades=154))
    with pytest.raises(RestoreError, match="report14_invariant_mismatch"):
        execute_isolated_restore(backup_root=report, target_database="guiyi_restore_x", target_data_root=tmp_path / "report-target", isolated=True, confirm_isolated_restore=True, dependencies=deps)


def test_backup_root_symlink_is_rejected_before_runtime(tmp_path: Path) -> None:
    backup = _artifact(tmp_path / "real")
    link = tmp_path / "backup-link"
    link.symlink_to(backup, target_is_directory=True)
    runtime = FakeRuntime()
    with pytest.raises(RestoreError, match="backup_root_unavailable"):
        execute_isolated_restore(backup_root=link, target_database="guiyi_restore_x", target_data_root=tmp_path / "isolated", isolated=True, confirm_isolated_restore=True, dependencies=RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime))
    assert runtime.cleaned == 0


def test_incomplete_runtime_cleanup_is_retried_and_no_receipt_is_published(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated" / "root"
    target.parent.mkdir()
    runtime = FakeRuntime(cleanup_results=[{"container_removed": False, "volume_removed": True}, {"container_removed": True, "volume_removed": True}])
    deps = RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime)
    with pytest.raises(RestoreError, match="isolated_runtime_cleanup_failed"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_x", target_data_root=target, isolated=True, confirm_isolated_restore=True, dependencies=deps)
    assert runtime.cleaned == 2
    assert not target.exists()


def test_receipt_collision_is_create_only_and_restored_root_is_removed(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    _add_inventory_file(backup, "isolated_restore_receipt.json", b"do-not-overwrite")
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    runtime = FakeRuntime()
    with pytest.raises(RestoreError, match="restore_receipt_already_exists"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_x", target_data_root=target, isolated=True, confirm_isolated_restore=True, dependencies=RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime))
    assert runtime.cleaned == 1
    assert not target.exists()


def test_target_created_during_restore_is_never_overwritten_or_removed(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    runtime = FakeRuntime(on_restore=lambda: target.mkdir())
    with pytest.raises(RestoreError, match="target_root_changed_during_restore"):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_x", target_data_root=target, isolated=True, confirm_isolated_restore=True, dependencies=RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime))
    assert runtime.cleaned == 1
    assert target.is_dir()
    assert not any(target.iterdir())


def test_runtime_failure_cleans_only_owned_target_and_cli_redacts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated" / "root"
    target.parent.mkdir()
    runtime = FakeRuntime(fail=True)
    deps = RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime)
    assert main(["--backup-root", str(backup), "--isolated", "--target-database", "guiyi_restore_x", "--target-data-root", str(target), "--confirm-isolated-restore"], dependencies=deps) == 2
    assert "secret-password" not in capsys.readouterr().out
    assert not target.exists()
    assert runtime.cleaned == 1


def test_docker_pg_restore_command_never_contains_password(tmp_path: Path) -> None:
    runtime = DockerPostgresRuntime(password="top-secret")
    rendered = json.dumps(runtime.pg_restore_command("restore-container", "guiyi_restore_x", Path("/tmp/dump")))
    assert "--exit-on-error" in rendered and "--single-transaction" in rendered
    assert "top-secret" not in rendered


def test_profile_and_canonical_paths_are_rebound_only_to_isolated_files(tmp_path: Path) -> None:
    artifact = verify_backup_artifact(_artifact(tmp_path))
    binding = artifact.manifest["database"]["active_profile_bindings"][0]
    source_root = Path(artifact.manifest["source"]["root"])
    target_root = tmp_path / "isolated"
    canonical = target_root / binding["relative_path"]
    config = target_root / binding["profile_config_relative_path"]
    canonical.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    canonical.write_bytes(b"parquet")
    config.write_bytes(b"{}")
    market_file = SimpleNamespace(id=7, instrument_symbol="jm", contract_code="JM2609", period="1m", data_version="v1", file_size_bytes=7, checksum=binding["sha256"], data_role="primary", quality_status="passed", file_path=binding["relative_path"])
    profile_binding = SimpleNamespace(id=1, profile_id="live_observation_v1", instrument_symbol="jm", contract_code="JM2609", period="1m", data_version="v1", market_data_file_id=7, binding_status="active")
    profile = SimpleNamespace(id=1, profile_id="live_observation_v1", config_path=binding["profile_config_relative_path"])
    _verify_profile_binding_and_rebind(market_file=market_file, profile_binding=profile_binding, profile=profile, binding=binding, source_root=source_root, target_root=target_root, set_value=setattr)
    assert market_file.file_path == str(canonical.resolve())
    assert profile.config_path == str(config.resolve())

    escaped = dict(binding, relative_path="../outside.parquet")
    with pytest.raises(RestoreError, match="restored_profile_path_invalid"):
        _verify_profile_binding_and_rebind(market_file=market_file, profile_binding=profile_binding, profile=profile, binding=escaped, source_root=source_root, target_root=target_root, set_value=setattr)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("transaction_read_only", False, "consumer_smoke_not_read_only"),
        ("consumer_methods", ["GET", "GET", "POST", "GET", "GET"], "consumer_smoke_not_read_only"),
        ("database_unchanged", False, "isolated_restore_verification_failed"),
        ("profile_verified", False, "isolated_restore_verification_failed"),
    ],
)
def test_evidence_gate_requires_get_only_read_only_and_unchanged_database(tmp_path: Path, field: str, value, error: str) -> None:
    artifact = verify_backup_artifact(_artifact(tmp_path))
    evidence = FakeRuntime().restore_and_verify(artifact, target_database="guiyi_restore_x", target_root=tmp_path)
    evidence[field] = value
    with pytest.raises(RestoreError, match=error):
        _validate_evidence(artifact, evidence)


def test_database_verifier_enforces_read_only_and_hashes_content() -> None:
    class MappingResult:
        def mappings(self):
            return self

        def one(self):
            return {"row_count": 2, "content_md5": "abc"}

    class SessionDouble:
        new: set = set()
        dirty: set = set()
        deleted: set = set()

        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, statement):
            self.statements.append(str(statement))
            return MappingResult()

    session = SessionDouble()
    _enforce_read_only(session)
    snapshot = _database_snapshot(session, ["backtest_reports"])
    assert session.statements[0] == "SET TRANSACTION READ ONLY"
    assert "to_jsonb(t)" in session.statements[1]
    assert "ORDER BY row_hash" in session.statements[1]
    assert snapshot == {"backtest_reports": {"row_count": 2, "content_md5": "abc"}}
    assert _session_unchanged(session, snapshot, dict(snapshot)) is True
    session.dirty = {"changed"}
    assert _session_unchanged(session, snapshot, dict(snapshot)) is False


class ScriptedDockerRunner:
    def __init__(self, fail_stage: str | None = None) -> None:
        self.fail_stage = fail_stage
        self.commands: list[list[str]] = []
        self.env_mode: int | None = None
        self.env_content = ""
        self.inspect_calls = 0

    def __call__(self, command: list[str]) -> str:
        self.commands.append(command)
        if command[:3] == ["docker", "volume", "ls"]:
            if self.fail_stage == "existing-volume":
                return command[-1].removeprefix("name=^").removesuffix("$") + "\n"
            return ""
        if command[:3] == ["docker", "volume", "create"]:
            return command[-1] + "\n"
        if command[:3] == ["docker", "volume", "inspect"]:
            self.inspect_calls += 1
            if self.fail_stage == "inspect-once" and self.inspect_calls == 1:
                raise RestoreError("isolated_runtime_command_failed:1")
            if self.fail_stage == "foreign-label":
                return "foreign\n"
            return command[-1].removeprefix("guiyi_restore_") + "\n"
        if command[:2] == ["docker", "run"]:
            env_path = Path(command[command.index("--env-file") + 1])
            self.env_mode = stat.S_IMODE(env_path.stat().st_mode)
            self.env_content = env_path.read_text()
            if self.fail_stage == "run":
                raise RestoreError("isolated_runtime_command_failed:1")
            return "container-id\n"
        if command[:3] == ["docker", "exec", command[2]] and "pg_isready" in command:
            return "ready\n"
        if command[:2] == ["docker", "cp"]:
            return ""
        if "pg_restore" in command and "--exit-on-error" in command:
            if self.fail_stage == "restore":
                raise RestoreError("isolated_runtime_command_failed:2")
            return ""
        if "pg_restore" in command and "--version" in command:
            return "pg_restore (PostgreSQL) 16.4\n"
        if command[:2] == ["docker", "port"]:
            return "127.0.0.1:54321\n"
        return ""


@pytest.mark.parametrize("fail_stage", ["run", "restore", "consumer"])
def test_docker_stage_failure_cleans_only_resources_created_by_this_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_stage: str) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    runner = ScriptedDockerRunner(fail_stage)
    runtime = DockerPostgresRuntime(command_runner=runner, password="top-secret")

    def verify(_url, artifact, _target):
        if fail_stage == "consumer":
            raise RestoreError("consumer_smoke_failed:market")
        return FakeRuntime().restore_and_verify(artifact, target_database="guiyi_restore_x", target_root=target)

    monkeypatch.setattr("scripts.restore.core.verify_restored_database", verify)
    with pytest.raises(RestoreError):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_x", target_data_root=target, isolated=True, confirm_isolated_restore=True, dependencies=RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime))
    rendered = json.dumps(runner.commands)
    assert "top-secret" not in rendered
    assert runner.env_mode == 0o600
    assert "top-secret" in runner.env_content
    assert ["docker", "volume", "rm", runtime.volume] in runner.commands
    assert (["docker", "rm", "--force", runtime.container] in runner.commands) is (fail_stage != "run")
    assert not target.exists()


@pytest.mark.parametrize("fail_stage,volume_removed", [("existing-volume", False), ("inspect-once", True), ("foreign-label", False)])
def test_volume_ownership_failure_never_leaks_or_removes_a_preexisting_volume(tmp_path: Path, fail_stage: str, volume_removed: bool) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    runner = ScriptedDockerRunner(fail_stage)
    runtime = DockerPostgresRuntime(command_runner=runner)
    with pytest.raises(RestoreError):
        execute_isolated_restore(backup_root=backup, target_database="guiyi_restore_x", target_data_root=target, isolated=True, confirm_isolated_restore=True, dependencies=RestoreDependencies.for_tests(production_database="guiyi_quant", runtime=runtime))
    assert (["docker", "volume", "rm", runtime.volume] in runner.commands) is volume_removed
    assert not target.exists()
