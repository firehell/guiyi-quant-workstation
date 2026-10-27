"""Failure journals retain useful public diagnostics without exception text."""

import json

import pytest

from app.runtime_handover import _write
from tests.test_runtime_cohort_forward_recovery import fixture, module


class PrivateProviderFailure(RuntimeError):
    code = "UNTRUSTED_PROVIDER_CODE"


@pytest.mark.parametrize(
    "error, expected_type",
    [
        (ValueError("PRIVATE_SQL_AND_CREDENTIAL_MARKER"), "ValueError"),
        (PrivateProviderFailure("PRIVATE_SQL_AND_CREDENTIAL_MARKER"), "REDACTED"),
    ],
)
def test_recovery_does_not_record_arbitrary_exception_text_or_provider_codes(
    tmp_path, error, expected_type
):
    host, _, path, _, _, _ = fixture(tmp_path)
    target = tmp_path / "recovery.json"
    plan = module().freeze_forward_recovery(host, path)
    _write(target, plan)

    def fail(*args):
        raise error

    host.await_consumers = fail
    with pytest.raises(ValueError, match="COHORT_FORWARD_OUTCOME_UNKNOWN"):
        module().apply_forward_recovery(host, target)
    state = json.loads(
        (
            host.directory
            / "cohort-forward-recoveries"
            / plan["plan_sha256"]
            / "state.json"
        ).read_bytes()
    )
    assert state["failed_stage"] == "intake"
    assert state["error_type"] == expected_type
    assert state["error_code"] == "COHORT_FORWARD_STEP_FAILED"
    assert "PRIVATE_SQL_AND_CREDENTIAL_MARKER" not in json.dumps(state)
    assert "UNTRUSTED_PROVIDER_CODE" not in json.dumps(state)
