from testkit import *  # noqa: F403

import os
import pytest


# ── WS-V2-006: Autouse bypass for WS-V2-006 gates during test suite ───
# Tests that explicitly test gate behavior should call _clean_env() to
# remove these bypass variables before running.
#
# Without this fixture, gate tests that create dirty repos or missing
# external disks would cause all tests to fail.


@pytest.fixture(autouse=True)
def _ws_v2_006_test_bypass(monkeypatch):
    """Automatically bypass WS-V2-006 gates during the test suite.

    Individual gate tests that want to exercise the real gate logic
    should use _clean_env() to remove these bypass vars.
    """
    monkeypatch.setenv("GUIYI_SKIP_DIRTY_GATE", "1")
    monkeypatch.setenv("GUIYI_SKIP_EXTERNAL_DISK_GATE", "1")
    monkeypatch.setenv("GUIYI_SKIP_SCOPE_GATE", "1")
    yield
