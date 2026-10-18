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


def test_scheduled_weekly_noop_is_success(monkeypatch):
    from contextlib import nullcontext
    from app import runtime_entry
    from app.market_data import weekly_audit
    monkeypatch.setattr(
        weekly_audit,
        "run_scheduled_weekly_audit",
        lambda *args, **kwargs: {
            "schema_version": 1,
            "command": "data.weekly-audit-scheduled",
            "status": "already_attempted",
            "readonly": True,
        },
    )
    output = io.StringIO()
    result = runtime_entry.main(
        ["weekly-audit-scheduled"],
        session_factory=lambda: nullcontext(object()),
        manager_factory=lambda _: object(),
        stdout=output,
        stderr=io.StringIO(),
    )
    assert result == 0
    assert json.loads(output.getvalue())["status"] == "already_attempted"


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


def _run_owned_live_poll_results(monkeypatch, results):
    from contextlib import nullcontext
    from app import runtime_entry
    snapshots = []
    class Owner:
        def assert_owned(self):
            pass
        def mark_not_ready(self, proof=None):
            snapshots.append({'ready': False, 'proof': proof or {}})
        def mark_ready(self, proof=None):
            snapshots.append({'ready': True, 'proof': proof or {'cycle_ok': True}})
    class Live:
        def poll(self, now):
            return results[now]
        def run_forever(self, *, should_stop):
            for index in range(len(results)):
                assert self.poll(index) is results[index]
    monkeypatch.setenv('GUIYI_RUNTIME_HANDOVER_ENABLED', '1')
    monkeypatch.setattr(runtime_entry, '_owned_runner', lambda service, run: run(Owner(), lambda: False))
    runtime_entry.run_live(session_factory=lambda: nullcontext(object()), live_service_factory=lambda _: Live())
    return snapshots


def test_live_poll_failure_proof_preserves_existing_fixed_codes_and_recovers(monkeypatch):
    from app import runtime_entry
    assert {'OBSERVATION_DAY_CHANGED', 'OBSERVATION_CONSUMER_UNREGISTERED'} <= runtime_entry._LIVE_POLL_FAILURE_CODES
    for code in sorted(runtime_entry._LIVE_POLL_FAILURE_CODES):
        snapshots = _run_owned_live_poll_results(monkeypatch, [code, None])
        assert snapshots == [
            {'ready': False, 'proof': {}},
            {'ready': False, 'proof': {'failure_code': code}},
            {'ready': False, 'proof': {}},
            {'ready': True, 'proof': {'cycle_ok': True}},
        ]


def test_live_poll_unknown_text_or_payload_is_redacted_without_claiming_ready(monkeypatch):
    results = ['postgresql://private-user:private-password@private-host/db',
               'LIVE_NEW_UNREVIEWED_CODE', {'secret': 'private-password'}, ['private-password'], False, 0]
    snapshots = _run_owned_live_poll_results(monkeypatch, results)
    assert all(snapshot['ready'] is False for snapshot in snapshots)
    failures = [snapshot['proof'] for snapshot in snapshots if snapshot['proof']]
    assert failures == [{'failure_code': 'LIVE_POLL_FAILED'}] * len(results)
    assert 'private' not in json.dumps(snapshots)
