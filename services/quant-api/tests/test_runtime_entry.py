from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


QUANT_API_ROOT = Path(__file__).resolve().parents[1]


def test_actual_runtime_launch_module_imports_no_offline_research() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.runtime_entry; "
                "print(sum(name == 'app.research' or "
                "name.startswith('app.research.') for name in sys.modules))"
            ),
        ],
        cwd=QUANT_API_ROOT,
        env={**os.environ, "PYTHONPATH": str(QUANT_API_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"
