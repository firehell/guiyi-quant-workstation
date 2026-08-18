from __future__ import annotations

from pathlib import Path
import os
import plistlib
import shutil
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_context_launchd_is_render_only_and_has_private_path_contract(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "deploy/launchd", repo / "deploy/launchd")
    script = repo / "scripts/ops/macos/install-local-services.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts/ops/macos/install-local-services.sh", script)
    openclaw_root = tmp_path / "openclaw"
    recipients = tmp_path / "secrets/recipients.json"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "git",
        "#!/bin/sh\nprintf '1111111111111111111111111111111111111111\\n'\n",
    )
    launch_log = tmp_path / "launchctl.log"
    _write_executable(
        fake_bin / "launchctl",
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{launch_log}'\nexit 99\n",
    )

    result = subprocess.run(
        [str(script), "--render-only"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "GUIYI_OPENCLAW_ROOT": str(openclaw_root),
            "GUIYI_ALERT_RECIPIENTS_PATH": str(recipients),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not launch_log.exists()
    rendered = repo / ".run/launchd/com.guiyi.quant-weixin-context.plist"
    with rendered.open("rb") as handle:
        payload = plistlib.load(handle)
    assert payload["Label"] == "com.guiyi.quant-weixin-context"
    assert payload["ProgramArguments"][-1] == "weixin-context"
    assert payload["EnvironmentVariables"] == {
        "GUIYI_PROJECT_ROOT": str(repo),
        "GUIYI_RUNTIME_COMMIT": "1111111111111111111111111111111111111111",
        "GUIYI_OPENCLAW_ROOT": str(openclaw_root),
        "GUIYI_ALERT_RECIPIENTS_PATH": str(recipients),
    }


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
