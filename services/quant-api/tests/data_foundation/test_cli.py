from __future__ import annotations

import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.guiyi_cli.main import CliUsageError, build_parser, main
from app.guiyi_cli.output import exception_error_payload
from app.market_data.composition import research_data_root
from app.market_data.after_market import AfterMarketResult
from app.market_data.historical_data_manager import MaintenanceResult
from app.market_data.catalog import MainMapFact
from app.market_data.member_rank_snapshot import MemberRankRow
from app.market_data.member_rank_snapshot_builder import (
    MemberRankFetch,
    MemberRankSnapshotBuildError,
    MemberRankSnapshotBuilder,
    MemberRankSnapshotResult,
)
from app.market_data.rqdata_adapter import RQDataMemberRankProvider


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
    member_rank_snapshot_builder_factory=None,
):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        args,
        manager_factory=lambda _session: manager,
        after_market_factory=after_market_factory,
        live_service_factory=live_service_factory,
        member_rank_snapshot_builder_factory=member_rank_snapshot_builder_factory,
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
        "member-rank",
    }


def test_member_rank_snapshot_defaults_to_plan_and_uses_shared_json_exit_path() -> None:
    manager = FakeManager()
    calls = []

    class Builder:
        def snapshot(self, request):
            calls.append(request)
            return MemberRankSnapshotResult(
                status="planned",
                dataset_id=request.dataset_id,
                products=request.products,
                contract_count=1,
                provider_calls=0,
                partition_count=0,
            )

    code, payload = _run(
        [
            "data", "member-rank", "snapshot", "--dataset-id", "mfm-member-20260821",
            "--products", "jm", "ag", "cu", "m", "--since", "2026-08-20",
            "--through", "2026-08-20",
        ],
        manager,
        member_rank_snapshot_builder_factory=lambda _session: Builder(),
    )

    assert code == 0
    assert payload["status"] == "planned"
    assert payload["provider_calls"] == 0
    assert payload["readonly"] is True
    assert calls[0].apply is False
    assert manager.calls == []


def test_member_rank_cli_real_builder_dry_run_never_constructs_provider(tmp_path: Path) -> None:
    factory_calls = 0

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("provider factory must not run")

    code, payload = _run(
        _member_rank_arguments(),
        FakeManager(),
        member_rank_snapshot_builder_factory=lambda _session: _snapshot_builder(
            tmp_path, factory
        ),
    )

    assert code == 0
    assert payload["status"] == "planned"
    assert payload["provider_calls"] == 0
    assert payload["readonly"] is True
    assert factory_calls == 0
    assert not (tmp_path / "main_force_member_rank_v1").exists()


@pytest.mark.parametrize("root_value", (None, "", "   "))
def test_member_rank_builder_root_rejects_missing_empty_or_whitespace_before_path_resolution(
    monkeypatch: pytest.MonkeyPatch,
    root_value: str | None,
) -> None:
    if root_value is None:
        monkeypatch.delenv("GUIYI_RESEARCH_DATA_ROOT", raising=False)
    else:
        monkeypatch.setenv("GUIYI_RESEARCH_DATA_ROOT", root_value)

    with pytest.raises(
        MemberRankSnapshotBuildError,
        match="MEMBER_SNAPSHOT_ROOT_UNCONFIGURED",
    ):
        research_data_root()


def test_member_rank_cli_reports_blank_research_root_without_resolving_worktree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUIYI_RESEARCH_DATA_ROOT", " \t ")
    code, payload = _run(
        _member_rank_arguments(),
        FakeManager(),
        member_rank_snapshot_builder_factory=lambda _session: research_data_root(),
    )

    assert code == 1
    assert payload["error"]["code"] == "MEMBER_SNAPSHOT_ROOT_UNCONFIGURED"


def test_member_rank_cli_published_uses_shared_success_exit_path(tmp_path: Path) -> None:
    code, payload = _run(
        [*_member_rank_arguments(), "--apply"],
        FakeManager(),
        member_rank_snapshot_builder_factory=lambda _session: _snapshot_builder(
            tmp_path, lambda: _CompleteProvider()
        ),
    )

    assert code == 0
    assert payload["status"] == "published"
    assert payload["readonly"] is False
    assert (tmp_path / "main_force_member_rank_v1" / "mfm-member-20260821").is_dir()


def test_member_rank_cli_provider_failure_has_stable_safe_json(tmp_path: Path) -> None:
    code, payload = _run(
        [*_member_rank_arguments(), "--apply"],
        FakeManager(),
        member_rank_snapshot_builder_factory=lambda _session: _snapshot_builder(
            tmp_path,
            lambda: RQDataMemberRankProvider(_BrokenProviderClient()),
        ),
    )

    assert code == 1
    assert payload == {
        "schema_version": 1,
        "command": "data.member-rank",
        "status": "error",
        "readonly": False,
        "error": {
            "code": "RQDATA_MEMBER_RANK_UNAVAILABLE",
            "type": "MemberRankSnapshotBuildError",
        },
    }


class _SnapshotFacts:
    def rank1_map(self, symbol: str, since: date, through: date):
        return (MainMapFact(symbol, since, "JM2609"),)

    def trading_days(self, symbol: str, since: date, through: date):
        return (since,)


class _SnapshotVerifier:
    def is_trading_day(self, symbol: str, trade_date: date) -> bool:
        return symbol == "jm" and trade_date == date(2026, 8, 20)

    def is_contract_valid(self, physical_contract: str, trade_date: date) -> bool:
        return physical_contract == "JM2609" and trade_date == date(2026, 8, 20)


class _CompleteProvider:
    def fetch(self, request: MemberRankFetch):
        return tuple(
            MemberRankRow(
                physical_contract=request.physical_contract,
                trade_date=request.since,
                rank_by=request.rank_by,
                rank=rank,
                member_name=f"member-{rank}",
                value=Decimal(rank),
                change=Decimal(rank - 10),
            )
            for rank in range(1, 21)
        )


class _BrokenProviderClient:
    def member_rank(self, *_args, **_kwargs):
        raise RuntimeError("provider secret must not escape")


def _snapshot_builder(tmp_path: Path, provider_factory) -> MemberRankSnapshotBuilder:
    return MemberRankSnapshotBuilder(
        tmp_path,
        rank1_source=_SnapshotFacts(),
        trading_calendar=_SnapshotVerifier(),
        contract_validity=_SnapshotVerifier(),
        provider_factory=provider_factory,
        provider_client_version="fake",
    )


def _member_rank_arguments() -> list[str]:
    return [
        "data",
        "member-rank",
        "snapshot",
        "--dataset-id",
        "mfm-member-20260821",
        "--products",
        "jm",
        "--since",
        "2026-08-20",
        "--through",
        "2026-08-20",
    ]


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

    assert code == 1
    assert payload["error"]["code"] == "PRODUCT_RETIRED"
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

    assert code == 1
    assert payload["error"]["code"] == "PRODUCT_RETIRED"


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
    }


def test_root_parser_exposes_only_active_domains() -> None:
    parser = build_parser()
    domain_action = next(action for action in parser._actions if action.dest == "domain")

    assert set(domain_action.choices) == {"data", "research", "runtime"}


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
