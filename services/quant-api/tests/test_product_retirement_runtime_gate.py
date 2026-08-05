from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.product_retirement_runtime_gate import (
    BoundProductRetirementCommandExecutor,
    ProductRetirementExecutionService,
    ProductRetirementPrecommitError,
    ProductRetirementRuntimeGate,
    ProductRetirementRuntimeGateError,
    REQUIRED_WRITER_SERVICES,
    RetirementRuntimeRequest,
    append_journal,
    validate_runtime_request,
)


class _RuntimeOperator:
    def __init__(
        self, *, running: tuple[str, ...] = (), runtime_sha: str = "b" * 40
    ) -> None:
        self.checkout_calls: list[str] = []
        self.restart_calls = 0
        self.restart_targets: list[dict[str, str]] = []
        self.states = {
            service: ("running" if service in running else "stopped")
            for service in REQUIRED_WRITER_SERVICES
        }
        self.current_sha = runtime_sha

    def preflight(self, *, root, release_tag, rollback_tag):
        return {
            "runtime_sha": self.runtime_identity(root),
            "release_tag": release_tag,
            "release_sha": "c" * 40,
            "rollback_tag": rollback_tag,
            "rollback_sha": "d" * 40,
            "writer_states": dict(self.states),
        }

    def stop_writer_services(self):
        self.states = {service: "stopped" for service in REQUIRED_WRITER_SERVICES}
        return self.states

    def writer_states(self):
        return self.states

    def runtime_identity(self, _root: Path) -> str:
        return self.current_sha

    def checkout_detached(self, _root: Path, ref: str) -> str:
        self.checkout_calls.append(ref)
        self.current_sha = "c" * 40
        return self.current_sha

    def restart_services(self, target_states):
        self.restart_calls += 1
        self.restart_targets.append(dict(target_states))
        self.states = dict(target_states)
        return self.states


class _DataOperator:
    def __init__(self, *, apply_status: str) -> None:
        self.apply_status = apply_status
        self.calls: list[tuple[object, ...]] = []

    def apply(self, _inventory, _precommit):
        self.calls.append(("apply",))
        return {"status": self.apply_status}

    def preflight(self, _request):
        self.calls.append(("preflight",))
        return {"status": "passed", "active_product_count": 69}

    def finalize(self, _inventory, _receipt):
        self.calls.append(("finalize",))
        return {"status": "applied"}

    def verify(self):
        self.calls.append(("verify",))
        return {"status": "passed"}

    def sync_direct(self, _products, frequencies):
        self.calls.append(("sync_direct", tuple(frequencies)))
        return {"status": "passed", "target_count": 1}

    def aggregate(self, _products, frequencies):
        self.calls.append(("aggregate", tuple(frequencies)))
        return {"status": "passed", "target_count": 1}


def test_runtime_gate_does_not_require_disabled_or_legacy_notification_services() -> (
    None
):
    assert "com.guiyi.quant-worker-notifications" not in REQUIRED_WRITER_SERVICES
    assert "com.guiyi.quant-notification-worker" not in REQUIRED_WRITER_SERVICES


def test_validate_runtime_request_rejects_protected_root_inside_runtime(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = runtime_root / "audit"
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text(
        "\n".join(f"keep_{index}" for index in range(69)) + "\n",
        encoding="utf-8",
    )

    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )

    with pytest.raises(
        ProductRetirementRuntimeGateError, match="PROTECTED_ROOT_OVERLAP"
    ):
        validate_runtime_request(request)


def test_append_journal_creates_one_append_only_record(tmp_path: Path) -> None:
    journal = append_journal(
        tmp_path,
        {"run_id": "run-001", "status": "preflight", "runtime_sha": "a" * 40},
    )

    assert journal.name == "product-retirement-run-001.jsonl"
    assert journal.read_text(encoding="utf-8") == (
        '{"run_id":"run-001","runtime_sha":"' + "a" * 40 + '","status":"preflight"}\n'
    )
    with pytest.raises(FileExistsError):
        append_journal(tmp_path, {"run_id": "run-001", "status": "duplicate"})


def test_precommit_inventory_failure_rolls_runtime_back_and_keeps_services_stopped(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text("jm\n", encoding="utf-8")
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    operator = _RuntimeOperator()
    gate = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: (_ for _ in ()).throw(
            RuntimeError("inventory failed")
        ),
    )

    result = gate.execute_precommit(request, operator=operator)

    assert result["status"] == "rejected"
    assert operator.checkout_calls == [request.release_tag, request.rollback_tag]
    assert operator.restart_calls == 0
    assert operator.writer_states() == {
        service: "stopped" for service in REQUIRED_WRITER_SERVICES
    }


def test_precommit_binds_one_run_shutdown_receipt(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        label: tmp_path / f"data/{label}" for label in ("raw", "canonical", "processed")
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text("jm\n", encoding="utf-8")
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    gate = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"},
        run_id_factory=lambda: "run-001",
    )

    result = gate.execute_precommit(request, operator=_RuntimeOperator())

    assert result["run_id"] == "run-001"
    assert result["release_tag"] == request.release_tag
    assert result["runtime_sha"] == "c" * 40
    assert len(result["shutdown_receipt_sha256"]) == 64


def test_postcommit_purge_failure_keeps_services_stopped(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text("jm\n", encoding="utf-8")
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    runtime = _RuntimeOperator()
    data = _DataOperator(apply_status="db_committed_purge_pending")
    gate = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"}
    )

    result = gate.execute(request, runtime_operator=runtime, data_operator=data)

    assert result["status"] == "db_committed_purge_pending"
    assert data.calls == [("preflight",), ("apply",)]
    assert runtime.restart_calls == 0


def test_bound_command_executor_owns_runtime_and_data_operators(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        label: tmp_path / f"data/{label}" for label in ("raw", "canonical", "processed")
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text(
        "\n".join(f"keep_{index}" for index in range(69)) + "\n"
    )
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    runtime = _RuntimeOperator()
    data = _DataOperator(apply_status="applied")
    executor = BoundProductRetirementCommandExecutor(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"},
        runtime_operator=runtime,
        data_operator=data,
    )

    result = executor.execute(request)

    assert result["status"] == "completed"
    assert data.calls == [
        ("preflight",),
        ("apply",),
        ("verify",),
        ("sync_direct", ("1m", "1d", "1w")),
        ("aggregate", ("5m", "15m", "30m", "60m")),
    ]


def test_database_apply_failure_rolls_runtime_back_and_keeps_services_stopped(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        label: tmp_path / f"data/{label}" for label in ("raw", "canonical", "processed")
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text("jm\n", encoding="utf-8")
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )

    class _FailingDataOperator(_DataOperator):
        def apply(self, _inventory, _precommit):
            raise ProductRetirementPrecommitError("database unavailable")

    runtime = _RuntimeOperator()
    result = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"}
    ).execute(
        request,
        runtime_operator=runtime,
        data_operator=_FailingDataOperator(apply_status="applied"),
    )

    assert result["status"] == "rejected"
    assert result["phase"] == "precommit"
    assert runtime.checkout_calls == [request.release_tag, request.rollback_tag]
    assert runtime.restart_calls == 0


def test_resume_finalizes_then_updates_retained_periods_and_restarts(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text(
        "\n".join(f"keep_{index}" for index in range(69)) + "\n",
        encoding="utf-8",
    )
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    journal = protected_root / "pending.jsonl"
    journal.write_text(
        json.dumps(
            {
                "status": "db_committed_purge_pending",
                "run_id": "run-resume",
                "release_tag": "runtime-20260805-c9de1cdf",
                "runtime_sha": "c" * 40,
                "shutdown_receipt_sha256": "d" * 64,
                "inventory": {"packet": "fresh"},
                "receipt": {"status": "db_committed_purge_pending"},
                "prior_service_states": {
                    service: "stopped" for service in REQUIRED_WRITER_SERVICES
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runtime = _RuntimeOperator(runtime_sha="c" * 40)
    data = _DataOperator(apply_status="applied")
    gate = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"}
    )

    result = gate.resume(
        request,
        journal_path=journal,
        runtime_operator=runtime,
        data_operator=data,
    )

    assert result["status"] == "completed"
    assert data.calls == [
        ("preflight",),
        ("finalize",),
        ("verify",),
        ("sync_direct", ("1m", "1d", "1w")),
        ("aggregate", ("5m", "15m", "30m", "60m")),
    ]
    assert runtime.restart_calls == 1


def test_resume_rejects_journal_runtime_drift_before_stop(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        label: tmp_path / f"data/{label}" for label in ("raw", "canonical", "processed")
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text(
        "\n".join(f"keep_{index}" for index in range(69)) + "\n",
        encoding="utf-8",
    )
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    journal = protected_root / "pending.jsonl"
    journal.write_text(
        json.dumps(
            {
                "status": "db_committed_purge_pending",
                "run_id": "run-drift",
                "release_tag": request.release_tag,
                "runtime_sha": "e" * 40,
                "shutdown_receipt_sha256": "d" * 64,
                "inventory": {"packet": "fresh"},
                "receipt": {"status": "applied"},
                "prior_service_states": {
                    service: "stopped" for service in REQUIRED_WRITER_SERVICES
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runtime = _RuntimeOperator(runtime_sha="c" * 40)

    result = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"}
    ).resume(
        request,
        journal_path=journal,
        runtime_operator=runtime,
        data_operator=_DataOperator(apply_status="applied"),
    )

    assert result["status"] == "rejected"
    assert result["phase"] == "preflight"
    assert runtime.writer_states() == {
        service: "stopped" for service in REQUIRED_WRITER_SERVICES
    }
    assert runtime.checkout_calls == []


def test_execute_preflights_before_stopping_and_restores_exact_prior_states(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        label: tmp_path / f"data/{label}" for label in ("raw", "canonical", "processed")
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text(
        "\n".join(f"keep_{index}" for index in range(69)) + "\n",
        encoding="utf-8",
    )
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    running = (
        "com.guiyi.quant-htdy-s610-one-day-observer",
        "com.guiyi.quant-htdy-s610-observer",
    )
    runtime = _RuntimeOperator(running=running)
    data = _DataOperator(apply_status="applied")

    result = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"}
    ).execute(request, runtime_operator=runtime, data_operator=data)

    expected = {
        service: ("running" if service in running else "stopped")
        for service in REQUIRED_WRITER_SERVICES
    }
    assert result["status"] == "completed"
    assert result["service_states"] == expected
    assert runtime.restart_targets == [expected]
    assert runtime.writer_states() == expected


def test_execute_runs_runtime_and_data_preflight_before_stop(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        label: tmp_path / f"data/{label}" for label in ("raw", "canonical", "processed")
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text(
        "\n".join(f"keep_{index}" for index in range(69)) + "\n",
        encoding="utf-8",
    )
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    events: list[str] = []

    class Runtime(_RuntimeOperator):
        def preflight(self, **kwargs):
            events.append("runtime_preflight")
            return super().preflight(**kwargs)

        def stop_writer_services(self):
            events.append("stop")
            return super().stop_writer_services()

    class Data(_DataOperator):
        def preflight(self, request):
            events.append("data_preflight")
            return super().preflight(request)

    result = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: (
            events.append("inventory") or {"packet": "fresh"}
        )
    ).execute(
        request,
        runtime_operator=Runtime(),
        data_operator=Data(apply_status="applied"),
    )

    assert result["status"] == "completed"
    assert events[:4] == [
        "runtime_preflight",
        "data_preflight",
        "stop",
        "inventory",
    ]


def test_postcommit_refresh_failure_writes_resumable_journal_and_keeps_stopped(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        label: tmp_path / f"data/{label}" for label in ("raw", "canonical", "processed")
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text(
        "\n".join(f"keep_{index}" for index in range(69)) + "\n",
        encoding="utf-8",
    )
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )

    class FailingRefresh(_DataOperator):
        def sync_direct(self, _products, _frequencies):
            raise RuntimeError("provider failed")

    runtime = _RuntimeOperator(running=("com.guiyi.quant-htdy-s610-observer",))
    result = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"},
        run_id_factory=lambda: "run-refresh-failed",
    ).execute(
        request,
        runtime_operator=runtime,
        data_operator=FailingRefresh(apply_status="applied"),
    )

    journal = protected_root / "product-retirement-run-refresh-failed.jsonl"
    payload = json.loads(journal.read_text(encoding="utf-8"))
    assert result["status"] == "db_committed_purge_pending"
    assert result["phase"] == "postcommit_refresh"
    assert payload["status"] == "db_committed_purge_pending"
    assert payload["phase"] == "postcommit_refresh"
    assert payload["receipt"]["status"] == "applied"
    assert (
        payload["prior_service_states"]["com.guiyi.quant-htdy-s610-observer"]
        == "running"
    )
    assert runtime.writer_states() == {
        service: "stopped" for service in REQUIRED_WRITER_SERVICES
    }


def test_execution_service_plan_declares_fixed_frequency_contract(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text(
        "\n".join(f"keep_{index}" for index in range(69)) + "\n",
        encoding="utf-8",
    )
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )

    plan = ProductRetirementExecutionService(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"}
    ).plan(request)

    assert plan["status"] == "planned"
    assert plan["active_product_count"] == 69
    assert plan["direct_frequencies"] == ["1m", "1d", "1w"]
    assert plan["derived_frequencies"] == ["5m", "15m", "30m", "60m"]
    assert plan["mapping_overlap_trading_days"] == 10
