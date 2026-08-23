from __future__ import annotations

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def _smoke_block() -> str:
    testing = (ROOT / "TESTING.md").read_text(encoding="utf-8")
    match = re.search(
        r"以下是一次完整的.*?```bash\n(?P<script>.*?)\n```",
        testing,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group("script")


def test_documented_real_smoke_is_valid_shell_and_only_snapshots_bundle(
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
    assert "bundle.before" in script
    assert "bundle.after" in script
    assert 'cmp -s "$task8_tmp_dir/bundle.before"' in script
    assert "backtest_formal_surface_snapshot.py" not in script
    assert "formal.before.json" not in script
    assert "formal.after.json" not in script


def test_repository_has_no_formal_surface_live_snapshot_helper() -> None:
    assert not (
        ROOT / "scripts/engineering/backtest_formal_surface_snapshot.py"
    ).exists()


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
