"""Task-contract disposition and active-contract consistency tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "engineering" / "repository_consistency.py"


def _load():
    spec = importlib.util.spec_from_file_location("repository_consistency_tasks", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


consistency = _load()


def test_every_task_file_has_exactly_one_disposition() -> None:
    inventory = consistency.inventory_task_dispositions(ROOT)
    names = [Path(item.path).name for item in inventory]
    assert len(names) == len(set(names))
    on_disk = {
        path.name
        for path in (ROOT / "docs" / "tasks").glob("*.md")
        if path.name != "README.md"
    }
    assert set(names) == on_disk


def test_active_disposition() -> None:
    inventory = {
        Path(item.path).name: item.disposition
        for item in consistency.inventory_task_dispositions(ROOT)
    }
    assert inventory["GY-DATA-CORE-V2.md"] is consistency.TaskDisposition.ACTIVE_CONTRACT


@pytest.mark.parametrize(
    "relative",
    [
        "docs/tasks/GY-DATA-CORE-V2.md",
    ],
)
def test_active_contracts_reject_collaboration_authorization_predicates(relative: str) -> None:
    text = (ROOT / relative).read_text(encoding="utf-8")
    blockers = [
        clause
        for clause in consistency.split_clauses(text)
        if consistency.is_collaboration_blocker(clause)
    ]
    assert not blockers, "\n".join(blockers)


@pytest.mark.parametrize(
    "needle",
    [
        "DatasetKey",
        "MarketDataService",
        "continuous",
        "actual_dominant",
        "DataGap",
        "six hard validations",
        "auto_order=false",
        "一次性",
    ],
)
def test_data_core_contract_keeps_business_boundaries(needle: str) -> None:
    text = (ROOT / "docs/tasks/GY-DATA-CORE-V2.md").read_text(encoding="utf-8")
    assert needle in text


def test_task_readme_lists_four_dispositions() -> None:
    text = (ROOT / "docs/tasks/README.md").read_text(encoding="utf-8")
    for name in (
        "active_contract",
        "historical_fact",
        "frozen_runtime_consumed",
        "superseded_unreferenced",
    ):
        assert name in text
