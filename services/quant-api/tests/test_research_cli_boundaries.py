from __future__ import annotations

import importlib

from app.guiyi_cli.main import build_parser


def test_research_cli_modules_own_one_boundary_each() -> None:
    requests = importlib.import_module("app.guiyi_cli.research_requests")
    commands = importlib.import_module("app.guiyi_cli.research_commands")
    payloads = importlib.import_module("app.guiyi_cli.research_payloads")

    assert requests.build_research_request.__module__ == requests.__name__
    assert commands.run_research_command.__module__ == commands.__name__
    assert (
        payloads._n_structure_payload.__module__
        == payloads.__name__
    )
    assert not hasattr(commands, "build_research_request")


def test_research_help_omits_retired_main_force_commands() -> None:
    parser = build_parser()
    domain_action = next(action for action in parser._actions if action.dest == "domain")
    research_parser = domain_action.choices["research"]
    command_action = next(
        action for action in research_parser._actions if action.dest == "research_command"
    )
    research_help = " ".join(command_action.choices)

    assert "main-force-mirror-v2" not in research_help
    assert "main-force-mirror-diagnostic" not in research_help
