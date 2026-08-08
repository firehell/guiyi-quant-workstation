from __future__ import annotations

import io
import json

from app.guiyi_cli.main import build_parser, main
from app.market_data.maintenance import MaintenanceResult


class FakeManager:
    def __init__(self) -> None:
        self.calls = []

    def update(self, request):
        self.calls.append(("update", request))
        return MaintenanceResult("update", "planned", request.through, 1, 0, 0, 0, 0)

    def bootstrap(self, request):
        self.calls.append(("bootstrap", request))
        return MaintenanceResult("bootstrap", "planned", request.through, 1, 0, 0, 0, 0)

    def repair(self, request):
        self.calls.append(("repair", request))
        return MaintenanceResult("repair", "planned", None, len(request.items), 0, 0, 0, 0)

    def audit(self, request):
        self.calls.append(("audit", request))
        return MaintenanceResult("audit", "passed", None, 0, 0, 0, 0, 0)


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


def test_data_parser_exposes_only_four_user_commands() -> None:
    parser = build_parser()
    data_action = next(action for action in parser._actions if action.dest == "domain")
    data_parser = data_action.choices["data"]
    command_action = next(
        action for action in data_parser._actions if action.dest == "data_command"
    )

    assert set(command_action.choices) == {"update", "bootstrap", "repair", "audit"}


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


def test_bootstrap_and_audit_require_active_universe() -> None:
    manager = FakeManager()
    bootstrap_code, _ = _run(
        ["data", "bootstrap", "--universe", "active", "--through", "2025-01-03"],
        manager,
    )
    audit_code, _ = _run(["data", "audit", "--universe", "active"], manager)
    invalid_code, invalid = _run(["data", "bootstrap", "--universe", "other"], manager)

    assert bootstrap_code == audit_code == 0
    assert invalid_code == 2
    assert invalid["status"] == "error"


def test_repair_loads_exact_plan_and_apply_flag(tmp_path) -> None:
    plan = tmp_path / "repair.json"
    plan.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "dataset": {
                            "kind": "continuous",
                            "symbol": "jm",
                            "series_or_contract": "MAIN",
                            "frequency": "1d",
                        },
                        "year": 2025,
                        "month": 1,
                        "start": "2025-01-01T00:00:00Z",
                        "end": "2025-02-01T00:00:00Z",
                    }
                ]
            }
        )
    )
    manager = FakeManager()

    code, payload = _run(
        ["data", "repair", "--plan", str(plan), "--apply"], manager
    )

    assert code == 0 and payload["planned"] == 1
    assert manager.calls[0][1].apply is True


def test_removed_commands_are_parser_errors() -> None:
    for command in ("download", "aggregate", "sync", "verify"):
        code, payload = _run(["data", command], FakeManager())
        assert code == 2
        assert payload["status"] == "error"
