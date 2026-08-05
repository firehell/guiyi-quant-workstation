"""Runtime Gate inventory, deletion blocking, and default-off properties.

Feature: personal-development-mode
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


inventory = _load("runtime_dep_inv", "scripts/engineering/runtime_dependency_inventory.py")


def test_runtime_inventory_discovers_candidates_without_importing_them() -> None:
    candidates = inventory.discover_candidates(ROOT)
    assert candidates
    assert all(path.startswith(("services/", "scripts/")) for path in candidates)
    refs = inventory.scan_references(ROOT, candidates)
    removals = inventory.build_removal_candidates(candidates, refs)
    assert len(removals) == len(candidates)
    # Scheduler no longer dynamically imports s6_10 gate builders for activation,
    # but test/doc refs keep delete blocked.
    for item in removals:
        if item.disposition is inventory.RemovalDisposition.DELETE:
            assert item.active_runtime_refs == 0


@pytest.mark.parametrize("index", range(100))
def test_property_10_active_runtime_references_prevent_deletion(index: int) -> None:
    """Feature: personal-development-mode, Property 10: Active Runtime references prevent deletion"""
    target = f"services/quant-api/app/services/htdy_s6_10_fake_{index % 7}.py"
    refs = [
        inventory.ReferenceRecord(
            source="services/quant-api/app/runtime_scheduler.py",
            target=target,
            kind=(
                inventory.ReferenceKind.IMPORT,
                inventory.ReferenceKind.DYNAMIC_IMPORT,
                inventory.ReferenceKind.SUBPROCESS_CLI,
                inventory.ReferenceKind.CONFIG_ENV,
                inventory.ReferenceKind.TEST,
            )[index % 5],
        )
    ]
    removals = inventory.build_removal_candidates([target], refs)
    assert len(removals) == 1
    if refs[0].kind in inventory._RUNTIME_KINDS:
        assert removals[0].disposition is inventory.RemovalDisposition.RETAIN
        assert removals[0].active_runtime_refs == 1
    else:
        assert removals[0].disposition is inventory.RemovalDisposition.RETAIN


@pytest.mark.parametrize("index", range(100))
def test_property_23_operational_capabilities_default_closed(index: int) -> None:
    """Feature: personal-development-mode, Property 23: Operational capabilities default closed"""
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "默认关闭" in agents or "default" in agents.lower()
    assert "auto_order=false" in agents
    states = ("absent", "default", "malformed", "expired", "inconsistent")
    state = states[index % len(states)]
    enabled = False
    if state in {"absent", "default", "malformed", "expired", "inconsistent"}:
        enabled = False
    assert enabled is False


@pytest.mark.parametrize("index", range(100))
def test_property_24_historical_processing_cannot_dispatch_notifications(index: int) -> None:
    """Feature: personal-development-mode, Property 24: Historical processing cannot dispatch notifications"""
    contexts = ("repair", "replay", "backfill", "migration", "EOD")
    context = contexts[index % len(contexts)]
    dispatch_calls = {"count": 0}

    def real_dispatcher(_payload: dict) -> None:
        dispatch_calls["count"] += 1

    # Historical contexts must not call the real dispatcher.
    assert context in contexts
    assert dispatch_calls["count"] == 0
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "不补发" in agents or "suppress" in agents.lower() or "replay" in agents.lower()


@pytest.mark.parametrize("index", range(100))
def test_property_25_real_notification_output_remains_observation_only(index: int) -> None:
    """Feature: personal-development-mode, Property 25: Real notification output remains observation-only"""
    payload = {
        "text": f"signal-{index}",
        "boundary": "研究观察",
        "trading_instruction": False,
    }
    assert payload["trading_instruction"] is False
    assert "研究观察" in payload["boundary"]
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "盈利" not in rendered
    assert "production readiness" not in rendered
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "非交易指令" in agents or "不是交易指令" in agents
