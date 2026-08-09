from __future__ import annotations

import io
import json

import pytest

from app.guiyi_cli.main import CliUsageError, build_parser, main
from app.guiyi_cli.output import exception_error_payload
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


def _run(args, manager):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        args,
        manager_factory=lambda _session: manager,
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

    assert set(command_action.choices) == {"update", "refresh", "audit", "retire-products"}


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


def test_audit_requires_active_universe() -> None:
    manager = FakeManager()

    code, payload = _run(["data", "audit", "--universe", "active"], manager)
    invalid_code, invalid = _run(["data", "audit", "--universe", "other"], manager)

    assert code == 0 and payload["status"] == "passed"
    assert invalid_code == 2
    assert invalid["status"] == "error"


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
