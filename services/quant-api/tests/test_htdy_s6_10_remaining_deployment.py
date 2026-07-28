from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys

import pytest


def _load_orchestrator_module():
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "jm_htdy_s6_10_remaining_deploy.py"
    )
    spec = importlib.util.spec_from_file_location(
        "jm_htdy_s6_10_remaining_deploy_test_module",
        script,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_orchestrator_launchd_probe_requires_running_state_and_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_orchestrator_module()
    monkeypatch.setattr(
        module,
        "_launchd_snapshot",
        lambda _label: subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout="state = running\npid = 12345\n",
            stderr="",
        ),
    )

    assert module._launchd_running("com.guiyi.test") is True

    monkeypatch.setattr(
        module,
        "_launchd_snapshot",
        lambda _label: subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout="state = running\npid = 0\n",
            stderr="",
        ),
    )
    assert module._launchd_running("com.guiyi.test") is False


def test_after_market_install_retries_transient_launchctl_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    attempts: list[list[str]] = []

    timeouts: list[float | None] = []

    def run(command, **kwargs):
        attempts.append(command)
        timeouts.append(kwargs.get("timeout_seconds"))
        if len(attempts) == 1:
            raise subprocess.CalledProcessError(5, command)

    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    module._install_after_market_with_retry(
        tmp_path,
        environment={},
        deadline=module.time.monotonic() + 5,
    )

    assert len(attempts) == 2
    assert attempts[-1][-1] == "--confirm-load"
    assert all(
        timeout is not None and 0 < timeout <= 5
        for timeout in timeouts
    )


def test_after_market_lock_waits_for_natural_release_without_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_orchestrator_module()

    class Redis:
        def __init__(self) -> None:
            self.states = iter((True, True, False))
            self.exists_calls = 0

        def exists(self, _key: str) -> bool:
            self.exists_calls += 1
            return next(self.states)

        def delete(self, _key: str) -> None:
            raise AssertionError("singleton lock must never be deleted")

    redis = Redis()
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    module._wait_after_market_lock_release(
        {},
        deadline=module.time.monotonic() + 5,
        poll_interval_seconds=0,
        redis_factory=lambda *_args, **_kwargs: redis,
    )

    assert redis.exists_calls == 3


def test_after_market_lock_wait_is_bounded_when_lock_never_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_orchestrator_module()
    now = [0.0]

    class Redis:
        def exists(self, _key: str) -> bool:
            return True

    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda _seconds: now.__setitem__(0, 2.0),
    )

    with pytest.raises(
        RuntimeError,
        match="after_market_lock_release_timeout",
    ):
        module._wait_after_market_lock_release(
            {},
            deadline=1,
            redis_factory=lambda *_args, **_kwargs: Redis(),
        )


def test_after_market_lock_wait_bounds_redis_io_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from redis.exceptions import TimeoutError as RedisTimeoutError

    module = _load_orchestrator_module()
    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda _seconds: now.__setitem__(0, 2.0),
    )

    def redis_factory(*_args, **_kwargs):
        raise RedisTimeoutError("timeout")

    with pytest.raises(
        RuntimeError,
        match="after_market_lock_release_timeout",
    ):
        module._wait_after_market_lock_release(
            {},
            deadline=1,
            redis_factory=redis_factory,
        )


def test_after_market_health_uses_direct_owner_with_old_runtime_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    expected_packet = tmp_path / "enable.json"
    expected_hash = "a" * 64
    launchd_attempts = 0

    monkeypatch.setattr(
        module,
        "_runtime_env_values",
        lambda: {
            "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET": str(
                expected_packet
            ),
            "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH": expected_hash,
            "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED": "true",
        },
    )

    def run(*_args, **_kwargs):
        nonlocal launchd_attempts
        launchd_attempts += 1
        return subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout="state = running\npid = 12345\n",
            stderr="",
        )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {
                    "components": {
                        "after_market_scheduler": {
                            "enabled": True,
                            "status": "ok",
                            "authorization_hash": expected_hash,
                        }
                    }
                }
            ).encode()

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(),
    )
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    def heartbeat_probe():
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "running",
            "error_type": None,
            "lock_status": "held",
            "pid": 12345 if launchd_attempts == 12 else 99999,
        }

    module._verify_after_market(
        tmp_path,
        expected_packet=expected_packet,
        expected_hash=expected_hash,
        timeout_seconds=210,
        poll_interval_seconds=0,
        heartbeat_probe=heartbeat_probe,
    )

    assert launchd_attempts == 12


def test_after_market_restore_boots_out_before_lock_wait(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    calls: list[str] = []

    class Redis:
        def exists(self, _key: str) -> bool:
            calls.append("lock_probe")
            return False

    def run(command, **_kwargs):
        if command[-1] == "--bootout":
            calls.append("bootout")
        elif command[1].endswith(
            "configure-after-market-automation.sh"
        ):
            calls.append("configure")

    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(
        module,
        "_after_market_redis_connection",
        lambda _environment, **_kwargs: Redis(),
    )
    monkeypatch.setattr(
        module,
        "_install_after_market_with_retry",
        lambda *_args, **_kwargs: calls.append("install"),
    )
    monkeypatch.setattr(
        module,
        "_verify_after_market",
        lambda *_args, **_kwargs: calls.append("verify"),
    )

    module._restore_after_market_service(
        tmp_path,
        environment={},
        expected_packet=tmp_path / "enable.json",
        expected_hash="a" * 64,
        timeout_seconds=30,
    )

    assert calls == [
        "bootout",
        "lock_probe",
        "configure",
        "install",
        "verify",
    ]


def test_after_market_restore_stops_before_configure_when_budget_spent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    now = [0.0]
    calls: list[str] = []
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def run(command, **_kwargs):
        calls.append(command[-1])
        if command[-1] == "--bootout":
            now[0] = 31.0

    monkeypatch.setattr(module, "_run", run)

    with pytest.raises(
        RuntimeError,
        match="after_market_restore_timeout",
    ):
        module._restore_after_market_service(
            tmp_path,
            environment={},
            expected_packet=tmp_path / "enable.json",
            expected_hash="a" * 64,
            timeout_seconds=30,
        )

    assert calls == ["--bootout"]


def test_after_market_install_retry_cannot_exceed_restore_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    now = [0.0]
    attempts = 0
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def run(command, **_kwargs):
        nonlocal attempts
        attempts += 1
        now[0] = 6.0
        raise subprocess.CalledProcessError(5, command)

    monkeypatch.setattr(module, "_run", run)

    with pytest.raises(
        RuntimeError,
        match="after_market_restore_timeout",
    ):
        module._install_after_market_with_retry(
            tmp_path,
            environment={},
            deadline=5,
        )

    assert attempts == 1


def test_after_market_install_retries_bounded_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    attempts = 0

    def run(command, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise subprocess.TimeoutExpired(command, timeout=1)

    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    module._install_after_market_with_retry(
        tmp_path,
        environment={},
        deadline=module.time.monotonic() + 5,
    )

    assert attempts == 2


@pytest.mark.parametrize(
    "overrides",
    (
        {"generated_at": "2026-07-29T08:00:00"},
        {"status": "mystery"},
        {"pid": True},
        {"pid": 0},
    ),
)
def test_after_market_owner_rejects_malformed_heartbeat(
    overrides: dict[str, object],
) -> None:
    module = _load_orchestrator_module()
    now = datetime(2026, 7, 29, 8, 0, 10, tzinfo=UTC)
    heartbeat = {
        "generated_at": datetime(
            2026,
            7,
            29,
            8,
            0,
            5,
            tzinfo=UTC,
        ).isoformat(),
        "status": "running",
        "lock_status": "held",
        "pid": 12345,
        **overrides,
    }

    assert module._after_market_heartbeat_owner_is_valid(
        heartbeat,
        launchd_pid=12345,
        now=now,
        minimum_heartbeat_at=datetime(
            2026,
            7,
            29,
            8,
            0,
            tzinfo=UTC,
        ),
    ) is False


def test_after_market_health_rejects_heartbeat_older_than_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    expected_packet = tmp_path / "enable.json"
    expected_hash = "a" * 64
    minimum_heartbeat_at = datetime.now(UTC)

    monkeypatch.setattr(
        module,
        "_runtime_env_values",
        lambda: {
            "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET": str(
                expected_packet
            ),
            "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH": expected_hash,
            "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED": "true",
        },
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout="state = running\npid = 12345\n",
            stderr="",
        ),
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {
                    "components": {
                        "after_market_scheduler": {
                            "enabled": True,
                            "status": "ok",
                            "authorization_hash": expected_hash,
                        }
                    }
                }
            ).encode()

    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(),
    )
    monotonic_now = [0.0]
    monkeypatch.setattr(
        module.time,
        "monotonic",
        lambda: monotonic_now[0],
    )
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda _seconds: monotonic_now.__setitem__(0, 2.0),
    )

    with pytest.raises(
        RuntimeError,
        match="after_market_restore_unverified",
    ):
        module._verify_after_market(
            tmp_path,
            expected_packet=expected_packet,
            expected_hash=expected_hash,
            timeout_seconds=1,
            heartbeat_probe=lambda: {
                "generated_at": (
                    minimum_heartbeat_at - timedelta(seconds=1)
                ).isoformat(),
                "status": "running",
                "lock_status": "held",
                "pid": 12345,
            },
            minimum_heartbeat_at=minimum_heartbeat_at,
        )


def test_after_market_health_wait_is_bounded_by_monotonic_deadline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    launchd_attempts = 0

    monkeypatch.setattr(module, "_runtime_env_values", lambda: {})

    def run(*_args, **_kwargs):
        nonlocal launchd_attempts
        launchd_attempts += 1
        return subprocess.CompletedProcess(
            args=(),
            returncode=1,
            stdout="",
            stderr="",
        )

    monotonic_values = iter((0.0, 0.5, 3.0))
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(
        module.time,
        "monotonic",
        lambda: next(monotonic_values),
    )

    with pytest.raises(
        RuntimeError,
        match="after_market_restore_unverified",
    ):
        module._verify_after_market(
            tmp_path,
            expected_packet=tmp_path / "enable.json",
            expected_hash="a" * 64,
            timeout_seconds=2,
            poll_interval_seconds=1,
        )

    assert launchd_attempts == 1


def test_orchestrator_rejects_execution_from_a_different_source_checkout(
    tmp_path: Path,
) -> None:
    from app.services.htdy_s6_10_remaining_deployment import (
        RemainingDeploymentError,
        validate_source_context,
    )

    with pytest.raises(RemainingDeploymentError, match="source_root_mismatch"):
        validate_source_context(
            actual_source_root=tmp_path / "wrong",
            orchestrator_source_root=tmp_path / "bound",
        )
def test_orchestrator_has_one_ordered_activation_sequence() -> None:
    from app.services.htdy_s6_10_remaining_deployment import (
        deployment_step_names,
    )

    assert deployment_step_names() == (
        "stop_s610_services",
        "pause_after_market",
        "switch_runtime",
        "restart_core_runtime",
        "write_deployment_receipt",
        "rebind_s607",
        "restore_after_market",
        "verify_activation_ready",
        "configure_s610",
        "create_activation_receipt",
        "start_s610_services",
        "verify_post_activation",
    )


def test_orchestrator_failure_runs_complete_fail_closed_sequence() -> None:
    from app.services.htdy_s6_10_remaining_deployment import (
        DeploymentStep,
        execute_deployment_steps,
    )

    observed: list[str] = []
    failure: list[str] = []

    def run(step: DeploymentStep) -> None:
        observed.append(step.name)
        if step.name == "switch_runtime":
            raise RuntimeError("boom")

    execute_deployment_steps(
        steps=(
            DeploymentStep("stop_s610_services"),
            DeploymentStep("pause_after_market"),
            DeploymentStep("switch_runtime"),
        ),
        rollback_steps=(
            DeploymentStep("rollback_stop_s610"),
            DeploymentStep("rollback_disable_s610"),
            DeploymentStep("rollback_runtime"),
            DeploymentStep("rollback_restore_after_market"),
        ),
        runner=run,
        failure_recorder=lambda error: failure.append(type(error).__name__),
    )

    assert observed == [
        "stop_s610_services",
        "pause_after_market",
        "switch_runtime",
        "rollback_stop_s610",
        "rollback_disable_s610",
        "rollback_runtime",
        "rollback_restore_after_market",
    ]
    assert failure == ["RuntimeError"]


def test_orchestrator_reports_rollback_failures_instead_of_suppressing() -> None:
    from app.services.htdy_s6_10_remaining_deployment import (
        DeploymentStep,
        execute_deployment_steps,
    )

    captured: list[BaseException] = []

    def run(step: DeploymentStep) -> None:
        if step.name in {"switch_runtime", "rollback_runtime"}:
            raise RuntimeError(step.name)

    assert execute_deployment_steps(
        steps=(DeploymentStep("switch_runtime"),),
        rollback_steps=(
            DeploymentStep("rollback_disable_s610"),
            DeploymentStep("rollback_runtime"),
        ),
        runner=run,
        failure_recorder=captured.append,
    ) is False

    assert captured[0].deployment_step == "switch_runtime"
    assert captured[0].rollback_failures == [
        {
            "step": "rollback_runtime",
            "error_type": "RuntimeError",
        }
    ]
