from __future__ import annotations

import ast
import importlib
from pathlib import Path


def test_research_cli_modules_own_one_boundary_each() -> None:
    requests = importlib.import_module("app.guiyi_cli.research_requests")
    commands = importlib.import_module("app.guiyi_cli.research_commands")
    payloads = importlib.import_module("app.guiyi_cli.research_payloads")

    assert requests.build_research_request.__module__ == requests.__name__
    assert commands.run_research_command.__module__ == commands.__name__
    assert (
        payloads._multi_candidate_robustness_payload.__module__
        == payloads.__name__
    )
    assert not hasattr(commands, "build_research_request")


def test_main_force_diagnostic_service_has_no_write_or_runtime_dependency() -> None:
    module = importlib.import_module(
        "app.research.main_force.main_force_mirror_diagnostic_service"
    )
    path = Path(module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = tuple(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ) + tuple(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden = (
        "app.db",
        "app.alerts",
        "app.runtime_entry",
        "app.services.runtime_health",
        "redis",
        "rqdatac",
        "rqdata",
    )

    assert not any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for module_name in imported
        for prefix in forbidden
    )
