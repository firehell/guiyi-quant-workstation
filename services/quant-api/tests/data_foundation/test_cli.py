from __future__ import annotations

import io
import inspect
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.guiyi_cli.main import CliUsageError, build_parser, main
from app.guiyi_cli import data_commands
from app.market_data import rqdata_adapter
from app.guiyi_cli.output import exception_error_payload
from app.market_data.after_market import AfterMarketResult
from app.market_data.historical_data_manager import (
    ContractWarmupPlan,
    ContractWarmupResult,
    MaintenanceResult,
)


class FakeManager:
    def __init__(self) -> None:
        self.calls = []

    def update(self, request):
        self.calls.append(("update", request))
        return MaintenanceResult("update", "planned", request.through, 1, 0, 0, 0, 0)

    def audit(self, request):
        self.calls.append(("audit", request))

        return MaintenanceResult("audit", "passed", None, 0, 0, 0, 0, 0)

    def refresh(self, request):
        self.calls.append(("refresh", request))
        return MaintenanceResult("refresh", "planned", request.through, 1, 0, 0, 0, 0)

    def contract_warmup(self, request, *, before_apply=None):
        self.calls.append(("contract_warmup", request, before_apply))
        return ContractWarmupResult(
            status="planned",
            readonly=True,
            plan=ContractWarmupPlan(
                symbol="pf",
                contract="PF2611",
                provider="rqdata",
                listed_date=date(2025, 11, 17),
                expired_date=date(2026, 11, 13),
                requested_through=date(2026, 9, 3),
                effective_through=date(2026, 9, 3),
                target_windows=(
                    {
                        "dataset": ("contract", "pf", "PF2611", "1m"),
                        "year": 2026,
                        "month": 9,
                        "expected_bar_count": 7,
                        "missing_bar_count": 7,
                    },
                ),
                direct_target_count=1,
                derived_target_count=2,
                expected_bar_count=7,
                provider_request_count=1,
                plan_sha256="a" * 64,
            ),
            applied=0,
            blocked=0,
            failed=0,
            provider_requests=0,
        )


class ProgressFakeManager(FakeManager):
    def audit(self, request, observer=None):
        self.calls.append(("audit", request))
        if observer is not None:
            observer(
                _ProgressEvent(
                    state="started",
                    completed=0,
                    total=len(request.products),
                    symbol=request.products[0].strip().lower(),
                    finding_count=None,
                )
            )
            observer(
                _ProgressEvent(
                    state="completed",
                    completed=1,
                    total=len(request.products),
                    symbol=request.products[0].strip().lower(),
                    finding_count=0,
                )
            )
        return MaintenanceResult("audit", "passed", None, 0, 0, 0, 0, 0)


def _run(
    args,
    manager,
    *,
    after_market_factory=None,
    live_service_factory=None,
):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        args,
        manager_factory=lambda _session: manager,
        after_market_factory=after_market_factory,
        live_service_factory=live_service_factory,
        session_factory=lambda: _NullContext(),
        stdout=stdout,
        stderr=stderr,
    )
    payload = json.loads((stdout if code == 0 else stderr).getvalue())
    return code, payload


class _NullContext:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return None


class _ProgressEvent:
    def __init__(
        self,
        *,
        state: str,
        completed: int,
        total: int,
        symbol: str,
        finding_count: int | None,
    ) -> None:
        self.state = state
        self.completed = completed
        self.total = total
        self.symbol = symbol
        self.finding_count = finding_count


class _FailingProgressStream:
    def __init__(self) -> None:
        self.writes = 0

    def write(self, _value: str) -> int:
        self.writes += 1
        raise OSError("progress output unavailable")


class _ShortWriteProgressStream:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.flushes = 0

    def write(self, value: str) -> int:
        self.lines.append(value)
        return len(value) - 1

    def flush(self) -> None:
        self.flushes += 1


class _FlushFailingProgressStream:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.flushes = 0

    def write(self, value: str) -> int:
        self.lines.append(value)
        return len(value)

    def flush(self) -> None:
        self.flushes += 1
        raise OSError("progress flush unavailable")


def test_data_parser_exposes_only_active_user_commands() -> None:
    parser = build_parser()
    data_action = next(action for action in parser._actions if action.dest == "domain")
    data_parser = data_action.choices["data"]
    command_action = next(
        action for action in data_parser._actions if action.dest == "data_command"
    )

    assert set(command_action.choices) == {
        "update",
        "refresh",
        "audit",
        "after-market",
        "session-anchor-repair",
        "contract-warmup",
    }


def test_contract_warmup_parser_requires_apply_hash_and_rejects_abbreviations() -> None:
    parser = build_parser()
    common = [
        "data",
        "contract-warmup",
        "--symbol",
        "pf",
        "--contract",
        "PF2611",
        "--through",
        "2026-09-03",
    ]

    parsed = parser.parse_args(common)

    assert parsed.apply is False
    assert parsed.expected_plan_sha256 is None
    with pytest.raises(CliUsageError):
        parser.parse_args([*common, "--expected-plan-sha256", "a" * 64])
    with pytest.raises(CliUsageError):
        parser.parse_args([*common, "--apply"])
    with pytest.raises(CliUsageError):
        parser.parse_args([*common, "--apply", "--expected-plan-sha256", "A" * 64])
    with pytest.raises(CliUsageError):
        parser.parse_args([
            "data",
            "contract-warmup",
            "--sym",
            "pf",
            "--contract",
            "PF2611",
            "--through",
            "2026-09-03",
        ])
    for required_flag in ("--symbol", "--contract", "--through"):
        missing = common.copy()
        index = missing.index(required_flag)
        del missing[index : index + 2]
        with pytest.raises(CliUsageError):
            parser.parse_args(missing)


def test_contract_warmup_dry_run_builds_active_request_and_fixed_public_payload() -> None:
    manager = FakeManager()
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "data",
            "contract-warmup",
            "--symbol",
            " PF ",
            "--contract",
            " pf2611 ",
            "--through",
            "2026-09-03",
        ],
        manager_factory=lambda _session: manager,
        session_factory=lambda: _NullContext(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert json.loads(stdout.getvalue()) == {
        "schema_version": 2,
        "command": "data.contract-warmup",
        "status": "planned",
        "readonly": True,
        "symbol": "pf",
        "contract": "PF2611",
        "provider": "rqdata",
        "listed_date": "2025-11-17",
        "expired_date": "2026-11-13",
        "requested_window": {"start": "2025-11-17", "through": "2026-09-03"},
        "effective_window": {"start": "2025-11-17", "through": "2026-09-03"},
        "direct_target_count": 1,
        "derived_target_count": 2,
        "expected_bar_count": 7,
        "provider_request_count": 1,
        "plan_sha256": "a" * 64,
        "applied": 0,
        "blocked": 0,
        "failed": 0,
        "targets": [
            {
                "dataset": ["contract", "pf", "PF2611", "1m"],
                "year": 2026,
                "month": 9,
                "expected_bar_count": 7,
                "missing_bar_count": 7,
            },
        ],
        "failures": [],
    }
    assert stderr.getvalue() == ""
    assert manager.calls[0][0] == "contract_warmup"
    request = manager.calls[0][1]
    assert request.symbol == "pf"
    assert request.contract == "PF2611"
    assert request.through == date(2026, 9, 3)
    assert request.expected_plan_sha256 is None
    assert request.apply is False
    assert manager.calls[0][2] is None
    assert len(manager.calls) == 1


def test_contract_warmup_rejects_symbols_outside_active_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(data_commands, "load_active_products", lambda: ("jm",))
    args = SimpleNamespace(
        data_command="contract-warmup",
        symbol="pf",
        contract=" PF-2611 ",
        through="2026-09-03",
        expected_plan_sha256=None,
        apply=False,
    )

    with pytest.raises(ValueError, match="CLI_SYMBOL_INACTIVE"):
        data_commands.build_request(args)


def test_contract_warmup_payload_exposes_requested_and_effective_windows() -> None:
    result = ContractWarmupResult(
        status="planned",
        readonly=True,
        plan=ContractWarmupPlan(
            symbol="pf",
            contract="PF2611",
            provider="rqdata",
            listed_date=date(2025, 11, 17),
            expired_date=date(2026, 11, 13),
            requested_through=date(2026, 12, 1),
            effective_through=date(2026, 11, 12),
            target_windows=(),
            direct_target_count=0,
            derived_target_count=0,
            expected_bar_count=0,
            provider_request_count=0,
            plan_sha256="a" * 64,
        ),
        applied=0,
        blocked=0,
        failed=0,
        provider_requests=0,
    )

    payload = data_commands.contract_warmup_payload(result)

    assert payload["schema_version"] == 2
    assert payload["requested_window"] == {
        "start": "2025-11-17",
        "through": "2026-12-01",
    }
    assert payload["effective_window"] == {
        "start": "2025-11-17",
        "through": "2026-11-12",
    }
    assert "through" not in payload


def test_contract_warmup_apply_failure_is_non_readonly_and_does_not_leak_details(
    tmp_path: Path,
) -> None:
    class FailingManager(FakeManager):
        def __init__(self) -> None:
            super().__init__()
            self.catalog = SimpleNamespace(canonical_root=tmp_path)

        def contract_warmup(self, request, *, before_apply=None):
            self.calls.append(("contract_warmup", request, before_apply))
            assert before_apply is not None
            before_apply()
            error = RuntimeError("provider response /private/secret.sql Traceback")
            error.code = "CONTRACT_WARMUP_PLAN_CHANGED"
            raise error

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        [
            "data",
            "contract-warmup",
            "--symbol",
            "pf",
            "--contract",
            "PF2611",
            "--through",
            "2026-09-03",
            "--apply",
            "--expected-plan-sha256",
            "a" * 64,
        ],
        manager_factory=lambda _session: FailingManager(),
        session_factory=lambda: _NullContext(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "data.contract-warmup",
        "status": "error",
        "readonly": False,
        "error": {"code": "CONTRACT_WARMUP_PLAN_CHANGED", "type": "RuntimeError"},
    }
    assert "provider response" not in stderr.getvalue()
    assert "/private/secret.sql" not in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_session_anchor_repair_plan_is_readonly_and_uses_dedicated_service() -> None:
    calls = []

    class Repair:
        def plan(self):
            calls.append(("plan",))
            return SimpleNamespace(
                as_payload=lambda: {
                    "schema_version": 1,
                    "command": "data.session-anchor-repair",
                    "phase": "plan",
                    "status": "planned",
                    "readonly": True,
                }
            )

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        ["data", "session-anchor-repair", "--phase", "plan"],
        session_factory=lambda: _NullContext(),
        session_anchor_repair_factory=lambda _session: Repair(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert json.loads(stdout.getvalue()) == {
        "schema_version": 1,
        "command": "data.session-anchor-repair",
        "phase": "plan",
        "status": "planned",
        "readonly": True,
    }
    assert stderr.getvalue() == ""
    assert calls == [("plan",)]


def test_session_anchor_repair_prepare_requires_explicit_paths_and_apply() -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args([
            "data",
            "session-anchor-repair",
            "--phase",
            "plan",
            "--shadow-root",
            "/tmp/shadow",
        ])

    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            ["data", "session-anchor-repair", "--phase", "prepare"]
        )

    parsed = build_parser().parse_args([
        "data",
        "session-anchor-repair",
        "--phase",
        "prepare",
        "--shadow-root",
        "/tmp/shadow",
        "--manifest",
        "/tmp/manifest.json",
        "--apply",
    ])

    assert parsed.phase == "prepare"
    assert Path(parsed.shadow_root) == Path("/tmp/shadow")
    assert Path(parsed.manifest) == Path("/tmp/manifest.json")
    assert parsed.apply is True


def test_after_market_is_a_dedicated_apply_free_cli_entrypoint() -> None:
    manager = FakeManager()
    received = []

    class Updater:
        def run(self):
            return AfterMarketResult("passed", date(2026, 8, 10), 1, None)

    code, payload = _run(
        ["data", "after-market"],
        manager,
        after_market_factory=lambda supplied_manager, **capability: (
            received.append((supplied_manager, capability)) or Updater()
        ),
    )

    assert code == 0
    assert payload == {
        "schema_version": 1,
        "command": "data.after-market",
        "status": "passed",
        "trading_day": "2026-08-10",
        "attempts": 1,
        "error_code": None,
    }
    assert received == [(manager, {"failure_notification": False})]
    assert manager.calls == []
    with pytest.raises(CliUsageError):
        build_parser().parse_args(["data", "after-market", "--apply"])


def test_after_market_non_trading_day_skip_exits_successfully() -> None:
    manager = FakeManager()
    stdout = io.StringIO()
    stderr = io.StringIO()

    class Updater:
        def run(self):
            return AfterMarketResult(
                "skipped",
                date(2026, 8, 14),
                0,
                "NON_TRADING_DAY",
            )

    code = main(
        ["data", "after-market"],
        manager_factory=lambda _session: manager,
        after_market_factory=lambda _manager, **capability: (
            Updater()
            if capability == {"failure_notification": False}
            else pytest.fail("manual CLI must disable failure notification")
        ),
        session_factory=lambda: _NullContext(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert json.loads(stdout.getvalue()) == {
        "schema_version": 1,
        "command": "data.after-market",
        "status": "skipped",
        "trading_day": "2026-08-14",
        "attempts": 0,
        "error_code": "NON_TRADING_DAY",
    }
    assert stderr.getvalue() == ""
    assert manager.calls == []


def test_refresh_requires_a_symbol_and_explicit_window() -> None:
    manager = FakeManager()
    code, payload = _run(
        ["data", "refresh", "--symbol", "jm", "--since", "2025-01-01", "--through", "2025-01-03"],
        manager,
    )

    assert code == 0 and payload["action"] == "refresh"
    request = manager.calls[0][1]
    assert request.symbol == "jm"
    assert request.apply is False


def test_refresh_rejects_the_completed_one_off_frequency_selector() -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [
                "data",
                "refresh",
                "--symbol",
                "rs",
                "--since",
                "2025-01-01",
                "--through",
                "2025-01-31",
                "--frequencies",
                "1d",
                "1w",
            ]
        )


def test_update_parses_since_through_and_defaults_to_dry_run() -> None:
    manager = FakeManager()

    code, payload = _run(
        [
            "data",
            "update",
            "--symbol",
            "jm",
            "--since",
            "2025-01-01",
            "--through",
            "2025-01-03",
        ],
        manager,
    )

    assert code == 0 and payload["status"] == "planned"
    request = manager.calls[0][1]
    assert request.products == ("jm",)
    assert request.apply is False
    assert request.since.isoformat() == "2025-01-01"


def test_audit_parses_single_active_symbol() -> None:
    manager = FakeManager()

    code, payload = _run(["data", "audit", "--symbol", "JM"], manager)

    assert code == 0 and payload["status"] == "passed"
    assert [action for action, _request in manager.calls] == ["audit"]
    assert manager.calls[0][1].products == ("jm",)


def test_audit_without_progress_preserves_exact_stdout_and_empty_stderr() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        ["data", "audit", "--symbol", "JM"],
        manager_factory=lambda _session: FakeManager(),
        session_factory=lambda: _NullContext(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stdout.getvalue() == (
        '{\n'
        '  "action": "audit",\n'
        '  "applied": 0,\n'
        '  "blocked": 0,\n'
        '  "failed": 0,\n'
        '  "failures": [],\n'
        '  "finding_count": 0,\n'
        '  "findings": [],\n'
        '  "planned": 0,\n'
        '  "provider_requests": 0,\n'
        '  "schema_version": 1,\n'
        '  "status": "passed",\n'
        '  "stop_reason": null,\n'
        '  "targets": [],\n'
        '  "through": null\n'
        '}\n'
    )
    assert stderr.getvalue() == ""


def test_audit_progress_writes_compact_ndjson_to_stderr() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        ["data", "audit", "--symbol", "JM", "--progress"],
        manager_factory=lambda _session: ProgressFakeManager(),
        session_factory=lambda: _NullContext(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert json.loads(stdout.getvalue())["status"] == "passed"
    assert stderr.getvalue() == (
        '{"schema_version":1,"event":"data.audit.progress","state":"started",'
        '"completed":0,"total":1,"symbol":"jm","finding_count":null}\n'
        '{"schema_version":1,"event":"data.audit.progress","state":"completed",'
        '"completed":1,"total":1,"symbol":"jm","finding_count":0}\n'
    )


def test_audit_progress_output_failure_disables_later_writes() -> None:
    stdout = io.StringIO()
    stderr = _FailingProgressStream()

    code = main(
        ["data", "audit", "--symbol", "jm", "--progress"],
        manager_factory=lambda _session: ProgressFakeManager(),
        session_factory=lambda: _NullContext(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert json.loads(stdout.getvalue())["status"] == "passed"
    assert stderr.writes == 1


def test_audit_progress_short_write_disables_later_emissions() -> None:
    stdout = io.StringIO()
    stderr = _ShortWriteProgressStream()
    manager = ProgressFakeManager()

    code = main(
        ["data", "audit", "--symbol", "jm", "--progress"],
        manager_factory=lambda _session: manager,
        session_factory=lambda: _NullContext(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert json.loads(stdout.getvalue())["status"] == "passed"
    assert [action for action, _request in manager.calls] == ["audit"]
    assert len(stderr.lines) == 1
    assert stderr.flushes == 0


def test_audit_progress_flush_failure_disables_later_emissions() -> None:
    stdout = io.StringIO()
    stderr = _FlushFailingProgressStream()
    manager = ProgressFakeManager()

    code = main(
        ["data", "audit", "--symbol", "jm", "--progress"],
        manager_factory=lambda _session: manager,
        session_factory=lambda: _NullContext(),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert json.loads(stdout.getvalue())["status"] == "passed"
    assert [action for action, _request in manager.calls] == ["audit"]
    assert len(stderr.lines) == 1
    assert stderr.flushes == 1


def test_audit_parses_fixed_through_boundary() -> None:
    manager = FakeManager()

    code, payload = _run(
        ["data", "audit", "--universe", "active", "--through", "2025-01-03"],
        manager,
    )

    assert code == 0 and payload["status"] == "passed"
    assert manager.calls[0][1].through == date(2025, 1, 3)


def test_audit_keeps_active_universe_selector() -> None:
    manager = FakeManager()

    code, payload = _run(["data", "audit", "--universe", "active"], manager)

    assert code == 0 and payload["status"] == "passed"
    assert len(manager.calls[0][1].products) == 60


@pytest.mark.parametrize(
    "arguments",
    ((), ("--symbol", "jm", "--universe", "active")),
)
def test_audit_requires_exactly_one_selector(arguments: tuple[str, ...]) -> None:
    manager = FakeManager()

    code, payload = _run(["data", "audit", *arguments], manager)

    assert code == 2
    assert payload["status"] == "error"
    assert manager.calls == []


def test_audit_rejects_retired_symbol_before_manager_call() -> None:
    manager = FakeManager()

    code, payload = _run(["data", "audit", "--symbol", "ic"], manager)

    assert code == 2
    assert payload["error"]["code"] == "CLI_ARGUMENT_INVALID"
    assert manager.calls == []


@pytest.mark.parametrize("command", ("bootstrap", "repair", "download", "aggregate", "sync", "verify"))
def test_retired_commands_are_parser_errors(command: str) -> None:
    code, payload = _run(["data", command], FakeManager())

    assert code == 2
    assert payload["status"] == "error"


@pytest.mark.parametrize(
    "arguments",
    (
        ("--candidate-root", "data/canonical-candidates/jm"),
        ("--candidate-mode", "fresh"),
    ),
)
def test_update_rejects_retired_candidate_flags(arguments: tuple[str, str]) -> None:
    parser = build_parser()

    with pytest.raises(CliUsageError):
        parser.parse_args(["data", "update", "--symbol", "jm", *arguments])


def test_update_rejects_retired_symbol() -> None:
    code, payload = _run(
        ["data", "update", "--symbol", "ic", "--through", "2025-01-03"],
        FakeManager(),
    )

    assert code == 2
    assert payload["error"]["code"] == "CLI_ARGUMENT_INVALID"


def test_cli_internal_error_does_not_expose_sqlalchemy_documentation_code() -> None:
    error = RuntimeError("database unavailable")
    error.code = "e3q8"

    payload = exception_error_payload(command="data.update", exc=error)

    assert payload["error"] == {"code": "CLI_INTERNAL_ERROR", "type": "RuntimeError"}


def test_runtime_parser_exposes_active_runtime_commands() -> None:
    parser = build_parser()
    runtime_action = next(action for action in parser._actions if action.dest == "domain")
    runtime_parser = runtime_action.choices["runtime"]
    command_action = next(action for action in runtime_parser._actions if action.dest == "runtime_command")

    assert set(command_action.choices) == {
        "status",
        "live",
        "alert",
        "alert-canary",
        "acknowledge-alert-notification",
        "subing-ths-scope",
    }


def test_root_parser_exposes_only_active_domains() -> None:
    parser = build_parser()
    domain_action = next(action for action in parser._actions if action.dest == "domain")

    assert set(domain_action.choices) == {"data", "runtime"}


def test_data_cli_omits_retired_member_rank_parser_dispatch_and_factory() -> None:
    parser = build_parser()
    domain_action = next(action for action in parser._actions if action.dest == "domain")
    data_parser = domain_action.choices["data"]
    command_action = next(
        action for action in data_parser._actions if action.dest == "data_command"
    )
    data_help = " ".join(command_action.choices)

    assert "member-rank" not in data_help
    assert "member_rank_snapshot_builder_factory" not in inspect.signature(main).parameters
    assert "member_rank" not in inspect.getsource(data_commands.build_request)
    assert not hasattr(data_commands, "MemberRankSnapshotRequest")
    assert not hasattr(rqdata_adapter, "RQDataMemberRankProvider")
    assert not hasattr(rqdata_adapter.RQDataClient, "member_rank")


def test_runtime_live_runs_only_the_injected_foreground_service() -> None:
    manager = FakeManager()
    calls: list[str] = []

    class LiveService:
        def run_forever(self) -> None:
            calls.append("run_forever")

    code, payload = _run(
        ["runtime", "live"],
        manager,
        live_service_factory=lambda _session: LiveService(),
    )

    assert code == 0
    assert calls == ["run_forever"]
    assert payload == {
        "schema_version": 1,
        "command": "runtime.live",
        "status": "ok",
        "foreground": True,
    }
