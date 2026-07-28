from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import stat
import subprocess
from types import SimpleNamespace

import pytest

from scripts.restore import core as restore_core
from scripts.restore import isolated as restore_isolated
from scripts.backup.artifact import verify_backup_artifact
from scripts.restore.core import DockerPostgresRuntime, RestoreDependencies, RestoreError, _database_snapshot, _enforce_read_only, _session_unchanged, _validate_evidence, _verify_profile_binding_and_rebind, execute_isolated_restore
from scripts.restore.isolated import default_dependencies, main


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
        "database": {"included": True, "identity": {"database": "guiyi_quant"}, "alembic_revision": "20260721_0025", "table_counts": {"backtest_reports": 14}, "report14": report14, "dump": {"path": "database/guiyi_quant.dump", "size": 4, "sha256": hashlib.sha256(b"dump").hexdigest()}, "active_profile_binding_count": 1, "active_profile_file_count": 1, "active_profile_bindings": [{"binding_id": 1, "profile_database_id": 1, "profile_id": "live_observation_v1", "profile_config_relative_path": "configs/data_profiles/live_observation_v1.json", "profile_config_sha256": hashlib.sha256(b"{}").hexdigest(), "instrument_symbol": "jm", "contract_code": "JM2609", "period": "1m", "data_version": "v1", "market_data_file_id": 7, "relative_path": "data/parquet/canonical/jm.parquet", "sha256": hashlib.sha256(b"parquet").hexdigest(), "size": 7}]},
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


def test_receipt_sidecar_failure_preserves_foreign_receipt_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "restore-root"
    root.mkdir()
    original_write = restore_core._write_create_only
    receipt = root / "isolated_restore_receipt.json"

    def replace_receipt_before_sidecar(path: Path, payload: bytes):
        if path.name == "isolated_restore_receipt.sha256":
            receipt.unlink()
            receipt.write_text("foreign replacement")
            raise RestoreError("sidecar_failed")
        return original_write(path, payload)

    monkeypatch.setattr(
        restore_core,
        "_write_create_only",
        replace_receipt_before_sidecar,
    )

    with pytest.raises(RestoreError, match="restore_receipt_cleanup_failed"):
        restore_core._write_receipt(root, {"schema_version": "test"})

    assert receipt.read_text() == "foreign replacement"


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


def test_runtime_cleanup_false_surfaces_incomplete_cleanup_with_original_cause(
    tmp_path: Path,
) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    runtime = FakeRuntime(
        fail=True,
        cleanup_results=[{"container_removed": False, "volume_removed": True}],
    )

    with pytest.raises(RestoreError, match="isolated_restore_cleanup_failed") as caught:
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_x",
            target_data_root=target,
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="guiyi_quant",
                runtime=runtime,
            ),
        )

    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == "secret-password"
    assert runtime.cleaned == 1
    assert not target.exists()


def test_runtime_cleanup_exception_surfaces_stable_incomplete_cleanup_error(
    tmp_path: Path,
) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()

    class CleanupRaisesRuntime(FakeRuntime):
        def cleanup(self):
            self.cleaned += 1
            raise RuntimeError("cleanup-secret")

    runtime = CleanupRaisesRuntime(fail=True)
    with pytest.raises(RestoreError, match="isolated_restore_cleanup_failed") as caught:
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_x",
            target_data_root=target,
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="guiyi_quant",
                runtime=runtime,
            ),
        )

    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == "secret-password"
    assert runtime.cleaned == 1
    assert not target.exists()


def test_cli_reports_incomplete_cleanup_without_exposing_original_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    runtime = FakeRuntime(
        fail=True,
        cleanup_results=[{"container_removed": False, "volume_removed": True}],
    )

    assert main(
        [
            "--backup-root",
            str(backup),
            "--isolated",
            "--target-database",
            "guiyi_restore_x",
            "--target-data-root",
            str(target),
            "--confirm-isolated-restore",
        ],
        dependencies=RestoreDependencies.for_tests(
            production_database="guiyi_quant",
            runtime=runtime,
        ),
    ) == 2
    output = json.loads(capsys.readouterr().out)

    assert output == {
        "status": "blocked",
        "error": "isolated_restore_cleanup_failed",
    }
    assert "secret-password" not in json.dumps(output)


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

    _verify_profile_binding_and_rebind(
        market_file=market_file,
        profile_binding=profile_binding,
        profile=profile,
        binding=binding,
        source_root=source_root,
        target_root=target_root,
        set_value=setattr,
    )
    assert market_file.file_path == str(canonical.resolve())

    second_market_file = SimpleNamespace(
        id=7,
        instrument_symbol="jm",
        contract_code="JM2609",
        period="1m",
        data_version="v1",
        file_size_bytes=7,
        checksum=binding["sha256"],
        data_role="primary",
        quality_status="passed",
        file_path=binding["relative_path"],
    )
    _verify_profile_binding_and_rebind(
        market_file=second_market_file,
        profile_binding=profile_binding,
        profile=profile,
        binding=binding,
        source_root=source_root,
        target_root=target_root,
        set_value=setattr,
    )
    assert second_market_file.file_path == str(canonical.resolve())
    assert profile.config_path == str(config.resolve())

    escaped = dict(binding, relative_path="../outside.parquet")
    with pytest.raises(RestoreError, match="restored_profile_path_invalid"):
        _verify_profile_binding_and_rebind(market_file=market_file, profile_binding=profile_binding, profile=profile, binding=escaped, source_root=source_root, target_root=target_root, set_value=setattr)


def test_external_registered_profile_path_rebinds_to_isolated_copy(
    tmp_path: Path,
) -> None:
    artifact = verify_backup_artifact(_artifact(tmp_path))
    original = artifact.manifest["database"]["active_profile_bindings"][0]
    binding = {
        **original,
        "relative_path": (
            "external/active_profile_files/root-0/parquet/JM2609.parquet"
        ),
        "registered_file_path": (
            "/Volumes/扩展盘/GuiyiApprovals/s607/retry-service/"
            "parquet/JM2609.parquet"
        ),
    }
    source_root = Path(artifact.manifest["source"]["root"])
    target_root = tmp_path / "isolated"
    canonical = target_root / binding["relative_path"]
    config = target_root / binding["profile_config_relative_path"]
    canonical.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    canonical.write_bytes(b"parquet")
    config.write_bytes(b"{}")
    market_file = SimpleNamespace(
        id=7,
        instrument_symbol="jm",
        contract_code="JM2609",
        period="1m",
        data_version="v1",
        file_size_bytes=7,
        checksum=binding["sha256"],
        data_role="primary",
        quality_status="passed",
        file_path=binding["registered_file_path"],
    )
    profile_binding = SimpleNamespace(
        id=1,
        profile_id="live_observation_v1",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="1m",
        data_version="v1",
        market_data_file_id=7,
        binding_status="active",
    )
    profile = SimpleNamespace(
        id=1,
        profile_id="live_observation_v1",
        config_path=binding["profile_config_relative_path"],
    )

    _verify_profile_binding_and_rebind(
        market_file=market_file,
        profile_binding=profile_binding,
        profile=profile,
        binding=binding,
        source_root=source_root,
        target_root=target_root,
        set_value=setattr,
    )

    assert market_file.file_path == str(canonical.resolve())


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
        self.volume_inspect_calls = 0
        self.container_inspect_calls = 0
        self.container_id = "container-id"
        self.container_name = ""
        self.ownership_token = ""

    def __call__(self, command: list[str]) -> str:
        self.commands.append(command)
        if command[:3] == ["docker", "volume", "ls"]:
            if self.fail_stage == "existing-volume":
                return command[-1].removeprefix("name=^").removesuffix("$") + "\n"
            return ""
        if command[:3] == ["docker", "volume", "create"]:
            return command[-1] + "\n"
        if command[:3] == ["docker", "volume", "inspect"]:
            self.volume_inspect_calls += 1
            if self.fail_stage == "inspect-once" and self.volume_inspect_calls == 1:
                raise RestoreError("isolated_runtime_command_failed:1")
            token = command[-1].removeprefix("guiyi_restore_")
            label = (
                "foreign"
                if self.fail_stage == "foreign-label"
                or (self.fail_stage == "volume-label-drift" and self.volume_inspect_calls > 1)
                else token
            )
            if ".Name" in command[-2]:
                return f"{command[-1]}\n{label}\n"
            return f"{label}\n"
        if command[:2] == ["docker", "run"]:
            env_path = Path(command[command.index("--env-file") + 1])
            self.env_mode = stat.S_IMODE(env_path.stat().st_mode)
            self.env_content = env_path.read_text()
            self.container_name = command[command.index("--name") + 1]
            self.ownership_token = command[command.index("--label") + 1].split("=", 1)[1]
            if self.fail_stage == "run":
                raise RestoreError("isolated_runtime_command_failed:1")
            return f"{self.container_id}\n"
        if command[:2] == ["docker", "inspect"]:
            self.container_inspect_calls += 1
            if (
                self.fail_stage
                in {"container-inspect-once", "container-inspect-once-rm-fails"}
                and self.container_inspect_calls == 1
            ) or (
                self.fail_stage == "container-name-reused"
                and self.container_inspect_calls > 1
            ):
                raise RestoreError("isolated_runtime_command_failed:1")
            identity = (
                "foreign-id"
                if self.fail_stage == "container-id-mismatch"
                or (
                    self.fail_stage == "container-id-mismatch-once"
                    and self.container_inspect_calls == 1
                )
                else self.container_id
            )
            label = (
                "foreign"
                if self.fail_stage == "container-label-mismatch"
                or (
                    self.fail_stage == "container-label-mismatch-once"
                    and self.container_inspect_calls == 1
                )
                or (
                    self.fail_stage == "container-label-drift"
                    and self.container_inspect_calls > 1
                )
                else self.ownership_token
            )
            return f"{identity}\n/{self.container_name}\n{label}\n"
        if command[:3] == ["docker", "rm", "--force"]:
            if self.fail_stage == "container-inspect-once-rm-fails":
                raise RestoreError("isolated_runtime_command_failed:1")
            return ""
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
    assert (
        ["docker", "rm", "--force", runtime.container_id] in runner.commands
    ) is (fail_stage != "run")
    assert ["docker", "rm", "--force", runtime.container] not in runner.commands
    copy_commands = [command for command in runner.commands if command[:2] == ["docker", "cp"]]
    if fail_stage == "run":
        assert copy_commands == []
    else:
        assert len(copy_commands) == 1
        assert Path(copy_commands[0][2]) != backup / "database/guiyi_quant.dump"
        assert copy_commands[0][3] == f"{runner.container_id}:/tmp/guiyi.dump"
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


def test_dump_replaced_after_verification_is_not_consumed_by_runtime(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    original_dump = backup / "database/guiyi_quant.dump"
    consumed: list[bytes] = []
    consumed_modes: list[int] = []
    private_directory_modes: list[int] = []

    class ReplacingRuntime(FakeRuntime):
        def restore_and_verify(self, artifact, *, target_database: str, target_root: Path):
            original_dump.rename(backup / "database/verified-dump-moved-away")
            original_dump.write_bytes(b"foreign replacement")
            consumed.append(artifact.dump_path.read_bytes())
            consumed_modes.append(stat.S_IMODE(artifact.dump_path.stat().st_mode))
            private_directory_modes.append(
                stat.S_IMODE(artifact.dump_path.parent.stat().st_mode)
            )
            return super().restore_and_verify(
                artifact,
                target_database=target_database,
                target_root=target_root,
            )

    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    result = execute_isolated_restore(
        backup_root=backup,
        target_database="guiyi_restore_x",
        target_data_root=target,
        isolated=True,
        confirm_isolated_restore=True,
        dependencies=RestoreDependencies.for_tests(
            production_database="guiyi_quant",
            runtime=ReplacingRuntime(),
        ),
    )

    assert result["status"] == "completed"
    assert consumed == [b"dump"]
    assert consumed_modes == [0o600]
    assert private_directory_modes == [0o700]


def test_staging_replacement_on_failure_is_never_chmoded_or_removed(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    foreign_marker: Path | None = None

    class ReplacingRuntime(FakeRuntime):
        def restore_and_verify(self, artifact, *, target_database: str, target_root: Path):
            nonlocal foreign_marker
            target_root.rename(target_root.parent / "owned-staging-moved-away")
            target_root.mkdir()
            foreign_marker = target_root / "foreign-marker"
            foreign_marker.write_text("foreign staging")
            raise RestoreError("injected_restore_failure")

    with pytest.raises(RestoreError, match="isolated_restore_cleanup_failed") as caught:
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_x",
            target_data_root=target,
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="guiyi_quant",
                runtime=ReplacingRuntime(),
            ),
        )

    assert isinstance(caught.value.__cause__, RestoreError)
    assert str(caught.value.__cause__) == "injected_restore_failure"
    assert foreign_marker is not None
    assert foreign_marker.read_text() == "foreign staging"


def test_foreign_staging_symlink_is_never_followed_chmoded_or_removed(
    tmp_path: Path,
) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    foreign = tmp_path / "foreign-staging-target"
    foreign.mkdir(mode=0o700)
    marker = foreign / "marker"
    marker.write_text("foreign symlink target")
    replacement_link: Path | None = None

    class ReplacingRuntime(FakeRuntime):
        def restore_and_verify(self, artifact, *, target_database: str, target_root: Path):
            nonlocal replacement_link
            target_root.rename(target_root.parent / "owned-staging-moved-away")
            target_root.symlink_to(foreign, target_is_directory=True)
            replacement_link = target_root
            raise RestoreError("injected_restore_failure")

    with pytest.raises(RestoreError, match="isolated_restore_cleanup_failed") as caught:
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_x",
            target_data_root=target,
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="guiyi_quant",
                runtime=ReplacingRuntime(),
            ),
        )

    assert isinstance(caught.value.__cause__, RestoreError)
    assert str(caught.value.__cause__) == "injected_restore_failure"
    assert replacement_link is not None and replacement_link.is_symlink()
    assert marker.read_text() == "foreign symlink target"
    assert stat.S_IMODE(foreign.stat().st_mode) == 0o700


def test_preexisting_empty_target_is_reserved_and_foreign_replacement_is_preserved(
    tmp_path: Path,
) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.mkdir(parents=True)
    foreign_marker: Path | None = None

    class ReplacingRuntime(FakeRuntime):
        def restore_and_verify(self, artifact, *, target_database: str, target_root: Path):
            nonlocal foreign_marker
            if target.exists():
                target.rename(target.parent / "target-moved-by-test-hook")
            target.mkdir()
            foreign_marker = target / "foreign-marker"
            foreign_marker.write_text("foreign target")
            raise RestoreError("injected_restore_failure")

    with pytest.raises(RestoreError, match="isolated_restore_cleanup_failed") as caught:
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_x",
            target_data_root=target,
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="guiyi_quant",
                runtime=ReplacingRuntime(),
            ),
        )

    assert isinstance(caught.value.__cause__, RestoreError)
    assert str(caught.value.__cause__) == "injected_restore_failure"
    reservations = list(target.parent.glob(".root.restore-target-reservation-*"))
    assert foreign_marker is not None
    assert foreign_marker.read_text() == "foreign target"
    assert len(reservations) == 1
    assert reservations[0].is_dir()


def test_foreign_target_replacement_after_promotion_surfaces_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    owned_target = target.parent / "owned-target-moved-away"
    foreign_marker = target / "foreign-marker"
    original_path_identity = restore_core._path_identity
    replaced = False

    def replace_promoted_target(path: Path):
        nonlocal replaced
        if path == target and target.exists() and not replaced:
            target.rename(owned_target)
            target.mkdir()
            foreign_marker.write_text("foreign target")
            replaced = True
            raise RestoreError("injected_post_promotion_failure")
        return original_path_identity(path)

    monkeypatch.setattr(restore_core, "_path_identity", replace_promoted_target)
    with pytest.raises(RestoreError, match="isolated_restore_cleanup_failed") as caught:
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_x",
            target_data_root=target,
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="guiyi_quant",
                runtime=FakeRuntime(),
            ),
        )

    assert isinstance(caught.value.__cause__, RestoreError)
    assert str(caught.value.__cause__) == "injected_post_promotion_failure"
    assert replaced is True
    assert foreign_marker.read_text() == "foreign target"
    assert owned_target.is_dir()


def test_preexisting_empty_target_reservation_is_restored_after_safe_failure(
    tmp_path: Path,
) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.mkdir(parents=True)
    original_identity = (target.stat().st_dev, target.stat().st_ino)
    target_visible_during_restore: list[bool] = []

    class FailingRuntime(FakeRuntime):
        def restore_and_verify(self, artifact, *, target_database: str, target_root: Path):
            target_visible_during_restore.append(target.exists() or target.is_symlink())
            raise RestoreError("injected_restore_failure")

    with pytest.raises(RestoreError, match="injected_restore_failure"):
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_x",
            target_data_root=target,
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="guiyi_quant",
                runtime=FailingRuntime(),
            ),
        )

    restored = target.stat()
    assert target_visible_during_restore == [False]
    assert (restored.st_dev, restored.st_ino) == original_identity
    assert list(target.parent.glob(".root.restore-target-reservation-*")) == []


def test_lock_release_uses_atomic_quarantine_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    lock = target.parent / ".root.restore.lock"
    previous_lock = target.parent / "owned-lock-before-replacement"
    original_stat = Path.stat
    replaced = False

    def stat_then_replace(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        nonlocal replaced
        result = original_stat(path, follow_symlinks=follow_symlinks)
        if path == lock and not replaced:
            lock.rename(previous_lock)
            lock.write_text("foreign replacement")
            replaced = True
        return result

    monkeypatch.setattr(Path, "stat", stat_then_replace)
    execute_isolated_restore(
        backup_root=backup,
        target_database="guiyi_restore_x",
        target_data_root=target,
        isolated=True,
        confirm_isolated_restore=True,
        dependencies=RestoreDependencies.for_tests(
            production_database="guiyi_quant",
            runtime=FakeRuntime(),
        ),
    )

    assert replaced is True
    assert lock.read_text() == "foreign replacement"
    assert previous_lock.exists()


def test_read_only_conversion_happens_before_atomic_target_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    converted_roots: list[Path] = []
    original_make_read_only = restore_core._make_read_only

    def record_read_only_root(root: Path) -> None:
        converted_roots.append(root)
        original_make_read_only(root)

    monkeypatch.setattr(restore_core, "_make_read_only", record_read_only_root)
    result = execute_isolated_restore(
        backup_root=backup,
        target_database="guiyi_restore_x",
        target_data_root=target,
        isolated=True,
        confirm_isolated_restore=True,
        dependencies=RestoreDependencies.for_tests(
            production_database="guiyi_quant",
            runtime=FakeRuntime(),
        ),
    )

    assert result["status"] == "completed"
    assert len(converted_roots) == 1
    assert converted_roots[0] != target
    assert ".backup-restore-staging-quarantine-" in converted_roots[0].name


def test_target_reservation_converts_w7_rename_error_to_stable_restore_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir()

    def fail_rename(_source: Path, _destination: Path) -> None:
        raise restore_core.BackupError("w7-internal-error")

    monkeypatch.setattr(restore_core, "_rename_no_replace", fail_rename)
    with pytest.raises(RestoreError, match="target_reservation_failed"):
        restore_core._reserve_empty_target(target, token_hex=lambda _size: "token")


def test_target_reservation_mismatch_rollback_converts_w7_rename_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    identities = iter((object(), object()))
    rename_calls = 0

    def scripted_rename(source: Path, destination: Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 1:
            source.rename(destination)
            return
        raise restore_core.BackupError("w7-internal-error")

    monkeypatch.setattr(restore_core, "_path_identity", lambda _path: next(identities))
    monkeypatch.setattr(restore_core, "_rename_no_replace", scripted_rename)
    with pytest.raises(
        RestoreError,
        match="target_ownership_lost_reservation_preserved",
    ):
        restore_core._reserve_empty_target(target, token_hex=lambda _size: "token")


def test_target_reservation_restore_converts_w7_rename_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reservation = tmp_path / "reservation"
    reservation.mkdir()
    identity = restore_core._path_identity(reservation)
    target = tmp_path / "target"

    def fail_rename(_source: Path, _destination: Path) -> None:
        raise restore_core.BackupError("w7-internal-error")

    monkeypatch.setattr(restore_core, "_rename_no_replace", fail_rename)
    with pytest.raises(RestoreError, match="target_reservation_restore_failed"):
        restore_core._restore_target_reservation(reservation, identity, target)


def test_target_promotion_converts_w7_rename_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()

    def fail_promotion(_source: Path, destination: Path) -> None:
        if destination == target:
            raise restore_core.BackupError("w7-internal-error")
        raise AssertionError("unexpected rename")

    monkeypatch.setattr(restore_core, "_rename_no_replace", fail_promotion)
    with pytest.raises(RestoreError, match="target_promotion_failed"):
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_x",
            target_data_root=target,
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="guiyi_quant",
                runtime=FakeRuntime(),
            ),
        )


def test_production_database_identity_is_required_before_restore(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    target = tmp_path / "isolated/root"
    target.parent.mkdir()
    runtime = FakeRuntime()

    with pytest.raises(RestoreError, match="production_database_identity_unavailable"):
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_x",
            target_data_root=target,
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="",
                runtime=runtime,
            ),
        )

    assert runtime.cleaned == 0


@pytest.mark.parametrize("database_identity", [None, "", 42])
def test_artifact_database_identity_is_required_and_must_be_a_nonempty_string(
    tmp_path: Path,
    database_identity,
) -> None:
    backup = _artifact(tmp_path)

    def mutate(manifest: dict) -> None:
        if database_identity is None:
            manifest["database"].pop("identity")
        else:
            manifest["database"]["identity"]["database"] = database_identity

    _rewrite_manifest(backup, mutate)
    runtime = FakeRuntime()
    with pytest.raises(RestoreError, match="artifact_database_identity_unavailable"):
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_x",
            target_data_root=tmp_path / "target",
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="guiyi_quant",
                runtime=runtime,
            ),
        )

    assert runtime.cleaned == 0


def test_target_database_must_not_match_artifact_database_identity(tmp_path: Path) -> None:
    backup = _artifact(tmp_path)
    _rewrite_manifest(
        backup,
        lambda manifest: manifest["database"]["identity"].update(
            database="guiyi_restore_artifact"
        ),
    )
    runtime = FakeRuntime()

    with pytest.raises(RestoreError, match="target_database_matches_artifact"):
        execute_isolated_restore(
            backup_root=backup,
            target_database="guiyi_restore_artifact",
            target_data_root=tmp_path / "target",
            isolated=True,
            confirm_isolated_restore=True,
            dependencies=RestoreDependencies.for_tests(
                production_database="guiyi_quant",
                runtime=runtime,
            ),
        )

    assert runtime.cleaned == 0


def test_default_dependencies_protect_runtime_data_and_all_git_worktree_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime-root"
    data_root = tmp_path / "explicit-data-root"
    runtime_root.mkdir()
    data_root.mkdir()
    monkeypatch.setenv("GUIYI_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setenv("GUIYI_DATA_ROOT", str(data_root))
    dependencies = default_dependencies()
    protected = {path.expanduser().resolve(strict=False) for path in dependencies.production_roots}
    worktree_output = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    worktrees = {
        Path(line.removeprefix("worktree ")).resolve(strict=False)
        for line in worktree_output.splitlines()
        if line.startswith("worktree ")
    }

    assert runtime_root.resolve() in protected
    assert data_root.resolve() in protected
    assert worktrees
    assert worktrees <= protected

    safe_dependencies = RestoreDependencies(
        production_database=dependencies.production_database,
        production_roots=dependencies.production_roots,
        runtime=FakeRuntime(),
    )
    backup = _artifact(tmp_path / "artifact")
    for target in (runtime_root / "restore", data_root / "restore", Path.cwd() / "restore"):
        with pytest.raises(RestoreError, match="target_data_root_overlaps_protected_root"):
            execute_isolated_restore(
                backup_root=backup,
                target_database="guiyi_restore_x",
                target_data_root=target,
                isolated=True,
                confirm_isolated_restore=True,
                dependencies=safe_dependencies,
            )


def test_default_dependencies_fail_closed_when_worktrees_cannot_be_enumerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_worktree_list(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["git", "worktree", "list"])

    monkeypatch.setattr(restore_isolated.subprocess, "run", fail_worktree_list)
    with pytest.raises(RestoreError, match="git_worktree_enumeration_failed"):
        default_dependencies()


@pytest.mark.parametrize(
    "fail_stage",
    ["container-id-mismatch", "container-label-mismatch"],
)
def test_container_is_owned_only_after_id_name_and_label_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_stage: str,
) -> None:
    artifact = verify_backup_artifact(_artifact(tmp_path))
    runner = ScriptedDockerRunner(fail_stage)
    runtime = DockerPostgresRuntime(command_runner=runner)
    monkeypatch.setattr(
        "scripts.restore.core.verify_restored_database",
        lambda *_args: pytest.fail("database verification must not run"),
    )

    with pytest.raises(RestoreError, match="isolated_container_ownership_mismatch"):
        runtime.restore_and_verify(
            artifact,
            target_database="guiyi_restore_x",
            target_root=tmp_path,
        )
    cleanup = runtime.cleanup()

    assert cleanup["container_removed"] is False
    assert ["docker", "rm", "--force", runner.container_id] not in runner.commands
    assert ["docker", "rm", "--force", runner.container_name] not in runner.commands


@pytest.mark.parametrize(
    "fail_stage,error",
    [
        ("container-inspect-once", "isolated_runtime_command_failed"),
        ("container-id-mismatch-once", "isolated_container_ownership_mismatch"),
        ("container-label-mismatch-once", "isolated_container_ownership_mismatch"),
    ],
)
def test_container_candidate_is_reinspected_and_removed_after_initial_inspect_failure(
    tmp_path: Path,
    fail_stage: str,
    error: str,
) -> None:
    artifact = verify_backup_artifact(_artifact(tmp_path))
    runner = ScriptedDockerRunner(fail_stage)
    runtime = DockerPostgresRuntime(command_runner=runner)

    with pytest.raises(RestoreError, match=error):
        runtime.restore_and_verify(
            artifact,
            target_database="guiyi_restore_x",
            target_root=tmp_path,
        )
    cleanup = runtime.cleanup()

    assert cleanup["container_removed"] is True
    assert runner.container_inspect_calls == 2
    assert ["docker", "rm", "--force", runner.container_id] in runner.commands
    assert ["docker", "rm", "--force", runner.container_name] not in runner.commands


def test_container_candidate_cleanup_reports_false_when_id_removal_fails(
    tmp_path: Path,
) -> None:
    artifact = verify_backup_artifact(_artifact(tmp_path))
    runner = ScriptedDockerRunner("container-inspect-once-rm-fails")
    runtime = DockerPostgresRuntime(command_runner=runner)

    with pytest.raises(RestoreError, match="isolated_runtime_command_failed"):
        runtime.restore_and_verify(
            artifact,
            target_database="guiyi_restore_x",
            target_root=tmp_path,
        )
    cleanup = runtime.cleanup()

    assert cleanup["container_removed"] is False
    assert runner.container_inspect_calls == 2
    assert ["docker", "rm", "--force", runner.container_id] in runner.commands
    assert ["docker", "rm", "--force", runner.container_name] not in runner.commands


def test_container_name_reuse_never_removes_a_different_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = verify_backup_artifact(_artifact(tmp_path))
    runner = ScriptedDockerRunner("container-name-reused")
    runtime = DockerPostgresRuntime(command_runner=runner)
    monkeypatch.setattr(
        "scripts.restore.core.verify_restored_database",
        lambda _url, artifact, _target: FakeRuntime().restore_and_verify(
            artifact,
            target_database="guiyi_restore_x",
            target_root=tmp_path,
        ),
    )

    runtime.restore_and_verify(
        artifact,
        target_database="guiyi_restore_x",
        target_root=tmp_path,
    )
    cleanup = runtime.cleanup()

    assert cleanup["container_removed"] is False
    assert ["docker", "rm", "--force", runner.container_id] not in runner.commands
    assert ["docker", "rm", "--force", runner.container_name] not in runner.commands


@pytest.mark.parametrize(
    "fail_stage,resource",
    [
        ("container-label-drift", "container"),
        ("volume-label-drift", "volume"),
    ],
)
def test_cleanup_refuses_container_or_volume_whose_ownership_label_drifted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_stage: str,
    resource: str,
) -> None:
    artifact = verify_backup_artifact(_artifact(tmp_path))
    runner = ScriptedDockerRunner(fail_stage)
    runtime = DockerPostgresRuntime(command_runner=runner)
    monkeypatch.setattr(
        "scripts.restore.core.verify_restored_database",
        lambda _url, artifact, _target: FakeRuntime().restore_and_verify(
            artifact,
            target_database="guiyi_restore_x",
            target_root=tmp_path,
        ),
    )

    runtime.restore_and_verify(
        artifact,
        target_database="guiyi_restore_x",
        target_root=tmp_path,
    )
    cleanup = runtime.cleanup()

    assert cleanup[f"{resource}_removed"] is False
    if resource == "container":
        assert ["docker", "rm", "--force", runner.container_id] not in runner.commands
    else:
        assert ["docker", "volume", "rm", runtime.volume] not in runner.commands
