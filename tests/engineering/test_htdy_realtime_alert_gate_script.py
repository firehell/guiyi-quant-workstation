from __future__ import annotations

import subprocess
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "engineering" / "htdy-realtime-alert-gate.py"


def test_htdy_gate_script_exposes_generate_and_verify_without_secrets() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Generate or verify" in result.stdout
    source = SCRIPT.read_text(encoding="utf-8")
    assert "open(\"x\"" in source
    assert "QYWX_WEBHOOK_URL" not in source
