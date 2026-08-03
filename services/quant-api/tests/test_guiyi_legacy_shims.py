from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
import subprocess

from app import cli as legacy_cli


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_installed_guiyi_data_backtest_command_fails_closed_without_legacy_reads() -> None:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            "services/quant-api",
            "guiyi-data",
            "run-su-bing-backtest",
            "--symbol",
            "jm",
            "--contract",
            "JM.MAIN",
            "--period",
            "15m",
            "--profile-id",
            "legacy-profile",
            "--start",
            "2024-01-02",
            "--end",
            "2024-02-02",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stderr == ""
    assert __import__("json").loads(completed.stdout) == {
        "ok": False,
        "code": "BACKTEST_LEGACY_CLI_DISABLED",
        "message": (
            "run-su-bing-backtest is retired because it used legacy Profile/file data; "
            "create a canonical formal task through POST /api/backtests/tasks"
        ),
        "writes_database": False,
        "auto_order": False,
    }


def test_guiyi_data_check_bars_preserves_text_output_via_shared_verifier() -> None:
    stdout = StringIO()
    observed: dict[str, object] = {}

    def verify(_session, **kwargs):
        observed.update(kwargs)
        return {
            "status": "warning",
            "result": {
                "quality": {
                    "status": "warning",
                    "missing_bars": 2,
                    "duplicated_bars": 1,
                    "abnormal_price_count": 0,
                    "abnormal_volume_count": 3,
                    "report_count": 4,
                }
            },
        }

    exit_code = legacy_cli.main(
        [
            "check-bars",
            "--symbol",
            "rb",
            "--contract",
            "rb.MAIN",
            "--period",
            "1d",
            "--provider",
            "rqdata",
        ],
        session_factory=lambda: _SessionContext(),
        data_verifier=verify,
        stdout=stdout,
    )

    assert exit_code == 0
    assert stdout.getvalue() == (
        "status=warning missing_bars=2 duplicated_bars=1 "
        "abnormal_price_count=0 abnormal_volume_count=3 report_count=4\n"
    )
    assert observed["legacy_compat"] is True


class _SessionContext:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return None


def test_reference_metadata_plan_legacy_formatter_uses_shared_service_result() -> None:
    from app.services.core_cli import format_reference_metadata_plan_legacy

    payload = {
        "status": "planned",
        "readonly": True,
        "effects": {
            "writes_database": False,
            "writes_parquet": False,
            "writes_manifest": False,
            "calls_rqdata": False,
        },
        "result": {
            "candidate_row_count": 2,
            "batch_count": 1,
            "classification_counts": {"ready": 2},
        },
        "outputs": {"plan_json": "/tmp/plan.json"},
    }

    assert format_reference_metadata_plan_legacy(payload) == (
        "Reference metadata gap apply plan completed\n"
        "writes_database=False writes_parquet=False writes_manifest=False calls_rqdata=False\n"
        "candidate_rows=2\n"
        "batch_count=1\n"
        "ready=2\n"
        "plan_json: /tmp/plan.json\n"
    )


def test_reference_metadata_plan_script_is_thin_shared_service_shim(
    tmp_path: Path,
) -> None:
    script_path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "rqdata_reference_metadata_gap_apply_plan.py"
    )
    spec = importlib.util.spec_from_file_location("reference_plan_cli", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stdout = StringIO()
    observed: dict[str, object] = {}

    def runner(**kwargs):
        observed.update(kwargs)
        return {
            "status": "planned",
            "result": {
                "candidate_row_count": 0,
                "batch_count": 0,
                "classification_counts": {},
            },
            "outputs": {},
        }

    exit_code = module.main(
        [
            "--project-root",
            str(tmp_path),
            "--gap-ledger",
            "gap.csv",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        plan_runner=runner,
        stdout=stdout,
    )

    assert exit_code == 0
    assert observed == {
        "project_root": tmp_path,
        "gap_ledger": Path("gap.csv"),
        "output_dir": tmp_path / "out",
    }
    assert stdout.getvalue().startswith(
        "Reference metadata gap apply plan completed\n"
    )
