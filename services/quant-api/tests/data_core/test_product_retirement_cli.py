from __future__ import annotations

import importlib.util
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[4] / "scripts/rqdata_product_retirement.py"
AGGREGATE_SCRIPT = Path(__file__).resolve().parents[4] / "scripts/rqdata_aggregate_main_universe.py"


def _module():
    spec = importlib.util.spec_from_file_location("rqdata_product_retirement", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _aggregate_module():
    sys.path.insert(0, str(AGGREGATE_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("rqdata_aggregate_main_universe", AGGREGATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_parser_requires_explicit_bounded_roots_and_output() -> None:
    module = _module()
    args = module.build_parser().parse_args(
        [
            "inventory",
            "--project-root",
            "/project",
            "--runtime-root",
            "/runtime",
            "--data-root",
            "raw=/data/raw",
            "--protected-root",
            "/evidence",
            "--output",
            "/evidence/packet.json",
        ]
    )

    assert args.command == "inventory"
    assert args.data_root == ["raw=/data/raw"]
    assert args.protected_root == Path("/evidence")
    assert args.output == Path("/evidence/packet.json")


def test_parse_roots_rejects_broad_or_duplicate_targets(tmp_path: Path) -> None:
    module = _module()
    raw = tmp_path / "data/raw/rqdata"
    canonical = tmp_path / "data/parquet/canonical"
    processed = tmp_path / "data/processed/v1b"
    raw.mkdir(parents=True)
    canonical.mkdir(parents=True)
    processed.mkdir(parents=True)

    assert module.parse_roots([f"raw={raw}", f"canonical={canonical}", f"processed={processed}"]) == {
        "raw": raw,
        "canonical": canonical,
        "processed": processed,
    }
    with pytest.raises(ValueError, match="ROOT_DUPLICATE"):
        module.parse_roots([f"raw={raw}", f"raw={canonical}"])
    with pytest.raises(ValueError, match="ROOT_TOO_BROAD"):
        module.parse_roots(["data=/"])
    with pytest.raises(ValueError, match="REQUIRED_ROOTS_MISMATCH"):
        module.parse_roots([f"raw={raw}", f"canonical={canonical}"])


def test_shutdown_receipt_requires_all_writer_services_stopped() -> None:
    module = _module()
    receipt = {
        "schema_version": 1,
        "status": "passed",
        "code_sha": "a" * 40,
        "runtime_sha": "b" * 40,
        "database_revision": "revision-1",
        "retired_products_digest": "c" * 64,
        "generated_at": "2026-08-05T12:00:00+08:00",
        "expires_at": "2026-08-05T13:00:00+08:00",
        "active_universe": {
            "product_count": 69,
            "retired_products_absent": True,
            "reingest_guard_verified": True,
        },
        "services": {service: "stopped" for service in module.REQUIRED_STOPPED_SERVICES},
    }

    kwargs = {
        "code_sha": "a" * 40,
        "runtime_sha": "b" * 40,
        "database_revision": "revision-1",
        "retired_products_digest": "c" * 64,
        "now": "2026-08-05T12:30:00+08:00",
    }
    module.validate_shutdown_receipt(receipt, **kwargs)
    receipt["services"]["com.guiyi.quant-api"] = "running"
    with pytest.raises(ValueError, match="SERVICE_NOT_STOPPED"):
        module.validate_shutdown_receipt(receipt, **kwargs)


def test_packet_file_bytes_are_the_exact_approved_digest(tmp_path: Path) -> None:
    module = _module()
    packet = {"scope": {"retired_product_count": 21}, "status": "ready_for_exact_approval"}
    output = tmp_path / "packet.json"

    digest = module.write_packet_exclusive(output, packet)

    assert sha256(output.read_bytes()).hexdigest() == digest
    assert json.loads(output.read_bytes()) == packet


def test_packet_bundle_output_rejects_existing_asset_directory(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "packet.json"
    (tmp_path / "packet.json.assets").mkdir()

    with pytest.raises(ValueError, match="SHARD_ROOT_COLLISION"):
        module._validate_packet_bundle_output(output, protected_roots=())


def test_aggregate_cli_rejects_explicit_retired_product_before_opening_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _aggregate_module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda argv=None: type(
            "Args",
            (),
            {"command": "run", "products": ["jr"], "products_file": Path("unused")},
        )(),
    )

    with pytest.raises(ValueError, match="PRODUCT_RETIREMENT_PRODUCT_RETIRED"):
        module.main([])


def test_git_sha_rejects_dirty_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()

    def fake_run(command, **kwargs):
        assert command[-2:] == ["status", "--porcelain"]
        return subprocess.CompletedProcess(command, 0, stdout=" M file.py\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="GIT_WORKTREE_DIRTY"):
        module._git_sha(Path("/project"))


def test_execution_project_root_is_bound_to_loaded_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    project = tmp_path / "project"
    loaded_module = project / "services/quant-api/app/data_core/product_retirement.py"
    loaded_module.parent.mkdir(parents=True)
    loaded_module.write_text("# test module\n", encoding="utf-8")
    monkeypatch.setattr(module, "_validated_git_root", lambda path: project)
    monkeypatch.setattr(module.product_retirement_module, "__file__", str(loaded_module))

    with pytest.raises(ValueError, match="EXECUTION_ROOT_MISMATCH"):
        module._validated_execution_project_root(project)


def test_protected_root_rejects_overlap_and_path_escape(tmp_path: Path) -> None:
    module = _module()
    data_root = tmp_path / "project/data/raw/rqdata"
    protected_root = tmp_path / "evidence"
    data_root.mkdir(parents=True)
    protected_root.mkdir()

    validated = module._validated_protected_root(
        protected_root,
        forbidden_roots=(data_root,),
    )
    module._require_path_in_protected_root(protected_root / "packet.json", validated)

    with pytest.raises(ValueError, match="PATH_OUTSIDE_PROTECTED_ROOT"):
        module._require_path_in_protected_root(protected_root / "../escape.json", validated)
    with pytest.raises(ValueError, match="PROTECTED_ROOT_OVERLAP"):
        module._validated_protected_root(
            data_root.parent,
            forbidden_roots=(data_root,),
        )


def test_writer_services_must_be_unloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()

    def unloaded(command, **kwargs):
        return subprocess.CompletedProcess(command, 113, stdout="", stderr="not found")

    monkeypatch.setattr(module.subprocess, "run", unloaded)
    module.validate_writer_services_unloaded()

    first = module.REQUIRED_STOPPED_SERVICES[0]

    def one_loaded(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0 if command[-1].endswith(first) else 113,
            stdout="loaded" if command[-1].endswith(first) else "",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", one_loaded)
    with pytest.raises(ValueError, match="SERVICE_STILL_LOADED"):
        module.validate_writer_services_unloaded()

    def unknown(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="permission denied")

    monkeypatch.setattr(module.subprocess, "run", unknown)
    with pytest.raises(ValueError, match="SERVICE_STATE_UNKNOWN"):
        module.validate_writer_services_unloaded()
