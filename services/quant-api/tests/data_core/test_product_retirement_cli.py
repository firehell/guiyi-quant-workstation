from __future__ import annotations

import importlib.util
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[4] / "scripts/rqdata_product_retirement.py"


def _module():
    spec = importlib.util.spec_from_file_location("rqdata_product_retirement", SCRIPT)
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
            "--output",
            "/evidence/packet.json",
        ]
    )

    assert args.command == "inventory"
    assert args.data_root == ["raw=/data/raw"]
    assert args.output == Path("/evidence/packet.json")


def test_parse_roots_rejects_broad_or_duplicate_targets(tmp_path: Path) -> None:
    module = _module()
    raw = tmp_path / "raw"
    canonical = tmp_path / "canonical"
    raw.mkdir()
    canonical.mkdir()

    assert module.parse_roots([f"raw={raw}", f"canonical={canonical}"]) == {
        "raw": raw,
        "canonical": canonical,
    }
    with pytest.raises(ValueError, match="ROOT_DUPLICATE"):
        module.parse_roots([f"raw={raw}", f"raw={canonical}"])
    with pytest.raises(ValueError, match="ROOT_TOO_BROAD"):
        module.parse_roots(["data=/"])


def test_shutdown_receipt_requires_all_writer_services_stopped() -> None:
    module = _module()
    receipt = {
        "schema_version": 1,
        "status": "passed",
        "runtime_sha": "b" * 40,
        "services": {
            "com.guiyi.quant-api": "stopped",
            "com.guiyi.quant-worker-backtests": "stopped",
            "com.guiyi.quant-worker-signals": "stopped",
            "com.guiyi.quant-htdy-s610-one-day-observer": "stopped",
            "com.guiyi.quant-htdy-s610-one-day-dispatcher": "stopped",
            "com.guiyi.quant-htdy-s610-observer": "stopped",
        },
    }

    module.validate_shutdown_receipt(receipt, runtime_sha="b" * 40)
    receipt["services"]["com.guiyi.quant-api"] = "running"
    with pytest.raises(ValueError, match="SERVICE_NOT_STOPPED"):
        module.validate_shutdown_receipt(receipt, runtime_sha="b" * 40)


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


def test_git_sha_rejects_dirty_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()

    def fake_run(command, **kwargs):
        assert command[-2:] == ["status", "--porcelain"]
        return subprocess.CompletedProcess(command, 0, stdout=" M file.py\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="GIT_WORKTREE_DIRTY"):
        module._git_sha(Path("/project"))


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
