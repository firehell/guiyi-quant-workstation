from __future__ import annotations

import os
from pathlib import Path
import subprocess
import hashlib
import json


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run(
    script: str,
    *args: str,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / script), *args],
        cwd=PROJECT_ROOT,
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def test_s610_runtime_config_is_atomic_and_disable_preserves_eod(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime_env = runtime / "project.env"
    runtime_env.write_text(
        "\n".join(
            (
                "GUIYI_LIVE_RUNTIME_ENABLED=true",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
                "GUIYI_WECHAT_AUTOSEND_ENABLED=false",
                "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=false",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    parent = tmp_path / "parent.json"
    parent.write_text("{}\n", encoding="utf-8")
    eod = tmp_path / "eod.json"
    eod.write_text("{}\n", encoding="utf-8")
    bundle = tmp_path / "approval_c_bundle.json"
    bundle.write_text("{}\n", encoding="utf-8")
    approval_receipt = tmp_path / "approval_c_receipt.json"
    approval_receipt.write_text("{}\n", encoding="utf-8")
    approval_signature = tmp_path / "approval_c_receipt.sig"
    approval_signature.write_text("sig\n", encoding="utf-8")
    approved_signers = tmp_path / "approved_signers"
    approved_signers.write_text("signer\n", encoding="utf-8")
    output = tmp_path / "evidence"
    output.mkdir()
    env = {
        "GUIYI_RUNTIME_DIR": str(runtime),
        "GUIYI_RUNTIME_ENV": str(runtime_env),
    }
    enabled = _run(
        "configure-htdy-s610-runtime.sh",
        "--enable",
        "--parent-packet",
        str(parent),
        "--approval-hash",
        "a" * 64,
        "--approval-c-bundle",
        str(bundle),
        "--approval-c-hash",
        "c" * 64,
        "--approval-c-receipt",
        str(approval_receipt),
        "--approval-c-signature",
        str(approval_signature),
        "--approval-c-approved-signers",
        str(approved_signers),
        "--output-dir",
        str(output),
        "--eod-packet",
        str(eod),
        "--eod-hash",
        "b" * 64,
        environment=env,
    )
    assert enabled.returncode == 0, enabled.stderr
    text = runtime_env.read_text(encoding="utf-8")
    assert "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=true" in text
    assert "GUIYI_HTDY_S610_REQUIRED=true" in text
    assert "GUIYI_WECHAT_AUTOSEND_ENABLED=false" in text
    assert "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true" in text

    disabled = _run(
        "configure-htdy-s610-runtime.sh",
        "--disable",
        environment=env,
    )
    assert disabled.returncode == 0, disabled.stderr
    text = runtime_env.read_text(encoding="utf-8")
    assert "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false" in text
    assert "GUIYI_HTDY_S610_REQUIRED=false" in text
    assert "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true" in text


def test_observer_installer_render_only_binds_exact_packet(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    packet = tmp_path / "parent.json"
    packet.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "evidence"
    output.mkdir()
    runtime_env = runtime / "project.env"
    runtime_env.write_text(
        "\n".join(
            (
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=true",
                "GUIYI_WECHAT_AUTOSEND_ENABLED=false",
                f"GUIYI_HTDY_S610_OUTPUT_DIR='{output}'",
                f"GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET='{packet}'",
                f"GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH={'a' * 64}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    render = tmp_path / "render"
    result = _run(
        "install-htdy-s610-observer.sh",
        "--render-only",
        environment={
            "GUIYI_PROJECT_ROOT": str(PROJECT_ROOT),
            "GUIYI_RUNTIME_DIR": str(runtime),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
            "GUIYI_S610_RENDER_DIR": str(render),
            "GUIYI_LOG_DIR": str(tmp_path / "logs"),
        },
    )
    assert result.returncode == 0, result.stderr
    plist = (
        render / "com.guiyi.quant-htdy-s610-observer.plist"
    ).read_text(encoding="utf-8")
    assert str(packet) in plist
    assert str(output) in plist
    assert "com.guiyi.quant-htdy-s610-observer" in plist
    local_runner = runtime / "run-htdy-s610-observer.sh"
    assert local_runner.is_file()
    assert os.access(local_runner, os.X_OK)
    assert str(local_runner) in plist
    assert (
        str(PROJECT_ROOT / "scripts" / "run-htdy-s610-observer.sh")
        not in plist
    )


def test_observer_runner_loads_runtime_environment_before_sampling(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    runtime_dir = tmp_path / "runtime-config"
    runtime_dir.mkdir()
    marker = tmp_path / "sample-env-ok"
    runtime_env = runtime_dir / "project.env"
    runtime_env.write_text(
        "\n".join(
            (
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=true",
                "GUIYI_WECHAT_AUTOSEND_ENABLED=false",
                f"GUIYI_TEST_SAMPLE_MARKER='{marker}'",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    parent = tmp_path / "parent.json"
    parent.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "evidence"
    output.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
[[ "${GUIYI_LIVE_SIGNAL_EVENTS_ENABLED:-}" == "true" ]]
[[ "${GUIYI_WECHAT_AUTOSEND_ENABLED:-}" == "false" ]]
touch "$GUIYI_TEST_SAMPLE_MARKER"
exit 42
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o700)

    result = subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts/run-htdy-s610-observer.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "GUIYI_PROJECT_ROOT": str(runtime_root),
            "GUIYI_RUNTIME_DIR": str(runtime_dir),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
            "GUIYI_HTDY_S610_OUTPUT_DIR": str(output),
            "GUIYI_HTDY_S610_PARENT_PACKET": str(parent),
            "GUIYI_HTDY_S610_APPROVAL_HASH": "a" * 64,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 42
    assert marker.is_file()


def test_schema_v5_runtime_config_binds_c2_and_bounded_dispatcher(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime_env = runtime / "project.env"
    runtime_env.write_text(
        "\n".join(
            (
                "GUIYI_LIVE_RUNTIME_ENABLED=true",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
                "GUIYI_WECHAT_AUTOSEND_ENABLED=false",
                "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts = {}
    for name in ("parent", "receipt", "signature", "signers"):
        path = tmp_path / name
        path.write_text("{}\n", encoding="utf-8")
        artifacts[name] = path
    output = tmp_path / "evidence"
    output.mkdir()
    env = {
        "GUIYI_RUNTIME_DIR": str(runtime),
        "GUIYI_RUNTIME_ENV": str(runtime_env),
    }
    enabled = _run(
        "configure-htdy-s610-one-day-runtime.sh",
        "--enable",
        "--parent-packet",
        str(artifacts["parent"]),
        "--approval-hash",
        "a" * 64,
        "--approval-c2-receipt",
        str(artifacts["receipt"]),
        "--approval-c2-hash",
        "b" * 64,
        "--approval-c2-signature",
        str(artifacts["signature"]),
        "--approved-signers",
        str(artifacts["signers"]),
        "--output-dir",
        str(output),
        environment=env,
    )
    assert enabled.returncode == 0, enabled.stderr
    text = runtime_env.read_text(encoding="utf-8")
    assert "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=true" in text
    assert "GUIYI_HTDY_S610_REQUIRED=true" in text
    assert "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED=true" in text
    assert "GUIYI_WECHAT_AUTOSEND_ENABLED=false" in text
    assert f"GUIYI_HTDY_S610_APPROVAL_C2_RECEIPT='{artifacts['receipt']}'" in text

    disabled = _run(
        "configure-htdy-s610-one-day-runtime.sh",
        "--disable",
        environment=env,
    )
    assert disabled.returncode == 0, disabled.stderr
    text = runtime_env.read_text(encoding="utf-8")
    assert "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false" in text
    assert "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED=false" in text
    assert "GUIYI_WECHAT_AUTOSEND_ENABLED=false" in text
    assert "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true" in text


def test_schema_v5_service_installer_renders_two_exact_services(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    output = tmp_path / "evidence"
    output.mkdir()
    identities: dict[str, Path] = {}
    identity_hashes: dict[str, str] = {}
    for service in ("observer", "dispatcher"):
        template = (
            PROJECT_ROOT
            / "deploy/launchd"
            / f"com.guiyi.quant-htdy-s610-one-day-{service}.plist.template"
        )
        runner = (
            PROJECT_ROOT
            / "scripts"
            / f"run-htdy-s610-one-day-{service}.sh"
        )
        identity = {
            "template_path": str(template),
            "template_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
            "runner_path": str(runner),
            "runner_sha256": hashlib.sha256(runner.read_bytes()).hexdigest(),
        }
        identity_path = tmp_path / f"{service}_identity.json"
        identity_path.write_text(
            json.dumps(identity, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        identities[service] = identity_path
        identity_hashes[service] = hashlib.sha256(
            identity_path.read_bytes()
        ).hexdigest()
    parent = tmp_path / "parent.json"
    parent.write_text(
        json.dumps(
            {
                "bindings": {
                    "artifact_paths": {
                        "observer_identity": str(identities["observer"]),
                        "delivery_identity": str(identities["dispatcher"]),
                    },
                    "observer_launchd_sha256": identity_hashes["observer"],
                    "delivery_launchd_sha256": identity_hashes["dispatcher"],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runtime_env = runtime / "project.env"
    runtime_env.write_text(
        "\n".join(
            (
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=true",
                "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED=true",
                "GUIYI_WECHAT_AUTOSEND_ENABLED=false",
                f"GUIYI_HTDY_S610_OUTPUT_DIR='{output}'",
                f"GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET='{parent}'",
                f"GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH={'a' * 64}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    render = tmp_path / "render"
    result = _run(
        "install-htdy-s610-one-day-services.sh",
        "--render-only",
        environment={
            "GUIYI_PROJECT_ROOT": str(PROJECT_ROOT),
            "GUIYI_RUNTIME_DIR": str(runtime),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
            "GUIYI_S610_RENDER_DIR": str(render),
            "GUIYI_LOG_DIR": str(tmp_path / "logs"),
        },
    )
    assert result.returncode == 0, result.stderr
    observer = (
        render / "com.guiyi.quant-htdy-s610-one-day-observer.plist"
    ).read_text(encoding="utf-8")
    dispatcher = (
        render / "com.guiyi.quant-htdy-s610-one-day-dispatcher.plist"
    ).read_text(encoding="utf-8")
    assert str(parent) in observer and str(parent) in dispatcher
    assert str(output) in observer and str(output) in dispatcher
    assert "one-day-observer" in observer
    assert "one-day-dispatcher" in dispatcher
    assert (runtime / "run-htdy-s610-one-day-observer.sh").is_file()
    assert (runtime / "run-htdy-s610-one-day-dispatcher.sh").is_file()
