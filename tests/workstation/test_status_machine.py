#!/usr/bin/env python3
"""Tests for status_machine.py — 17-state transitions, permissions, and validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "ai" / "lib"))

import pytest
from status_machine import (
    Status,
    is_valid_transition,
    is_terminal,
    is_interrupt,
    is_gate,
    allowed_stages,
    can_execute_stage,
    map_legacy_status,
    map_to_legacy,
    valid_targets,
    check_approval_scope_for_dev,
    LEGACY_TO_V2,
    TERMINAL_STATES,
)


# ---- Status enum ----

def test_all_17_statuses():
    assert len(Status) == 17


def test_terminal_states():
    assert Status.CLOSED in TERMINAL_STATES
    assert Status.CANCELLED in TERMINAL_STATES
    assert Status.SKIPPED_NOT_APPLICABLE in TERMINAL_STATES
    assert Status.SKIPPED_WITH_REASON in TERMINAL_STATES


# ---- Valid transitions ----

def test_forward_main_line():
    """Test the main forward transition chain."""
    assert is_valid_transition(Status.DRAFT, Status.REQUIREMENT_READY)
    assert is_valid_transition(Status.REQUIREMENT_READY, Status.PLAN_READY)
    assert is_valid_transition(Status.PLAN_READY, Status.APPROVED)
    assert is_valid_transition(Status.APPROVED, Status.EXECUTING)
    assert is_valid_transition(Status.EXECUTING, Status.TESTING)
    assert is_valid_transition(Status.TESTING, Status.REVIEWING)
    assert is_valid_transition(Status.REVIEWING, Status.DELIVERY_READY)
    assert is_valid_transition(Status.DELIVERY_READY, Status.CLOSED)


def test_failure_recovery():
    """Test failure → replan → plan_ready chain."""
    assert is_valid_transition(Status.EXECUTING, Status.FAILED)
    assert is_valid_transition(Status.FAILED, Status.REPLAN)
    assert is_valid_transition(Status.REPLAN, Status.PLAN_READY)


def test_skip_paths():
    """Test skip-from-draft paths."""
    assert is_valid_transition(Status.DRAFT, Status.SKIPPED_NOT_APPLICABLE)
    assert is_valid_transition(Status.DRAFT, Status.SKIPPED_WITH_REASON)


def test_cancellation_from_any():
    """Test that cancellation is allowed from many states."""
    assert is_valid_transition(Status.PLAN_READY, Status.CANCELLED)
    assert is_valid_transition(Status.EXECUTING, Status.CANCELLED)
    assert is_valid_transition(Status.TESTING, Status.CANCELLED)
    assert is_valid_transition(Status.FAILED, Status.CANCELLED)


def test_block_recovery():
    """Test blocked states can recover."""
    assert is_valid_transition(Status.BLOCKED, Status.EXECUTING)
    assert is_valid_transition(Status.BLOCKED, Status.PLAN_READY)
    assert is_valid_transition(Status.BLOCKED_BY_DEPENDENCY, Status.APPROVED)


def test_terminal_no_transitions():
    """Terminal states should have no valid outgoing transitions (except self)."""
    for ts in TERMINAL_STATES:
        targets = valid_targets(ts)
        assert len(targets) == 0, f"{ts.value} should have no valid targets, got {targets}"


def test_invalid_transitions():
    """Test some clearly invalid transitions."""
    assert not is_valid_transition(Status.CLOSED, Status.EXECUTING)
    assert not is_valid_transition(Status.DRAFT, Status.CLOSED)
    assert not is_valid_transition(Status.PLAN_READY, Status.EXECUTING)  # Skip APPROVED
    assert not is_valid_transition(Status.CANCELLED, Status.DRAFT)


def test_noop_transition():
    """Same state should always be valid (no-op)."""
    for s in Status:
        assert is_valid_transition(s, s)


# ---- Stage permissions ----

def test_stage_permissions_draft():
    stages = allowed_stages(Status.DRAFT)
    assert "plan" in stages
    assert "dev" not in stages


def test_stage_permissions_approved():
    stages = allowed_stages(Status.APPROVED)
    assert "dev" in stages
    assert "fix" in stages
    assert "plan" not in stages


def test_stage_permissions_testing():
    assert can_execute_stage(Status.TESTING, "test")
    assert not can_execute_stage(Status.TESTING, "dev")


def test_stage_permissions_terminal():
    for ts in TERMINAL_STATES:
        assert allowed_stages(ts) == set(), f"{ts.value} should have no allowed stages"


# ---- is_* helpers ----

def test_is_terminal():
    assert is_terminal(Status.CLOSED)
    assert not is_terminal(Status.EXECUTING)


def test_is_interrupt():
    assert is_interrupt(Status.BLOCKED)
    assert is_interrupt(Status.FAILED)
    assert not is_interrupt(Status.DRAFT)


def test_is_gate():
    assert is_gate(Status.PLAN_READY)
    assert is_gate(Status.APPROVED)
    assert not is_gate(Status.EXECUTING)


# ---- Legacy mapping ----

def test_legacy_mapping():
    assert map_legacy_status("IDEA") == Status.DRAFT
    assert map_legacy_status("APPROVED_DEV") == Status.APPROVED
    assert map_legacy_status("CODING") == Status.EXECUTING
    assert map_legacy_status("PAUSED") == Status.BLOCKED


def test_legacy_mapping_unknown():
    with pytest.raises(ValueError):
        map_legacy_status("UNKNOWN_STATUS")


def test_map_to_legacy():
    assert map_to_legacy(Status.DRAFT) == "IDEA"
    assert map_to_legacy(Status.APPROVED) == "APPROVED_DEV"
    assert map_to_legacy(Status.EXECUTING) == "CODING"


def test_legacy_mapping_coverage():
    """Verify all 12 legacy statuses have valid V2 mappings."""
    assert len(LEGACY_TO_V2) == 12


# ---- approval_scope checks ----

def test_approval_scope_r0_requires_external_review():
    err = check_approval_scope_for_dev("R0", ["plan", "code"], "dev")
    assert err is None  # R0 dev requires code, which is present

    err = check_approval_scope_for_dev("R0", ["plan", "code"], "review")
    assert err is not None
    assert "external_review" in err


def test_approval_scope_r1_requires_code():
    err = check_approval_scope_for_dev("R1", ["plan"], "dev")
    assert err is not None
    assert "code" in err


def test_approval_scope_r3_no_requirements():
    err = check_approval_scope_for_dev("R3", ["plan"], "dev")
    assert err is None


def test_approval_scope_r2_production_write():
    err = check_approval_scope_for_dev("R2", ["plan", "code"], "result")
    assert err is None  # R2 has no requirement for result stage
