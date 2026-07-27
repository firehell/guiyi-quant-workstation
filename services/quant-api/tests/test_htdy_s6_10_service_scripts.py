from __future__ import annotations

import os
from pathlib import Path
import subprocess


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
