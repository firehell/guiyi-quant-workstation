from __future__ import annotations

import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_values(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
        for key, value in [line.split("=", 1)]
    }


def test_configure_live_signal_events_enable_and_disable_only_three_keys(tmp_path) -> None:
    runtime_dir = tmp_path / "runtime support"
    runtime_dir.mkdir()
    runtime_env = runtime_dir / "project.env"
    runtime_env.write_text(
        "\n".join(
            (
                "UNCHANGED=value",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
                "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=",
                "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    packet = tmp_path / "approval packet.json"
    packet.write_text("{}\n", encoding="utf-8")
    approval_hash = "a" * 64
    environ = {
        **os.environ,
        "GUIYI_RUNTIME_DIR": str(runtime_dir),
        "GUIYI_RUNTIME_ENV": str(runtime_env),
    }

    enabled = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "configure-live-signal-events.sh"),
            "--enable",
            "--approval-packet",
            str(packet),
            "--approval-hash",
            approval_hash,
        ],
        env=environ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert enabled.returncode == 0
    values = _env_values(runtime_env)
    assert values == {
        "UNCHANGED": "value",
        "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": "true",
        "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET": f"'{packet}'",
        "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH": approval_hash,
    }
    assert str(packet) not in enabled.stdout
    assert approval_hash not in enabled.stdout
    sourced = subprocess.run(
        [
            "bash",
            "-c",
            'set -eu; source "$GUIYI_RUNTIME_ENV"; test "$GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET" = "$EXPECTED_PACKET"',
        ],
        env={**environ, "EXPECTED_PACKET": str(packet)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert sourced.returncode == 0, sourced.stderr

    disabled = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "configure-live-signal-events.sh"), "--disable"],
        env=environ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert disabled.returncode == 0
    values = _env_values(runtime_env)
    assert values["UNCHANGED"] == "value"
    assert values["GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"] == "false"
    assert values["GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET"] == ""
    assert values["GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH"] == ""


def test_configure_live_signal_events_round_trips_unicode_packet_path(tmp_path) -> None:
    runtime_dir = tmp_path / "runtime support"
    runtime_dir.mkdir()
    runtime_env = runtime_dir / "project.env"
    runtime_env.write_text(
        "\n".join(
            (
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false",
                "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=",
                "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    packet = tmp_path / "扩展盘" / "approval packet's.json"
    packet.parent.mkdir()
    packet.write_text("{}\n", encoding="utf-8")
    environ = {
        **os.environ,
        "GUIYI_RUNTIME_DIR": str(runtime_dir),
        "GUIYI_RUNTIME_ENV": str(runtime_env),
        "EXPECTED_PACKET": str(packet),
    }

    enabled = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "configure-live-signal-events.sh"),
            "--enable",
            "--approval-packet",
            str(packet),
            "--approval-hash",
            "a" * 64,
        ],
        env=environ,
        capture_output=True,
        text=True,
        check=False,
    )

    assert enabled.returncode == 0, enabled.stderr
    runtime_env.read_text(encoding="utf-8")
    sourced = subprocess.run(
        [
            "bash",
            "-c",
            'set -eu; source "$GUIYI_RUNTIME_ENV"; test "$GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET" = "$EXPECTED_PACKET"',
        ],
        env=environ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert sourced.returncode == 0, sourced.stderr


def test_local_scheduler_runner_requires_and_forwards_signal_gate() -> None:
    runner = (REPO_ROOT / "scripts" / "run-local-service.sh").read_text(encoding="utf-8")

    assert "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET" in runner
    assert "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH" in runner
    assert "--approval-packet" in runner
    assert "--approval-hash" in runner
    assert "GUIYI_WECHAT_AUTOSEND_ENABLED" in runner
