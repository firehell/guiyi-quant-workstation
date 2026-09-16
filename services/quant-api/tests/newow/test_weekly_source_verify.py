from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import newow_weekly_recovery as recovery
from scripts import newow_weekly_source_verify as source_verify


def _request_payload() -> dict[str, object]:
    return {
        "method": "futures.get_exchange_daily",
        "contract": "B2411",
        "start": "2023-12-27",
        "end": "2023-12-27",
        "expected_dates": ["2023-12-27"],
    }


def _manifest() -> dict[str, object]:
    request = _request_payload()
    return {
        "code_commit": "a" * 40,
        "execution_code_sha256": "b" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "d" * 64,
        "units": [
            {
                "symbol": "b",
                "contract": "B2411",
                "frequency": "1w",
                "through": "2024-10-23",
                "plan_sha256": "e" * 64,
                "source_requests": [request],
            }
        ],
    }


def test_source_verify_runner_is_part_of_execution_digest() -> None:
    assert "scripts/newow_weekly_source_verify.py" in recovery._EXECUTION_CODE_PATHS


def test_selection_is_bound_to_execution_and_request_hashes() -> None:
    manifest = _manifest()
    request_sha256 = hashlib.sha256(
        recovery._canonical_json(_request_payload()).encode("utf-8")
    ).hexdigest()

    selection = source_verify.validate_selection(
        manifest,
        current_execution_code_sha256="b" * 64,
        unit_index=0,
        request_index=0,
        expected_request_sha256=request_sha256,
    )

    assert selection.request.contract == "B2411"
    assert selection.request.expected_dates == (date(2023, 12, 27),)
    assert selection.unit["plan_sha256"] == "e" * 64

    with pytest.raises(recovery.RecoveryError, match="EXECUTION_IDENTITY_CHANGED"):
        source_verify.validate_selection(
            manifest,
            current_execution_code_sha256="f" * 64,
            unit_index=0,
            request_index=0,
            expected_request_sha256=request_sha256,
        )
    with pytest.raises(recovery.RecoveryError, match="SOURCE_SCOPE_INVALID"):
        source_verify.validate_selection(
            manifest,
            current_execution_code_sha256="b" * 64,
            unit_index=0,
            request_index=0,
            expected_request_sha256="0" * 64,
        )


@pytest.mark.parametrize(
    ("responses_saved", "outcome_unknown", "expected_status", "expected_classification"),
    [
        (1, False, "completed", "SOURCE_RESPONSE_SAVED_REVIEW_REQUIRED"),
        (0, True, "unknown", "SOURCE_QUERY_OUTCOME_UNKNOWN"),
    ],
)
def test_result_never_promotes_a_window_error_to_anomaly_fact(
    responses_saved: int,
    outcome_unknown: bool,
    expected_status: str,
    expected_classification: str,
) -> None:
    status, classification = source_verify.classify_evidence_outcome(
        {
            "responses_saved": responses_saved,
            "outcome_unknown": outcome_unknown,
        },
        plan_unchanged=True,
    )

    assert status == expected_status
    assert classification == expected_classification


def test_plan_drift_keeps_saved_response_in_review_required_state() -> None:
    status, classification = source_verify.classify_evidence_outcome(
        {"responses_saved": 1, "outcome_unknown": False},
        plan_unchanged=False,
    )

    assert status == "completed"
    assert classification == "SOURCE_RESPONSE_SAVED_PLAN_DRIFT_REVIEW_REQUIRED"


def _selection() -> source_verify.SourceSelection:
    request_payload = _request_payload()
    request = recovery._source_request_from_payload(request_payload)
    units = _manifest()["units"]
    assert isinstance(units, list)
    return source_verify.SourceSelection(
        unit=_manifest()["units"][0],
        request=request,
        request_payload=request_payload,
    )


def _execute_args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        output_root=str(tmp_path),
        attempt_id="source-only-attempt",
        project_env="/private/project.env",
        prepared="/private/prepared.json",
        expected_prepared_sha256="f" * 64,
        unit_index=0,
        request_index=0,
        expected_request_sha256=hashlib.sha256(
            recovery._canonical_json(_request_payload()).encode("utf-8")
        ).hexdigest(),
    )


def _install_execute_fakes(
    monkeypatch: pytest.MonkeyPatch,
    provider: object,
    *,
    current_plan_sha256: str = "e" * 64,
) -> tuple[dict[str, bool], dict[str, object]]:
    selection = _selection()
    lease_state = {"held": False}
    state: dict[str, object] = {"provider_calls": 0, "environment": None}

    class Lease:
        def release(self) -> None:
            lease_state["held"] = False

    class Catalog:
        def acquire_maintenance_lock(self) -> Lease:
            lease_state["held"] = True
            return Lease()

    class Adapter:
        def __init__(self, observer: recovery.AttemptJournal) -> None:
            self.observer = observer

        def _exchange_daily_rows(self, _key: object, _dates: object, *, cache: object):
            state["provider_calls"] = int(state["provider_calls"]) + 1
            return provider(self.observer, lease_state)

    class Environment:
        def __init__(self, observer: recovery.AttemptJournal) -> None:
            self.manager = SimpleNamespace(catalog=Catalog())
            self.adapter = Adapter(observer)
            self.closed = False

        def close(self) -> None:
            self.closed = True

    def open_environment(_path: Path, observer: recovery.AttemptJournal) -> Environment:
        environment = Environment(observer)
        state["environment"] = environment
        return environment

    monkeypatch.setattr(source_verify, "_open_execution_environment", open_environment)
    monkeypatch.setattr(
        source_verify, "_require_execution_identity", lambda value, _identity: value
    )
    monkeypatch.setattr(
        source_verify,
        "_require_current_plan",
        lambda _environment, _selection, _identity: None,
    )
    monkeypatch.setattr(source_verify, "_require_frozen_execution", lambda _value: None)
    monkeypatch.setattr(
        source_verify,
        "_current_source_requests",
        lambda _environment, _unit: (current_plan_sha256, (selection.request,)),
    )
    monkeypatch.setattr(source_verify, "_current_code_commit", lambda: "a" * 40)
    return lease_state, state


def test_preflight_rejects_unavailable_maintenance_lock_without_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection = _selection()
    state = {"provider_calls": 0}

    class Environment:
        manager = SimpleNamespace(
            catalog=SimpleNamespace(acquire_maintenance_lock=lambda: None)
        )
        adapter = SimpleNamespace()

        def close(self) -> None:
            return None

    monkeypatch.setattr(source_verify, "load_prepared_manifest", lambda *_args: _manifest())
    monkeypatch.setattr(source_verify, "_require_frozen_execution", lambda _value: None)
    monkeypatch.setattr(source_verify, "validate_selection", lambda *_args, **_kwargs: selection)
    monkeypatch.setattr(
        source_verify,
        "load_private_execution_settings",
        lambda _path: ({}, {"config_sha256": "c" * 64, "canonical_root_sha256": "d" * 64}),
    )
    monkeypatch.setattr(source_verify, "_open_execution_environment", lambda _path: Environment())
    monkeypatch.setattr(
        source_verify, "_require_execution_identity", lambda value, _identity: value
    )
    monkeypatch.setattr(
        source_verify,
        "_require_current_plan",
        lambda _environment, _selection, _identity: None,
    )

    with pytest.raises(recovery.RecoveryError, match="MAINTENANCE_LOCK_UNAVAILABLE"):
        source_verify._load_preflight(_execute_args(tmp_path))

    assert state["provider_calls"] == 0


def test_pre_provider_plan_drift_does_not_call_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def provider(_observer: object, _lease_state: object) -> object:
        raise AssertionError("provider must not be called")

    lease_state, state = _install_execute_fakes(monkeypatch, provider)
    monkeypatch.setattr(
        source_verify,
        "_require_current_plan",
        lambda _environment, _selection, _identity: (_ for _ in ()).throw(
            recovery.RecoveryError("CONTRACT_WARMUP_PLAN_CHANGED")
        ),
    )

    with pytest.raises(recovery.RecoveryError, match="CONTRACT_WARMUP_PLAN_CHANGED"):
        source_verify._execute(
            _execute_args(tmp_path),
            _manifest(),
            {"config_sha256": "c" * 64, "canonical_root_sha256": "d" * 64},
            _selection(),
        )

    assert state["provider_calls"] == 0
    assert recovery.read_attempt_outcome(tmp_path / "source-only-attempt") == {
        "state": "not_started",
        "outcome_unknown": False,
        "retry_allowed": False,
        "requests_started": 0,
        "responses_saved": 0,
    }
    assert lease_state["held"] is False


def test_provider_started_without_response_is_unknown_and_not_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection = _selection()

    def provider(
        observer: recovery.AttemptJournal, _lease_state: dict[str, bool]
    ) -> object:
        observer.before_request(selection.request)
        raise TimeoutError

    lease_state, _state = _install_execute_fakes(monkeypatch, provider)
    result = source_verify._execute(
        _execute_args(tmp_path),
        _manifest(),
        {"config_sha256": "c" * 64, "canonical_root_sha256": "d" * 64},
        selection,
    )

    assert result["status"] == "unknown"
    assert result["classification"] == "SOURCE_QUERY_OUTCOME_UNKNOWN"
    assert result["attempt"]["retry_allowed"] is False
    assert result["attempt"]["requests_started"] == 1
    assert result["attempt"]["responses_saved"] == 0
    assert lease_state["held"] is False


def test_response_persistence_failure_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection = _selection()

    def provider(
        observer: recovery.AttemptJournal, _lease_state: dict[str, bool]
    ) -> object:
        observer.before_request(selection.request)
        observer.after_response(
            selection.request,
            ({"date": date(2023, 12, 27), "close": 1},),
        )
        return {}

    monkeypatch.setattr(
        recovery.AttemptJournal,
        "_write_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
    )
    _lease_state, _state = _install_execute_fakes(monkeypatch, provider)
    result = source_verify._execute(
        _execute_args(tmp_path),
        _manifest(),
        {"config_sha256": "c" * 64, "canonical_root_sha256": "d" * 64},
        selection,
    )

    assert result["status"] == "unknown"
    assert result["classification"] == "SOURCE_QUERY_OUTCOME_UNKNOWN"
    assert result["attempt"]["retry_allowed"] is False
    assert result["attempt"]["responses_saved"] == 0


def test_execute_writes_receipt_and_holds_maintenance_lock_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection = _selection()

    def provider(
        observer: recovery.AttemptJournal, lease_state: dict[str, bool]
    ) -> object:
        attempt = tmp_path / "source-only-attempt"
        assert (attempt / "invocation-receipt.json").exists()
        assert lease_state["held"] is True
        observer.before_request(selection.request)
        observer.after_response(
            selection.request,
            (
                {
                    "date": date(2023, 12, 27),
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "volume": 1,
                },
            ),
        )
        return {date(2023, 12, 27): {"close": 1}}

    lease_state, state = _install_execute_fakes(monkeypatch, provider)

    result = source_verify._execute(
        _execute_args(tmp_path),
        _manifest(),
        {"config_sha256": "c" * 64, "canonical_root_sha256": "d" * 64},
        selection,
    )

    assert result["status"] == "completed"
    assert result["classification"] == "SOURCE_RESPONSE_SAVED_REVIEW_REQUIRED"
    assert result["canonical_writes"] == 0
    assert result["database_writes"] == 0
    environment = state["environment"]
    assert environment is not None and environment.closed is True
    assert lease_state["held"] is False
