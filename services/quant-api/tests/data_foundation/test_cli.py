from __future__ import annotations

import io
import json
from datetime import date

import pytest

from app.guiyi_cli.main import CliUsageError, build_parser, main
from app.guiyi_cli.output import exception_error_payload
from app.market_data.after_market import AfterMarketResult
from app.market_data.maintenance import MaintenanceResult


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


def _run(args, manager, *, after_market_factory=None, live_service_factory=None):
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
        "retire-products",
        "after-market",
    }


def test_after_market_is_a_dedicated_apply_free_cli_entrypoint() -> None:
    manager = FakeManager()
    received = []

    class Updater:
        def run(self):
            return AfterMarketResult("passed", date(2026, 8, 10), 1, None)

    code, payload = _run(
        ["data", "after-market"],
        manager,
        after_market_factory=lambda supplied_manager: received.append(supplied_manager) or Updater(),
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
    assert received == [manager]
    assert manager.calls == []
    with pytest.raises(CliUsageError):
        build_parser().parse_args(["data", "after-market", "--apply"])


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


def test_runtime_parser_exposes_status_and_live_only() -> None:
    parser = build_parser()
    runtime_action = next(action for action in parser._actions if action.dest == "domain")
    runtime_parser = runtime_action.choices["runtime"]
    command_action = next(action for action in runtime_parser._actions if action.dest == "runtime_command")

    assert set(command_action.choices) == {"status", "live"}


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
