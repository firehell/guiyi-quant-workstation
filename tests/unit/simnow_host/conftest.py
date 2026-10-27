"""All supervisor lock side effects stay inside disposable fixtures."""

import pytest


@pytest.fixture(autouse=True)
def isolated_account_lock_directory(monkeypatch, tmp_path):
    from guiyi_quant.simnow_execution import supervisor

    monkeypatch.setattr(
        supervisor, "global_account_lock_directory", lambda: tmp_path / "global-locks"
    )
