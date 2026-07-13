#!/usr/bin/env python3
"""Tests for compat_reader.py — legacy task markdown → V2 dict conversion."""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "ai" / "lib"))

import pytest
from compat_reader import (
    parse_task_file,
    parse_legacy_task,
    extract_table_section,
    extract_task_id_from_filename,
)
from risk_resolver import RiskLevel
from status_machine import Status


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


# ---- Table extraction ----

def test_extract_table_section():
    content = """## 0. 元信息

| Key | Value |
|-----|-------|
| Task ID | TEST-001 |
| Status | DRAFT |

## 1. Next Section
"""
    table = extract_table_section(content)
    assert table is not None
    assert table.get("task id") == "TEST-001"
    assert table.get("status") == "DRAFT"


def test_extract_table_section_missing():
    content = """# No metadata section
## 1. Some section
"""
    table = extract_table_section(content)
    assert table is None


# ---- Filename extraction ----

def test_extract_task_id_from_filename():
    assert extract_task_id_from_filename("TASK-2026-07-11-002-lean-v1-demo.md") == "TASK-2026-07-11-002-lean-v1-demo"
    assert extract_task_id_from_filename("GUIYI-DEMO-001.md") == "GUIYI-DEMO-001"
    assert extract_task_id_from_filename("WS-V2-003.md") == "WS-V2-003"
    assert extract_task_id_from_filename("unknown.md") == "unknown"


# ---- Legacy task parsing ----

def test_parse_legacy_L2_task():
    """Parse old_task_L2.md and verify key fields."""
    task_file = FIXTURE_DIR / "old_task_L2.md"
    data = parse_task_file(str(task_file))

    assert data["task_id"] == "TASK-2026-07-11-002"
    assert data["status"] == Status.APPROVED.value
    assert data["work_level"] == "L2"
    assert data["github_issue"] == "#2"
    assert data["branch"] == "feature/lean-v1-demo"
    assert data["critical"] is False
    assert data["schema_version"] == "2.0"


def test_parse_legacy_L0_task():
    """Parse old_task_L0.md and verify it handles missing fields gracefully."""
    task_file = FIXTURE_DIR / "old_task_L0.md"
    data = parse_task_file(str(task_file))

    assert data["task_id"] == "TASK-L0-001"
    assert data["work_level"] == "L0"
    assert data["status"] == Status.PLAN_READY.value
    assert data["worktree"] == ""
    assert data["branch"] == ""
    # L0 tasks should still get default approval_scope
    assert "plan" in data["approval_scope"]


def test_parse_v2_yaml_task():
    """Parse sample_task_v2.md (YAML frontmatter) and verify all fields."""
    task_file = FIXTURE_DIR / "sample_task_v2.md"
    data = parse_task_file(str(task_file))

    assert data["task_id"] == "EXAMPLE-TASK-V2"
    assert data["schema_version"] == "2.0"
    assert data["status"] == "PLAN_READY"
    assert data["risk_level"] == "R2"
    assert data["work_level"] == "L2"
    assert "plan" in data["approval_scope"]
    assert "code" in data["approval_scope"]
    assert data["depends_on"] == ["EXAMPLE-001"]
    assert data["github_issue"] == "#99"
    assert "services/quant-api/tests/test_health.py" in data["allowed_paths"]
    assert "services/quant-api/app/main.py" in data["forbidden_paths"]
    assert data["model_profile"] == "standard"


def test_parse_v2_epic_file():
    """Parse sample_epic_v2.md and verify epic fields."""
    epic_file = FIXTURE_DIR / "sample_epic_v2.md"
    data = parse_task_file(str(epic_file))

    assert data["epic_id"] == "EXAMPLE-EPIC"
    assert data["kind"] == "Epic"
    assert data["status"] == "EXECUTING"
    assert data["risk_level"] == "R1"
    assert "EXAMPLE-TASK-V2" in data["tasks"]
    assert data["readiness_flags"]["example_flag_1"] is True
    assert data["readiness_flags"]["example_flag_2"] is False


def test_legacy_risk_inference():
    """Legacy task with strategies/ path should infer R1."""
    task_file = FIXTURE_DIR / "old_task_L2.md"
    data = parse_task_file(str(task_file))
    assert data["risk_level"] in ("R1", "R2", "R3")


def test_legacy_defaults():
    """Legacy tasks should get sensible defaults for missing V2 fields."""
    task_file = FIXTURE_DIR / "old_task_L2.md"
    data = parse_task_file(str(task_file))

    assert data["owner"] == "WorkBuddy"
    assert isinstance(data["depends_on"], list)
    assert isinstance(data["resource_locks"], list)
    assert isinstance(data["required_tests"], list)


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        parse_task_file("/nonexistent/file.md")


def test_approval_scope_default():
    """Tasks without explicit approval_scope should get [plan, code]."""
    task_file = FIXTURE_DIR / "old_task_L0.md"
    data = parse_task_file(str(task_file))
    assert "plan" in data["approval_scope"]
    assert "code" in data["approval_scope"]
