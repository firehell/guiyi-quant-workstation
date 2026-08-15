from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_installed_guiyi_cli_runs_without_repository_pythonpath(tmp_path: Path) -> None:
    """Catches the console script importing quant-core only from repo PYTHONPATH."""
    executable = Path(sys.executable).with_name("guiyi")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        (str(executable), "--help"),
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "guiyi" in completed.stdout
