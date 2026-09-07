from __future__ import annotations

import os
import subprocess
import sys

import pytest


def test_guard_excludes_another_process_and_kernel_releases_after_crash(tmp_path):
    from app.market_data.live_recovery_guard import recovery_guard

    code = """import os, sys
from pathlib import Path
from app.market_data.live_recovery_guard import recovery_guard
try:
    with recovery_guard('jm', root=Path(sys.argv[1])):
        os._exit(0)
except RuntimeError:
    sys.exit(7)
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    with recovery_guard("jm", root=tmp_path):
        result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], env=env, capture_output=True)
        assert result.returncode == 7
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], env=env, capture_output=True)
    assert result.returncode == 0
    with recovery_guard("jm", root=tmp_path):
        pass  # os._exit did not leave a lease that could expire during Event commit


def test_guard_rejects_linked_or_unbounded_names(tmp_path):
    from app.market_data.live_recovery_guard import recovery_guard

    with pytest.raises(ValueError):
        with recovery_guard("../escape", root=tmp_path):
            pass
    target = tmp_path / "target"
    target.write_text("keep")
    (tmp_path / "jm.lock").symlink_to(target)
    with pytest.raises(ValueError):
        with recovery_guard("jm", root=tmp_path):
            pass
    assert target.read_text() == "keep"
