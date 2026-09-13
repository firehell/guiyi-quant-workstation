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


def test_after_market_guard_is_global_and_uses_existing_safe_directory(tmp_path):
    from app.market_data.live_recovery_guard import after_market_recovery_guard, recovery_guard

    with after_market_recovery_guard(root=tmp_path):
        with pytest.raises(RuntimeError, match="LIVE_RECOVERY_BUSY"):
            with after_market_recovery_guard(root=tmp_path):
                pytest.fail("captured operation must not race after-market")
        with recovery_guard("jm", root=tmp_path):
            pass  # Global guard and symbol guard are separate locks with fixed ordering.
    assert (tmp_path / "after-market.lock").stat().st_mode & 0o777 == 0o600


def test_after_market_guard_rejects_symlink(tmp_path):
    from app.market_data.live_recovery_guard import after_market_recovery_guard

    target = tmp_path / "target"
    target.write_text("keep")
    (tmp_path / "after-market.lock").symlink_to(target)
    with pytest.raises(ValueError, match="LIVE_RECOVERY_GUARD_UNSAFE"):
        with after_market_recovery_guard(root=tmp_path):
            pass
    assert target.read_text() == "keep"


@pytest.mark.parametrize("closed_before_error", (False, True))
def test_close_failure_does_not_leave_process_holding_product_lock(tmp_path, monkeypatch, closed_before_error):
    from app.market_data.live_recovery_guard import recovery_guard

    original_close = os.close
    failed_fd = None

    def fail_close(fd):
        nonlocal failed_fd
        failed_fd = fd
        if closed_before_error:
            original_close(fd)
        raise OSError("injected close failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "close", fail_close)
            with pytest.raises(OSError, match="injected close failure"):
                with recovery_guard("jm", root=tmp_path):
                    pass
        # This must work BEFORE test cleanup closes a potentially still-open fd.
        with recovery_guard("jm", root=tmp_path):
            pass
    finally:
        if failed_fd is not None and not closed_before_error:
            original_close(failed_fd)


def test_unlock_failure_still_closes_descriptor_and_releases_kernel_lock(tmp_path, monkeypatch):
    import fcntl
    from app.market_data.live_recovery_guard import recovery_guard

    original_flock = fcntl.flock

    def fail_unlock(fd, operation):
        if operation == fcntl.LOCK_UN:
            raise OSError("injected unlock failure")
        return original_flock(fd, operation)

    with monkeypatch.context() as patch:
        patch.setattr(fcntl, "flock", fail_unlock)
        with pytest.raises(OSError, match="injected unlock failure"):
            with recovery_guard("jm", root=tmp_path):
                pass
    with recovery_guard("jm", root=tmp_path):
        pass
