#!/usr/bin/env python3
"""Tests for schema_validator.py — JSON Schema validation for V2 tasks and epics."""

import sys
import os
import json
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "ai" / "lib"))

import pytest


# Skip if jsonschema not installed
try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


from schema_validator import (
    extract_yaml_frontmatter,
    parse_yaml_frontmatter,
    validate_file,
    validate_task,
    validate_epic,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


# ---- YAML frontmatter extraction ----

def test_extract_yaml_frontmatter_present():
    content = """---
kind: Task
schema_version: "2.0"
task_id: "TEST-001"
status: DRAFT
risk_level: R3
work_level: L2
approval_scope: [plan]
---
# Task Title
"""
    result = extract_yaml_frontmatter(content)
    assert result is not None
    assert "kind: Task" in result


def test_extract_yaml_frontmatter_absent():
    content = """# No frontmatter
## Section
Some text.
"""
    result = extract_yaml_frontmatter(content)
    assert result is None


def test_extract_yaml_frontmatter_empty():
    content = """---
---
# Empty frontmatter
"""
    result = extract_yaml_frontmatter(content)
    # Empty frontmatter block may return None or empty string depending on parser
    # Both are acceptable — the real test is validate_file on a no-frontmatter file
    assert result is None or result.strip() == ""


# ---- Task validation ----

@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_valid_v2_task():
    valid_data = {
        "kind": "Task",
        "schema_version": "2.0",
        "task_id": "WS-V2-003",
        "status": "PLAN_READY",
        "risk_level": "R1",
        "work_level": "L2",
        "approval_scope": ["plan", "code"],
    }
    valid, errors = validate_task(valid_data)
    assert valid, f"Expected valid, got errors: {errors}"


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_missing_required_field():
    invalid_data = {
        "kind": "Task",
        "schema_version": "2.0",
        "task_id": "WS-V2-003",
        # Missing status, risk_level, work_level, approval_scope
    }
    valid, errors = validate_task(invalid_data)
    assert not valid
    assert len(errors) > 0


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_invalid_risk_level():
    invalid_data = {
        "kind": "Task",
        "schema_version": "2.0",
        "task_id": "WS-V2-003",
        "status": "DRAFT",
        "risk_level": "R5",  # Invalid
        "work_level": "L2",
        "approval_scope": ["plan"],
    }
    valid, errors = validate_task(invalid_data)
    assert not valid


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_invalid_status():
    invalid_data = {
        "kind": "Task",
        "schema_version": "2.0",
        "task_id": "WS-V2-003",
        "status": "INVALID_STATUS",
        "risk_level": "R3",
        "work_level": "L2",
        "approval_scope": ["plan"],
    }
    valid, errors = validate_task(invalid_data)
    assert not valid


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_empty_approval_scope():
    invalid_data = {
        "kind": "Task",
        "schema_version": "2.0",
        "task_id": "WS-V2-003",
        "status": "DRAFT",
        "risk_level": "R3",
        "work_level": "L2",
        "approval_scope": [],  # Empty, should fail minItems
    }
    valid, errors = validate_task(invalid_data)
    assert not valid


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_wrong_kind():
    data = {
        "kind": "Epic",
        "schema_version": "2.0",
        "task_id": "WS-V2-003",
        "status": "DRAFT",
        "risk_level": "R3",
        "work_level": "L2",
        "approval_scope": ["plan"],
    }
    valid, errors = validate_task(data)
    assert not valid


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_valid_v2_epic():
    valid_data = {
        "kind": "Epic",
        "schema_version": "2.0",
        "epic_id": "EXAMPLE-EPIC",
        "status": "EXECUTING",
        "risk_level": "R1",
        "tasks": ["T1", "T2"],
        "readiness_flags": {"flag_a": True, "flag_b": False},
    }
    valid, errors = validate_epic(valid_data)
    assert valid, f"Expected valid, got errors: {errors}"


# ---- File-level validation ----

@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_validate_sample_task_v2_file():
    task_file = FIXTURE_DIR / "sample_task_v2.md"
    assert task_file.exists(), f"Fixture not found: {task_file}"
    valid, errors = validate_file(str(task_file))
    assert valid, f"Expected valid task file, got errors: {errors}"


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_validate_sample_epic_v2_file():
    epic_file = FIXTURE_DIR / "sample_epic_v2.md"
    assert epic_file.exists(), f"Fixture not found: {epic_file}"
    valid, errors = validate_file(str(epic_file), epic_mode=True)
    assert valid, f"Expected valid epic file, got errors: {errors}"


def test_validate_file_no_frontmatter():
    """File without YAML frontmatter should fail validation."""
    task_file = FIXTURE_DIR / "old_task_L2.md"
    assert task_file.exists()
    valid, errors = validate_file(str(task_file))
    assert not valid
    assert any("No YAML frontmatter" in e for e in errors)


def test_validate_file_missing():
    valid, errors = validate_file("/nonexistent/file.md")
    assert not valid
    assert any("not found" in e for e in errors)
