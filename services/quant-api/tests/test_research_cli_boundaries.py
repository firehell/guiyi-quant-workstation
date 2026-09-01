from __future__ import annotations

import importlib


def test_research_cli_modules_own_one_boundary_each() -> None:
    requests = importlib.import_module("app.guiyi_cli.research_requests")
    commands = importlib.import_module("app.guiyi_cli.research_commands")
    payloads = importlib.import_module("app.guiyi_cli.research_payloads")

    assert requests.build_research_request.__module__ == requests.__name__
    assert commands.run_research_command.__module__ == commands.__name__
    assert payloads._calibration_payload.__module__ == payloads.__name__
    assert payloads._lifecycle_payload.__module__ == payloads.__name__
    assert payloads._subing_watch_payload.__module__ == payloads.__name__
    assert not hasattr(commands, "build_research_request")
