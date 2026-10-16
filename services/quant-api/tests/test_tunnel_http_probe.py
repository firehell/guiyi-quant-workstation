"""Offline checks of both healthcheck entry points; no network or Runtime access."""
import os
import shutil
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ("local-tunnel-healthcheck.sh", "tunnel-healthcheck.sh")


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("status,elapsed,exit_code,error,healthy,diagnostic", [
    ("200", "0.123", 0, "", True, ""),
    ("401", "0.045", 0, "", True, ""),
    ("204", "0.015", 0, "", True, ""),
    ("301", "0.025", 0, "", True, ""),
    ("302", "0.035", 0, "", True, ""),
    ("invalid", "0.035", 0, "", False, "无效探测结果"),
    ("200", "invalid", 0, "", False, "无效探测结果"),
    ("", "", 127, "curl: command not found", False, "curl exit=127"),
    ("503", "0.002", 0, "", False, "异常状态: 503"),
    ("000", "0.004", 7, "curl: (7) Connection refused", False, "Connection refused"),
    ("000", "0.005", 52, "curl: (52) Empty reply from server", False, "Empty reply"),
    ("200", "0.006", 18, "curl: (18) partial response", False, "curl exit=18"),
    ("200", "0.007", 28, "curl: (28) timed out after headers", False, "curl exit=28"),
])
def test_healthcheck_uses_one_request_and_rejects_transport_failure(
    tmp_path, script, status, elapsed, exit_code, error, healthy, diagnostic,
):
    tools = tmp_path / "bin"
    tools.mkdir()
    fake_curl = tools / "curl"
    fake_curl.write_text("""#!/bin/bash
printf 'request\\n' >> "$CURL_CALLS"
format=''
while [[ $# -gt 0 ]]; do
  if [[ "$1" == '-w' ]]; then format="$2"; shift; fi
  shift
done
[[ -z "$CURL_ERROR" ]] || printf '%s\\n' "$CURL_ERROR" >&2
format="${format//%\\{http_code\\}/$CURL_STATUS}"
format="${format//%\\{time_total\\}/$CURL_TIME}"
printf '%b' "$format"
exit "$CURL_EXIT"
""")
    fake_curl.chmod(0o755)
    for name, body in (("lsof", "exit 0"), ("ss", "echo ':18080 :18000 '"),
                       ("pgrep", "echo fixture-frpc")):
        executable = tools / name
        executable.write_text(f"#!/bin/bash\n{body}\n")
        executable.chmod(0o755)
    config = tmp_path / "frpc.toml"
    config.write_text('serverAddr = "fixture.invalid"\n')
    calls = tmp_path / "calls"
    env = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}", FRPC_CONFIG=str(config),
               CURL_CALLS=str(calls), CURL_STATUS=status, CURL_TIME=elapsed,
               CURL_EXIT=str(exit_code), CURL_ERROR=error)
    # Simulate the documented ECS distribution without a repository checkout.
    for filename in (script, "http-probe.sh"):
        shutil.copy2(ROOT / "scripts/ops/network" / filename, tmp_path / filename)
    result = subprocess.run(["bash", str(tmp_path / script)],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == (0 if healthy else 1), result.stdout + result.stderr
    assert calls.read_text().splitlines() == ["request", "request"]
    if diagnostic != "无效探测结果":
        assert f"{elapsed or '0.000'}s" in result.stdout
    assert f"overall={'passed' if healthy else 'failed'}" in result.stdout
    if diagnostic:
        assert diagnostic in result.stderr
