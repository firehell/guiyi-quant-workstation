from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

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


def test_orchestrator_materializes_c2_mapping_before_full_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_orchestrator_module()
    order: list[str] = []
    args = SimpleNamespace(
        confirm_deploy=True,
        approval_hash="a" * 64,
        activation_receipt=Path("/activation.json"),
    )

    monkeypatch.setattr(module, "parse_args", lambda _argv: args)
    monkeypatch.setattr(
        module,
        "_prepare_c2_mapping",
        lambda _args: order.append("mapping"),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "_preflight",
        lambda _args: order.append("preflight") or {},
    )
    monkeypatch.setattr(module, "_commands", lambda *_args: {})
    monkeypatch.setattr(
        module,
        "execute_deployment_steps",
        lambda **_kwargs: True,
    )

    assert module.main([]) == 0
    assert order == ["mapping", "preflight"]


def test_schema_v7_preactivation_does_not_require_activation_receipt(
    tmp_path: Path,
) -> None:
    from app.services.htdy_s6_10_runtime_support import (
        _schema_v7_allowed_bucket_ends,
    )

    parent = {"schema_version": 7}
    environ = {
        "GUIYI_HTDY_S610_ACTIVATION_RECEIPT": str(
            tmp_path / "missing.json"
        )
    }

    assert (
        _schema_v7_allowed_bucket_ends(
            parent_packet=parent,
            environ=environ,
            required=False,
        )
        is None
    )
    with pytest.raises(
        Exception,
        match="activation_allowlist_invalid",
    ):
        _schema_v7_allowed_bucket_ends(
            parent_packet=parent,
            environ=environ,
            required=True,
        )


def _c2_mapping_args(
    module: Any,
    tmp_path: Path,
) -> SimpleNamespace:
    output = tmp_path / "approval"
    output.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    deployment_path = output / "deployment_packet.json"
    parent_path = output / "parent_packet.json"
    c2_receipt_path = output / "approval_c2_receipt.json"
    signature_path = output / "approval_c2_receipt.json.sig"
    signers_path = output / "approved_signers"
    deployment = {
        "schema_version": 1,
        "packet_type": "s6_10_schema_v7_code_only_deployment",
        "source_commit": "1" * 40,
        "target_runtime_commit": "1" * 40,
    }
    deployment["packet_hash"] = module.canonical_hash(deployment)
    deployment_path.write_text(json.dumps(deployment), encoding="utf-8")
    parent = {
        "schema_version": 7,
        "window_mode": "complete_trading_day",
        "complete_trading_day_claim_allowed": True,
        "activation_deadline": "2099-07-29T20:40:00+08:00",
        "trading_days": ["2099-07-30"],
        "bindings": {
            "source_commit": "1" * 40,
            "runtime_commit": "1" * 40,
            "pre_activation_runtime_commit": "0" * 40,
            "artifact_paths": {
                "deployment_packet": str(deployment_path),
                "runtime_root": str(runtime),
            },
        },
    }
    parent["packet_hash"] = module.canonical_hash(parent)
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    c2_receipt_path.write_text(
        json.dumps({"approved_at": "2026-07-29T12:00:00+00:00"}),
        encoding="utf-8",
    )
    signature_path.write_text("signature", encoding="utf-8")
    signers_path.write_text("signers", encoding="utf-8")
    return SimpleNamespace(
        parent=parent_path,
        approval_hash=parent["packet_hash"],
        approval_c2_receipt=c2_receipt_path,
        approval_c2_hash="a" * 64,
        approval_c2_signature=signature_path,
        approved_signers=signers_path,
        deployment_packet=deployment_path,
        output_dir=output,
    )


def _patch_c2_mapping_preconditions(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_git(root: Path, *arguments: str) -> str:
        if arguments == ("status", "--porcelain=v1"):
            return ""
        if arguments == ("rev-parse", "HEAD"):
            return (
                "0" * 40
                if str(root).endswith("runtime")
                else "1" * 40
            )
        raise AssertionError(arguments)

    monkeypatch.setattr(module, "_git", fake_git)
    monkeypatch.setattr(
        module,
        "_runtime_env_values",
        lambda: {
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": "false",
            "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED": "false",
            "GUIYI_WECHAT_AUTOSEND_ENABLED": "false",
        },
    )


def test_c2_mapping_invalid_signature_has_zero_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_orchestrator_module()
    args = _c2_mapping_args(module, tmp_path)
    _patch_c2_mapping_preconditions(module, monkeypatch)
    monkeypatch.setitem(
        sys.modules,
        "jm_htdy_s6_10_remaining_window_gate",
        SimpleNamespace(
            _verify_signed_c2=lambda **_kwargs: (_ for _ in ()).throw(
                ValueError("approval_c2_receipt_invalid")
            )
        ),
    )

    with pytest.raises(ValueError, match="approval_c2_receipt_invalid"):
        module._prepare_c2_mapping(args)
    assert not (args.output_dir / "daily_mapping").exists()


def test_c2_mapping_commits_before_create_only_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_orchestrator_module()
    args = _c2_mapping_args(module, tmp_path)
    _patch_c2_mapping_preconditions(module, monkeypatch)
    import app.db.session as db_session
    import app.services.htdy_s6_10_daily_mapping as mapping
    import app.services.htdy_s6_10_long_running_runtime_gate as runtime_gate
    import app.services.rqdata_ingest.client as rq_client

    order: list[str] = []

    class FakeSession:
        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def commit(self) -> None:
            order.append("commit")

        def rollback(self) -> None:
            order.append("rollback")

    receipt = {
        "receipt_hash": "b" * 64,
        "actual_contract": "JM9999",
    }
    result = SimpleNamespace(
        receipt=receipt,
        mapping_sha256="c" * 64,
        actual_contract="JM9999",
    )
    monkeypatch.setitem(
        sys.modules,
        "jm_htdy_s6_10_remaining_window_gate",
        SimpleNamespace(_verify_signed_c2=lambda **_kwargs: None),
    )
    monkeypatch.setattr(db_session, "SessionLocal", FakeSession)
    monkeypatch.setattr(rq_client, "RqDataClient", lambda **_kwargs: object())
    monkeypatch.setattr(
        mapping,
        "resolve_or_create_s610_c2_daily_mapping",
        lambda *_args, **_kwargs: order.append("resolve") or result,
    )

    def publish(
        payload: dict[str, Any],
        *,
        root: Path,
        trading_day: Any,
        create: bool,
    ) -> dict[str, Any]:
        order.append("publish")
        assert order == ["resolve", "commit", "publish"]
        assert create is True
        path = root / str(trading_day) / "mapping_receipt.json"
        path.parent.mkdir()
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(
        runtime_gate,
        "publish_daily_mapping_receipt_create_only",
        publish,
    )

    identity = module._prepare_c2_mapping(args)
    assert order == ["resolve", "commit", "publish"]
    assert identity["actual_contract"] == "JM9999"
    assert identity["mapping_sha256"] == "c" * 64


def test_c2_mapping_existing_receipt_rebinds_without_rqdata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_orchestrator_module()
    args = _c2_mapping_args(module, tmp_path)
    _patch_c2_mapping_preconditions(module, monkeypatch)
    import app.db.session as db_session
    import app.services.htdy_s6_10_daily_mapping as mapping
    import app.services.rqdata_ingest.client as rq_client

    receipt = {
        "receipt_hash": "b" * 64,
        "actual_contract": "JM9999",
    }
    receipt_path = (
        args.output_dir
        / "daily_mapping"
        / "2099-07-30"
        / "mapping_receipt.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    class FakeSession:
        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def rollback(self) -> None:
            return None

    result = SimpleNamespace(
        mapping_sha256="c" * 64,
        actual_contract="JM9999",
    )
    monkeypatch.setitem(
        sys.modules,
        "jm_htdy_s6_10_remaining_window_gate",
        SimpleNamespace(_verify_signed_c2=lambda **_kwargs: None),
    )
    monkeypatch.setattr(db_session, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        mapping,
        "verify_s610_c2_daily_mapping_receipt",
        lambda *_args, **_kwargs: result,
    )
    monkeypatch.setattr(
        rq_client,
        "RqDataClient",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("rqdata_must_not_be_called")
        ),
    )

    identity = module._prepare_c2_mapping(args)
    assert identity["receipt_hash"] == "b" * 64


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


def test_signal_runtime_wait_covers_stale_scheduler_lock_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_orchestrator_module()
    calls = 0

    class Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        scheduler = {
            "status": "ok",
            "signal_events_enabled": calls > 60,
            "signal_event_gate_status": (
                "authorized" if calls > 60 else "disabled"
            ),
            "signal_event_authorization_hash": (
                "a" * 64 if calls > 60 else None
            ),
            "heartbeat_age_seconds": 0,
        }
        return Response({"components": {"scheduler": scheduler}})

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(module.json, "load", lambda value: value.payload)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    module._wait_signal_runtime(expected_parent_hash="a" * 64)

    assert calls == 61


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
        elif command[:3] == ["launchctl", "kickstart", "-k"]:
            assert command[-1].endswith("/com.guiyi.quant-api")
            calls.append("restart_api")

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
        "restart_api",
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


def test_after_market_restore_stops_before_api_restart_when_budget_spent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    now = [0.0]
    calls: list[str] = []
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    class Redis:
        def exists(self, _key: str) -> bool:
            return False

    def run(command, **_kwargs):
        calls.append(command[-1])
        if command[1].endswith(
            "configure-after-market-automation.sh"
        ):
            now[0] = 31.0

    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(
        module,
        "_after_market_redis_connection",
        lambda _environment, **_kwargs: Redis(),
    )

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

    assert calls == [
        "--bootout",
        "a" * 64,
    ]


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
    diagnostic_path = tmp_path / "restore_diagnostic.json"

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
    ) as captured:
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
            diagnostic_path=diagnostic_path,
        )

    diagnostic = json.loads(
        diagnostic_path.read_text(encoding="utf-8")
    )
    assert diagnostic["status"] == "failed"
    assert diagnostic["environment"]["matches"] is True
    assert diagnostic["launchd"]["pid"] == 12345
    assert diagnostic["api"]["authorization_hash_matches"] is True
    assert diagnostic["heartbeat"]["owner_valid"] is False
    assert diagnostic["diagnostic_hash"]
    assert captured.value.restore_diagnostic_path == str(
        diagnostic_path
    )


def test_after_market_diagnostic_keeps_api_success_when_redis_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from redis.exceptions import RedisError

    module = _load_orchestrator_module()
    expected_packet = tmp_path / "enable.json"
    expected_hash = "a" * 64
    diagnostic_path = tmp_path / "restore_diagnostic.json"
    now = [0.0]

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
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda _seconds: now.__setitem__(0, 2.0),
    )

    def failed_heartbeat():
        raise RedisError("unavailable")

    with pytest.raises(
        RuntimeError,
        match="after_market_restore_unverified",
    ):
        module._verify_after_market(
            tmp_path,
            expected_packet=expected_packet,
            expected_hash=expected_hash,
            timeout_seconds=1,
            heartbeat_probe=failed_heartbeat,
            diagnostic_path=diagnostic_path,
        )

    diagnostic = json.loads(
        diagnostic_path.read_text(encoding="utf-8")
    )
    assert diagnostic["api"]["reachable"] is True
    assert diagnostic["api"]["error_type"] is None
    assert diagnostic["heartbeat"]["available"] is False
    assert diagnostic["heartbeat"]["error_type"] == "RedisError"


def test_after_market_diagnostic_does_not_poll_heartbeat_when_api_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    expected_packet = tmp_path / "enable.json"
    expected_hash = "a" * 64
    diagnostic_path = tmp_path / "restore_diagnostic.json"
    now = [0.0]
    heartbeat_calls = 0

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
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("api unavailable")
        ),
    )
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda _seconds: now.__setitem__(0, 2.0),
    )

    def heartbeat_probe():
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        return {}

    with pytest.raises(
        RuntimeError,
        match="after_market_restore_unverified",
    ):
        module._verify_after_market(
            tmp_path,
            expected_packet=expected_packet,
            expected_hash=expected_hash,
            timeout_seconds=1,
            heartbeat_probe=heartbeat_probe,
            diagnostic_path=diagnostic_path,
        )

    diagnostic = json.loads(
        diagnostic_path.read_text(encoding="utf-8")
    )
    assert diagnostic["api"]["reachable"] is False
    assert diagnostic["api"]["error_type"] == "OSError"
    assert diagnostic["heartbeat"]["error_type"] is None
    assert heartbeat_calls == 0


def test_after_market_diagnostic_does_not_swallow_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    expected_packet = tmp_path / "enable.json"
    expected_hash = "a" * 64
    diagnostic_path = tmp_path / "restore_diagnostic.json"

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

    with pytest.raises(RuntimeError, match="probe invariant") as captured:
        module._verify_after_market(
            tmp_path,
            expected_packet=expected_packet,
            expected_hash=expected_hash,
            timeout_seconds=1,
            heartbeat_probe=lambda: (_ for _ in ()).throw(
                RuntimeError("probe invariant")
            ),
            diagnostic_path=diagnostic_path,
        )

    diagnostic = json.loads(
        diagnostic_path.read_text(encoding="utf-8")
    )
    assert diagnostic["api"]["reachable"] is True
    assert diagnostic["heartbeat"]["error_type"] == "RuntimeError"
    assert captured.value.restore_diagnostic_path == str(diagnostic_path)


def test_after_market_launchd_timeout_uses_budget_after_env_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    now = [0.0]
    observed_timeouts: list[float] = []

    def runtime_values():
        now[0] = 4.0
        return {}

    def run(*_args, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        now[0] = 6.0
        return subprocess.CompletedProcess(
            args=(),
            returncode=1,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(module, "_runtime_env_values", runtime_values)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    with pytest.raises(
        RuntimeError,
        match="after_market_restore_unverified",
    ):
        module._verify_after_market(
            tmp_path,
            expected_packet=tmp_path / "enable.json",
            expected_hash="a" * 64,
            deadline=5.0,
        )

    assert observed_timeouts == [1.0]


def test_after_market_diagnostic_normalizes_untrusted_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    expected_packet = tmp_path / "enable.json"
    expected_hash = "a" * 64
    diagnostic_path = tmp_path / "restore_diagnostic.json"
    now = [0.0]

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
                            "enabled": "yes",
                            "status": "secret-" + "x" * 1000,
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
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda _seconds: now.__setitem__(0, 2.0),
    )

    with pytest.raises(RuntimeError):
        module._verify_after_market(
            tmp_path,
            expected_packet=expected_packet,
            expected_hash=expected_hash,
            timeout_seconds=1,
            heartbeat_probe=lambda: {
                "generated_at": "secret-" + "x" * 1000,
                "status": "secret-" + "x" * 1000,
                "lock_status": "secret-" + "x" * 1000,
                "pid": "secret",
            },
            diagnostic_path=diagnostic_path,
        )

    diagnostic = json.loads(
        diagnostic_path.read_text(encoding="utf-8")
    )
    assert diagnostic["api"]["enabled"] is None
    assert diagnostic["api"]["status"] == "invalid"
    assert diagnostic["heartbeat"]["status"] == "invalid"
    assert diagnostic["heartbeat"]["pid"] is None
    assert diagnostic["heartbeat"]["lock_status"] == "invalid"
    assert diagnostic["heartbeat"]["generated_at"] == "invalid"
    assert "secret-" not in diagnostic_path.read_text(encoding="utf-8")


def test_after_market_diagnostic_is_create_only(tmp_path: Path) -> None:
    module = _load_orchestrator_module()
    diagnostic_path = tmp_path / "restore_diagnostic.json"
    observation = {"healthy": False}

    module._publish_after_market_restore_diagnostic(
        diagnostic_path,
        status="failed",
        expected_packet=tmp_path / "enable.json",
        expected_hash="a" * 64,
        minimum_heartbeat_at=None,
        observation=observation,
    )
    with pytest.raises(FileExistsError):
        module._publish_after_market_restore_diagnostic(
            diagnostic_path,
            status="failed",
            expected_packet=tmp_path / "enable.json",
            expected_hash="a" * 64,
            minimum_heartbeat_at=None,
            observation=observation,
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

    monotonic_values = iter((0.0, 0.5, 1.0, 3.0))
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
        "activate_s610",
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
        if step.name == "switch_runtime":
            raise RuntimeError(step.name)
        if step.name == "rollback_runtime":
            error = RuntimeError(step.name)
            error.restore_diagnostic_path = "/safe/diagnostic.json"
            raise error

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
            "restore_diagnostic_path": "/safe/diagnostic.json",
        }
    ]


def test_failure_receipt_binds_rollback_restore_diagnostic(
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    diagnostic_path = tmp_path / "rollback_restore_diagnostic.json"
    diagnostic_path.write_text('{"status":"failed"}\n', encoding="utf-8")
    error = RuntimeError("forward failure")
    error.rollback_failures = [
        {
            "step": "rollback_restore_after_market",
            "error_type": "RuntimeError",
            "restore_diagnostic_path": str(diagnostic_path),
        }
    ]
    args = module.argparse.Namespace(
        output_dir=tmp_path,
        approval_hash="a" * 64,
    )

    module._write_failure(
        args,
        failed_step="switch_runtime",
        error=error,
    )

    receipt = json.loads(
        (tmp_path / "deployment_failed.json").read_text(
            encoding="utf-8"
        )
    )
    rollback = receipt["rollback_failures"][0]
    assert rollback["restore_diagnostic"] == {
        "path": str(diagnostic_path.resolve()),
        "sha256": module._file_sha256(diagnostic_path),
    }
    assert "restore_diagnostic_path" not in rollback
