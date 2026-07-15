import os
import pytest

from testkit import *  # noqa: F403


@pytest.fixture(autouse=True)
def _ws_v2_006_test_bypass(monkeypatch):
    """Bypass WS-V2-006 gates in test environments.
    
    Tests create temporary repos with uncommitted files and no
    external disks — these gates are tested explicitly in
    test_worktree_gate.py.
    """
    monkeypatch.setenv("GUIYI_SKIP_DIRTY_GATE", "1")
    monkeypatch.setenv("GUIYI_SKIP_EXTERNAL_DISK_GATE", "1")
    monkeypatch.setenv("GUIYI_SKIP_SCOPE_GATE", "1")
