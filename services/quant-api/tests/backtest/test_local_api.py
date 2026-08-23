from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO, Iterator

from fastapi.testclient import TestClient
import pytest

from app.backtest.contracts import BacktestRunRequest
from app.backtest.errors import (
    BacktestError,
    BacktestHttpErrorCode,
    RegistryError,
)
from app.backtest.local_app import create_app


RUN_ID = "20260823T010203000000Z-0123456789abcdef"
ALLOWED_ORIGIN = "http://127.0.0.1:5173"


def _health(**changes: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "ready",
        "research_only": True,
        "formal_evidence": False,
        "promotion_eligible": False,
        "busy": False,
        "runner": {
            "available": True,
            "rqalpha_version": "fake-rqalpha-1",
            "rqsdk_version": "fake-rqsdk-1",
            "python_version": "fake-python-1",
        },
        "bundle_available": True,
        "runs_root_available": True,
    }
    payload.update(changes)
    return payload


def _strategy() -> dict[str, Any]:
    return {
        "id": "example_future_smoke_v1",
        "name": "Fixture strategy",
        "description": "TestClient-only strategy",
        "supported_frequencies": ["1d", "1m"],
        "defaults": {
            "future_cash": "1000000",
            "matching_type": "current_bar",
            "margin_multiplier": "1",
            "futures_commission_multiplier": "1",
            "slippage_model": "PriceRatioSlippage",
            "slippage": "0",
        },
        "parameters": [
            {
                "name": "quantity",
                "type": "integer",
                "default": 1,
                "minimum": 1,
                "maximum": 10,
                "options": [],
            }
        ],
        "research_only": True,
        "formal_evidence": False,
        "promotion_eligible": False,
    }


def _request_payload() -> dict[str, Any]:
    return {
        "strategy_id": "example_future_smoke_v1",
        "start_date": "2026-01-05",
        "end_date": "2026-01-06",
        "frequency": "1d",
        "future_cash": "1000000.00",
        "matching_type": "current_bar",
        "margin_multiplier": "1.00",
        "futures_commission_multiplier": "1.00",
        "slippage_model": "PriceRatioSlippage",
        "slippage": "0.00",
        "parameters": {"quantity": 2},
    }


def _run_record(
    *,
    status: str = "running",
    finished_at: str | None = None,
    exit_code: int | None = None,
    failure_code: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "research_only": True,
        "formal_evidence": False,
        "promotion_eligible": False,
        "strategy_id": "example_future_smoke_v1",
        "strategy_name": "Fixture strategy",
        "strategy_entry_file": "example_future_smoke_v1.py",
        "strategy_sha256": "a" * 64,
        "repository_commit": "b" * 40,
        "bundle_path": "/configured/bundle",
        "versions": {
            "rqalpha": "fake-rqalpha-1",
            "rqsdk": "fake-rqsdk-1",
            "python": "fake-python-1",
        },
        "requested_config": _request_payload(),
        "effective_config": {
            "base": {
                "start_date": "2026-01-05",
                "end_date": "2026-01-06",
                "frequency": "1d",
                "accounts": {"future": "1000000"},
                "auto_update_bundle": False,
            }
        },
        "effective_parameters": {"quantity": 2},
        "status": status,
        "started_at": "2026-08-23T01:02:03+00:00",
        "finished_at": finished_at,
        "exit_code": exit_code,
        "failure_code": failure_code,
    }


def _result() -> dict[str, Any]:
    return {
        "summary": {
            "total_returns": "0.125",
            "annualized_returns": "0.25",
            "max_drawdown": "0.05",
            "sharpe": "1.5",
            "sortino": "2",
            "volatility": "0.2",
            "total_value": "1125000",
            "cash": "100000",
        },
        "equity": [{"date": "2026-01-05", "unit_net_value": "1.125"}],
        "trade_count": "1",
        "artifacts": {
            "report_zip": True,
            "result_pickle": True,
            "equity_png": True,
            "stdout_log": True,
            "stderr_log": True,
            "run_json": True,
        },
    }


class FakeBacktestService:
    def __init__(self) -> None:
        self.health_payload = _health()
        self.health_error: Exception | None = None
        self.error_by_operation: dict[str, Exception] = {}
        self.received_request: BacktestRunRequest | None = None
        self.received_limits: list[int] = []
        self.artifact_requests: list[tuple[str, str]] = []
        self.artifact_closed = False

    def _raise_for(self, operation: str) -> None:
        error = self.error_by_operation.get(operation)
        if error is not None:
            raise error

    def health(self) -> dict[str, Any]:
        if self.health_error is not None:
            raise self.health_error
        return self.health_payload

    def list_strategies(self) -> list[dict[str, Any]]:
        self._raise_for("list_strategies")
        return [_strategy()]

    def start_run(self, request: BacktestRunRequest) -> dict[str, Any]:
        self._raise_for("start_run")
        self.received_request = request
        return _run_record()

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        self._raise_for("list_runs")
        self.received_limits.append(limit)
        return [_run_record()]

    def get_run(self, run_id: str) -> dict[str, Any]:
        self._raise_for("get_run")
        assert run_id == RUN_ID
        return _run_record(
            status="succeeded",
            finished_at="2026-08-23T01:03:03+00:00",
            exit_code=0,
        ) | {
            "result": _result(),
            "stdout_tail": "safe stdout",
            "stderr_tail": "",
        }

    @contextmanager
    def open_artifact(self, run_id: str, kind: str) -> Iterator[BinaryIO]:
        self._raise_for("open_artifact")
        self.artifact_requests.append((run_id, kind))
        try:
            yield BytesIO(b"PK\x03\x04fake-report")
        finally:
            self.artifact_closed = True


@pytest.fixture
def service() -> FakeBacktestService:
    return FakeBacktestService()


@pytest.fixture
def client(service: FakeBacktestService) -> TestClient:
    return TestClient(create_app(service, allowed_origins=(ALLOWED_ORIGIN,)))


def test_health_returns_stable_ready_dto(client: TestClient) -> None:
    response = client.get("/api/v1/backtests/health")

    assert response.status_code == 200
    assert response.json() == _health() | {
        "registry_available": True,
        "error": None,
    }


@pytest.mark.parametrize(
    ("changes", "unavailable_field"),
    [
        (
            {
                "status": "degraded",
                "runner": {
                    "available": False,
                    "rqalpha_version": None,
                    "rqsdk_version": None,
                    "python_version": None,
                },
            },
            "runner",
        ),
        ({"status": "degraded", "bundle_available": False}, "bundle_available"),
        (
            {"status": "degraded", "runs_root_available": False},
            "runs_root_available",
        ),
    ],
)
def test_health_returns_200_for_each_degraded_dependency(
    client: TestClient,
    service: FakeBacktestService,
    changes: dict[str, Any],
    unavailable_field: str,
) -> None:
    service.health_payload = _health(**changes)

    response = client.get("/api/v1/backtests/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    if unavailable_field == "runner":
        assert response.json()["runner"]["available"] is False
    else:
        assert response.json()[unavailable_field] is False
    assert response.json()["registry_available"] is True
    assert response.json()["error"] is None


def test_registry_failure_keeps_health_200_and_degraded(
    client: TestClient,
    service: FakeBacktestService,
) -> None:
    service.health_error = RegistryError()

    response = client.get("/api/v1/backtests/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "research_only": True,
        "formal_evidence": False,
        "promotion_eligible": False,
        "busy": False,
        "runner": {
            "available": False,
            "rqalpha_version": None,
            "rqsdk_version": None,
            "python_version": None,
        },
        "bundle_available": False,
        "runs_root_available": False,
        "registry_available": False,
        "error": {"code": "REGISTRY_INVALID"},
    }


def test_strategies_route_returns_stable_dto(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/backtests/strategies")

    assert response.status_code == 200
    assert response.json() == [_strategy()]


def test_post_runs_validates_json_and_returns_202(
    client: TestClient,
    service: FakeBacktestService,
) -> None:
    response = client.post("/api/v1/backtests/runs", json=_request_payload())

    assert response.status_code == 202
    assert response.json() == _run_record()
    assert service.received_request is not None
    assert service.received_request.start_date == date(2026, 1, 5)
    assert service.received_request.future_cash == Decimal("1000000.00")
    assert service.received_request.parameters == {"quantity": 2}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        _request_payload() | {"start_date": "01/05/2026"},
        _request_payload() | {"future_cash": 1000000},
        _request_payload() | {"unexpected": "unsafe"},
    ],
)
def test_request_validation_errors_have_one_safe_code(
    client: TestClient,
    service: FakeBacktestService,
    payload: dict[str, Any],
) -> None:
    response = client.post("/api/v1/backtests/runs", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "INVALID_BACKTEST_REQUEST"}}
    assert service.received_request is None


def test_runs_route_defaults_and_bounds_limit(
    client: TestClient,
    service: FakeBacktestService,
) -> None:
    default_response = client.get("/api/v1/backtests/runs")
    bounded_response = client.get("/api/v1/backtests/runs?limit=100")

    assert default_response.status_code == 200
    assert default_response.json() == [_run_record()]
    assert bounded_response.status_code == 200
    assert bounded_response.json() == [_run_record()]
    assert service.received_limits == [20, 100]


@pytest.mark.parametrize("limit", ["0", "101", "1.5", "true"])
def test_runs_route_rejects_invalid_limits_with_stable_error(
    client: TestClient,
    service: FakeBacktestService,
    limit: str,
) -> None:
    response = client.get(f"/api/v1/backtests/runs?limit={limit}")

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "INVALID_BACKTEST_REQUEST"}}
    assert service.received_limits == []


def test_run_detail_returns_result_logs_and_artifact_allowlist(
    client: TestClient,
) -> None:
    response = client.get(f"/api/v1/backtests/runs/{RUN_ID}")

    assert response.status_code == 200
    assert response.json() == _run_record(
        status="succeeded",
        finished_at="2026-08-23T01:03:03+00:00",
        exit_code=0,
    ) | {
        "result": _result(),
        "stdout_tail": "safe stdout",
        "stderr_tail": "",
    }


def test_report_zip_stream_is_closed_after_response(
    client: TestClient,
    service: FakeBacktestService,
) -> None:
    response = client.get(f"/api/v1/backtests/runs/{RUN_ID}/artifacts/report_zip")

    assert response.status_code == 200
    assert response.content == b"PK\x03\x04fake-report"
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{RUN_ID}-report.zip"'
    )
    assert service.artifact_requests == [(RUN_ID, "report_zip")]
    assert service.artifact_closed is True


@pytest.mark.parametrize(
    ("operation", "error_code", "status_code"),
    [
        ("start_run", "BACKTEST_ALREADY_RUNNING", 409),
        ("get_run", "BACKTEST_RUN_NOT_FOUND", 404),
        ("open_artifact", "BACKTEST_ARTIFACT_NOT_FOUND", 404),
        ("list_strategies", "REGISTRY_INVALID", 503),
        ("start_run", "RUNNER_UNAVAILABLE", 503),
        ("start_run", "BUNDLE_UNAVAILABLE", 503),
        ("start_run", "BACKTEST_LOCAL_UNAVAILABLE", 503),
        ("start_run", "STRATEGY_NOT_FOUND", 404),
        ("start_run", "INVALID_BACKTEST_REQUEST", 422),
    ],
)
def test_domain_errors_map_to_stable_http_contract(
    client: TestClient,
    service: FakeBacktestService,
    operation: str,
    error_code: str,
    status_code: int,
) -> None:
    service.error_by_operation[operation] = BacktestError(
        BacktestHttpErrorCode(error_code)
    )
    if operation == "start_run":
        response = client.post("/api/v1/backtests/runs", json=_request_payload())
    elif operation == "get_run":
        response = client.get(f"/api/v1/backtests/runs/{RUN_ID}")
    elif operation == "open_artifact":
        response = client.get(f"/api/v1/backtests/runs/{RUN_ID}/artifacts/equity_png")
    else:
        response = client.get("/api/v1/backtests/strategies")

    assert response.status_code == status_code
    assert response.json() == {"detail": {"code": error_code}}


def test_unexpected_errors_are_redacted_to_one_safe_contract(
    client: TestClient,
    service: FakeBacktestService,
) -> None:
    sensitive = "Traceback DATABASE_URL=postgres://secret RQDATA_LICENSE=license-secret"
    service.error_by_operation["list_runs"] = RuntimeError(sensitive)

    response = client.get("/api/v1/backtests/runs")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "BACKTEST_LOCAL_UNAVAILABLE"}}
    rendered = response.text
    assert "Traceback" not in rendered
    assert "DATABASE_URL" not in rendered
    assert "license-secret" not in rendered


def test_no_origin_local_cli_post_is_allowed(
    client: TestClient,
    service: FakeBacktestService,
) -> None:
    response = client.post("/api/v1/backtests/runs", json=_request_payload())

    assert response.status_code == 202
    assert service.received_request is not None


def test_allowed_origin_is_exact_and_receives_cors_header(client: TestClient) -> None:
    response = client.get(
        "/api/v1/backtests/health",
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1:5173",
        "http://127.0.0.1:5173.evil.example",
        "http://localhost:5173",
        "null",
    ],
)
def test_disallowed_origin_is_rejected_before_service_call(
    client: TestClient,
    service: FakeBacktestService,
    origin: str,
) -> None:
    response = client.post(
        "/api/v1/backtests/runs",
        json=_request_payload(),
        headers={"Origin": origin},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "BACKTEST_LOCAL_UNAVAILABLE"}}
    assert service.received_request is None


def test_bad_host_is_rejected_before_service_call(
    client: TestClient,
    service: FakeBacktestService,
) -> None:
    response = client.get(
        "/api/v1/backtests/strategies",
        headers={"Host": "192.168.1.8:8011"},
    )

    assert response.status_code == 400
    assert response.text == "Invalid host header"
    assert service.received_limits == []


@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("text/plain", "{}"),
        ("application/x-www-form-urlencoded", "strategy_id=example"),
        (None, "{}"),
    ],
)
def test_mutation_accepts_only_json_media_type(
    client: TestClient,
    service: FakeBacktestService,
    content_type: str | None,
    content: str,
) -> None:
    headers = {"Content-Type": content_type} if content_type is not None else {}

    response = client.post(
        "/api/v1/backtests/runs",
        content=content,
        headers=headers,
    )

    assert response.status_code == 415
    assert response.json() == {"detail": {"code": "INVALID_BACKTEST_REQUEST"}}
    assert service.received_request is None


def test_main_fixes_loopback_host_and_port_without_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.backtest import local_app

    built_app = object()
    calls: list[tuple[object, dict[str, Any]]] = []
    fake_uvicorn = SimpleNamespace(
        run=lambda app, **kwargs: calls.append((app, kwargs))
    )
    monkeypatch.setattr(local_app, "build_app", lambda: built_app)
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", fake_uvicorn)

    local_app.main()

    assert calls == [(built_app, {"host": "127.0.0.1", "port": 8011})]


def test_repository_identity_uses_fixed_git_without_inheriting_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.backtest import local_app

    calls: list[dict[str, Any]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append({"argv": argv, **kwargs})
        return SimpleNamespace(stdout="b" * 40 + "\n")

    monkeypatch.setattr(local_app.subprocess, "run", fake_run)

    commit = local_app._repository_commit()

    assert commit == "b" * 40
    assert calls == [
        {
            "argv": ["/usr/bin/git", "rev-parse", "HEAD"],
            "cwd": Path(local_app.__file__).resolve().parents[4],
            "env": {"LANG": "C"},
            "stdin": local_app.subprocess.DEVNULL,
            "capture_output": True,
            "text": True,
            "check": True,
            "timeout": 5,
        }
    ]
