#!/usr/bin/env python3
"""Tests for epic_manager.py — Epic readiness_flags management."""

import sys
import os
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "ai" / "lib"))

import pytest
from epic_manager import EpicManager, EpicData


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def temp_results_dir():
    """Create a temporary results directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def epic_manager(temp_results_dir):
    """Create an EpicManager with a temp directory."""
    return EpicManager(str(temp_results_dir / "TEST-EPIC"))


# ---- Basic operations ----

def test_initial_state_empty(epic_manager):
    assert epic_manager.all_flags_ready() is True
    assert epic_manager.get_unready_flags() == []


def test_set_flag(epic_manager):
    changed = epic_manager.set_flag("test_flag", True)
    assert changed is True
    assert epic_manager.get_flag("test_flag") is True


def test_set_flag_no_change(epic_manager):
    epic_manager.set_flag("test_flag", True)
    changed = epic_manager.set_flag("test_flag", True)
    assert changed is False  # No change


def test_set_flag_toggle(epic_manager):
    epic_manager.set_flag("test_flag", True)
    changed = epic_manager.set_flag("test_flag", False)
    assert changed is True
    assert epic_manager.get_flag("test_flag") is False


def test_set_flags_batch(epic_manager):
    changed = epic_manager.set_flags_batch({
        "flag_a": True,
        "flag_b": True,
        "flag_c": False,
    })
    assert changed == 3
    assert epic_manager.get_flag("flag_a") is True
    assert epic_manager.get_flag("flag_c") is False


# ---- Readiness checks ----

def test_all_flags_ready_true(epic_manager):
    epic_manager.set_flags_batch({"a": True, "b": True})
    assert epic_manager.all_flags_ready() is True


def test_all_flags_ready_false(epic_manager):
    epic_manager.set_flags_batch({"a": True, "b": False})
    assert epic_manager.all_flags_ready() is False


def test_get_unready_flags(epic_manager):
    epic_manager.set_flags_batch({"a": True, "b": False, "c": True, "d": False})
    unready = epic_manager.get_unready_flags()
    assert "b" in unready
    assert "d" in unready
    assert "a" not in unready


# ---- Summary ----

def test_get_flags_summary(epic_manager):
    epic_manager.set_flags_batch({"a": True, "b": False})
    summary = epic_manager.get_flags_summary()

    assert summary["epic_id"] == "TEST-EPIC"
    assert summary["total"] == 2
    assert summary["ready_count"] == 1
    assert summary["all_ready"] is False


# ---- Immutable log ----

def test_log_created(epic_manager):
    epic_manager.set_flag("logged_flag", True, source="test_log_created")
    assert epic_manager.log_file.exists()

    lines = epic_manager.log_file.read_text().strip().split("\n")
    assert len(lines) >= 1

    last_entry = json.loads(lines[-1])
    assert last_entry["flag"] == "logged_flag"
    assert last_entry["new_value"] is True
    assert last_entry["source"] == "test_log_created"


def test_log_records_old_value(epic_manager):
    epic_manager.set_flag("toggle_flag", False, source="initial")
    epic_manager.set_flag("toggle_flag", True, source="toggle")

    lines = epic_manager.log_file.read_text().strip().split("\n")
    assert len(lines) >= 2

    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["old_value"] is None  # First set
    assert first["new_value"] is False
    assert second["old_value"] is False
    assert second["new_value"] is True


# ---- Persistence ----

def test_flags_persisted(epic_manager, temp_results_dir):
    epic_manager.set_flags_batch({"x": True, "y": False})

    # Create a new manager pointing to the same directory
    mgr2 = EpicManager(str(temp_results_dir / "TEST-EPIC"))
    assert mgr2.get_flag("x") is True
    assert mgr2.get_flag("y") is False


# ---- Epic file parsing ----

def test_parse_epic_file(temp_results_dir):
    epic_file = FIXTURE_DIR / "sample_epic_v2.md"
    mgr = EpicManager(
        str(temp_results_dir / "EXAMPLE-EPIC"),
        epic_file=str(epic_file),
    )

    assert mgr.epic_data is not None
    assert mgr.epic_data.epic_id == "EXAMPLE-EPIC"
    assert mgr.epic_data.risk_level == "R1"

    # Flags from epic file should sync
    assert mgr.get_flag("example_flag_1") is True
    assert mgr.get_flag("example_flag_2") is False


def test_parse_epic_file_no_yaml(temp_results_dir):
    """Epic file without YAML frontmatter should still parse gracefully."""
    # Create a minimal epic without YAML
    epic_file = temp_results_dir / "minimal_epic.md"
    epic_file.write_text("# Minimal Epic\n\nNo YAML here.\n")

    mgr = EpicManager(
        str(temp_results_dir / "MINIMAL-EPIC"),
        epic_file=str(epic_file),
    )
    # Should not crash
    assert mgr.epic_data is not None


# ---- Edge cases ----

def test_get_nonexistent_flag(epic_manager):
    assert epic_manager.get_flag("nonexistent") is None


def test_empty_batch(epic_manager):
    changed = epic_manager.set_flags_batch({})
    assert changed == 0


def test_concurrent_flag_sets(epic_manager):
    """Multiple rapid flag sets should all be recorded."""
    for i in range(5):
        epic_manager.set_flag(f"flag_{i}", True)

    # All should be true
    for i in range(5):
        assert epic_manager.get_flag(f"flag_{i}") is True

    # Log should have 5 entries
    lines = epic_manager.log_file.read_text().strip().split("\n")
    assert len(lines) == 5
