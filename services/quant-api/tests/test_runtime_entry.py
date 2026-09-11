from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys


QUANT_API_ROOT = Path(__file__).resolve().parents[1]


def test_after_market_boundary_never_claims_an_execution_exception_is_readonly():
    from app.runtime_entry import main

    stderr = io.StringIO()

    def unavailable():
        raise RuntimeError("private database details")

    assert (
        main(
            ["after-market"],
            session_factory=unavailable,
            stderr=stderr,
            stdout=io.StringIO(),
        )
        == 1
    )
    payload = json.loads(stderr.getvalue())
    assert payload["readonly"] is False
    assert "private" not in stderr.getvalue()


def test_after_market_logging_setup_failure_still_runs_maintenance(monkeypatch):
    import pytest
    from app import runtime_entry, runtime_logging
    calls = []
    monkeypatch.setattr(sys, "argv", ["runtime_entry", "after-market"])
    def unavailable(service):
        calls.append(service)
        raise OSError("private")
    monkeypatch.setattr(runtime_logging, "install_runtime_diagnostics", unavailable)
    monkeypatch.setattr(runtime_entry, "main", lambda: calls.append("maintenance") or 0)
    with pytest.raises(SystemExit) as exit_info:
        runtime_entry.entrypoint()
    assert exit_info.value.code == 0
    assert calls == ["after-market", "maintenance"]


def test_weekly_failure_payload_stays_readonly_and_sanitized():
    import io
    import json
    from app.runtime_entry import main
    def unavailable():
        raise RuntimeError("private database details")
    stderr = io.StringIO()
    assert main(["weekly-audit"], session_factory=unavailable, stderr=stderr, stdout=io.StringIO()) == 1
    assert json.loads(stderr.getvalue())["readonly"] is True
    assert "private" not in stderr.getvalue()


def test_maintenance_logging_failure_with_closed_stderr_does_not_skip_business(monkeypatch):
    import io
    import pytest
    from app import runtime_entry, runtime_logging
    closed = io.StringIO()
    closed.close()
    monkeypatch.setattr(sys, "argv", ["runtime_entry", "weekly-audit"])
    monkeypatch.setattr(sys, "stderr", closed)
    monkeypatch.setattr(runtime_logging, "install_runtime_diagnostics", lambda _: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(runtime_entry, "main", lambda: 0)
    with pytest.raises(SystemExit) as result:
        runtime_entry.entrypoint()
    assert result.value.code == 0


def test_actual_runtime_launch_module_imports_no_offline_research() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.runtime_entry; "
                "print(sum(name == 'app.research' or "
                "name.startswith('app.research.') for name in sys.modules))"
            ),
        ],
        cwd=QUANT_API_ROOT,
        env={**os.environ, "PYTHONPATH": str(QUANT_API_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"
