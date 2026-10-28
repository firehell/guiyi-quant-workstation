import json
from datetime import UTC, datetime

import pytest

from guiyi_quant.simnow_execution.supervisor import retain_failure


def test_failure_fact_is_private_immutable_and_contains_only_supplied_sanitized_diagnostic(
    tmp_path,
):
    diagnostic = dict(
        stage="NATIVE_LOGIN", inventory=dict(status="LOGIN_REJECTED", error_id=3)
    )
    retain_failure(
        tmp_path,
        "fixture-run",
        1,
        "CONTINUOUS_RECOVERY_REQUIRED",
        datetime(2026, 10, 27, tzinfo=UTC),
        diagnostic,
    )
    path = tmp_path / "failure-fixture-run-1.json"
    data = json.loads(path.read_text())
    assert data["diagnostic"] == diagnostic
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        retain_failure(tmp_path, "fixture-run", 1, "DIFFERENT", datetime.now(UTC), {})
    assert path.read_bytes() == before
