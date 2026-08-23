from __future__ import annotations

from pathlib import Path
import importlib.util
import re
import subprocess
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _formal_snapshot_module() -> ModuleType:
    service_root = ROOT / "services/quant-api"
    sys.path.insert(0, str(service_root))
    try:
        path = ROOT / "scripts/engineering/backtest_formal_surface_snapshot.py"
        spec = importlib.util.spec_from_file_location("backtest_formal_snapshot", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(service_root))


def _smoke_block() -> str:
    testing = (ROOT / "TESTING.md").read_text(encoding="utf-8")
    match = re.search(
        r"以下是一次完整的.*?```bash\n(?P<script>.*?)\n```",
        testing,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group("script")


def test_documented_real_smoke_is_valid_shell_and_fail_closed_on_formal_snapshots(
    tmp_path: Path,
) -> None:
    script = _smoke_block()
    fixture = tmp_path / "smoke.sh"
    fixture.write_text(script, encoding="utf-8")

    parsed = subprocess.run(
        ["bash", "-n", str(fixture)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert parsed.returncode == 0, parsed.stderr
    assert "backtest_formal_surface_snapshot.py" in script
    assert "formal.before.json" in script
    assert "formal.after.json" in script
    assert 'cmp -s "$task8_tmp_dir/formal.before.json"' in script
    assert "NOT_VERIFIED" in script


def test_documented_smoke_binds_strategy_snapshot_to_commit_and_source_sha() -> None:
    script = _smoke_block()

    assert "task8_repository_commit" in script
    assert "task8_expected_strategy_sha256" in script
    assert ".repository_commit == $task8_repository_commit" in script
    assert ".strategy_sha256 == $task8_expected_strategy_sha256" in script
    assert 'shasum -a 256 "$task8_run_dir/strategy.py"' in script


def test_sidecar_cleanup_revalidates_full_process_identity_before_each_signal() -> None:
    script = _smoke_block()

    assert "task8_capture_sidecar_identity" in script
    assert "task8_verify_sidecar_identity" in script
    assert "task8_sidecar_executable" in script
    assert "task8_sidecar_command" in script
    assert "task8_sidecar_cwd" in script
    assert "task8_sidecar_started" in script
    assert (
        'task8_verify_sidecar_identity || return 1\n'
        '    kill -TERM "$task8_sidecar_pid"' in script
    )
    assert (
        'task8_verify_sidecar_identity || return 1\n'
        '      kill -KILL "$task8_sidecar_pid"' in script
    )


def test_formal_snapshot_reads_every_named_surface_and_has_no_constant_order_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _formal_snapshot_module()
    names = (
        "database",
        "redis",
        "canonical",
        "notification_config",
        "runtime",
        "order_boundary",
    )
    for name in names:
        monkeypatch.setattr(module, f"_{name}_snapshot", lambda name=name: name)

    assert module.snapshot() == {
        "schema_version": 1,
        "status": "VERIFIED",
        "database_alert_execution_review_catalog": "database",
        "redis": "redis",
        "canonical": "canonical",
        "notification_config": "notification_config",
        "runtime": "runtime",
        "order_boundary": "order_boundary",
    }


def test_formal_snapshot_reports_not_verified_without_error_or_secret_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _formal_snapshot_module()

    def fail() -> None:
        raise RuntimeError("secret-private-detail")

    monkeypatch.setattr(module, "snapshot", fail)

    assert module.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == '{"schema_version": 1, "status": "NOT_VERIFIED"}'
